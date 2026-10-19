"""#110/T5: the hunting seam endpoints (seam contract 3.3) - whole-pipeline
launch, singular component launches, per-session pause/resume/stop, stop,
status. No live PG / control plane: the gateway accessors, the marshalling
harness, and the runtime presence are faked. The 503 fail-closed launch is the
real surface while `polymerhus.app.runtime` has not landed."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from polymerhus.app.clients import pg
from polymerhus.app.main import app

client = TestClient(app)

RUN_ID = "rt-hunt-0001"


def _row(status: str = "running"):
    return {
        "hunting_run_id": RUN_ID, "project_id": "p1", "status": status,
        "started_at": None, "finished_at": None,
    }


class _FakeRuntime:
    """The stand-in for `polymerhus.app.runtime` once the control plane lands.
    `run_ids` is the registry the T4 stop path enumerates (`stop_hunting`
    cancels every session of the run by id)."""

    def __init__(self):
        self.scheduled: list[str] = []
        self.cancelled: list[str] = []
        self.held: list[str] = []
        self.resumed: list[str] = []
        self.ensured: list[str] = []

    def ensure_running(self, module: str) -> None:
        self.ensured.append(module)

    def schedule(self, module: str, coro, *, name: str) -> object:
        self.scheduled.append(name)
        # consume the coroutine so pytest never reports it as un-awaited
        asyncio.create_task(coro)
        return coro

    def cancel_run(self, module: str, run_id: str) -> None:
        self.cancelled.append(run_id)

    def hold_session(self, module: str, run_id: str) -> None:
        self.held.append(run_id)

    def resume_session(self, module: str, run_id: str) -> None:
        self.resumed.append(run_id)

    def run_ids(self, module: str) -> list[str]:
        return list(self.scheduled)


class _FakeHuntingRows:
    """The stateful faked `hunting_runs` row surface: `create_hunting_run` mints
    rows the `list_hunting_runs` guard and the orphan closer observe, so a
    replay against an already-created live run id is refusable like the live
    gateway would."""

    def __init__(self, *, seeded_running: tuple[str, ...] = ()):
        self.rows: dict[str, dict] = {
            rid: {"hunting_run_id": rid, "project_id": "p1", "status": "running",
                  "started_at": None, "finished_at": None}
            for rid in seeded_running
        }
        self.status_writes: list[tuple[str, str]] = []

    def create_hunting_run(self, project_id: str) -> str:
        rid = RUN_ID if not self.rows else f"{RUN_ID}-{len(self.rows)}"
        self.rows[rid] = {
            "hunting_run_id": rid, "project_id": project_id, "status": "running",
            "started_at": None, "finished_at": None,
        }
        return rid

    def set_hunting_run_status(self, hunting_run_id: str, status: str, *,
                               stats: dict | None = None) -> None:
        self.status_writes.append((hunting_run_id, status))
        row = self.rows.get(hunting_run_id)
        if row is not None:
            row["status"] = status

    def list_hunting_runs(self, project_id: str) -> list[dict]:
        return [
            r for r in self.rows.values() if r["project_id"] == project_id
        ]

    def get_hunting_run(self, hunting_run_id: str) -> dict | None:
        return self.rows.get(hunting_run_id)


def _patch_control_plane(monkeypatch, runtime=None):
    """Patch BOTH runtime getters the surface consults onto the same fake: the
    hunting module's `_app_runtime` (the launch + orchestrator-pass gates) and
    the SHARED `polymerhus.app.runtime.get_active_runtime` (the API's own
    `_runtime()` used by the module-lifecycle and per-session verbs)."""
    import polymerhus.app.runtime as app_runtime
    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: runtime)
    monkeypatch.setattr(app_runtime, "get_active_runtime", lambda: runtime)
    return hunting_runtime


# --- POST /projects/{pid}/hunting ----------------------------------------------

def test_launch_returns_the_surrogate_id_and_schedules(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)

    recorded: list[tuple] = []

    def fake_start(project_id, *, run_id=None, **kw):
        recorded.append((project_id, run_id, dict(kw)))

        async def _finish():
            return run_id

        return _finish()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)

    resp = client.post("/projects/p1/hunting", json={})

    assert resp.status_code == 201
    assert resp.json() == {"hunting_run_id": RUN_ID}
    assert fake_runtime.scheduled == [f"hunting:{RUN_ID}"]
    # the row opens SYNCHRONOUSLY before scheduling; the launch carries NO
    # candidate batch any more (T3 #376: the run's intake is the L1 inventory)
    (pid, rid, kwargs) = recorded[0]
    assert pid == "p1" and rid == RUN_ID
    assert "candidates" not in kwargs
    assert "intake_units" not in kwargs


def test_a_caller_supplied_candidate_body_is_ignored_not_a_launch_input(
        monkeypatch):
    """T3 #376: the candidate wire batch is retired - a client that still sends
    one gets a normal launch (the pass reads the L1 inventory itself), never a
    caller-controlled unit set."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)
    scheduled: list[tuple] = []

    def fake_start(project_id, *, run_id=None, **kw):
        scheduled.append((run_id, dict(kw)))

        async def _finish():
            return run_id

        return _finish()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)

    resp = client.post("/projects/p1/hunting", json={"candidates": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x"},
    ]})

    assert resp.status_code == 201
    assert scheduled == [(RUN_ID, {})]


