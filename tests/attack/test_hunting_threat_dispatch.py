"""Unit tier: the per-threat dispatch (T4, #377; S2 8, S1 7.6; S3 8.7/8.9).

The threat file is the dispatch grain: ONE produced threat file dispatches ONE
hunter session, the payload is materialised at dispatch time from the model
document, the mover consumes the threat file on admission and the model document
with its last threat file, and the run's produced read is cross-unit and
run-scoped.

Every test drives the REAL stores (the `ThreatModelStore` and the
`HunterMemoryStore`) on a temporary root; the agent seams (the hunter/pod
session coroutines) and the control plane are the injected fakes.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunter_payload import materialise_hunter_payload
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.app.llm.actor import AgentMessage

from tests.hunting_fixtures import threat_row as _threat_row
from tests.hunting_fixtures import produce_model as _produce_model

PROJECT = "proj-threat"
RUN = "run-threat-1"
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


def produce_model(store, *, unit_id=UNIT, run_id=RUN, threats=None) -> str:
    """This module's binding of the SHARED produced-model fixture
    (`tests.hunting_fixtures.produce_model`): the project/run/unit defaults
    stay here, the five-gate ladder has one home."""
    return _produce_model(
        store, project_id=PROJECT, unit_id=unit_id, run_id=run_id, threats=threats)


# --- the payload (S2 8.2) ------------------------------------------------------

def test_the_payload_carries_the_dispatch_context_and_nothing_more(threat_store):
    """S2 8.2: the payload carries the threat record, the unit identity, the
    relevant sharpening, the trust boundary, the fault, the classes, the
    evidence, the likelihood rationale, the confidence and the target context -
    and does NOT carry the failure modes, a narrowed vector, a `HuntConfig`, or
    a payload vector space."""
    produce_model(threat_store)
    model = threat_store.read_model(PROJECT, UNIT)
    threat_file = threat_store.read_threat_files(PROJECT, UNIT)[0]
    threat = threat_file["threat"]

    payload = materialise_hunter_payload(
        model, threat_file, dispatch_id=f"{UNIT_NAME}__threat-1",
    )

    # the POSITIVE list (S2 8.2): the payload carries exactly these keys and no
    # others - the failure modes, a narrowed vector, the retired `HuntConfig` and
    # a payload vector space stay in the model (T4a review F4: `assumption` and `suite_gap`
    # were extra; `programming_fault` and the threat record already carry them)
    assert set(payload) == {
        "dispatch_id", "run_id", "threat_id", "unit_id", "unit_kind", "threat",
        "technical_sharpening", "trust_agreement", "dynamic_state",
        "programming_fault", "canonical_class", "web_vulnerability_class",
        "evidence", "likelihood", "likelihood_rationale",
        "vulnerability_rationale", "confidence", "target_context",
    }
    assert payload["dispatch_id"] == f"{UNIT_NAME}__threat-1"
    assert payload["threat_id"] == "threat-1"
    assert payload["unit_id"] == UNIT
    assert payload["unit_kind"] == "service"
    assert payload["threat"]["id"] == "threat-1"
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
    assert payload["evidence"] == threat["evidences"]
    assert payload["target_context"] == {
        "unit_id": UNIT, "unit_kind": "service",
        "baseline_refs": ["GET /catalogue"],
    }
    assert payload["likelihood"] == "high"
    assert payload["likelihood_rationale"] == threat["likelihood_rationale"]
    assert payload["vulnerability_rationale"] == "An anonymous caller reads another user's item."
    assert payload["confidence"] == "INFERRED"
    # the prohibitions (S2 8.2)
    assert "failure_modes" not in payload
    assert "payload_vector_space" not in payload
    assert "hunt_config" not in payload
    assert "vector" not in payload


def test_the_payload_carries_the_impact_and_not_the_derived_score(threat_store):
    """The hunter receives the intended end impact as context. The derived
    impact weight and threat risk are dispatch concerns, not hunter reasoning."""
    produce_model(threat_store)
    model = threat_store.read_model(PROJECT, UNIT)
    threat_file = threat_store.read_threat_files(PROJECT, UNIT)[0]

    payload = materialise_hunter_payload(
        model, threat_file, dispatch_id=f"{UNIT_NAME}__threat-1",
    )

    assert payload["threat"]["impact"]["end_impact"] == (
        "A caller reads another tenant's item.")
    assert payload["threat"]["impact"]["confidentiality"] == "low"
    assert "impact_weight" not in payload["threat"]
    assert "risk" not in payload["threat"]


# --- the payload's violation -> transition link (S2 5.1, S3 8.2) -------------

def _dynamic_model(threat_store):
    """The produced completed model and its threat file, deep-copyable."""
    _produce_model(threat_store, project_id=PROJECT, unit_id=UNIT, run_id=RUN)
    model = threat_store.read_model(PROJECT, UNIT)
    threat_file = threat_store.read_threat_files(PROJECT, UNIT)[0]
    return model, threat_file


def _second_transition() -> dict:
    return {
        "id": "tr-2",
        "source": "ds-1",
        "target": "ds-1",
        "guard": "a forged item id",
        "confidence": "INFERRED",
        "evidences": [{"kind": "request", "ref": "GET /catalogue"}],
    }


def test_a_violation_transition_ref_selects_exactly_that_transition(threat_store):
    """S2 5.1/S3 8.2: a valid `Violation.transition_ref` selects exactly the
    named transition, never the first one in the model."""
    import copy

    model, threat_file = _dynamic_model(threat_store)
    model = copy.deepcopy(model)
    dynamic = model["trust_model"]["dynamic_state_trust"]
    dynamic["transitions"].append(_second_transition())
    dynamic["violations"][0]["transition_ref"] = "tr-2"

    payload = materialise_hunter_payload(
        model, threat_file, dispatch_id=f"{UNIT_NAME}__threat-1")

    assert payload["dynamic_state"]["transition"]["id"] == "tr-2"
    assert payload["dynamic_state"]["violation"]["id"] == "vi-1"


def test_an_absent_transition_ref_with_multiple_transitions_yields_no_transition(
        threat_store):
    """S2 5.1/S3 8.2: without a ref, several transitions are ambiguous - the
    payload records the gap (transition None) instead of guessing the first."""
    import copy

    model, threat_file = _dynamic_model(threat_store)
    model = copy.deepcopy(model)
    dynamic = model["trust_model"]["dynamic_state_trust"]
    dynamic["transitions"].append(_second_transition())
    dynamic["violations"][0].pop("transition_ref")

    payload = materialise_hunter_payload(
        model, threat_file, dispatch_id=f"{UNIT_NAME}__threat-1")

    assert payload["dynamic_state"]["transition"] is None
    assert payload["dynamic_state"]["violation"]["id"] == "vi-1"


def test_an_absent_transition_ref_with_one_transition_is_unambiguous(threat_store):
    """S2 5.1/S3 8.2: a single-transition model needs no ref - that transition
    is the only reading; zero transitions also degrade to None."""
    import copy

    model, threat_file = _dynamic_model(threat_store)
    model = copy.deepcopy(model)
    model["trust_model"]["dynamic_state_trust"]["violations"][0].pop(
        "transition_ref")
    payload = materialise_hunter_payload(
        model, threat_file, dispatch_id=f"{UNIT_NAME}__threat-1")
    assert payload["dynamic_state"]["transition"]["id"] == "tr-1"

    model["trust_model"]["dynamic_state_trust"]["transitions"] = []
    payload = materialise_hunter_payload(
        model, threat_file, dispatch_id=f"{UNIT_NAME}__threat-1")
    assert payload["dynamic_state"]["transition"] is None


def test_an_invalid_transition_ref_yields_no_transition(threat_store):
    """S2 5.1/S3 8.2: an invalid ref is the completion checker's referential
    error; the payload degrades to the gap, never a raise (the payload is
    advisory context, never a gate)."""
    import copy

    model, threat_file = _dynamic_model(threat_store)
    model = copy.deepcopy(model)
    model["trust_model"]["dynamic_state_trust"]["violations"][0][
        "transition_ref"] = "tr-missing"

    payload = materialise_hunter_payload(
        model, threat_file, dispatch_id=f"{UNIT_NAME}__threat-1")

    assert payload["dynamic_state"]["transition"] is None


# --- one threat file dispatches one hunter (S2 2.2, 8.4) -------------------------

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
                    dict(state.threat_buckets), set(state.hunters_in_graph),
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
        threat_store=threat_store,
        hunter_store=hunter_store, pod_store=None,
        state=state, gate=None,
        hunter_builder=hunter_builder or _hunter_builder,
        pod_builder=_pod_builder_fake, control=control,
    )


async def _pod_builder_fake(spec, **kw):
    return {"verdict": "unsuccessful", "terminal_reason": "space-exhausted"}


def test_one_threat_file_dispatches_one_hunter_and_moves_both_records(
        threat_store, hunter_store):
    """S2 8.4: the threat file IS the dispatch grain - ONE threat file admits ONE
    hunter session under the per-threat id, and the admission moves the threat file
    to consumed/ with the model document (its last threat file, S2 8.1)."""
    from polymerhus.attack.hunting.mover import run_delivery_tick

    produce_model(threat_store)
    control = RecordingControlPlane()

    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control, coro_for=_coro_for(threat_store, hunter_store),
    )

    assert control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-1"]
    assert report.produced == 1
    assert report.admitted == 1 and report.refused == 0
    assert report.moved == 1 and report.paused == 0
    # the produced->consumed move is the admission marker (S2 8.4): the threat
    # file and the model document both left produced/
    assert threat_store.read_produced_threats(PROJECT) == []
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    assert threat_store.read_threat_files(PROJECT, UNIT)[0]["threat_id"] == "threat-1"


def test_the_hunter_session_receives_the_materialised_payload(
        threat_store, hunter_store):
    """S2 8.2/S3 8.9: the threat dispatch hands the hunter the payload materialised
    at dispatch time - the threat record, the unit context, the trust boundary and
    the fault - and the launch is keyed by the per-threat dispatch id."""
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch

    produce_model(threat_store)
    state = RunDispatchState()
    builder, seen, snapshots = _payload_recorder(state=state)
    coro_for = build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        threat_store=threat_store,
        hunter_store=hunter_store, pod_store=None,
        state=state, gate=None,
        hunter_builder=builder, pod_builder=_pod_builder_fake, control=None,
    )
    item = _only_item(threat_store, hunter_store)

    coro = coro_for(item)
    assert coro is not None
    # the dispatch seam itself registers nothing (a refused coroutine must never
    # mutate the run state, T4a review I1)
    assert state.threat_buckets == {}
    assert state.hunters_in_graph == set()
    asyncio.run(coro)

    assert [p["dispatch_id"] for p in seen] == [f"{UNIT_NAME}__threat-1"]
    assert seen[0]["threat_id"] == "threat-1"
    assert seen[0]["programming_fault"]["id"] == "fault-1"
    assert seen[0]["canonical_class"] == "IDOR"
    assert seen[0]["trust_agreement"]["id"] == "ta-1"
    # DURING the graph stretch the two fields move TOGETHER (I1 + the F6
    # invariant): `hunters_in_graph` holds quiesce, `threat_buckets` carries the
    # live dispatch bucket a later `low` threat waits behind - and both are
    # released when the graph ends.
    assert snapshots == [({item.dispatch_id: item.bucket}, {item.dispatch_id})]
    assert state.threat_buckets == {}
    assert state.hunters_in_graph == set()


def _only_item(threat_store, hunter_store):
    from polymerhus.attack.hunting.mover import read_produced_inbox

    inbox = read_produced_inbox(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store)
    assert len(inbox.items) == 1
    return inbox.items[0]


# --- the sequencing: low threats wait (S2 8.3, S1 7.6) ---------------------------

def _tick(threat_store, hunter_store, *, control=None, state=None):
    from polymerhus.attack.hunting.mover import run_delivery_tick

    control = control or RecordingControlPlane()
    state = state if state is not None else _dispatch_state()
    return run_delivery_tick(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control,
        coro_for=_coro_for(threat_store, hunter_store, control=control,
                           state=state),
        live_threat_buckets=state.threat_buckets,
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


def test_a_stopped_hunter_role_pauses_threat_dispatch_without_changing_quiesce(
        threat_store, hunter_store):
    """T4 AC (the role-gate interaction, #317): a stopped hunter role pauses the
    threat dispatch - the threat file stays produced (at-least-once) and the run does
    NOT quiesce while dispatchable work waits; starting the role releases it on
    the next tick."""
    from polymerhus.attack.hunting.surfer import (
        RunDispatchState,
        is_run_quiesced,
    )

    produce_model(threat_store)
    control = _RoleGateControl(running=False)
    session = f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-1"

    paused = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert paused.produced == 1 and paused.refused == 1 and paused.moved == 0
    assert len(threat_store.read_produced_threats(PROJECT)[0]["threats"]) == 1
    # a stopped role holds its work: the threat is dispatchable work, so the run
    # must not quiesce on it
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control, state=RunDispatchState(),
    )) is False

    control.hunter_running = True
    released = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [session]
    assert released.admitted == 1 and released.moved == 1
    assert threat_store.read_produced_threats(PROJECT) == []


def test_a_low_threat_waits_for_the_higher_threat_and_is_released_after_it(
        threat_store, hunter_store):
    """The low-threat pause is a PER-TICK condition on filesystem state: while the
    higher threat file is produced the low threat stays in produced/; once the higher
    threat is consumed and its session is gone, the next tick releases the low
    threat."""
    produce_model(threat_store, threats=[_threat_row(likelihood="low"),
                                       _threat_row(likelihood="critical")])
    # the store ranks the threats: threat-1 is the critical one
    control = RecordingControlPlane()

    first = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-1"]
    assert first.admitted == 1 and first.moved == 1 and first.paused == 1
    assert [e["threat_id"] for e in threat_store.read_produced_threats(PROJECT)[0]["threats"]] \
        == ["threat-2"]
    # F-022: the higher hunter settled and finalized its (zero-spec) terminal
    # set; the run-local wire state is gone, exactly as after a restart.
    hunter_store.finalize_specs(
        PROJECT, f"{UNIT_NAME}__threat-1", run_id=RUN)

    # the low threat is released once the higher one is consumed and complete
    second_control = RecordingControlPlane()
    second = _tick(threat_store, hunter_store, control=second_control)

    assert second_control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-2"]
    assert second.admitted == 1 and second.paused == 0 and second.moved == 1
    assert threat_store.read_produced_threats(PROJECT) == []


def test_a_low_threat_stays_paused_while_a_higher_hunter_is_live(
        threat_store, hunter_store):
    """S2 8.3: a `low` threat dispatches only when no higher-tier threat file is
    produced AND no higher-tier hunter session is live - the run-local state is
    the live-session half of that condition. The two state fields move together:
    only a threat whose hunter is still mid-graph holds a later low threat."""
    from polymerhus.attack.hunting.surfer import RunDispatchState

    produce_model(threat_store, threats=[_threat_row(likelihood="low")])
    state = RunDispatchState()
    state.hunters_in_graph.add("Service-x__threat-1")
    state.threat_buckets["Service-x__threat-1"] = "high"
    assert set(state.threat_buckets) <= state.hunters_in_graph

    report = run_delivery_tick_for_state(threat_store, hunter_store, state)

    assert report.dispatched == 0 and report.paused == 1
    assert [e["threat_id"] for e in threat_store.read_produced_threats(PROJECT)[0]["threats"]] \
        == ["threat-1"]


def test_a_restart_holds_a_low_threat_while_the_higher_threat_file_is_produced(
        threat_store, hunter_store):
    """T4a review F5: the pause's durable half is the produced higher threat file.
    A restart (the run-local wire state is gone) with the higher threat file still
    produced keeps the low threat paused - losing the state cannot release work past
    a higher-ranked threat."""
    produce_model(threat_store, threats=[_threat_row(likelihood="low"),
                                       _threat_row(likelihood="critical")])
    higher = f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-1"

    # the higher threat's dispatch is refused, so its threat file stays produced
    refused = RecordingControlPlane(refused={higher})
    first = _tick(threat_store, hunter_store, control=refused)

    assert refused.calls == [higher]
    assert first.refused == 1 and first.moved == 0 and first.paused == 1

    # the "restarted" run: a fresh state and a fresh tick - the higher threat file
    # is still produced, so the low threat is still held
    restarted_control = RecordingControlPlane()
    second = _tick(threat_store, hunter_store, control=restarted_control)

    assert restarted_control.calls == [higher]
    assert second.admitted == 1 and second.moved == 1 and second.paused == 1
    assert [e["threat_id"] for e in
            threat_store.read_produced_threats(PROJECT)[0]["threats"]] == ["threat-2"]
    # F-022: the higher hunter finalized its zero-spec terminal set, so the
    # consumed threat is complete (the fake session never ran).
    hunter_store.finalize_specs(
        PROJECT, f"{UNIT_NAME}__threat-1", run_id=RUN)

    # ... and the low threat is released once the higher one is consumed
    third_control = RecordingControlPlane()
    third = _tick(threat_store, hunter_store, control=third_control)

    assert third_control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-2"]
    assert third.admitted == 1 and third.paused == 0


def run_delivery_tick_for_state(threat_store, hunter_store, state):
    from polymerhus.attack.hunting.mover import run_delivery_tick

    return run_delivery_tick(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=RecordingControlPlane(),
        coro_for=_coro_for(threat_store, hunter_store, state=state),
        live_threat_buckets=state.threat_buckets,
    )


def test_the_sequencing_is_cross_unit(threat_store, hunter_store):
    """S2 8.3/S1 7.6: the surfer reads the RUN's produced threat files, not only
    the current unit's - another unit's produced high threat holds this unit's low
    threat, and BOTH are dispatchable in one run."""
    produce_model(threat_store, threats=[_threat_row(likelihood="low")])
    produce_model(threat_store, unit_id="Service:other",
                  threats=[_threat_row(likelihood="high")])
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [f"hunting:{RUN}:hunt:Service-other__threat-1"]
    assert report.produced == 2 and report.paused == 1 and report.moved == 1


def test_a_threat_file_from_another_run_is_left_untouched(
        threat_store, hunter_store):
    """S2 8.3: the dispatch read is RUN-scoped - another run's produced threat file
    is neither dispatched nor moved by this run."""
    produce_model(threat_store, run_id="another-run")
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert report.produced == 0 and report.moved == 0
    assert len(threat_store.read_produced_threats(PROJECT)[0]["threats"]) == 1


def test_a_malformed_threat_file_is_refused_without_wedging_the_quiesce(
        threat_store, hunter_store, tmp_path):
    """T4 AC: a malformed threat is refused - never dispatched, never counted as
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
            / "produced" / UNIT_NAME / "threat-1.yaml")
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    body["threat"] = None                      # the payload's anchors are gone
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
    # the malformed body is refused, never dropped and never consumed as a threat
    # record: it stays in produced/ as evidence while the model document moves
    assert (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
            / "produced" / UNIT_NAME / "threat-1.yaml").exists()
    assert [e["threat_id"] for e in
            threat_store.read_produced_threats(PROJECT)] == []
    assert [threat["threat_id"] for threat in threat_store.read_threat_files(PROJECT, UNIT)] == []


