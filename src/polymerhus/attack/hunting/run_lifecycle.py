"""The run lifecycle: the risk accumulator, the halt, the run record, the resume
rules and the commit order (S1 7.4-7.5, S2 7.4 and 9.2-9.4; T3 #376).

The intake freeze and the ordering live in `unit_intake`; THIS module owns what
the run does with the frozen order:

- the **symbolic risk accumulator** (S2 7.4): the unit total is the sum of the
  loop likelihood weights, the run total is their running sum, and the halt
  comparison is INCLUSIVE (`run_total >= threshold`);
- the **halt** (S1 7.4, ordering-halt ADR): the crossing unit completes and is
  dispatched, the NEXT unit in the intake order is never modelled, and the
  blocked unit is recorded. The halt never re-sorts or re-ranks the intake;
- the **run record** (S2 9.2): the fixed keys the run row's `stats` carries, so
  the halt is auditable after the process is gone;
- the **resume rules** (S1 7.5): a stopped run re-enters at `intake_position`,
  never re-models a unit whose model is complete, and RECOMPUTES `risk_total`
  from `model_sums` and the completed models - so a crash between the model
  document commit and the run-record write cannot leave a stale total;
- the **commit order**: the model document commits before the run-record update
  (the driver writes the record only after the pass returned).

The run record is plain JSON-safe data: the pg `stats` JSONB column is its
durable home.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .threat_model import DEFAULT_RISK_THRESHOLD, RISK_WEIGHTS, Likelihood
from .unit_intake import IntakeExclusion

logger = logging.getLogger(__name__)

# The five likelihood levels in ascending weight order: the breakdown's key
# order, so a recorded breakdown is stable and readable.
RISK_LEVELS: tuple[str, ...] = tuple(level.value for level in Likelihood)

# The threshold's override variable and its recorded basis (S2 7.4).
RISK_THRESHOLD_ENV = "HUNT_RISK_THRESHOLD"
THRESHOLD_BASIS_DEFAULT = "default"
THRESHOLD_BASIS_OVERRIDE = "override"

# The run record's fixed key set (S1 7.4, S2 9.2): the run bootstrap writes the
# intake order and the exclusions before the first unit, the accumulator updates
# after each COMPLETED write, and the crossing and blocked units are written when
# the halt fires. The record IS the run row's `stats` JSON, so the keys are
# stable across a restart.
RUN_RECORD_KEYS: tuple[str, ...] = (
    "intake_order",
    "intake_position",
    "intake_excluded",
    "risk_threshold",
    "threshold_basis",
    "risk_weights",
    "risk_total",
    "risk_breakdown",
    "model_sums",
    "crossing_unit",
    "blocked_unit",
    "halt",
    "degraded_units",
    "trajectory",
)


def risk_weights() -> dict[str, int]:
    """The recorded weight table (S2 7.1): the ONE likelihood-weight constant,
    re-keyed by the enum's string value for the run record's JSON."""
    return {level.value: RISK_WEIGHTS[level] for level in Likelihood}


def threshold_config(env: Mapping[str, str] | None = None) -> tuple[int, str]:
    """The effective risk threshold and its basis (S2 7.4).

    The default is a documented starting constant, not a calibrated value: the
    calibration replays recorded runs in intake order against the fixed weights
    (ordering-halt ADR consequences). `HUNT_RISK_THRESHOLD` overrides it; a
    malformed override warns and falls back to the default, so a typo can never
    silently disable the halt.
    """
    source = os.environ if env is None else env
    raw = (source.get(RISK_THRESHOLD_ENV) or "").strip()
    if not raw:
        return DEFAULT_RISK_THRESHOLD, THRESHOLD_BASIS_DEFAULT
    try:
        threshold = int(raw)
    except ValueError:
        logger.warning(
            "run lifecycle: %s=%r is not an integer; using the default "
            "threshold %d", RISK_THRESHOLD_ENV, raw, DEFAULT_RISK_THRESHOLD,
        )
        return DEFAULT_RISK_THRESHOLD, THRESHOLD_BASIS_DEFAULT
    return threshold, THRESHOLD_BASIS_OVERRIDE


@dataclass(frozen=True)
class ModelSum:
    """One modelled unit's contribution (S2 9.2 `model_sums` entry)."""

    unit_id: str
    total: int
    breakdown: dict[str, int]

    def record(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "total": self.total,
            "breakdown": dict(self.breakdown),
        }


