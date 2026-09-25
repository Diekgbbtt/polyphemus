# src/polymerhus/recon/domain/traffic_admission.py
"""The #238 follow-up domain: the CLOSED traffic-cost vocabulary every canonical
`JobSpec` must declare, and the operator's admission configuration.

Two design facts are encoded here as types, not conventions
(`docs/superpowers/specs/2026-09-24-rate-limit-job-admission-e2e-design.md`
sections 5-6):

- Every job's relationship to the measured target is an explicit, closed
  `JobTrafficCost`. There is NO permissive default: a job that does not
  declare its traffic relationship cannot be constructed, so a new or renamed
  request-intensive job can never escape admission by omission (spec 4.2).
- The admission thresholds are one typed value object parsed once at the
  configuration boundary. Zero, negative, non-numeric, `NaN`, or infinite
  values fail loudly rather than being silently repaired - a silently-loosened
  safety threshold is exactly the failure this module exists to prevent.

This module is pure: no I/O, no collaborator construction, no config read at
import (CODING_STANDARD sections 3 and 6). `from_env` reads its environment
inside the call, at the boundary, never at import.
"""
from __future__ import annotations

import math
import os
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Mapping

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
)

from polymerhus.recon.domain.rate_limit import RateOutcome

if TYPE_CHECKING:  # avoid a cycle: types.py imports this module
    from polymerhus.recon.domain.types import JobSpec


class TrafficCostClass(StrEnum):
    """A canonical job's relationship to the MEASURED target's traffic.

    `non_target` sends no HTTP requests to the measured target; `bounded_http`
    sends target HTTP but is tightly bounded and allowed under a conservative
    policy; `request_intensive` must pass the posture, minimum-rate, and
    projected-duration gates before it may run at all.
    """

    NON_TARGET = "non_target"
    BOUNDED_HTTP = "bounded_http"
    REQUEST_INTENSIVE = "request_intensive"


