"""Per-project artifact store: SQLite (WAL) metadata + content-addressed blobs.

Layout::

    <root>/<project_id>/http-history/history.sqlite3
    <root>/<project_id>/http-history/bodies/<sha256>.blob

Bodies are written atomically *before* the record that references them, so a
crash can orphan a blob but can never leave a record pointing at nothing. A
record, once committed, is immutable.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, field
from pathlib import Path

from kali.http_history.models import SCHEMA_VERSION, HttpArtifact

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

ALLOWED_SIDES = frozenset({"request", "response", "connection", "context", "timing"})
ALLOWED_NAMESPACES = frozenset({"core", "header", "cookie", "query", "form", "body", "tls"})
ALLOWED_OPS = frozenset({"eq", "contains", "prefix", "gte", "lte"})
MIN_LIMIT, MAX_LIMIT = 1, 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flows (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    schema_version TEXT NOT NULL,
    derived_from TEXT,
    replay_kind TEXT,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS flows_created ON flows (created_at, artifact_id);
CREATE INDEX IF NOT EXISTS flows_derived ON flows (derived_from);
CREATE TABLE IF NOT EXISTS bodies (
    sha256 TEXT PRIMARY KEY,
    size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS attributes (
    artifact_id TEXT NOT NULL,
    side TEXT NOT NULL,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    text_value TEXT,
    numeric_value REAL
);
CREATE INDEX IF NOT EXISTS attributes_artifact ON attributes (artifact_id);
CREATE INDEX IF NOT EXISTS attributes_text_cov
    ON attributes (side, namespace, key, text_value, artifact_id);
CREATE INDEX IF NOT EXISTS attributes_numeric_cov
    ON attributes (side, namespace, key, numeric_value, artifact_id);
CREATE VIRTUAL TABLE IF NOT EXISTS flows_fts USING fts5 (
    artifact_id UNINDEXED,
    url,
    markers
);
"""


class ArtifactImmutableError(RuntimeError):
    """Raised when a record attempts to overwrite an existing artifact id."""


@dataclass
class SearchPage:
    artifacts: list[HttpArtifact] = field(default_factory=list)
    next_cursor: str | None = None


