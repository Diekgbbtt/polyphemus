"""Unit tier: the halt-everything shutdown ordering (#211, TD-6/TD-7/TD-10, P7b).

`main._shutdown` runs flush (runtime walk, then the guaranteed single bulk
`flush_all_indexes`) strictly BEFORE the pool closes, then releases the sole
persistent outbound handle (neo4j driver) - fail-open throughout, never raises.
"""
from __future__ import annotations

import asyncio


def test_shutdown_flushes_before_pool_close_then_releases_handles(monkeypatch):
    import polymerhus.app.llm as llm_pkg
    import polymerhus.app.llm.checkpoints as checkpoints
    import polymerhus.app.main as main
    from polymerhus.app.clients import neo4j_client

    order = []

    class _FakeRuntime:
        def shutdown(self):
            order.append("runtime.shutdown")

    def fake_flush_all():
        order.append("flush_all_indexes")
        return {}

    def fake_close_pool():
        order.append("close_session_checkpointer")

    monkeypatch.setattr(checkpoints, "flush_all_indexes", fake_flush_all)
    monkeypatch.setattr(llm_pkg, "close_session_checkpointer", fake_close_pool)
    monkeypatch.setattr(neo4j_client, "close",
                        lambda: order.append("neo4j.close"))
    monkeypatch.setattr(main.app.state, "runtime", _FakeRuntime(), raising=False)

    asyncio.run(main._shutdown())   # must not raise

    assert order == [
        "runtime.shutdown",
        "flush_all_indexes",
        "close_session_checkpointer",
        "neo4j.close",
    ]


def test_shutdown_bulk_flush_drop_is_logged_loudly(monkeypatch, caplog):
    import polymerhus.app.llm as llm_pkg
    import polymerhus.app.llm.checkpoints as checkpoints
    import polymerhus.app.main as main
    from polymerhus.app.clients import neo4j_client

    class _FakeRuntime:
        def shutdown(self):
            pass

    monkeypatch.setattr(
        checkpoints, "flush_all_indexes",
        lambda: {"hunting": checkpoints.FlushResult(
            committed=1, archived=0, dropped=1,
            dropped_thread_ids=["hunting:r:t9"])},
    )
    monkeypatch.setattr(llm_pkg, "close_session_checkpointer", lambda: None)
    monkeypatch.setattr(neo4j_client, "close", lambda: None)
    monkeypatch.setattr(main.app.state, "runtime", _FakeRuntime(), raising=False)

    with caplog.at_level("WARNING", logger="polymerhus.app.main"):
        asyncio.run(main._shutdown())

    assert any("bulk flush dropped 1/1" in r.message and "hunting:r:t9" in r.message
               for r in caplog.records)
