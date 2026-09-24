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
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from polymerhus.recon import config as recon_config
from polymerhus.recon.domain.blocking import BlockingSignal
from polymerhus.recon.domain.rate_limit import (
    RATE_PROFILE_VERSION,
    TRAFFIC_POLICY_VERSION,
    EvidenceReference,
    ExperimentEvidence,
    ExperimentSpec,
    MutationSpec,
    RateLimitSafetyBudget,
    RateProfile,
    TrafficPolicy,
    upgrade_rate_profile_v1,
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

    assert payload["version"] == "traffic-policy/v2"
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
    assert profile.traffic_policy.version == "traffic-policy/v2"
    assert profile.budget == budget
    assert profile.reason == "controller failure"


def test_conservative_profile_never_exceeds_the_operator_rate_cap():
    budget = RateLimitSafetyBudget(max_rate_per_s=0.5)

    profile = RateProfile.conservative("t", [], budget, "rate failure", "inconclusive")

    assert profile.outcome == "inconclusive"
    assert profile.traffic_policy.rate_per_s == 0.5


_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _v2_profile(**overrides) -> RateProfile:
    policy = _policy()
    fields = dict(
        target_key="target-1",
        host_patterns=["app.example.test"],
        outcome="mapped",
        budget=RateLimitSafetyBudget(),
        measured_at=_NOW,
        expires_at=_NOW + timedelta(seconds=3600),
        safe_rate_per_s=policy.rate_per_s,
        traffic_policy=policy,
    )
    fields.update(overrides)
    return RateProfile(**fields)


def test_profile_signals_use_the_shared_vocabulary():
    profile = _v2_profile(
        target_key="t",
        signals=["rate_limited"],
    )

    assert profile.signals == [BlockingSignal.RATE_LIMITED]
    assert profile.model_dump(mode="json")["signals"] == ["rate_limited"]


def test_profile_rejects_an_unknown_outcome():
    with pytest.raises(ValidationError):
        _v2_profile(target_key="t", outcome="probably-fine")


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


# --- v2 wire contracts, typed evidence, and freshness (Task 3) --------------------


def test_wire_versions_advanced_to_v2_together():
    assert RATE_PROFILE_VERSION == "rate-profile/v2"
    assert TRAFFIC_POLICY_VERSION == "traffic-policy/v2"
    assert _v2_profile().version == "rate-profile/v2"


def test_evidence_reference_accepts_a_relative_hashed_coordinate():
    ref = EvidenceReference(
        ref="rate-artifact/v1:proj-1/run-1/steady-1",
        sha256="a" * 64,
        experiment_id="steady-1",
        count=40,
    )
    assert ref.model_dump(mode="json") == {
        "ref": "rate-artifact/v1:proj-1/run-1/steady-1",
        "sha256": "a" * 64,
        "experiment_id": "steady-1",
        "count": 40,
    }


@pytest.mark.parametrize(
    "bad_ref",
    ["/tmp/raw.json", "file:///tmp/x", "../escape", "~/.ssh/id_rsa", "C:/raw"],
)
def test_evidence_reference_rejects_a_non_relative_coordinate(bad_ref):
    with pytest.raises(ValidationError):
        EvidenceReference(ref=bad_ref, sha256="a" * 64, experiment_id="e1", count=1)


@pytest.mark.parametrize("bad_sha", ["abc", "A" * 64, "z" * 64, "", "a" * 63])
def test_evidence_reference_rejects_a_bad_sha256(bad_sha):
    with pytest.raises(ValidationError):
        EvidenceReference(
            ref="rate-artifact/v1:p/r/e1", sha256=bad_sha, experiment_id="e1", count=1
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"body": "raw response body"},
        {"authorization": "Bearer secret"},
        {"cookie": "sid=secret"},
        {"payload": {"raw": "hits"}},
    ],
)
def test_evidence_reference_is_closed_against_raw_and_sensitive_keys(extra):
    with pytest.raises(ValidationError):
        EvidenceReference(
            ref="rate-artifact/v1:p/r/e1", sha256="a" * 64, experiment_id="e1",
            count=1, **extra,
        )


def test_profile_is_stale_at_expiry():
    profile = _v2_profile()
    assert profile.is_fresh(profile.expires_at - timedelta(microseconds=1))
    assert not profile.is_fresh(profile.expires_at)


def test_profile_requires_timezone_aware_timestamps():
    with pytest.raises(ValidationError):
        _v2_profile(measured_at=datetime(2026, 9, 24, 12, 0))
    with pytest.raises(ValidationError):
        _v2_profile(expires_at=datetime(2026, 9, 24, 13, 0))


def test_profile_stores_typed_evidence_references():
    ref = EvidenceReference(
        ref="rate-artifact/v1:p/r/e1", sha256="a" * 64, experiment_id="e1", count=3
    )
    profile = _v2_profile(evidence=(ref,))
    dumped = profile.model_dump(mode="json")
    assert dumped["evidence"] == [
        {"ref": "rate-artifact/v1:p/r/e1", "sha256": "a" * 64,
         "experiment_id": "e1", "count": 3}
    ]


def test_the_wire_boundary_rejects_a_v1_profile_payload():
    # v1 payloads carry `profile_version` and the untyped `artifact_refs`; they
    # are readable ONLY through the explicit `upgrade_rate_profile_v1` adapter.
    with pytest.raises(ValidationError):
        RateProfile.model_validate(
            {"profile_version": "rate-profile/v1", "version": "rate-profile/v1",
             "target_key": "t"}
        )


def test_upgrade_rate_profile_v1_returns_a_v2_profile():
    v1 = {
        "target_key": "t",
        "host_patterns": ["app.example.test"],
        "outcome": "mapped",
        "profile_version": "rate-profile/v1",
        "traffic_policy": _policy().model_dump(mode="json"),
        "artifact_refs": ["rate-artifact/v1:proj-1/run-1/steady-1"],
        "measured_at": "2026-09-24T12:00:00+00:00",
        "expires_at": "2026-09-24T13:00:00+00:00",
        "safe_rate_per_s": 4.0,
    }
    profile = upgrade_rate_profile_v1(v1)

    assert profile.version == "rate-profile/v2"
    assert profile.safe_rate_per_s == 4.0
    assert profile.safe_rate_per_s == profile.traffic_policy.rate_per_s
    assert profile.artifact_refs == ["rate-artifact/v1:proj-1/run-1/steady-1"]
    # v1 refs are unhashed audit data - never fabricated into typed evidence.
    assert profile.evidence == ()


def test_upgrade_rate_profile_v1_derives_safe_rate_from_the_policy_when_absent():
    v1 = {
        "target_key": "t",
        "outcome": "no_limiter",
        "profile_version": "rate-profile/v1",
        "traffic_policy": _policy(rate_per_s=7.5).model_dump(mode="json"),
        "measured_at": "2026-09-24T12:00:00+00:00",
        "expires_at": "2026-09-24T13:00:00+00:00",
    }
    profile = upgrade_rate_profile_v1(v1)
    assert profile.safe_rate_per_s == 7.5
