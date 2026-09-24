"""The #238 rate-limit domain: the safety budget, the experiment contracts,
and the measured profile that governs a target's later traffic.

The design split this module encodes (spec `docs/design/rate-limit-system-mapping-238-spec.md`,
resolved decision 2): a DETERMINISTIC controller owns traffic shape - counts,
rates, durations, concurrency, experiment order - while the LLM only picks
bounded variants and interprets evidence. That split is a type-level fact
here, not a convention:

- `RateLimitSafetyBudget` is the operator's hard ceiling. It is parsed once
  from the environment (`recon.config.rate_limit_safety_budget()`), the
  controller may consume it, and NOTHING in the model-facing contracts
  (`MutationSpec`, `RateLoopVerdict`) can carry a number that enlarges it.
- `ExperimentSpec` is what the controller admits and sends; its traffic
  numbers are controller-owned.
- `ExperimentEvidence` is the measured per-experiment result (aggregates and
  references only - raw hits and response bodies live in the artifact store,
  never here).
- `MappedControl` is the deterministic classification of that evidence, and
  `TrafficPolicy` its mechanically derived, enforceable output.
- `RateProfile` is the immutable public result: measurements, scope, bypass
  outcome, budget/usage, artifact REFERENCES, and the policy - the value the
  run stores under `recon_runs.stats.rate_limit` and every later request
  obeys.
- `RateProfile.conservative(...)` is the loud fallback: when mapping fails,
  times out or cannot represent a browser-only target, the run continues
  under a policy capped at 1 request/second rather than unthrottled.

Everything is pure: no I/O, no collaborator construction, no config read at
import (CODING_STANDARD section 6). Every contract is CLOSED (`extra="forbid"`):
a misspelled field is a wiring defect, not a silently-ignored one - a typo'd
`burst` must never weaken a policy by default.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Mapping, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    field_validator,
    model_validator,
)

from polymerhus.recon.domain.blocking import BLOCKING_SIGNALS, BlockingSignal

# --- closed vocabularies ------------------------------------------------------

RateOutcome = Literal["mapped", "no_limiter", "inconclusive", "failed"]
"""How the mapping ended. `no_limiter` means "no transition within the tested
bounds", never "no limiter exists" (spec, failure posture)."""

BypassOutcome = Literal["confirmed", "no_bypass", "inconclusive"]
"""The three first-class bypass results; `confirmed` is a finding, never an
instruction to change traffic (spec, bypass evidence gate)."""

EvidenceOutcome = Literal["measured", "failed"]
"""Whether one experiment produced measurements or returned a typed failure."""

ExperimentPhase = Literal[
    "baseline", "steady", "refine", "burst", "recovery", "boundary", "ramp",
    "concurrency", "scope",
]
"""The deterministic mapping sequence's phases (spec, mapping sequence)."""

EnforcementHypothesis = Literal[
    "fixed-window-like", "sliding-window-like", "token-bucket-like",
    "leaky-bucket-like", "concurrency-limited", "backend-saturation", "unknown",
]
"""Behavioural hypotheses only: the classifier never claims to know the
implementation (spec, mapping sequence)."""

LimiterScope = Literal["target", "host", "endpoint", "principal", "unknown"]
"""What the limiter appears to be keyed on."""

MutationFamily = Literal[
    "pacing", "endpoint-shape", "parameter-carrier", "method-equivalence",
    "session-principal", "identity-header",
]
"""The CLOSED mutation families a bypass hypothesis may draw from - the same
families the shared `performing-api-rate-limiting-bypass` procedure states.
`identity-header` (client-IP/forwarded-header identity mutations) is disabled
by default and requires an explicit operator opt-in (spec, resolved
decision 9)."""

TRAFFIC_POLICY_VERSION = "traffic-policy/v2"
"""The wire version of the enforced policy shape. v2 is required because
`max_concurrency` changes from inert data to enforced semantics (spec 13); the
application refuses an incompatible governor rather than assuming the field is
enforced."""

