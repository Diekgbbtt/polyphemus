"""Unit tier: the inbox-surfer impure shell + the single-owner produced->
consumed move primitives (tracker #172, ADR #169 Q3/Q11/Q13) - PRODUCTION-
CODE-FIRST as of the identity-based refactor (2026-08-25).

The shell (`run_delivery_tick`) is the THIN impure layer: it reads the
produced inboxes from the memory stores, calls the PURE deduction, drives the
delivery to a control plane (the T2 `RuntimeManager.schedule` with the
session-id-as-name rule, here injected as a recording stub - CODING_STANDARD
s6), and applies the moves. The mover-level tests exercise the REAL
`build_run_dispatch` `coro_for` (the T4 run-dispatch seam) on production
stores over temp roots - so the pod-dispatch DECISION is the code under test,
with fakes kept ONLY at the agent-seam boundary (the hunter/pod builder
coroutines) and the control plane. Pins the at-least-once ACs:

- admitted items move produced -> consumed;
- refused items STAY produced and are RETRIED next tick - never dropped;
- an already-live registry session is never re-dispatched (and its move
  lands - the crash-window completion);
- the produced->consumed rename is SINGLE-OWNER: only the mover calls the
  store move primitives (`HuntStore.consume_config`,
  `HunterMemoryStore.consume_spec`), and a refused tick moves nothing;
- a failed move is counted, never aborting the tick (fail-open ring, s5).

The identity-based-refactor (2026-08-25) regression pins the never-disagree
contract: a produced `specified` spec with NO parent inbox still dispatches a
pod (own-status dispatch gate), the quiesce pending-work predicate
(`run_work_remaining`) agrees with `build_run_dispatch` by construction, and
`is_run_quiesced` is reachable - a produced spec can never wedge the run.

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
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    build_run_dispatch,
    is_run_quiesced,
    run_work_remaining,
)

PROJECT = "proj-1"
RUN = "run-1"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
# The hunter memory <fault_key> is the 3-part config key (G4, ADR Q13's
# `config_id`): `_`-joined `<unit_id>_<CWE_ID>_<vulnerability_class>`, the
# config file-name stem. The 2-part revival key is NOT a fault_key. The
# canonical `::`-joined config_key is a DIFFERENT string: the identity-refactor
# joins the two on the canonical config_key.
FAULT_KEY = f"{UNIT}_{CWE}_{CLASS}"
CONFIG_KEY = f"{UNIT}::{CWE}::{CLASS}"


def _config(**overrides) -> dict:
    data = {
        "hunt_id": "hunt-1",
        "unit_id": UNIT,
        "fault_class": CWE,
        "status": "ratified",
        "vulnerability_class": CLASS,
        "prompt_template": {
            "rationale": "r", "l0_evidence": [], "research_direction": "rd",
        },
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


class RecordingControlPlane:
    """A recording dispatch stub (s6): dispatches admitted unless the session
    is refused; `live` sessions are pre-registered and never dispatched. The
    recorded coroutines are CLOSED (never run by the stub) so pytest never
    warns about un-awaited coroutines."""

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
        try:
            coro.close()
        except Exception:
            pass
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


def _write_spec(hunter, *, fault_key=FAULT_KEY, keyword="sqli", strategy="blind",
                status="specified"):
    return hunter.write_spec(
        PROJECT, fault_key,
        fault_keyword=keyword, strategy_keyword=strategy, spec=_spec(status=status),
    )


# --- the REAL run-dispatch builder (agent-seam fakes only) ----------------------
#
# `build_run_dispatch` is the code under test: the mover-level ticks below drive
# its `coro_for` with production stores on temp roots. The ONLY fakes are at the
# agent-seam boundary - the hunter/pod builder coroutines (never awaited by the
# recorder) and the control plane. `pod_store` is None (it reaches the pod
# builder only when a pod session is awaited, which the recorder never does).

def _hunter_builder_fake(*, run_id, project_id, hunt_store, hunter_store, **kw):
    """The agent-seam hunter builder: returns a no-op dispatch (never run by
    the recording control plane) + no registry - the ONLY fake."""
    async def _dispatch(config):
        return None

    return _dispatch, None


async def _pod_builder_fake(spec, **kw):
    """The agent-seam pod builder: a recording no-op envelope (never run by the
    recording control plane) - the ONLY fake."""
    return {
        "verdict": "successful", "terminal_reason": "symptom-confirmed",
        "evidence": {"trail": []}, "clean": True, "iterations": 0,
    }


def _real_coro_for(hunt, hunter, state=None):
    """The real `build_run_dispatch` `coro_for` on temp-root production stores
    with the agent-seam fakes and no gate."""
    return build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        hunt_store=hunt, hunter_store=hunter, pod_store=None,
        state=state or RunDispatchState(), gate=None,
        hunter_builder=_hunter_builder_fake, pod_builder=_pod_builder_fake,
    )


# --- the shell: admitting dispatches and moves ---------------------------------

def test_empty_inbox_yields_a_noop_tick(stores):
    hunt, hunter = stores
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.produced == 0
    assert report.dispatched == 0 and report.admitted == 0 and report.refused == 0
    assert report.moved == 0 and report.move_failed == 0


def test_admitted_config_is_dispatched_and_moves_to_consumed(stores):
    hunt, hunter = stores
    _write_config(hunt)
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(hunt, hunter),
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
        control=control, coro_for=_real_coro_for(hunt, hunter),
    )
    assert control.calls == [pod_session_id(RUN, FAULT_KEY, "sqli_blind")]
    assert report.moved == 1 and report.admitted == 1 and report.refused == 0
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1


# --- identity-based refactor: the never-disagree + no-parent wedge regression ---

def test_specified_spec_without_a_parent_inbox_still_dispatches_a_pod(stores):
    """The pod-dispatch WEDGE regression (2026-08-25): a produced `specified`
    spec with NO parent hunter inbox (and no produced/consumed parent config -
    the cross-run shape) STILL dispatches a pod. The dispatch is gated on the
    spec's OWN persisted `status == "specified"` - never on a chain-adjacent
    parent's liveness - so the mover admits it and the move lands."""
    hunt, hunter = stores
    _write_spec(hunter)                     # produced specified spec, no parent
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(hunt, hunter),
    )
    # the pod session dispatched AND moved produced -> consumed: the REAL
    # `build_run_dispatch` answered a coroutine (no None-refusal for a missing
    # parent), the control plane admitted it, the at-least-once marker landed.
    assert control.calls == [pod_session_id(RUN, FAULT_KEY, "sqli_blind")]
    assert report.admitted == 1 and report.moved == 1 and report.refused == 0
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1


