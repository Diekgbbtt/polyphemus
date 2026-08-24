"""Unit tier: the inbox-surfer impure shell + the single-owner produced->
consumed move primitives (tracker #172, ADR #169 Q3/Q11/Q13).

The shell (`run_delivery_tick`) is the THIN impure layer: it reads the
produced inboxes from the memory stores, calls the PURE deduction, drives the
delivery to a control plane (the T2 `RuntimeManager.schedule` with the
session-id-as-name rule, here injected as a recording stub - CODING_STANDARD
s6), and applies the moves. It does NO reasoning of its own - every decision
is in the deduction. Pins the at-least-once ACs:

- admitted items move produced -> consumed;
- refused items STAY produced and are RETRIED next tick - never dropped;
- an already-live registry session is never re-dispatched (and its move
  lands - the crash-window completion);
- the produced->consumed rename is SINGLE-OWNER: only the mover calls the
  store move primitives (`HuntStore.consume_config`,
  `HunterMemoryStore.consume_spec`), and a refused tick moves nothing;
- a failed move is counted, never aborting the tick (fail-open ring, s5).

Also pins the store move primitives themselves (moves + at-least-once
idempotency + the absent-record False + the locked rename), and the real
`RuntimeControlPlane` adapter (ModuleAdmissionRefused -> refused).
"""
import asyncio
import time

import pytest

from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    RuntimeControlPlane,
    hunter_session_id,
    pod_session_id,
    run_delivery_tick,
)

PROJECT = "proj-1"
RUN = "run-1"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
FAULT_KEY = f"{UNIT}::{CWE}"


def _config(**overrides) -> dict:
    data = {
        "hunt_id": "hunt-1",
        "unit_id": UNIT,
        "fault_class": CWE,
        "status": "ratified",
        "vulnerability_class": CLASS,
    }
    data.update(overrides)
    return data


def _spec(**overrides) -> dict:
    data = {
        "spec_id": "sqli_blind",
        "fault_key": FAULT_KEY,
        "fault": {},
        "strategy": "blind",
        "status": "specified",
    }
    data.update(overrides)
    return data


async def _noop_coro():
    return None


def _stub_coro(item):
    return _noop_coro()


class RecordingControlPlane:
    """A recording dispatch stub (s6): dispatches admitted unless the session
    is refused; `live` sessions are pre-registered and never dispatched."""

    def __init__(self, refused=(), live=()):
        self._refused = set(refused)
        self._live = set(live)
        self.calls: list[str] = []
        self.scheduled: list = []

    def live_session_ids(self):
        return set(self._live)

    def dispatch(self, session_id, coro):
        self.calls.append(session_id)
        self.scheduled.append(coro)
        return session_id not in self._refused


def _wait_until(pred, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


@pytest.fixture
def stores(tmp_path):
    return (
        HuntStore(tmp_path / "hunts"),
        HunterMemoryStore(tmp_path / "hunter"),
    )


def _write_config(store, **overrides) -> str:
    return store.write_config(PROJECT, _config(**overrides))


def _write_spec(hunter, *, fault_key=FAULT_KEY, keyword="sqli", strategy="blind"):
    return hunter.write_spec(
        PROJECT, fault_key,
        fault_keyword=keyword, strategy_keyword=strategy, spec=_spec(),
    )


# --- the shell: admitting dispatches and moves ---------------------------------

def test_empty_inbox_yields_a_noop_tick(stores):
    hunt, hunter = stores
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_stub_coro,
    )
    assert report.produced == 0
    assert report.dispatched == 0 and report.admitted == 0 and report.refused == 0
    assert report.moved == 0 and report.move_failed == 0


def test_admitted_config_is_dispatched_and_moves_to_consumed(stores):
    hunt, hunter = stores
    key = _write_config(hunt)
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, coro_for=_stub_coro,
    )
    assert control.calls == ["hunting:run-1:hunt:Service:catalogue-and-discovery_CWE-639_IDOR"]
    assert report.produced == 1
    assert report.dispatched == 1 and report.admitted == 1 and report.refused == 0
    assert report.moved == 1 and report.move_failed == 0
    # the produced->consumed move IS the at-least-once marker: nothing left
    # in produced, the config is readable on the consumed side
    assert hunt.read_produced_configs(PROJECT) == []
    assert len(hunt.read_configs(PROJECT)) == 1


def test_admitted_spec_dispatches_a_pod_session_and_moves(stores):
    hunt, hunter = stores
    _write_spec(hunter)
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, coro_for=_stub_coro,
    )
    assert control.calls == [pod_session_id(RUN, FAULT_KEY, "sqli_blind")]
    assert report.moved == 1 and report.admitted == 1 and report.refused == 0
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1


