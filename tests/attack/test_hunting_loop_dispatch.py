"""Unit tier: the per-loop dispatch (T4, #377; S2 8, S1 7.6; S3 8.7/8.9).

The loop file is the dispatch grain: ONE produced loop file dispatches ONE
hunter session, the payload is materialised at dispatch time from the model
document, the mover consumes the loop file on admission and the model document
with its last loop file, and the run's produced read is cross-unit and
run-scoped.

Every test drives the REAL stores (the `ThreatModelStore` and the
`HunterMemoryStore`) on a temporary root; the agent seams (the hunter/pod
session coroutines) and the control plane are the injected fakes.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_payload import materialise_hunter_payload
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.app.llm.actor import AgentMessage

from tests.hunting_fixtures import modeller_gate_payloads

PROJECT = "proj-loop"
RUN = "run-loop-1"
UNIT = "Service:catalogue-and-discovery"
UNIT_NAME = "Service-catalogue-and-discovery"


@pytest.fixture
def threat_store(tmp_path):
    return ThreatModelStore(tmp_path / "threat")


@pytest.fixture(autouse=True)
def _fresh_refusal_log():
    """The refuse-once log is process-global (the mover re-reads the produced
    family every tick, so the guard must outlive one read): each test starts from
    a clean one, so a refusal in a sibling test cannot silence this one. The run
    terminal clears it in production."""
    from polymerhus.attack.hunting.mover import clear_refusal_log

    clear_refusal_log(PROJECT, RUN)
    clear_refusal_log("gap-proj", "gap-run")   # the whole-pipeline tests' run
    yield
    clear_refusal_log(PROJECT, RUN)
    clear_refusal_log("gap-proj", "gap-run")


@pytest.fixture
def hunter_store(tmp_path):
    return HunterMemoryStore(tmp_path / "hunter")


def produce_model(store, *, unit_id=UNIT, run_id=RUN, loops=None) -> str:
    """Drive the REAL store's five gates to COMPLETED for `unit_id` - the
    produced COMPLETED valid model the surfer dispatches from. `loops` overrides
    the COMPLETED write's loop rows (the sequencing fixtures)."""
    payloads = modeller_gate_payloads()
    from polymerhus.attack.hunting.threat_model import ModelState

    for state in ModelState:
        sections = dict(payloads[state])
        if state is ModelState.COMPLETED and loops is not None:
            sections["loops"] = loops
        store.write_sections(PROJECT, unit_id, state, sections, run_id=run_id)
    return unit_id


def _loop_row(**overrides) -> dict:
    row = {
        "fault_ref": "fault-1",
        "vulnerability_ref": "v-1",
        "failure_mode_refs": ["fm-1"],
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "likelihood": "high",
        "likelihood_rationale": "The item id is attacker-controlled and unauthenticated.",
        "risk_factors": {
            "attack_vector": "network",
            "attack_requirements": "none",
            "privileges_required": "none",
            "complexity": "low",
        },
        "confidence": "INFERRED",
        "evidences": [{"kind": "request", "ref": "GET /catalogue?id=2"}],
    }
    row.update(overrides)
    return row


# --- the payload (S2 8.2) ------------------------------------------------------

def test_the_payload_carries_the_dispatch_context_and_nothing_more(threat_store):
    """S2 8.2: the payload carries the loop record, the unit identity, the
    relevant sharpening, the trust boundary, the fault, the classes, the
    evidence, the likelihood rationale, the confidence and the target context -
    and does NOT carry the failure modes, a narrowed vector, a `HuntConfig`, or
    a payload vector space."""
    produce_model(threat_store)
    model = threat_store.read_model(PROJECT, UNIT)
    loop_file = threat_store.read_loop_files(PROJECT, UNIT)[0]
    loop = loop_file["loop"]

    payload = materialise_hunter_payload(
        model, loop_file, dispatch_id=f"{UNIT_NAME}__loop-1",
    )

    # the POSITIVE list (S2 8.2): the payload carries exactly these keys and no
    # others - the failure modes, a narrowed vector, a `HuntConfig` and a payload
    # vector space stay in the model (T4a review F4: `assumption` and `suite_gap`
    # were extra; `programming_fault` and the loop record already carry them)
    assert set(payload) == {
        "dispatch_id", "run_id", "loop_id", "unit_id", "unit_kind", "loop",
        "technical_sharpening", "trust_agreement", "dynamic_state",
        "programming_fault", "canonical_class", "web_vulnerability_class",
        "evidence", "likelihood", "likelihood_rationale",
        "vulnerability_rationale", "confidence", "target_context",
    }
    assert payload["dispatch_id"] == f"{UNIT_NAME}__loop-1"
    assert payload["loop_id"] == "loop-1"
    assert payload["unit_id"] == UNIT
    assert payload["unit_kind"] == "service"
    assert payload["loop"]["id"] == "loop-1"
    # the relevant sharpening: the interface agreement the trust agreement refs,
    # plus the control-flow and data-flow overview
    sharpening = payload["technical_sharpening"]
    assert [a["id"] for a in sharpening["interface_agreements"]] == ["ia-1"]
    assert [a["id"] for a in sharpening["control_flows"]] == ["cf-1"]
    assert [a["id"] for a in sharpening["data_flows"]] == ["df-1"]
    # the relevant trust agreement (the assumption's boundary_ref)
    assert payload["trust_agreement"]["id"] == "ta-1"
    # the programming fault
    assert payload["programming_fault"]["id"] == "fault-1"
    assert payload["canonical_class"] == "IDOR"
    assert payload["web_vulnerability_class"] == "idor"
    # the evidence pointers and the target context the spec's identity needs
    assert payload["evidence"] == loop["evidences"]
    assert payload["target_context"] == {
        "unit_id": UNIT, "unit_kind": "service",
        "baseline_refs": ["GET /catalogue"],
    }
    assert payload["likelihood"] == "high"
    assert payload["likelihood_rationale"] == loop["likelihood_rationale"]
    assert payload["vulnerability_rationale"] == "An anonymous caller reads another user's item."
    assert payload["confidence"] == "INFERRED"
    # the prohibitions (S2 8.2)
    assert "failure_modes" not in payload
    assert "payload_vector_space" not in payload
    assert "hunt_config" not in payload
    assert "vector" not in payload


