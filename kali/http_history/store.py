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
from pathlib import Path

from kali.http_history.models import SCHEMA_VERSION, HttpArtifact

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

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
CREATE INDEX IF NOT EXISTS attributes_text
    ON attributes (side, namespace, key, text_value);
CREATE INDEX IF NOT EXISTS attributes_numeric
    ON attributes (side, namespace, key, numeric_value);
CREATE VIRTUAL TABLE IF NOT EXISTS flows_fts USING fts5 (
    artifact_id UNINDEXED,
    url,
    markers
);
"""


class ArtifactImmutableError(RuntimeError):
    """Raised when a record attempts to overwrite an existing artifact id."""


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
        self._migrate()

    # --- schema ---------------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
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

    def close(self) -> None:
        with self._lock:
            self._conn.close()


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
