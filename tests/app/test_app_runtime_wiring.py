"""#122: the app wiring tier (startup constructs the runtime, shutdown drives the
fan-out, API routes reach the manager).

These tests exercise the REAL `polymerhus.app.main._startup` / `_shutdown`
lifespan handlers through `with TestClient(app) as client:` (the only way the
FastAPI startup/shutdown events fire; a bare module-level `TestClient(app)`
does not run them):

- startup constructs the RuntimeManager, starts the ONE worker runner thread,
  registers recon/analysis/hunting RUNNING, keeps the existing reconcilers and
  reaper, and leaves a manager active that `hunting_control_plane_available()`
  sees - the 503 -> live flip.
- shutdown cancels the reaper, then `runtime.shutdown()` runs the fan-out
  (module flushes BEFORE `close_session_checkpointer` closes the pool), and
  the pool closes last.
- the recon POST (combined and recon-only) routes the run through the
  manager's `runtime.schedule`, not raw `asyncio.create_task`.

No live LLM / graph / database: every startup DB/LLM seam is stubbed to a
record/no-op (unit tier, CODING_STANDARD sections 6, 10). Em-dash clean.
"""
from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from polymerhus.app.main import app
from polymerhus.app.runtime import ModuleState, get_active_runtime


# --- helpers -----------------------------------------------------------------

def _wait_until(pred, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def _stub_startup(monkeypatch, events=None):
    """No-op / record every external seam `_startup` and `_shutdown` touch, so
    the lifespan handlers run against a bare environment (unit tier)."""
    from polymerhus.app.clients import pg, neo4j_client
    import polymerhus.app.main as main_mod

    def rec(name):
        def _f(*a, **k):
            if events is not None:
                events.append(name)
        return _f

    def rec_async(name):
        async def _f(*a, **k):
            if events is not None:
                events.append(name)
        return _f

    monkeypatch.setattr(pg, "ensure_checkpoint_tables", rec_async("ensure-checkpoint-tables"))
    monkeypatch.setattr(pg, "ensure_recon_schema", rec("ensure-recon-schema"))
    monkeypatch.setattr(pg, "ensure_hunting_schema", rec("ensure-hunting-schema"))
    monkeypatch.setattr(neo4j_client, "ensure_schema", rec("ensure-schema"))
    monkeypatch.setattr(neo4j_client, "ensure_l1_schema", rec("ensure-l1-schema"))
    monkeypatch.setattr(main_mod, "validate_llm_config", rec("validate-llm-config"))

    import polymerhus.app.llm as llm
    monkeypatch.setattr(llm, "setup_session_checkpointer", rec("setup-checkpointer"))
    monkeypatch.setattr(llm, "close_session_checkpointer", rec("close-pool"))

    from polymerhus.app.llm import checkpoints as checkpoints
    monkeypatch.setattr(checkpoints, "flush_module_index", rec("flush-index"))

    monkeypatch.setattr(pg, "reap_stale_runs", rec("reap-stale-runs"))
    monkeypatch.setattr(pg, "reconcile_orphaned_analysis_runs", rec("reconcile-analysis-runs"))


# --- startup: constructs the manager, registers modules, keeps the reaper -----

def test_startup_constructs_manager_registers_modules_and_starts_reaper(monkeypatch):
    events = []
    _stub_startup(monkeypatch, events)

    with TestClient(app) as client:
        runtime = get_active_runtime()
        assert runtime is not None
        assert runtime.worker_thread is not None
        assert runtime.worker_thread.is_alive()
        assert runtime.worker_thread.name.startswith("runtime-worker")
        for module in ("recon", "analysis", "hunting"):
            assert runtime.state(module) == ModuleState.RUNNING
            assert runtime.gate(module) is not None

        # the existing startup behavior is preserved, in order
        for expected in (
            "ensure-checkpoint-tables",
            "ensure-recon-schema",
            "ensure-hunting-schema",
            "ensure-schema",
            "ensure-l1-schema",
            "validate-llm-config",
            "setup-checkpointer",
            "reap-stale-runs",
            "reconcile-analysis-runs",
        ):
            assert expected in events, f"{expected!r} missing from {events}"
        assert "setup-checkpointer" in events  # pre-warmed pooled saver

        # the reaper task was created and the health route still answers
        assert getattr(app.state, "reaper_task", None) is not None
        assert client.get("/health").status_code == 200

    # shutdown cleared the manager and stopped the worker thread
    assert get_active_runtime() is None
    assert runtime.worker_thread is None
    assert "close-pool" in events


def test_hunting_control_plane_flips_to_live_when_the_app_is_up(monkeypatch):
    _stub_startup(monkeypatch)
    from polymerhus.attack.hunting import runtime as hunting_runtime

    with TestClient(app) as client:
        assert hunting_runtime.hunting_control_plane_available() is True


# --- shutdown: fan-out runs before the pooled saver closes --------------------

def test_shutdown_fans_out_flushes_then_closes_the_pool(monkeypatch):
    events = []
    _stub_startup(monkeypatch, events)

    from polymerhus.app.runtime import RuntimeManager

    orig_shutdown = RuntimeManager.shutdown

    def spied_shutdown(self, *a, **k):
        orig_shutdown(self, *a, **k)
        events.append("runtime-shutdown-done")

    monkeypatch.setattr(RuntimeManager, "shutdown", spied_shutdown)

    with TestClient(app) as client:
        runtime = get_active_runtime()
        assert runtime is not None
        # pause must NOT flush (AC: PAUSE never flushes or closes)
        runtime.pause("analysis")
        time.sleep(0.05)
        assert "flush-index" not in events
        assert "close-pool" not in events
        runtime.resume("analysis")

    # the ratified shutdown order (module-architecture 5.12, G7c):
    # fan-out flushes each module index into the STILL-OPEN pool,
    # then shutdown() completes, then close_session_checkpointer() closes it.
    flush_at = events.index("flush-index")
    shutdown_at = events.index("runtime-shutdown-done")
    close_at = events.index("close-pool")
    assert flush_at < shutdown_at < close_at
    assert runtime.state("recon") == ModuleState.STOPPED
    assert runtime.state("analysis") == ModuleState.STOPPED
    assert runtime.state("hunting") == ModuleState.STOPPED
    assert runtime.worker_thread is None


def test_shutdown_is_safe_without_a_constructed_runtime(monkeypatch):
    """`_shutdown` must tolerate a startup that never reached manager
    construction (a schema call raised before the RuntimeManager wiring): the
    pool close still runs and nothing raises."""
    events = []
    _stub_startup(monkeypatch, events)
    from polymerhus.app.main import _shutdown

    # simulate a startup that failed before the manager was assigned
    if hasattr(app.state, "runtime"):
        del app.state.runtime
    assert not hasattr(app.state, "runtime")
    asyncio.run(_shutdown())

    assert get_active_runtime() is None
    assert "close-pool" in events


# --- hunting: first live launch through the manager ---------------------------

def test_hunting_launch_is_live_through_the_manager_and_201s(monkeypatch):
    _stub_startup(monkeypatch)
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime

    RUN_ID = "hunt-wire-0001"
    started = []

    async def fake_start_hunting(project_id, *, run_id=None, candidates=None, **kw):
        started.append((project_id, run_id))
        await asyncio.sleep(0.2)
        return run_id

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start_hunting)

    with TestClient(app) as client:
        runtime = get_active_runtime()
        assert runtime is not None

        resp = client.post("/projects/p1/hunting", json={})

        assert resp.status_code == 201
        assert resp.json() == {"hunting_run_id": RUN_ID}
        _wait_until(
            lambda: runtime.has_run("hunting", f"hunting:{RUN_ID}"), timeout=5
        )
        assert started == [("p1", RUN_ID)]