# --- one loop file dispatches one hunter (S2 2.2, 8.4) -------------------------

class RecordingControlPlane:
    """A recording dispatch stub (s6): admits unless the session is refused;
    `live` sessions are pre-registered. The recorded coroutines are CLOSED (never
    run by the stub) so pytest never warns about un-awaited coroutines."""

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


def _hunter_builder(*, run_id, project_id, hunter_store, **kw):
    """The agent-seam hunter builder: records the payload it is handed and
    returns a no-op dispatch + no registry (the ONLY fake)."""
    async def _dispatch(payload):
        return None

    _dispatch.seen = []
    return _dispatch, None


def _payload_recorder(*, state=None):
    """A hunter builder seam whose dispatch records the payload it receives - and,
    when a `state` is given, the run-local registration it observes DURING the
    graph stretch (the registration lands inside the session coroutine, T4a
    review I1)."""
    seen: list = []
    snapshots: list = []

    def builder(*, run_id, project_id, hunter_store, **kw):
        async def _dispatch(payload):
            seen.append(payload)
            if state is not None:
                snapshots.append((
                    dict(state.loop_likelihoods), set(state.hunters_in_graph),
                ))
                # settle the idle loop up front (the run terminal's own verb): the
                # session's graph stretch has run, so it must not wait for a later
                # terminal - the registration (the inbox) exists by now (I1)
                for inbox in state.hunter_inboxes.values():
                    inbox.post_nowait(AgentMessage(kind="settle"))

        return _dispatch, None

    return builder, seen, snapshots


def _coro_for(threat_store, hunter_store, *, state=None, hunter_builder=None,
              control=None):
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch

    state = state if state is not None else RunDispatchState()
    return build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        threat_store=threat_store, hunt_store=HuntStore(),
        hunter_store=hunter_store, pod_store=None,
        state=state, gate=None,
        hunter_builder=hunter_builder or _hunter_builder,
        pod_builder=_pod_builder_fake, control=control,
        hunter_payload_capable=state.hunter_payload_capable,
    )


async def _pod_builder_fake(spec, **kw):
    return {"verdict": "unsuccessful", "terminal_reason": "space-exhausted"}


def test_one_loop_file_dispatches_one_hunter_and_moves_both_records(
        threat_store, hunter_store):
    """S2 8.4: the loop file IS the dispatch grain - ONE loop file admits ONE
    hunter session under the per-loop id, and the admission moves the loop file
    to consumed/ with the model document (its last loop file, S2 8.1)."""
    from polymerhus.attack.hunting.mover import run_delivery_tick

    produce_model(threat_store)
    control = RecordingControlPlane()

    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control, coro_for=_coro_for(threat_store, hunter_store),
    )

    assert control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1"]
    assert report.produced == 1
    assert report.admitted == 1 and report.refused == 0
    assert report.moved == 1 and report.paused == 0
    # the produced->consumed move is the admission marker (S2 8.4): the loop
    # file and the model document both left produced/
    assert threat_store.read_produced_loops(PROJECT) == []
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    assert threat_store.read_loop_files(PROJECT, UNIT)[0]["loop_id"] == "loop-1"