def test_run_work_remaining_agrees_with_the_dispatch_gate(stores):
    """The never-disagree contract (spec #169 "Testing Decisions"): the quiesce
    pending-work predicate (`run_work_remaining`) gates on the SAME own-status
    `build_run_dispatch` gates on, so a produced `specified` spec is real work
    AND dispatchable - it can never wedge the quiesce."""
    hunt, hunter = stores
    # a produced ratified config is dispatchable work
    _write_config(hunt)
    assert run_work_remaining(PROJECT, hunt_store=hunt, hunter_store=hunter) is True
    # a produced specified spec is dispatchable work (the never-agree case that
    # used to wedge: it counted as work but could not dispatch without a parent)
    _write_spec(hunter)
    assert run_work_remaining(PROJECT, hunt_store=hunt, hunter_store=hunter) is True
    # both dispatch (real builder) and move: the work is now gone
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.admitted == 2 and report.moved == 2
    assert run_work_remaining(PROJECT, hunt_store=hunt, hunter_store=hunter) is False
    # and with nothing left and no live session, quiesce is REACHABLE - the
    # produced-spec wedge is gone
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), state=RunDispatchState(),
    )) is True


def test_undispatchable_statuses_are_not_work(stores):
    """A hypothesised spec draft and a dropped config are NOT dispatchable work:
    `run_work_remaining` says False (their status is not the dispatch gate) and
    `build_run_dispatch` refuses them - the two never disagree."""
    hunt, hunter = stores
    _write_config(hunt, status="hypothesised")
    # a dropped config stays on disk (G6), never dispatchable
    _write_config(hunt, status="dropped", vulnerability_class="CSRF")
    _write_spec(hunter, status="hypothesised")
    assert run_work_remaining(PROJECT, hunt_store=hunt, hunter_store=hunter) is False
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.dispatched == 3 and report.admitted == 0 and report.moved == 0
    assert report.refused == 3               # the builder answered None for each
    assert len(hunt.read_produced_configs(PROJECT)) == 2   # stayed produced
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == ["sqli_blind"]


# --- the shell: refusal is at-least-once, never dropped -------------------------

