"""Contract tier: the T3 (#376) run lifecycle through the run bootstrap -
the intake record, the symbolic accumulator, the progressive halt, the resume
rules, the commit order, the interleave and the degraded units (S1 7.1-7.5, S2
7.4 and 9.2-9.4).

No live LLM, no live DB, no live Neo4j: the control plane, the pg accessors and
the modeller turn seam are injected (the `test_hunting_modeller_wiring` fakes),
and the real `ThreatModelStore` runs on a temp root - so the model the pass
commits and the run record the driver writes are both observable.
"""
from __future__ import annotations

import asyncio

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.run_lifecycle import RUN_RECORD_KEYS
from polymerhus.attack.hunting.threat_modeller import UnitOutcome

from tests.attack.test_hunting_modeller_wiring import (
    _FakeControl,
    _FakePg,
    _noop_pod_builder,
    _patch_pg,
)
from tests.hunting_fixtures import (
    ScriptedModellerTurns,
    intake_unit,
    produce_model,
)

PROJECT = "lifecycle-proj"
RUN = "lifecycle-run"
UNIT_A = "Service:slug:a"
UNIT_B = "GraphQLApi"
UNIT_C = "RESTApi"


def _stores(tmp_path):
    """The two stores the dispatch path reads: the hunter memory and the threat
    model store. The hunt store retired with the config family (T4b)."""
    return (HunterMemoryStore(tmp_path / "hunter"),
            ThreatModelStore(root_dir=tmp_path / "models"))


def _unit(unit_id: str, edges: int) -> object:
    return intake_unit(unit_id, live_edges=edges)


def _units(*triples) -> list:
    return [_unit(unit_id, edges) for unit_id, edges in triples]


def _seed_record(**overrides) -> dict:
    """A persisted run record (the run row's `stats`) for a resume."""
    record = {
        "intake_order": [],
        "intake_position": 0,
        "intake_excluded": [],
        "risk_threshold": 250,
        "threshold_basis": "default",
        "risk_weights": {"none": 0, "low": 1, "medium": 2, "high": 3,
                         "critical": 4},
        "risk_total": 0,
        "risk_breakdown": {"none": 0, "low": 0, "medium": 0, "high": 0,
                           "critical": 0},
        "model_sums": [],
        "crossing_unit": None,
        "blocked_unit": None,
        "halt": False,
        "degraded_units": [],
        "trajectory": [],
    }
    record.update(overrides)
    return record


def _completed_sum(unit_id: str, total: int = 3) -> dict:
    """The recorded sum of one completed model: one `high` loop (weight 3)."""
    return {
        "unit_id": unit_id,
        "total": total,
        "breakdown": {"none": 0, "low": 0, "medium": 0, "high": 1,
                      "critical": 0},
    }


def _resume_fake(record: dict) -> _FakePg:
    """A fake pg whose run row already carries `record` (the resume read)."""
    fake = _FakePg()
    fake.records[RUN] = dict(record)
    return fake


def _write_completed_model(models: ThreatModelStore, unit_id: str,
                           *, run_id: str = "earlier-run") -> None:
    """Drive the REAL store to a COMPLETED, valid model for `unit_id` through
    its five gates (the shared worked example: one `high` loop)."""
    from tests.hunting_fixtures import modeller_gate_payloads

    for state, sections in modeller_gate_payloads().items():
        models.write_sections(PROJECT, unit_id, state, sections, run_id=run_id)
    assert models.read_model(PROJECT, unit_id)["state"] == ModelState.COMPLETED.value


def _noop_hunter_builder(*, run_id, project_id, hunter_store, **kw):
    """The agent-seam hunter builder fake: it is a SYNCHRONOUS factory (the seam
    is called, not awaited) returning an async dispatch - the real shape."""
    async def dispatch(payload):
        return None
    return dispatch, None


async def _recording_pass(seen: list):
    async def run(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="degraded")
    return run


