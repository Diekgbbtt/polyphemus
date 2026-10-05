"""Unit tier: the module-lifecycle HTTP surface (#118/#121) - pause/resume/drain.

These handlers expose the runtime manager's lifecycle verbs over the wire so an
operator (and the e2e tier) can drive the runtime plane against the live agent.
The handlers are thin adapters: they route to `runtime.pause/resume/drain` and
map errors to status codes, exactly like the launch/stop handlers.

Pattern follows the #122 wiring-test style: a REAL RuntimeManager on a real
asyncio.Runner thread (never a mocked loop), modules registered, driven through
the FastAPI TestClient. The app module cannot be imported in unit tests (it
imports the LLM gateway seam at module scope), so the router is mounted on a
fresh FastAPI app.
"""
import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import polymerhus.project_management.api as api_mod
from polymerhus.project_management import repository
from polymerhus.project_management.api import router

app = FastAPI()
app.include_router(router)


@pytest.fixture
def runtime():
    from polymerhus.app.runtime import RuntimeManager

    rm = RuntimeManager()
    rm.start()
    rm.register_module("recon")
    rm.register_module("analysis")
    rm.register_module("hunting")
    try:
        yield rm
    finally:
        rm.shutdown()


def _post(client, module, verb):
    return client.post(f"/projects/p1/modules/{module}/{verb}")


