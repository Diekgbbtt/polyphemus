"""#238 the deterministic rate-limit controller, harness and actor tools.

The harness is where pure planning meets the world, and where the design's two
authorities are separated for good:

* the CONTROLLER owns the budget and every traffic number. `RateLimitHarness.map`
  drives `rate_limit_mapper.next_experiment` through an injected async
  `execute(spec) -> ExperimentEvidence` seam, admitting each experiment through
  the atomic ledger before it starts. The LLM never sees a count, a rate or a
  duration.
* the MODEL interprets. `build_rate_limit_tools` exposes exactly two
  actor-callable tools - `map_rate_limit()` and `test_rate_limit_variant(mutation)`
  - and a `MutationSpec` carries no traffic number. A confirmed variant is
  EVIDENCE: it is recorded in the profile and never applied to recon traffic.

Failure posture (spec, "Persistenza e failure posture"): a controller/tool
failure yields a `failed` control and, through `build_profile`, the loud
one-request-per-second conservative policy - never unthrottled traffic.

Everything side-effecting is injectable and resolved lazily (CODING_STANDARD
section 6): importing this module performs no I/O and requires no env var.
"""
from __future__ import annotations

import inspect
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from polymerhus.recon.domain.rate_limit import (
    MAX_EVIDENCE_REFERENCES,
    EvidenceReference,
    ExperimentEvidence,
    ExperimentSpec,
    MappedControl,
    MutationSpec,
    RateLimitSafetyBudget,
    RateLoopVerdict,
    RateProfile,
    TestedBounds,
    TrafficPolicy,
)
from polymerhus.recon.control.rate_limit_mapper import (
    STEADY_DURATION_S,
    BudgetLedger,
    MappingState,
    ScopeProbe,
    classify_mapping,
    derive_policy,
    derive_scope,
    judge_bypass,
    next_experiment,
)
from polymerhus.recon.control.request_mutation import (
    CanonicalRequest,
    apply_mutation,
)

logger = logging.getLogger(__name__)

KALI_RUNNER_COMMAND = "/opt/venv/bin/python -m kali.rate_limit.runner"
"""The Kali-side entry point the controller invokes through `execute_command`."""

DEFAULT_EXPERIMENT_TIMEOUT_S = 300.0
"""The exec envelope's timeout when the caller names none."""

LADDER_PHASES = ("steady", "refine", "boundary", "ramp")


class KaliExecutionError(RuntimeError):
    """The Kali exec seam itself failed (transport, MCP, tool error).

    Distinct from a MEASURED failure: this says "the experiment could not be
    attempted", which the controller treats as a loud, typed controller failure.
    """


# --- the Kali transport ------------------------------------------------------


def kali_spec_payload(
    spec: ExperimentSpec, *, project_id: str, run_id: str
) -> dict:
    """The JSON payload the Kali runner reads from PRIVATE STDIN.

    The project/run scope is what makes the published artifact reference
    `rate-artifact/v1:<project>/<run>/<experiment>` resolvable. No request body
    is expressible - the replay surface is method+url+headers.

    #238 follow-up (Task 5): the controller materializes the EFFECTIVE request
    here, once, and ships it as `effective_request`. Kali executes exactly that -
    it never reinterprets `ExperimentSpec.variant`, which is what let a variant
    probe silently replay the canonical request before this landed.
    """
    canonical = CanonicalRequest(
        method=spec.method,
        url=spec.url,
        headers=tuple(spec.headers.items()),
    )
    effective = apply_mutation(
        canonical, spec.variant.payload if spec.variant is not None else None
    )
    return {
        "experiment_id": spec.experiment_id,
        "phase": spec.phase,
        "project_id": project_id,
        "run_id": run_id,
        "effective_request": effective.model_dump(mode="json"),
        "rate_per_s": spec.rate_per_s,
        "duration_s": spec.duration_s,
        "requests": spec.requests,
        "concurrency": spec.concurrency,
        "timeout_s": spec.timeout_s,
        "notes": spec.notes,
    }


