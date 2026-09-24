# src/polymerhus/recon/control/traffic_admission.py
"""The #238 follow-up control layer: the immutable traffic-admission envelope
persisted under `recon_runs.stats["traffic_admission"]`.

This is deliberately a SEPARATE envelope from `stats["rate_limit"]` (spec 1.6 /
Task-2 acceptance): the detected posture and the downstream decision that used
it must be distinguishable. The envelope is additive JSONB, so it needs no SQL
migration and survives a rollback.

Task 2 defines only the closed contract here; Task 4 adds the canonical input
preparation, cost estimation, phase pruning, decision assembly, and the
persistence adapter that fills it in.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.domain.rate_limit import RateOutcome, TrafficPolicy
from polymerhus.recon.domain.traffic_admission import (
    AdmissionContext,
    AdmissionDisposition,
    JobAdmissionDecision,
    TrafficAdmissionSettings,
    TrafficCostClass,
    TrafficRefusal,
    decide_job_admission,
)
from polymerhus.recon.domain.types import JobSpec

TRAFFIC_ADMISSION_VERSION = "traffic-admission/v1"
"""The stored version of the admission envelope (spec 12.2)."""


class TrafficAdmissionEnvelope(BaseModel):
    """One run's immutable admission record, persisted before each phase
    dispatch. Every field is secret-safe: the decisions carry counts, rates, and
    reason codes only, and the effective policy carries no evidence or
    credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["traffic-admission/v1"] = TRAFFIC_ADMISSION_VERSION
    profile_version: str
    profile_outcome: RateOutcome
    measured_at: datetime
    expires_at: datetime
    effective_policy: TrafficPolicy | None
    candidate_phases: tuple[tuple[str, ...], ...]
    materialized_phases: tuple[tuple[str, ...], ...]
    decisions: tuple[JobAdmissionDecision, ...]
    effective_config: TrafficAdmissionSettings
    event_order: tuple[str, ...]
    warnings: tuple[str, ...]
    refusals: tuple[TrafficRefusal, ...]
    """Runtime refusals recorded AFTER the pre-run persist (a governed flow the
    proxy refused locally). Appending one never rewrites the original admission
    decisions."""


def estimate_job_requests(
    job: JobSpec,
    prepared_pod_inputs: Sequence[dict],
    *,
    cardinalities: Mapping[str, int] | None = None,
) -> int:
    """The controller-owned request estimate for one job at one phase.

    A `non_target` job sends nothing to the measured target, so its estimate is
    0. Every other job uses its declared `estimated_requests_per_input`; a
    `cardinalities` entry keyed by the job's `cardinality_source` OVERRIDES it
    with the value verified against the image (Task 7). When that map supplies an
    entry for the source it is authoritative - a non-positive override yields 0,
    which the decision function records as `cost_model_invalid` rather than
    silently underestimating.
    """
    cost = job.traffic_cost
    if cost.cost_class is TrafficCostClass.NON_TARGET:
        return 0
    per_input = int(cost.estimated_requests_per_input)
    if cost.estimation_basis == "wordlist_cardinality" and cost.cardinality_source:
        override = (cardinalities or {}).get(cost.cardinality_source)
        if override is not None:
            per_input = int(override)
    return len(prepared_pod_inputs) * per_input


def admission_context_for(profile, now: datetime) -> AdmissionContext:
    """Build the pure decision's context from the resolved `RateProfile` and an
    injected UTC instant. Freshness is evaluated HERE, at the admission
    chokepoint - a profile fresh during mapping but expired by materialization is
    stale (spec 7, step 4)."""
    policy = profile.traffic_policy
    return AdmissionContext(
        profile_status=profile.outcome,
        safe_rate_per_s=None if policy is None else profile.safe_rate_per_s,
        profile_fresh=profile.is_fresh(now),
        policy_present=policy is not None,
        evaluated_at=now,
    )


def materialize_admitted_phase(
    phase: int,
    candidate_names: Sequence[str],
    prepared_by_job: Mapping[str, Sequence[dict]],
    profile,
    settings: TrafficAdmissionSettings,
    now: datetime,
    *,
    cardinalities: Mapping[str, int] | None = None,
    registry_lookup=None,
) -> tuple[list[str], tuple[JobAdmissionDecision, ...]]:
    """Decide one phase's candidate jobs and return the MATERIALIZED subset plus
    the decisions.

    Pure with respect to the plan: the materialized list is the intersection of
    the static candidate list and the admitted decisions. No model output enters
    here - `candidate_names` is the controller's own static candidate set, and the
    only inputs are the job's typed cost and the caller-derived context.
    """
    if registry_lookup is None:
        from polymerhus.recon.control.jobs import JOBS  # noqa: PLC0415

        registry_lookup = JOBS

    context = admission_context_for(profile, now)
    admitted: list[str] = []
    decisions: list[JobAdmissionDecision] = []
    for name in candidate_names:
        job = registry_lookup[name]
        prepared = prepared_by_job.get(name, ())
        estimated = estimate_job_requests(
            job, prepared, cardinalities=cardinalities
        )
        decision = decide_job_admission(
            phase, job, len(prepared), context, settings,
            estimated_requests=estimated,
        )
        decisions.append(decision)
        if decision.decision is AdmissionDisposition.INCLUDED:
            admitted.append(name)
    return admitted, tuple(decisions)


def build_admission_envelope(
    *,
    profile,
    settings: TrafficAdmissionSettings,
    candidate_phases: Sequence[Sequence[str]],
    materialized_phases: Sequence[Sequence[str]],
    decisions: Sequence[JobAdmissionDecision],
    event_order: Sequence[str],
    warnings: Sequence[str] = (),
    refusals: Sequence[TrafficRefusal] = (),
) -> TrafficAdmissionEnvelope:
    """Assemble one run's immutable admission envelope from the accumulated
    per-phase records."""
    return TrafficAdmissionEnvelope(
        profile_version=profile.version,
        profile_outcome=profile.outcome,
        measured_at=profile.measured_at,
        expires_at=profile.expires_at,
        effective_policy=profile.traffic_policy,
        candidate_phases=tuple(tuple(group) for group in candidate_phases),
        materialized_phases=tuple(tuple(group) for group in materialized_phases),
        decisions=tuple(decisions),
        effective_config=settings,
        event_order=tuple(event_order),
        warnings=tuple(warnings),
        refusals=tuple(refusals),
    )


def persist_admission_envelope(registry, run_id: str, envelope) -> None:
    """Persist the admission envelope through the EXISTING additive
    `recon_runs.stats` seam, under its OWN key so it can never clobber
    `stats["rate_limit"]` (spec 12.2). Raises on a registry without the seam or
    a failing write - the pipeline turns that into a pre-run failure, because the
    executed configuration must never be unobservable."""
    write_stats = getattr(registry, "set_run_stats", None)
    if write_stats is None:
        raise RuntimeError("registry exposes no set_run_stats for traffic_admission")
    write_stats(run_id, {"traffic_admission": envelope.model_dump(mode="json")})
