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
  store move primitives (`ThreatModelStore.consume_loop`,
  `HunterMemoryStore.consume_spec`), and a refused tick moves nothing;
- T4b (#387): the loop file is the ONLY hunter dispatch record - the retired
  config family is not an item, is not dispatched and is not work;
- a failed move is counted, never aborting the tick (fail-open ring, s5).

The identity-based-refactor (2026-08-25) regression pins the never-disagree
contract: a produced `ratified` spec with NO parent inbox still dispatches a
pod (own-status dispatch gate), the quiesce pending-work predicate
(`run_work_remaining`) agrees with `build_run_dispatch` by construction, and
`is_run_quiesced` is reachable - a produced spec can never wedge the run.

Also pins the store move primitives themselves (moves + at-least-once
idempotency + the absent-record False + the locked rename), and the real
`RuntimeControlPlane` adapter (ModuleAdmissionRefused -> refused). The retired
hunt-store config I/O is not exercised here (T6 removed it; the key helpers and
the residual note vocabulary lives in `test_hunt_store.py`).
"""
import asyncio
import time

import pytest

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    ProducedItem,
    RuntimeControlPlane,
    ThreatLoopItem,
    hunter_session_id,
    pod_session_id,
    read_produced_inbox,
    run_delivery_tick,
)
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    build_run_dispatch,
    is_run_quiesced,
    run_work_remaining,
)

from tests.hunting_fixtures import loop_row, produce_model

PROJECT = "proj-1"
RUN = "run-1"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
# The hunter memory key is the loop dispatch id `<unit_name>__<loop_id>` (S3
# 8.9) - never a config key; the pod's parent key IS that same loop id.
UNIT_NAME = "Service-catalogue-and-discovery"
LOOP_ID = "loop-1"
DISPATCH_ID = f"{UNIT_NAME}__{LOOP_ID}"
HUNTER_SESSION = hunter_session_id(RUN, DISPATCH_ID)


def _spec(**overrides) -> dict:
    data = {
        "status": "ratified",
        "fault_keyword": "sqli",
        "strategy_keyword": "blind",
        "verification_symptoms": ["a foreign item renders"],
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
    """The two PRODUCTION stores the dispatch path reads: the threat model
    store (the produced loop files) and the hunter memory (the produced specs).
    The hunt store is not here: nothing on the dispatch path reads it (T4b),
    and T10 removed its residual notes surface."""
    return (
        ThreatModelStore(tmp_path / "threat"),
        HunterMemoryStore(tmp_path / "hunter"),
    )


def _produce(stores, *, loops=None, run_id=RUN):
    """One produced COMPLETED valid model on the test's threat store."""
    threat, _hunter = stores
    return produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=run_id, loops=loops)


def _write_spec(hunter, *, hunt_key=DISPATCH_ID, keyword="sqli", strategy="blind",
                status="ratified"):
    return hunter.write_specs(
        PROJECT, hunt_key, [_spec(status=status, fault_keyword=keyword,
                                  strategy_keyword=strategy)])


# --- the REAL run-dispatch builder (agent-seam fakes only) ----------------------
#
# `build_run_dispatch` is the code under test: the mover-level ticks below drive
# its `coro_for` with production stores on temp roots. The ONLY fakes are at the
# agent-seam boundary - the hunter/pod builder coroutines (never awaited by the
# recorder) and the control plane. `pod_store` is None (it reaches the pod
# builder only when a pod session is awaited, which the recorder never does).

def _hunter_builder_fake(*, run_id, project_id, hunter_store, **kw):
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


def _real_coro_for(threat, hunter, state=None):
    """The real `build_run_dispatch` `coro_for` on temp-root production stores
    with the agent-seam fakes and no gate."""
    return build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        threat_store=threat, hunter_store=hunter, pod_store=None,
        state=state or RunDispatchState(), gate=None,
        hunter_builder=_hunter_builder_fake, pod_builder=_pod_builder_fake,
    )