def kali_exec_args(
    spec: ExperimentSpec,
    *,
    project_id: str,
    run_id: str,
    timeout_s: float = DEFAULT_EXPERIMENT_TIMEOUT_S,
) -> dict:
    """The exact `execute_command` argument dict the controller sends.

    The spec rides `stdin_text` (never argv): it carries the authenticated
    context, and argv is visible in the process table.
    """
    return {
        "command": KALI_RUNNER_COMMAND,
        "stdin_text": json.dumps(
            kali_spec_payload(spec, project_id=project_id, run_id=run_id)
        ),
        "session_id": f"rate-{run_id}",
        "timeout_s": int(timeout_s),
        "project_id": project_id,
        "run_id": run_id,
        "spec_id": spec.experiment_id,
    }


def evidence_from_kali_result(spec: ExperimentSpec, payload: Mapping) -> ExperimentEvidence:
    """Translate the Kali runner's compact result into domain evidence.

    Aggregates, fingerprints and references only: the raw hit stream stays on
    the Kali data root, addressed by `artifact_ref` and pinned by
    `manifest_sha256`.
    """
    failed = str(payload.get("outcome") or "measured") == "failed"
    return ExperimentEvidence(
        experiment_id=str(payload.get("experiment_id") or spec.experiment_id),
        phase=spec.phase,
        offered_rate_per_s=float(payload.get("offered_rate_per_s") or spec.rate_per_s),
        requests=int(payload.get("count") or 0),
        concurrent_workers=int(payload.get("concurrent_workers") or spec.concurrency),
        duration_s=float(payload.get("duration_s") or spec.duration_s),
        status_counts={
            str(key): int(value)
            for key, value in (payload.get("status_counts") or {}).items()
        },
        rejection_ratio=float(payload.get("rejection_ratio") or 0.0),
        latency_p50_ms=payload.get("latency_p50_ms"),
        latency_p95_ms=payload.get("latency_p95_ms"),
        burst_accepted=payload.get("burst_accepted"),
        header_fingerprint=[str(item) for item in payload.get("header_fingerprint") or []],
        body_fingerprint=[str(item) for item in payload.get("body_fingerprint") or []],
        artifact_ref=payload.get("artifact_ref") or None,
        manifest_sha256=payload.get("manifest_sha256") or None,
        outcome="failed" if failed else "measured",
        error=payload.get("error") or None,
    )


def parse_kali_exec_envelope(spec: ExperimentSpec, envelope: Mapping) -> ExperimentEvidence:
    """Parse one `execute_command` envelope, loudly and totally.

    A well-formed compact result is used as-is; anything else (non-zero exit
    with no result, malformed JSON, a truncated stdout) is a TYPED failure - the
    absence of evidence is never an assumed success.
    """
    returncode = int(envelope.get("returncode", 1) or 0)
    stdout = str(envelope.get("stdout") or "")
    payload: object = None
    if stdout.strip():
        try:
            payload = json.loads(stdout)
        except ValueError:
            payload = None
    if isinstance(payload, dict):
        return evidence_from_kali_result(spec, payload)
    stderr = str(envelope.get("stderr") or "").strip()[:200]
    return ExperimentEvidence(
        experiment_id=spec.experiment_id,
        phase=spec.phase,
        offered_rate_per_s=spec.rate_per_s,
        concurrent_workers=spec.concurrency,
        outcome="failed",
        error=f"no structured rate-limit result (returncode={returncode}): {stderr}",
    )


