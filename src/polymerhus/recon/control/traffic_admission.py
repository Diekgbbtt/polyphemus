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
from typing import Literal

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.domain.rate_limit import RateOutcome, TrafficPolicy
from polymerhus.recon.domain.traffic_admission import (
    JobAdmissionDecision,
    TrafficAdmissionSettings,
)

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
    refusals: tuple[str, ...]