def test_the_hunter_session_receives_the_materialised_payload(
        threat_store, hunter_store):
    """S2 8.2/S3 8.9: the loop dispatch hands the hunter the payload materialised
    at dispatch time - the loop record, the unit context, the trust boundary and
    the fault - and the launch is keyed by the per-loop dispatch id."""
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch

    produce_model(threat_store)
    state = RunDispatchState()
    builder, seen, snapshots = _payload_recorder(state=state)
    coro_for = build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        threat_store=threat_store, hunt_store=HuntStore(),
        hunter_store=hunter_store, pod_store=None,
        state=state, gate=None,
        hunter_builder=builder, pod_builder=_pod_builder_fake, control=None,
    )
    item = _only_item(threat_store, hunter_store)

    coro = coro_for(item)
    assert coro is not None
    # the dispatch seam itself registers nothing (a refused coroutine must never
    # mutate the run state, T4a review I1)
    assert state.loop_likelihoods == {}
    assert state.hunters_in_graph == set()
    asyncio.run(coro)

    assert [p["dispatch_id"] for p in seen] == [f"{UNIT_NAME}__loop-1"]
    assert seen[0]["loop_id"] == "loop-1"
    assert seen[0]["programming_fault"]["id"] == "fault-1"
    assert seen[0]["canonical_class"] == "IDOR"
    assert seen[0]["trust_agreement"]["id"] == "ta-1"
    # DURING the graph stretch the two fields move TOGETHER (I1 + the F6
    # invariant): `hunters_in_graph` holds quiesce, `loop_likelihoods` is what a
    # later `low` loop waits behind - and both are released when the graph ends
    assert snapshots == [({item.dispatch_id: "high"}, {item.dispatch_id})]
    assert state.loop_likelihoods == {}
    assert state.hunters_in_graph == set()


def _only_item(threat_store, hunter_store):
    from polymerhus.attack.hunting.mover import read_produced_inbox

    inbox = read_produced_inbox(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store)
    assert len(inbox.items) == 1
    return inbox.items[0]


# --- the sequencing: low loops wait (S2 8.3, S1 7.6) ---------------------------

def _tick(threat_store, hunter_store, *, control=None, state=None):
    from polymerhus.attack.hunting.mover import run_delivery_tick

    control = control or RecordingControlPlane()
    state = state if state is not None else _dispatch_state()
    return run_delivery_tick(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control,
        coro_for=_coro_for(threat_store, hunter_store, control=control,
                           state=state),
        live_loop_likelihoods=state.loop_likelihoods,
        hunter_payload_capable=state.hunter_payload_capable,
    )


def _dispatch_state():
    from polymerhus.attack.hunting.surfer import RunDispatchState

    return RunDispatchState()


class _RoleGateControl(RecordingControlPlane):
    """The control plane with the #317 role reads: a run's hunter role can be
    stopped (its gate refuses new dispatch) while the module keeps running."""

    def __init__(self, *, running=True, **kw):
        super().__init__(**kw)
        self.hunter_running = running
        self.role_gate_reads = 0

    def role_running(self, run_id, role):
        return self.hunter_running

    def role_gate(self, run_id, role):
        self.role_gate_reads += 1
        return None


def test_a_stopped_hunter_role_pauses_loop_dispatch_without_changing_quiesce(
        threat_store, hunter_store):
    """T4 AC (the role-gate interaction, #317): a stopped hunter role pauses the
    loop dispatch - the loop file stays produced (at-least-once) and the run does
    NOT quiesce while dispatchable work waits; starting the role releases it on
    the next tick."""
    from polymerhus.attack.hunting.surfer import (
        RunDispatchState,
        is_run_quiesced,
    )

    produce_model(threat_store)
    control = _RoleGateControl(running=False)
    session = f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1"

    paused = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert paused.produced == 1 and paused.refused == 1 and paused.moved == 0
    assert len(threat_store.read_produced_loops(PROJECT)[0]["loops"]) == 1
    # a stopped role holds its work: the loop is dispatchable work, so the run
    # must not quiesce on it
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control, state=RunDispatchState(),
    )) is False

    control.hunter_running = True
    released = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [session]
    assert released.admitted == 1 and released.moved == 1
    assert threat_store.read_produced_loops(PROJECT) == []


def test_a_low_loop_waits_for_the_higher_loop_and_is_released_after_it(
        threat_store, hunter_store):
    """The low-loop pause is a PER-TICK condition on filesystem state: while the
    higher loop file is produced the low loop stays in produced/; once the higher
    loop is consumed and its session is gone, the next tick releases the low
    loop."""
    produce_model(threat_store, loops=[_loop_row(likelihood="low"),
                                       _loop_row(likelihood="critical")])
    # the store ranks the loops: loop-1 is the critical one
    control = RecordingControlPlane()

    first = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1"]
    assert first.admitted == 1 and first.moved == 1 and first.paused == 1
    assert [e["loop_id"] for e in threat_store.read_produced_loops(PROJECT)[0]["loops"]] \
        == ["loop-2"]

    # the higher hunter has settled (a fresh state: the run-local wire state is
    # gone, exactly as after a restart) - the low loop is released
    second_control = RecordingControlPlane()
    second = _tick(threat_store, hunter_store, control=second_control)

    assert second_control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-2"]
    assert second.admitted == 1 and second.paused == 0 and second.moved == 1
    assert threat_store.read_produced_loops(PROJECT) == []