# --- the refuse-once accounting (T4a review F2/F3) ------------------------------

class _ModellessStore:
    """The store seam's degenerate case: it hands a produced unit over but cannot
    supply the unit's model document (a partially-wired store wrapper)."""

    def __init__(self, entry):
        self._entry = entry

    def read_produced_threats(self, project_id):
        return [self._entry]

    def read_model(self, project_id, unit_id):
        return None


def test_a_threat_whose_model_is_unavailable_is_not_work_and_logs_once(
        hunter_store, caplog):
    """T4a review F2 (S2 8.1/10.5): the threat file does not duplicate the model, so
    a produced read that cannot supply the model refuses its threats - they neither
    dispatch nor count as work (no live-lock, no quiesce wedge), and the refusal
    is logged ONCE across reads."""
    from polymerhus.attack.hunting.mover import read_produced_inbox
    from polymerhus.attack.hunting.surfer import run_work_remaining

    store = _ModellessStore({
        "unit_id": UNIT, "unit_name": UNIT_NAME, "run_id": RUN,
        "threats": [{"threat_id": "threat-1", "record": _threat_file_record()}],
        "malformed_threats": [],
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
    from polymerhus.attack.hunting.mover import ThreatItem
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch

    coro_for = build_run_dispatch(
        project_id=PROJECT, run_id=RUN, threat_store=None,
        hunter_store=hunter_store, pod_store=None,
        state=RunDispatchState(), gate=None,
        hunter_builder=_hunter_builder, pod_builder=_pod_builder_fake, control=None,
    )
    item = ThreatItem(
        message_id=f"{UNIT_NAME}__threat-1",
        session_id=f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-1",
        unit_id=UNIT, unit_name=UNIT_NAME, threat_id="threat-1",
        dispatch_id=f"{UNIT_NAME}__threat-1", likelihood="high",
        record=_threat_file_record(),
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
        assert mover.log_refusal_once("p1", "r", "u/threat-1", "refused %s", "one") is True
        assert mover.log_refusal_once("p1", "r", "u/threat-1", "refused %s", "one") is False
        assert mover.log_refusal_once("p2", "r", "u/threat-1", "refused %s", "two") is True
        assert mover.log_refusal_once("p1", "r-2", "u/threat-1", "refused %s", "three") is True

    assert [record.message for record in caplog.records] == [
        "refused one", "refused two", "refused three",
    ]

    # the clear is RUN-scoped: a sibling run's record is left alone
    mover.clear_refusal_log("p1", "r")
    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        assert mover.log_refusal_once("p1", "r", "u/threat-1", "refused %s", "four") is True
        assert mover.log_refusal_once("p2", "r", "u/threat-1", "refused %s", "five") is False

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


def _threat_file_record(**overrides) -> dict:
    """One produced threat file record exactly as the store writes it (S2 8.1)."""
    record = {
        "threat_id": "threat-1",
        "unit_id": UNIT,
        "unit_kind": "service",
        "run_id": RUN,
        "dispatch_id": f"{UNIT_NAME}__threat-1",
        "likelihood": "high",
        "threat": {
            "id": "threat-1",
            "fault_ref": "fault-1",
            "vulnerability_ref": "v-1",
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


def test_a_refused_dispatch_leaks_no_run_state_and_quiesces(
        threat_store, hunter_store):
    """I1 (the T4a code-quality review): the run-local registration lands INSIDE
    the session coroutine, so an admission refusal - which closes the coroutine
    without ever running it - leaks nothing. Otherwise the leaked key stays in
    `hunters_in_graph`/`threat_buckets`: the quiesce never lands and a leaked
    higher tier holds every later low threat for ever."""
    from polymerhus.attack.hunting.surfer import (
        RunDispatchState,
        is_run_quiesced,
        run_work_remaining,
    )

    produce_model(threat_store)
    state = RunDispatchState()
    session = f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-1"

    refused = _tick(threat_store, hunter_store, control=RecordingControlPlane(
        refused={session}), state=state)

    assert refused.refused == 1 and refused.moved == 0
    assert state.hunter_inboxes == {}
    assert state.hunters_in_graph == set()
    assert state.threat_buckets == {}
    # the work is still produced and still dispatchable: the run is not quiesced
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is True

    # the next tick, SAME state: the admission lands, the move lands, no leak
    admitted = _tick(threat_store, hunter_store, control=RecordingControlPlane(),
                     state=state)

    assert admitted.admitted == 1 and admitted.moved == 1
    assert state.hunters_in_graph == set()
    assert state.threat_buckets == {}
    # F-022: the move is admission, not completion. The fake hunter session
    # never ran, so its terminal spec set is written here (a zero-spec hunt is
    # still a completed hunt); only then is the run's work exhausted.
    hunter_store.finalize_specs(
        PROJECT, f"{UNIT_NAME}__threat-1", run_id=RUN)
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=RecordingControlPlane(), state=state,
    )) is True


def test_a_builder_failure_undoes_the_whole_run_registration(
        hunter_store, caplog):
    """M-c (T4a review round 2): a failing hunter builder degrades the session, and
    the registration is undone WHOLE - a leftover inbox reads as "a hunter was
    dispatched" and suppresses the run's dispatch-gap line for the rest of the
    run, and a leftover mid-graph key would hold the quiesce."""
    from polymerhus.attack.hunting.surfer import RunDispatchState, run_hunter_session

    def failing_builder(**kwargs):
        raise RuntimeError("builder unavailable (fixture)")

    state = RunDispatchState()
    hunt_key = f"{UNIT_NAME}__threat-1"

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.surfer"):
        asyncio.run(run_hunter_session(
            payload={}, project_id=PROJECT, run_id=RUN, hunt_key=hunt_key,
            likelihood="high", hunter_store=hunter_store, state=state, gate=None,
            hunter_builder=failing_builder,
        ))

    assert state.hunter_inboxes == {}
    assert state.hunters_in_graph == set()
    assert state.threat_buckets == {}
    assert any("builder failed" in record.message for record in caplog.records)


def _threat_path(tmp_path, *, unit_name=UNIT_NAME, threat_id="threat-1"):
    return (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
            / "produced" / unit_name / f"{threat_id}.yaml")


@pytest.mark.parametrize("body", [
    pytest.param("{[ unparseable\n", id="unreadable-yaml"),
    pytest.param("- just\n- a\n- list\n", id="not-a-mapping"),
])
def test_an_unreadable_threat_file_is_refused_and_never_wedges_the_run(
        threat_store, hunter_store, tmp_path, caplog, body):
    """T4a review F1 (S2 10.5): a threat file whose body cannot be read must not
    wedge the run. It is refused ONCE, never dispatched, never counted as a
    pending threat, and the model document is consumed as the no-dispatch model -
    so the run reaches quiesce instead of staying `running` for ever."""
    from polymerhus.attack.hunting.surfer import (
        RunDispatchState,
        is_run_quiesced,
        run_work_remaining,
    )

    produce_model(threat_store)
    _threat_path(tmp_path).write_text(body, encoding="utf-8")
    control = RecordingControlPlane()

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        first = _tick(threat_store, hunter_store, control=control)
        second = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert first.dispatched == 0 and first.moved == 0
    assert first.models_consumed == 1
    assert second.models_consumed == 0
    assert threat_store.read_produced_threats(PROJECT) == []
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is False
    assert asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control, state=RunDispatchState(),
    )) is True
    refusals = [record.message for record in caplog.records
                if "threat-1" in record.message and "refus" in record.message]
    assert len(refusals) == 1, "the refusal is logged once, never per tick"


def test_a_malformed_threat_file_is_logged_once_across_ticks(
        threat_store, hunter_store, tmp_path, caplog):
    """S2 10.5's log-once discipline (T4a review F1/F3): the mover re-reads the
    produced family every tick, so a refusal must not flood the log while its file
    lives - here the file survives TWO ticks (the valid threat dispatches in the
    first, the model document moves only in the second)."""
    import yaml

    produce_model(threat_store, threats=[_threat_row(likelihood="high"),
                                       _threat_row(likelihood="high")])
    path = _threat_path(tmp_path, threat_id="threat-2")
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    body["threat"] = None                      # a record the predicate refuses
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    control = RecordingControlPlane()

    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.mover"):
        first = _tick(threat_store, hunter_store, control=control)
        # F-022: the admitted hunter's terminal set is what completes threat-1;
        # the fake session never ran, so the test writes it before the next tick.
        hunter_store.finalize_specs(
            PROJECT, f"{UNIT_NAME}__threat-1", run_id=RUN)
        second = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [f"hunting:{RUN}:hunt:{UNIT_NAME}__threat-1"]
    assert first.admitted == 1 and first.moved == 1
    # the malformed leftover cannot hold the model: the second tick consumes it
    assert second.moved == 0 and second.models_consumed == 1
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    refusals = [record.message for record in caplog.records
                if "threat-2" in record.message and "refus" in record.message]
    assert len(refusals) == 1, "the refusal is logged once for both ticks"


# --- the consumption grain (S2 8.4) --------------------------------------------

def test_a_zero_threat_model_is_consumed_without_a_dispatch(
        threat_store, hunter_store):
    """S2 8.4: a produced COMPLETED valid model with no threat file is consumed on
    the mover's next tick, records zero dispatches, and the model document move
    is the single consumption marker. The work read counts it as work."""
    from polymerhus.attack.hunting.surfer import run_work_remaining

    _produce_zero_threat_model(threat_store)
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is True
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == []
    assert report.produced == 0 and report.dispatched == 0 and report.moved == 0
    assert report.models_consumed == 1
    assert threat_store.read_completed_units(PROJECT) == [UNIT]
    assert threat_store.read_produced_threats(PROJECT) == []
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store) is False