def test_launch_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post("/projects/nope/hunting", json={})

    assert resp.status_code == 404
    assert fake_runtime.scheduled == []  # never scheduled


def test_launch_fails_closed_503_until_the_control_plane_lands(monkeypatch):
    """THE fail-closed surface: a real orchestration pass must never ride the
    uvicorn request loop through the in-process fallback, so the launch is a 503
    while `polymerhus.app.runtime` has not landed (as in this worktree)."""
    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: None)
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    opened = []
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: opened.append(pid) or RUN_ID)

    resp = client.post("/projects/p1/hunting", json={})

    assert resp.status_code == 503
    assert opened == []  # no run opened behind the gate


def test_launch_refused_409_while_a_live_run_exists(monkeypatch):
    """T5 AC3: the one-live-run-per-project guard refuses a second launch
    against a project with a live run - BEFORE a new row opens (the API check
    prevents the orphan), with a clear 409 Conflict detail."""
    rows = _FakeHuntingRows(seeded_running=(RUN_ID,))
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "list_hunting_runs", rows.list_hunting_runs)
    created = []
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: created.append(pid) or RUN_ID)
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post("/projects/p1/hunting", json={})

    assert resp.status_code == 409
    assert "live" in resp.json()["detail"]
    assert created == []  # no new row opened behind the guard
    assert fake_runtime.scheduled == []  # nothing scheduled behind the guard


def test_replayed_launch_for_an_already_created_run_id_is_refused(monkeypatch):
    """T5 AC4 (at-most-once): replaying the launch trigger once a run id was
    already created and is live is refused 409 - the run row IS the creation
    marker (ADR #169 Q6), and `list_hunting_runs` tracks it server-side. No
    Idempotency-Key header, no new persistence surface."""
    rows = _FakeHuntingRows()
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "list_hunting_runs", rows.list_hunting_runs)
    monkeypatch.setattr(pg, "create_hunting_run", rows.create_hunting_run)
    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)
    async def _noop_bootstrap(*_a, **_kw):
        return None

    monkeypatch.setattr(hunting_runtime, "start_hunting", _noop_bootstrap)

    first = client.post("/projects/p1/hunting", json={})
    assert first.status_code == 201

    replay = client.post("/projects/p1/hunting", json={})
    assert replay.status_code == 409
    assert fake_runtime.scheduled == [f"hunting:{RUN_ID}"]  # the replay never scheduled


def test_replayed_launch_permitted_again_once_the_run_is_terminal(monkeypatch):
    """The at-most-once guard is scoped to the LIVE run: a launch against a
    project whose created run id is terminal is NOT a replay - it relaunches."""
    rows = _FakeHuntingRows()
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "list_hunting_runs", rows.list_hunting_runs)
    monkeypatch.setattr(pg, "create_hunting_run", rows.create_hunting_run)
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    assert client.post("/projects/p1/hunting", json={}).status_code == 201
    rows.set_hunting_run_status(RUN_ID, "complete")
    replay = client.post("/projects/p1/hunting", json={})

    assert replay.status_code == 201  # terminal rows do not hold the guard