async def _call_kali_exec(args: Mapping, *, mcp_url: str | None = None) -> dict:
    """Call the Kali MCP `execute_command` tool programmatically.

    The MCP client and the config are resolved HERE, never at import, so the
    unit tier never needs a Kali host (CODING_STANDARD section 6).
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: PLC0415
    from polymerhus.app.config import config  # noqa: PLC0415
    from polymerhus.recon.domain.pod import _exec_result_from_artifact  # noqa: PLC0415

    client = MultiServerMCPClient(
        {"kali": {"url": mcp_url or config.KALI_MCP_URL, "transport": "streamable_http"}}
    )
    tools = await client.get_tools()
    exec_tool = next(tool for tool in tools if tool.name == "execute_command")
    result = await exec_tool.ainvoke(
        {
            "type": "tool_call",
            "name": "execute_command",
            "id": str(args.get("session_id") or "rate-limit"),
            "args": dict(args),
        }
    )
    # Reuse the pod layer's artifact unwrapping: one reading of the
    # content-and-artifact envelope across the codebase (CODING_STANDARD 8).
    shaped = _exec_result_from_artifact(
        getattr(result, "artifact", None), content=getattr(result, "content", None)
    )
    return {
        "stdout": shaped.stdout,
        "stderr": shaped.stderr,
        "returncode": shaped.returncode,
        "duration_ms": shaped.duration_ms,
    }


def build_kali_execute(
    *,
    project_id: str,
    run_id: str,
    timeout_s: float = DEFAULT_EXPERIMENT_TIMEOUT_S,
    mcp_url: str | None = None,
) -> Callable[[ExperimentSpec], Awaitable[ExperimentEvidence]]:
    """The production executor: one experiment, measured by the Kali runner."""

    async def execute(spec: ExperimentSpec) -> ExperimentEvidence:
        args = kali_exec_args(
            spec, project_id=project_id, run_id=run_id, timeout_s=timeout_s
        )
        try:
            envelope = await _call_kali_exec(args, mcp_url=mcp_url)
        except Exception as exc:  # noqa: BLE001 - transport failure, typed loudly
            raise KaliExecutionError(f"{type(exc).__name__}: {exc}") from exc
        return parse_kali_exec_envelope(spec, envelope)

    return execute


# --- the harness --------------------------------------------------------------


def default_host_patterns(url: str) -> list[str]:
    """The host a `TrafficPolicy` should match, derived from the target URL."""
    host = urlsplit(url).hostname
    return [host] if host else []


def default_scope_probes() -> tuple[ScopeProbe, ...]:
    """The two single-dimension scope comparisons that need no identity change:
    another endpoint on the same host, and the same path on another host."""
    return (
        ScopeProbe(experiment_id="scope-0", dimension="endpoint"),
        ScopeProbe(experiment_id="scope-1", dimension="host"),
    )


class RateLimitHarness:
    """Owns the budget ledger, drives the mapper, and builds the public profile.

    `execute` is the ONLY side-effecting collaborator and is injected: production
    passes `build_kali_execute(...)`, tests pass a recording fake. It is called
    with an `ExperimentSpec` and answers with `ExperimentEvidence`.
    """

    def __init__(
        self,
        *,
        target_key: str,
        url: str,
        budget: RateLimitSafetyBudget,
        execute: Callable[[ExperimentSpec], Awaitable[ExperimentEvidence]],
        project_id: str = "",
        run_id: str = "",
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        host_patterns: Sequence[str] | None = None,
        scope_probes: Sequence[ScopeProbe] | None = None,
        ledger: BudgetLedger | None = None,
        experiment_timeout_s: float = DEFAULT_EXPERIMENT_TIMEOUT_S,
        profile_ttl_s: float,
    ):
        if not math.isfinite(profile_ttl_s) or profile_ttl_s <= 0:
            raise ValueError(
                f"profile_ttl_s must be finite and > 0, got {profile_ttl_s!r}"
            )
        self.target_key = target_key
        self.url = url
        self.method = method
        self.headers = dict(headers or {})
        self.project_id = project_id
        self.run_id = run_id
        self.budget = budget
        self.host_patterns = list(
            host_patterns if host_patterns is not None else default_host_patterns(url)
        )
        self.scope_probes = tuple(
            scope_probes if scope_probes is not None else default_scope_probes()
        )
        self.ledger = ledger or BudgetLedger(budget)
        self.experiment_timeout_s = experiment_timeout_s
        # The effective profile TTL, supplied by the caller from the operator
        # knob (`RATE_LIMIT_PROFILE_TTL_S`). Required: the harness never
        # silently falls back to the domain default.
        self.profile_ttl_s = profile_ttl_s
        self._execute = execute
        self._state: MappingState | None = None
        self._control: MappedControl | None = None
        self._failure_reason = ""
        self._findings: dict[str, object] = {}
        self._charged_variants: set[str] = set()

    # --- read-only views -------------------------------------------------------

    @property
    def control(self) -> MappedControl | None:
        return self._control

    @property
    def failure_reason(self) -> str:
        return self._failure_reason

    @property
    def findings(self) -> dict:
        return dict(self._findings)

    @property
    def bypass_outcome(self) -> str:
        if any(
            getattr(finding, "outcome", "") == "confirmed"
            for finding in self._findings.values()
        ):
            return "confirmed"
        if self._findings:
            return "no_bypass"
        return "inconclusive"

    @property
    def evidence(self) -> list[ExperimentEvidence]:
        return list(self._state.evidence) if self._state else []

    # --- driving ---------------------------------------------------------------

    async def _measure(self, spec: ExperimentSpec) -> ExperimentEvidence:
        """Run one admitted experiment through the injected seam."""
        result = self._execute(spec)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def map(self) -> MappedControl:
        """Run the deterministic mapping sequence within the operator budget."""
        state = MappingState(
            target_key=self.target_key,
            url=self.url,
            method=self.method,
            headers=dict(self.headers),
            scope_probes=self.scope_probes,
        )
        self._state = state
        while True:
            spec = next_experiment(state, self.ledger.usage, self.budget)
            if spec is None:
                break
            if not self.ledger.try_reserve(
                requests=spec.requests,
                duration_s=spec.duration_s,
                concurrency=spec.concurrency,
            ):
                # The ledger refused: the experiment does not start and consumes
                # nothing. The mapping ends honestly with what it measured.
                self._failure_reason = self._failure_reason or "budget exhausted"
                break
            try:
                evidence = await self._measure(spec)
            except Exception as exc:  # noqa: BLE001 - a controller fault is typed
                self._failure_reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "rate mapping: exec seam failed for %s (fail-loud, conservative)",
                    spec.experiment_id,
                    exc_info=True,
                )
                state.evidence.append(
                    ExperimentEvidence(
                        experiment_id=spec.experiment_id,
                        phase=spec.phase,
                        offered_rate_per_s=spec.rate_per_s,
                        concurrent_workers=spec.concurrency,
                        outcome="failed",
                        error=self._failure_reason,
                    )
                )
                break
            state.evidence.append(evidence)
            if evidence.outcome == "failed":
                self._failure_reason = evidence.error or "experiment failed"
                break

        return self._finish(state)

    def _finish(self, state: MappingState) -> MappedControl:
        control = classify_mapping(state.evidence)
        control = control.model_copy(
            update={"scope": derive_scope(state.evidence, state.scope_probes)}
        )
        control = control.model_copy(
            update={
                "traffic_policy": derive_policy(
                    control,
                    self.budget,
                    target_key=self.target_key,
                    host_patterns=self.host_patterns,
                )
            }
        )
        self._control = control
        return control

    # --- variants --------------------------------------------------------------

    def _canonical_rate(self) -> float:
        # The variant MUST be offered at the rate of the evidence the gate will
        # compare it against: a differential measured at two different rates is
        # confounded (the lower rate alone can explain an acceptance), which
        # `judge_bypass` refuses. The comparison anchor is `_canonical_evidence`,
        # so that is what sets the replay rate.
        canonical = self._canonical_evidence()
        if canonical is not None:
            return float(canonical.offered_rate_per_s)
        control = self._control
        if control and (control.threshold_high_per_s or control.threshold_low_per_s):
            return float(control.threshold_high_per_s or control.threshold_low_per_s)
        return min(1.0, self.budget.max_rate_per_s)

    def _canonical_evidence(self) -> ExperimentEvidence | None:
        for evidence in self.evidence:
            if evidence.phase in LADDER_PHASES and evidence.outcome == "measured":
                if evidence.rejection_ratio > 0:
                    return evidence
        return None

    def _variant_spec(self, mutation: MutationSpec, index: int) -> ExperimentSpec:
        rate = self._canonical_rate()
        duration = STEADY_DURATION_S
        return ExperimentSpec(
            experiment_id=f"variant-{mutation.variant_id}-{index}",
            phase="steady",  # the steady rate that triggers the mapped limiter
            url=self.url,
            method=self.method,
            rate_per_s=rate,
            duration_s=duration,
            requests=max(1, math.ceil(rate * duration)),
            headers=dict(self.headers),
            variant=mutation,
            notes=f"bounded bypass variant ({mutation.family}); evidence only",
        )

    def _refused_variant(self, mutation: MutationSpec, reason: str) -> ExperimentEvidence:
        return ExperimentEvidence(
            experiment_id=f"variant-{mutation.variant_id}-refused",
            phase="steady",
            offered_rate_per_s=self._canonical_rate(),
            concurrent_workers=1,
            outcome="failed",
            error=reason,
        )

    def _reserve_variant(self, spec: ExperimentSpec, mutation: MutationSpec) -> bool:
        # `max_bypass_variants` counts DISTINCT variants, not probe runs, so the
        # independent repetition of one variant is not charged twice.
        charge = mutation.variant_id not in self._charged_variants
        admitted = self.ledger.try_reserve(
            requests=spec.requests,
            duration_s=spec.duration_s,
            concurrency=spec.concurrency,
            variant=charge,
        )
        if admitted and charge:
            self._charged_variants.add(mutation.variant_id)
        return admitted

    async def run_variant(self, mutation: MutationSpec) -> ExperimentEvidence:
        """Probe ONE bounded bypass variant.

        Identity/forwarded-header mutations are refused while the operator has
        not opted in, and a variant the budget cannot admit is refused BEFORE
        the executor is reached.
        """
        if mutation.identity_mutation or mutation.family == "identity-header":
            if not self.budget.allow_identity_mutations:
                return self._refused_variant(
                    mutation,
                    "identity mutations are disabled by the operator budget "
                    "(set RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS to opt in)",
                )
        spec = self._variant_spec(mutation, index=len(self._charged_variants))
        if not self._reserve_variant(spec, mutation):
            return self._refused_variant(
                mutation, "the bypass-variant budget cannot admit this variant"
            )
        try:
            return await self._measure(spec)
        except Exception as exc:  # noqa: BLE001 - a probe fault is typed
            return ExperimentEvidence(
                experiment_id=spec.experiment_id,
                phase=spec.phase,
                offered_rate_per_s=spec.rate_per_s,
                concurrent_workers=spec.concurrency,
                outcome="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    async def judge_variant(self, mutation: MutationSpec) -> object:
        """Run a variant and its INDEPENDENT repetition, then apply the gate."""
        canonical = self._canonical_evidence()
        if canonical is None:
            canonical = ExperimentEvidence(
                experiment_id="no-canonical-refusal",
                phase="steady",
                offered_rate_per_s=self._canonical_rate(),
                concurrent_workers=1,
                rejection_ratio=0.0,
            )
        variant = await self.run_variant(mutation)
        repeat = await self.run_variant(mutation)
        finding = judge_bypass(canonical, variant, repeat, mutation=mutation)
        self._findings[mutation.variant_id] = finding
        return finding

    # --- the public profile ----------------------------------------------------

    def build_profile(self, verdict: RateLoopVerdict) -> RateProfile:
        """Merge the model's interpretation into the controller's measurement.

        The verdict can only ever ADD an accepted bypass claim about an
        experiment that exists and passed every gate. It cannot state a rate, a
        burst, a budget, a policy or a confidence - those fields are the
        controller's, and the model-facing type does not carry them.
        """
        state = self._state
        if self._control is None and state is not None:
            self._finish(state)
        control = self._control or classify_mapping([])
        policy: TrafficPolicy = control.traffic_policy or derive_policy(
            control,
            self.budget,
            target_key=self.target_key,
            host_patterns=self.host_patterns,
        )

        confirmed = []
        for variant_id in verdict.confirmed_variant_ids:
            finding = self._findings.get(variant_id)
            if finding is not None and getattr(finding, "outcome", "") == "confirmed":
                confirmed.append(finding)
        if confirmed:
            bypass_outcome = "confirmed"
        elif verdict.bypass_outcome == "no_bypass" and not verdict.confirmed_variant_ids:
            bypass_outcome = "no_bypass"
        else:
            bypass_outcome = "inconclusive"

        evidence = self.evidence
        artifact_refs = list(
            dict.fromkeys(
                item.artifact_ref for item in evidence if item.artifact_ref
            )
        )
        # The typed, relative, hashed, capped evidence references (v2). v1's
        # untyped `artifact_refs` above is retained for audit compatibility.
        evidence_references = tuple(
            EvidenceReference(
                ref=item.artifact_ref,
                sha256=item.manifest_sha256,
                experiment_id=item.experiment_id,
                count=item.requests,
            )
            for item in evidence
            if item.artifact_ref and item.manifest_sha256
        )[:MAX_EVIDENCE_REFERENCES]
        measured_at = datetime.now(timezone.utc)
        return RateProfile(
            target_key=self.target_key,
            host_patterns=list(self.host_patterns),
            outcome=control.outcome,
            tested_bounds=TestedBounds(
                max_requests=self.ledger.usage.requests,
                max_duration_s=self.ledger.usage.duration_s,
                max_rate_per_s=max(
                    (item.offered_rate_per_s for item in evidence), default=0.0
                ),
                max_concurrency=max(1, self.ledger.usage.max_concurrency),
            ),
            threshold_low_per_s=control.threshold_low_per_s,
            threshold_high_per_s=control.threshold_high_per_s,
            burst_capacity=control.burst_capacity,
            recovery_s=control.recovery_s,
            window_sensitivity=control.window_sensitivity,
            scope=control.scope,
            behaviour=control.behaviour,
            fingerprint=list(control.fingerprint),
            enforcement=_describe(control),
            confidence=control.confidence,
            measured_at=measured_at,
            expires_at=measured_at + timedelta(seconds=self.profile_ttl_s),
            safe_rate_per_s=policy.rate_per_s,
            budget=self.budget,
            usage=self.ledger.usage,
            artifact_refs=artifact_refs,
            evidence=evidence_references,
            bypass_outcome=bypass_outcome,
            bypass_findings=confirmed,
            signals=list(control.signals),
            traffic_policy=policy,
            reason=(
                f"rate mapping {control.outcome}"
                + (f": {self._failure_reason}" if self._failure_reason else "")
            ),
        )


def _describe(control: MappedControl) -> str:
    """A short, deterministic description - never model-authored prose."""
    low = control.threshold_low_per_s
    high = control.threshold_high_per_s
    bracket = "unknown"
    if low is not None and high is not None:
        bracket = f"{low:g}-{high:g}/s"
    elif control.tested_max_rate_per_s is not None:
        bracket = f"tested up to {control.tested_max_rate_per_s:g}/s"
    return f"{control.behaviour} limiter, scope={control.scope}, threshold={bracket}"


# --- the actor tools ----------------------------------------------------------


def build_rate_limit_tools(harness: RateLimitHarness) -> list:
    """Exactly the two actor-callable tools of the rate-limit turn.

    `map_rate_limit()` runs the deterministic sequence (the model proposes
    nothing about traffic); `test_rate_limit_variant(mutation)` probes ONE
    bounded variant from the closed family list. Both return compact,
    secret-free summaries - no raw hits, no credentials, no absolute paths.
    """
    from langchain_core.tools import tool  # noqa: PLC0415 - lazy, no I/O

    @tool
    async def map_rate_limit() -> dict:
        """Measure this target's rate-limit behaviour under the operator's hard
        safety budget and return the mapped control (ranges, a behavioural
        hypothesis, and the constraints the run will obey)."""
        control = await harness.map()
        return {
            "outcome": control.outcome,
            "behaviour": control.behaviour,
            "scope": control.scope,
            "threshold_low_per_s": control.threshold_low_per_s,
            "threshold_high_per_s": control.threshold_high_per_s,
            "burst_capacity": control.burst_capacity,
            "recovery_s": control.recovery_s,
            "confidence": control.confidence,
            "signals": [signal.value for signal in control.signals],
            "experiment_ids": control.experiment_ids,
            "traffic_policy": (
                control.traffic_policy.model_dump(mode="json")
                if control.traffic_policy
                else None
            ),
        }

    @tool
    async def test_rate_limit_variant(mutation: MutationSpec) -> dict:
        """Probe ONE bounded bypass variant and return its evidence-gated
        finding. A confirmed finding is evidence only - it is never applied to
        recon traffic. Identity-header mutations require an explicit operator
        opt-in and are refused otherwise."""
        finding = await harness.judge_variant(mutation)
        gates = finding.gates
        return {
            "variant_id": finding.variant.variant_id,
            "outcome": finding.outcome,
            "gates": {
                "canonical_rejected": gates.canonical_rejected,
                "material_state_change": gates.material_state_change,
                "semantic_equivalence": gates.semantic_equivalence,
                "reproduced": gates.reproduced,
            },
            "canonical_experiment_id": finding.canonical_experiment_id,
            "variant_experiment_ids": finding.variant_experiment_ids,
            "rationale": finding.rationale,
        }

    return [map_rate_limit, test_rate_limit_variant]


__all__ = [
    "DEFAULT_EXPERIMENT_TIMEOUT_S",
    "KALI_RUNNER_COMMAND",
    "KaliExecutionError",
    "RateLimitHarness",
    "build_kali_execute",
    "build_rate_limit_tools",
    "default_host_patterns",
    "default_scope_probes",
    "evidence_from_kali_result",
    "kali_exec_args",
    "kali_spec_payload",
    "parse_kali_exec_envelope",
]