def test_the_model_document_moves_with_its_last_threat_file(
        threat_store, hunter_store):
    """S2 8.1/8.4: the model document remains in produced/ while a threat file
    does; the LAST threat file's admission moves it."""
    produce_model(threat_store, threats=[_threat_row(likelihood="low"),
                                       _threat_row(likelihood="high")])

    # the high threat (rank 1) dispatches; the low one waits behind it, so the
    # model stays produced with one threat file left
    first = _tick(threat_store, hunter_store)
    assert first.moved == 1 and first.paused == 1 and first.models_consumed == 0
    assert threat_store.read_completed_units(PROJECT) == []
    assert [e["threat_id"] for e in
            threat_store.read_produced_threats(PROJECT)[0]["threats"]] == ["threat-2"]
    # F-022: complete the high hunt so its consumed threat is not recovered while
    # the low threat is released.
    hunter_store.finalize_specs(
        PROJECT, f"{UNIT_NAME}__threat-1", run_id=RUN)

    second = _tick(threat_store, hunter_store)
    assert second.moved == 1 and second.paused == 0
    assert threat_store.read_produced_threats(PROJECT) == []
    assert threat_store.read_completed_units(PROJECT) == [UNIT]


def test_an_archived_unit_is_never_dispatched(threat_store, hunter_store):
    """S2 4.2/8.4: a degraded unit's produced directory moves to abandoned/; the
    mover ignores it (the archive took the threat files out of produced/)."""
    produce_model(threat_store)
    threat_store.archive_unit(PROJECT, UNIT, "degraded (fixture)")
    control = RecordingControlPlane()

    report = _tick(threat_store, hunter_store, control=control)

    assert control.calls == [] and report.produced == 0
    assert threat_store.read_abandoned_units(PROJECT) == [UNIT]