def test_launch_closes_the_orphan_row_on_admission_503(monkeypatch):
    """Orphan resolution (T5 ruling point 3): a post-open admission refusal
    (the hunting module paused/draining -> `ModuleAdmissionRefused` -> 503)
    closes the just-opened `running` row to `failed` synchronously - no orphan
    `running` row is ever left behind by a refused launch."""
    rows = _FakeHuntingRows()
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "list_hunting_runs", rows.list_hunting_runs)
    monkeypatch.setattr(pg, "create_hunting_run", rows.create_hunting_run)
    monkeypatch.setattr(pg, "set_hunting_run_status", rows.set_hunting_run_status)
    hunting_runtime = _patch_control_plane(monkeypatch, _FakeRuntime())

    from polymerhus.app.runtime import ModuleAdmissionRefused

    def refusing_schedule(coro, *, name):
        raise ModuleAdmissionRefused("hunting is paused")

    monkeypatch.setattr(hunting_runtime, "schedule_hunting", refusing_schedule)
    async def _never_run_bootstrap(*_a, **_kw):
        return None  # the admission refuses before this coroutine is consumed

    monkeypatch.setattr(hunting_runtime, "start_hunting", _never_run_bootstrap)

    resp = client.post("/projects/p1/hunting", json={})

    assert resp.status_code == 503
    assert rows.status_writes == [(RUN_ID, "failed")]  # the orphan row is closed
    row = rows.get_hunting_run(RUN_ID)
    assert row is not None and row["status"] == "failed"


def test_launch_after_a_hunting_drain_is_admitted_not_503(monkeypatch):
    """#332 regression: drain settles hunting to `stopped`; the next launch must
    repair the module through the shared `ensure_running` precondition and be
    admitted - never a 503 admission refusal (and no orphan row)."""
    from polymerhus.app.runtime import RuntimeManager
    from polymerhus.attack.hunting import runtime as hunting_runtime

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    monkeypatch.setattr(pg, "list_hunting_runs", lambda pid: [])
    monkeypatch.setattr(pg, "set_hunting_run_status", lambda rid, status: None)

    async def _noop_bootstrap(*_a, **_kw):
        return None

    monkeypatch.setattr(hunting_runtime, "start_hunting", _noop_bootstrap)

    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        rm.drain("hunting", timeout=5)
        assert rm.state("hunting").value == "stopped"

        resp = client.post("/projects/p1/hunting", json={})

        assert resp.status_code == 201, resp.text
        assert resp.json() == {"hunting_run_id": RUN_ID}
        assert rm.state("hunting").value == "running"
    finally:
        rm.shutdown()


def test_hunting_launch_during_shutdown_window_is_a_503_not_a_500(monkeypatch):
    """#332 fix-pass regression, the hunting arm of #328: in the shutdown window
    the active runtime is still published while its worker loop is already
    cleared, so reviving a drained hunting module raises
    `RuntimeLoopNotRunning`. The launch must map that to a clean 503, never an
    unhandled 500."""
    from polymerhus.app.runtime import RuntimeManager
    from polymerhus.attack.hunting import runtime as hunting_runtime

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    monkeypatch.setattr(pg, "list_hunting_runs", lambda pid: [])
    monkeypatch.setattr(pg, "set_hunting_run_status", lambda rid, status: None)
    # A plain sentinel, not a coroutine: `schedule_hunting` raises at the revive
    # before it could consume one, so no un-awaited coroutine warning.
    monkeypatch.setattr(hunting_runtime, "start_hunting", lambda *a, **k: object())

    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        rm.drain("hunting", timeout=5)
        assert rm.state("hunting").value == "stopped"

        saved_loop = rm._loop
        rm._loop = None
        try:
            resp = client.post("/projects/p1/hunting", json={})
            assert resp.status_code == 503, resp.text
            assert "not running" in resp.json()["detail"]
        finally:
            rm._loop = saved_loop
    finally:
        rm.shutdown()


# --- T5 singular launches: the hunt enqueue is RETIRED (T4b, #387) ------------

