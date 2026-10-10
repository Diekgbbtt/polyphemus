"""Integration tier: the agent sub-module contract predicates C1-C19 (#317).

Mechanises the contract predicate catalogue in
`docs/design/hunting-317-agent-submodule-assertions.md`. Three seams:

- the runtime manager's agent-sub-module verbs + role gate (C1-C9, C19) on a
  REAL `RuntimeManager` worker loop;
- the surfer's dispatch builder (C5/C10-C12) via the REAL `build_run_dispatch`
  on temp-root production stores with fakes kept at the agent-seam builders and
  the role reads;
- the app REST surface (C13-C18) via the REAL FastAPI app (`TestClient`) over a
  REAL runtime manager, with the pg accessors faked (hermetic - never a live
  database).

Expected values come from the spec, never recomputed the way the code computes
them. These gate the verifier and are NOT selected by the tdd unit red/green loop.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from polymerhus.app.main import app
from polymerhus.app.runtime import (
    ModuleState,
    RuntimeManager,
    UnknownAgentSubmoduleRole,
)
from polymerhus.app.clients import pg
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    HuntConfigItem,
    RuntimeControlPlane,
    hunter_session_id,
    run_delivery_tick,
)
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    build_run_dispatch,
    is_run_quiesced,
    run_work_remaining,
)

RUN = "run-as-int"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
FAULT_KEY = f"{UNIT}_{CWE}_{CLASS}"
CONFIG_KEY = f"{UNIT}::{CWE}::{CLASS}"
SPEC_FILE = "sqli_blind"
ROLES = ("orchestrator", "hunter", "pod")


def _wait_until(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def _wait_until_flat(seq, timeout=5.0):
    deadline = time.monotonic() + timeout
    samples = []
    while time.monotonic() < deadline:
        samples.append(len(seq))
        if len(samples) >= 3 and samples[-1] == samples[-2] == samples[-3]:
            return
        time.sleep(0.02)
    raise AssertionError(f"sequence did not stabilise within {timeout}s")


def _config(**overrides):
    data = {
        "hunt_id": "hunt-1", "unit_id": UNIT, "fault_class": CWE,
        "status": "ratified", "vulnerability_class": CLASS,
        "rationale": "r", "research_direction": "rd",
    }
    data.update(overrides)
    return data


def _spec(**overrides):
    data = {
        "spec_id": SPEC_FILE, "fault_key": FAULT_KEY,
        "fault": {}, "strategy": "blind", "status": "specified",
    }
    data.update(overrides)
    return data


@pytest.fixture
def runtime():
    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        yield rm
    finally:
        rm.shutdown()


# =========================================================================
# C1-C9: the runtime manager seam
# =========================================================================

def test_C1_booted_run_has_its_roles_up(runtime):
    for role in ROLES:
        runtime.register_agent_submodule("hunting", RUN, role)
    states = {r: runtime.agent_submodule_state("hunting", RUN, r) for r in ROLES}
    assert states == {r: ModuleState.RUNNING for r in ROLES}


def test_C2_stop_is_idempotent(runtime):
    assert runtime.stop_agent_submodule("hunting", RUN, "hunter") is ModuleState.PAUSED
    assert runtime.stop_agent_submodule("hunting", RUN, "hunter") is ModuleState.PAUSED
    states = runtime.agent_submodule_states("hunting", RUN)
    assert states["hunter"] is ModuleState.PAUSED
    assert sum(1 for s in states.values() if s is ModuleState.PAUSED) == 1


def test_C3_start_releases_and_is_idempotent(runtime):
    runtime.stop_agent_submodule("hunting", RUN, "hunter")
    assert runtime.start_agent_submodule("hunting", RUN, "hunter") is ModuleState.RUNNING
    assert runtime.start_agent_submodule("hunting", RUN, "hunter") is ModuleState.RUNNING


def test_C4_unknown_role_is_a_named_refusal(runtime):
    with pytest.raises(UnknownAgentSubmoduleRole):
        runtime.stop_agent_submodule("hunting", RUN, "sorcerer")
    with runtime._agent_lock:  # noqa: SLF001 - no handle created
        assert runtime._agent_submodules == {}


def test_C6_role_gate_holds_in_flight_and_start_releases(runtime):
    gate = runtime.agent_submodule_gate("hunting", RUN, "hunter")
    progress = []

    async def hunter_run():
        for i in range(1500):
            async with gate:
                progress.append(i)
                await asyncio.sleep(0.002)

    fut = runtime.schedule("hunting", hunter_run(), name=f"hunting:{RUN}:hunt:a")
    _wait_until(lambda: len(progress) > 5)

    runtime.stop_agent_submodule("hunting", RUN, "hunter")
    _wait_until_flat(progress)
    frozen = len(progress)
    time.sleep(0.1)
    assert len(progress) == frozen
    runtime.start_agent_submodule("hunting", RUN, "hunter")
    _wait_until(lambda: len(progress) > frozen)
    assert fut.result(timeout=15) is None


def test_C7_the_hierarchy_holds_module_pause_dominates(runtime):
    gate = runtime.agent_submodule_gate("hunting", RUN, "hunter")
    progress = []

    async def hunter_run():
        for i in range(1500):
            async with gate:
                progress.append(i)
                await asyncio.sleep(0.002)

    fut = runtime.schedule("hunting", hunter_run(), name=f"hunting:{RUN}:hunt:a")
    _wait_until(lambda: len(progress) > 5)
    # the role's own state stays RUNNING; the MODULE pause still holds it.
    assert runtime.agent_submodule_state("hunting", RUN, "hunter") is ModuleState.RUNNING
    runtime.pause("hunting")
    _wait_until_flat(progress)
    frozen = len(progress)
    time.sleep(0.1)
    assert len(progress) == frozen
    runtime.resume("hunting")
    _wait_until(lambda: len(progress) > frozen)
    assert fut.result(timeout=15) is None


def test_C8_a_module_drain_settles_the_role_gates(runtime):
    runtime.agent_submodule_gate("hunting", RUN, "hunter")
    runtime.drain("hunting", timeout=5)
    assert runtime.state("hunting") is ModuleState.STOPPED
    with runtime._agent_lock:  # noqa: SLF001 - role handles reaped
        assert runtime._agent_submodules == {}


def test_C9_state_is_in_memory_and_resets_up():
    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        assert rm.agent_submodule_states("hunting", RUN) == {
            r: ModuleState.RUNNING for r in ROLES
        }
    finally:
        rm.shutdown()


def test_C19_the_role_state_read_is_pure(runtime):
    # After the run terminal reaped the role handles, a state read reports the
    # declared roles (a missing handle reads the RUNNING default) and creates NO
    # new handle: the registry stays empty (handles never outlive the run).
    for role in ROLES:
        runtime.register_agent_submodule("hunting", RUN, role)
    runtime.reap_agent_submodules("hunting", RUN)
    with runtime._agent_lock:  # noqa: SLF001 - reaped
        assert runtime._agent_submodules == {}

    assert runtime.agent_submodule_states("hunting", RUN) == {
        r: ModuleState.RUNNING for r in ROLES
    }
    assert runtime.agent_submodule_state(
        "hunting", RUN, "hunter") is ModuleState.RUNNING
    assert runtime.agent_submodule_running("hunting", RUN, "hunter") is True

    with runtime._agent_lock:  # noqa: SLF001 - the reads left it empty
        assert runtime._agent_submodules == {}


# =========================================================================
# C5/C10-C12: the surfer dispatch seam
# =========================================================================

class _RoleControl:
    def __init__(self, down=()):
        self._down = set(down)

    def role_running(self, run_id, role):
        return role not in self._down

    def role_gate(self, run_id, role):
        return None


class _RecordingControl:
    def __init__(self):
        self.calls: list[str] = []

    def live_session_ids(self):
        return set()

    def dispatch(self, session_id, coro):
        self.calls.append(session_id)
        coro.close()
        return True


def _hunter_builder(*, run_id, project_id, hunter_store, **kw):
    async def _dispatch(config):
        return None

    return _dispatch, None


async def _pod_builder(spec, **kw):
    return {"verdict": "successful", "terminal_reason": "symptom-confirmed"}


def _coro_for(hunt, hunter, state, control):
    return build_run_dispatch(
        project_id="p", run_id=RUN, hunt_store=hunt, hunter_store=hunter,
        pod_store=None, state=state, gate=None, control=control,
        hunter_builder=_hunter_builder, pod_builder=_pod_builder,
    )


def test_C5_stop_refuses_new_dispatch_for_the_role(tmp_path, runtime):
    """Through the REAL RuntimeControlPlane: with the hunter role stopped, the
    surfer builder yields no coroutine and no new session registers."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt.write_config("p", _config())
    runtime.stop_agent_submodule("hunting", RUN, "hunter")
    plane = RuntimeControlPlane(runtime=runtime)
    item = HuntConfigItem(
        message_id=f"{FAULT_KEY}.yaml",
        session_id=hunter_session_id(RUN, FAULT_KEY),
        config_key=CONFIG_KEY,
    )
    coro_for = _coro_for(hunt, hunter, RunDispatchState(), plane)
    assert coro_for(item) is None                     # refused
    assert runtime.run_ids("hunting") == []           # zero new sessions