def _wait_until(pred, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def test_pause_resume_analysis_toggles_state(runtime):
    with TestClient(app) as client:
        r = _post(client, "analysis", "pause")
        assert r.status_code == 200
        assert r.json() == {"module": "analysis", "state": "paused"}
        assert runtime.state("analysis").value == "paused"
        r = _post(client, "analysis", "resume")
        assert r.status_code == 200
        assert r.json() == {"module": "analysis", "state": "running"}


def test_pause_isolates_analysis_recon_keeps_running(runtime):
    with TestClient(app) as client:
        _post(client, "recon", "pause")
        assert runtime.state("recon").value == "paused"
        assert runtime.state("analysis").value == "running"
        assert runtime.state("hunting").value == "running"


def test_drain_settles_module_to_stopped(runtime):
    with TestClient(app) as client:
        r = _post(client, "analysis", "drain")
        assert r.status_code == 200
        assert r.json()["state"] == "stopped"
        assert runtime.state("analysis").value == "stopped"


def test_resume_of_non_paused_is_a_safe_noop(runtime):
    with TestClient(app) as client:
        r = _post(client, "recon", "resume")
        assert r.status_code == 200
        assert r.json() == {"module": "recon", "state": "running"}


def test_unknown_module_404s(runtime):
    with TestClient(app) as client:
        for verb in ("pause", "resume", "drain"):
            r = client.post("/projects/p1/modules/exploit/pause")
            assert r.status_code == 404


def test_lifecycle_verbs_fail_closed_without_active_runtime():
    from polymerhus.app import runtime as runtime_mod

    saved = runtime_mod.get_active_runtime()
    runtime_mod._ACTIVE_RUNTIME = None
    try:
        with TestClient(app) as client:
            r = _post(client, "recon", "pause")
            assert r.status_code == 503
    finally:
        runtime_mod._ACTIVE_RUNTIME = saved


def test_recon_launch_after_a_drain_is_admitted_not_503(runtime, monkeypatch):
    """#328 regression: drain settles recon to `stopped`; the next launch must
    repair the module and be admitted - never a 503 admission refusal."""
    monkeypatch.setattr(repository, "validate_launch", lambda project_id, jobs: None)
    monkeypatch.setattr(repository, "open_run", lambda project_id: "run-after-drain")

    async def fake_run_pipeline(project_id, *, run_id, job_subset=None, **kw):
        await asyncio.sleep(0.2)
        return None

    monkeypatch.setattr(api_mod, "run_pipeline", fake_run_pipeline)

    with TestClient(app) as client:
        r = _post(client, "recon", "drain")
        assert r.status_code == 200
        assert r.json()["state"] == "stopped"

        r = client.post("/projects/p1/recon", json={"jobs": None})
        assert r.status_code == 200, r.text
        assert r.json() == {"run_id": "run-after-drain"}

        _wait_until(lambda: runtime.has_run("recon", "run-after-drain"), 5)
        runtime.cancel_run("recon", "run-after-drain")


def test_recon_launch_during_shutdown_window_is_a_503_not_a_500(runtime, monkeypatch):
    """#328 fix-pass regression: in the shutdown window the active runtime is
    still published while its worker loop is already cleared, so `ensure_running`
    raises `RuntimeLoopNotRunning`. The launch must map that to a clean 503 -
    never an unhandled 500."""
    from polymerhus.app.runtime import ModuleState

    monkeypatch.setattr(repository, "validate_launch", lambda project_id, jobs: None)
    monkeypatch.setattr(repository, "open_run", lambda project_id: "run-shutdown")

    runtime.drain("recon", timeout=5)
    assert runtime.state("recon") == ModuleState.STOPPED

    saved_loop = runtime._loop
    runtime._loop = None
    try:
        with TestClient(app) as client:
            r = client.post("/projects/p1/recon", json={"jobs": None})
            assert r.status_code == 503, r.text
            assert "not running" in r.json()["detail"]
    finally:
        runtime._loop = saved_loop


def test_analysis_launch_after_a_drain_is_admitted_not_503(runtime, monkeypatch):
    """#332 regression: drain settles analysis to `stopped`; the next analysis
    launch must repair the module and be admitted - never a 503 admission
    refusal. Covers the API-only entrypoint; the combined recon launch calls the
    same `start_analysis` seam one step later."""
    from polymerhus.analysis.feed import get_feed
    from polymerhus.app.clients import pg

    monkeypatch.setattr(pg, "get_run", lambda run_id: {"run_id": run_id})
    monkeypatch.setattr(pg, "create_analysis_run", lambda *a, **k: None)
    monkeypatch.setattr(pg, "set_analysis_run_status", lambda *a, **k: None)

    with TestClient(app) as client:
        r = _post(client, "analysis", "drain")
        assert r.status_code == 200
        assert r.json()["state"] == "stopped"

        r = client.post("/projects/p1/analysis", json={"run_id": "analysis-after-drain"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] == "analysis-after-drain"
        assert body["analysis_run_id"]

        _wait_until(lambda: runtime.has_run("analysis", "analysis-after-drain"), 5)
        # drain the (empty) consumer with the terminal marker so its supervisor
        # settles and the module registry empties - no leaked consumer task.
        feed = get_feed("analysis-after-drain")
        assert feed is not None
        runtime.call(feed.signal_end()).result(timeout=5)


def test_analysis_launch_during_shutdown_window_is_a_503_not_a_500(runtime, monkeypatch):
    """#332 fix-pass regression, the analysis arm of #328: in the shutdown
    window the active runtime is still published while its worker loop is
    already cleared, so the analysis revive cannot be delivered and
    `RuntimeLoopNotRunning` is raised. The launch must map that to a clean 503,
    never an unhandled 500."""
    from polymerhus.app.clients import pg

    monkeypatch.setattr(pg, "get_run", lambda run_id: {"run_id": run_id})

    saved_loop = runtime._loop
    runtime._loop = None
    try:
        with TestClient(app) as client:
            r = client.post(
                "/projects/p1/analysis", json={"run_id": "run-shutdown"}
            )
            assert r.status_code == 503, r.text
            assert "not running" in r.json()["detail"]
    finally:
        runtime._loop = saved_loop


def test_launch_into_paused_module_is_a_503_not_a_500(runtime, monkeypatch):
    """The #118 contract: `schedule` is refused while a module is paused. The
    operator-intent surface must say *why* with a clean 503 - an unhandled
    ModuleAdmissionRefused (500) would be a leak."""
    from polymerhus.app.clients import pg

    monkeypatch.setattr(pg, "get_run", lambda run_id: {"run_id": run_id})
    with TestClient(app) as client:
        _post(client, "analysis", "pause")
        r = client.post("/projects/p1/analysis", json={"run_id": "any-run"})
        assert r.status_code == 503
        assert "not accepting new work" in r.json()["detail"]