def test_hunt_launch_is_a_loud_410_and_the_enqueue_seam_is_gone():
    """T4b (#387): the hunter-only enqueue retires with the config family.

    A produced hunt config is no longer dispatch input (S2 8.2/8.4: the loop
    file is the dispatch record, and a live run's surfer dispatches it), so the
    wire path must NEVER silently accept a config into a family nothing reads.
    The endpoint stays a LOUD 410 naming the replacement, and the launcher
    seam is gone. The eval caller check (T4b): `eval/orchestrator/api.py` and
    `eval/ph.py` never call this path; the eval translation of the recorded
    config artifacts is T10 (#383)."""
    from polymerhus.attack.hunting import runtime as hunting_runtime

    assert not hasattr(hunting_runtime, "enqueue_hunt_config"), (
        "the config enqueue seam retired with the config family")

    resp = client.post("/projects/p1/hunting/hunt", json={
        "unit_id": "Service:slug:a", "fault_class": "CWE-352",
        "vulnerability_class": "CSRF",
    })

    assert resp.status_code == 410, resp.text
    detail = resp.json()["detail"]
    assert "retired" in detail.lower()
    assert "loop file" in detail.lower()
    assert "T10" in detail and "#383" in detail


def test_pod_launch_resumes_via_the_launcher_seam(monkeypatch):
    """Pod-only launch (identity-based refactor, 2026-08-25 operator ruling)
    routes through the launcher seam `resume_pod_session` (the recording stub):
    it resumes ONE pod session by posting its coroutine id - it never
    fabricates a produced `specified` spec - and acks asynchronously."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    fake_runtime = _FakeRuntime()
    from polymerhus.attack.hunting import runtime as hunting_runtime
    _patch_control_plane(monkeypatch, fake_runtime)
    recorded: list[tuple] = []

    def record(runtime, session_id):
        recorded.append((runtime, session_id))
        return None

    monkeypatch.setattr(hunting_runtime, "resume_pod_session", record)

    resp = client.post("/projects/p1/hunting/pod", json={
        "session_id": "hunting:rt-hunt-0001:pod:Service:slug:a_fault-x_CSRF:sqli_blind",
    })

    assert resp.status_code == 202
    body = resp.json()
    assert body["component"] == "pod" and body["resumed"] is True
    assert body["dispatched_asynchronously"] is True
    assert body["session_id"] == "hunting:rt-hunt-0001:pod:Service:slug:a_fault-x_CSRF:sqli_blind"
    (pid, session_id) = recorded[0]
    assert session_id == "hunting:rt-hunt-0001:pod:Service:slug:a_fault-x_CSRF:sqli_blind"


def test_pod_launch_resume_fail_closed_when_no_session_is_registered(monkeypatch):
    """FAIL-CLOSED (no fabricated dispatch input): no stored/paused pod session
    by that id maps the shared runtime's `RunNotRegistered` onto 404 - the
    launch refuses rather than enqueueing a fabricated `specified` spec."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    fake_runtime = _FakeRuntime()
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from polymerhus.app.runtime import RunNotRegistered
    _patch_control_plane(monkeypatch, fake_runtime)

    def no_session(runtime, session_id):
        raise RunNotRegistered(session_id)

    monkeypatch.setattr(hunting_runtime, "resume_pod_session", no_session)

    resp = client.post("/projects/p1/hunting/pod", json={
        "session_id": "hunting:rt-hunt-0001:pod:x:y",
    })

    assert resp.status_code == 404
    assert "no stored/paused pod session" in resp.json()["detail"]


def test_pod_launch_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    from polymerhus.attack.hunting import runtime as hunting_runtime
    called = []
    monkeypatch.setattr(
        hunting_runtime, "resume_pod_session",
        lambda runtime, sid: called.append(sid),
    )

    resp = client.post("/projects/nope/hunting/pod", json={
        "session_id": "hunting:r:pod:x:y",
    })

    assert resp.status_code == 404
    assert called == []


def test_orchestrator_launch_schedules_the_pass_via_the_launcher_seam(monkeypatch):
    """The modeller-only launch schedules ONE modelling pass through the
    launcher seam under the ADR Q13 modeller session id (no surfer, no run row)
    and acks asynchronously - the pass models its selected units on the loop.
    The `/hunting/orchestrator` path and the `orchestrator` component label are
    the planner-era wire names (T10 hygiene); the BODY is the modeller's."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    fake_runtime = _FakeRuntime()
    from polymerhus.attack.hunting import runtime as hunting_runtime
    _patch_control_plane(monkeypatch, fake_runtime)

    async def _pass_ran(*_a, **_kw):
        return None

    def record_pass(*_a, **_kw):
        return _pass_ran()

    monkeypatch.setattr(hunting_runtime, "launch_modeller", record_pass)

    resp = client.post("/projects/p1/hunting/orchestrator", json={})

    assert resp.status_code == 202
    body = resp.json()
    assert body["component"] == "orchestrator"
    assert body["dispatched_asynchronously"] is True
    assert body["run_id"]
    assert fake_runtime.scheduled == [
        f"hunting:{body['run_id']}:threat-modeller"]


def test_orchestrator_launch_fails_closed_503_without_control_plane(monkeypatch):
    """The orchestrator pass is a real LLM stretch: fail-closed 503 while the
    control plane has not landed, never booted on the request loop."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: None)

    resp = client.post("/projects/p1/hunting/orchestrator", json={})

    assert resp.status_code == 503


