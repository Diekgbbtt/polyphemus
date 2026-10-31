"""Unit tier: the run lifecycle - the risk accumulator, the halt, the run record,
and the resume rules (S1 7.4-7.5, S2 7.4 and 9.2-9.4; T3 #376, T7 #410).

Pure run state: no store, no PG, no LLM. The unit total sums the threats'
mirrored CVSS 4.0 `risk` (a float in `0.0 .. 10.0`), the breakdown counts them
by severity band, and the run record is the dict the run row's `stats` carries,
so these tests assert the record's fixed keys and their values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from polymerhus.attack.hunting.run_lifecycle import (
    DEFAULT_RISK_THRESHOLD,
    RUN_RECORD_KEYS,
    ModelSum,
    ThreatModelRun,
    model_sum,
    resume_run,
    threshold_config,
    trajectory_entry,
)
from polymerhus.attack.hunting.threat_modeller import TrailEntry
from polymerhus.attack.hunting.unit_intake import IntakeExclusion


def _breakdown(**counts: int) -> dict[str, int]:
    bands = {"none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}
    bands.update(counts)
    return bands


def _record(**overrides) -> dict:
    """A persisted run record (the run row's `stats`), overridable per case."""
    record = {
        "intake_order": ["Service:a", "Service:b"],
        "intake_position": 0,
        "intake_excluded": [],
        "risk_threshold": 112.5,
        "threshold_basis": "override",
        "risk_total": 0.0,
        "risk_breakdown": _breakdown(),
        "model_sums": [],
        "crossing_unit": None,
        "blocked_unit": None,
        "halt": False,
        "degraded_units": [],
        "trajectory": [],
    }
    record.update(overrides)
    return record


def _model(*risks: float) -> dict:
    """A persisted COMPLETED, valid model carrying one threat per score."""
    return {
        "state": "COMPLETED",
        "validation": {"valid": True},
        "threats": [{"risk": risk} for risk in risks],
    }


def test_the_unit_total_sums_the_mirrored_threat_risk():
    """S2 7.3 (schema 5): the harness-owned per-unit total sums every threat's
    mirrored CVSS 4.0 `risk` (rounded to two decimals, as the score is), and the
    breakdown counts every threat by its severity band."""
    model = {"threats": [
        {"risk": 9.9},                          # critical
        {"risk": 9.3},                          # critical
        {"risk": 7.0},                          # high
        {"risk": 4.0},                          # medium
        {"risk": 0.0},                          # none
    ]}

    assert model_sum("Service:a", model) == ModelSum(
        unit_id="Service:a",
        total=30.2,
        breakdown=_breakdown(none=1, medium=1, high=1, critical=2),
    )


def test_a_threat_without_a_score_contributes_zero_to_the_unit_total():
    """A threat whose `risk` is absent or not a number consumes no budget and
    counts in the `none` band: a malformed row can never inflate the halt."""
    model = {"threats": [
        {"risk": 5.0},
        {},
        {"risk": "n/a"},
    ]}

    assert model_sum("Service:a", model) == ModelSum(
        unit_id="Service:a",
        total=5.0,
        breakdown=_breakdown(none=2, medium=1),
    )


def test_the_halt_crosses_inclusively_and_blocks_the_next_unit():
    """S1 7.4 / S2 7.4: the comparison is inclusive (`>=`) on the FLOAT total; the
    crossing unit is the unit whose model crossed, the NEXT unit in the intake
    order is never modelled, and it is recorded as the blocked unit."""
    run = ThreatModelRun.start(
        order=("Service:a", "Service:b", "Service:c"), threshold=16.25)

    run.complete_unit("Service:a", ModelSum("Service:a", 9.0, _breakdown(critical=1)))
    assert run.accumulator.halt is False
    assert run.next_unit == "Service:b"

    run.complete_unit("Service:b", ModelSum("Service:b", 7.25, _breakdown(high=1)))

    assert run.accumulator.total == 16.25
    assert run.accumulator.halt is True
    assert run.crossing_unit == "Service:b"
    assert run.blocked_unit == "Service:c"
    assert run.next_unit is None


def test_the_run_record_carries_every_fixed_key():
    """S1 7.4 / S2 9.2/9.4: the run record carries the fixed key set (the
    accumulator's audit trail, the intake order and position, the exclusions,
    the degraded units and the trajectory), and it is JSON-safe - it is the run
    row's `stats` payload. The likelihood and impact weight tables and the impact
    breakdown are RETIRED (T7 #410): the risk is one float total by band."""
    run = ThreatModelRun.start(
        order=("Service:a",),
        excluded=(IntakeExclusion("Service:b", "completed"),),
        threshold=112.5, basis="default",
    )
    run.complete_unit("Service:a", ModelSum(
        "Service:a", 9.2, _breakdown(critical=1)))

    record = run.record()

    assert set(record) == set(RUN_RECORD_KEYS)
    assert record["intake_order"] == ["Service:a"]
    assert record["intake_position"] == 1
    assert record["intake_excluded"] == [
        {"unit_id": "Service:b", "reason": "completed"}]
    assert record["risk_threshold"] == 112.5
    assert record["threshold_basis"] == "default"
    assert record["risk_total"] == 9.2
    assert isinstance(record["risk_total"], float)
    assert record["risk_breakdown"] == _breakdown(critical=1)
    assert record["model_sums"] == [
        {"unit_id": "Service:a", "total": 9.2,
         "breakdown": _breakdown(critical=1)}]
    assert record["crossing_unit"] is None
    assert record["blocked_unit"] is None
    assert record["halt"] is False
    assert record["degraded_units"] == []
    assert record["trajectory"] == []
    for retired in ("risk_weights", "impact_weights", "impact_breakdown"):
        assert retired not in record, f"{retired} is a retired run-record key"
    assert json.loads(json.dumps(record)) == record


def test_resume_re_enters_at_the_intake_position_and_recomputes_the_total():
    """S1 7.5: a stopped run resumes from the persisted run record. It re-enters
    at `intake_position`, reads the recorded order, threshold and basis, and
    RECOMPUTES `risk_total` from `model_sums` - never from the recorded total."""
    record = _record(
        intake_position=1,
        intake_excluded=[{"unit_id": "Service:c", "reason": "completed"}],
        model_sums=[{"unit_id": "Service:a", "total": 9.2,
                     "breakdown": _breakdown(critical=1)}],
        risk_total=999.0,                     # stale: never trusted
    )

    run = resume_run(record, models={"Service:a": _model(9.2)})

    assert run.next_unit == "Service:b"
    assert run.accumulator.total == 9.2
    assert run.accumulator.threshold == 112.5
    assert isinstance(run.accumulator.threshold, float)
    assert run.accumulator.basis == "override"
    assert run.accumulator.breakdown == _breakdown(critical=1)
    # the exclusions are part of the audit trail a restart must not lose
    assert run.record()["intake_excluded"] == [
        {"unit_id": "Service:c", "reason": "completed"}]


def test_resume_round_trips_a_v5_float_threshold_and_a_float_total():
    """S1 7.5 / T7 (#410): a record written by the float accumulator resumes with
    its threshold and its total intact. The stored `112.5` threshold and the
    recomputed `10.3` total are floats on the way back out, never truncated."""
    record = _record(
        intake_position=2,
        risk_threshold=112.5,
        risk_total=10.3,
        risk_breakdown=_breakdown(low=1, critical=1),
        model_sums=[
            {"unit_id": "Service:a", "total": 9.2,
             "breakdown": _breakdown(critical=1)},
            {"unit_id": "Service:b", "total": 1.1,
             "breakdown": _breakdown(low=1)},
        ],
    )

    run = resume_run(record)

    assert run.accumulator.threshold == 112.5
    assert isinstance(run.accumulator.threshold, float)
    assert run.accumulator.total == 10.3
    assert isinstance(run.accumulator.total, float)
    resumed = run.record()
    assert resumed["risk_threshold"] == 112.5
    assert resumed["risk_total"] == 10.3
    assert resumed["risk_breakdown"] == _breakdown(low=1, critical=1)


def test_resume_adopts_a_model_committed_before_the_run_record_update():
    """S1 7.5 commit order: the model document commits BEFORE the run-record
    update, so a crash between the two leaves a complete model the record does
    not mention. The resume adopts it - the unit is never re-modelled and its
    sum can never leave a stale total behind."""
    record = _record(intake_position=0, model_sums=[], risk_total=0.0)

    run = resume_run(record, models={"Service:a": _model(9.2)})

    assert run.intake_position == 1
    assert run.next_unit == "Service:b"
    assert run.accumulator.total == 9.2
    assert run.record()["model_sums"] == [
        {"unit_id": "Service:a", "total": 9.2,
         "breakdown": _breakdown(critical=1)}]
    assert run.record()["risk_total"] == 9.2


def test_a_resume_keeps_one_degraded_entry_per_unit():
    """S2 9.2: the crash window lets a resume degrade the same unit twice (the
    record can lag the position), so the restored `degraded_units` carries ONE
    entry per unit id - the latest reason wins."""
    record = _record(
        intake_order=["Service:a", "Service:b"],
        intake_position=1,
        degraded_units=[
            {"unit_id": "Service:a", "reason": "the target was unreachable"},
            {"unit_id": "Service:a", "reason": "the projection was unparseable"},
            {"unit_id": "Service:b", "reason": "the pass aborted"},
        ],
    )

    run = resume_run(record)

    assert run.record()["degraded_units"] == [
        {"unit_id": "Service:a", "reason": "the projection was unparseable"},
        {"unit_id": "Service:b", "reason": "the pass aborted"},
    ]


def test_the_resume_adoption_stops_at_the_crossing_unit():
    """S1 7.4/7.5: the adoption replays the halt check per adopted model, and the
    FIRST crossing is final - the crossing unit is the last one adopted, the next
    one is the blocked unit, and the position stops there (the order is never
    re-ranked, and a later complete model never overwrites the audit trail).
    The float comparison is inclusive: `9.2 >= 9.2` crosses."""
    record = _record(
        intake_order=["Service:a", "Service:b", "Service:c"],
        intake_position=0,
        risk_threshold=9.2,
        threshold_basis="override",
    )

    run = resume_run(record, models={
        "Service:a": _model(9.2),             # the inclusive crossing
        "Service:b": _model(9.2),
        "Service:c": None,
    })

    assert run.crossing_unit == "Service:a"
    assert run.blocked_unit == "Service:b"
    assert run.intake_position == 1
    assert run.accumulator.total == 9.2
    assert run.next_unit is None
    assert run.halt is True
    assert [entry["unit_id"] for entry in run.record()["model_sums"]] == [
        "Service:a"]


def test_a_halted_run_resumes_dispatch_only():
    """S1 7.5: a halted run resumes dispatch only - it never models another unit
    (the dequeue stays closed) and the halt's audit trail survives the restart."""
    record = _record(
        intake_position=1, halt=True,
        crossing_unit="Service:a", blocked_unit="Service:b",
        model_sums=[{"unit_id": "Service:a", "total": 9.2,
                     "breakdown": _breakdown(critical=1)}],
        risk_total=9.2,
    )

    run = resume_run(record, models={"Service:a": _model(9.2)})

    assert run.halt is True
    assert run.next_unit is None
    assert run.crossing_unit == "Service:a"
    assert run.blocked_unit == "Service:b"
    assert run.accumulator.total == 9.2


def test_the_threshold_records_whether_it_is_the_default_or_an_override():
    """S2 7.4 / ADR 8: the threshold default is the old 250 scaled by the 0.625
    ratio (`156.25`); `HUNT_RISK_THRESHOLD` parses a float and overrides it, and
    the run records the basis (`default` / `override`) so the halt is
    reproducible. A malformed override falls back to the default."""
    assert DEFAULT_RISK_THRESHOLD == 156.25
    assert threshold_config({}) == (156.25, "default")
    assert threshold_config({"HUNT_RISK_THRESHOLD": "112.5"}) == (112.5, "override")
    assert threshold_config({"HUNT_RISK_THRESHOLD": "not-a-number"}) == (
        156.25, "default")


def test_threshold_config_reads_a_float_from_the_db_and_falls_back_on_a_bad_one():
    """S2 7.4: the stored `settings.hunting.risk_threshold` wins and is read as a
    float; a malformed or negative stored value warns and falls back to the env
    basis, so a bad row can never silently disable the halt."""
    assert threshold_config({"HUNT_RISK_THRESHOLD": "7"}, db_value=112.5) == (
        112.5, "db")
    assert threshold_config({"HUNT_RISK_THRESHOLD": "7"}, db_value="oops") == (
        7.0, "override")
    assert threshold_config({"HUNT_RISK_THRESHOLD": "7"}, db_value=-1.0) == (
        7.0, "override")


def test_a_degraded_unit_is_recorded_and_consumes_no_budget():
    """S1 7.7: a degraded unit is recorded with its reason, contributes nothing
    to the accumulator, and the run continues to the next unit."""
    run = ThreatModelRun.start(
        order=("Service:a", "Service:b"), threshold=112.5)

    run.degrade_unit("Service:a", "no threat model was written for this unit")

    assert run.intake_position == 1
    assert run.next_unit == "Service:b"
    assert run.accumulator.total == 0.0
    assert run.accumulator.model_sums == []
    assert run.record()["degraded_units"] == [{
        "unit_id": "Service:a",
        "reason": "no threat model was written for this unit",
    }]


def test_the_trajectory_entry_records_the_signal_states_and_skipped_gates():
    """S1 6.1 / S2 9.2: a trajectory entry records the unit, the signal, the
    from-state, the to-state, the outcome and the time - and a forward jump also
    records the gates it skipped, so a skipped gate stays auditable."""
    entry = trajectory_entry("Service:a", TrailEntry(
        kind="gate", state="COMPLETED", previous_state="TRUST_MODELLED",
        skipped=["TRUST_ASSUMPTIONS_WRITTEN", "VULNERABILITIES_WRITTEN"],
        sections=["threats"],
        at=datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc),
    ))

    assert entry == {
        "unit_id": "Service:a",
        "signal": "COMPLETED",
        "from_state": "TRUST_MODELLED",
        "to_state": "COMPLETED",
        "outcome": "gate",
        "skipped": ["TRUST_ASSUMPTIONS_WRITTEN", "VULNERABILITIES_WRITTEN"],
        "at": "2026-10-19T09:30:00+00:00",
    }
