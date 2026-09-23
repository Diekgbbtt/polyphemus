"""Unit tier - the #238 rate-limit contracts (Task 1).

The measured rate profile that governs every later request for a target is a
typed value object, and the operator's safety budget is the ONE bound the
deterministic controller may consume but never enlarge. These tests pin the
closed vocabularies, the budget refusals, the conservative fallback policy,
and the environment boundary that parses the operator knobs once (loudly on
an invalid value, never a silent repair).

Pure contracts only: no production collaborator is constructed here
(CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from polymerhus.recon import config as recon_config
from polymerhus.recon.domain.blocking import BlockingSignal
from polymerhus.recon.domain.rate_limit import (
    ExperimentEvidence,
    ExperimentSpec,
    MutationSpec,
    RateLimitSafetyBudget,
    RateProfile,
    TrafficPolicy,
)

_KNOBS = (
    "RATE_LIMIT_MAX_REQUESTS",
    "RATE_LIMIT_MAX_DURATION_S",
    "RATE_LIMIT_MAX_RATE",
    "RATE_LIMIT_MAX_CONCURRENCY",
    "RATE_LIMIT_MAX_BYPASS_VARIANTS",
    "RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS",
    "RATE_LIMIT_AWAIT_TIMEOUT_S",
    "RATE_LIMIT_PROFILE_TTL_S",
)


@pytest.fixture
def rate_config(monkeypatch):
    """`recon.config` reloaded with every rate-limit knob cleared.

    The knobs are read ONCE at import (the KATANA_DEPTH contract), so the only
    faithful way to exercise them is set-the-env-then-reload. The fixture
    restores the production module afterwards, so a reload can never leak a
    test value into another test in the session.
    """
    with monkeypatch.context() as m:
        for name in _KNOBS:
            m.delenv(name, raising=False)
        module = importlib.reload(recon_config)
        yield module
    importlib.reload(recon_config)


# --- the blocking vocabulary -----------------------------------------------------


def test_blocking_vocabulary_is_single_sourced():
    assert {item.value for item in BlockingSignal} == {
        "waf_protected", "waf_detection", "rate_limited"
    }


def test_blocking_signal_is_the_string_it_names():
    """A `str` enum, so classifiers, JSON payloads and skill text share one
    spelling without a translation table."""
    assert BlockingSignal.RATE_LIMITED == "rate_limited"
    assert BlockingSignal("waf_protected") is BlockingSignal.WAF_PROTECTED


# --- RateLimitSafetyBudget --------------------------------------------------------


def test_budget_rejects_zero_requests():
    with pytest.raises(ValidationError):
        RateLimitSafetyBudget(max_requests=0)


def test_budget_rejects_concurrency_above_request_cap():
    with pytest.raises(ValidationError):
        RateLimitSafetyBudget(max_requests=3, max_concurrency=4)


def test_budget_rejects_a_non_positive_rate_and_duration():
    with pytest.raises(ValidationError):
        RateLimitSafetyBudget(max_rate_per_s=0)
    with pytest.raises(ValidationError):
        RateLimitSafetyBudget(max_duration_s=0)


def test_budget_allows_a_zero_variant_bypass_budget():
    """Zero bypass variants is the strictly-safer setting (no mutation probe
    runs at all), so it is a legal operator budget, not an invalid one."""
    budget = RateLimitSafetyBudget(max_bypass_variants=0)
    assert budget.max_bypass_variants == 0


def test_identity_mutations_default_to_disabled():
    assert RateLimitSafetyBudget().allow_identity_mutations is False


# --- the operator environment boundary (parsed once, loudly) ----------------------


def test_default_environment_resolves_the_documented_budget(rate_config):
    budget = rate_config.rate_limit_safety_budget()

    assert budget.max_requests == 400
    assert budget.max_duration_s == 180.0
    assert budget.max_rate_per_s == 20.0
    assert budget.max_concurrency == 4
    assert budget.max_bypass_variants == 4
    assert budget.allow_identity_mutations is False


def test_await_timeout_and_profile_ttl_have_defaults(rate_config):
    assert rate_config.RATE_LIMIT_AWAIT_TIMEOUT_S == 1800.0
    assert rate_config.RATE_LIMIT_PROFILE_TTL_S == 3600


def test_environment_overrides_the_budget(monkeypatch):
    with monkeypatch.context() as m:
        m.setenv("RATE_LIMIT_MAX_REQUESTS", "50")
        m.setenv("RATE_LIMIT_MAX_DURATION_S", "30")
        m.setenv("RATE_LIMIT_MAX_RATE", "2.5")
        m.setenv("RATE_LIMIT_MAX_CONCURRENCY", "2")
        m.setenv("RATE_LIMIT_MAX_BYPASS_VARIANTS", "1")
        m.setenv("RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS", "true")
        m.setenv("RATE_LIMIT_AWAIT_TIMEOUT_S", "12.5")
        m.setenv("RATE_LIMIT_PROFILE_TTL_S", "60")
        module = importlib.reload(recon_config)

        budget = module.rate_limit_safety_budget()
        assert budget == RateLimitSafetyBudget(
            max_requests=50, max_duration_s=30.0, max_rate_per_s=2.5,
            max_concurrency=2, max_bypass_variants=1,
            allow_identity_mutations=True,
        )
        assert module.RATE_LIMIT_AWAIT_TIMEOUT_S == 12.5
        assert module.RATE_LIMIT_PROFILE_TTL_S == 60
    importlib.reload(recon_config)


@pytest.mark.parametrize(
    "name, value",
    [
        ("RATE_LIMIT_MAX_REQUESTS", "0"),
        ("RATE_LIMIT_MAX_REQUESTS", "-1"),
        ("RATE_LIMIT_MAX_REQUESTS", "many"),
        ("RATE_LIMIT_MAX_DURATION_S", "0"),
        ("RATE_LIMIT_MAX_RATE", "0"),
        ("RATE_LIMIT_MAX_CONCURRENCY", "0"),
        ("RATE_LIMIT_MAX_BYPASS_VARIANTS", "-1"),
        ("RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS", "sometimes"),
        ("RATE_LIMIT_AWAIT_TIMEOUT_S", "0"),
        ("RATE_LIMIT_PROFILE_TTL_S", "0"),
    ],
)
def test_an_invalid_knob_fails_loudly_at_configuration_load(monkeypatch, name, value):
    """The operator budget is a safety boundary: an unparseable or
    non-positive value must stop the boot, never be silently repaired."""
    with monkeypatch.context() as m:
        m.setenv(name, value)
        with pytest.raises(ValueError, match=name):
            importlib.reload(recon_config)
    importlib.reload(recon_config)


# --- TrafficPolicy ---------------------------------------------------------------


def _policy(**overrides) -> TrafficPolicy:
    fields = {
        "target_key": "target-1",
        "host_patterns": ["app.example.test"],
        "rate_per_s": 4.0,
        "burst": 2,
        "max_concurrency": 2,
        "min_delay_ms": 250.0,
        "source": "measured",
    }
    fields.update(overrides)
    return TrafficPolicy(**fields)


def test_traffic_policy_carries_the_closed_transport_contract():
    payload = _policy().model_dump(mode="json")

    assert payload["version"] == "traffic-policy/v1"
    assert payload["target_key"] == "target-1"
    assert payload["host_patterns"] == ["app.example.test"]
    assert payload["rate_per_s"] == 4.0
    assert payload["burst"] == 2
    assert payload["max_concurrency"] == 2
    assert payload["min_delay_ms"] == 250.0
    assert payload["source"] == "measured"


def test_traffic_policy_rejects_a_non_positive_rate():
    with pytest.raises(ValidationError):
        _policy(rate_per_s=0)


# --- RateProfile: the conservative fallback ---------------------------------------


def test_conservative_profile_caps_rate_burst_and_concurrency():
    budget = RateLimitSafetyBudget(max_rate_per_s=20.0)

    profile = RateProfile.conservative(
        "target-1", ["app.example.test"], budget,
        "controller failure", "failed",
    )

    assert profile.outcome == "failed"
    assert profile.target_key == "target-1"
    assert profile.host_patterns == ["app.example.test"]
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert profile.traffic_policy.burst == 1
    assert profile.traffic_policy.max_concurrency == 1
    assert profile.traffic_policy.source == "conservative-fallback"
    assert profile.traffic_policy.version == "traffic-policy/v1"
    assert profile.budget == budget
    assert profile.reason == "controller failure"


def test_conservative_profile_never_exceeds_the_operator_rate_cap():
    budget = RateLimitSafetyBudget(max_rate_per_s=0.5)

    profile = RateProfile.conservative("t", [], budget, "rate failure", "inconclusive")

    assert profile.outcome == "inconclusive"
    assert profile.traffic_policy.rate_per_s == 0.5


def test_profile_signals_use_the_shared_vocabulary():
    profile = RateProfile(
        target_key="t",
        host_patterns=["app.example.test"],
        outcome="mapped",
        budget=RateLimitSafetyBudget(),
        signals=["rate_limited"],
        traffic_policy=_policy(),
    )

    assert profile.signals == [BlockingSignal.RATE_LIMITED]
    assert profile.model_dump(mode="json")["signals"] == ["rate_limited"]


def test_profile_rejects_an_unknown_outcome():
    with pytest.raises(ValidationError):
        RateProfile(
            target_key="t", outcome="probably-fine",
            budget=RateLimitSafetyBudget(), traffic_policy=_policy(),
        )


def test_profile_starts_empty_of_bypass_claims():
    profile = RateProfile.conservative(
        "t", [], RateLimitSafetyBudget(), "no mapping", "no_limiter",
    )

    assert profile.artifact_refs == []
    assert profile.bypass_findings == []
    assert profile.bypass_outcome == "inconclusive"
    assert profile.confidence == 0.0
    assert profile.signals == []


def test_profile_is_json_serialisable_without_raw_evidence():
    """The run-stats seam carries the profile and artifact REFERENCES only -
    never a hit body, a header dump or a credential."""
    payload = RateProfile.conservative(
        "t", ["app.example.test"], RateLimitSafetyBudget(), "no mapping",
        "inconclusive",
    ).model_dump(mode="json")

    assert set(payload) >= {
        "target_key", "host_patterns", "outcome", "budget", "signals",
        "traffic_policy", "artifact_refs", "bypass_outcome", "confidence",
    }
    assert "headers" not in payload
    assert "body" not in payload


# --- ExperimentSpec / MutationSpec / ExperimentEvidence ---------------------------


def test_experiment_spec_carries_the_controller_owned_traffic_shape():
    spec = ExperimentSpec(
        experiment_id="exp-1", phase="steady", url="https://app.example.test/api",
        rate_per_s=5.0, duration_s=10.0, requests=50, concurrency=2,
        timeout_s=15.0,
    )

    assert spec.method == "GET"
    assert spec.variant is None
    assert spec.model_dump(mode="json")["phase"] == "steady"


def test_experiment_spec_rejects_an_unknown_phase():
    with pytest.raises(ValidationError):
        ExperimentSpec(
            experiment_id="exp-1", phase="guess", url="https://a.test/",
            rate_per_s=1.0, duration_s=1.0, requests=1, concurrency=1,
            timeout_s=2.0,
        )


def test_mutation_families_are_closed():
    assert MutationSpec(
        variant_id="v1", family="endpoint-shape", description="trailing slash",
    ).identity_mutation is False
    assert MutationSpec(
        variant_id="v2", family="identity-header", identity_mutation=True,
    ).identity_mutation is True
    with pytest.raises(ValidationError):
        MutationSpec(variant_id="v3", family="make-it-faster")


def test_experiment_evidence_is_a_typed_failed_or_measured_result():
    evidence = ExperimentEvidence(
        experiment_id="exp-1", phase="steady", offered_rate_per_s=5.0,
        requests=50, status_counts={"200": 48, "429": 2}, rejection_ratio=0.04,
    )

    assert evidence.outcome == "measured"
    assert evidence.error is None
    failed = ExperimentEvidence(
        experiment_id="exp-2", phase="steady", offered_rate_per_s=5.0,
        requests=0, outcome="failed", error="vegeta exit 1",
    )
    assert failed.error == "vegeta exit 1"