# --- T5: per-session lifecycle verbs (ADR #169 Q17, spec #169 "REST surface") ---

ORCH_SESSION = f"hunting:{RUN_ID}:orchestrator"
HUNT_SESSION = f"hunting:{RUN_ID}:hunt:u_CWE-x_C"
FOREIGN_SESSION = "hunting:other-run:orchestrator"


def test_session_pause_routes_to_the_per_session_hold(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post(
        f"/projects/p1/hunting/{RUN_ID}/sessions/{ORCH_SESSION}/pause")

    assert resp.status_code == 200
    assert resp.json()["state"] == "held"
    assert fake_runtime.held == [ORCH_SESSION]  # hold_session by session id
    assert fake_runtime.cancelled == []        # never the module-wide verbs


def test_session_resume_routes_to_the_per_session_resume(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post(
        f"/projects/p1/hunting/{RUN_ID}/sessions/{ORCH_SESSION}/resume")

    assert resp.status_code == 200
    assert resp.json()["state"] == "resumed"
    assert fake_runtime.resumed == [ORCH_SESSION]


def test_session_stop_routes_to_the_per_session_cancel(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post(
        f"/projects/p1/hunting/{RUN_ID}/sessions/{HUNT_SESSION}/stop")

    assert resp.status_code == 200
    assert resp.json()["state"] == "stopping"
    assert fake_runtime.cancelled == [HUNT_SESSION]  # ONE session, not the run


def test_session_verb_unknown_run_404(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: None)
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post(f"/projects/p1/hunting/{RUN_ID}/sessions/{ORCH_SESSION}/pause")

    assert resp.status_code == 404
    assert fake_runtime.held == []


def test_session_verb_foreign_session_404(monkeypatch):
    """A session id that does not belong to the run is an unknown session - it
    must never hold/cancel a sibling run's session through this endpoint."""
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post(
        f"/projects/p1/hunting/{RUN_ID}/sessions/{FOREIGN_SESSION}/pause")

    assert resp.status_code == 404
    assert fake_runtime.held == []


def test_session_stop_unregistered_session_404_via_the_runtime_error(monkeypatch):
    """A session of the run that is not currently registered (already settled)
    maps the runtime's own `RunNotRegistered` onto 404 - the cancel never
    tears down something that is not there."""
    from polymerhus.app.runtime import RunNotRegistered

    class _StrictRuntime(_FakeRuntime):
        def cancel_run(self, module, run_id):
            raise RunNotRegistered(run_id)

    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())
    _patch_control_plane(monkeypatch, _StrictRuntime())

    resp = client.post(
        f"/projects/p1/hunting/{RUN_ID}/sessions/{ORCH_SESSION}/stop")

    assert resp.status_code == 404


def test_session_verb_503_without_an_active_runtime(monkeypatch):
    _patch_control_plane(monkeypatch, None)
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())

    resp = client.post(
        f"/projects/p1/hunting/{RUN_ID}/sessions/{ORCH_SESSION}/pause")

    assert resp.status_code == 503


# --- POST /projects/{pid}/hunting/{rid}/stop -----------------------------------

def test_stop_acknowledges_and_reaches_the_cancel_seam(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())
    recorded_statuses = []
    monkeypatch.setattr(pg, "set_hunting_run_status",
                        lambda rid, status: recorded_statuses.append((rid, status)))
    fake_runtime = _FakeRuntime()
    # the T4 stop path cancels EVERY session of the run by session id, so the
    # registry must hold the run's live sessions (the launch registered the
    # bootstrap task as `hunting:<run_id>`)
    fake_runtime.scheduled.append(f"hunting:{RUN_ID}")
    fake_runtime.scheduled.append(f"hunting:{RUN_ID}:orchestrator")
    fake_runtime.scheduled.append(f"hunting:{RUN_ID}:hunt:u_CWE-x_C")
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post(f"/projects/p1/hunting/{RUN_ID}/stop")

    assert resp.status_code == 200
    assert resp.json() == {"hunting_run_id": RUN_ID, "stopping": True}
    # every session of the run reaches the hard-cancel, by session id
    assert fake_runtime.cancelled == [
        f"hunting:{RUN_ID}",
        f"hunting:{RUN_ID}:orchestrator",
        f"hunting:{RUN_ID}:hunt:u_CWE-x_C",
    ]
    assert recorded_statuses == [(RUN_ID, "stopped")]


def test_stop_unknown_run_404(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: None)

    resp = client.post(f"/projects/p1/hunting/{RUN_ID}/stop")

    assert resp.status_code == 404


# --- POST /projects/{pid}/execution/stop ---------------------------------------

def test_project_execution_stop_stops_every_live_run_kind(monkeypatch):
    # The ONE stop a token-budget / deadline monitor calls: every live run of the
    # project, all kinds at once, regardless of analysis mode - analysis, then the
    # recon and hunting hard cancels. Other projects' runs are never touched.
    monkeypatch.setattr(pg, "list_running_analysis_runs", lambda: [
        {"analysis_run_id": "a1", "run_id": "r0", "project_id": "p1",
         "status": "draining", "started_at": None},
        {"analysis_run_id": "a9", "run_id": "r9", "project_id": "other",
         "status": "draining", "started_at": None},
    ])
    monkeypatch.setattr(pg, "list_running_runs", lambda: [
        {"run_id": "r0", "project_id": "p1", "status": "running", "jobs": {}},
        {"run_id": "r9", "project_id": "other", "status": "running", "jobs": {}},
    ])
    monkeypatch.setattr(pg, "list_running_hunting_runs", lambda: [
        {"hunting_run_id": "h1", "project_id": "p1", "status": "running",
         "started_at": None, "finished_at": None},
    ])

    stopped_analysis: list[str] = []

    async def _fake_stop_analysis(run_id: str) -> None:
        stopped_analysis.append(run_id)

    import polymerhus.analysis.lifecycle as analysis_lifecycle
    monkeypatch.setattr(analysis_lifecycle, "stop_analysis", _fake_stop_analysis)

    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)

    stopped_hunting: list[str] = []

    async def _fake_stop_hunting(hunting_run_id: str) -> None:
        stopped_hunting.append(hunting_run_id)

    monkeypatch.setattr(hunting_runtime, "stop_hunting", _fake_stop_hunting)

    resp = client.post("/projects/p1/execution/stop")

    assert resp.status_code == 200
    body = resp.json()
    assert body["stopped"] == {"analysis": ["r0"], "recon": ["r0"], "hunting": ["h1"]}
    assert body["errors"] == []
    assert stopped_analysis == ["r0"]     # only the p1 analysis, by its recon id
    assert "r0" in fake_runtime.cancelled  # recon hard-cancel, only p1
    assert "r9" not in fake_runtime.cancelled
    assert stopped_hunting == ["h1"]


def test_project_execution_stop_is_a_no_op_for_an_idle_project(monkeypatch):
    monkeypatch.setattr(pg, "list_running_analysis_runs", lambda: [])
    monkeypatch.setattr(pg, "list_running_runs", lambda: [])
    monkeypatch.setattr(pg, "list_running_hunting_runs", lambda: [])
    _patch_control_plane(monkeypatch, _FakeRuntime())

    resp = client.post("/projects/p1/execution/stop")

    assert resp.status_code == 200
    assert resp.json() == {
        "project_id": "p1",
        "stopped": {"analysis": [], "recon": [], "hunting": []},
        "errors": [],
    }


# --- GET /projects/{pid}/hunting/{rid} -----------------------------------------

def test_status_returns_the_status_row(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row(status="complete"))

    resp = client.get(f"/projects/p1/hunting/{RUN_ID}")

    assert resp.status_code == 200
    assert resp.json()["hunting_run_id"] == RUN_ID
    assert resp.json()["status"] == "complete"


def test_status_unknown_run_404(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: None)

    resp = client.get(f"/projects/p1/hunting/{RUN_ID}")

    assert resp.status_code == 404