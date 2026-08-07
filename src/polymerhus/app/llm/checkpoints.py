"""The process-wide backing store for stateful agent sessions (#94).

Every stateful agent (`stateful_turn`, `session.py`) resumes from a checkpoint. This
module owns ONE process-wide, POOLED, persistent checkpointer that ALL stateful agents
share - the analysis proposers, the concurrent recon pods, and the hunts - each holding
a DISTINCT `thread_id` (from its `SessionAddress`) in that one store. A pooled
`PostgresSaver` is required, not a single connection: up to `MAX_PODS` recon pods run
their stateful agents CONCURRENTLY, so the checkpointer must serve concurrent threads
safely (each op borrows a pooled connection) - a single shared connection would race,
and a per-agent connection would thrash `setup()` and exhaust Postgres.

Lifecycle (wired in `app/main.py`):
  startup  -> `setup_session_checkpointer()`  opens the pool + `PostgresSaver`, `setup()`.
  runtime  -> `get_session_checkpointer()`     returns the shared saver (every call site).
  shutdown -> `close_session_checkpointer()`   closes the pool.

Fail-open: with no DSN (tests / a bare environment) or if Postgres cannot be opened,
`get_session_checkpointer()` returns a shared in-process `InMemorySaver` - a stateful
agent still works, its memory just does not persist beyond the process.

Importing this module performs no I/O and opens no connection (CODING_STANDARD section
6): the pool and saver classes are imported lazily inside `setup`, never at import.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# The process-wide pooled saver (set by setup), its pool, and the in-process fallback.
_saver = None
_pool = None
_fallback = None
_lock = threading.Lock()

# Pool sizing: enough for the concurrent recon pods (MAX_PODS) plus the serialized
# analysis/hunt agents, with headroom. Kept modest so a run never exhausts Postgres.
_POOL_MAX = 24


def setup_session_checkpointer(dsn: str | None = None) -> None:
    """Open the process-wide pooled `PostgresSaver` at app startup (idempotent).

    Resolves `dsn` (or the app `POSTGRES_DSN`); with none, leaves the store unset so
    `get_session_checkpointer` serves the in-process fallback. Fail-open: any failure to
    open Postgres logs and leaves the fallback in place rather than blocking startup."""
    global _saver, _pool
    with _lock:
        if _saver is not None:
            return
        resolved = dsn
        if resolved is None:
            try:
                from polymerhus.app.config import config as app_config
                resolved = getattr(app_config, "POSTGRES_DSN", None)
            except Exception:  # noqa: BLE001
                resolved = None
        if not resolved:
            logger.warning("session checkpointer: no POSTGRES_DSN; stateful agent "
                           "memory will not persist (in-process fallback)")
            return
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                resolved, max_size=_POOL_MAX, open=True,
                # PostgresSaver requires autocommit + dict rows; prepare_threshold=0
                # avoids server-side prepared-statement churn across pooled conns.
                kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
            )
            saver = PostgresSaver(pool)
            saver.setup()  # idempotent DDL
            _pool, _saver = pool, saver
            logger.info("session checkpointer: pooled PostgresSaver open (max_size=%d)", _POOL_MAX)
        except Exception as exc:  # noqa: BLE001 - never block startup on it
            logger.warning("session checkpointer: could not open pooled Postgres (%s); "
                           "stateful agent memory degraded to in-process", exc)


def get_session_checkpointer():
    """The shared checkpointer every stateful agent uses. The pooled `PostgresSaver`
    once `setup_session_checkpointer` has run; otherwise a process-wide in-process
    `InMemorySaver` (tests / no-DSN) so a stateful turn still works, non-persistently."""
    if _saver is not None:
        return _saver
    global _fallback
    if _fallback is None:
        with _lock:
            if _fallback is None:
                from langgraph.checkpoint.memory import InMemorySaver
                _fallback = InMemorySaver()
    return _fallback


def close_session_checkpointer() -> None:
    """Close the pool at app shutdown (idempotent)."""
    global _saver, _pool
    with _lock:
        if _pool is not None:
            try:
                _pool.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("session checkpointer: pool close failed (%s)", exc)
        _saver = None
        _pool = None
