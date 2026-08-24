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

    def set_hunting_run_status(self, hunting_run_id: str, status: str) -> None:
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
    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: runtime)
    return hunting_runtime


# --- POST /projects/{pid}/hunting ----------------------------------------------

def test_launch_returns_the_surrogate_id_and_schedules(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)

    recorded: list[tuple] = []

    def fake_start(project_id, *, run_id=None, candidates=None, **kw):
        recorded.append((project_id, run_id, candidates))

        async def _finish():
            return run_id

        return _finish()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)

    resp = client.post("/projects/p1/hunting", json={"candidates": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x"},
    ]})

    assert resp.status_code == 201
    assert resp.json() == {"hunting_run_id": RUN_ID}
    assert fake_runtime.scheduled == [f"hunting:{RUN_ID}"]
    # the row opens SYNCHRONOUSLY before scheduling, and the launch carries the
    # candidate batch into the scheduled entry point
    (pid, rid, candidates) = recorded[0]
    assert pid == "p1" and rid == RUN_ID
    assert [c.unit_id for c in candidates] == ["Service:slug:a"]
    assert [c.fault_class for c in candidates] == ["fault-x"]


def test_launch_empty_batch_is_an_empty_pass_scheduled(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)
    recorded: list[tuple] = []

    def fake_start(project_id, *, run_id=None, candidates=None, **kw):
        recorded.append((candidates,))

        async def _finish():
            return run_id

        return _finish()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)

    resp = client.post("/projects/p1/hunting", json={})

    assert resp.status_code == 201
    assert recorded[0] == ([],)  # an empty batch launches an O1 empty pass


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


# --- T5: singular component launches (enqueue, never a dependency error) ------

def test_hunt_launch_enqueues_via_the_launcher_seam(monkeypatch):
    """Hunter-only launch routes through the launcher seam (the recording
    stub): the endpoint enqueues the wire config into the project's HuntStore
    via `enqueue_hunt_config` and acks asynchronously - it never boots a
    hunter itself, never opens a run row."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    recorded: list[tuple] = []

    def record(project_id, config):
        recorded.append((project_id, config))
        return f"{config.unit_id}::{config.fault_class}::{config.vulnerability_class}"

    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "enqueue_hunt_config", record)

    resp = client.post("/projects/p1/hunting/hunt", json={
        "unit_id": "Service:slug:a", "fault_class": "fault-x",
        "vulnerability_class": "CSRF", "research_direction": "rd",
    })

    assert resp.status_code == 202
    body = resp.json()
    assert body["component"] == "hunt" and body["enqueued"] is True
    assert body["dispatched_asynchronously"] is True
    assert body["enqueued_key"] == "Service:slug:a::fault-x::CSRF"
    (pid, config) = recorded[0]
    assert pid == "p1"
    assert config.unit_id == "Service:slug:a"
    assert config.fault_class == "fault-x"
    assert config.vulnerability_class == "CSRF"
    assert config.prompt_template.research_direction == "rd"


def test_pod_launch_enqueues_via_the_launcher_seam(monkeypatch):
    """Pod-only launch routes through the launcher seam (the recording stub):
    the endpoint enqueues the wire spec into the project's HunterMemoryStore
    via `enqueue_test_spec` and acks asynchronously."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    recorded: list[tuple] = []

    def record(project_id, **kw):
        recorded.append((project_id, kw))
        return f"{kw['fault_keyword']}_{kw['strategy_keyword']}"

    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "enqueue_test_spec", record)

    resp = client.post("/projects/p1/hunting/pod", json={
        "fault_key": "Service:slug:a::fault-x::CSRF",
        "fault_keyword": "sqli", "strategy_keyword": "blind",
        "spec": {"target_identity": "http://target/"},
    })

    assert resp.status_code == 202
    body = resp.json()
    assert body["component"] == "pod" and body["enqueued"] is True
    assert body["spec_file"] == "sqli_blind"
    (pid, kw) = recorded[0]
    assert pid == "p1"
    assert kw["fault_key"] == "Service:slug:a::fault-x::CSRF"
    assert kw["spec"]["target_identity"] == "http://target/"