def _empty_breakdown() -> dict[str, int]:
    return {level: 0 for level in RISK_LEVELS}


def model_sum(unit_id: str, model: Mapping[str, Any] | None) -> ModelSum:
    """The harness-owned sum of ONE persisted model (S2 7.3).

    The total and the breakdown come from the model's loops by the fixed weight
    table; the store computes the same profile at the COMPLETED write and the
    completion checker regression-checks it, so the recorded sum always restates
    the loops the model carries. A model with no loops (a zero-loop unit, or a
    partial document) sums to zero - it consumes no budget.
    """
    breakdown = _empty_breakdown()
    total = 0
    for loop in (model or {}).get("loops") or []:
        likelihood = str((loop or {}).get("likelihood") or "")
        if likelihood not in RISK_LEVELS:
            logger.warning(
                "run lifecycle: model %s carries an unknown loop likelihood %r; "
                "the loop contributes no budget", unit_id, likelihood,
            )
            continue
        breakdown[likelihood] += 1
        total += RISK_WEIGHTS[Likelihood(likelihood)]
    return ModelSum(unit_id=unit_id, total=total, breakdown=breakdown)


@dataclass
class RiskAccumulator:
    """The symbolic run accumulator (S1 7.4, S2 7.4).

    `total` is the running sum of the completed units' totals, `breakdown` the
    summed per-level loop counts, and `model_sums` the per-unit entries the run
    record carries. `crossing_unit`, `blocked_unit` and `halt` are the halt's
    audit trail: the crossing unit completed (and is dispatched), the blocked
    unit is the next unit in the intake order that was never modelled.
    """

    threshold: int = DEFAULT_RISK_THRESHOLD
    basis: str = THRESHOLD_BASIS_DEFAULT
    weights: dict[str, int] = field(default_factory=risk_weights)
    total: int = 0
    breakdown: dict[str, int] = field(default_factory=_empty_breakdown)
    model_sums: list[ModelSum] = field(default_factory=list)
    crossing_unit: str | None = None
    blocked_unit: str | None = None
    halt: bool = False

    def add(self, entry: ModelSum) -> None:
        """Accumulate one modelled unit. The total is symbolic: the weights are
        fixed, so the same loops always yield the same sum."""
        self.total += entry.total
        for level, count in entry.breakdown.items():
            self.breakdown[level] = self.breakdown.get(level, 0) + count
        self.model_sums.append(entry)

    @property
    def crossed(self) -> bool:
        """The INCLUSIVE halt comparison (S1 7.4 / S2 7.4): `>=`."""
        return self.total >= self.threshold

    def record(self) -> dict[str, Any]:
        """The accumulator's run-record keys (S2 9.2)."""
        return {
            "risk_threshold": self.threshold,
            "threshold_basis": self.basis,
            "risk_weights": dict(self.weights),
            "risk_total": self.total,
            "risk_breakdown": dict(self.breakdown),
            "model_sums": [entry.record() for entry in self.model_sums],
            "crossing_unit": self.crossing_unit,
            "blocked_unit": self.blocked_unit,
            "halt": self.halt,
        }