# --- the shell: refusal is at-least-once, never dropped -------------------------

def test_refused_config_stays_produced_and_is_retried_next_tick(stores):
    hunt, hunter = stores
    key = _write_config(hunt)
    session = hunter_session_id(RUN, "Service:catalogue-and-discovery_CWE-639_IDOR")
    denied = RecordingControlPlane(refused={session})
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=denied, coro_for=_stub_coro,
    )
    assert denied.calls == [session]
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    # nothing dropped: the produced record survives with its content readable
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [key]
    assert hunt.read_configs_by_key(PROJECT, key)
    # the retry: a fresh tick (the next loop lap) admits and completes the move
    report2 = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_stub_coro,
    )
    assert report2.moved == 1 and report2.refused == 0
    assert hunt.read_produced_configs(PROJECT) == []


def test_refused_spec_stays_produced_and_is_retried_next_tick(stores):
    hunt, hunter = stores
    _write_spec(hunter)
    session = pod_session_id(RUN, FAULT_KEY, "sqli_blind")
    denied = RecordingControlPlane(refused={session})
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=denied, coro_for=_stub_coro,
    )
    assert report.refused == 1 and report.moved == 0
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == ["sqli_blind"]
    report2 = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_stub_coro,
    )
    assert report2.moved == 1
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []


def test_a_fully_refused_tick_moves_nothing_for_either_family(stores):
    hunt, hunter = stores
    _write_config(hunt)
    _write_spec(hunter)
    denied = RecordingControlPlane(refused={
        hunter_session_id(RUN, "Service:catalogue-and-discovery_CWE-639_IDOR"),
        pod_session_id(RUN, FAULT_KEY, "sqli_blind"),
    })
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=denied, coro_for=_stub_coro,
    )
    assert report.refused == 2 and report.moved == 0 and report.admitted == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [
        f"{UNIT}::{CWE}::{CLASS}"]
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == ["sqli_blind"]


# --- the shell: the live registry is the double-dispatch defense ----------------

def test_live_session_is_never_redispatched_and_its_move_lands(stores):
    """The R3 crash window: the dispatch landed (session live in the registry)
    but the move did not - the item is still produced. The mover re-dispatches
    NOTHING and completes the marker by moving produced -> consumed."""
    hunt, hunter = stores
    _write_config(hunt)
    session = hunter_session_id(RUN, "Service:catalogue-and-discovery_CWE-639_IDOR")
    control = RecordingControlPlane(live={session})
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, coro_for=_stub_coro,
    )
    assert control.calls == []             # no double dispatch
    assert report.dispatched == 0 and report.refused == 0
    assert report.moved == 1               # registry-confirmed: marker stamped
    assert hunt.read_produced_configs(PROJECT) == []


# --- the shell: fail-open rings (never abort the tick) --------------------------

def test_coro_builder_failure_is_refused_and_stays_produced(stores):
    hunt, hunter = stores
    _write_config(hunt)

    def broken(item):
        raise RuntimeError("no producer coroutine wired (designed-not-built)")

    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=broken,
    )
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [
        f"{UNIT}::{CWE}::{CLASS}"]


def test_move_failure_is_counted_and_never_aborts_the_tick(stores, monkeypatch):
    hunt, hunter = stores
    _write_config(hunt, vulnerability_class=CLASS)
    _write_config(hunt, vulnerability_class="CSRF")

    def failing_consume(store, project_id, key):
        raise OSError("disk failure (fixture)")

    monkeypatch.setattr(hunt, "consume_config", failing_consume)
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_stub_coro,
    )
    assert report.admitted == 2 and report.moved == 0
    assert report.move_failed == 2
    assert report.dispatched == 2            # the tick completed, nothing raised
    assert len(hunt.read_configs(PROJECT)) == 2


# --- the store move primitives (single-owner, at-least-once idempotency) --------

def test_consume_config_moves_and_is_at_least_once_idempotent(tmp_path):
    store = HuntStore(tmp_path)
    key = store.write_config(PROJECT, _config())
    assert store.consume_config(PROJECT, key) is True
    assert store.read_produced_configs(PROJECT) == []
    assert len(store.read_configs(PROJECT)) == 1
    # a second consume of an already-consumed record is a True no-op
    assert store.consume_config(PROJECT, key) is True
    # an absent record is False (nothing to move)
    assert store.consume_config(PROJECT, "x::CWE-1::y") is False


def test_consume_config_requires_the_full_semantic_key(tmp_path):
    store = HuntStore(tmp_path)
    _write_config(store)
    with pytest.raises(ValueError, match="3-part"):
        store.consume_config(PROJECT, f"{UNIT}::{CWE}")   # 2-part is a prefix


