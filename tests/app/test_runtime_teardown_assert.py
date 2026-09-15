"""Unit tier: the teardown assert + loud-drop surfaces (#211, TD-1..TD-4, TD-6).

`flush -> assert -> teardown`: the module settle runs the flush, INSPECTS its typed
result, records any drop on the handle + logs it, and only THEN marks the module
`stopped`. The registered flush hook is the primary resolution; the
`flush_module_index` fallback serves hook-less modules; `ShutdownFanOut` records
each module's flush. The drain HTTP surface carries the flush result so the eval
harness / operator can assert `dropped == 0` machine-readably (no prose report).

Real RuntimeManager on a real asyncio.Runner thread; the flush target is a fake
(no DB). CODING_STANDARD sections 6, 10.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from polymerhus.app.llm.checkpoints import FlushResult
from polymerhus.app.runtime import ModuleState, RuntimeManager
from polymerhus.project_management.api import router

app = FastAPI()
app.include_router(router)


@pytest.fixture
def runtime():
    rm = RuntimeManager()
    rm.start()
    try:
        yield rm
    finally:
        rm.shutdown()


def _clean(archived: int = 0) -> FlushResult:
    return FlushResult(committed=archived, archived=archived, dropped=0,
                       dropped_thread_ids=[])


# --- C6: the assert gate - flush result inspected BEFORE `stopped` --------------

def test_settle_records_a_drop_and_logs_it_before_stopped(runtime, caplog):
    hook = lambda: FlushResult(  # noqa: E731
        committed=2, archived=1, dropped=1, dropped_thread_ids=["hunting:r:pod:1"])
    runtime.register_module("hunting", hooks={"flush": hook})

    runtime.drain("hunting", timeout=5)

    assert runtime.state("hunting") is ModuleState.STOPPED
    recorded = runtime.handle("hunting").last_flush
    assert recorded is not None
    assert recorded.dropped == 1
    assert recorded.dropped_thread_ids == ["hunting:r:pod:1"]
    assert any(
        "flush dropped 1/2 committed thread(s) before teardown" in r.message
        for r in caplog.records
    )


def test_settle_clean_flush_records_no_drop(runtime, caplog):
    hook = lambda: _clean(archived=3)  # noqa: E731
    runtime.register_module("analysis", hooks={"flush": hook})

    runtime.drain("analysis", timeout=5)

    assert runtime.state("analysis") is ModuleState.STOPPED
    recorded = runtime.handle("analysis").last_flush
    assert recorded is not None
    assert recorded.archived == 3 and recorded.dropped == 0
    assert not any("flush dropped" in r.message for r in caplog.records)


def test_settle_flush_hook_raising_never_breaks_teardown(runtime, caplog):
    def hook():
        raise RuntimeError("hook exploded")

    runtime.register_module("recon", hooks={"flush": hook})

    runtime.drain("recon", timeout=5)   # must not raise; fail-open preserved

    assert runtime.state("recon") is ModuleState.STOPPED
    recorded = runtime.handle("recon").last_flush
    assert recorded is not None         # degraded, never null (P3)
    assert recorded.to_dict() == {
        "committed": 0, "archived": 0, "dropped": 0,
        "dropped_thread_ids": [], "cause": "hook-raised",
    }


def test_settle_flush_hook_returning_nothing_degrades_loudly(runtime, caplog):
    runtime.register_module("recon", hooks={"flush": lambda: None})

    runtime.drain("recon", timeout=5)   # must not raise; fail-open preserved

    assert runtime.state("recon") is ModuleState.STOPPED
    recorded = runtime.handle("recon").last_flush
    assert recorded is not None
    assert recorded.cause == "no-result"


# --- C8: registered hook primary, flush_module_index fallback -------------------

def test_flush_module_resolves_registered_hook_over_fallback(runtime):
    seen = []

    def hunting_hook():
        seen.append("hook")
        return _clean()

    runtime.register_module("hunting", hooks={"flush": hunting_hook})
    runtime.register_module("recon")   # hook-less: falls back to flush_module_index

    runtime.drain("hunting", timeout=5)
    runtime.drain("recon", timeout=5)

    assert seen == ["hook"]            # the registered hook, not the fallback
    assert runtime.handle("recon").last_flush is not None   # fallback produced a result


# --- C12: the shutdown fan-out records every module's flush ----------------------

def test_shutdown_fanout_records_each_modules_flush(runtime):
    order = []
    runtime.register_module("recon", hooks={"flush": lambda: (order.append("recon"), _clean())[1]})
    runtime.register_module("analysis", hooks={"flush": lambda: (order.append("analysis"), _clean())[1]})
    runtime.register_module("hunting", hooks={"flush": lambda: (order.append("hunting"), _clean())[1]})

    runtime.shutdown()

    assert order == ["recon", "analysis", "hunting"]
    assert runtime.handle("recon").last_flush is not None
    assert runtime.handle("analysis").last_flush is not None
    assert runtime.handle("hunting").last_flush is not None


# --- C10: the drain HTTP surface carries the flush result -----------------------

def _post(client, module, verb):
    return client.post(f"/projects/p1/modules/{module}/{verb}")


def test_drain_response_carries_the_flush_result(runtime):
    hook = lambda: FlushResult(  # noqa: E731
        committed=4, archived=3, dropped=1, dropped_thread_ids=["hunting:r:pod:9"])
    runtime.register_module("hunting", hooks={"flush": hook})

    with TestClient(app) as client:
        r = _post(client, "hunting", "drain")
        assert r.status_code == 200
        body = r.json()
        assert body["module"] == "hunting"
        assert body["state"] == "stopped"
        assert body["flush"] == {
            "committed": 4,
            "archived": 3,
            "dropped": 1,
            "dropped_thread_ids": ["hunting:r:pod:9"],
            "cause": None,
        }
        assert runtime.state("hunting").value == "stopped"


def test_drain_response_reports_clean_flush(runtime):
    runtime.register_module("analysis", hooks={"flush": lambda: _clean(archived=2)})
    with TestClient(app) as client:
        r = _post(client, "analysis", "drain")
        body = r.json()
        assert body["flush"]["archived"] == 2
        assert body["flush"]["dropped"] == 0


def test_drain_response_is_never_null_before_any_flush(runtime):
    runtime.register_module("recon")    # never drained, never shut down
    runtime.handle("recon").state = ModuleState.STOPPED   # already stopped: settle skipped
    with TestClient(app) as client:
        r = _post(client, "recon", "drain")
        assert r.status_code == 200
        assert r.json()["flush"] == {
            "committed": 0, "archived": 0, "dropped": 0,
            "dropped_thread_ids": [], "cause": "never-flushed",
        }