def test_C10_a_down_hunter_denies_hunter_dispatch(tmp_path):
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt.write_config("p", _config())
    control = _RecordingControl()
    report = run_delivery_tick(
        "p", RUN, hunt_store=hunt, hunter_store=hunter, control=control,
        coro_for=_coro_for(hunt, hunter, RunDispatchState(),
                           _RoleControl(down={"hunter"})),
    )
    assert control.calls == []
    assert report.refused == 1 and report.moved == 0
    assert [k for k, _ in hunt.read_produced_configs("p")] == [CONFIG_KEY]
    # S6/E1 lower tier: while the hunter role is down its refused config is
    # still DISPATCHABLE work, so the quiesce predicate stays False and the run
    # can never reach `complete` (the E1 "run stays running" claim, without
    # Docker).
    assert run_work_remaining("p", hunt_store=hunt, hunter_store=hunter) is True
    assert asyncio.run(is_run_quiesced(
        "p", RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, state=RunDispatchState(),
    )) is False


def test_C11_a_down_pod_denies_pod_dispatch(tmp_path):
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunter.write_spec("p", FAULT_KEY, fault_keyword="sqli",
                      strategy_keyword="blind", spec=_spec())
    control = _RecordingControl()
    report = run_delivery_tick(
        "p", RUN, hunt_store=hunt, hunter_store=hunter, control=control,
        coro_for=_coro_for(hunt, hunter, RunDispatchState(),
                           _RoleControl(down={"pod"})),
    )
    assert control.calls == []
    assert report.refused == 1 and report.moved == 0
    assert hunter.produced_spec_files("p", FAULT_KEY) == [SPEC_FILE]