@dataclass
class ThreatModelRun:
    """One modeller run's frozen intake and its symbolic progress (S1 7.4).

    The run dequeues `intake_order[intake_position]`, models it, and records the
    outcome. The order is never re-sorted (ordering-halt ADR 2) and the halt
    never re-ranks it: the position advances monotonically, and a halt only
    stops the dequeue.
    """

    intake_order: tuple[str, ...]
    accumulator: RiskAccumulator = field(default_factory=RiskAccumulator)
    intake_excluded: tuple[IntakeExclusion, ...] = ()
    intake_position: int = 0
    degraded_units: list[dict[str, str]] = field(default_factory=list)
    trajectory: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        order: Sequence[str],
        *,
        excluded: Sequence[IntakeExclusion] = (),
        threshold: int = DEFAULT_RISK_THRESHOLD,
        basis: str = THRESHOLD_BASIS_DEFAULT,
    ) -> "ThreatModelRun":
        """A fresh run over the frozen intake order."""
        return cls(
            intake_order=tuple(order),
            accumulator=RiskAccumulator(threshold=threshold, basis=basis),
            intake_excluded=tuple(excluded),
        )

    @property
    def next_unit(self) -> str | None:
        """The unit to model next, or None when the intake is exhausted or the
        run has halted (a halted run dequeues nothing)."""
        if self.accumulator.halt:
            return None
        if self.intake_position >= len(self.intake_order):
            return None
        return self.intake_order[self.intake_position]

    @property
    def crossing_unit(self) -> str | None:
        return self.accumulator.crossing_unit

    @property
    def blocked_unit(self) -> str | None:
        return self.accumulator.blocked_unit

    @property
    def halt(self) -> bool:
        return self.accumulator.halt

    def complete_unit(self, unit_id: str, entry: ModelSum) -> None:
        """Record one COMPLETED, valid model: accumulate it, advance the intake
        position, and evaluate the halt (S1 7.4: the check runs immediately
        after the COMPLETED write, before the next unit is dequeued)."""
        self.accumulator.add(entry)
        self.intake_position += 1
        if self.accumulator.crossed and not self.accumulator.halt:
            self.accumulator.crossing_unit = unit_id
            self.accumulator.blocked_unit = (
                self.intake_order[self.intake_position]
                if self.intake_position < len(self.intake_order) else None
            )
            self.accumulator.halt = True

    def degrade_unit(self, unit_id: str, reason: str) -> None:
        """Record one degraded unit (S1 7.7): the reason is kept, the unit
        consumes no budget, and the run continues to the next unit."""
        self.degraded_units.append({"unit_id": unit_id, "reason": reason})
        self.intake_position += 1

    def keep_trajectory(self, entries: Sequence[Mapping[str, Any]]) -> None:
        """Append the unit's state-and-gate entries to the run's trajectory."""
        self.trajectory.extend(dict(entry) for entry in entries)

    def record(self) -> dict[str, Any]:
        """The run record: every fixed key (S2 9.2). This is the dict the run
        row's `stats` carries."""
        return {
            "intake_order": list(self.intake_order),
            "intake_position": self.intake_position,
            "intake_excluded": [
                {"unit_id": entry.unit_id, "reason": entry.reason}
                for entry in self.intake_excluded
            ],
            **self.accumulator.record(),
            "degraded_units": [dict(entry) for entry in self.degraded_units],
            "trajectory": [dict(entry) for entry in self.trajectory],
        }


def is_complete_model(model: Mapping[str, Any] | None) -> bool:
    """The ONE consumability predicate the resume re-reads (S2 5.7, 10.5): the
    model is COMPLETED and its completion validation is valid."""
    if not model:
        return False
    validation = model.get("validation")
    return (
        model.get("state") == "COMPLETED"
        and isinstance(validation, Mapping)
        and validation.get("valid") is True
    )


def trajectory_entry(unit_id: str, trail_entry: Any) -> dict[str, Any]:
    """One run-record trajectory entry (S1 6.1, S2 9.2).

    `signal` is the gate the model asked for, `from_state`/`to_state` the
    transition, and `outcome` what the harness recorded: `gate` for a forward
    write (with the states it skipped), `lower_gate` for a write behind the
    tracked state (content only - the state does not move), `seeded` for the
    state a resumed pass started from. The trajectory lives in the run record,
    not in the model document (S2 9.2).
    """
    kind = str(getattr(trail_entry, "kind", ""))
    state = str(getattr(trail_entry, "state", ""))
    previous = getattr(trail_entry, "previous_state", None)
    tracked = getattr(trail_entry, "tracked", None)
    at = getattr(trail_entry, "at", None)
    return {
        "unit_id": unit_id,
        "signal": state,
        "from_state": previous if kind == "gate" else tracked,
        "to_state": state if kind == "gate" else tracked,
        "outcome": kind,
        "skipped": [str(skipped) for skipped in getattr(trail_entry, "skipped", ())],
        "at": at.isoformat() if hasattr(at, "isoformat") else (at or ""),
    }