class JobTrafficCost(BaseModel):
    """The mandatory, frozen traffic-cost declaration on every `JobSpec`.

    `estimated_requests_per_input` is a controller-owned estimate, never a
    model-facing number. `estimation_basis` names HOW the estimate was derived:
    `fixed` for a measured constant, `wordlist_cardinality` for the cardinality
    of the wordlist the job actually pins (resolved through `cardinality_source`
    against the image; Task 7 verifies it).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cost_class: TrafficCostClass
    estimated_requests_per_input: PositiveInt
    estimation_basis: Literal["fixed", "wordlist_cardinality"]
    cardinality_source: str | None = None


# The two shared, frozen declarations for the common shapes. Referenced (not
# duplicated) by the canonical registry and by focused fixtures, so the shape
# has one definition (CODING_STANDARD section 8).
NON_TARGET_COST = JobTrafficCost(
    cost_class=TrafficCostClass.NON_TARGET,
    # Inert sentinel: a non_target job sends no HTTP to the measured target, so
    # this estimate is never read by admission. PositiveInt demands a minimum of
    # 1; 1 is the honest "at most one logical unit of work" declaration.
    estimated_requests_per_input=1,
    estimation_basis="fixed",
)
"""A job that sends no HTTP requests to the measured target."""

BOUNDED_HTTP_COST = JobTrafficCost(
    cost_class=TrafficCostClass.BOUNDED_HTTP,
    # A bounded HTTP job's work is tightly bounded (one/few requests per input),
    # so the estimate is 1 per input; it runs only under a conservative policy.
    estimated_requests_per_input=1,
    estimation_basis="fixed",
)
"""A tightly-bounded target HTTP job, admissible under a conservative policy."""


# --- admission configuration -------------------------------------------------

DEFAULT_MIN_SAFE_RATE_PER_S = 2.0
"""The lowest safe rate at which a request-intensive job may run. Grounded in
the arjun template contract: ~260 requests/input at 1 rps would nearly consume
`EXEC_TIMEOUT_S=300` alone; 2 rps is the lower bound the template already
justifies (spec 6)."""

DEFAULT_MAX_PROJECTED_DURATION_S = 300.0
"""The longest projected duration a request-intensive job may have. Equal to
the current `EXEC_TIMEOUT_S`, so it is the existing execution boundary rather
than a new, unrelated duration (spec 6)."""

MIN_SAFE_RATE_ENV = "RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S"
MAX_PROJECTED_DURATION_ENV = "RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S"


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    """One strictly-positive, finite float knob. A missing value uses the
    default; a non-numeric, non-finite, zero, or negative value raises
    `ValueError` naming the exact variable, so the boot fails loudly."""
    raw = env.get(name, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite value > 0, got {raw!r}")
    return value


class TrafficAdmissionSettings(BaseModel):
    """The run's effective admission thresholds, parsed once at the
    configuration boundary and persisted with every run (spec 6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_safe_rate_per_s: float
    max_projected_duration_s: float

    @field_validator("min_safe_rate_per_s", "max_projected_duration_s")
    @classmethod
    def _finite_positive(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("must be a finite value > 0")
        return value

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "TrafficAdmissionSettings":
        """Parse the two thresholds from the environment (or a supplied
        mapping). Missing values use the documented defaults; anything invalid
        raises `ValueError` before a run can start."""
        source = os.environ if env is None else env
        return cls(
            min_safe_rate_per_s=_positive_float(
                source, MIN_SAFE_RATE_ENV, DEFAULT_MIN_SAFE_RATE_PER_S
            ),
            max_projected_duration_s=_positive_float(
                source, MAX_PROJECTED_DURATION_ENV, DEFAULT_MAX_PROJECTED_DURATION_S
            ),
        )


# --- the pure admission decision ---------------------------------------------


class AdmissionReason(StrEnum):
    """The CLOSED reason vocabulary for one job's admission decision (spec
    section 12.2). Every inclusion and exclusion is attributable to exactly one
    of these; a free-text reason is not expressible."""

    ADMITTED = "admitted"
    NO_INPUTS = "no_inputs"
    PROFILE_INCONCLUSIVE = "profile_inconclusive"
    PROFILE_FAILED = "profile_failed"
    PROFILE_STALE = "profile_stale"
    BELOW_MIN_SAFE_RATE = "below_min_safe_rate"
    PROJECTED_DURATION_EXCEEDED = "projected_duration_exceeded"
    COST_MODEL_INVALID = "cost_model_invalid"
    POLICY_MISSING = "policy_missing"
    GOVERNOR_REFUSED = "governor_refused"


class AdmissionDisposition(StrEnum):
    """Whether a candidate job is materialized (`included`) or pruned
    (`excluded`) at the phase boundary."""

    INCLUDED = "included"
    EXCLUDED = "excluded"


class AdmissionContext(BaseModel):
    """The controller-derived facts the pure decision reads.

    Every field is computed by the deterministic caller (the effective profile
    and its freshness resolved with an injected UTC clock). There is deliberately
    NO bypass field: a bypass is evidence only and cannot reach this type, so it
    can never change an admission decision.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_status: RateOutcome
    safe_rate_per_s: float | None = None
    profile_fresh: bool
    policy_present: bool
    evaluated_at: datetime


class JobAdmissionDecision(BaseModel):
    """One job's persisted inclusion/exclusion, secret-safe by construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: int
    job: str = Field(validation_alias=AliasChoices("job", "job_name"))
    """The job's tool name. Serialized as `job` so the persisted decisions read
    the same key the public recon-jobs API uses; the legacy `job_name` is still
    accepted on input for already-stored envelopes."""
    cost_class: TrafficCostClass
    input_count: int
    estimated_requests: int
    safe_rate_per_s: float | None
    projected_duration_s: float
    decision: AdmissionDisposition
    reason_code: AdmissionReason

    @property
    def job_name(self) -> str:
        """Backwards-compatible accessor for the legacy field name."""
        return self.job


def _resolve_estimate(
    cost: JobTrafficCost, input_count: int, override: int | None
) -> int:
    """The controller-owned request estimate for one job at one phase. An
    explicit `override` (a verified wordlist cardinality, Task 7) wins; else the
    job's declared per-input estimate times its derived input count."""
    if override is not None:
        return override
    return input_count * int(cost.estimated_requests_per_input)


def decide_job_admission(
    phase: int,
    job: "JobSpec",
    input_count: int,
    context: AdmissionContext,
    settings: TrafficAdmissionSettings,
    estimated_requests: int | None = None,
) -> JobAdmissionDecision:
    """Decide one job's admission at the current phase boundary.

    Pure and total over every supported profile outcome: it reads only the
    job's mandatory `traffic_cost`, the caller-derived `AdmissionContext`, and
    the parsed `TrafficAdmissionSettings`. No I/O, no clock, no model, no
    bypass. Order is deterministic:

    1. an empty consumption set is recorded as `no_inputs` (nothing to run);
    2. `non_target` runs without a target traffic policy;
    3. every other class requires a policy; an invalid estimate is
       `cost_model_invalid`;
    4. `bounded_http` then runs under whatever policy is present;
    5. `request_intensive` must be fresh, `mapped`/`no_limiter`, and clear both
       inclusive numeric gates (`safe_rate_per_s >= min` and
       `projected_duration_s <= max`).
    """
    if input_count < 0:
        raise ValueError(f"input_count must be >= 0, got {input_count!r}")

    cost = job.traffic_cost

    def record(
        include: bool,
        reason: AdmissionReason,
        *,
        estimated: int,
        duration: float,
        safe_rate: float | None = context.safe_rate_per_s,
    ) -> JobAdmissionDecision:
        return JobAdmissionDecision(
            phase=phase,
            job=job.tool,
            cost_class=cost.cost_class,
            input_count=input_count,
            estimated_requests=estimated,
            safe_rate_per_s=safe_rate,
            projected_duration_s=duration,
            decision=(
                AdmissionDisposition.INCLUDED
                if include
                else AdmissionDisposition.EXCLUDED
            ),
            reason_code=reason,
        )

    if input_count == 0:
        return record(
            False, AdmissionReason.NO_INPUTS, estimated=0, duration=0.0
        )

    if cost.cost_class is TrafficCostClass.NON_TARGET:
        # No HTTP to the measured target: admitted without a traffic policy.
        return record(True, AdmissionReason.ADMITTED, estimated=0, duration=0.0)

    estimate = _resolve_estimate(cost, input_count, estimated_requests)
    if estimate <= 0:
        return record(
            False, AdmissionReason.COST_MODEL_INVALID, estimated=0, duration=0.0
        )

    if not context.policy_present:
        return record(
            False, AdmissionReason.POLICY_MISSING, estimated=estimate, duration=0.0
        )

    if cost.cost_class is TrafficCostClass.BOUNDED_HTTP:
        # Tightly bounded work runs under the conservative policy.
        return record(True, AdmissionReason.ADMITTED, estimated=estimate, duration=0.0)

    # request_intensive: freshness and posture first, then the numeric gates.
    if not context.profile_fresh:
        return record(
            False, AdmissionReason.PROFILE_STALE, estimated=estimate, duration=0.0
        )
    if context.profile_status == "failed":
        return record(
            False, AdmissionReason.PROFILE_FAILED, estimated=estimate, duration=0.0
        )
    if context.profile_status == "inconclusive":
        return record(
            False,
            AdmissionReason.PROFILE_INCONCLUSIVE,
            estimated=estimate,
            duration=0.0,
        )

    safe_rate = context.safe_rate_per_s
    if safe_rate is None or safe_rate <= 0:
        return record(
            False, AdmissionReason.POLICY_MISSING, estimated=estimate, duration=0.0
        )

    projected_duration_s = estimate / safe_rate
    if safe_rate < settings.min_safe_rate_per_s:
        return record(
            False,
            AdmissionReason.BELOW_MIN_SAFE_RATE,
            estimated=estimate,
            duration=projected_duration_s,
            safe_rate=safe_rate,
        )
    if projected_duration_s > settings.max_projected_duration_s:
        return record(
            False,
            AdmissionReason.PROJECTED_DURATION_EXCEEDED,
            estimated=estimate,
            duration=projected_duration_s,
            safe_rate=safe_rate,
        )
    return record(
        True,
        AdmissionReason.ADMITTED,
        estimated=estimate,
        duration=projected_duration_s,
        safe_rate=safe_rate,
    )


TRAFFIC_REFUSAL_RETURNCODE = 78
"""The exec seam's stable return code for "an armed TrafficPolicy could not be
enforced". Mirrors `kali.http_history.service.TRAFFIC_REFUSAL_RETURNCODE` BY
VALUE: the recon domain cannot import the Kali service, and a drift here would
make a refusal look like a tool failure."""


class TrafficRefusal(BaseModel):
    """One runtime refusal to egress, secret-safe by construction: a closed reason
    code, the target key, and the policy version. It never carries a URL query, a
    header value, a body, or a credential - the pipeline appends it to the
    admission envelope's `refusals` without rewriting the original decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason_code: AdmissionReason
    target_key: str = ""
    policy_version: str = ""