class _RecordingGate:
    def __init__(self, log):
        self._log = log

    async def __aenter__(self):
        self._log.append("enter")
        return self

    async def __aexit__(self, *exc):
        self._log.append("exit")


def test_C12_an_up_role_dispatches_and_acquires_the_role_gate(monkeypatch, tmp_path):
    from polymerhus.attack.hunting import surfer as surfer_mod

    log: list[str] = []
    control = _RoleControl()

    class _GateControl(_RoleControl):
        def role_gate(self, run_id, role):
            return _RecordingGate(log)

    async def _noop_idle(**kw):
        return None

    monkeypatch.setattr(surfer_mod, "_run_hunter_idle", _noop_idle)
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt.write_config("p", _config())
    item = HuntConfigItem(
        message_id=f"{FAULT_KEY}.yaml",
        session_id=hunter_session_id(RUN, FAULT_KEY),
        config_key=CONFIG_KEY,
    )
    coro = _coro_for(hunt, hunter, RunDispatchState(), _GateControl())(item)
    assert coro is not None
    asyncio.run(coro)
    assert log == ["enter", "exit"]


# =========================================================================
# C13-C18: the REST surface (real app + real runtime manager, faked pg)
# =========================================================================

class _FakePg:
    def __init__(self, status="running"):
        self.row = {
            "hunting_run_id": RUN, "project_id": "p1", "status": status,
            "started_at": None, "finished_at": None,
        }

    def get_hunting_run(self, run_id):
        return self.row if run_id == RUN else None

    def project_exists(self, project_id):
        return project_id == "p1"