# --- the whole-run integration path (real stores, fakes at the seams) ----------

def test_a_whole_run_dispatches_the_modelled_threat(tmp_path, monkeypatch):
    """The integration path (T4 AC): the run bootstrap models its unit through
    the real `ThreatModelStore`, and the run's surfer dispatches the produced threat
    file to ONE hunter session keyed by the threat's dispatch id. Fakes only at the
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
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(tmp_path / "models")
    control = _FakeControl()

    hid = asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT)],
        modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
        graph_read_fn=lambda cypher, params: [],
        control=control,
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert hid == WIRING_RUN
    assert f"hunting:{WIRING_RUN}:hunt:{UNIT_NAME}__threat-1" in control.started
    # the admission moved the threat file and (with it) the model document
    assert models.read_produced_threats(PROJECT) == []
    assert models.read_completed_units(PROJECT) == [UNIT]


def test_a_whole_run_consumes_a_zero_threat_model_without_a_dispatch(
        tmp_path, monkeypatch):
    """S2 8.4 through the bootstrap: the zero-threat produced COMPLETED valid model
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
    hunter = HunterMemoryStore(tmp_path / "hunter")
    models = ThreatModelStore(tmp_path / "models")
    control = _FakeControl()

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, intake_units=[intake_unit(UNIT)],
        modeller_kwargs={"turn_fn": _zero_threat_turns()},
        graph_read_fn=lambda cypher, params: [],
        control=control,
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert fake.statuses[-1][1] == "complete"
    assert models.read_completed_units(PROJECT) == [UNIT]
    assert not [sid for sid in control.started if ":hunt:" in sid]


def _zero_threat_turns():
    """The scripted modeller turn seam whose COMPLETED write has no threat (every
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
    payloads[ModelState.COMPLETED] = {"threats": []}
    return ScriptedModellerTurns(payloads=payloads)


def _produce_zero_threat_model(store, *, unit_id=UNIT):
    """The zero-threat COMPLETED valid model: every vulnerability dropped (S2
    5.7's only threat-free shape), so no threat file is emitted."""
    from tests.hunting_fixtures import modeller_gate_payloads

    payloads = modeller_gate_payloads()
    from polymerhus.attack.hunting.threat_model import ModelState

    vulnerable = payloads[ModelState.VULNERABILITIES_WRITTEN]["vulnerabilities"][0]
    payloads[ModelState.VULNERABILITIES_WRITTEN] = {"vulnerabilities": [{
        **vulnerable, "dropped": True,
        "drop_reason": "the mechanics are absent",
        "drop_probe": "a second tenant's item id returning that item",
    }]}
    payloads[ModelState.COMPLETED] = {"threats": []}
    for state in ModelState:
        store.write_sections(PROJECT, unit_id, state, payloads[state], run_id=RUN)
    return unit_id

