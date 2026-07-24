"""Increment-0 message value objects for the analyser control plane (#22).

Three slim, IMMUTABLE value objects carry the supervisor<->agent conversation,
wrapping the existing proposal shapes by COMPOSITION - they never reinvent
`L1DeltaBatch` / `AnatomyResult` / `CurationBatch` (#17):

  AgentDispatch    - supervisor -> proposer (DOWN): the typed work order.
  ProposalEnvelope - the single-step baton across proposer -> auditor -> curator.
  StepReceipt      - curator -> supervisor (UP): the sequenced OUTCOME.

The envelope carries SEPARATE optional cargo fields (never a `Union`) because the
mechanism-typist emits BOTH an `L1DeltaBatch` and an `AnatomyResult` (#17 shape).
In increment 0 every proposer is HOLLOW and yields an empty envelope; the VOs, their
total defaults, and the dispatch invariant are exactly what this increment proves.

LOAD-BEARING (#17): there is no accumulated-proposals channel - the live graph is the
accumulator. The supervisor sequences on the `StepReceipt` OUTCOME, never on the batch.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.anatomy import AnatomyResult
from polymerhus.analysis.curation_types import CurationBatch

# The five DISPATCHABLE proposer roles plus the auditor (the fixed checker stage,
# never dispatched - #17 DP-7: "wrapper-node subgraph for all five proposers").
Role = Literal[
    "bootstrapper", "assigner", "mechanism_typist", "data_modeller", "anti_cluttering", "auditor",
]
Phase = Literal["bootstrap", "A1", "A2"]
Mode = Literal["create", "reflect"]
StepStatus = Literal["written", "empty", "degraded"]

# The roles the supervisor may route a dispatch to (the auditor is excluded - it
# is the fixed pipeline stage after every proposer, not a routing target).
PROPOSER_ROLES: tuple[Role, ...] = (
    "bootstrapper", "assigner", "mechanism_typist", "data_modeller", "anti_cluttering",
)
# Roles that carry NEITHER a chunk nor a sweep_cursor: they re-derive the whole
# live L1 rather than working a bounded slice (#17).
_SLICELESS_ROLES: frozenset[Role] = frozenset({"bootstrapper", "anti_cluttering"})


class Chunk(BaseModel):
    """PLACEHOLDER for the #13 `Chunk` (increment 1 owns `analysis/chunking.py`).

    Increment 0 needs `Chunk` only as the TYPE an `AgentDispatch` may carry, so
    this is a minimal immutable stand-in. #13 replaces it with the real bounded
    L0 slice (nodes/links + batch-overflow cursor); nothing here depends on its
    internals."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str


class SweepCursor(BaseModel):
    """PLACEHOLDER position for the anti-cluttering / A.2 sweep (#11/#13).

    Minimal in increment 0 - the topology needs it only as the alternative to a
    `chunk` on a dispatch."""

    model_config = ConfigDict(frozen=True)

    position: int = 0


class AuditVerdict(BaseModel):
    """One auditor judgment riding the envelope (score-and-annotate, #12). In
    increment 0 the auditor is hollow and emits none; the type exists so the
    envelope's `verdicts` list is well-typed from the first increment. A verdict
    cites a checkable `evidence_ref` (an unchecked LLM is not admitted, AMV-16)."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["accept", "reject", "demand_evidence"]
    reason: str = ""
    evidence_ref: str | None = None


class WriteCounts(BaseModel):
    """What a `StepReceipt` reports the curator wrote (idempotent-MERGE counts).
    All-zero is the increment-0 hollow default (nothing is written)."""

    model_config = ConfigDict(frozen=True)

    services: int = 0
    systems: int = 0
    aggregates: int = 0
    enrichment: int = 0


class SteeringState(BaseModel):
    """Cross-run steering carried on the supervisor state (#17 refines T2's queued
    'steering state'). Inert in increment 0 - carried, never acted on."""

    model_config = ConfigDict(frozen=True)

    gaps: list[str] = Field(default_factory=list)
    granularity: list[str] = Field(default_factory=list)


class AgentDispatch(BaseModel):
    """Supervisor -> proposer work order (DOWN). Carries the (chunk, role) pair
    (#13) plus the phase/mode axes (T2: schedule-stage vs operating-mode).

    Invariant (#17): EXACTLY ONE of `chunk` / `sweep_cursor` is set, EXCEPT the
    slice-less roles (bootstrapper + anti_cluttering) which set NEITHER - they
    re-derive the whole live L1. Never both."""

    model_config = ConfigDict(frozen=True)

    dispatch_id: str
    role: Role
    phase: Phase
    mode: Mode = "create"
    chunk: Chunk | None = None
    sweep_cursor: SweepCursor | None = None

    @model_validator(mode="after")
    def _one_or_neither(self) -> "AgentDispatch":
        has_chunk = self.chunk is not None
        has_cursor = self.sweep_cursor is not None
        if has_chunk and has_cursor:
            raise ValueError(
                "AgentDispatch carries at most one of chunk/sweep_cursor, never both"
            )
        if self.role in _SLICELESS_ROLES:
            if has_chunk or has_cursor:
                raise ValueError(
                    f"slice-less role {self.role!r} sets neither chunk nor sweep_cursor"
                )
        elif not (has_chunk or has_cursor):
            raise ValueError(
                f"role {self.role!r} requires exactly one of chunk/sweep_cursor"
            )
        return self


class ProposalEnvelope(BaseModel):
    """The single-step baton across proposer -> auditor -> curator.

    SEPARATE optional cargo (never a `Union`) because the mechanism-typist emits
    BOTH `deltas` and `anatomy`. The `AuditVerdict` trail rides this same baton
    (score-and-annotate, blocks nothing in v1). Increment 0: every proposer yields
    this with all cargo `None`, `verdicts == []`, and `status == "empty"`."""

    model_config = ConfigDict(frozen=True)

    dispatch_id: str
    role: Role
    phase: Phase
    deltas: L1DeltaBatch | None = None
    anatomy: AnatomyResult | None = None
    curation: CurationBatch | None = None
    verdicts: list[AuditVerdict] = Field(default_factory=list)
    status: StepStatus = "empty"
    error: str | None = None


class StepReceipt(BaseModel):
    """Curator -> supervisor OUTCOME (UP). The supervisor sequences on THIS, never
    on the (already written + discarded) batch. `surfaced` carries the gaps /
    granularity the step observed (inert in increment 0)."""

    model_config = ConfigDict(frozen=True)

    dispatch_id: str
    role: Role
    phase: Phase
    status: StepStatus = "empty"
    written: WriteCounts = Field(default_factory=WriteCounts)
    surfaced: dict = Field(default_factory=dict)
    error: str | None = None