def test_consume_config_round_trips_the_carried_bare_class(tmp_path):
    store = HuntStore(tmp_path)
    key = store.write_config(PROJECT, _config(vulnerability_class=""))
    assert key == f"{UNIT}::{CWE}::"
    assert store.consume_config(PROJECT, key) is True
    assert store.read_produced_configs(PROJECT) == []
    assert len(store.read_configs(PROJECT)) == 1


def test_read_produced_configs_returns_only_the_produced_side(tmp_path):
    store = HuntStore(tmp_path)
    key_a = _write_config(store, vulnerability_class=CLASS)
    _write_config(store, vulnerability_class="CSRF")
    store.consume_config(PROJECT, key_a)
    produced = store.read_produced_configs(PROJECT)
    assert [k for k, _ in produced] == [f"{UNIT}::{CWE}::CSRF"]
    assert [name for _, name in produced] == ["Service:catalogue-and-discovery_CWE-639_CSRF.yaml"]


def test_consume_spec_moves_and_is_at_least_once_idempotent(tmp_path):
    hunter = HunterMemoryStore(tmp_path)
    _write_spec(hunter)
    assert hunter.consume_spec(PROJECT, FAULT_KEY, "sqli_blind") is True
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1
    assert hunter.consume_spec(PROJECT, FAULT_KEY, "sqli_blind") is True
    assert hunter.consume_spec(PROJECT, FAULT_KEY, "missing") is False


def test_consume_spec_rejects_path_traversal_spec_files(tmp_path):
    hunter = HunterMemoryStore(tmp_path)
    for bad in ("../escape", "a/b", ".", ".."):
        with pytest.raises(ValueError):
            hunter.consume_spec(PROJECT, FAULT_KEY, bad)


def test_list_fault_keys_and_produced_spec_files_are_deterministic(tmp_path):
    hunter = HunterMemoryStore(tmp_path)
    _write_spec(hunter, fault_key=FAULT_KEY, keyword="sqli", strategy="blind")
    _write_spec(hunter, fault_key=FAULT_KEY, keyword="xss", strategy="reflected")
    other = f"Service:b::{CWE}"
    _write_spec(hunter, fault_key=other, keyword="sqli", strategy="blind")
    assert hunter.list_fault_keys(PROJECT) == [other, FAULT_KEY]   # lexical order
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == ["sqli_blind", "xss_reflected"]
    assert hunter.produced_spec_files(PROJECT, "nope") == []


# --- the real control-plane adapter: ModuleAdmissionRefused is the refusal ------


@pytest.fixture
def runtime():
    from polymerhus.app.runtime import RuntimeManager
    rm = RuntimeManager()
    rm.start()
    try:
        yield rm
    finally:
        rm.shutdown()


def test_runtime_plane_refuses_while_paused_then_admits_after_resume(
    tmp_path, runtime,
):
    from polymerhus.app.runtime import ModuleState

    runtime.register_module("hunting")
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_config(hunt)
    session = hunter_session_id(RUN, "Service:catalogue-and-discovery_CWE-639_IDOR")
    plane = RuntimeControlPlane(runtime=runtime)

    # paused -> the shared gate refuses admission (T2's ModuleAdmissionRefused)
    runtime.pause("hunting")
    assert runtime.state("hunting") == ModuleState.PAUSED
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=plane, coro_for=_stub_coro,
    )
    assert report.refused == 1 and report.moved == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [
        f"{UNIT}::{CWE}::{CLASS}"]

    # resumed -> the same produced item is retried and admitted this lap
    runtime.resume("hunting")
    async def linger():
        await asyncio.sleep(30)
    report2 = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=plane, coro_for=lambda item: linger(),
    )
    assert report2.moved == 1 and report2.refused == 0
    # the session registered under its Q13 session id (then reaped)
    _wait_until(lambda: session in runtime.run_ids("hunting"), timeout=15)
    runtime.cancel_run("hunting", session)
    _wait_until(lambda: runtime.run_ids("hunting") == [], timeout=15)
    assert hunt.read_produced_configs(PROJECT) == []


def test_runtime_plane_without_a_manager_refuses_fail_open(tmp_path):
    """No active manager -> the adapter degrades to refused (fail-open): the
    item stays produced, never dropped, never a raise."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_config(hunt)
    plane = RuntimeControlPlane(runtime=_NullManager())
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=plane, coro_for=_stub_coro,
    )
    assert report.refused == 1 and report.moved == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [
        f"{UNIT}::{CWE}::{CLASS}"]


class _NullManager:
    """A manager-shaped object with no registry (the 'no active runtime'
    stand-in for the adapter test)."""

    def run_ids(self, module):
        return []

    def schedule(self, module, coro, *, name):
        raise RuntimeError("no active runtime manager")