def test_a_low_loop_stays_paused_while_a_higher_hunter_is_live(
        threat_store, hunter_store):
    """S2 8.3: a `low` loop dispatches only when no higher-tier loop file is
    produced AND no higher-tier hunter session is live - the run-local state is
    the live-session half of that condition. The two state fields move together:
    only a loop whose hunter is still mid-graph holds a later low loop."""
    from polymerhus.attack.hunting.surfer import RunDispatchState

    produce_model(threat_store, loops=[_loop_row(likelihood="low")])
    state = RunDispatchState()
    state.hunters_in_graph.add("Service-x__loop-1")
    state.loop_likelihoods["Service-x__loop-1"] = "high"
    assert set(state.loop_likelihoods) <= state.hunters_in_graph

    report = run_delivery_tick_for_state(threat_store, hunter_store, state)

    assert report.dispatched == 0 and report.paused == 1
    assert [e["loop_id"] for e in threat_store.read_produced_loops(PROJECT)[0]["loops"]] \
        == ["loop-1"]


def test_a_restart_holds_a_low_loop_while_the_higher_loop_file_is_produced(
        threat_store, hunter_store):
    """T4a review F5: the pause's durable half is the produced higher loop file.
    A restart (the run-local wire state is gone) with the higher loop file still
    produced keeps the low loop paused - losing the state cannot release work past
    a higher-ranked loop."""
    produce_model(threat_store, loops=[_loop_row(likelihood="low"),
                                       _loop_row(likelihood="critical")])
    higher = f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1"

    # the higher loop's dispatch is refused, so its loop file stays produced
    refused = RecordingControlPlane(refused={higher})
    first = _tick(threat_store, hunter_store, control=refused)

    assert refused.calls == [higher]
    assert first.refused == 1 and first.moved == 0 and first.paused == 1

    # the "restarted" run: a fresh state and a fresh tick - the higher loop file
    # is still produced, so the low loop is still held
    restarted_control = RecordingControlPlane()
    second = _tick(threat_store, hunter_store, control=restarted_control)

    assert restarted_control.calls == [higher]
    assert second.admitted == 1 and second.moved == 1 and second.paused == 1
    assert [e["loop_id"] for e in
            threat_store.read_produced_loops(PROJECT)[0]["loops"]] == ["loop-2"]

    # ... and the low loop is released once the higher one is consumed
    third_control = RecordingControlPlane()
    third = _tick(threat_store, hunter_store, control=third_control)

    assert third_control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-2"]
    assert third.admitted == 1 and third.paused == 0


def run_delivery_tick_for_state(threat_store, hunter_store, state):
    from polymerhus.attack.hunting.mover import run_delivery_tick

    return run_delivery_tick(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=RecordingControlPlane(),
        coro_for=_coro_for(threat_store, hunter_store, state=state),
        live_loop_likelihoods=state.loop_likelihoods,
    )


def test_the_sequencing_is_cross_unit(threat_store, hunter_store):
    """S2 8.3/S1 7.6: the surfer reads the RUN's produced loop files, not only
    the current unit's - another unit's produced high loop holds this unit's low
    loop, and BOTH are dispatchable in one run."""
    produce_model(threat_store, loops=[_loop_row(likelihood="low")])
    produce_model(threat_store, unit_id="Service:other",
                  loops=[_loop_row(likelihood="high")])
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [f"hunting:{RUN}:hunt:Service-other__loop-1"]
    assert report.produced == 2 and report.paused == 1 and report.moved == 1


def test_a_loop_file_from_another_run_is_left_untouched(
        threat_store, hunter_store):
    """S2 8.3: the dispatch read is RUN-scoped - another run's produced loop file
    is neither dispatched nor moved by this run."""
    produce_model(threat_store, run_id="another-run")
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert report.produced == 0 and report.moved == 0
    assert len(threat_store.read_produced_loops(PROJECT)[0]["loops"]) == 1


def test_a_malformed_loop_file_is_refused_without_wedging_the_quiesce(
        threat_store, hunter_store, tmp_path):
    """T4 AC: a malformed loop is refused - never dispatched, never counted as
    dispatchable work - so it can neither hot-loop the mover nor hold the run's
    quiesce open."""
    import yaml

    from polymerhus.attack.hunting.surfer import (
        RunDispatchState,
        is_run_quiesced,
        run_work_remaining,
    )

    produce_model(threat_store)
    path = (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
            / "produced" / UNIT_NAME / "loop-1.yaml")
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    body["loop"] = None                      # the payload's anchors are gone
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert report.produced == 0 and report.dispatched == 0 and report.moved == 0
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is False
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control, state=RunDispatchState(),
    )) is True
    # the malformed body is refused, never dropped and never consumed as a loop
    # record: it stays in produced/ as evidence while the model document moves
    assert (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
            / "produced" / UNIT_NAME / "loop-1.yaml").exists()
    assert [e["loop_id"] for e in
            threat_store.read_produced_loops(PROJECT)] == []
    assert [loop["loop_id"] for loop in threat_store.read_loop_files(PROJECT, UNIT)] == []


