"""Unit tier: the run lifecycle - the symbolic risk accumulator, the halt, the
run record, and the resume rules (S1 7.4-7.5, S2 7.4 and 9.2-9.4; T3 #376).

Pure run state: no store, no PG, no LLM. The run record is the dict the run row's
`stats` carries, so these tests assert the record's fixed keys and their values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from polymerhus.attack.hunting.run_lifecycle import (
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
    levels = {"none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}
    levels.update(counts)
    return levels


def _record(**overrides) -> dict:
    """A persisted run record (the run row's `stats`), overridable per case."""
    record = {
        "intake_order": ["Service:a", "Service:b"],
        "intake_position": 0,
        "intake_excluded": [],
        "risk_threshold": 12,
        "threshold_basis": "override",
        "risk_weights": {"none": 0, "low": 1, "medium": 2, "high": 3,
                         "critical": 4},
        "impact_weights": {"none": 0, "low": 1, "medium": 2, "high": 3,
                           "critical": 4},
        "risk_total": 0,
        "risk_breakdown": _breakdown(),
        "impact_breakdown": _breakdown(),
        "model_sums": [],
        "crossing_unit": None,
        "blocked_unit": None,
        "halt": False,
        "degraded_units": [],
        "trajectory": [],
    }
    record.update(overrides)
    return record


def _impact(confidentiality="low", integrity="none", availability="none") -> dict:
    return {
        "confidentiality": confidentiality,
        "integrity": integrity,
        "availability": availability,
        "end_impact": "a literal end effect",
    }


def _model(*likelihoods: str) -> dict:
    """A persisted COMPLETED, valid model carrying the given loop levels.

    The impact weight is 1 for every loop, so the combined total equals the
    likelihood total in the resume fixtures.
    """
    return {
        "state": "COMPLETED",
        "validation": {"valid": True},
        "loops": [
            {"likelihood": level, "impact": _impact()} for level in likelihoods
        ],
    }


def test_the_unit_total_sums_the_combined_loop_risk():
    """S2 7.3 (amended 2026-10-25): the harness-owned per-unit total sums the
    combined loop risk (likelihood weight x impact weight), the likelihood
    breakdown counts every loop, and the impact breakdown counts every loop by
    its ordinal impact severity."""
    model = {"loops": [
        {"likelihood": "critical", "impact": _impact("high", "high", "high")},
        {"likelihood": "high", "impact": _impact("high", "high")},
        {"likelihood": "medium", "impact": _impact("medium")},
        {"likelihood": "low", "impact": _impact("low")},
        {"likelihood": "none", "impact": _impact("high", "high", "high")},
    ]}

    assert model_sum("Service:a", model) == ModelSum(
        unit_id="Service:a",
        total=16 + 12 + 4 + 1 + 0,
        breakdown={"none": 1, "low": 1, "medium": 1, "high": 1, "critical": 1},
        impact_breakdown={
            "none": 0, "low": 1, "medium": 1, "high": 0, "critical": 3,
        },
    )


def test_a_loop_without_impact_contributes_zero_to_the_unit_total():
    model = {"loops": [
        {"likelihood": "critical"},
        {"likelihood": "high"},
    ]}

    assert model_sum("Service:a", model) == ModelSum(
        unit_id="Service:a",
        total=0,
        breakdown={"none": 0, "low": 0, "medium": 0, "high": 1, "critical": 1},
        impact_breakdown={
            "none": 2, "low": 0, "medium": 0, "high": 0, "critical": 0,
        },
    )


def test_the_halt_crosses_inclusively_and_blocks_the_next_unit():
    """S1 7.4 / S2 7.4: the comparison is inclusive (`>=`); the crossing unit is
    the unit whose model crossed, the NEXT unit in the intake order is never
    modelled, and it is recorded as the blocked unit."""
    run = ThreatModelRun.start(
        order=("Service:a", "Service:b", "Service:c"), threshold=5)

    run.complete_unit("Service:a", ModelSum("Service:a", 2, _breakdown(medium=1)))
    assert run.accumulator.halt is False
    assert run.next_unit == "Service:b"

    run.complete_unit("Service:b", ModelSum("Service:b", 3, _breakdown(high=1)))

    assert run.accumulator.total == 5
    assert run.accumulator.halt is True
    assert run.crossing_unit == "Service:b"
    assert run.blocked_unit == "Service:c"
    assert run.next_unit is None


def test_the_run_record_carries_every_fixed_key():
    """S1 7.4 / S2 9.2/9.4: the run record carries the fixed key set (the
    accumulator's audit trail, the intake order and position, the exclusions,
    the degraded units and the trajectory), and it is JSON-safe - it is the run
    row's `stats` payload."""
    run = ThreatModelRun.start(
        order=("Service:a",),
        excluded=(IntakeExclusion("Service:b", "completed"),),
        threshold=12, basis="default",
    )
    run.complete_unit("Service:a", ModelSum(
        "Service:a", 3, _breakdown(high=1), _breakdown(low=1)))

    record = run.record()

    assert set(record) == set(RUN_RECORD_KEYS)
    assert record["intake_order"] == ["Service:a"]
    assert record["intake_position"] == 1
    assert record["intake_excluded"] == [
        {"unit_id": "Service:b", "reason": "completed"}]
    assert record["risk_threshold"] == 12
    assert record["threshold_basis"] == "default"
    assert record["risk_weights"] == {
        "none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    assert record["impact_weights"] == {
        "none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    assert record["risk_total"] == 3
    assert record["risk_breakdown"] == _breakdown(high=1)
    assert record["impact_breakdown"] == _breakdown(low=1)
    assert record["model_sums"] == [
        {"unit_id": "Service:a", "total": 3, "breakdown": _breakdown(high=1),
         "impact_breakdown": _breakdown(low=1)}]
    assert record["crossing_unit"] is None
    assert record["blocked_unit"] is None
    assert record["halt"] is False
    assert record["degraded_units"] == []
    assert record["trajectory"] == []
    assert json.loads(json.dumps(record)) == record


def test_resume_re_enters_at_the_intake_position_and_recomputes_the_total():
    """S1 7.5: a stopped run resumes from the persisted run record. It re-enters
    at `intake_position`, reads the recorded order, threshold and basis, and
    RECOMPUTES `risk_total` from `model_sums` - never from the recorded total."""
    record = _record(
        intake_position=1,
        intake_excluded=[{"unit_id": "Service:c", "reason": "completed"}],
        model_sums=[{"unit_id": "Service:a", "total": 3,
                     "breakdown": _breakdown(high=1)}],
        risk_total=999,                       # stale: never trusted
    )

    run = resume_run(record, models={"Service:a": _model("high")})

    assert run.next_unit == "Service:b"
    assert run.accumulator.total == 3
    assert run.accumulator.threshold == 12
    assert run.accumulator.basis == "override"
    assert run.accumulator.breakdown == _breakdown(high=1)
    # the exclusions are part of the audit trail a restart must not lose
    assert run.record()["intake_excluded"] == [
        {"unit_id": "Service:c", "reason": "completed"}]


def test_resume_adopts_a_model_committed_before_the_run_record_update():
    """S1 7.5 commit order: the model document commits BEFORE the run-record
    update, so a crash between the two leaves a complete model the record does
    not mention. The resume adopts it - the unit is never re-modelled and its
    sum can never leave a stale total behind."""
    record = _record(intake_position=0, model_sums=[], risk_total=0)

    run = resume_run(record, models={"Service:a": _model("high")})

    assert run.intake_position == 1
    assert run.next_unit == "Service:b"
    assert run.accumulator.total == 3
    assert run.record()["model_sums"] == [
        {"unit_id": "Service:a", "total": 3, "breakdown": _breakdown(high=1),
         "impact_breakdown": _breakdown(low=1)}]
    assert run.record()["risk_total"] == 3


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
    re-ranked, and a later complete model never overwrites the audit trail)."""
    record = _record(
        intake_order=["Service:a", "Service:b", "Service:c"],
        intake_position=0,
        risk_threshold=3,
        threshold_basis="override",
    )

    run = resume_run(record, models={
        "Service:a": _model("high"),              # 3, the inclusive crossing
        "Service:b": _model("high"),
        "Service:c": None,
    })

    assert run.crossing_unit == "Service:a"
    assert run.blocked_unit == "Service:b"
    assert run.intake_position == 1
    assert run.accumulator.total == 3
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
        model_sums=[{"unit_id": "Service:a", "total": 5,
                     "breakdown": _breakdown(high=1, medium=1)}],
        risk_total=5,
    )

    run = resume_run(record, models={"Service:a": _model("high", "medium")})

    assert run.halt is True
    assert run.next_unit is None
    assert run.crossing_unit == "Service:a"
    assert run.blocked_unit == "Service:b"
    assert run.accumulator.total == 5


def test_the_threshold_records_whether_it_is_the_default_or_an_override():
    """S2 7.4: the threshold default is 250; `HUNT_RISK_THRESHOLD` overrides it,
    and the run records the basis (`default` / `override`) so the halt is
    reproducible. A malformed override falls back to the default."""
    assert threshold_config({}) == (250, "default")
    assert threshold_config({"HUNT_RISK_THRESHOLD": "20"}) == (20, "override")
    assert threshold_config({"HUNT_RISK_THRESHOLD": "not-a-number"}) == (
        250, "default")


def test_a_degraded_unit_is_recorded_and_consumes_no_budget():
    """S1 7.7: a degraded unit is recorded with its reason, contributes nothing
    to the accumulator, and the run continues to the next unit."""
    run = ThreatModelRun.start(order=("Service:a", "Service:b"), threshold=12)

    run.degrade_unit("Service:a", "no threat model was written for this unit")

    assert run.intake_position == 1
    assert run.next_unit == "Service:b"
    assert run.accumulator.total == 0
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
        sections=["failure_modes", "loops"],
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