def test_the_run_record_carries_every_fixed_key_and_the_accumulated_sum(
        tmp_path, monkeypatch):
    """S1 7.4 / S2 9.2: the bootstrap freezes the intake, records it before the
    first unit, updates the accumulator after every COMPLETED write, and the
    run record carries every fixed key."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 3), (UNIT_B, 1)),
        modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    record = fake.run_record(RUN)
    assert set(record) == set(RUN_RECORD_KEYS)
    assert record["intake_order"] == [UNIT_A, UNIT_B]
    assert record["intake_position"] == 2
    assert record["intake_excluded"] == []
    assert record["risk_threshold"] == 250
    assert record["threshold_basis"] == "default"
    assert record["risk_weights"] == {"none": 0, "low": 1, "medium": 2,
                                      "high": 3, "critical": 4}
    # one `high` loop per unit (the shared worked example): 3 + 3
    assert record["risk_total"] == 6
    assert record["risk_breakdown"] == {"none": 0, "low": 0, "medium": 0,
                                        "high": 2, "critical": 0}
    assert record["model_sums"] == [_completed_sum(UNIT_A), _completed_sum(UNIT_B)]
    assert record["crossing_unit"] is None
    assert record["blocked_unit"] is None
    assert record["halt"] is False
    assert record["degraded_units"] == []
    assert [entry["unit_id"] for entry in record["trajectory"]] == [
        UNIT_A] * 5 + [UNIT_B] * 5
    assert {entry["to_state"] for entry in record["trajectory"]} == {
        state.value for state in ModelState}
    assert all(entry["outcome"] == "gate" for entry in record["trajectory"])
    assert record["trajectory"][-1]["signal"] == ModelState.COMPLETED.value


def test_the_halt_completes_the_crossing_unit_and_never_models_the_blocked_one(
        tmp_path, monkeypatch):
    """S1 7.4 / S2 7.4: the accumulator is checked after each COMPLETED write;
    on an inclusive crossing the crossing unit is fully modelled and the NEXT
    unit in the intake order is never modelled - it is recorded as the blocked
    unit with `halt` set."""
    monkeypatch.setenv("HUNT_RISK_THRESHOLD", "5")
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        # one `high` loop's worth of budget (3), committed through the store
        from tests.hunting_fixtures import modeller_gate_payloads
        for state, sections in modeller_gate_payloads().items():
            tools.threat_store.write_sections(
                project_id, unit_id, state, sections, run_id=run_id)
        return UnitOutcome(unit_id=unit_id, status="completed")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 3), (UNIT_B, 2), (UNIT_C, 1)),
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_A, UNIT_B]              # the blocked unit is never seen
    record = fake.run_record(RUN)
    assert record["threshold_basis"] == "override"
    assert record["risk_threshold"] == 5
    assert record["risk_total"] == 6             # 3 + 3, inclusive `>=`
    assert record["crossing_unit"] == UNIT_B
    assert record["blocked_unit"] == UNIT_C
    assert record["halt"] is True
    assert record["intake_position"] == 2
    assert models.read_model(PROJECT, UNIT_C) is None


def test_a_degraded_unit_is_recorded_and_the_run_continues(tmp_path, monkeypatch):
    """S1 7.7: a degraded unit contributes no budget, is recorded with its
    reason, and the run continues to the next unit."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    seen: list[str] = []

    async def mixed_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        if unit_id == UNIT_B:
            return UnitOutcome(unit_id=unit_id, status="degraded",
                               reason="the target was unreachable")
        from tests.hunting_fixtures import modeller_gate_payloads
        for state, sections in modeller_gate_payloads().items():
            tools.threat_store.write_sections(
                project_id, unit_id, state, sections, run_id=run_id)
        return UnitOutcome(unit_id=unit_id, status="completed")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 2), (UNIT_B, 1)),
        modeller_pass_fn=mixed_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_A, UNIT_B]
    record = fake.run_record(RUN)
    assert record["degraded_units"] == [
        {"unit_id": UNIT_B, "reason": "the target was unreachable"}]
    assert record["risk_total"] == 3             # the degraded unit is zero
    assert [entry["unit_id"] for entry in record["model_sums"]] == [UNIT_A]
    assert record["intake_position"] == 2
    assert record["halt"] is False


