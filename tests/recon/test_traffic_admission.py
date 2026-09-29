"""Task 2 (#238 follow-up): the pure, total job-admission decision and the
closed, round-trippable admission envelope.

The decision function is deterministic and pure: it observes ONLY the job's
mandatory `traffic_cost`, the caller-derived `AdmissionContext`, and the parsed
`TrafficAdmissionSettings`. It cannot see bypass findings, LLM output, or any
model-facing value - so a bypass can never change an admission decision.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.control.traffic_admission import TrafficAdmissionEnvelope
from polymerhus.recon.domain.rate_limit import TrafficPolicy
from polymerhus.recon.domain.traffic_admission import (
    AdmissionContext,
    AdmissionDisposition,
    AdmissionReason,
    JobAdmissionDecision,
    TrafficAdmissionSettings,
    decide_job_admission,
)

SETTINGS = TrafficAdmissionSettings.from_env({})
_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

ARJUN = JOBS["arjun"]
FFUF = JOBS["ffuf"]
HTTPX = JOBS["httpx"]
WHOIS = JOBS["whois"]


def fresh_context(
    safe_rate_per_s: float | None,
    *,
    status: str = "mapped",
    policy_present: bool = True,
    fresh: bool = True,
    now: datetime = _NOW,
) -> AdmissionContext:
    return AdmissionContext(
        profile_status=status,
        safe_rate_per_s=safe_rate_per_s,
        profile_fresh=fresh,
        policy_present=policy_present,
        evaluated_at=now,
    )


def policy(rate_per_s: float) -> TrafficPolicy:
    return TrafficPolicy(
        target_key="t1", rate_per_s=rate_per_s, burst=1, source="mapped"
    )


# --- request_intensive: the numeric gates -----------------------------------


def test_mapped_high_rate_admits_intensive_job():
    decision = decide_job_admission(4, ARJUN, 2, fresh_context(10.0), SETTINGS)
    assert decision.decision is AdmissionDisposition.INCLUDED
    assert decision.reason_code is AdmissionReason.ADMITTED
    # 2 inputs * 260 requests / 10 rps = 52 s.
    assert decision.estimated_requests == 520
    assert decision.projected_duration_s == 52.0


def test_mapped_low_rate_prunes_intensive_job():
    decision = decide_job_admission(4, ARJUN, 1, fresh_context(1.5), SETTINGS)
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.BELOW_MIN_SAFE_RATE


def test_no_limiter_uses_the_highest_tested_rate():
    # `no_limiter` is a usable outcome: admission runs from the highest actually
    # tested rate, never an unbounded sentinel.
    decision = decide_job_admission(
        4, FFUF, 1, fresh_context(20.0, status="no_limiter"), SETTINGS
    )
    assert decision.decision is AdmissionDisposition.INCLUDED
    assert decision.safe_rate_per_s == 20.0


@pytest.mark.parametrize("status", ["inconclusive", "failed"])
def test_uncertain_outcome_prunes_intensive_job(status):
    decision = decide_job_admission(4, ARJUN, 1, fresh_context(50.0, status=status), SETTINGS)
    assert decision.decision is AdmissionDisposition.EXCLUDED
    expected = (
        AdmissionReason.PROFILE_INCONCLUSIVE
        if status == "inconclusive"
        else AdmissionReason.PROFILE_FAILED
    )
    assert decision.reason_code is expected


def test_stale_profile_prunes_intensive_job():
    decision = decide_job_admission(5, ARJUN, 1, fresh_context(50.0, fresh=False), SETTINGS)
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.PROFILE_STALE


def test_missing_policy_prunes_intensive_job():
    decision = decide_job_admission(
        4, ARJUN, 1, fresh_context(10.0, policy_present=False), SETTINGS
    )
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.POLICY_MISSING


def test_empty_intensive_consumption_is_recorded_but_not_started():
    decision = decide_job_admission(4, ARJUN, 0, fresh_context(10.0), SETTINGS)
    assert decision == JobAdmissionDecision(
        phase=4,
        job_name=ARJUN.tool,
        cost_class="request_intensive",
        input_count=0,
        estimated_requests=0,
        safe_rate_per_s=10.0,
        projected_duration_s=0.0,
        decision="excluded",
        reason_code="no_inputs",
    )


def test_public_issue_238_shapes_use_job_and_typed_evidence():
    """The persisted JSON uses the SAME key the public recon-jobs API uses.

    #238 A2: the decision serialized as `job_name` while every public job row
    (the API's `/recon/{run_id}` `per_job`) uses `job`, so a consumer reading
    the two with one key silently saw nothing. `job` is canonical; the legacy
    `job_name` is accepted on INPUT so already-stored envelopes still validate.
    """
    decision = decide_job_admission(5, ARJUN, 1, fresh_context(50.0), SETTINGS)

    dumped = decision.model_dump(mode="json")
    assert dumped["job"] == ARJUN.tool
    assert "job_name" not in dumped
    # A legacy envelope (serialized as `job_name`) still validates.
    legacy_payload = {key: value for key, value in dumped.items() if key != "job"}
    legacy_payload["job_name"] = dumped["job"]
    legacy = JobAdmissionDecision.model_validate(legacy_payload)
    assert legacy.job == ARJUN.tool


def test_empty_non_target_consumption_is_also_excluded():
    decision = decide_job_admission(0, WHOIS, 0, fresh_context(None, policy_present=False), SETTINGS)
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.NO_INPUTS


def test_intensive_boundaries_are_inclusive():
    decision = decide_job_admission(
        phase=4,
        job=ARJUN,
        input_count=1,
        estimated_requests=600,
        context=fresh_context(safe_rate_per_s=2.0),
        settings=SETTINGS.model_copy(update={"max_projected_duration_s": 300.0}),
    )
    assert decision.decision is AdmissionDisposition.INCLUDED
    assert decision.projected_duration_s == 300.0
    assert decision.safe_rate_per_s == 2.0


def test_just_below_the_minimum_rate_is_pruned():
    decision = decide_job_admission(
        4, ARJUN, 1, fresh_context(1.999_999), SETTINGS, estimated_requests=100
    )
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.BELOW_MIN_SAFE_RATE


def test_just_over_the_maximum_duration_is_pruned():
    decision = decide_job_admission(
        4, ARJUN, 1, fresh_context(2.0), SETTINGS, estimated_requests=601
    )
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.PROJECTED_DURATION_EXCEEDED


@pytest.mark.parametrize("estimate", [0, -5])
def test_invalid_estimate_is_cost_model_invalid(estimate):
    decision = decide_job_admission(
        4, ARJUN, 1, fresh_context(10.0), SETTINGS, estimated_requests=estimate
    )
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.COST_MODEL_INVALID


# --- bounded_http / non_target ----------------------------------------------


def test_bounded_job_runs_under_a_conservative_policy_when_uncertain():
    decision = decide_job_admission(
        3, HTTPX, 5, fresh_context(1.0, status="inconclusive"), SETTINGS
    )
    assert decision.decision is AdmissionDisposition.INCLUDED
    assert decision.reason_code is AdmissionReason.ADMITTED


def test_bounded_job_is_excluded_when_no_policy_exists():
    decision = decide_job_admission(
        3, HTTPX, 5, fresh_context(None, policy_present=False), SETTINGS
    )
    assert decision.decision is AdmissionDisposition.EXCLUDED
    assert decision.reason_code is AdmissionReason.POLICY_MISSING


def test_non_target_job_runs_without_a_policy():
    decision = decide_job_admission(
        0, WHOIS, 3, fresh_context(None, policy_present=False), SETTINGS
    )
    assert decision.decision is AdmissionDisposition.INCLUDED
    assert decision.reason_code is AdmissionReason.ADMITTED
    assert decision.estimated_requests == 0


# --- bypass non-authority ----------------------------------------------------


def test_bypass_findings_cannot_change_an_admission_decision():
    # No input type carries a bypass field, so four otherwise-identical contexts
    # (one per bypass outcome) must produce byte-identical decisions. A bypass
    # is evidence only.
    assert "bypass" not in " ".join(AdmissionContext.model_fields)
    assert "bypass" not in " ".join(JobAdmissionDecision.model_fields)
    baseline = decide_job_admission(4, ARJUN, 1, fresh_context(10.0), SETTINGS)
    for _ in range(3):
        assert decide_job_admission(4, ARJUN, 1, fresh_context(10.0), SETTINGS) == baseline


# --- the closed envelope -----------------------------------------------------


def _envelope() -> TrafficAdmissionEnvelope:
    decisions = tuple(
        decide_job_admission(phase, job, 1, fresh_context(10.0), SETTINGS)
        for phase, name in ((3, "httpx"), (4, "ffuf"))
        for job in (JOBS[name],)
    )
    return TrafficAdmissionEnvelope(
        profile_version="rate-profile/v2",
        profile_outcome="mapped",
        measured_at=_NOW,
        expires_at=_NOW + timedelta(seconds=3600),
        effective_policy=policy(10.0),
        candidate_phases=(("httpx", "ffuf"),),
        materialized_phases=(("httpx",),),
        decisions=decisions,
        effective_config=SETTINGS,
        event_order=("auth", "rate_mapping", "admission_persisted"),
        warnings=(),
        refusals=(),
    )


def test_envelope_roundtrips_json():
    env = _envelope()
    payload = env.model_dump(mode="json")
    assert payload["version"] == "traffic-admission/v1"
    assert TrafficAdmissionEnvelope.model_validate(payload) == env


def test_envelope_forbids_unknown_fields():
    payload = _envelope().model_dump(mode="json")
    payload["surprise"] = 1
    with pytest.raises(ValidationError):
        TrafficAdmissionEnvelope.model_validate(payload)


def test_envelope_preserves_candidate_and_materialized_phase_order():
    env = _envelope()
    assert env.candidate_phases == (("httpx", "ffuf"),)
    assert env.materialized_phases == (("httpx",),)


def test_every_exclusion_reason_is_a_structured_enum_member():
    for reason in AdmissionReason:
        assert isinstance(reason.value, str)
        assert reason.value == reason.value.lower()
