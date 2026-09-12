"""Shared source-address -> capture-context registry (SQLite, WAL).

Written by the MCP process that leases a namespace; read by the mitmproxy addon
to correlate a flow with the execution that produced it. Deliberately ordered
by ``source_ip`` (unique) rather than a time window or command order.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from kali.http_history.models import CaptureContext

DEFAULT_TTL_S = 900

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leases (
    source_ip TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT,
    run_id TEXT,
    spec_id TEXT,
    variant_ref TEXT,
    exec_id TEXT,
    derived_from TEXT,
    replay_kind TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""


@dataclass(frozen=True)
class LeaseRecord:
    source_ip: str
    project_id: str
    context: CaptureContext
    created_at: float
    expires_at: float


class SourceRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._migrate_columns()

    def _migrate_columns(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(leases)").fetchall()
        }
        for column in ("derived_from", "replay_kind"):
            if column not in columns:
                self._conn.execute(f"ALTER TABLE leases ADD COLUMN {column} TEXT")

    def register(
        self,
        source_ip: str,
        project_id: str,
        context: CaptureContext,
        *,
        ttl_s: int = DEFAULT_TTL_S,
        now: float | None = None,
    ) -> None:
        now = time.time() if now is None else now
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO leases "
                "(source_ip, project_id, session_id, run_id, spec_id, variant_ref,"
                " exec_id, derived_from, replay_kind, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_ip,
                    project_id,
                    context.session_id,
                    context.run_id,
                    context.spec_id,
                    context.variant_ref,
                    context.exec_id,
                    context.derived_from,
                    context.replay_kind,
                    now,
                    now + max(0, ttl_s),
                ),
            )

    def lookup(self, source_ip: str, *, now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM leases WHERE source_ip=?", (source_ip,)
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now:
            self.release(source_ip)
            return None
        context = CaptureContext(
            session_id=row["session_id"] or "",
            run_id=row["run_id"] or "",
            spec_id=row["spec_id"] or "",
            variant_ref=row["variant_ref"] or "",
            exec_id=row["exec_id"] or "",
            derived_from=row["derived_from"],
            replay_kind=row["replay_kind"],
            source_ip=source_ip,
        )
        return row["project_id"], context

    def release(self, source_ip: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM leases WHERE source_ip=?", (source_ip,))

    def leases(self, *, now: float | None = None) -> list[LeaseRecord]:
        now = time.time() if now is None else now
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM leases WHERE expires_at > ? ORDER BY created_at",
                (now,),
            ).fetchall()
        return [
            LeaseRecord(
                source_ip=row["source_ip"],
                project_id=row["project_id"],
                context=CaptureContext(
                    session_id=row["session_id"] or "",
                    run_id=row["run_id"] or "",
                    spec_id=row["spec_id"] or "",
                    variant_ref=row["variant_ref"] or "",
                    exec_id=row["exec_id"] or "",
                    derived_from=row["derived_from"],
                    replay_kind=row["replay_kind"],
                ),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
            )
            for row in rows
        ]

    def cleanup_expired(self, *, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM leases WHERE expires_at <= ?", (now,))
        return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