def test_a_resumed_run_re_enters_at_the_intake_position(tmp_path, monkeypatch):
    """S1 7.5: a stopped run resumes from the persisted run record - it re-enters
    at `intake_position`, keeps the recorded order and threshold, recomputes the
    total from `model_sums`, and models only the units that remain."""
    fake = _resume_fake(_seed_record(
        intake_order=[UNIT_A, UNIT_B],
        intake_position=1,
        risk_total=3,
        risk_breakdown={"none": 0, "low": 0, "medium": 0, "high": 1,
                        "critical": 0},
        model_sums=[_completed_sum(UNIT_A)],
    ))
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    _write_completed_model(models, UNIT_A)
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        from tests.hunting_fixtures import modeller_gate_payloads
        for state, sections in modeller_gate_payloads().items():
            tools.threat_store.write_sections(
                project_id, unit_id, state, sections, run_id=run_id)
        return UnitOutcome(unit_id=unit_id, status="completed")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 3), (UNIT_B, 1)),
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_B]                      # UNIT_A is never re-modelled
    record = fake.run_record(RUN)
    assert set(record) == set(RUN_RECORD_KEYS)
    assert record["intake_order"] == [UNIT_A, UNIT_B]
    assert record["intake_position"] == 2
    assert record["risk_total"] == 6
    assert [entry["unit_id"] for entry in record["model_sums"]] == [
        UNIT_A, UNIT_B]


def test_a_crash_between_the_model_and_the_run_record_leaves_no_stale_total(
        tmp_path, monkeypatch):
    """S1 7.5 commit order: the model document commits BEFORE the run-record
    update. A crash between the two leaves a complete model the record does not
    mention; the resume ADOPTS it, so the recorded total can never be stale."""
    fake = _resume_fake(_seed_record(
        intake_order=[UNIT_A, UNIT_B],
        intake_position=0,
        risk_total=0,                            # stale: the record never updated
        model_sums=[],
    ))
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    _write_completed_model(models, UNIT_A)       # committed, unrecorded
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="degraded")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_B]                      # the committed unit is adopted
    record = fake.run_record(RUN)
    assert record["intake_position"] == 2
    assert record["risk_total"] == 3             # the adopted model's sum
    assert [entry["unit_id"] for entry in record["model_sums"]] == [UNIT_A]


def test_a_halted_run_resumes_dispatch_only(tmp_path, monkeypatch):
    """S1 7.5: a halted run resumes with the dequeue closed - it models nothing
    more and the halt's audit trail survives the restart."""
    fake = _resume_fake(_seed_record(
        intake_order=[UNIT_A, UNIT_B, UNIT_C],
        intake_position=2,
        risk_total=6,
        model_sums=[_completed_sum(UNIT_A), _completed_sum(UNIT_B)],
        crossing_unit=UNIT_B, blocked_unit=UNIT_C, halt=True,
    ))
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)

    async def exploding_pass(project_id, run_id, unit_id, tools, **kwargs):
        raise AssertionError(f"a halted run must not model {unit_id}")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        modeller_pass_fn=exploding_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert fake.statuses[-1] == (RUN, "complete")
    record = fake.run_record(RUN)
    assert record["halt"] is True
    assert record["crossing_unit"] == UNIT_B
    assert record["blocked_unit"] == UNIT_C
    assert record["intake_position"] == 2
    assert record["risk_total"] == 6


def test_the_freeze_excludes_the_completed_and_the_in_flight_units(
        tmp_path, monkeypatch):
    """S2 9.3 / T11 #398: a unit whose COMPLETED model already lives in
    `consumed/` is excluded (`completed`) and a unit whose model is in flight in
    `produced/` under a RESUMABLE `interrupted` run (a transient throttle whose
    backoff elapsed) is skipped (`in-flight`) - both recorded with their reason
    and never modelled."""
    from datetime import datetime, timedelta, timezone

    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    # the producing run paused on a TRANSIENT throttle with its class stamped:
    # the resume decision is resumable, so its produced model is in flight (a
    # second writer would break the sole-writer rule)
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.list_hunting_runs",
        lambda project_id: [{
            "hunting_run_id": "paused-run",
            "project_id": PROJECT,
            "status": "interrupted",
            "finished_at": datetime.now(timezone.utc) - timedelta(seconds=5),
            "stats": {"interrupted": True, "quota_exhausted": False,
                      "retry_after_s": 0.0},
        }],
    )
    hunter, models = _stores(tmp_path)
    _write_completed_model(models, UNIT_A)
    # the model moves with its last loop file: the unit is decided in consumed/
    assert models.consume_loop(PROJECT, UNIT_A, "loop-1") is True
    assert models.read_completed_units(PROJECT) == [UNIT_A]
    models.write_sections(PROJECT, UNIT_B, ModelState.TRUST_MODELLED, {
        "trust_model": {"trust_agreements": [{
            "id": "ta-1", "boundary": "b", "statement": "s",
            "confidence": "INFERRED", "evidences": []}]},
    }, run_id="paused-run")
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="degraded")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 3), (UNIT_B, 2), (UNIT_C, 1)),
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_C]
    record = fake.run_record(RUN)
    assert record["intake_order"] == [UNIT_C]
    assert record["intake_excluded"] == [
        {"unit_id": UNIT_A, "reason": "completed"},
        {"unit_id": UNIT_B, "reason": "in-flight"},
    ]