def test_the_surfer_work_read_and_dispatch_carry_no_config_clause(stores):
    """T4b (#387): the surfer's work read and dispatch decision are loop-only.

    No config predicate, no config dispatch branch, no config refuse-once log,
    and no hunt-store parameter on any dispatch seam. A produced ratified hunt
    config is not work and has no dispatch coroutine - it is not an item at all
    (the mover's produced read never reads the config family)."""
    import inspect

    from polymerhus.attack.hunting import surfer

    for gone in ("_read_config_body", "_ratified_config", "_config_dispatch",
                 "_WARNED_UNRATIFIABLE", "HuntConfigItem"):
        assert not hasattr(surfer, gone), (
            f"surfer.{gone} retired with the config family")
    for fn in (surfer.run_work_remaining, surfer.is_run_quiesced,
               surfer.build_run_dispatch, surfer.run_surfer_loop):
        assert "hunt_store" not in inspect.signature(fn).parameters, (
            f"{fn.__name__} must not carry the retired hunt store")

    _threat, hunter = stores
    assert run_work_remaining(PROJECT, RUN, hunter_store=hunter) is False
    coro_for = build_run_dispatch(
        project_id=PROJECT, run_id=RUN, hunter_store=hunter, pod_store=None,
        state=RunDispatchState(), gate=None,
        hunter_builder=_hunter_builder_fake, pod_builder=_pod_builder_fake,
    )
    # a produced item with NO dispatch family (the retired config shape): the
    # builder refuses it instead of fabricating a config hunt
    assert coro_for(ProducedItem(
        message_id=DISPATCH_ID, session_id=hunter_session_id(RUN, DISPATCH_ID),
    )) is None


# --- the shell: admitting dispatches and moves ---------------------------------

def test_empty_inbox_yields_a_noop_tick(stores):
    threat, hunter = stores
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(threat, hunter),
    )
    assert report.produced == 0
    assert report.dispatched == 0 and report.admitted == 0 and report.refused == 0
    assert report.moved == 0 and report.move_failed == 0


def test_one_produced_loop_dispatches_a_hunter_and_moves_both_records(stores):
    """S2 8.4: the loop file IS the dispatch grain - ONE loop file admits ONE
    hunter session under the per-loop id, and the admission moves the loop file
    to consumed/ with the model document (its last loop file, S2 8.1)."""
    threat, hunter = stores
    _produce(stores)
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(threat, hunter),
    )
    assert control.calls == [HUNTER_SESSION]
    assert report.produced == 1
    assert report.dispatched == 1 and report.admitted == 1 and report.refused == 0
    assert report.moved == 1 and report.move_failed == 0
    # the produced->consumed move IS the at-least-once marker: nothing left in
    # produced/, the loop file and the model document live in consumed/
    assert threat.read_produced_loops(PROJECT) == []
    assert threat.read_completed_units(PROJECT) == [UNIT]


def test_admitted_spec_dispatches_a_pod_session_and_moves(stores):
    threat, hunter = stores
    _write_spec(hunter)
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(threat, hunter),
    )
    assert control.calls == [pod_session_id(RUN, DISPATCH_ID, "sqli_blind")]
    assert report.moved == 1 and report.admitted == 1 and report.refused == 0
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []
    assert len(hunter.read_specs(PROJECT, DISPATCH_ID, sides=("consumed",))) == 1


# --- identity-based refactor: the never-disagree + no-parent wedge regression ---

def test_a_ratified_spec_without_a_parent_inbox_still_dispatches_a_pod(stores):
    """The pod-dispatch WEDGE regression (2026-08-25): a produced `ratified`
    spec with NO parent hunter inbox STILL dispatches a pod. The dispatch is
    gated on the spec's OWN persisted `status == "ratified"` - never on a
    chain-adjacent parent's liveness - so the mover admits it and the move
    lands."""
    threat, hunter = stores
    _write_spec(hunter)                     # produced ratified spec, no parent
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(threat, hunter),
    )
    # the pod session dispatched AND moved produced -> consumed: the REAL
    # `build_run_dispatch` answered a coroutine (no None-refusal for a missing
    # parent), the control plane admitted it, the at-least-once marker landed.
    assert control.calls == [pod_session_id(RUN, DISPATCH_ID, "sqli_blind")]
    assert report.admitted == 1 and report.moved == 1 and report.refused == 0
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []
    assert len(hunter.read_specs(PROJECT, DISPATCH_ID, sides=("consumed",))) == 1