@pytest.fixture
def api_runtime(monkeypatch):
    fake = _FakePg()
    monkeypatch.setattr(pg, "get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr(pg, "project_exists", fake.project_exists)
    rm = RuntimeManager()
    rm.start()
    rm.register_module("hunting")
    try:
        yield rm, fake
    finally:
        rm.shutdown()


@pytest.fixture
def client(api_runtime):
    return TestClient(app)


def test_C13_start_stop_are_idempotent_over_http(client):
    r1 = client.post(f"/projects/p1/hunting/{RUN}/agent-submodules/hunter/stop")
    r2 = client.post(f"/projects/p1/hunting/{RUN}/agent-submodules/hunter/stop")
    assert r1.status_code == 200 and r2.status_code == 200
    listing = client.get(f"/projects/p1/hunting/{RUN}/agent-submodules").json()
    hunter = next(x for x in listing if x["role"] == "hunter")
    assert hunter["state"] == "paused"
    assert sum(1 for x in listing if x["role"] == "hunter") == 1

    start = client.post(f"/projects/p1/hunting/{RUN}/agent-submodules/hunter/start")
    assert start.status_code == 200
    listing = client.get(f"/projects/p1/hunting/{RUN}/agent-submodules").json()
    assert next(x for x in listing if x["role"] == "hunter")["state"] == "running"


def test_C14_the_role_listing_shape(client):
    listing = client.get(f"/projects/p1/hunting/{RUN}/agent-submodules")
    assert listing.status_code == 200
    body = listing.json()
    assert [x["role"] for x in body] == list(ROLES)
    assert all(x["state"] in ("running", "paused") for x in body)


def test_C15_the_thread_listing_shape(client, api_runtime):
    rm, _ = api_runtime
    entered = threading.Event()

    async def live():
        entered.set()
        await asyncio.sleep(30)

    session_id = f"hunting:{RUN}:hunt:{FAULT_KEY}"
    rm.schedule("hunting", live(), name=session_id)
    assert entered.wait(timeout=5)

    listing = client.get(f"/projects/p1/hunting/{RUN}/threads")
    assert listing.status_code == 200
    by_id = {t["thread_id"]: t for t in listing.json()}
    assert session_id in by_id
    assert by_id[session_id]["role"] == "hunter"
    assert by_id[session_id]["held"] is False

    rm.cancel_run("hunting", session_id)
    _wait_until(lambda: session_id not in rm.run_ids("hunting"))


def test_C15_thread_listing_empty_is_valid(client):
    listing = client.get(f"/projects/p1/hunting/{RUN}/threads")
    assert listing.status_code == 200
    assert listing.json() == []


def test_C16_unknown_run_role_thread_fail_clearly(client):
    unknown_role = client.post(
        f"/projects/p1/hunting/{RUN}/agent-submodules/sorcerer/stop")
    assert unknown_role.status_code == 404
    listing = client.get(f"/projects/p1/hunting/{RUN}/agent-submodules").json()
    assert [x["role"] for x in listing] == list(ROLES)  # no state change

    unknown_run = client.post(
        "/projects/p1/hunting/nope/agent-submodules/hunter/stop")
    assert unknown_run.status_code == 404

    unknown_thread = client.post(
        f"/projects/p1/hunting/{RUN}/threads/hunting:{RUN}:hunt:nope/stop")
    assert unknown_thread.status_code == 404

    unknown_resume = client.post(
        f"/projects/p1/hunting/{RUN}/threads/hunting:{RUN}:hunt:nope/resume")
    assert unknown_resume.status_code == 404


def test_C17_thread_stop_resume_idempotency(client, api_runtime):
    rm, _ = api_runtime
    entered = threading.Event()

    async def live():
        entered.set()
        await asyncio.sleep(30)

    session_id = f"hunting:{RUN}:hunt:{FAULT_KEY}"
    rm.schedule("hunting", live(), name=session_id)
    assert entered.wait(timeout=5)

    stop = client.post(f"/projects/p1/hunting/{RUN}/threads/{session_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["state"] == "held"
    held = {t["thread_id"]: t for t in client.get(
        f"/projects/p1/hunting/{RUN}/threads").json()}[session_id]
    assert held["held"] is True

    second = client.post(f"/projects/p1/hunting/{RUN}/threads/{session_id}/stop")
    assert second.status_code == 200
    held = {t["thread_id"]: t for t in client.get(
        f"/projects/p1/hunting/{RUN}/threads").json()}[session_id]
    assert held["held"] is True

    resume = client.post(f"/projects/p1/hunting/{RUN}/threads/{session_id}/resume")
    assert resume.status_code == 200
    assert resume.json()["state"] == "resumed"
    held = {t["thread_id"]: t for t in client.get(
        f"/projects/p1/hunting/{RUN}/threads").json()}[session_id]
    assert held["held"] is False

    again = client.post(f"/projects/p1/hunting/{RUN}/threads/{session_id}/resume")
    assert again.status_code == 200

    rm.cancel_run("hunting", session_id)
    _wait_until(lambda: session_id not in rm.run_ids("hunting"))


def test_C18_no_active_runtime_degrades_cleanly(monkeypatch, client):
    # There is an active runtime for the fixture; simulate its absence by
    # making the resolver return None for this test.
    import polymerhus.app.runtime as app_runtime
    monkeypatch.setattr(app_runtime, "get_active_runtime", lambda: None)

    stop = client.post(f"/projects/p1/hunting/{RUN}/agent-submodules/hunter/stop")
    assert stop.status_code == 503
    listing = client.get(f"/projects/p1/hunting/{RUN}/agent-submodules")
    assert listing.status_code == 503
    threads = client.get(f"/projects/p1/hunting/{RUN}/threads")
    assert threads.status_code == 503