def test_refused_config_stays_produced_and_is_retried_next_tick(stores):
    hunt, hunter = stores
    key = _write_config(hunt)
    session = hunter_session_id(RUN, "Service:catalogue-and-discovery_CWE-639_IDOR")
    denied = RecordingControlPlane(refused={session})
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=denied, coro_for=_real_coro_for(hunt, hunter),
    )
    assert denied.calls == [session]
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    # nothing dropped: the produced record survives with its content readable
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [key]
    assert hunt.read_configs_by_key(PROJECT, key)
    # the retry: a fresh tick (the next loop lap) admits and completes the move
    report2 = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(hunt, hunter),
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
        control=denied, coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.refused == 1 and report.moved == 0
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == ["sqli_blind"]
    report2 = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(hunt, hunter),
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
        control=denied, coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.refused == 2 and report.moved == 0 and report.admitted == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [CONFIG_KEY]
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
        control=control, coro_for=_real_coro_for(hunt, hunter),
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
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [CONFIG_KEY]


def test_move_failure_is_counted_and_never_aborts_the_tick(stores, monkeypatch):
    hunt, hunter = stores
    _write_config(hunt, vulnerability_class=CLASS)
    _write_config(hunt, vulnerability_class="CSRF")

    def failing_consume(store, project_id, key):
        raise OSError("disk failure (fixture)")

    monkeypatch.setattr(hunt, "consume_config", failing_consume)
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(hunt, hunter),
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


def test_consume_spec_requires_the_3_part_config_key(tmp_path):
    """The fault_key is the 3-part config key (G4/ADR Q13): a 2-part revival
    key is the config's prefix, not its identity, and is NOT accepted."""
    hunter = HunterMemoryStore(tmp_path)
    _write_spec(hunter)
    with pytest.raises(ValueError, match="3-part"):
        hunter.consume_spec(PROJECT, f"{UNIT}::{CWE}", "sqli_blind")
    with pytest.raises(ValueError, match="3-part"):
        hunter.write_spec(
            PROJECT, f"{UNIT}::{CWE}",
            fault_keyword="sqli", strategy_keyword="blind", spec=_spec(),
        )
    with pytest.raises(ValueError, match="3-part"):
        hunter.read_spec(PROJECT, f"{UNIT}::{CWE}", "sqli", "blind")


def test_list_fault_keys_and_produced_spec_files_are_deterministic(tmp_path):
    hunter = HunterMemoryStore(tmp_path)
    _write_spec(hunter, fault_key=FAULT_KEY, keyword="sqli", strategy="blind")
    _write_spec(hunter, fault_key=FAULT_KEY, keyword="xss", strategy="reflected")
    other = f"Service:b_{CWE}_{CLASS}"          # a distinct 3-part config key
    _write_spec(hunter, fault_key=other, keyword="sqli", strategy="blind")
    assert hunter.list_fault_keys(PROJECT) == [other, FAULT_KEY]   # lexical order
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == ["sqli_blind", "xss_reflected"]
    assert hunter.produced_spec_files(PROJECT, "Service:zzz_CWE-999_X") == []


# --- the fault_key -> config_key conversion (single-sourced join key) -----------

def test_config_key_from_fault_key_converges_both_physical_forms(tmp_path):
    from polymerhus.attack.hunting.hunter_memory import (
        config_key_from_fault_key,
    )
    # the production `_`-joined folder form
    assert config_key_from_fault_key(FAULT_KEY) == CONFIG_KEY
    # the `::`-joined semantic key form (write_spec accepts both) is unchanged
    assert config_key_from_fault_key(CONFIG_KEY) == CONFIG_KEY
    # a 2-part revival key is NOT a config_key - refused (never a join key)
    with pytest.raises(ValueError, match="3-part"):
        config_key_from_fault_key(f"{UNIT}::{CWE}")


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
        control=plane, coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.refused == 1 and report.moved == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [CONFIG_KEY]

    # resumed -> the same produced item is retried and admitted this lap. This
    # is a control-plane admission test, NOT a dispatch-decision test, so the
    # scheduled coroutine is a linger stand-in for "a real session that stays
    # live" (the real `run_hunter_session` would enter the idle-loop agent
    # machinery, outside this mover test's scope).
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
        control=plane, coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.refused == 1 and report.moved == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [CONFIG_KEY]


class _NullManager:
    """A manager-shaped object with no registry (the 'no active runtime'
    stand-in for the adapter test)."""

    def run_ids(self, module):
        return []

    def schedule(self, module, coro, *, name):
        raise RuntimeError("no active runtime manager")