RATE_PROFILE_VERSION = "rate-profile/v2"
"""The stored version of the public profile shape. v2 carries typed, hashed
`EvidenceReference` entries and an explicit `safe_rate_per_s`; historical v1
rows stay audit data, readable only through `upgrade_rate_profile_v1` (spec 12.1,
19)."""

MAX_EVIDENCE_REFERENCES = 64
"""Cap on the typed evidence references kept on a profile. A run's experiments
are already bounded by the operator budget; 64 sits above any realistic mapping,
and this bound keeps the JSONB profile row small. Surplus refs are dropped - the
raw artifacts remain in the store, and the refs are informational."""

PROFILE_TTL_DEFAULT_S = 3600.0
"""The default validity of a mapping estimate. Mirrored by the
`RATE_LIMIT_PROFILE_TTL_S` operator knob (which imports this constant), so
the domain default and the deployment default cannot drift. A mapping is an
estimate at a moment: it is never presented as permanently true."""

CONSERVATIVE_RATE_PER_S = 1.0
"""The fallback policy's rate ceiling: one request per second."""


class _ClosedContract(BaseModel):
    """Base for every contract in this module: unknown keys are refused, so a
    typo lands as a loud validation error instead of a dropped safety field."""

    model_config = ConfigDict(extra="forbid")


class EvidenceReference(_ClosedContract):
    """One typed, integrity-pinned reference to a raw experiment artifact.

    The raw artifact (hit stream, response bodies, headers) lives in the
    immutable artifact store; the profile stores ONLY this coordinate. `ref` is
    a RELATIVE `rate-artifact/v1:...` coordinate (never an absolute path), and
    `sha256` is the manifest/content integrity hash. Raw payloads, response
    bodies, credentials, and sensitive headers are not expressible here - they
    are unknown keys, and this contract is closed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str
    sha256: str
    experiment_id: str
    count: NonNegativeInt

    @field_validator("ref")
    @classmethod
    def _ref_is_a_relative_coordinate(cls, value: str) -> str:
        if (
            not value
            or value.startswith(("/", "~"))
            or "://" in value
            or ".." in value
            or re.match(r"^[A-Za-z]:", value)
        ):
            raise ValueError(
                f"evidence ref must be a relative coordinate, got {value!r}"
            )
        return value

    @field_validator("sha256")
    @classmethod
    def _sha256_is_lowercase_hex(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value or ""):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return value


# --- the operator's hard safety budget --------------------------------------------


class RateLimitSafetyBudget(_ClosedContract):
    """The operator-owned ceiling on everything the rate-mapping turn may send.

    Parsed once at the configuration boundary, never repaired silently: an
    invalid or non-positive value stops the boot (`recon.config`). The
    deterministic controller admits each experiment against it atomically and
    can only ever CONSUME it - no model-facing type can carry a number that
    enlarges it (spec, resolved decision 5).

    `max_bypass_variants=0` is legal and is the strictly safer setting: it
    disables mutation probing entirely rather than shrinking it.
    """

    max_requests: int = Field(default=400, gt=0)
    """Total requests the whole rate-mapping turn may send."""

    max_duration_s: float = Field(default=180.0, gt=0)
    """Total offered-traffic duration, in seconds."""

    max_rate_per_s: float = Field(default=20.0, gt=0)
    """The highest offered rate any single experiment may use."""

    max_concurrency: int = Field(default=4, gt=0)
    """The highest worker count any single experiment may use."""

    max_bypass_variants: int = Field(default=4, ge=0)
    """How many bounded bypass variants may be probed at all."""

    allow_identity_mutations: bool = False
    """Whether client-IP/forwarded-header identity mutations may be probed.
    OFF by default; requiring an explicit operator opt-in (spec, resolved
    decision 9)."""

    @model_validator(mode="after")
    def _concurrency_fits_inside_the_request_cap(self):
        if self.max_concurrency > self.max_requests:
            raise ValueError(
                "max_concurrency cannot exceed max_requests: a single "
                "experiment can never need more workers than the whole "
                f"budget allows ({self.max_concurrency} > {self.max_requests})"
            )
        return self


class BudgetUsage(_ClosedContract):
    """What the controller has consumed so far. Monotonic, never negative."""

    requests: int = Field(default=0, ge=0)
    duration_s: float = Field(default=0.0, ge=0)
    variants: int = Field(default=0, ge=0)
    experiments: int = Field(default=0, ge=0)
    max_concurrency: int = Field(default=0, ge=0)


# --- one experiment, as the controller specifies and measures it -------------------


class HeaderMutation(_ClosedContract):
    """A bounded header-family mutation (request-carrier swap, pacing header).
    It can only name one header and one value - never a count, a rate, or a
    budget."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["header"] = "header"
    mutation_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: str
    replace: bool = True
    """True: overwrite the canonical value. False: append (HTTP list semantics)."""