# --- the refuse-once accounting (T4a review F2/F3) ------------------------------

class _ModellessStore:
    """The store seam's degenerate case: it hands a produced unit over but cannot
    supply the unit's model document (a partially-wired store wrapper)."""

    def __init__(self, entry):
        self._entry = entry

    def read_produced_loops(self, project_id):
        return [self._entry]

    def read_model(self, project_id, unit_id):
        return None


def test_a_loop_whose_model_is_unavailable_is_not_work_and_logs_once(
        hunter_store, caplog):
    """T4a review F2 (S2 8.1/10.5): the loop file does not duplicate the model, so
    a produced read that cannot supply the model refuses its loops - they neither
    dispatch nor count as work (no live-lock, no quiesce wedge), and the refusal
    is logged ONCE across reads."""
    from polymerhus.attack.hunting.mover import read_produced_inbox
    from polymerhus.attack.hunting.surfer import run_work_remaining

    store = _ModellessStore({
        "unit_id": UNIT, "unit_name": UNIT_NAME, "run_id": RUN,
        "loops": [{"loop_id": "loop-1", "record": _loop_file_record()}],
        "malformed_loops": [],
    })

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        first = read_produced_inbox(
            PROJECT, RUN, threat_store=store, hunter_store=hunter_store)
        second = read_produced_inbox(
            PROJECT, RUN, threat_store=store, hunter_store=hunter_store)

    assert first.items == () and first.models_to_consume == {}
    assert second.items == () and second.models_to_consume == {}
    refusals = [record.message for record in caplog.records
                if "refus" in record.message]
    assert len(refusals) == 1, "the model-context refusal is logged once"
    assert run_work_remaining(
        PROJECT, RUN, threat_store=store, hunter_store=hunter_store) is False


def test_a_model_less_item_is_refused_once_by_the_dispatch_branch(
        hunter_store, caplog):
    """The surfer's own model-context guard (T4a review F2): a hand-built item
    without a model is refused on every tick without re-logging."""
    from polymerhus.attack.hunting.mover import ThreatLoopItem
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch

    coro_for = build_run_dispatch(
        project_id=PROJECT, run_id=RUN, threat_store=None, hunt_store=HuntStore(),
        hunter_store=hunter_store, pod_store=None,
        state=RunDispatchState(), gate=None,
        hunter_builder=_hunter_builder, pod_builder=_pod_builder_fake, control=None,
    )
    item = ThreatLoopItem(
        message_id=f"{UNIT_NAME}__loop-1",
        session_id=f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1",
        unit_id=UNIT, unit_name=UNIT_NAME, loop_id="loop-1",
        dispatch_id=f"{UNIT_NAME}__loop-1", likelihood="high",
        record=_loop_file_record(),
    )

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.surfer"):
        assert coro_for(item) is None
        assert coro_for(item) is None

    refusals = [record.message for record in caplog.records
                if "refus" in record.message]
    assert len(refusals) == 1, "the refusal is logged once, never per tick"


def test_the_refusal_log_is_project_scoped_and_bounded(monkeypatch, caplog):
    """T4a review F3: the refuse-once log is keyed with the project id (one
    project's refusal never silences another's) and bounded (a long-lived process
    cannot grow it without limit; the oldest key is evicted first)."""
    from polymerhus.attack.hunting import mover

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        assert mover.log_refusal_once("p1", "r", "u/loop-1", "refused %s", "one") is True
        assert mover.log_refusal_once("p1", "r", "u/loop-1", "refused %s", "one") is False
        assert mover.log_refusal_once("p2", "r", "u/loop-1", "refused %s", "two") is True
        assert mover.log_refusal_once("p1", "r-2", "u/loop-1", "refused %s", "three") is True

    assert [record.message for record in caplog.records] == [
        "refused one", "refused two", "refused three",
    ]

    # the clear is RUN-scoped: a sibling run's record is left alone
    mover.clear_refusal_log("p1", "r")
    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        assert mover.log_refusal_once("p1", "r", "u/loop-1", "refused %s", "four") is True
        assert mover.log_refusal_once("p2", "r", "u/loop-1", "refused %s", "five") is False

    # bounded per run: the oldest detail is evicted first
    monkeypatch.setattr(mover, "REFUSAL_LOG_LIMIT", 2)
    assert mover.log_refusal_once("p3", "r", "a", "x") is True
    assert mover.log_refusal_once("p3", "r", "b", "x") is True
    assert mover.log_refusal_once("p3", "r", "c", "x") is True   # evicts "a"
    assert mover.log_refusal_once("p3", "r", "a", "x") is True   # "a" was evicted

    # and bounded in the runs remembered: the oldest run's record is dropped
    monkeypatch.setattr(mover, "REFUSAL_RUN_LIMIT", 1)
    assert mover.log_refusal_once("p4", "r1", "a", "x") is True
    assert mover.log_refusal_once("p4", "r2", "a", "x") is True  # evicts (p4, r1)
    assert mover.log_refusal_once("p4", "r1", "a", "x") is True  # forgotten again