def test_run_work_remaining_agrees_with_the_dispatch_gate(stores):
    """The never-disagree contract (spec #169 "Testing Decisions"): the quiesce
    pending-work predicate (`run_work_remaining`) gates on the SAME predicates
    `build_run_dispatch` gates on, so real work is always dispatchable - it can
    never wedge the quiesce."""
    threat, hunter = stores
    # a produced loop file is dispatchable work
    _produce(stores)
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is True
    # a produced ratified spec is dispatchable work too
    _write_spec(hunter)
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is True
    # both dispatch (real builder) and move: the work is now gone
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(threat, hunter),
    )
    assert report.admitted == 2 and report.moved == 2
    # F-026: the move is admission, not completion. The tick's admitted hunter
    # did not run in this fake plane, so the consumed loop has no terminal spec
    # set yet and IS still work. The hunter's finalize settles it.
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is True
    hunter.finalize_specs(PROJECT, DISPATCH_ID, run_id=RUN)
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False
    # and with nothing left and no live session, quiesce is REACHABLE - the
    # produced-spec wedge is gone
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), state=RunDispatchState(),
    )) is True


# --- F-026: the consumed-loop recovery family -----------------------------------

def _consumed_loop(stores):
    """One loop consumed at admission: the loop file and model live in
    consumed/, and no hunter has written a terminal spec set yet."""
    threat, hunter = stores
    _produce(stores)
    assert threat.consume_loop(PROJECT, UNIT, LOOP_ID) is True
    assert threat.read_produced_loops(PROJECT) == []
    return threat, hunter


def test_a_consumed_loop_without_a_terminal_set_is_recovered(stores):
    """F-026: the produced->consumed move is admission, not completion. The
    recovery item carries the consumed model document (never a re-model) and
    the same loop identity/session; the hunter's zero-spec finalize settles it."""
    threat, hunter = _consumed_loop(stores)

    inbox = read_produced_inbox(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter)

    loops = [item for item in inbox.items if isinstance(item, ThreatLoopItem)]
    assert len(loops) == 1
    item = loops[0]
    assert item.recovered is True
    assert item.message_id == DISPATCH_ID
    assert item.session_id == HUNTER_SESSION
    assert item.model is not None and item.model["unit_id"] == UNIT
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is True

    hunter.finalize_specs(PROJECT, DISPATCH_ID, run_id=RUN)

    assert [i for i in read_produced_inbox(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter).items
        if isinstance(i, ThreatLoopItem)] == []
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False


def test_a_consumed_loop_is_recovered_while_its_sibling_stays_produced(stores):
    """F-026 model dependency: a multi-loop unit consumes its model only with
    the LAST loop. The consumed loop is recovered from the still-produced
    model, while the sibling produced loop stays a normal dispatch candidate."""
    threat, hunter = stores
    _produce(stores, loops=[loop_row(), loop_row(likelihood="low")])
    assert threat.consume_loop(PROJECT, UNIT, "loop-1") is True
    assert [e["unit_id"] for e in threat.read_consumed_loops(PROJECT)] == [UNIT]
    assert [e["unit_id"] for e in threat.read_produced_loops(PROJECT)] == [UNIT]

    inbox = read_produced_inbox(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter)

    recovered = [i for i in inbox.items
                 if isinstance(i, ThreatLoopItem) and i.recovered]
    produced = [i for i in inbox.items
                if isinstance(i, ThreatLoopItem) and not i.recovered]
    assert [i.loop_id for i in recovered] == ["loop-1"]
    assert [i.loop_id for i in produced] == ["loop-2"]
    assert recovered[0].model is not None
    assert recovered[0].model["unit_id"] == UNIT


