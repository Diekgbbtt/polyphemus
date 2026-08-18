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
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