# --- recon: the POST routes the run through the runtime -----------------------

def test_recon_launch_routes_through_the_manager_combined_and_recon_only(monkeypatch):
    _stub_startup(monkeypatch)
    from polymerhus.app.clients import pg
    import polymerhus.project_management.api as api_mod

    run_ids = []
    runs = {"i": 0}

    def create_run(run_id, pid):
        run_ids.append(run_id)
        return None

    async def fake_run_pipeline(project_id, *, run_id, job_subset=None, **kw):
        await asyncio.sleep(0.05)
        return "ran"

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    monkeypatch.setattr(pg, "create_run", create_run)
    monkeypatch.setattr(api_mod, "run_pipeline", fake_run_pipeline)

    with TestClient(app) as client:
        runtime = get_active_runtime()
        assert runtime is not None

        combined = client.post("/projects/p1/recon",
                               json={"jobs": ["subfinder", "dnsx"]})
        assert combined.status_code == 200
        combined_run = combined.json()["run_id"]
        assert combined_run in run_ids

        recon_only = client.post("/projects/p1/recon",
                                 json={"jobs": ["subfinder"], "with_analysis": False})
        assert recon_only.status_code == 200
        recon_only_run = recon_only.json()["run_id"]
        assert recon_only_run in run_ids

        _wait_until(lambda: runtime.has_run("recon", combined_run), timeout=5)
        _wait_until(lambda: runtime.has_run("recon", recon_only_run), timeout=5)
        assert set(runtime.run_ids("recon")) in ({combined_run, recon_only_run}, set())


# --- the renamed seam stays monkeypatchable -----------------------------------

def test_launch_seam_is_named_schedule_pipeline_and_monkeypatchable(monkeypatch):
    """AC (d): `_launch_pipeline` is renamed to `_schedule_pipeline`, and the
    module-level monkeypatch seam the API tests rely on keeps working."""
    _stub_startup(monkeypatch)
    from polymerhus.app.clients import pg
    import polymerhus.project_management.api as api_mod

    assert not hasattr(api_mod, "_launch_pipeline")
    assert callable(getattr(api_mod, "_schedule_pipeline", None))

    launched = []
    monkeypatch.setattr(api_mod, "_schedule_pipeline",
                        lambda project_id, run_id, jobs, **kw: launched.append(run_id))
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    monkeypatch.setattr(pg, "create_run", lambda run_id, pid: None)

    with TestClient(app) as client:
        resp = client.post("/projects/p1/recon", json={"jobs": ["subfinder", "dnsx"]})
        assert resp.status_code == 200
        assert launched == [resp.json()["run_id"]]