def test_a_terminal_set_from_another_run_does_not_settle_this_loop(stores):
    """The terminal-set marker is run-scoped, like the loop body: a stale marker
    from an earlier run must not suppress recovery of the current run's loop."""
    threat, hunter = _consumed_loop(stores)
    hunter.finalize_specs(PROJECT, DISPATCH_ID, run_id="run-earlier")

    assert any(
        isinstance(item, ThreatLoopItem) and item.recovered
        for item in read_produced_inbox(
            PROJECT, RUN, threat_store=threat, hunter_store=hunter).items
    )

    hunter.finalize_specs(PROJECT, DISPATCH_ID, run_id=RUN)
    assert not any(
        isinstance(item, ThreatLoopItem)
        for item in read_produced_inbox(
            PROJECT, RUN, threat_store=threat, hunter_store=hunter).items
    )


def test_a_recovered_loop_redispatches_without_a_second_move(stores):
    """At-least-once: a recovered loop is dispatched again, and its move is
    already satisfied - the tick lands no second produced->consumed move. A live
    recovered session is never re-dispatched."""
    threat, hunter = _consumed_loop(stores)

    live = RecordingControlPlane(live={HUNTER_SESSION})
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=live, coro_for=_real_coro_for(threat, hunter),
    )
    assert live.calls == []
    assert report.dispatched == 0 and report.moved == 0

    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(threat, hunter),
    )
    assert control.calls == [HUNTER_SESSION]
    assert report.produced == 1 and report.admitted == 1
    assert report.moved == 0 and report.models_consumed == 0
    # the loop stays in consumed/ (the move is already satisfied), and the
    # still-unsettled hunter keeps the work pending for the next tick
    assert [loop["loop_id"] for loop in
            threat.read_consumed_loops(PROJECT)[0]["loops"]] == [LOOP_ID]
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is True

    hunter.finalize_specs(PROJECT, DISPATCH_ID, run_id=RUN)
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False


def test_a_foreign_run_consumed_loop_is_not_recovered(stores):
    """The recovery read is run-scoped: another run's consumed loop is its own
    mover's work, never stolen by this run."""
    threat, hunter = stores
    _produce(stores, run_id="run-other")
    assert threat.consume_loop(PROJECT, UNIT, LOOP_ID) is True

    assert read_produced_inbox(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter).items == ()
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False


def test_undispatchable_statuses_are_not_work(stores):
    """A hypothesised spec draft is NOT dispatchable work: `run_work_remaining`
    says False (its status is not the dispatch gate) and the produced read does
    not even hand it over as an item - the two never disagree. A malformed loop
    file is refused by the ONE loop validity predicate instead, and never counts
    as work either."""
    threat, hunter = stores
    _write_spec(hunter, status="hypothesised")
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False
    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(threat, hunter),
    )
    # the drafted spec is not even an ITEM - the produced read applies the same
    # own-status gate - so nothing is attempted at all
    assert report.produced == 0 and report.dispatched == 0 and report.moved == 0
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == ["sqli_blind"]


# --- the shell: refusal is at-least-once, never dropped -------------------------

def test_refused_loop_stays_produced_and_is_retried_next_tick(stores):
    threat, hunter = stores
    _produce(stores)
    denied = RecordingControlPlane(refused={HUNTER_SESSION})
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=denied, coro_for=_real_coro_for(threat, hunter),
    )
    assert denied.calls == [HUNTER_SESSION]
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    # nothing dropped: the produced loop file survives, readable
    assert [entry["loop_id"] for entry in
            threat.read_produced_loops(PROJECT)[0]["loops"]] == [LOOP_ID]
    # the retry: a fresh tick (the next loop lap) admits and completes the move
    report2 = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(threat, hunter),
    )
    assert report2.moved == 1 and report2.refused == 0
    assert threat.read_produced_loops(PROJECT) == []


def test_refused_spec_stays_produced_and_is_retried_next_tick(stores):
    threat, hunter = stores
    _write_spec(hunter)
    session = pod_session_id(RUN, DISPATCH_ID, "sqli_blind")
    denied = RecordingControlPlane(refused={session})
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=denied, coro_for=_real_coro_for(threat, hunter),
    )
    assert report.refused == 1 and report.moved == 0
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == ["sqli_blind"]
    report2 = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(threat, hunter),
    )
    assert report2.moved == 1
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []


