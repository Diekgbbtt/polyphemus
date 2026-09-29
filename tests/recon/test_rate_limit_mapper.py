"""#238 Task 4 - the pure mapper: planning, classification, evidence gates.

Everything in this module is a function of its arguments: no clock, no I/O, no
collaborator. The tests therefore pin BEHAVIOUR (ranges, hypotheses, admitted
work) rather than implementation, and they deliberately never assert that a
limiter's implementation is "known" - only that the evidence supports a
hypothesis, a bound, or an honest `unknown`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from polymerhus.recon.domain.blocking import BlockingSignal
from polymerhus.recon.domain.rate_limit import (
    BudgetUsage,
    ExperimentEvidence,
    MutationSpec,
    RateLimitSafetyBudget,
)
from polymerhus.recon.control.rate_limit_mapper import (
    STEADY_RATE_LADDER,
    BudgetLedger,
    MappingState,
    ScopeProbe,
    classify_mapping,
    derive_policy,
    derive_scope,
    judge_bypass,
    next_experiment,
)

_T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _ev(
    experiment_id: str,
    phase: str,
    offered_rate: float,
    *,
    requests: int = 10,
    rejected: int = 0,
    p50: float = 10.0,
    p95: float = 20.0,
    burst_accepted: int | None = None,
    workers: int = 1,
    codes: dict[str, int] | None = None,
    headers: tuple[str, ...] = (),
    bodies: tuple[str, ...] = (),
    outcome: str = "measured",
    measured_at: datetime | None = None,
    error: str | None = None,
    transport_errors: int = 0,
) -> ExperimentEvidence:
    if codes is None:
        codes = {"429": rejected, "200": requests - rejected} if rejected else {"200": requests}
    codes = {k: v for k, v in codes.items() if v}
    return ExperimentEvidence(
        experiment_id=experiment_id,
        phase=phase,
        offered_rate_per_s=offered_rate,
        requests=requests,
        concurrent_workers=workers,
        duration_s=3.0,
        status_counts=codes,
        rejection_ratio=(rejected / requests) if requests else 0.0,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        burst_accepted=burst_accepted,
        header_fingerprint=list(headers),
        body_fingerprint=list(bodies),
        artifact_ref=f"rate-artifact/v1:proj-1/run-1/{experiment_id}",
        manifest_sha256="a" * 64,
        measured_at=measured_at or _T0,
        outcome=outcome,
        error=error,
        transport_errors=transport_errors,
    )


# --- classification ----------------------------------------------------------


def test_no_transition_through_the_tested_maximum_is_no_limiter():
    evidence = [
        _ev("baseline-0", "baseline", 1.0, requests=2),
        _ev("steady-0", "steady", 1.0),
        _ev("steady-1", "steady", 2.0),
        _ev("steady-2", "steady", 5.0),
        _ev("steady-3", "steady", 10.0),
        _ev("steady-4", "steady", 20.0),
    ]

    control = classify_mapping(evidence)

    assert control.outcome == "no_limiter"
    assert control.tested_max_rate_per_s == 20.0
    assert control.behaviour == "unknown"  # never a claim of absence
    assert control.signals == []  # no refusal fingerprint was observed
    assert set(control.experiment_ids) >= {"steady-0", "steady-4"}


def test_partial_transport_never_becomes_an_accepted_bound():
    """Two probes that each lost some hits at the transport layer answered no
    clean evidence that the target has no limiter - the outcome is inconclusive,
    not `no_limiter` (#238 B4)."""
    control = classify_mapping(
        [
            _ev("steady-0", "steady", 1.0, transport_errors=2, codes={"200": 8}),
            _ev("steady-1", "steady", 2.0, transport_errors=1, codes={"200": 9}),
        ]
    )

    assert control.outcome == "inconclusive"


def test_real_refusal_uses_only_the_clean_lower_bound():
    """A real refusal plus one clean lower probe and one partially-transported
    probe maps only the CLEAN lower bound - the degraded probe is not usable
    evidence for an accepted rate."""
    control = classify_mapping(
        [
            _ev("steady-0", "steady", 1.0, codes={"200": 10}),
            _ev("steady-1", "steady", 2.0, transport_errors=1, codes={"200": 9}),
            _ev("steady-2", "steady", 5.0, rejected=5, codes={"429": 5}),
        ]
    )

    assert control.outcome == "mapped"
    assert control.threshold_low_per_s == 1.0
    assert control.threshold_high_per_s == 5.0


def test_sharp_refusal_plus_cooldown_is_a_window_hypothesis():
    later = _T0 + timedelta(seconds=30)
    evidence = [
        _ev("baseline-0", "baseline", 1.0, requests=2),
        _ev("steady-0", "steady", 1.0),
        _ev("steady-1", "steady", 2.0),
        _ev("steady-2", "steady", 5.0),
        _ev("steady-3", "steady", 10.0, rejected=30, requests=30,
            codes={"429": 30}, headers=("retry-after",), bodies=("deadbeef",)),
        _ev("refine-0", "refine", 7.5),
        _ev("refine-1", "refine", 8.75, rejected=28, requests=28, codes={"429": 28}),
        _ev("burst-0", "burst", 8.75, requests=8, burst_accepted=3),
        _ev("recovery-0", "recovery", 1.0, requests=1, measured_at=later),
    ]

    control = classify_mapping(evidence)

    assert control.outcome == "mapped"
    assert control.threshold_low_per_s == 7.5
    assert control.threshold_high_per_s == 8.75
    assert control.behaviour == "fixed-window-like"
    assert control.burst_capacity == 3
    assert control.recovery_s == pytest.approx(30.0, abs=0.001)
    assert BlockingSignal.RATE_LIMITED in control.signals
    assert 0.0 < control.confidence <= 1.0


def test_high_burst_with_smooth_refill_is_a_token_bucket_hypothesis():
    evidence = [
        _ev("baseline-0", "baseline", 1.0, requests=2),
        _ev("steady-0", "steady", 1.0),
        _ev("steady-1", "steady", 2.0),
        _ev("steady-2", "steady", 5.0, rejected=4, requests=10, codes={"429": 4, "200": 6}),
        _ev("burst-0", "burst", 5.0, requests=10, burst_accepted=8),
    ]

    control = classify_mapping(evidence)

    assert control.outcome == "mapped"
    assert control.behaviour == "token-bucket-like"
    assert control.burst_capacity == 8
    assert control.threshold_low_per_s == 2.0
    assert control.threshold_high_per_s == 5.0


def test_latency_growth_without_a_refusal_fingerprint_is_backend_saturation():
    evidence = [
        _ev("baseline-0", "baseline", 1.0, requests=2, p95=20.0),
        _ev("steady-0", "steady", 1.0, p95=20.0),
        _ev("steady-1", "steady", 5.0, p95=45.0),
        _ev("steady-2", "steady", 20.0, p95=300.0),
    ]

    control = classify_mapping(evidence)

    assert control.behaviour == "backend-saturation"
    assert BlockingSignal.RATE_LIMITED not in control.signals
    assert control.outcome in ("mapped", "no_limiter", "inconclusive")


def test_failure_only_at_higher_concurrency_is_concurrency_limited():
    evidence = [
        _ev("baseline-0", "baseline", 1.0, requests=2),
        _ev("steady-0", "steady", 1.0),
        _ev("steady-1", "steady", 5.0),
        _ev("concurrency-0", "concurrency", 5.0, workers=1),
        _ev("concurrency-1", "concurrency", 5.0, workers=4, rejected=10, requests=10,
            codes={"429": 10}, headers=("x-ratelimit-limit",)),
    ]

    control = classify_mapping(evidence)

    assert control.behaviour == "concurrency-limited"
    assert control.outcome == "mapped"
    assert control.threshold_low_per_s == 5.0
    assert BlockingSignal.RATE_LIMITED in control.signals


def test_a_noisy_inconsistent_ladder_stays_inconclusive_and_unknown():
    evidence = [
        _ev("baseline-0", "baseline", 1.0, requests=2),
        _ev("steady-0", "steady", 1.0, rejected=3, requests=10, codes={"429": 3, "200": 7}),
        _ev("steady-1", "steady", 2.0),
        _ev("steady-2", "steady", 5.0, rejected=1, requests=10, codes={"429": 1, "200": 9}),
    ]

    control = classify_mapping(evidence)

    assert control.behaviour == "unknown"
    assert control.outcome == "inconclusive"
    assert control.confidence <= 0.3
    # The refusal fingerprint is still reported: the classifier never hides
    # evidence it cannot explain.
    assert BlockingSignal.RATE_LIMITED in control.signals


def test_an_entirely_failed_mapping_is_failed_not_guessed():
    evidence = [
        _ev("baseline-0", "baseline", 1.0, requests=0, outcome="failed", error="vegeta attack exited 1"),
    ]

    control = classify_mapping(evidence)

    assert control.outcome == "failed"
    assert control.behaviour == "unknown"
    assert control.traffic_policy is None


# --- scope -------------------------------------------------------------------


def test_scope_probes_vary_exactly_one_dimension():
    state = MappingState(
        target_key="https://target.example",
        url="https://target.example/login",
        scope_probes=(
            ScopeProbe(experiment_id="scope-0", dimension="endpoint"),
            ScopeProbe(experiment_id="scope-1", dimension="host"),
        ),
        evidence=[
            _ev("baseline-0", "baseline", 1.0, requests=2),
            _ev("steady-0", "steady", 1.0),
            _ev("steady-1", "steady", 20.0, rejected=20, requests=20, codes={"429": 20}),
            _ev("refine-0", "refine", 10.0),
            _ev("refine-1", "refine", 15.0, rejected=15, requests=15, codes={"429": 15}),
            _ev("burst-0", "burst", 15.0, requests=4, burst_accepted=2),
            _ev("recovery-0", "recovery", 1.0, requests=1),
            _ev("boundary-0", "boundary", 10.0),
            _ev("boundary-1", "boundary", 15.0, rejected=5, requests=5, codes={"429": 5}),
            _ev("ramp-0", "ramp", 15.0, rejected=10, requests=10, codes={"429": 10}),
            _ev("concurrency-0", "concurrency", 10.0, workers=1),
            _ev("concurrency-1", "concurrency", 10.0, workers=4),
        ],
    )
    budget = RateLimitSafetyBudget(max_requests=1000, max_duration_s=600)

    first = next_experiment(state, BudgetUsage(), budget)
    assert first is not None and first.phase == "scope"
    state.evidence.append(
        _ev(first.experiment_id, "scope", first.rate_per_s, rejected=5, requests=5, codes={"429": 5})
    )
    second = next_experiment(state, BudgetUsage(), budget)
    assert second is not None and second.phase == "scope"

    # Exactly one dimension changes between the canonical target and each probe.
    from urllib.parse import urlsplit

    canonical = urlsplit(state.url)
    first_parts = urlsplit(first.url)
    second_parts = urlsplit(second.url)
    assert (first_parts.netloc == canonical.netloc) != (first_parts.path == canonical.path)
    assert (second_parts.netloc == canonical.netloc) != (second_parts.path == canonical.path)
    assert first.url != second.url
    assert first.method == "GET" and second.method == "GET"


def test_scope_uses_the_single_dimension_that_removed_the_refusal():
    evidence = [
        _ev("steady-1", "steady", 20.0, rejected=20, requests=20, codes={"429": 20}),
        _ev("scope-0", "scope", 20.0),  # same host, other endpoint: accepted
        _ev("scope-1", "scope", 20.0, rejected=20, requests=20, codes={"429": 20}),
    ]
    probes = (
        ScopeProbe(experiment_id="scope-0", dimension="endpoint"),
        ScopeProbe(experiment_id="scope-1", dimension="host"),
    )
    assert derive_scope(evidence, probes) == "endpoint"

    still_limited = [evidence[0], _ev("scope-0", "scope", 20.0, rejected=20, requests=20, codes={"429": 20}), evidence[2]]
    assert derive_scope(still_limited, probes) == "target"


# --- policy derivation -------------------------------------------------------


def test_mapped_transition_policy_is_eighty_percent_of_the_lower_safe_bound():
    control = classify_mapping([
        _ev("steady-0", "steady", 1.0),
        _ev("steady-1", "steady", 10.0, rejected=10, requests=10, codes={"429": 10}),
        _ev("refine-0", "refine", 5.0),
    ])
    budget = RateLimitSafetyBudget(max_requests=100, max_duration_s=60, max_rate_per_s=20)

    policy = derive_policy(control, budget, target_key="https://target.example", host_patterns=["target.example"])

    assert policy.rate_per_s == pytest.approx(4.0)  # 80% of 5/s
    assert 1.0 <= policy.rate_per_s <= budget.max_rate_per_s
    assert policy.target_key == "https://target.example"
    assert policy.host_patterns == ["target.example"]
    assert policy.version == "traffic-policy/v2"
    assert policy.source == "measured-transition"


def test_mapped_policy_never_exceeds_the_operator_ceiling():
    control = classify_mapping([
        _ev("steady-0", "steady", 20.0),
        _ev("steady-1", "steady", 50.0, rejected=50, requests=50, codes={"429": 50}),
    ])
    budget = RateLimitSafetyBudget(max_requests=100, max_duration_s=60, max_rate_per_s=5)

    policy = derive_policy(control, budget, target_key="k", host_patterns=[])

    assert policy.rate_per_s == 5.0


def test_no_limiter_policy_uses_the_highest_rate_actually_tested():
    control = classify_mapping([
        _ev("steady-0", "steady", 1.0),
        _ev("steady-1", "steady", 10.0),
    ])
    budget = RateLimitSafetyBudget(max_requests=100, max_duration_s=600, max_rate_per_s=20)

    policy = derive_policy(control, budget, target_key="k", host_patterns=[])

    assert policy.rate_per_s == 10.0  # never infinity
    assert policy.source == "measured-no-limiter"


def test_failed_and_inconclusive_policies_are_conservative():
    budget = RateLimitSafetyBudget(max_requests=100, max_duration_s=60)
    for outcome in ("failed", "inconclusive"):
        control = classify_mapping([]).model_copy(update={"outcome": outcome})
        policy = derive_policy(control, budget, target_key="k", host_patterns=[])
        assert policy.rate_per_s <= 1.0
        assert policy.burst == 1
        assert policy.max_concurrency == 1
        assert policy.source == "conservative-fallback"


# --- budget ledger -----------------------------------------------------------


def test_budget_ledger_admits_atomically_and_refuses_before_execution():
    budget = RateLimitSafetyBudget(max_requests=8, max_duration_s=2, max_concurrency=2)
    ledger = BudgetLedger(budget)

    assert ledger.try_reserve(requests=8, duration_s=2) is True
    assert ledger.try_reserve(requests=3, duration_s=1) is False
    assert ledger.usage.requests == 8
    assert ledger.usage.duration_s == 2
    assert ledger.usage.experiments == 1


def test_budget_ledger_bounds_concurrency_variants_and_identity_opt_in():
    budget = RateLimitSafetyBudget(
        max_requests=100, max_duration_s=100, max_concurrency=2, max_bypass_variants=1
    )
    ledger = BudgetLedger(budget)

    assert ledger.try_reserve(requests=5, duration_s=1, concurrency=3) is False
    assert ledger.usage.requests == 0  # a refused admission consumes nothing
    assert ledger.try_reserve(requests=5, duration_s=1, concurrency=2, variant=True) is True
    assert ledger.try_reserve(requests=5, duration_s=1, variant=True) is False
    assert ledger.usage.variants == 1
    assert ledger.usage.max_concurrency == 2


# --- the state machine -------------------------------------------------------


def _walk(state: MappingState, budget: RateLimitSafetyBudget, ledger: BudgetLedger, limit: int = 30):
    """Drive `next_experiment` exactly the way the harness does."""
    specs = []
    for _ in range(limit):
        spec = next_experiment(state, ledger.usage, budget)
        if spec is None:
            break
        if not ledger.try_reserve(
            requests=spec.requests, duration_s=spec.duration_s, concurrency=spec.concurrency
        ):
            break
        specs.append(spec)
        # Answer each probe as an accepted response so the ladder runs out.
        state.evidence.append(
            _ev(spec.experiment_id, spec.phase, spec.rate_per_s, requests=spec.requests)
        )
    return specs


def test_the_state_machine_advances_through_the_closed_phase_sequence():
    budget = RateLimitSafetyBudget(max_requests=400, max_duration_s=180, max_concurrency=4)
    state = MappingState(target_key="k", url="https://target.example/login")
    specs = _walk(state, budget, BudgetLedger(budget))

    phases = [spec.phase for spec in specs]
    assert phases[0] == "baseline"
    assert phases[1] == "steady"
    assert set(phases) >= {"baseline", "steady", "burst", "recovery", "boundary", "ramp", "concurrency"}
    assert len(set(phases)) == len(phases) or phases.count("steady") == len(STEADY_RATE_LADDER)
    # Rates never exceed the operator ceiling, and the ladder is monotonically
    # ascending (a transition can only be bracketed by an ordered ladder).
    steady_rates = [s.rate_per_s for s in specs if s.phase == "steady"]
    assert steady_rates == sorted(steady_rates)
    assert max(steady_rates) <= budget.max_rate_per_s


def test_the_state_machine_end_is_bounded_by_the_budget():
    budget = RateLimitSafetyBudget(max_requests=6, max_duration_s=6, max_concurrency=1)
    state = MappingState(target_key="k", url="https://target.example/login")
    specs = _walk(state, budget, BudgetLedger(budget))

    # The controller stops offering work the ledger cannot admit - it never
    # silently enlarges the operator's budget.
    assert len(specs) < len(STEADY_RATE_LADDER) + 6
    assert next_experiment(state, BudgetUsage(requests=100), budget) is None


def test_the_state_machine_skips_the_concurrency_probe_at_concurrency_one():
    budget = RateLimitSafetyBudget(max_requests=400, max_duration_s=180, max_concurrency=1)
    state = MappingState(target_key="k", url="https://target.example/login")
    specs = _walk(state, budget, BudgetLedger(budget))
    assert "concurrency" not in {spec.phase for spec in specs}


# --- the bypass evidence gate ------------------------------------------------


def _mutation(**overrides) -> MutationSpec:
    data = {"variant_id": "v1", "family": "parameter-carrier", "description": "carrier swap"}
    data.update(overrides)
    return MutationSpec(**data)


def test_bypass_confirms_only_when_all_four_gates_are_positive():
    canonical = _ev("steady-3", "steady", 10.0, rejected=10, requests=10, codes={"429": 10},
                    headers=("retry-after",), bodies=("refusal",))
    variant = _ev("variant-0", "steady", 10.0, headers=("content-type",), bodies=("welcome",))
    repeat = _ev("variant-1", "steady", 10.0, bodies=("welcome",))

    finding = judge_bypass(canonical, variant, repeat)

    assert finding.outcome == "confirmed"
    assert finding.gates.all_passed is True
    assert finding.canonical_experiment_id == "steady-3"
    assert set(finding.variant_experiment_ids) == {"variant-0", "variant-1"}


def test_an_unchanged_limiter_state_is_no_bypass():
    canonical = _ev("steady-3", "steady", 10.0, rejected=10, requests=10, codes={"429": 10},
                    headers=("retry-after",))
    variant = _ev("variant-0", "steady", 10.0, rejected=10, requests=10, codes={"429": 10},
                  headers=("retry-after",))
    repeat = _ev("variant-1", "steady", 10.0, rejected=10, requests=10, codes={"429": 10},
                 headers=("retry-after",))

    finding = judge_bypass(canonical, variant, repeat)

    assert finding.outcome == "no_bypass"
    assert finding.gates.all_passed is False


def test_missing_semantic_evidence_is_inconclusive_never_confirmed():
    canonical = _ev("steady-3", "steady", 10.0, rejected=10, requests=10, codes={"429": 10})
    variant = _ev("variant-0", "steady", 10.0)  # accepted but no body fingerprint
    repeat = _ev("variant-1", "steady", 10.0)

    finding = judge_bypass(canonical, variant, repeat)

    assert finding.outcome == "inconclusive"
    assert finding.gates.semantic_equivalence is False


def test_an_unstable_repeat_is_inconclusive():
    canonical = _ev("steady-3", "steady", 10.0, rejected=10, requests=10, codes={"429": 10},
                    bodies=("refusal",))
    variant = _ev("variant-0", "steady", 10.0, bodies=("welcome",))
    repeat = _ev("variant-1", "steady", 10.0, rejected=6, requests=10, codes={"429": 6, "200": 4},
                 bodies=("refusal",))

    finding = judge_bypass(canonical, variant, repeat)

    assert finding.outcome == "inconclusive"
    assert finding.gates.reproduced is False


def test_a_variant_offered_at_a_different_rate_is_never_a_confirmed_bypass():
    """#238 Task 8 (found LIVE): the gate used to compare a refusal measured at
    one offered rate with an acceptance measured at a LOWER rate, and called the
    difference a bypass. With the mutation transport unwired, the harness's own
    variant probe then "confirmed" an unmutated replay - the variant was
    accepted because less traffic was offered, not because anything changed.
    A confounded differential proves neither a bypass nor its absence."""
    canonical = _ev("steady-1", "steady", 2.0, rejected=3, requests=6,
                    codes={"200": 3, "429": 3}, headers=("retry-after",))
    variant = _ev("variant-0", "steady", 1.0, requests=3)  # fewer requests/s
    repeat = _ev("variant-1", "steady", 1.0, requests=3)

    finding = judge_bypass(canonical, variant, repeat)

    assert finding.outcome == "inconclusive"
    assert finding.gates.material_state_change is False
    assert finding.gates.all_passed is False
