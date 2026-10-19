"""Unit tier: the surfer's per-role dispatch enforcement (#317).

`build_run_dispatch` consults the target role's agent sub-module state via the
control plane: a role that is not `RUNNING` makes the builder answer `None`
(the mover's refused rule - the item stays produced, at-least-once). Each
dispatched role session acquires its OWN role gate around its active stretch.
These tests drive the REAL `build_run_dispatch` / `run_hunter_session` /
`run_pod_session` on temp-root production stores, with fakes kept at the
agent-seam builder boundary and the role reads.
"""
import asyncio

import pytest

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting import mover as mover_mod
from polymerhus.attack.hunting import surfer as surfer_mod
from polymerhus.attack.hunting.mover import (
    read_produced_inbox,
    run_delivery_tick,
)
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    build_run_dispatch,
    derive_thread_role,
    run_hunter_session,
    run_pod_session,
)

from tests.hunting_fixtures import produce_model

PROJECT = "proj-as"
RUN = "run-as"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
FAULT_KEY = f"{UNIT}_{CWE}_{CLASS}"
CONFIG_KEY = f"{UNIT}::{CWE}::{CLASS}"
UNIT_NAME = "Service-catalogue-and-discovery"
LOOP_ID = "loop-1"
DISPATCH_ID = f"{UNIT_NAME}__{LOOP_ID}"
HUNTER_SESSION = mover_mod.hunter_session_id(RUN, DISPATCH_ID)
SPEC_FILE = "sqli_blind"


def _produce(threat):
    """One produced COMPLETED valid model with its loop file (S2 8.1)."""
    return produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN)


def _spec(**overrides):
    data = {
        "spec_id": SPEC_FILE, "fault_key": FAULT_KEY,
        "fault": {}, "strategy": "blind", "status": "specified",
    }
    data.update(overrides)
    return data


def _hunter_builder(*, run_id, project_id, hunter_store, **kw):
    async def _dispatch(config):
        return None

    return _dispatch, None


async def _pod_builder(spec, **kw):
    return {"verdict": "successful", "terminal_reason": "symptom-confirmed"}


class _RoleControl:
    """A control-plane stand-in exposing the #317 role reads."""

    def __init__(self, down=()):
        self._down = set(down)
        self.gates: dict[str, object] = {}

    def role_running(self, run_id, role):
        return role not in self._down

    def role_gate(self, run_id, role):
        return self.gates.get(role)


class _RecordingControl:
    def __init__(self, refused=()):
        self._refused = set(refused)
        self.calls: list[str] = []

    def live_session_ids(self):
        return set()

    def dispatch(self, session_id, coro):
        self.calls.append(session_id)
        coro.close()
        return session_id not in self._refused


@pytest.fixture
def stores(tmp_path):
    return ThreatModelStore(tmp_path / "threat"), HunterMemoryStore(tmp_path / "hunter")


def _coro_for(threat, hunter, state, control):
    return build_run_dispatch(
        project_id=PROJECT, run_id=RUN, threat_store=threat, hunter_store=hunter,
        pod_store=None, state=state, gate=None, control=control,
        hunter_builder=_hunter_builder, pod_builder=_pod_builder,
    )


# --- C10/C11: a down role refuses dispatch, the item stays produced ----------

def test_C10_down_hunter_role_refuses_loop_dispatch(stores):
    threat, hunter = stores
    _produce(threat)
    control = _RecordingControl()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_coro_for(threat, hunter, RunDispatchState(),
                                            _RoleControl(down={"hunter"})),
    )
    assert control.calls == []           # no coroutine was even admitted
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    assert [entry["loop_id"] for entry in
            threat.read_produced_loops(PROJECT)[0]["loops"]] == [LOOP_ID]


def test_C11_down_pod_role_refuses_spec_dispatch(stores):
    threat, hunter = stores
    hunter.write_spec(PROJECT, FAULT_KEY, fault_keyword="sqli",
                      strategy_keyword="blind", spec=_spec())
    control = _RecordingControl()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_coro_for(threat, hunter, RunDispatchState(),
                                            _RoleControl(down={"pod"})),
    )
    assert control.calls == []
    assert report.refused == 1 and report.moved == 0
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == [SPEC_FILE]


# --- C12: an up role dispatches and the session acquires the role gate --------

class _RecordingGate:
    def __init__(self, log):
        self._log = log

    async def __aenter__(self):
        self._log.append("enter")
        return self

    async def __aexit__(self, *exc):
        self._log.append("exit")


def test_C12_up_hunter_dispatches_and_acquires_the_role_gate(monkeypatch, tmp_path):
    log: list[str] = []
    control = _RoleControl()
    control.gates["hunter"] = _RecordingGate(log)

    async def _noop_idle(**kw):
        return None

    monkeypatch.setattr(surfer_mod, "_run_hunter_idle", _noop_idle)
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _produce(threat)
    state = RunDispatchState()
    coro_for = _coro_for(threat, hunter, state, control)
    item = read_produced_inbox(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter).items[0]
    assert item.message_id == DISPATCH_ID
    coro = coro_for(item)
    assert coro is not None            # up role -> a session coroutine
    asyncio.run(coro)
    assert log == ["enter", "exit"]    # the role gate bounded the stretch


def test_C12_up_pod_session_acquires_the_role_gate(monkeypatch, tmp_path):
    log: list[str] = []
    control = _RoleControl()
    control.gates["pod"] = _RecordingGate(log)
    control.role_gate  # noqa: B018 - the read is exercised via _coro_for

    async def _noop_idle(**kw):
        return None

    monkeypatch.setattr(surfer_mod, "_run_hunter_idle", _noop_idle)
    hunter = HunterMemoryStore(tmp_path / "hunter")

    async def _go():
        return await run_pod_session(
            spec=_spec(), project_id=PROJECT, run_id=RUN, fault_key=FAULT_KEY,
            config_key=CONFIG_KEY, spec_id=SPEC_FILE, inbox=None,
            hunter_store=hunter, gate=None, role_gate=control.gates["pod"],
            pod_builder=_pod_builder, pod_store=None,
        )

    asyncio.run(_go())
    assert log == ["enter", "exit"]


# --- thread role derivation ---------------------------------------------------

def test_derive_thread_role_maps_every_session_shape():
    r = RUN
    assert derive_thread_role(f"hunting:{r}") == "infra"          # bootstrap
    assert derive_thread_role(r) == "infra"                       # bare legacy
    assert derive_thread_role(f"hunting:{r}:surfer") == "infra"
    # the renamed segment and its one-window legacy alias are the same role
    assert derive_thread_role(f"hunting:{r}:threat-modeller") == "threat_modeller"
    assert derive_thread_role(f"hunting:{r}:orchestrator") == "threat_modeller"
    assert derive_thread_role(f"hunting:{r}:hunt:{FAULT_KEY}") == "hunter"
    assert derive_thread_role(
        f"hunting:{r}:pod:{FAULT_KEY}:{SPEC_FILE}") == "pod"