def test_a_fully_refused_tick_moves_nothing_for_either_family(stores):
    threat, hunter = stores
    _produce(stores)
    _write_spec(hunter)
    denied = RecordingControlPlane(refused={
        HUNTER_SESSION,
        pod_session_id(RUN, DISPATCH_ID, "sqli_blind"),
    })
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=denied, coro_for=_real_coro_for(threat, hunter),
    )
    assert report.refused == 2 and report.moved == 0 and report.admitted == 0
    assert [entry["loop_id"] for entry in
            threat.read_produced_loops(PROJECT)[0]["loops"]] == [LOOP_ID]
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == ["sqli_blind"]


# --- the shell: the live registry is the double-dispatch defense ----------------

def test_live_session_is_never_redispatched_and_its_move_lands(stores):
    """The R3 crash window: the dispatch landed (session live in the registry)
    but the move did not - the item is still produced. The mover re-dispatches
    NOTHING and completes the marker by moving produced -> consumed."""
    threat, hunter = stores
    _produce(stores)
    control = RecordingControlPlane(live={HUNTER_SESSION})
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=control, coro_for=_real_coro_for(threat, hunter),
    )
    assert control.calls == []             # no double dispatch
    assert report.dispatched == 0 and report.refused == 0
    assert report.moved == 1               # registry-confirmed: marker stamped
    assert threat.read_produced_loops(PROJECT) == []


# --- the shell: fail-open rings (never abort the tick) --------------------------

def test_coro_builder_failure_is_refused_and_stays_produced(stores):
    threat, hunter = stores
    _produce(stores)

    def broken(item):
        raise RuntimeError("no producer coroutine wired (designed-not-built)")

    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=broken,
    )
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    assert [entry["loop_id"] for entry in
            threat.read_produced_loops(PROJECT)[0]["loops"]] == [LOOP_ID]


def test_move_failure_is_counted_and_never_aborts_the_tick(stores, monkeypatch):
    threat, hunter = stores
    _produce(stores, loops=[loop_row(), loop_row(likelihood="critical")])

    def failing_consume(project_id, unit_id, loop_id):
        raise OSError("disk failure (fixture)")

    monkeypatch.setattr(threat, "consume_loop", failing_consume)
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(threat, hunter),
    )
    assert report.admitted == 2 and report.moved == 0
    assert report.move_failed == 2
    assert report.dispatched == 2            # the tick completed, nothing raised
    assert len(threat.read_produced_loops(PROJECT)[0]["loops"]) == 2


# --- the store move primitives (single-owner, at-least-once idempotency) --------

def test_consume_spec_moves_and_is_at_least_once_idempotent(tmp_path):
    hunter = HunterMemoryStore(tmp_path)
    _write_spec(hunter)
    assert hunter.consume_spec(PROJECT, DISPATCH_ID, "sqli_blind") is True
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []
    assert len(hunter.read_specs(PROJECT, DISPATCH_ID, sides=("consumed",))) == 1
    assert hunter.consume_spec(PROJECT, DISPATCH_ID, "sqli_blind") is True
    assert hunter.consume_spec(PROJECT, DISPATCH_ID, "missing") is False


def test_consume_spec_rejects_path_traversal_spec_files(tmp_path):
    hunter = HunterMemoryStore(tmp_path)
    for bad in ("../escape", "a/b", ".", ".."):
        with pytest.raises(ValueError):
            hunter.consume_spec(PROJECT, DISPATCH_ID, bad)


def test_consume_spec_requires_a_safe_hunt_key(tmp_path):
    """The hunt key is a safe single path component (S3 8.9); a traversal key
    is a caller defect and is refused by the store."""
    hunter = HunterMemoryStore(tmp_path)
    _write_spec(hunter)
    with pytest.raises(ValueError):
        hunter.consume_spec(PROJECT, "../escape", "sqli_blind")
    with pytest.raises(ValueError):
        hunter.write_specs(PROJECT, "../escape", [_spec()])


