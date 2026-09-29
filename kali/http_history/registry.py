"""Shared source-address -> capture-context registry (SQLite, WAL).

Written by the MCP process that leases a namespace; read by the mitmproxy addon
to correlate a flow with the execution that produced it. Deliberately ordered
by ``source_ip`` (unique) rather than a time window or command order.

Since #238 the same row also carries the run's serialized ``TrafficPolicy``: the
governor lives in the PROXY process, so the policy has to cross that process
boundary through the one channel that already identifies a lease's traffic - its
source address. ``lookup()`` keeps returning the pre-#238 two-tuple;
``lookup_registration()`` is the additive, policy-aware form.
"""
from __future__ import annotations

import json
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


@dataclass(frozen=True)
class SourceRegistration:
    """Everything the proxy knows about one leased source address.

    `traffic_policy` is the canonical `traffic-policy/v2` payload (already
    validated at the exec boundary), or None for a capture-only lease.
    """

    project_id: str
    capture_context: CaptureContext
    traffic_policy: dict | None = None


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
        for column in ("derived_from", "replay_kind", "traffic_policy"):
            if column not in columns:
                self._conn.execute(f"ALTER TABLE leases ADD COLUMN {column} TEXT")

    def register(
        self,
        source_ip: str,
        project_id: str,
        context: CaptureContext,
        *,
        traffic_policy: dict | None = None,
        ttl_s: int = DEFAULT_TTL_S,
        now: float | None = None,
    ) -> None:
        now = time.time() if now is None else now
        policy_json = json.dumps(traffic_policy) if traffic_policy is not None else None
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO leases "
                "(source_ip, project_id, session_id, run_id, spec_id, variant_ref,"
                " exec_id, derived_from, replay_kind, traffic_policy, created_at,"
                " expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    policy_json,
                    now,
                    now + max(0, ttl_s),
                ),
            )

    def lookup_registration(
        self, source_ip: str, *, now: float | None = None
    ) -> SourceRegistration | None:
        """The #238 form of `lookup`: project, capture context AND policy.

        Returns None for an unknown or expired source, exactly like `lookup`.
        A row whose stored policy is unreadable is still returned, with
        `traffic_policy=None`: the capture correlation is independent of it, and
        the governor refuses to enforce anything it cannot parse.
        """
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
        return SourceRegistration(
            project_id=row["project_id"],
            capture_context=self._context_from_row(row, source_ip=source_ip),
            traffic_policy=self._policy_from_row(row),
        )

    @staticmethod
    def _context_from_row(row, *, source_ip: str | None = None) -> CaptureContext:
        return CaptureContext(
            session_id=row["session_id"] or "",
            run_id=row["run_id"] or "",
            spec_id=row["spec_id"] or "",
            variant_ref=row["variant_ref"] or "",
            exec_id=row["exec_id"] or "",
            derived_from=row["derived_from"],
            replay_kind=row["replay_kind"],
            source_ip=source_ip,
        )

    @staticmethod
    def _policy_from_row(row) -> dict | None:
        raw = row["traffic_policy"]
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

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
        context = self._context_from_row(row, source_ip=source_ip)
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
                context=self._context_from_row(row),
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