def test_orchestrator_launch_schedules_the_pass_via_the_launcher_seam(monkeypatch):
    """Orchestrator-only launch schedules ONE orchestration pass through the
    launcher seam under the ADR Q13 orchestrator session id (no surfer, no run
    row) and acks asynchronously - the pass consumes its candidate inbox on
    the loop."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    fake_runtime = _FakeRuntime()
    from polymerhus.attack.hunting import runtime as hunting_runtime
    _patch_control_plane(monkeypatch, fake_runtime)

    async def _pass_ran(*_a, **_kw):
        return None

    def record_pass(*_a, **_kw):
        return _pass_ran()

    monkeypatch.setattr(hunting_runtime, "launch_orchestrator", record_pass)

    resp = client.post("/projects/p1/hunting/orchestrator", json={
        "candidates": [{"unit_id": "Service:slug:a", "fault_class": "fault-x"}],
    })

    assert resp.status_code == 202
    body = resp.json()
    assert body["component"] == "orchestrator"
    assert body["dispatched_asynchronously"] is True
    assert body["run_id"]
    assert fake_runtime.scheduled == [f"hunting:{body['run_id']}:orchestrator"]


def test_hunt_launch_never_fabricates_a_dependency_error_without_a_run(monkeypatch):
    """The hunter-only enqueue succeeds with NO live run and NO control plane
    (the control plane is not gated for an enqueue - only the whole launch
    and the orchestrator pass schedule): the config waits in produced,
    at-least-once, until a run's surfer admits it. No chained-dependency
    error is ever fabricated."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    from polymerhus.attack.hunting import runtime as hunting_runtime
    _patch_control_plane(monkeypatch, None)  # no control plane at all
    recorded = []
    monkeypatch.setattr(
        hunting_runtime, "enqueue_hunt_config",
        lambda pid, config: recorded.append(pid) or "k",
    )

    resp = client.post("/projects/p1/hunting/hunt", json={
        "unit_id": "Service:slug:a", "fault_class": "fault-x",
        "vulnerability_class": "CSRF",
    })

    assert resp.status_code == 202
    assert recorded == ["p1"]


def test_hunt_launch_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    from polymerhus.attack.hunting import runtime as hunting_runtime
    called = []
    monkeypatch.setattr(
        hunting_runtime, "enqueue_hunt_config",
        lambda pid, config: called.append(pid) or "k",
    )

    resp = client.post("/projects/nope/hunting/hunt", json={
        "unit_id": "u", "fault_class": "f",
    })

    assert resp.status_code == 404
    assert called == []


def test_hunt_launch_replayed_enqueue_is_refused_409(monkeypatch):
    """At-most-once on the enqueue (T5 AC4): the storage novelty gate
    (`DuplicateConfigError` - a config identity already produced or consumed)
    maps to 409 for a replayed enqueue - duplicate requests cannot
    double-dispatch agents."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from polymerhus.attack.hunting.hunt_store import DuplicateConfigError

    def already_enqueued(pid, config):
        raise DuplicateConfigError("already exists in produced/")

    monkeypatch.setattr(hunting_runtime, "enqueue_hunt_config", already_enqueued)

    resp = client.post("/projects/p1/hunting/hunt", json={
        "unit_id": "u", "fault_class": "f", "vulnerability_class": "CSRF",
    })

    assert resp.status_code == 409
    assert "already enqueued" in resp.json()["detail"]


def test_pod_launch_replayed_enqueue_is_refused_409(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from polymerhus.attack.hunting.hunter_memory import DuplicateSpecError

    def already_enqueued(pid, **kw):
        raise DuplicateSpecError("spec file already exists")

    monkeypatch.setattr(hunting_runtime, "enqueue_test_spec", already_enqueued)

    resp = client.post("/projects/p1/hunting/pod", json={
        "fault_key": "u::f::CSRF", "fault_keyword": "sqli",
        "strategy_keyword": "blind", "spec": {},
    })

    assert resp.status_code == 409
    assert "already enqueued" in resp.json()["detail"]


def test_orchestrator_launch_fails_closed_503_without_control_plane(monkeypatch):
    """The orchestrator pass is a real LLM stretch: fail-closed 503 while the
    control plane has not landed, never booted on the request loop."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: None)

    resp = client.post("/projects/p1/hunting/orchestrator", json={})

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