def test_a_stale_produced_model_of_a_terminal_run_is_archived_and_retried(
        tmp_path, monkeypatch):
    """S2 9.3: a produced model whose producing run is terminal and not
    resumable is stale - the freeze archives it to `abandoned/` and the unit is
    retried in the same run."""
    fake = _FakePg()
    fake.statuses.append(("dead-run", "failed"))      # terminal, not resumable
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    models.write_sections(PROJECT, UNIT_B, ModelState.TRUST_MODELLED, {
        "trust_model": {"trust_agreements": [{
            "id": "ta-1", "boundary": "b", "statement": "s",
            "confidence": "INFERRED", "evidences": []}]},
    }, run_id="dead-run")
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="degraded")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_B, 2)),
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_B]
    record = fake.run_record(RUN)
    assert record["intake_order"] == [UNIT_B]
    assert record["intake_excluded"] == []
    assert models.read_abandoned_units(PROJECT) == [UNIT_B]


def test_an_abandoned_model_is_ignored_and_the_unit_is_retried(
        tmp_path, monkeypatch):
    """S2 9.3: `abandoned/` is a graveyard, never an exclusion - a unit with an
    abandoned model is retried and modelled again."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    models.write_sections(PROJECT, UNIT_A, ModelState.UNIT_TECHNICAL_SHARP, {
        "technical_sharpening": {"interface_agreements": [{
            "id": "ia-1", "statement": "s", "confidence": "OBSERVED",
            "evidences": []}]},
    }, run_id="dead-run")
    assert models.archive_unit(PROJECT, UNIT_A, "degraded (fixture)") is not None
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="degraded")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 1)),
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_A]
    assert fake.run_record(RUN)["intake_excluded"] == []


def test_the_modeller_does_not_wait_for_dispatch(tmp_path, monkeypatch):
    """S1 7.3: the pass and the surfer are independent sessions - the surfer
    dispatches produced work while the pass is still modelling, so the pass
    never waits for a dispatch."""
    fake = _FakePg()
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    # a produced loop file of THIS run is the dispatch input (S2 8.4): the
    # surfer dispatches it while the pass is still modelling
    produce_model(
        models, project_id=PROJECT, unit_id=UNIT_C, run_id=RUN)
    events: list[str] = []

    async def slow_pass(project_id, run_id, unit_id, tools, **kwargs):
        events.append(f"model:{unit_id}")
        await asyncio.sleep(0.05)
        events.append(f"modelled:{unit_id}")
        return UnitOutcome(unit_id=unit_id, status="degraded")

    def hunter_builder(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            events.append("dispatch")
            return None
        return dispatch, None

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 1)),
        modeller_pass_fn=slow_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert "dispatch" in events, "the surfer must dispatch the produced config"
    assert events.index("dispatch") < events.index(f"modelled:{UNIT_A}"), (
        "the hunt dispatched while the pass was still modelling the unit"
    )


def test_the_runtime_no_longer_selects_units_through_the_fault_source_path():
    """S1 7.1/9.1: the intake order REPLACES the selection path. The runtime
    carries no fault-source/KB selection seam, no candidate intake, and no
    transitional order: a run's unit set is read from the L1 inventory (or an
    injected snapshot) and frozen."""
    import inspect

    source = inspect.getsource(hunting_runtime)
    for retired in ("fault_source", "fault_kb", "symptom_kb", "fault_risk",
                    "materialize_candidates", "select(", "DeliveredCandidate",
                    "Witness", "transitional_unit_order"):
        assert retired not in source, f"the runtime must not carry {retired!r}"

    parameters = inspect.signature(hunting_runtime.start_hunting).parameters
    for retired in ("candidates", "fault_entries", "match_fn", "unit_ids_fn"):
        assert retired not in parameters, f"{retired!r} is a retired seam"
    assert not hasattr(hunting_runtime, "transitional_unit_order")


def test_a_stopped_runs_produced_model_is_in_flight_and_its_unit_is_skipped(
        tmp_path, monkeypatch):
    """S1 7.5 / S2 9.3: a `stopped` run is RESUMABLE (it resumes from the
    persisted run record), so its produced model must be treated as in flight -
    the next run SKIPS the unit and never archives (destroys) the stopped run's
    model and its pending loop files."""
    fake = _FakePg()
    fake.statuses.append(("stopped-run", "stopped"))
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    _write_completed_model(models, UNIT_A,
                           run_id="stopped-run")   # the stopped run's model
    seen: list[str] = []

    async def recording_pass(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="degraded")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 3), (UNIT_B, 1)),
        modeller_pass_fn=recording_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert seen == [UNIT_B]                         # the stopped unit is skipped
    record = fake.run_record(RUN)
    assert record["intake_excluded"] == [
        {"unit_id": UNIT_A, "reason": "in-flight"}]
    # the stopped run's produced model SURVIVES: nothing was archived
    assert models.read_abandoned_units(PROJECT) == []
    assert models.read_model(PROJECT, UNIT_A)["state"] == ModelState.COMPLETED.value


def test_a_resume_that_models_nothing_re_persists_the_recomputed_record(
        tmp_path, monkeypatch):
    """S1 7.5: a resume whose ADOPTION itself crosses the threshold halts before
    the unit loop runs, so no loop iteration can write the record. The persisted
    row must still carry the recomputed total, the adopted model sum and the
    halt fields - the pre-crash record would otherwise read `risk_total=0` and
    `halt=false` for a run that is already halted."""
    fake = _resume_fake(_seed_record(
        intake_order=[UNIT_A, UNIT_B],
        intake_position=0,
        risk_threshold=3,                 # one adopted `high` loop crosses it
        threshold_basis="override",
        risk_total=0,                     # stale: the record never updated
        model_sums=[],
    ))
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    _write_completed_model(models, UNIT_A)       # committed before the crash

    async def exploding_pass(project_id, run_id, unit_id, tools, **kwargs):
        raise AssertionError(f"the halt must stop the dequeue at {unit_id}")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        modeller_pass_fn=exploding_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    record = fake.run_record(RUN)
    assert record["risk_total"] == 3
    assert [entry["unit_id"] for entry in record["model_sums"]] == [UNIT_A]
    assert record["halt"] is True
    assert record["crossing_unit"] == UNIT_A
    assert record["blocked_unit"] == UNIT_B
    assert record["intake_position"] == 1
    assert fake.statuses[-1] == (RUN, "complete")


class _RecordingPg(_FakePg):
    """The wiring fake pg plus a shared event log: every record write lands as
    `("record", <the model_sums unit ids it carries>)`, so a test can assert the
    commit ORDER against the model writes."""

    def __init__(self, events: list):
        super().__init__()
        self.events = events

    def set_hunting_run_stats(self, hunting_run_id: str, stats: dict) -> None:
        self.events.append((
            "record",
            tuple(entry["unit_id"]
                  for entry in (stats or {}).get("model_sums") or []),
        ))
        super().set_hunting_run_stats(hunting_run_id, stats)


class _RecordingStore:
    """Wraps the real store and logs every gate write as
    `("model", unit_id, gate)`; every other store call proxies."""

    def __init__(self, inner, events: list):
        self._inner = inner
        self.events = events

    def write_sections(self, project_id, unit_id, state, sections, *, run_id):
        self.events.append(
            ("model", unit_id, str(getattr(state, "value", state))))
        return self._inner.write_sections(
            project_id, unit_id, state, sections, run_id=run_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _RaisingCompletedStore(_RecordingStore):
    """The commit-order failure injection: the COMPLETED write raises, so the
    model document never lands."""

    def write_sections(self, project_id, unit_id, state, sections, *, run_id):
        if str(getattr(state, "value", state)) == "COMPLETED":
            self.events.append(("model-failed", unit_id, "COMPLETED"))
            raise OSError("model commit failed (fixture)")
        return super().write_sections(
            project_id, unit_id, state, sections, run_id=run_id)


def test_the_model_commits_before_the_run_record_on_every_unit(tmp_path, monkeypatch):
    """S1 7.5 commit order: the model document commits BEFORE the run-record
    update. The event log proves it per unit: each unit's COMPLETED write
    precedes the record write that counts its sum, in intake order."""
    events: list = []
    fake = _RecordingPg(events)
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    recording = _RecordingStore(models, events)

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 2), (UNIT_B, 1)),
        modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
        control=_FakeControl(),
        hunter_store=hunter, threat_store=recording,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    for unit_id in (UNIT_A, UNIT_B):
        commit = events.index(("model", unit_id, "COMPLETED"))
        counted = next(
            index for index, event in enumerate(events)
            if event[0] == "record" and unit_id in event[1])
        assert commit < counted, (
            f"{unit_id}: the run record counted the unit before its model "
            f"committed ({events})"
        )
    assert events.index(("model", UNIT_A, "COMPLETED")) < events.index(
        ("model", UNIT_B, "COMPLETED"))


def test_a_failed_model_commit_is_never_counted_in_the_run_record(
        tmp_path, monkeypatch):
    """The commit order's failure injection: when the COMPLETED write raises the
    model never lands, so the run record must carry NO sum for that unit - an
    order that recorded the sum first would claim a model that does not exist."""
    events: list = []
    fake = _RecordingPg(events)
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)
    recording = _RaisingCompletedStore(models, events)

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        intake_units=_units((UNIT_A, 1)),
        modeller_kwargs={"turn_fn": ScriptedModellerTurns()},
        control=_FakeControl(),
        hunter_store=hunter, threat_store=recording,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert ("model-failed", UNIT_A, "COMPLETED") in events
    record = fake.run_record(RUN)
    assert record["model_sums"] == []
    assert record["risk_total"] == 0
    assert [entry["unit_id"] for entry in record["degraded_units"]] == [UNIT_A]
    assert record["intake_position"] == 1


def test_a_resumed_run_clears_the_stale_provider_interrupt_keys(
        tmp_path, monkeypatch):
    """M7: the provider-failure handler stamps `interrupted` / `interrupt_reason`
    / `provider_status` onto the run row, and the additive stats merge never
    clears them - the eval reads `interrupt_reason`. A resume that completes the
    run must clear them: a completed run is not interrupted."""
    fake = _resume_fake(_seed_record(
        intake_order=[UNIT_A],
        intake_position=1,                # the intake was already exhausted
        risk_total=3,
        model_sums=[_completed_sum(UNIT_A)],
        interrupted=True,
        interrupt_reason="provider unavailable (status=429)",
        provider_status=429,
        quota_exhausted=False,
        retry_after_s=45.0,
    ))
    _patch_pg(monkeypatch, fake)
    hunter, models = _stores(tmp_path)

    async def exploding_pass(project_id, run_id, unit_id, tools, **kwargs):
        raise AssertionError(f"the intake is exhausted at {unit_id}")

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT, run_id=RUN,
        modeller_pass_fn=exploding_pass,
        control=_FakeControl(),
        hunter_store=hunter, threat_store=models,
        hunter_builder=_noop_hunter_builder, pod_builder=_noop_pod_builder,
        tick_interval=0.001,
    ))

    assert fake.statuses[-1] == (RUN, "complete")
    record = fake.run_record(RUN)
    assert record["interrupted"] is None
    assert record["interrupt_reason"] is None
    assert record["provider_status"] is None
    assert record["quota_exhausted"] is None
    assert record["retry_after_s"] is None
    assert record["risk_total"] == 3      # the run record itself is untouched
