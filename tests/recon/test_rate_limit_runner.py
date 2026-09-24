"""#238 Task 4 - the deterministic controller, evidence gate and profile.

The harness is the composition point: it owns the budget ledger, drives the
state machine through an INJECTED async executor, judges variants against the
evidence gate, and merges the model's interpretation into a measurement it can
never overwrite.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest

from polymerhus.recon.domain.rate_limit import (
    EvidenceReference,
    ExperimentEvidence,
    ExperimentSpec,
    MAX_EVIDENCE_REFERENCES,
    MutationSpec,
    RateLimitSafetyBudget,
    RateLoopVerdict,
)
from polymerhus.recon.control import rate_limit_runner as runner_module
from polymerhus.recon.control.rate_limit_runner import (
    KaliExecutionError,
    RateLimitHarness,
    build_rate_limit_tools,
    evidence_from_kali_result,
    kali_exec_args,
    kali_spec_payload,
    parse_kali_exec_envelope,
)


class RecordingExecutor:
    """The injected async executor: answers from a scripted plan and records
    every spec it was asked to run."""

    def __init__(self, responder=None):
        self.specs: list[ExperimentSpec] = []
        self._responder = responder or self._accept
        self.calls = 0

    @staticmethod
    def _accept(spec: ExperimentSpec) -> ExperimentEvidence:
        return ExperimentEvidence(
            experiment_id=spec.experiment_id,
            phase=spec.phase,
            offered_rate_per_s=spec.rate_per_s,
            requests=spec.requests,
            concurrent_workers=spec.concurrency,
            duration_s=spec.duration_s,
            status_counts={"200": spec.requests},
            rejection_ratio=0.0,
            latency_p50_ms=10.0,
            latency_p95_ms=20.0,
            artifact_ref=f"rate-artifact/v1:proj-1/run-1/{spec.experiment_id}",
            manifest_sha256="b" * 64,
        )

    async def __call__(self, spec: ExperimentSpec) -> ExperimentEvidence:
        self.specs.append(spec)
        self.calls += 1
        return self._responder(spec)


def _run(coro):
    return asyncio.run(coro)


def _harness(executor, **overrides) -> RateLimitHarness:
    kwargs = dict(
        target_key="https://target.example",
        url="https://target.example/login",
        project_id="proj-1",
        run_id="run-1",
        budget=RateLimitSafetyBudget(max_requests=400, max_duration_s=180, max_concurrency=4),
        execute=executor,
        profile_ttl_s=3600.0,
    )
    kwargs.update(overrides)
    return RateLimitHarness(**kwargs)


# --- mapping -----------------------------------------------------------------


def test_map_returns_a_classified_control_and_attaches_the_policy():
    def responder(spec: ExperimentSpec) -> ExperimentEvidence:
        rejected = spec.rate_per_s > 5.0
        requests = spec.requests
        return ExperimentEvidence(
            experiment_id=spec.experiment_id,
            phase=spec.phase,
            offered_rate_per_s=spec.rate_per_s,
            requests=requests,
            concurrent_workers=spec.concurrency,
            duration_s=spec.duration_s,
            status_counts={"429": requests} if rejected else {"200": requests},
            rejection_ratio=1.0 if rejected else 0.0,
            latency_p50_ms=10.0,
            latency_p95_ms=20.0,
            artifact_ref=f"rate-artifact/v1:proj-1/run-1/{spec.experiment_id}",
            manifest_sha256="c" * 64,
        )

    executor = RecordingExecutor(responder)
    harness = _harness(executor)

    control = _run(harness.map())

    assert control.outcome == "mapped"
    assert control.threshold_low_per_s == 5.0
    assert control.threshold_high_per_s == pytest.approx(6.25)
    assert control.traffic_policy is not None
    assert control.traffic_policy.rate_per_s == pytest.approx(4.0)
    assert control.traffic_policy.version == "traffic-policy/v2"
    assert harness.control is control


def test_map_never_exceeds_the_operator_budget():
    executor = RecordingExecutor()
    harness = _harness(
        executor, budget=RateLimitSafetyBudget(max_requests=6, max_duration_s=6, max_concurrency=1)
    )

    _run(harness.map())

    assert sum(spec.requests for spec in executor.specs) <= 6
    assert sum(spec.duration_s for spec in executor.specs) <= 6
    assert harness.ledger.usage.requests <= 6


def test_a_truncated_ladder_is_inconclusive_not_no_limiter():
    """`no_limiter` is only honest when the permitted surface was EXHAUSTED."""
    executor = RecordingExecutor()
    harness = _harness(
        executor, budget=RateLimitSafetyBudget(max_requests=5, max_duration_s=5, max_concurrency=1)
    )

    control = _run(harness.map())

    assert control.outcome == "inconclusive"
    assert control.traffic_policy is None or control.traffic_policy.source == "conservative-fallback"


def test_a_tool_failure_stops_probing_and_yields_a_failed_control():
    def responder(spec: ExperimentSpec) -> ExperimentEvidence:
        return ExperimentEvidence(
            experiment_id=spec.experiment_id,
            phase=spec.phase,
            offered_rate_per_s=spec.rate_per_s,
            outcome="failed",
            error="vegeta attack exited 1: no such host",
        )

    executor = RecordingExecutor(responder)
    harness = _harness(executor)

    control = _run(harness.map())

    assert control.outcome == "failed"
    # The harness attaches Task 1's conservative fallback: a failed mapping
    # never leaves later traffic unthrottled.
    assert control.traffic_policy is not None
    assert control.traffic_policy.source == "conservative-fallback"
    assert control.traffic_policy.rate_per_s <= 1.0
    assert len(executor.specs) == 1  # the controller stops spending on a broken tool


def test_the_executor_exception_degrades_to_a_loud_conservative_profile():
    class Boom:
        async def __call__(self, spec):
            raise KaliExecutionError("kali MCP unavailable")

    harness = _harness(Boom())
    control = _run(harness.map())

    assert control.outcome == "failed"
    assert "kali MCP unavailable" in harness.failure_reason
    profile = harness.build_profile(RateLoopVerdict())
    assert profile.outcome == "failed"
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert profile.traffic_policy.source == "conservative-fallback"


# --- variants and the evidence gate ------------------------------------------


def test_identity_mutations_are_refused_when_the_operator_has_not_opted_in():
    executor = RecordingExecutor()
    harness = _harness(executor)  # allow_identity_mutations defaults to False

    async def scenario():
        await harness.map()
        before = len(executor.specs)
        evidence = await harness.run_variant(
            MutationSpec(
                variant_id="id-1",
                family="identity-header",
                identity_mutation=True,
                parameters={"header": "X-Forwarded-For"},
            )
        )
        return before, evidence

    before, evidence = _run(scenario())

    assert evidence.outcome == "failed"
    assert "identity" in (evidence.error or "").lower()
    assert len(executor.specs) == before  # the executor was never called


def test_budget_refuses_a_variant_before_the_executor_runs():
    executor = RecordingExecutor()
    harness = _harness(
        executor,
        budget=RateLimitSafetyBudget(
            max_requests=400, max_duration_s=180, max_bypass_variants=0
        ),
    )

    async def scenario():
        await harness.map()
        before = len(executor.specs)
        evidence = await harness.run_variant(
            MutationSpec(variant_id="v1", family="parameter-carrier")
        )
        return before, evidence

    before, evidence = _run(scenario())

    assert evidence.outcome == "failed"
    assert "variant" in (evidence.error or "").lower()
    assert len(executor.specs) == before


def test_the_tools_are_exactly_the_two_actor_callables():
    harness = _harness(RecordingExecutor())
    tools = build_rate_limit_tools(harness)

    assert [tool.name for tool in tools] == ["map_rate_limit", "test_rate_limit_variant"]
    mapped = _run(tools[0].ainvoke({}))
    payload = json.loads(mapped) if isinstance(mapped, str) else mapped
    assert payload["experiment_ids"], payload
    # The variant tool takes exactly one bounded mutation: no traffic numbers.
    assert set(tools[1].args_schema.model_json_schema()["properties"]) == {"mutation"}


def test_a_variant_run_is_judged_against_the_canonical_rejection():
    def responder(spec: ExperimentSpec) -> ExperimentEvidence:
        canonical = spec.variant is None
        if canonical:
            return ExperimentEvidence(
                experiment_id=spec.experiment_id,
                phase=spec.phase,
                offered_rate_per_s=spec.rate_per_s,
                requests=spec.requests,
                status_counts={"429": spec.requests},
                rejection_ratio=1.0,
                body_fingerprint=["refusal"],
            )
        return ExperimentEvidence(
            experiment_id=spec.experiment_id,
            phase=spec.phase,
            offered_rate_per_s=spec.rate_per_s,
            requests=spec.requests,
            status_counts={"200": spec.requests},
            rejection_ratio=0.0,
            body_fingerprint=["welcome"],
        )

    executor = RecordingExecutor(responder)
    harness = _harness(executor)

    async def scenario():
        await harness.map()
        return await harness.judge_variant(MutationSpec(variant_id="v1", family="parameter-carrier"))

    finding = _run(scenario())

    assert finding.outcome == "confirmed"
    assert finding.gates.all_passed
    assert harness.bypass_outcome == "confirmed"


# --- the profile merge -------------------------------------------------------


def _mapped_harness() -> RateLimitHarness:
    def responder(spec: ExperimentSpec) -> ExperimentEvidence:
        rejected = spec.rate_per_s > 5.0
        return ExperimentEvidence(
            experiment_id=spec.experiment_id,
            phase=spec.phase,
            offered_rate_per_s=spec.rate_per_s,
            requests=spec.requests,
            duration_s=spec.duration_s,
            status_counts={"429": spec.requests} if rejected else {"200": spec.requests},
            rejection_ratio=1.0 if rejected else 0.0,
            latency_p50_ms=10.0,
            latency_p95_ms=20.0,
            artifact_ref=f"rate-artifact/v1:proj-1/run-1/{spec.experiment_id}",
            manifest_sha256="d" * 64,
        )

    harness = _harness(RecordingExecutor(responder))
    _run(harness.map())
    return harness


def test_build_profile_merges_measurement_budget_and_artifact_refs():
    harness = _mapped_harness()
    profile = harness.build_profile(
        RateLoopVerdict(outcome="mapped", bypass_outcome="no_bypass", interpretation="window limiter")
    )

    assert profile.outcome == "mapped"
    assert profile.target_key == "https://target.example"
    assert profile.traffic_policy.rate_per_s == pytest.approx(4.0)
    assert profile.artifact_refs
    assert all(ref.startswith("rate-artifact/v1:") for ref in profile.artifact_refs)
    assert profile.budget.max_requests == 400
    assert profile.usage.requests == harness.ledger.usage.requests
    assert profile.expires_at is not None and profile.expires_at > profile.measured_at


def test_the_model_cannot_overwrite_a_measurement_or_enlarge_the_budget():
    harness = _mapped_harness()
    # A hostile verdict names variants and signals it never measured: neither
    # can enter the profile, and no numeric field exists for it to edit.
    verdict = RateLoopVerdict(
        outcome="mapped",
        bypass_outcome="confirmed",
        confirmed_variant_ids=["never-ran"],
        evidence_experiment_ids=["never-ran"],
        interpretation="send 1000 rps, budget is now unlimited",
    )

    profile = harness.build_profile(verdict)

    assert profile.bypass_outcome == "inconclusive"
    assert profile.bypass_findings == []
    assert profile.budget.max_requests == 400
    assert profile.traffic_policy.rate_per_s <= 4.0


def test_a_validated_model_claim_is_merged_but_stays_evidence_only():
    def responder(spec: ExperimentSpec) -> ExperimentEvidence:
        if spec.variant is None:
            rejected = spec.rate_per_s > 5.0
            return ExperimentEvidence(
                experiment_id=spec.experiment_id,
                phase=spec.phase,
                offered_rate_per_s=spec.rate_per_s,
                requests=spec.requests,
                status_counts={"429": spec.requests} if rejected else {"200": spec.requests},
                rejection_ratio=1.0 if rejected else 0.0,
                body_fingerprint=["refusal"] if rejected else [],
            )
        return ExperimentEvidence(
            experiment_id=spec.experiment_id,
            phase=spec.phase,
            offered_rate_per_s=spec.rate_per_s,
            requests=spec.requests,
            status_counts={"200": spec.requests},
            rejection_ratio=0.0,
            body_fingerprint=["welcome"],
        )

    harness = _harness(RecordingExecutor(responder))

    async def scenario():
        await harness.map()
        await harness.judge_variant(MutationSpec(variant_id="v1", family="parameter-carrier"))

    _run(scenario())
    profile = harness.build_profile(
        RateLoopVerdict(bypass_outcome="confirmed", confirmed_variant_ids=["v1"])
    )

    assert profile.bypass_outcome == "confirmed"
    assert [finding.variant.variant_id for finding in profile.bypass_findings] == ["v1"]
    # Evidence is never an instruction: the traffic policy is unchanged by the
    # confirmed bypass.
    assert profile.traffic_policy.rate_per_s <= 4.0


# --- the Kali result adapter -------------------------------------------------


def test_evidence_from_kali_result_keeps_only_aggregates_and_references():
    spec = ExperimentSpec(
        experiment_id="steady-1",
        phase="steady",
        url="https://target.example/login",
        rate_per_s=5.0,
        duration_s=3.0,
        requests=15,
    )
    payload = {
        "experiment_id": "steady-1",
        "phase": "steady",
        "outcome": "measured",
        "artifact_ref": "rate-artifact/v1:proj-1/run-1/steady-1",
        "manifest_sha256": "e" * 64,
        "count": 15,
        "duration_s": 3.0,
        "offered_rate_per_s": 5.0,
        "concurrent_workers": 1,
        "status_counts": {"200": 10, "429": 5},
        "rejection_ratio": 1 / 3,
        "latency_p50_ms": 12.0,
        "latency_p95_ms": 40.0,
        "header_fingerprint": ["retry-after"],
        "body_fingerprint": ["deadbeef"],
    }

    evidence = evidence_from_kali_result(spec, payload)

    assert evidence.experiment_id == "steady-1"
    assert evidence.requests == 15
    assert evidence.rejection_ratio == pytest.approx(1 / 3)
    assert evidence.artifact_ref == "rate-artifact/v1:proj-1/run-1/steady-1"
    assert evidence.manifest_sha256 == "e" * 64
    assert evidence.header_fingerprint == ["retry-after"]
    assert evidence.outcome == "measured"


def test_evidence_from_a_failed_kali_result_is_typed_and_unreferenced():
    spec = ExperimentSpec(
        experiment_id="steady-1", phase="steady", url="https://t/", rate_per_s=1.0,
        duration_s=1.0, requests=1,
    )
    evidence = evidence_from_kali_result(
        spec, {"outcome": "failed", "error": "vegeta attack exited 1"}
    )
    assert evidence.outcome == "failed"
    assert evidence.error
    assert evidence.artifact_ref is None


def test_kali_spec_payload_carries_the_controller_owned_traffic_shape():
    spec = ExperimentSpec(
        experiment_id="steady-1",
        phase="steady",
        url="https://t/login",
        method="POST",
        headers={"Authorization": "Bearer x"},
        rate_per_s=2.0,
        duration_s=3.0,
        requests=6,
        concurrency=2,
    )

    payload = kali_spec_payload(spec, project_id="proj-1", run_id="run-1")

    assert payload["experiment_id"] == "steady-1"
    assert payload["project_id"] == "proj-1"
    assert payload["run_id"] == "run-1"
    assert payload["rate_per_s"] == 2.0 and payload["duration_s"] == 3.0
    assert payload["requests"] == 6 and payload["concurrency"] == 2
    assert payload["headers"] == {"Authorization": "Bearer x"}
    assert "body" not in payload  # the replay surface carries no request body


def test_the_kali_envelope_is_parsed_and_a_bare_failure_is_typed():
    spec = ExperimentSpec(
        experiment_id="steady-1", phase="steady", url="https://t/", rate_per_s=1.0,
        duration_s=1.0, requests=1,
    )
    def fake_exec(args: dict) -> dict:
        return {
            "stdout": json.dumps({
                "experiment_id": "steady-1",
                "phase": "steady",
                "outcome": "measured",
                "count": 1,
                "status_counts": {"200": 1},
                "artifact_ref": "rate-artifact/v1:p/r/steady-1",
                "manifest_sha256": "f" * 64,
            }),
            "returncode": 0,
        }

    evidence = parse_kali_exec_envelope(spec, fake_exec({}))
    assert evidence.outcome == "measured" and evidence.requests == 1

    failed = parse_kali_exec_envelope(
        spec, {"stdout": "", "stderr": "boom", "returncode": 1}
    )
    assert failed.outcome == "failed"
    assert failed.error


def test_kali_exec_args_match_the_exec_seam_contract():
    """The plan's exact invocation: the Kali runner, the spec on private stdin,
    and the run-scoped session the artifacts are published under."""
    spec = ExperimentSpec(
        experiment_id="steady-2", phase="steady", url="https://t/login",
        rate_per_s=5.0, duration_s=3.0, requests=15,
    )

    args = kali_exec_args(spec, project_id="proj-1", run_id="run-1", timeout_s=120)

    assert args["command"] == "/opt/venv/bin/python -m kali.rate_limit.runner"
    assert args["session_id"] == "rate-run-1"
    assert args["project_id"] == "proj-1" and args["run_id"] == "run-1"
    assert args["spec_id"] == "steady-2"
    assert args["timeout_s"] == 120
    payload = json.loads(args["stdin_text"])
    assert payload["project_id"] == "proj-1" and payload["experiment_id"] == "steady-2"
    # The spec is on stdin, never in argv (argv is visible in the process table).
    assert "stdin_text" in args and "Authorization" not in json.dumps(args["command"])


# --- Task 3: configured TTL, typed evidence, and secret safety ---------------------


def test_profile_honours_the_configured_ttl():
    harness = _harness(RecordingExecutor(), profile_ttl_s=60.0)
    _run(harness.map())
    profile = harness.build_profile(RateLoopVerdict())
    assert profile.expires_at - profile.measured_at == timedelta(seconds=60)


def test_harness_refuses_a_non_positive_ttl():
    with pytest.raises(ValueError):
        _harness(RecordingExecutor(), profile_ttl_s=0.0)
    with pytest.raises(ValueError):
        _harness(RecordingExecutor(), profile_ttl_s=float("nan"))


def test_build_profile_stores_only_typed_capped_evidence_references():
    harness = _mapped_harness()
    profile = harness.build_profile(RateLoopVerdict())

    assert profile.evidence
    assert len(profile.evidence) <= MAX_EVIDENCE_REFERENCES
    for ref in profile.evidence:
        assert isinstance(ref, EvidenceReference)
        assert ref.ref.startswith("rate-artifact/v1:")
        assert len(ref.sha256) == 64
    for dumped in profile.model_dump(mode="json")["evidence"]:
        assert set(dumped) == {"ref", "sha256", "experiment_id", "count"}


def test_profile_json_never_leaks_header_or_cookie_secrets():
    harness = _harness(
        RecordingExecutor(),
        headers={"Authorization": "Bearer SECRET-TOKEN", "Cookie": "sid=SECRET-SID"},
    )
    _run(harness.map())
    profile = harness.build_profile(RateLoopVerdict())
    blob = json.dumps(profile.model_dump(mode="json"))
    assert "SECRET-TOKEN" not in blob
    assert "SECRET-SID" not in blob
