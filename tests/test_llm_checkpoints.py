"""Unit tier: the process-wide stateful-session checkpointer provider (#94).

`checkpoints.py` owns ONE pooled, persistent checkpointer shared by every stateful agent.
Without Postgres (tests / a bare environment) it must fail-open to a shared in-process
saver so a stateful turn still works, and its lifecycle calls must be idempotent. The
pooled-Postgres path itself is a live-tier concern (needs a real DB) and is not exercised
here (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

from polymerhus.app.llm import checkpoints as C


def test_fallback_is_a_shared_saver_when_postgres_absent(monkeypatch):
    """No DSN -> `get_session_checkpointer` returns a usable in-process saver, and the
    SAME instance every call (one shared store, distinct threads within it)."""
    # ensure a clean, un-setup state
    C.close_session_checkpointer()
    monkeypatch.setattr(C, "_fallback", None)
    cp1 = C.get_session_checkpointer()
    cp2 = C.get_session_checkpointer()
    assert cp1 is cp2                       # shared singleton
    assert hasattr(cp1, "get_tuple") and hasattr(cp1, "put")  # a real checkpointer


def test_setup_is_idempotent_and_noops_without_dsn(monkeypatch):
    """`setup_session_checkpointer` with no resolvable DSN leaves the store unset (the
    fallback serves), and calling it twice never raises."""
    C.close_session_checkpointer()
    monkeypatch.setattr(C, "_saver", None)

    import polymerhus.app.config as cfg
    monkeypatch.setattr(cfg.config, "POSTGRES_DSN", "", raising=False)

    C.setup_session_checkpointer()          # no DSN -> no-op, no raise
    C.setup_session_checkpointer()          # idempotent
    # still serves the in-process fallback
    assert C.get_session_checkpointer() is not None


def test_close_is_idempotent():
    C.close_session_checkpointer()
    C.close_session_checkpointer()          # second close never raises
