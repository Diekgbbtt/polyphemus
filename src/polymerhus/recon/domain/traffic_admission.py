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
from enum import StrEnum
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, PositiveInt, field_validator


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
