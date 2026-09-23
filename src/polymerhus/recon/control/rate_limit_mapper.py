"""#238 the PURE rate-limit mapper: planning, classification, evidence gates.

This module is a function of its arguments - no clock, no I/O, no collaborator
(CODING_STANDARD section 3: pure builders apart from impure orchestration).
It encodes the design's central split (spec `docs/design/rate-limit-system-mapping-238-spec.md`,
resolved decision 2):

* the DETERMINISTIC controller owns traffic shape. `next_experiment` decides
  which experiment is next (`STEADY_RATE_LADDER` clipped by the operator
  ceiling), how many requests it costs, and when a phase is finished. The LLM
  has no input here - and no model-facing type carries a traffic number.
* the classification emits HYPOTHESES, never certainty: `behaviour` is always a
  `-like` guess (`fixed-window-like`, `token-bucket-like`, ...) or `unknown`,
  and every conclusion carries the experiment ids that produced it.
* `no_limiter` means "no transition within the tested bounds", never "no
  limiter exists": the harness downgrades it to `inconclusive` unless the whole
  permitted surface was actually exercised.
* the bypass gate (`judge_bypass`) is positive evidence ONLY: four gates, all
  defaulting False, so a missing gate yields `no_bypass`/`inconclusive` and can
  never be coerced into `confirmed` (spec, bypass evidence gate).

`BudgetLedger` is the atomic admission boundary: an experiment consumes requests,
offered duration and concurrency in ONE all-or-nothing reservation, so a
controller cannot spend a budget the operator did not grant.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal, Sequence
from urllib.parse import urlsplit, urlunsplit

from polymerhus.recon.domain.blocking import BlockingSignal
from polymerhus.recon.domain.rate_limit import (
    BudgetUsage,
    BypassFinding,
    BypassGates,
    EnforcementHypothesis,
    ExperimentEvidence,
    ExperimentPhase,
    ExperimentSpec,
    LimiterScope,
    MappedControl,
    MutationSpec,
    RateLimitSafetyBudget,
    RateOutcome,
    RateProfile,
    TrafficPolicy,
)

STEADY_RATE_LADDER: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 20.0)
"""The offered-rate ladder the steady phase walks, clipped by the operator's
`max_rate_per_s` - the operator ceiling is always the binding constraint."""

LADDER_PHASES: tuple[ExperimentPhase, ...] = ("steady", "refine", "boundary", "ramp")
"""The phases whose evidence brackets the rate transition."""

LIMITER_STATUSES: frozenset[int] = frozenset({429, 503})
"""The statuses that ARE a limiter refusal (spec: "typically 429, or an
equivalent documented retry signal")."""

TRANSITION_FLOOR = 0.8
"""A mapped transition yields this fraction of the lower safe bound (spec)."""

BASELINE_DURATION_S = 2.0
STEADY_DURATION_S = 3.0
PROBE_DURATION_S = 1.0
RAMP_DURATION_S = 5.0
REFINE_STEPS = 2
_EPSILON = 1e-6


# --- scope probes ------------------------------------------------------------


@dataclass(frozen=True)
class ScopeProbe:
    """One single-dimension scope comparison.

    The dimension is the ONLY thing the probe changes relative to the canonical
    request, and the experiment id is the one the controller will run it under -
    so classification reads the outcome back without guessing which dimension
    moved (the evidence itself carries no URL).
    """

    experiment_id: str
    dimension: Literal["endpoint", "host", "principal"]


def scope_probe_url(url: str, dimension: str) -> str:
    """The URL for one single-dimension scope probe (pure, deterministic).

    `endpoint` keeps the host and moves the path; `host` keeps the path and
    moves the host. Nothing else changes - not the method, not the headers.
    """
    parts = urlsplit(url)
    if dimension == "endpoint":
        return urlunsplit((parts.scheme, parts.netloc, "/rate-limit-scope", "", ""))
    if dimension == "host":
        return urlunsplit(
            (parts.scheme, f"scope-{parts.netloc}", parts.path, parts.query, "")
        )
    return url


# --- the planner's mutable state ---------------------------------------------


@dataclass
class MappingState:
    """Everything the pure planner needs to choose the next experiment.

    Deliberately data-only: the harness owns the ledger and the transport, so a
    planner step is reproducible from `(state, usage, budget)` alone.
    """

    target_key: str
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    scope_probes: tuple[ScopeProbe, ...] = ()
    evidence: list[ExperimentEvidence] = field(default_factory=list)


# --- budget admission (shared by the planner and the ledger) -----------------


def admits(
    usage: BudgetUsage,
    budget: RateLimitSafetyBudget,
    *,
    requests: int,
    duration_s: float,
    concurrency: int = 1,
    variant: bool = False,
) -> bool:
    """Whether one experiment fits in the REMAINING budget.

    Pure and total: the planner uses it to avoid offering unaffordable work and
    `BudgetLedger.try_reserve` uses the same rule to admit it atomically, so the
    two can never disagree about the operator's ceiling.
    """
    if requests <= 0 or duration_s < 0 or concurrency < 1:
        return False
    if concurrency > budget.max_concurrency:
        return False
    if usage.requests + requests > budget.max_requests:
        return False
    if usage.duration_s + duration_s > budget.max_duration_s + _EPSILON:
        return False
    if variant and usage.variants + 1 > budget.max_bypass_variants:
        return False
    return True


@dataclass
class BudgetLedger:
    """The controller's appetite: an all-or-nothing reservation per experiment.

    A refused admission consumes NOTHING and the executor is never reached, so
    "the experiment did not start" and "the budget did not move" are the same
    fact.
    """

    budget: RateLimitSafetyBudget
    usage: BudgetUsage = field(default_factory=BudgetUsage)

    def try_reserve(
        self,
        *,
        requests: int,
        duration_s: float,
        concurrency: int = 1,
        variant: bool = False,
    ) -> bool:
        if not admits(
            self.usage,
            self.budget,
            requests=requests,
            duration_s=duration_s,
            concurrency=concurrency,
            variant=variant,
        ):
            return False
        self.usage = BudgetUsage(
            requests=self.usage.requests + requests,
            duration_s=round(self.usage.duration_s + duration_s, 6),
            variants=self.usage.variants + (1 if variant else 0),
            experiments=self.usage.experiments + 1,
            max_concurrency=max(self.usage.max_concurrency, concurrency),
        )
        return True


# --- the adaptive state machine ----------------------------------------------


_PHASE_TARGET = {
    "baseline": 1,
    "burst": 1,
    "recovery": 1,
    "boundary": 2,
    "ramp": 1,
    "concurrency": 2,
}


def _ladder(budget: RateLimitSafetyBudget) -> tuple[float, ...]:
    """The ladder clipped by the operator ceiling (never the other way round)."""
    clipped = tuple(
        rate for rate in STEADY_RATE_LADDER if rate <= budget.max_rate_per_s
    )
    return clipped or (float(budget.max_rate_per_s),)


def _measured(state: MappingState, phase: str) -> list[ExperimentEvidence]:
    return [e for e in state.evidence if e.phase == phase and e.outcome == "measured"]


def _refused(evidence: Sequence[ExperimentEvidence]) -> list[ExperimentEvidence]:
    return [e for e in evidence if e.rejection_ratio > _EPSILON]


def _last_good(state: MappingState) -> float | None:
    ladder = [e for e in _measured(state, "steady") if not _refused([e])]
    for phase in ("refine", "boundary"):
        ladder += [e for e in _measured(state, phase) if not _refused([e])]
    if not ladder:
        return None
    return max(e.offered_rate_per_s for e in ladder)


def _first_bad(state: MappingState) -> float | None:
    ladder: list[ExperimentEvidence] = []
    for phase in LADDER_PHASES:
        ladder += _refused(_measured(state, phase))
    if not ladder:
        return None
    return min(e.offered_rate_per_s for e in ladder)


def _refine_rate(state: MappingState, budget: RateLimitSafetyBudget) -> float | None:
    low, high = _last_good(state), _first_bad(state)
    if low is None or high is None or high - low <= _EPSILON:
        return None
    midpoint = round((low + high) / 2.0, 4)
    tested = {
        round(e.offered_rate_per_s, 4) for e in state.evidence if e.offered_rate_per_s
    }
    if midpoint in tested or midpoint > budget.max_rate_per_s:
        return None
    return midpoint


def _next_phase(state: MappingState, budget: RateLimitSafetyBudget) -> str | None:
    counts = Counter(e.phase for e in state.evidence)
    if counts["baseline"] < 1:
        return "baseline"
    ladder = _ladder(budget)
    tested = {round(e.offered_rate_per_s, 4) for e in _measured(state, "steady")}
    refusals = _refused([e for e in state.evidence if e.phase in LADDER_PHASES])
    if not refusals and len(tested) < len(ladder):
        return "steady"
    if (
        refusals
        and counts["refine"] < REFINE_STEPS
        and _refine_rate(state, budget) is not None
    ):
        return "refine"
    for phase in ("burst", "recovery", "boundary", "ramp", "concurrency", "scope"):
        if phase == "concurrency" and budget.max_concurrency < 2:
            # A concurrency probe the budget cannot express is not a probe.
            continue
        if phase == "scope" and not state.scope_probes:
            continue
        target = len(state.scope_probes) if phase == "scope" else _PHASE_TARGET[phase]
        if counts[phase] < target:
            return phase
    return None


def _build_spec(
    phase: str, state: MappingState, budget: RateLimitSafetyBudget
) -> ExperimentSpec | None:
    index = sum(1 for e in state.evidence if e.phase == phase)
    ladder = _ladder(budget)
    top = max(ladder)
    low = _last_good(state) or top
    high = _first_bad(state) or top
    url = state.url
    concurrency = 1
    notes = ""

    if phase == "baseline":
        rate, duration = min(1.0, budget.max_rate_per_s), BASELINE_DURATION_S
        notes = "low-load baseline: does the canonical request succeed at all"
    elif phase == "steady":
        rate, duration = ladder[min(index, len(ladder) - 1)], STEADY_DURATION_S
        notes = "steady-rate ladder step; the first refusal brackets the transition"
    elif phase == "refine":
        refined = _refine_rate(state, budget)
        if refined is None:
            return None
        rate, duration = refined, STEADY_DURATION_S
        notes = "binary refinement of the transition interval"
    elif phase == "burst":
        rate, duration = high, PROBE_DURATION_S
        notes = "burst-capacity probe at the transition rate"
    elif phase == "recovery":
        rate, duration = min(1.0, budget.max_rate_per_s), PROBE_DURATION_S
        notes = "cooldown/recovery probe: is a low-rate request accepted again"
    elif phase == "boundary":
        rate, duration = (low, high)[min(index, 1)], PROBE_DURATION_S
        notes = "boundary/window probe one step either side of the transition"
    elif phase == "ramp":
        rate, duration = high, RAMP_DURATION_S
        notes = "sustained-load probe: do refusals start mid-stream (window) or stay spread"
    elif phase == "concurrency":
        rate, duration = low, STEADY_DURATION_S
        concurrency = (1, budget.max_concurrency)[min(index, 1)]
        notes = "concurrency probe at a CONSTANT offered rate"
    elif phase == "scope":
        probe = state.scope_probes[index]
        rate, duration = high, STEADY_DURATION_S
        url = scope_probe_url(state.url, probe.dimension)
        notes = f"scope probe varying exactly one dimension: {probe.dimension}"
        return ExperimentSpec(
            experiment_id=probe.experiment_id,
            phase="scope",
            url=url,
            method=state.method,
            rate_per_s=rate,
            duration_s=duration,
            requests=max(1, math.ceil(rate * duration)),
            concurrency=concurrency,
            headers=dict(state.headers),
            notes=notes,
        )
    else:  # pragma: no cover - the phase list above is exhaustive
        return None

    return ExperimentSpec(
        experiment_id=f"{phase}-{index}",
        phase=phase,  # type: ignore[arg-type]
        url=url,
        method=state.method,
        rate_per_s=rate,
        duration_s=duration,
        requests=max(1, math.ceil(rate * duration)),
        concurrency=concurrency,
        headers=dict(state.headers),
        notes=notes,
    )


def next_experiment(
    state: MappingState, usage: BudgetUsage, budget: RateLimitSafetyBudget
) -> ExperimentSpec | None:
    """The next admitted experiment, or `None` when the mapping is finished.

    `None` means exactly one of: every phase completed, or the remaining budget
    cannot support a meaningful step. The caller distinguishes them from the
    evidence it collected - and classifies a truncated ladder as
    `inconclusive`, never as `no_limiter`.
    """
    phase = _next_phase(state, budget)
    if phase is None:
        return None
    spec = _build_spec(phase, state, budget)
    if spec is None:
        return None
    if not admits(
        usage,
        budget,
        requests=spec.requests,
        duration_s=spec.duration_s,
        concurrency=spec.concurrency,
    ):
        return None
    return spec


# --- classification ----------------------------------------------------------


def _baseline_p95(measured: Sequence[ExperimentEvidence]) -> float | None:
    values = [e.latency_p95_ms for e in measured if e.latency_p95_ms]
    return min(values) if values else None


def _fingerprint_of(evidence: Sequence[ExperimentEvidence]) -> list[str]:
    """The observed refusal fingerprint: statuses, limiter headers, body hashes."""
    fingerprint: set[str] = set()
    for item in evidence:
        for status in item.status_counts:
            if status.isdigit() and int(status) in LIMITER_STATUSES:
                fingerprint.add(f"status:{status}")
        fingerprint.update(f"header:{name}" for name in item.header_fingerprint)
        fingerprint.update(f"body:{digest}" for digest in item.body_fingerprint)
    return sorted(fingerprint)


def _concurrency_limited(measured: Sequence[ExperimentEvidence]) -> bool:
    """A refusal that follows WORKERS rather than the offered rate."""
    probes = [e for e in measured if e.phase == "concurrency"]
    refused = [e for e in probes if e.rejection_ratio > _EPSILON]
    accepted = [e for e in probes if e.rejection_ratio <= _EPSILON]
    if not refused or not accepted:
        return False
    return any(
        bad.concurrent_workers > good.concurrent_workers
        and abs(bad.offered_rate_per_s - good.offered_rate_per_s) <= _EPSILON
        for bad in refused
        for good in accepted
    )


def _behaviour(
    measured: Sequence[ExperimentEvidence],
    accepted: Sequence[ExperimentEvidence],
    refused: Sequence[ExperimentEvidence],
) -> EnforcementHypothesis:
    """The behavioural HYPOTHESIS the evidence supports (never certainty)."""
    if _concurrency_limited(measured):
        return "concurrency-limited"
    baseline = _baseline_p95(measured)
    if not refused:
        peak = max((e.latency_p95_ms or 0.0) for e in measured)
        if baseline and peak >= 3 * baseline:
            return "backend-saturation"
        return "unknown"
    first_bad = min(refused, key=lambda e: e.offered_rate_per_s)
    ratio = first_bad.rejection_ratio
    burst = max((e.burst_accepted or 0) for e in measured)
    queueing = bool(baseline) and (first_bad.latency_p95_ms or 0.0) >= 2 * baseline
    if burst >= 2 and 0.0 < ratio < 0.9:
        return "token-bucket-like"
    if burst >= 2 and ratio >= 0.9 and queueing:
        return "leaky-bucket-like"
    if ratio >= 0.9:
        return "fixed-window-like"
    if ratio > 0.0:
        return "sliding-window-like"
    return "unknown"


def _recovery_seconds(measured: Sequence[ExperimentEvidence]) -> float | None:
    probes = [
        e for e in measured if e.phase == "recovery" and e.rejection_ratio <= _EPSILON
    ]
    refusals = [e for e in measured if e.rejection_ratio > _EPSILON]
    if not probes or not refusals:
        return None
    probe = max(probes, key=lambda e: e.measured_at)
    last_refusal = max(refusals, key=lambda e: e.measured_at)
    delta = (probe.measured_at - last_refusal.measured_at).total_seconds()
    return delta if delta > 0 else None


def _window_sensitivity(measured: Sequence[ExperimentEvidence]) -> bool | None:
    probes = sorted(
        (e for e in measured if e.phase == "boundary"),
        key=lambda e: e.offered_rate_per_s,
    )
    if len(probes) < 2:
        return None
    return (probes[0].rejection_ratio > _EPSILON) != (
        probes[-1].rejection_ratio > _EPSILON
    )


def classify_mapping(evidence: Sequence[ExperimentEvidence]) -> MappedControl:
    """Turn measured evidence into ranges and HYPOTHESES (never certainty).

    The classification is budget-free: it reports what the evidence supports.
    The harness downgrades a `no_limiter` it could not exhaust, derives the
    enforceable `TrafficPolicy`, and merges the single-dimension scope result.
    """
    experiment_ids = [e.experiment_id for e in evidence]
    measured = [e for e in evidence if e.outcome == "measured"]
    if not measured:
        outcome: RateOutcome = (
            "failed" if any(e.outcome == "failed" for e in evidence) else "inconclusive"
        )
        return MappedControl(outcome=outcome, experiment_ids=experiment_ids)

    ladder = sorted(
        (e for e in measured if e.phase in LADDER_PHASES),
        key=lambda e: e.offered_rate_per_s,
    )
    refused = _refused(ladder)
    accepted = [e for e in ladder if e.rejection_ratio <= _EPSILON]
    concurrency_limited = _concurrency_limited(measured)
    tested_max = max((e.offered_rate_per_s for e in measured), default=None)
    # The fingerprint is what the target actually SAID no with - including a
    # refusal that only appeared under higher concurrency (it is still the
    # limiter's fingerprint, and the model must be able to see it).
    fingerprint = _fingerprint_of(_refused(measured))
    signals = [BlockingSignal.RATE_LIMITED] if fingerprint else []
    distinct_rates = {round(e.offered_rate_per_s, 4) for e in ladder}

    inconsistent = (
        bool(accepted)
        and bool(refused)
        and max(e.offered_rate_per_s for e in accepted)
        >= min(e.offered_rate_per_s for e in refused)
    )

    if inconsistent:
        outcome = "inconclusive"
    elif refused or concurrency_limited:
        outcome = "mapped"
    elif len(distinct_rates) >= 2:
        outcome = "no_limiter"
    else:
        outcome = "inconclusive"

    threshold_low: float | None = None
    threshold_high: float | None = None
    if not inconsistent:
        if accepted:
            threshold_low = max(e.offered_rate_per_s for e in accepted)
        if refused:
            threshold_high = min(e.offered_rate_per_s for e in refused)
        elif concurrency_limited:
            # The refusal follows the worker count, so the offered-rate bracket
            # closes on itself: the rate is not the axis that moved.
            threshold_high = threshold_low

    behaviour = "unknown" if inconsistent else _behaviour(measured, accepted, refused)
    burst_capacity = None
    bursts = [e.burst_accepted for e in measured if e.burst_accepted is not None]
    if bursts:
        burst_capacity = max(bursts)

    confidence = {
        "mapped": 0.6,
        "no_limiter": 0.4,
        "inconclusive": 0.2,
        "failed": 0.0,
    }[outcome]
    if behaviour == "concurrency-limited":
        confidence = 0.7
    elif behaviour == "backend-saturation":
        confidence = 0.5
    if inconsistent:
        confidence = 0.2
    elif outcome == "mapped" and any(e.phase == "refine" for e in measured):
        confidence = 0.8

    return MappedControl(
        outcome=outcome,
        tested_max_rate_per_s=tested_max,
        threshold_low_per_s=threshold_low,
        threshold_high_per_s=threshold_high,
        burst_capacity=burst_capacity,
        recovery_s=_recovery_seconds(measured),
        window_sensitivity=_window_sensitivity(measured),
        scope="unknown",  # the harness merges the single-dimension scope result
        behaviour=behaviour,
        fingerprint=fingerprint,
        confidence=confidence,
        experiment_ids=experiment_ids,
        signals=signals,
        traffic_policy=None,
    )


def derive_scope(
    evidence: Sequence[ExperimentEvidence], probes: Sequence[ScopeProbe]
) -> LimiterScope:
    """The limiter's effective key, from single-dimension probes.

    The canonical request must currently be refused (otherwise there is no key
    to find). The dimension whose change REMOVED the refusal is the key; if no
    single change removes it, the limiter follows the whole target.
    """
    if not probes:
        return "unknown"
    by_id = {e.experiment_id: e for e in evidence}
    canonical_refused = any(
        e.rejection_ratio > _EPSILON for e in evidence if e.phase in LADDER_PHASES
    )
    if not canonical_refused:
        return "unknown"
    for probe in probes:
        observed = by_id.get(probe.experiment_id)
        if observed is None or observed.outcome != "measured":
            continue
        if observed.rejection_ratio <= _EPSILON:
            return probe.dimension
    return "target"


def derive_policy(
    control: MappedControl,
    budget: RateLimitSafetyBudget,
    *,
    target_key: str,
    host_patterns: Sequence[str],
) -> TrafficPolicy:
    """The mechanically derived, enforceable traffic shape.

    The policy is CONSERVATIVE by construction: 80% of the lower safe bound for
    a mapped transition, the highest rate actually tested for `no_limiter`
    (never infinity), and Task 1's one-request-per-second fallback otherwise.
    """
    if control.traffic_policy is not None:
        return control.traffic_policy
    if control.outcome == "mapped":
        floor = control.threshold_low_per_s or control.tested_max_rate_per_s or 1.0
        rate = min(max(TRANSITION_FLOOR * floor, 1.0), budget.max_rate_per_s)
        source = "measured-transition"
    elif control.outcome == "no_limiter":
        rate = min(max(control.tested_max_rate_per_s or 1.0, 1.0), budget.max_rate_per_s)
        source = "measured-no-limiter"
    else:
        # Failed/inconclusive: Task 1's loud conservative fallback.
        return RateProfile.conservative(
            target_key,
            list(host_patterns),
            budget,
            f"rate mapping {control.outcome}",
            outcome=control.outcome,
        ).traffic_policy

    burst = max(1, min(int(control.burst_capacity or 1), max(1, int(math.floor(rate)))))
    return TrafficPolicy(
        target_key=target_key,
        host_patterns=list(host_patterns),
        rate_per_s=rate,
        burst=burst,
        max_concurrency=1,
        min_delay_ms=1000.0 / rate,
        source=source,
    )


# --- the bypass evidence gate -------------------------------------------------


def _reproduces(variant: ExperimentEvidence, repeat: ExperimentEvidence) -> bool:
    if variant.rejection_ratio > _EPSILON or repeat.rejection_ratio > _EPSILON:
        return False
    if not variant.body_fingerprint:
        return False  # no semantic evidence to reproduce
    return list(variant.body_fingerprint) == list(repeat.body_fingerprint)


def judge_bypass(
    canonical: ExperimentEvidence,
    variant: ExperimentEvidence,
    repeat: ExperimentEvidence,
    *,
    mutation: MutationSpec | None = None,
) -> BypassFinding:
    """Judge one variant against the four evidence gates (spec, bypass gate).

    1. `canonical` currently triggers the limiter (a refusal fingerprint exists);
    2. `variant` materially changes that state (accepted where the canonical was
       refused);
    3. application semantics remain equivalent - the variant reached the
       application (an accepted body fingerprint, distinct from the refusal
       body);
    4. the differential repeats independently (`repeat` matches `variant`).

    Gate 3 is the observable proxy available to a PURE function of three
    experiments. A missing or unstable fingerprint yields `inconclusive` -
    never `confirmed`.

    `mutation` names the variant that was run. The three evidence arguments do
    not carry it (the domain evidence holds aggregates only), so the harness
    passes it explicitly; without it the finding stays evidence-only and is
    marked unattributed rather than invented.
    """
    canonical_rejected = (
        canonical.outcome == "measured" and canonical.rejection_ratio > _EPSILON
    )
    variant_accepted = (
        variant.outcome == "measured" and variant.rejection_ratio <= _EPSILON
    )
    material = (
        canonical_rejected
        and variant_accepted
        and variant.rejection_ratio < canonical.rejection_ratio
    )
    refusal_bodies = set(canonical.body_fingerprint)
    semantic = (
        variant_accepted
        and bool(variant.body_fingerprint)
        and not (set(variant.body_fingerprint) & refusal_bodies)
    )
    reproduced = variant_accepted and _reproduces(variant, repeat)

    gates = BypassGates(
        canonical_rejected=canonical_rejected,
        material_state_change=material,
        semantic_equivalence=semantic,
        reproduced=reproduced,
    )
    if gates.all_passed:
        outcome = "confirmed"
    elif canonical_rejected and variant.outcome == "measured" and not material:
        # The limiter behaved exactly as it did for the canonical request.
        outcome = "no_bypass"
    else:
        outcome = "inconclusive"

    variant_spec = mutation or MutationSpec(
        variant_id="unattributed",
        family="pacing",
        description="unattributed variant (the caller passed no mutation=)",
    )
    return BypassFinding(
        variant=variant_spec,
        outcome=outcome,
        gates=gates,
        canonical_experiment_id=canonical.experiment_id,
        variant_experiment_ids=[variant.experiment_id, repeat.experiment_id],
        rationale=(
            f"canonical={canonical.experiment_id} "
            f"variant={variant.experiment_id} repeat={repeat.experiment_id}"
        ),
    )


__all__ = [
    "BASELINE_DURATION_S",
    "BudgetLedger",
    "LADDER_PHASES",
    "LIMITER_STATUSES",
    "MappingState",
    "PROBE_DURATION_S",
    "RAMP_DURATION_S",
    "REFINE_STEPS",
    "STEADY_DURATION_S",
    "STEADY_RATE_LADDER",
    "TRANSITION_FLOOR",
    "ScopeProbe",
    "admits",
    "classify_mapping",
    "derive_policy",
    "derive_scope",
    "judge_bypass",
    "next_experiment",
    "scope_probe_url",
]