def test_list_hunt_keys_and_produced_spec_files_are_deterministic(tmp_path):
    hunter = HunterMemoryStore(tmp_path)
    hunter.write_specs(PROJECT, DISPATCH_ID, [
        _spec(status="ratified", fault_keyword="sqli", strategy_keyword="blind"),
        _spec(status="ratified", fault_keyword="xss", strategy_keyword="reflected"),
    ])
    other = "Service-b__loop-2"                 # a distinct loop dispatch id
    _write_spec(hunter, hunt_key=other, keyword="sqli", strategy="blind")
    assert hunter.list_hunt_keys(PROJECT) == [other, DISPATCH_ID]  # lexical order
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == ["sqli_blind", "xss_reflected"]
    assert hunter.produced_spec_files(PROJECT, "Service-zzz__loop-9") == []


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
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN)
    plane = RuntimeControlPlane(runtime=runtime)

    # paused -> the shared gate refuses admission (T2's ModuleAdmissionRefused)
    runtime.pause("hunting")
    assert runtime.state("hunting") == ModuleState.PAUSED
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(threat, hunter),
    )
    assert report.refused == 1 and report.moved == 0
    assert [entry["loop_id"] for entry in
            threat.read_produced_loops(PROJECT)[0]["loops"]] == [LOOP_ID]

    # resumed -> the same produced item is retried and admitted this lap. This
    # is a control-plane admission test, NOT a dispatch-decision test, so the
    # scheduled coroutine is a linger stand-in for "a real session that stays
    # live" (the real `run_hunter_session` would enter the idle-loop agent
    # machinery, outside this mover test's scope).
    runtime.resume("hunting")
    async def linger():
        await asyncio.sleep(30)
    report2 = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=plane, coro_for=lambda item: linger(),
    )
    assert report2.moved == 1 and report2.refused == 0
    # the session registered under its Q13 session id (then reaped)
    _wait_until(lambda: HUNTER_SESSION in runtime.run_ids("hunting"), timeout=15)
    runtime.cancel_run("hunting", HUNTER_SESSION)
    _wait_until(lambda: runtime.run_ids("hunting") == [], timeout=15)
    assert threat.read_produced_loops(PROJECT) == []


def test_runtime_plane_without_a_manager_refuses_fail_open(tmp_path):
    """No active manager -> the adapter degrades to refused (fail-open): the
    item stays produced, never dropped, never a raise."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN)
    plane = RuntimeControlPlane(runtime=_NullManager())
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(threat, hunter),
    )
    assert report.refused == 1 and report.moved == 0
    assert [entry["loop_id"] for entry in
            threat.read_produced_loops(PROJECT)[0]["loops"]] == [LOOP_ID]


class _NullManager:
    """A manager-shaped object with no registry (the 'no active runtime'
    stand-in for the adapter test)."""

    def run_ids(self, module):
        return []

    def schedule(self, module, coro, *, name):
        raise RuntimeError("no active runtime manager")


# --- the hunter idle loop threads the project's usage scope --------------------

def test_hunter_idle_loop_threads_the_project_as_usage_scope(tmp_path, monkeypatch):
    """The idle-loop session's tokens are attributed to the run's project."""
    import contextlib
    import types

    import polymerhus.app.llm.actor as _A
    import polymerhus.app.llm.checkpoints as _CP
    from polymerhus.attack.hunting.surfer import _run_hunter_idle

    seen = {}

    async def fake_run_session_agent(role, thread, initial, **kw):
        seen.update(kw)
        return None

    monkeypatch.setattr(_A, "run_session_agent", fake_run_session_agent)
    monkeypatch.setattr(_CP, "get_session_checkpointer", lambda: object())
    monkeypatch.setattr(_CP, "module_context", lambda *_: contextlib.nullcontext())
    binding = types.SimpleNamespace(tools=[], middleware=[], context={})
    monkeypatch.setattr(
        "polymerhus.app.auth.seams.auth_capable_binding", lambda *a, **k: binding)

    hunt_key = "Service-a__loop-1"
    state = RunDispatchState()
    state.hunter_inboxes[hunt_key] = _A.AgentInbox()
    asyncio.run(_run_hunter_idle(
        project_id=PROJECT, run_id=RUN, hunt_key=hunt_key,
        hunter_store=HunterMemoryStore(tmp_path / "hunter"), state=state))
    assert seen["usage_scope"] == PROJECT