class QueryMutation(_ClosedContract):
    """A bounded query-string mutation: one parameter name, one value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["query"] = "query"
    mutation_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: str
    replace: bool = True
    """True: replace every occurrence of `name`. False: append a second one."""


class PathMutation(_ClosedContract):
    """A bounded path mutation: a suffix appended to the canonical path. It
    cannot carry a scheme or an authority, so it can never change the request's
    origin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["path"] = "path"
    mutation_id: str = Field(min_length=1)
    suffix: str = Field(min_length=1)

    @field_validator("suffix")
    @classmethod
    def _suffix_is_a_path_fragment(cls, value: str) -> str:
        if not value.startswith("/") or "://" in value or ".." in value:
            raise ValueError(
                f"path suffix must be a path fragment starting with '/', got {value!r}"
            )
        return value


class BodyMutation(_ClosedContract):
    """A bounded body-family mutation carrying a REFERENCE to a body artifact -
    never inline content, so a credential-bearing body cannot ride the
    model-facing contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["body"] = "body"
    mutation_id: str = Field(min_length=1)
    body_ref: str = Field(min_length=1)


Mutation = Annotated[
    Union[HeaderMutation, QueryMutation, PathMutation, BodyMutation],
    Field(discriminator="kind"),
]
"""The CLOSED, discriminated union of mutations the controller can materialize.
Its members carry no traffic number: a model-facing mutation can never name a
rate, a duration, a concurrency, or a budget."""


class MutationSpec(_ClosedContract):
    """One bounded bypass variant: an LLM-chosen mutation FROM the closed
    family list, carrying no traffic numbers of its own.

    `identity_mutation` marks the families that change who the target thinks
    is asking (client IP, forwarded-for/identity headers). Those are refused
    unless the operator armed `allow_identity_mutations`.
    """

    variant_id: str
    family: MutationFamily
    description: str = ""
    identity_mutation: bool = False
    payload: Mutation | None = None
    """The typed, closed mutation payload (#238 follow-up, Task 5). `None` means
    the variant changes nothing on the wire, so the controller must never treat
    such a probe as a transported mutation. Replaces the retired generic
    `parameters: dict[str, str]`, which could not guarantee that any mutation
    actually reached the target."""


class ExperimentSpec(_ClosedContract):
    """One admitted experiment: the controller owns every traffic number here.

    `headers` carries the authenticated context the run replays. It is
    SECRET-BEARING transport (private stdin to Kali, redacted at artifact
    persistence) - it must never reach a log line, a prompt, run stats or a
    commit.
    """

    experiment_id: str
    phase: ExperimentPhase
    url: str
    method: str = "GET"
    rate_per_s: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    requests: int = Field(gt=0)
    concurrency: int = Field(default=1, gt=0)
    timeout_s: float = Field(default=30.0, gt=0)
    headers: dict[str, str] = Field(default_factory=dict)
    variant: MutationSpec | None = None
    notes: str = ""


class ExperimentEvidence(_ClosedContract):
    """The measured result of one experiment: aggregates and references.

    Response bodies, raw hit streams and credentials are NOT here - they live
    in the immutable artifact store, addressed by `artifact_ref` and pinned by
    `manifest_sha256` (spec, raw-artifact posture). A `failed` experiment
    carries the typed error and publishes nothing.
    """

    experiment_id: str
    phase: ExperimentPhase
    offered_rate_per_s: float = Field(ge=0)
    requests: int = Field(default=0, ge=0)
    concurrent_workers: int = Field(default=1, ge=1)
    duration_s: float = Field(default=0.0, ge=0)
    status_counts: dict[str, int] = Field(default_factory=dict)
    rejection_ratio: float = Field(default=0.0, ge=0, le=1)
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    burst_accepted: int | None = None
    header_fingerprint: list[str] = Field(default_factory=list)
    body_fingerprint: list[str] = Field(default_factory=list)
    artifact_ref: str | None = None
    manifest_sha256: str | None = None
    measured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    outcome: EvidenceOutcome = "measured"
    error: str | None = None


# --- the enforced output ----------------------------------------------------------


class TrafficPolicy(_ClosedContract):
    """The conservative, enforceable traffic shape for one target.

    This is what the shared per-target egress governor and the Steel pacing
    adapter obey (Tasks 6-7). It carries no evidence and no secrets: only the
    numbers and the key they apply to.
    """

    target_key: str
    host_patterns: list[str] = Field(default_factory=list)
    rate_per_s: float = Field(gt=0)
    burst: int = Field(default=1, gt=0)
    max_concurrency: int = Field(default=1, gt=0)
    min_delay_ms: float = Field(default=0.0, ge=0)
    source: str
    version: str = TRAFFIC_POLICY_VERSION


# --- deterministic classification --------------------------------------------------


class MappedControl(_ClosedContract):
    """The deterministic classification of the mapping evidence: ranges and
    hypotheses, each carrying the experiment IDs that produced it.

    No certainty about implementation is expressible here: `behaviour` is a
    `-like` hypothesis and an unknown limiter is `unknown`.
    """

    outcome: RateOutcome = "inconclusive"
    tested_max_rate_per_s: float | None = None
    threshold_low_per_s: float | None = None
    threshold_high_per_s: float | None = None
    burst_capacity: int | None = None
    recovery_s: float | None = None
    window_sensitivity: bool | None = None
    scope: LimiterScope = "unknown"
    behaviour: EnforcementHypothesis = "unknown"
    fingerprint: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    experiment_ids: list[str] = Field(default_factory=list)
    signals: list[BlockingSignal] = Field(default_factory=list)
    traffic_policy: TrafficPolicy | None = None


class BypassGates(_ClosedContract):
    """The four evidence gates a variant must pass to become `confirmed`
    (spec, bypass evidence gate). All default False: the gates are positive
    evidence, never assumed."""

    canonical_rejected: bool = False
    """1. the canonical request currently triggers the mapped limiter."""

    material_state_change: bool = False
    """2. the variant materially changes limiter state."""

    semantic_equivalence: bool = False
    """3. application semantics remain equivalent."""

    reproduced: bool = False
    """4. the differential repeats independently."""

    @property
    def all_passed(self) -> bool:
        return (
            self.canonical_rejected
            and self.material_state_change
            and self.semantic_equivalence
            and self.reproduced
        )


class BypassFinding(_ClosedContract):
    """One judged bypass hypothesis: the variant, the gates it did or did not
    pass, and the experiment IDs behind it. Evidence only - a confirmed
    finding is never applied to recon traffic (spec, traffic enforcement)."""

    variant: MutationSpec
    outcome: BypassOutcome = "inconclusive"
    gates: BypassGates = Field(default_factory=BypassGates)
    canonical_experiment_id: str | None = None
    variant_experiment_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class TestedBounds(_ClosedContract):
    """The surface actually exercised, so a `no_limiter` outcome is scoped to
    what was tested rather than asserted absolutely."""

    max_requests: int = Field(default=0, ge=0)
    max_duration_s: float = Field(default=0.0, ge=0)
    max_rate_per_s: float = Field(default=0.0, ge=0)
    max_concurrency: int = Field(default=1, ge=1)


# --- the model's second-turn reply -------------------------------------------------


class RateLoopVerdict(_ClosedContract):
    """The rate-limit turn's structured reply: interpretation, nothing more.

    The model may name the variants it believes confirmed and the experiment
    IDs behind them; it can NOT state a rate, a burst, a budget or a policy -
    those fields simply do not exist here, so no prompt injection can enlarge
    the operator's budget or overwrite a measurement. The host accepts a
    claim only when every referenced experiment exists and the evidence gate
    validates it. The default is the honest failure: `inconclusive`.
    """

    outcome: RateOutcome = "inconclusive"
    bypass_outcome: BypassOutcome = "inconclusive"
    confirmed_variant_ids: list[str] = Field(default_factory=list)
    evidence_experiment_ids: list[str] = Field(default_factory=list)
    signals: list[BlockingSignal] = Field(default_factory=list)
    interpretation: str = ""
    rationale: str = ""


# --- the public profile ------------------------------------------------------------


class RateProfile(_ClosedContract):
    """The measured rate profile for one target: the run's stored result and
    the input every later request phase obeys.

    It carries the measurement (bounds, threshold interval, burst, recovery,
    window sensitivity, scope, behavioural hypothesis, fingerprint,
    confidence, timestamps), the operator budget and its consumption, the
    immutable artifact REFERENCES, the bypass outcome and findings, the
    shared blocking signals, and the conservative `TrafficPolicy`.

    `conservative(...)` is the mandated fallback: a failed, timed-out or
    non-replayable mapping yields this profile instead of unthrottled traffic.
    """

    target_key: str
    host_patterns: list[str] = Field(default_factory=list)
    outcome: RateOutcome = "inconclusive"
    version: Literal["rate-profile/v2"] = RATE_PROFILE_VERSION
    safe_rate_per_s: float = Field(gt=0)
    """The controller-derived rate admission gates on. It equals the enforced
    `traffic_policy.rate_per_s` (validated below): mapped posture uses the safe
    tested control, `no_limiter` the maximum actually tested rate, and every
    uncertain/error outcome the conservative fallback. It is NEVER derived from
    LLM prose or bypass status."""
    tested_bounds: TestedBounds | None = None
    threshold_low_per_s: float | None = None
    threshold_high_per_s: float | None = None
    burst_capacity: int | None = None
    recovery_s: float | None = None
    window_sensitivity: bool | None = None
    scope: LimiterScope = "unknown"
    behaviour: EnforcementHypothesis = "unknown"
    fingerprint: list[str] = Field(default_factory=list)
    enforcement: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    measured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime
    budget: RateLimitSafetyBudget = Field(default_factory=RateLimitSafetyBudget)
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    artifact_refs: list[str] = Field(default_factory=list)
    """Legacy untyped artifact coordinates, kept for v1 audit compatibility.
    New runs populate the typed `evidence` tuple; nothing consumes v1 refs as
    governing evidence."""
    evidence: tuple[EvidenceReference, ...] = ()
    """The typed, relative, hashed, capped evidence references (v2)."""
    bypass_outcome: BypassOutcome = "inconclusive"
    bypass_findings: list[BypassFinding] = Field(default_factory=list)
    signals: list[BlockingSignal] = Field(default_factory=list)
    traffic_policy: TrafficPolicy
    reason: str = ""

    @field_validator("measured_at", "expires_at")
    @classmethod
    def _timestamps_are_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("profile timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _safe_rate_matches_the_enforced_policy(self) -> "RateProfile":
        if abs(self.safe_rate_per_s - self.traffic_policy.rate_per_s) > 1e-9:
            raise ValueError(
                "safe_rate_per_s must equal the enforced traffic_policy.rate_per_s "
                f"({self.safe_rate_per_s} != {self.traffic_policy.rate_per_s})"
            )
        return self

    def is_fresh(self, at: datetime) -> bool:
        """Whether the mapping is still valid at `at` (exclusive upper bound:
        `at == expires_at` is stale). Requires a timezone-aware instant."""
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("is_fresh requires a timezone-aware datetime")
        return at < self.expires_at

    @classmethod
    def conservative(
        cls,
        target_key: str,
        host_patterns: list[str],
        budget: RateLimitSafetyBudget,
        reason: str,
        outcome: RateOutcome = "inconclusive",
        *,
        signals: list[BlockingSignal] | None = None,
        ttl_s: float | None = None,
    ) -> "RateProfile":
        """The loud fallback profile: at most one request per second, burst 1,
        one worker, and an inter-action delay that expresses that rate.

        `outcome` says WHY the fallback was taken (`failed` for a
        controller/tool failure, `inconclusive` for insufficient budget or a
        browser-only non-replayable target, `no_limiter` for no transition
        within the tested bounds). Never `mapped`: a fallback is not a
        measurement. `signals` stays empty unless the caller carries
        fingerprint evidence, because the fallback itself is not evidence.
        """
        rate = min(CONSERVATIVE_RATE_PER_S, budget.max_rate_per_s)
        measured_at = datetime.now(timezone.utc)
        return cls(
            target_key=target_key,
            host_patterns=list(host_patterns),
            outcome=outcome,
            budget=budget,
            measured_at=measured_at,
            expires_at=measured_at + timedelta(
                seconds=PROFILE_TTL_DEFAULT_S if ttl_s is None else ttl_s
            ),
            safe_rate_per_s=rate,
            signals=list(signals or ()),
            reason=reason,
            traffic_policy=TrafficPolicy(
                target_key=target_key,
                host_patterns=list(host_patterns),
                rate_per_s=rate,
                burst=1,
                max_concurrency=1,
                min_delay_ms=1000.0 / rate,
                source="conservative-fallback",
            ),
        )


def upgrade_rate_profile_v1(payload: Mapping[str, Any]) -> RateProfile:
    """The ONE compatibility boundary for a persisted `rate-profile/v1` row.

    v1 carried an untyped `artifact_refs` list, no `safe_rate_per_s`, and a
    nullable `expires_at`. This adapter is the only path that accepts such a
    payload - `RateProfile.model_validate` refuses it (its `version` is a closed
    literal). The adapter:

    - bumps the profile version to v2;
    - derives `safe_rate_per_s` from the stored enforced policy (the controller's
      own value, never prose or bypass status);
    - leaves `evidence` empty (v1 refs are unhashed audit data - they are never
      fabricated into typed, hashed references);
    - treats a missing/`None` expiry as immediately stale, so a historical row is
      never reused as a fresh profile for a new run (spec 19).
    """
    data = dict(payload)
    policy_raw = data.get("traffic_policy")
    if not policy_raw:
        raise ValueError("v1 rate profile has no traffic_policy to derive from")
    policy = TrafficPolicy.model_validate(policy_raw)

    measured_at = data.get("measured_at") or datetime.now(timezone.utc)
    data["measured_at"] = measured_at
    # A missing expiry means "not reusable": treat it as stale at measured_at.
    data["expires_at"] = data.get("expires_at") or measured_at
    data.pop("profile_version", None)
    data["version"] = RATE_PROFILE_VERSION
    data.setdefault("safe_rate_per_s", policy.rate_per_s)
    data.setdefault("evidence", ())
    return RateProfile.model_validate(data)


__all__ = [
    "BLOCKING_SIGNALS",
    "BodyMutation",
    "BypassFinding",
    "BypassGates",
    "BypassOutcome",
    "BudgetUsage",
    "CONSERVATIVE_RATE_PER_S",
    "EnforcementHypothesis",
    "EvidenceOutcome",
    "EvidenceReference",
    "ExperimentEvidence",
    "ExperimentPhase",
    "ExperimentSpec",
    "LimiterScope",
    "MappedControl",
    "HeaderMutation",
    "Mutation",
    "MutationFamily",
    "MutationSpec",
    "PathMutation",
    "QueryMutation",
    "MAX_EVIDENCE_REFERENCES",
    "PROFILE_TTL_DEFAULT_S",
    "RATE_PROFILE_VERSION",
    "RateLimitSafetyBudget",
    "RateLoopVerdict",
    "RateOutcome",
    "RateProfile",
    "TRAFFIC_POLICY_VERSION",
    "TestedBounds",
    "TrafficPolicy",
    "upgrade_rate_profile_v1",
]