def _loop_file_record(**overrides) -> dict:
    """One produced loop file record exactly as the store writes it (S2 8.1)."""
    record = {
        "loop_id": "loop-1",
        "unit_id": UNIT,
        "unit_kind": "service",
        "run_id": RUN,
        "dispatch_id": f"{UNIT_NAME}__loop-1",
        "likelihood": "high",
        "loop": {
            "id": "loop-1",
            "fault_ref": "fault-1",
            "vulnerability_ref": "v-1",
            "failure_mode_refs": ["fm-1"],
            "canonical_class": "IDOR",
            "web_vulnerability_class": "idor",
            "likelihood": "high",
            "likelihood_rationale": "the item id is caller-supplied",
            "confidence": "INFERRED",
            "evidences": [{"kind": "request", "ref": "GET /catalogue"}],
        },
        "created_at": "2026-10-19T00:00:00Z",
    }
    record.update(overrides)
    return record


# --- the inert production path (C1, the T4a review) -----------------------------

def test_a_run_whose_builder_cannot_consume_the_payload_is_inert(
        tmp_path, monkeypatch, caplog):
    """C1 (CODING_STANDARD s12): between T4a and T6 the production hunter harness
    cannot consume the loop payload, so the run must be INERT - the loop file is
    not dispatched and not moved, the model document is not consumed, the unit is
    NOT excluded from later intake, and the run still quiesces - with ONE
    run-level line naming the state.
    """
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from tests.attack.test_hunting_modeller_wiring import (
        RUN as WIRING_RUN,
        _FakeControl,
        _FakePg,
        _noop_pod_builder,
        _patch_pg,
    )
    from tests.hunting_fixtures import ScriptedModellerTurns, intake_unit

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(tmp_path / "models")
    control = _FakeControl()

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.runtime"):
        hid = asyncio.run(hunting_runtime.start_hunting(
            PROJECT, intake_units=[intake_unit(UNIT)],
            modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
            graph_read_fn=lambda cypher, params: [],
            control=control,
            hunt_store=hunt, hunter_store=hunter, threat_store=models,
            # the PRODUCTION hunter builder: the harness that cannot consume the
            # loop payload yet
            pod_builder=_noop_pod_builder,
            tick_interval=0.001,
        ))

    assert hid == WIRING_RUN
    assert fake.statuses[-1] == (WIRING_RUN, "complete")
    # nothing dispatched, nothing moved, nothing consumed: the work stays
    # dispatchable for the run that CAN consume it (T4b/T6)
    assert [sid for sid in control.started if ":hunt:" in sid] == []
    assert [entry["loop_id"] for entry in
            models.read_produced_loops(PROJECT)[0]["loops"]] == ["loop-1"]
    assert models.read_completed_units(PROJECT) == []
    # and ONE run-level line names the state: the loops are produced, the per-loop
    # hunter harness is designed-not-built, zero hunts ran
    gap = [record.message for record in caplog.records
           if "designed-not-built" in record.message and "loop" in record.message]
    assert len(gap) == 1, gap
    assert "1 produced loop file" in gap[0] and "zero hunts" in gap[0]


def test_a_run_whose_builder_can_consume_the_payload_dispatches(
        threat_store, hunter_store):
    """The same seam, a capable builder: the loop dispatches and moves as before
    (the capability flag must not change the capable path)."""
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch

    produce_model(threat_store)
    state = RunDispatchState()
    builder, seen, _snapshots = _payload_recorder()
    coro_for = build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        threat_store=threat_store, hunt_store=HuntStore(),
        hunter_store=hunter_store, pod_store=None, state=state, gate=None,
        hunter_builder=builder, pod_builder=_pod_builder_fake, control=None,
    )

    item = _only_item(threat_store, hunter_store)

    assert coro_for(item) is not None


def test_a_refused_dispatch_leaks_no_run_state_and_quiesces(
        threat_store, hunter_store):
    """I1 (the T4a code-quality review): the run-local registration lands INSIDE
    the session coroutine, so an admission refusal - which closes the coroutine
    without ever running it - leaks nothing. Otherwise the leaked key stays in
    `hunters_in_graph`/`loop_likelihoods`: the quiesce never lands and a leaked
    higher tier holds every later low loop for ever."""
    from polymerhus.attack.hunting.surfer import (
        RunDispatchState,
        is_run_quiesced,
        run_work_remaining,
    )

    produce_model(threat_store)
    state = RunDispatchState()
    session = f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1"

    refused = _tick(threat_store, hunter_store, control=RecordingControlPlane(
        refused={session}), state=state)

    assert refused.refused == 1 and refused.moved == 0
    assert state.hunter_inboxes == {}
    assert state.hunters_in_graph == set()
    assert state.loop_likelihoods == {}
    # the work is still produced and still dispatchable: the run is not quiesced
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is True

    # the next tick, SAME state: the admission lands, the move lands, no leak
    admitted = _tick(threat_store, hunter_store, control=RecordingControlPlane(),
                     state=state)

    assert admitted.admitted == 1 and admitted.moved == 1
    assert state.hunters_in_graph == set()
    assert state.loop_likelihoods == {}
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=RecordingControlPlane(), state=state,
    )) is True