class HttpHistoryStore:
    def __init__(self, root: str | Path, project_id: str):
        if not _PROJECT_ID_RE.match(project_id or ""):
            raise ValueError(
                f"invalid project_id {project_id!r}: must match "
                r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
            )
        self.project_id = project_id
        self.root = Path(root)
        self.directory = self.root / project_id / "http-history"
        self.bodies_dir = self.directory / "bodies"
        self.db_path = self.directory / "history.sqlite3"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.bodies_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Due processi scrivono lo stesso file di progetto (l'addon registra,
        # il MCP purga/fa retention): senza busy_timeout il secondo incassa un
        # "database is locked" immediato invece di attendere il writer.
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    # --- schema ---------------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            # hardening #196: i due indici non covering restano su file
            # esistenti finche non li si rimuove; il rimpiazzo covering e gia
            # creato da _SCHEMA. DROP IF EXISTS e un no-op sui file nuovi.
            self._conn.execute("DROP INDEX IF EXISTS attributes_text")
            self._conn.execute("DROP INDEX IF EXISTS attributes_numeric")
            existing = self._conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (SCHEMA_VERSION,),
                )
            elif existing["value"] != SCHEMA_VERSION:
                raise RuntimeError(
                    "http-history schema-version mismatch: store has "
                    f"{existing['value']!r}, code expects {SCHEMA_VERSION!r}; "
                    "no automatic destructive rebuild is performed"
                )

    # --- writes ---------------------------------------------------------------

    def record(self, artifact: HttpArtifact, bodies: dict[str, bytes] | None = None) -> None:
        """Persist ``artifact`` after making every referenced body durable."""
        with self._lock:
            if self._conn.execute(
                "SELECT 1 FROM flows WHERE artifact_id=?", (artifact.artifact_id,)
            ).fetchone():
                raise ArtifactImmutableError(
                    f"artifact {artifact.artifact_id} already exists and is immutable"
                )
            for ref, content in (bodies or {}).items():
                self._write_body(ref, content)
            for ref in _referenced_refs(artifact):
                if not self._body_exists(ref):
                    raise ValueError(f"referenced body {ref} is not durable")
            try:
                self._insert_record(artifact)
                self._insert_attributes(artifact)
                self._insert_fts(artifact)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _insert_record(self, artifact: HttpArtifact) -> None:
        self._conn.execute(
            "INSERT OR ABORT INTO flows "
            "(artifact_id, project_id, created_at, schema_version, derived_from,"
            " replay_kind, record_json) VALUES (?,?,?,?,?,?,?)",
            (
                artifact.artifact_id,
                self.project_id,
                artifact.created_at,
                artifact.schema_version,
                artifact.derived_from,
                artifact.replay_kind,
                artifact.model_dump_json(),
            ),
        )

    def _insert_attributes(self, artifact: HttpArtifact) -> None:
        from kali.http_history.index import project_attributes

        for row in project_attributes(artifact, self.get_body):
            self._conn.execute(
                "INSERT INTO attributes "
                "(artifact_id, side, namespace, key, text_value, numeric_value) "
                "VALUES (?,?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    row.side,
                    row.namespace,
                    row.key,
                    row.text_value,
                    row.numeric_value,
                ),
            )

    def _insert_fts(self, artifact: HttpArtifact) -> None:
        from kali.http_history.index import fts_document

        url, markers = fts_document(artifact, self.get_body)
        self._conn.execute(
            "INSERT INTO flows_fts (artifact_id, url, markers) VALUES (?,?,?)",
            (artifact.artifact_id, url, markers),
        )

    def _write_body(self, body_ref: str, content: bytes) -> None:
        digest = _digest_of(body_ref)
        target = self.bodies_dir / f"{digest}.blob"
        if target.exists():
            return
        tmp = self.bodies_dir / f".{digest}.tmp{os.getpid()}"
        tmp.write_bytes(content)
        os.replace(tmp, target)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO bodies (sha256, size) VALUES (?,?)",
                (digest, len(content)),
            )

    # --- reads ----------------------------------------------------------------

    def get_raw(self, artifact_id: str) -> HttpArtifact | None:
        row = self._conn.execute(
            "SELECT record_json FROM flows WHERE artifact_id=? AND project_id=?",
            (artifact_id, self.project_id),
        ).fetchone()
        if row is None:
            return None
        return HttpArtifact.model_validate_json(row["record_json"])

    def get_body(self, body_ref: str | None) -> bytes | None:
        if not body_ref:
            return None
        target = self.bodies_dir / f"{_digest_of(body_ref)}.blob"
        if not target.exists():
            return None
        return target.read_bytes()

    def _body_exists(self, body_ref: str) -> bool:
        return (self.bodies_dir / f"{_digest_of(body_ref)}.blob").exists()

    def status(self) -> dict:
        count = self._conn.execute("SELECT COUNT(*) AS n FROM flows").fetchone()["n"]
        blob_count = len(list(self.bodies_dir.glob("*.blob")))
        total_bytes = sum(p.stat().st_size for p in self.bodies_dir.glob("*.blob"))
        writable = os.access(self.directory, os.W_OK)
        return {
            "ok": bool(writable),
            "project_id": self.project_id,
            "path": str(self.directory),
            "schema_version": SCHEMA_VERSION,
            "artifact_count": count,
            "body_count": blob_count,
            "body_bytes": total_bytes,
            "writable": writable,
        }

    # --- search ---------------------------------------------------------------

    def search(
        self,
        filters: list[dict] | None = None,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> SearchPage:
        """Conjunctive attribute search, ordered by ``(created_at, artifact_id)``."""
        self._validate_limit(limit)
        where, params = self._filter_sql(filters or [])
        return self._page(where, params, cursor=cursor, limit=limit)

    def text_search(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> SearchPage:
        """FTS over the URL and textual body markers."""
        self._validate_limit(limit)
        phrase = '"' + (query or "").replace('"', '""') + '"'
        sql = (
            "SELECT f.record_json, f.created_at, f.artifact_id FROM flows f "
            "WHERE f.artifact_id IN "
            "(SELECT artifact_id FROM flows_fts WHERE flows_fts MATCH ?) "
            "AND f.project_id = ?"
        )
        params: list[object] = [phrase, self.project_id]
        sql, params = self._append_cursor(sql, params, cursor)
        sql += " ORDER BY f.created_at ASC, f.artifact_id ASC LIMIT ?"
        params.append(limit + 1)
        rows = self._conn.execute(sql, params).fetchall()
        return self._page_from_rows(rows, limit)

    def _page(
        self, where: str, params: list[object], *, cursor: str | None, limit: int
    ) -> SearchPage:
        sql = (
            "SELECT f.record_json, f.created_at, f.artifact_id FROM flows f "
            f"WHERE f.project_id = ? {where}"
        )
        all_params: list[object] = [self.project_id, *params]
        sql, all_params = self._append_cursor(sql, all_params, cursor)
        sql += " ORDER BY f.created_at ASC, f.artifact_id ASC LIMIT ?"
        all_params.append(limit + 1)
        rows = self._conn.execute(sql, all_params).fetchall()
        return self._page_from_rows(rows, limit)

    def _page_from_rows(self, rows, limit: int) -> SearchPage:
        artifacts = [HttpArtifact.model_validate_json(row["record_json"]) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit and rows:
            last = rows[limit - 1]
            next_cursor = _encode_cursor(last["created_at"], last["artifact_id"])
        return SearchPage(artifacts=artifacts, next_cursor=next_cursor)

    def _append_cursor(
        self, sql: str, params: list[object], cursor: str | None
    ) -> tuple[str, list[object]]:
        if cursor:
            created_at, artifact_id = _decode_cursor(cursor)
            sql += " AND (f.created_at > ? OR (f.created_at = ? AND f.artifact_id > ?))"
            params.extend([created_at, created_at, artifact_id])
        return sql, params

    def _filter_sql(self, filters: list[dict]) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        for raw in filters:
            side = str(raw.get("side", ""))
            namespace = str(raw.get("namespace", ""))
            key = str(raw.get("key", ""))
            op = str(raw.get("op", "eq"))
            value = raw.get("value")
            if side not in ALLOWED_SIDES:
                raise ValueError(f"unknown side {side!r}")
            if namespace not in ALLOWED_NAMESPACES:
                raise ValueError(f"unknown namespace {namespace!r}")
            if op not in ALLOWED_OPS:
                raise ValueError(f"unknown op {op!r}")
            if namespace == "header":
                key = key.lower()
            clause, clause_params = _op_sql(op, value)
            clauses.append(
                "EXISTS (SELECT 1 FROM attributes a WHERE a.artifact_id = f.artifact_id "
                "AND a.side = ? AND a.namespace = ? AND a.key = ? AND " + clause + ")"
            )
            params.extend([side, namespace, key, *clause_params])
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        return where, params

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or not (MIN_LIMIT <= limit <= MAX_LIMIT):
            raise ValueError(f"limit must be an integer in [{MIN_LIMIT}, {MAX_LIMIT}], got {limit!r}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def optimize(self) -> None:
        """Refresh the query planner statistics (SQLite ANALYZE)."""
        with self._lock:
            self._conn.execute("ANALYZE")

    # --- retention / purge -----------------------------------------------------

    def purge_older_than(self, retention_s: int, *, now: float | None = None) -> int:
        """Delete artifacts older than ``retention_s`` and GC their blobs."""
        cutoff = (now if now is not None else time.time()) - max(0, retention_s)
        removed = self._delete_where("created_at < ?", (cutoff,))
        self._audit("retention", removed, cutoff)
        return removed

    def enforce_project_max_bytes(self, max_bytes: int) -> int:
        """Evict oldest artifacts until the stored body bytes fit ``max_bytes``."""
        removed = 0
        while max_bytes > 0 and self._body_bytes() > max_bytes:
            row = self._conn.execute(
                "SELECT artifact_id FROM flows ORDER BY created_at ASC, artifact_id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                break
            removed += self._delete_where("artifact_id = ?", (row["artifact_id"],))
        self._audit("project-byte-cap", removed, float(max_bytes))
        return removed

    def purge(self) -> dict:
        """Remove every row and blob for this project (used by project purge)."""
        removed = self._delete_where("1 = 1", ())
        self._audit("project-purge", removed, 0.0)
        return {"artifacts_removed": removed, "bodies_removed": self._gc_blobs()}

    def _delete_where(self, where: str, params: tuple) -> int:
        with self._lock, self._conn:
            rows = self._conn.execute(
                f"SELECT artifact_id FROM flows WHERE {where}", params
            ).fetchall()
            ids = [row["artifact_id"] for row in rows]
            for artifact_id in ids:
                self._conn.execute("DELETE FROM attributes WHERE artifact_id=?", (artifact_id,))
                self._conn.execute("DELETE FROM flows_fts WHERE artifact_id=?", (artifact_id,))
                self._conn.execute("DELETE FROM flows WHERE artifact_id=?", (artifact_id,))
        self._gc_blobs()
        return len(ids)

    def _body_bytes(self) -> int:
        row = self._conn.execute("SELECT COALESCE(SUM(size), 0) AS n FROM bodies").fetchone()
        return int(row["n"] or 0)

    def _gc_blobs(self) -> int:
        """Delete blobs no live record references (content-addressed dedup)."""
        with self._lock:
            referenced: set[str] = set()
            for row in self._conn.execute("SELECT record_json FROM flows"):
                artifact = HttpArtifact.model_validate_json(row["record_json"])
                if artifact.request.body_ref:
                    referenced.add(_digest_of(artifact.request.body_ref))
                if artifact.response is not None and artifact.response.body_ref:
                    referenced.add(_digest_of(artifact.response.body_ref))
            removed = 0
            for blob in self.bodies_dir.glob("*.blob"):
                if blob.stem not in referenced:
                    blob.unlink(missing_ok=True)
                    removed += 1
            with self._conn:
                for row in self._conn.execute("SELECT sha256 FROM bodies").fetchall():
                    if row["sha256"] not in referenced:
                        self._conn.execute(
                            "DELETE FROM bodies WHERE sha256=?", (row["sha256"],)
                        )
        return removed

    def _audit(self, reason: str, removed: int, threshold: float) -> None:
        payload = json.dumps(
            {
                "reason": reason,
                "artifacts_removed": removed,
                "threshold": threshold,
                "at": time.time(),
            }
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_purge', ?)",
                (payload,),
            )

    def last_purge(self) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='last_purge'"
        ).fetchone()
        return None if row is None else row["value"]


def _op_sql(op: str, value: object) -> tuple[str, list[object]]:
    if op == "eq":
        if isinstance(value, bool):
            raise ValueError("eq does not accept booleans")
        if isinstance(value, (int, float)):
            return "a.numeric_value = ?", [float(value)]
        return "a.text_value = ?", [str(value)]
    if op == "contains":
        return "a.text_value LIKE ?", [f"%{value}%"]
    if op == "prefix":
        return "a.text_value LIKE ?", [f"{value}%"]
    if op == "gte":
        return "a.numeric_value >= ?", [float(value)]
    if op == "lte":
        return "a.numeric_value <= ?", [float(value)]
    raise ValueError(f"unknown op {op!r}")


def _encode_cursor(created_at: float, artifact_id: str) -> str:
    raw = json.dumps([created_at, artifact_id]).encode("utf-8")
    return urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[float, str]:
    try:
        created_at, artifact_id = json.loads(urlsafe_b64decode(cursor.encode("ascii")))
        return float(created_at), str(artifact_id)
    except Exception as exc:  # noqa: BLE001 - a bad cursor is a caller error
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


def _digest_of(body_ref: str) -> str:
    return body_ref.split(":", 1)[1] if ":" in body_ref else body_ref


def _referenced_refs(artifact: HttpArtifact) -> list[str]:
    refs = []
    if artifact.request.body_ref:
        refs.append(artifact.request.body_ref)
    if artifact.response is not None and artifact.response.body_ref:
        refs.append(artifact.response.body_ref)
    return refs


def write_body_blob(body_bytes: bytes) -> tuple[str, bytes]:
    """Return ``("sha256:<hex>", body_bytes)`` for a candidate body."""
    import hashlib

    return f"sha256:{hashlib.sha256(body_bytes).hexdigest()}", body_bytes