def resume_run(
    record: Mapping[str, Any],
    *,
    models: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> ThreatModelRun:
    """A resumed run from its persisted record (S1 7.5).

    - The intake order is READ, never re-frozen or re-sorted (ordering-halt ADR
      2): the recorded order is the run's order.
    - `risk_total` is RECOMPUTED from `model_sums` and the completed models on
      disk. The model document commits before the run-record update, so a crash
      between the two leaves a complete model the record does not mention: the
      resume ADOPTS every complete model at or after `intake_position`, which is
      why a stale total can never survive a restart.
    - A halted record resumes as halted: the run dispatches its produced loops
      and models nothing more.
    """
    order = tuple(str(unit) for unit in record.get("intake_order") or ())
    accumulator = RiskAccumulator(
        threshold=int(record.get("risk_threshold") or DEFAULT_RISK_THRESHOLD),
        basis=str(record.get("threshold_basis") or THRESHOLD_BASIS_DEFAULT),
        weights=dict(record.get("risk_weights") or risk_weights()),
    )
    run = ThreatModelRun(
        intake_order=order,
        accumulator=accumulator,
        intake_excluded=tuple(
            IntakeExclusion(str(entry.get("unit_id")), str(entry.get("reason") or ""))
            for entry in record.get("intake_excluded") or ()
            if entry.get("unit_id")
        ),
        intake_position=min(int(record.get("intake_position") or 0), len(order)),
        degraded_units=_dedupe_degraded(record.get("degraded_units") or ()),
        trajectory=[dict(entry) for entry in record.get("trajectory") or []],
    )
    # The recorded model sums, re-accumulated through the ONE accumulator entry
    # point (the same weights the live run uses): the running total is the sum of
    # the entries, never the recorded `risk_total`.
    recorded: dict[str, ModelSum] = {}
    for entry in record.get("model_sums") or []:
        unit_id = entry.get("unit_id")
        if not unit_id:
            continue
        recorded[str(unit_id)] = ModelSum(
            unit_id=str(unit_id),
            total=int(entry.get("total") or 0),
            breakdown={level: int((entry.get("breakdown") or {}).get(level, 0))
                       for level in RISK_LEVELS},
        )
    for entry in recorded.values():
        run.accumulator.add(entry)
    run.accumulator.crossing_unit = record.get("crossing_unit")
    run.accumulator.blocked_unit = record.get("blocked_unit")
    run.accumulator.halt = bool(record.get("halt"))

    # Adopt every complete model from the recorded position forward: the units
    # already modelled before the crash were neither re-modelled nor lost. A
    # HALTED record adopts nothing (a halted run resumes dispatch only, S1 7.5),
    # and the adoption itself replays the halt check: the FIRST crossing is final
    # - the crossing unit is the last one adopted and the position stops there.
    if not run.accumulator.halt:
        for unit_id in order[run.intake_position:]:
            model = (models or {}).get(unit_id)
            if not is_complete_model(model):
                break
            if unit_id not in recorded:
                entry = model_sum(unit_id, model)
                recorded[unit_id] = entry
                run.accumulator.add(entry)
            run.intake_position += 1
            if run.accumulator.crossed:
                run.accumulator.crossing_unit = unit_id
                run.accumulator.blocked_unit = (
                    order[run.intake_position]
                    if run.intake_position < len(order) else None
                )
                run.accumulator.halt = True
                break
    return run


def _dedupe_degraded(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The degraded-unit entries, one per unit id (S2 9.2).

    A crash between a unit's degradation and the run-record write leaves the
    record behind the position, so a resume can degrade the same unit again. The
    record keeps ONE entry per unit - the latest reason wins - so a restart never
    multiplies a unit's finding."""
    deduped: dict[str, dict[str, str]] = {}
    for entry in entries:
        unit_id = str(entry.get("unit_id") or "")
        if not unit_id:
            continue
        deduped[unit_id] = {
            "unit_id": unit_id, "reason": str(entry.get("reason") or ""),
        }
    return list(deduped.values())


__all__ = [
    "ModelSum",
    "RISK_LEVELS",
    "RISK_THRESHOLD_ENV",
    "RUN_RECORD_KEYS",
    "RiskAccumulator",
    "THRESHOLD_BASIS_DEFAULT",
    "THRESHOLD_BASIS_OVERRIDE",
    "ThreatModelRun",
    "is_complete_model",
    "model_sum",
    "resume_run",
    "risk_weights",
    "threshold_config",
    "trajectory_entry",
]