def _loop_path(tmp_path, *, unit_name=UNIT_NAME, loop_id="loop-1"):
    return (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
            / "produced" / unit_name / f"{loop_id}.yaml")


@pytest.mark.parametrize("body", [
    pytest.param("{[ unparseable\n", id="unreadable-yaml"),
    pytest.param("- just\n- a\n- list\n", id="not-a-mapping"),
])
def test_an_unreadable_loop_file_is_refused_and_never_wedges_the_run(
        threat_store, hunter_store, tmp_path, caplog, body):
    """T4a review F1 (S2 10.5): a loop file whose body cannot be read must not
    wedge the run. It is refused ONCE, never dispatched, never counted as a
    pending loop, and the model document is consumed as the no-dispatch model -
    so the run reaches quiesce instead of staying `running` for ever."""
    from polymerhus.attack.hunting.surfer import (
        RunDispatchState,
        is_run_quiesced,
        run_work_remaining,
    )

    produce_model(threat_store)
    _loop_path(tmp_path).write_text(body, encoding="utf-8")
    control = RecordingControlPlane()

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        first = _tick(threat_store, hunter_store, control=control)
        second = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert first.dispatched == 0 and first.moved == 0
    assert first.models_consumed == 1
    assert second.models_consumed == 0
    assert threat_store.read_produced_loops(PROJECT) == []
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is False
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control, state=RunDispatchState(),
    )) is True
    refusals = [record.message for record in caplog.records
                if "loop-1" in record.message and "refus" in record.message]
    assert len(refusals) == 1, "the refusal is logged once, never per tick"


def test_a_malformed_loop_file_is_logged_once_across_ticks(
        threat_store, hunter_store, tmp_path, caplog):
    """S2 10.5's log-once discipline (T4a review F1/F3): the mover re-reads the
    produced family every tick, so a refusal must not flood the log while its file
    lives - here the file survives TWO ticks (the valid loop dispatches in the
    first, the model document moves only in the second)."""
    import yaml

    produce_model(threat_store, loops=[_loop_row(likelihood="high"),
                                       _loop_row(likelihood="high")])
    path = _loop_path(tmp_path, loop_id="loop-2")
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    body["loop"] = None                      # a record the predicate refuses
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    control = RecordingControlPlane()

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        first = _tick(threat_store, hunter_store, control=control)
        second = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1"]
    assert first.admitted == 1 and first.moved == 1
    # the malformed leftover cannot hold the model: the second tick consumes it
    assert second.moved == 0 and second.models_consumed == 1
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    refusals = [record.message for record in caplog.records
                if "loop-2" in record.message and "refus" in record.message]
    assert len(refusals) == 1, "the refusal is logged once for both ticks"


# --- the consumption grain (S2 8.4) --------------------------------------------

def test_a_zero_loop_model_is_consumed_without_a_dispatch(
        threat_store, hunter_store):
    """S2 8.4: a produced COMPLETED valid model with no loop file is consumed on
    the mover's next tick, records zero dispatches, and the model document move
    is the single consumption marker. The work read counts it as work."""
    from polymerhus.attack.hunting.surfer import run_work_remaining

    _produce_zero_loop_model(threat_store)
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is True
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert report.produced == 0 and report.dispatched == 0 and report.moved == 0
    assert report.models_consumed == 1
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    assert threat_store.read_produced_loops(PROJECT) == []
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is False


def test_the_model_document_moves_with_its_last_loop_file(
        threat_store, hunter_store):
    """S2 8.1/8.4: the model document remains in produced/ while a loop file
    does; the LAST loop file's admission moves it."""
    produce_model(threat_store, loops=[_loop_row(likelihood="low"),
                                       _loop_row(likelihood="high")])

    # the high loop (rank 1) dispatches; the low one waits behind it, so the
    # model stays produced with one loop file left
    first = _tick(threat_store, hunter_store)
    assert first.moved == 1 and first.paused == 1 and first.models_consumed == 0
    assert threat_store.read_completed_units(PROJECT) == []
    assert [e["loop_id"] for e in
            threat_store.read_produced_loops(PROJECT)[0]["loops"]] == ["loop-2"]

    second = _tick(threat_store, hunter_store)
    assert second.moved == 1 and second.paused == 0
    assert threat_store.read_produced_loops(PROJECT) == []
    assert threat_store.read_completed_units(PROJECT) == [UNIT]


