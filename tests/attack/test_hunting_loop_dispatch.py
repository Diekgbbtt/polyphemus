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


def _payload_recorder():
    """A hunter builder seam whose dispatch records the payload it receives."""
    seen: list = []

    def builder(*, run_id, project_id, hunter_store, **kw):
        async def _dispatch(payload):
            seen.append(payload)

        return _dispatch, None

    return builder, seen


def _coro_for(threat_store, hunter_store, *, state=None, hunter_builder=None,
              control=None):
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch

    return build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        threat_store=threat_store, hunt_store=HuntStore(),
        hunter_store=hunter_store, pod_store=None,
        state=state or RunDispatchState(), gate=None,
        hunter_builder=hunter_builder or _hunter_builder,
        pod_builder=_pod_builder_fake, control=control,
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
    builder, seen = _payload_recorder()
    state = RunDispatchState()
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
    # Settle the hunt's idle loop up front (the run terminal's own verb): the
    # dispatched session's graph stretch runs, then its idle loop ends instead of
    # waiting for a later terminal.
    item_inbox = state.hunter_inboxes[item.dispatch_id]
    item_inbox.post_nowait(AgentMessage(kind="settle"))
    asyncio.run(coro)

    assert [p["dispatch_id"] for p in seen] == [f"{UNIT_NAME}__loop-1"]
    assert seen[0]["loop_id"] == "loop-1"
    assert seen[0]["programming_fault"]["id"] == "fault-1"
    assert seen[0]["canonical_class"] == "IDOR"
    assert seen[0]["trust_agreement"]["id"] == "ta-1"
    # the graph stretch is over: the loop no longer holds the sequencing
    assert state.loop_likelihoods == {}
    assert state.hunters_in_graph == set()


def _only_item(threat_store, hunter_store):
    from polymerhus.attack.hunting.mover import read_produced_inbox

    inbox = read_produced_inbox(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store)
    assert len(inbox.items) == 1
    return inbox.items[0]


# --- the sequencing: low loops wait (S2 8.3, S1 7.6) ---------------------------

def _tick(threat_store, hunter_store, *, control=None):
    from polymerhus.attack.hunting.mover import run_delivery_tick

    control = control or RecordingControlPlane()
    return run_delivery_tick(
        PROJECT, RUN, threat_store=threat_store, hunter_store=hunter_store,
        control=control,
        coro_for=_coro_for(threat_store, hunter_store, control=control),
    )


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
    the live-session half of that condition."""
    from polymerhus.attack.hunting.surfer import RunDispatchState

    produce_model(threat_store, loops=[_loop_row(likelihood="low")])
    state = RunDispatchState()
    state.loop_likelihoods["Service-x__loop-1"] = "high"

    report = run_delivery_tick_for_state(threat_store, hunter_store, state)

    assert report.dispatched == 0 and report.paused == 1
    assert [e["loop_id"] for e in threat_store.read_produced_loops(PROJECT)[0]["loops"]] \
        == ["loop-1"]


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
    # refused, never dropped: the file is still in produced/
    assert len(threat_store.read_produced_loops(PROJECT)[0]["loops"]) == 1


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