def test_an_archived_unit_is_never_dispatched(threat_store, hunter_store):
    """S2 4.2/8.4: a degraded unit's produced directory moves to abandoned/; the
    mover ignores it (the archive took the loop files out of produced/)."""
    produce_model(threat_store)
    threat_store.archive_unit(PROJECT, UNIT, "degraded (fixture)")
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [] and report.produced == 0
    assert threat_store.read_abandoned_units(PROJECT) == [UNIT]


# --- the whole-run integration path (real stores, fakes at the seams) ----------

def test_a_whole_run_dispatches_the_modelled_loop(tmp_path, monkeypatch):
    """The integration path (T4 AC): the run bootstrap models its unit through
    the real `ThreatModelStore`, and the run's surfer dispatches the produced loop
    file to ONE hunter session keyed by the loop's dispatch id. Fakes only at the
    pg rows, the control plane and the agent seam."""
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from tests.attack.test_hunting_modeller_wiring import (
        RUN as WIRING_RUN,
        _FakeControl,
        _FakePg,
        _noop_hunter_builder,
        _noop_pod_builder,
        _patch_pg,
    )
    from tests.hunting_fixtures import ScriptedModellerTurns, intake_unit

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(tmp_path / "models")
    control = _FakeControl()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT)],
        modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
        graph_read_fn=lambda cypher, params: [],
        control=control,
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == WIRING_RUN
    assert f"hunting:{WIRING_RUN}:hunt:{UNIT_NAME}__loop-1" in control.started
    # the admission moved the loop file and (with it) the model document
    assert models.read_produced_loops(PROJECT) == []
    assert models.read_completed_units(PROJECT) == [UNIT]


def test_a_whole_run_consumes_a_zero_loop_model_without_a_dispatch(
        tmp_path, monkeypatch):
    """S2 8.4 through the bootstrap: the zero-loop produced COMPLETED valid model
    is consumed by the mover without a dispatch, and the run still lands
    `complete` (nothing hangs on the consumed model)."""
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from tests.attack.test_hunting_modeller_wiring import (
        _FakeControl,
        _FakePg,
        _noop_hunter_builder,
        _noop_pod_builder,
        _patch_pg,
    )
    from tests.hunting_fixtures import ScriptedModellerTurns, intake_unit

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(tmp_path / "models")
    control = _FakeControl()

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT)],
        modeller_kwargs={"turn_fn": _zero_loop_turns()},
        graph_read_fn=lambda cypher, params: [],
        control=control,
        hunt_store=hunt, hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert fake.statuses[-1][1] == "complete"
    assert models.read_completed_units(PROJECT) == [UNIT]
    assert not [sid for sid in control.started if ":hunt:" in sid]


def _zero_loop_turns():
    """The scripted modeller turn seam whose COMPLETED write has no loop (every
    vulnerability dropped): the model the mover consumes without a dispatch."""
    from tests.hunting_fixtures import ScriptedModellerTurns, modeller_gate_payloads
    from polymerhus.attack.hunting.threat_model import ModelState

    payloads = modeller_gate_payloads()
    vulnerable = payloads[ModelState.VULNERABILITIES_WRITTEN]["vulnerabilities"][0]
    payloads[ModelState.VULNERABILITIES_WRITTEN] = {"vulnerabilities": [{
        **vulnerable, "dropped": True,
        "drop_reason": "the mechanics are absent",
        "drop_probe": "a second tenant's item id returning that item",
    }]}
    failed = payloads[ModelState.COMPLETED]["failure_modes"][0]
    payloads[ModelState.COMPLETED] = {
        "failure_modes": [{**failed, "dropped": True,
                           "drop_reason": "the mechanics are absent"}],
        "loops": [],
    }
    return ScriptedModellerTurns(payloads=payloads)


def _produce_zero_loop_model(store, *, unit_id=UNIT):
    """The zero-loop COMPLETED valid model: every vulnerability dropped (S2
    5.7's only loop-free shape), so no loop file is emitted."""
    payloads = modeller_gate_payloads()
    from polymerhus.attack.hunting.threat_model import ModelState

    vulnerable = payloads[ModelState.VULNERABILITIES_WRITTEN]["vulnerabilities"][0]
    payloads[ModelState.VULNERABILITIES_WRITTEN] = {"vulnerabilities": [{
        **vulnerable, "dropped": True,
        "drop_reason": "the mechanics are absent",
        "drop_probe": "a second tenant's item id returning that item",
    }]}
    failed = payloads[ModelState.COMPLETED]["failure_modes"][0]
    payloads[ModelState.COMPLETED] = {
        "failure_modes": [{**failed, "dropped": True,
                           "drop_reason": "the mechanics are absent"}],
        "loops": [],
    }
    for state in ModelState:
        store.write_sections(PROJECT, unit_id, state, payloads[state], run_id=RUN)
    return unit_id

