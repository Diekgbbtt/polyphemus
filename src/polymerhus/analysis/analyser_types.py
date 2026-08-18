"""LLM-facing proposal models for the analyser (the `_L1DeltaBatch` structured
output) + their mapping to the curator's provenance-carrying deltas.

The analyser LLM emits *proposals* — its adversarial judgment about which
Services/Systems exist and which L0 elements a Service aggregates — but it must
NOT set provenance or status: those are system-controlled (who/what produced the
write), exactly as `l1_curator` strips reserved props so an LLM cannot spoof
identity/provenance. So the proposal models deliberately omit `provenance`, and
`proposals_to_deltas` injects it from the run context at the curate boundary.

This keeps the analyser a pure `f(L0-slice + observations) -> L1-deltas` whose
writes are idempotent MERGEs (L1D-22), with the judgment envelope (L1D-25) built
here from the LLM's `confidence`/`evidence_refs` plus system provenance.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from typing import Literal

from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
    AggregatesDelta,
    DataFlowDelta,
    DataItemDelta,
    DataRelationshipDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
    SurfacesAtDelta,
    SystemDelta,
    SystemEdgeDelta,
)


class ServiceProposal(BaseModel):
    """A business-function Service the analyser judges to exist (L1D-4)."""

    business_function_slug: str
    props: dict = Field(default_factory=dict)


class SystemProposal(BaseModel):
    """A cross-cutting System the analyser judges to exist (L1D-4). `kind` must be
    a known system kind (the curator rejects kinds outside `SYSTEM_KINDS`)."""

    kind: str
    discriminator: str = L1_SINGLETON
    props: dict = Field(default_factory=dict)


class AggregatesProposal(BaseModel):
    """One assignment judgment (L1D-25): the Service `service_slug` aggregates the
    L0 element `l0`, with the analyser's `confidence` and `evidence_refs`. The MVP
    commits every assignment (status='committed'); the envelope's provenance is
    injected by the curate boundary, not the LLM."""

    service_slug: str
    l0: L0Ref
    confidence: float = 0.0
    evidence_refs: list[str] = Field(default_factory=list)


# --- FR-ENRICH LLM-facing proposals (no provenance; system-stamped at curate) --

class DataItemProposal(BaseModel):
    """A logical DataItem the analyser lifts (L1D-13). `item_key` is the flexible
    semantic key; the analyser gives the same key to sites it judges one item."""

    item_key: str
    props: dict = Field(default_factory=dict)


class SurfacesAtProposal(BaseModel):
    """Where a DataItem appears on the L0 surface (cross-layer SURFACES_AT)."""

    item_key: str
    l0: L0Ref


class DataFlowProposal(BaseModel):
    """A Service PRODUCES/CONSUMES a DataItem; a CONSUMES may carry a trust
    assumption predicate + rationale (L1D-14)."""

    service_slug: str
    item_key: str
    direction: Literal["produces", "consumes"]
    assumption: str | None = None
    assumption_rationale: str | None = None


class DataRelationshipProposal(BaseModel):
    """A functional-dependency relationship between two DataItems; `kind` is one of
    the fixed allowlist (it becomes the edge type), carrying a predicate + NL."""

    from_item_key: str
    to_item_key: str
    kind: str
    predicate: str | None = None
    rationale: str | None = None


class SystemEdgeProposal(BaseModel):
    """A typed Service->System edge (systems are edges, not strings, L1D-18)."""

    service_slug: str
    kind: str
    discriminator: str = L1_SINGLETON
    rel: str
    role: str | None = None
    realm: str | None = None
    order: int | None = None


class L1DeltaBatch(BaseModel):
    """The analyser LLM's structured output: the L1 deltas it proposes from an
    L0 slice + observations. Every list defaults empty so a 'nothing to add'
    judgment is a valid, well-typed result (mirrors `_ObservationBatch`). The
    enrichment lists (data_items … system_edges) let one analyser pass propose
    the Tier-1 trust substrate alongside the assignment."""

    services: list[ServiceProposal] = Field(default_factory=list)
    systems: list[SystemProposal] = Field(default_factory=list)
    aggregates: list[AggregatesProposal] = Field(default_factory=list)
    data_items: list[DataItemProposal] = Field(default_factory=list)
    surfaces_at: list[SurfacesAtProposal] = Field(default_factory=list)
    data_flows: list[DataFlowProposal] = Field(default_factory=list)
    data_relationships: list[DataRelationshipProposal] = Field(default_factory=list)
    system_edges: list[SystemEdgeProposal] = Field(default_factory=list)


def proposals_to_deltas(
    batch: L1DeltaBatch, provenance: Provenance
) -> tuple[list[ServiceDelta], list[SystemDelta], list[AggregatesDelta]]:
    """Map LLM proposals to the curator's provenance-carrying deltas, stamping
    the system-supplied `provenance` (the LLM never sets it). The judgment
    envelope is built here: MVP writes status='committed' (L1R-4) while always
    carrying the LLM's confidence + evidence_refs."""
    services = [
        ServiceDelta(business_function_slug=s.business_function_slug, props=s.props, provenance=provenance)
        for s in batch.services
    ]
    systems = [
        SystemDelta(kind=s.kind, discriminator=s.discriminator, props=s.props, provenance=provenance)
        for s in batch.systems
    ]
    aggregates = [
        AggregatesDelta(
            service_slug=a.service_slug,
            l0=a.l0,
            envelope=JudgmentEnvelope(
                confidence=a.confidence,
                status="committed",
                evidence_refs=a.evidence_refs,
                provenance=provenance,
            ),
        )
        for a in batch.aggregates
    ]
    return services, systems, aggregates


def enrichment_proposals_to_deltas(batch: L1DeltaBatch, provenance: Provenance) -> dict:
    """Map the FR-ENRICH proposals to their provenance-carrying deltas, keyed to
    match `l1_curator.enrich`'s kwargs. Provenance is system-supplied (the LLM
    never sets it), exactly as `proposals_to_deltas` does for the core deltas."""
    return {
        "data_items": [
            DataItemDelta(item_key=d.item_key, props=d.props, provenance=provenance)
            for d in batch.data_items
        ],
        "surfaces_at": [
            SurfacesAtDelta(item_key=s.item_key, l0=s.l0, provenance=provenance)
            for s in batch.surfaces_at
        ],
        "data_flows": [
            DataFlowDelta(
                service_slug=f.service_slug, item_key=f.item_key, direction=f.direction,
                assumption=f.assumption, assumption_rationale=f.assumption_rationale,
                provenance=provenance,
            )
            for f in batch.data_flows
        ],
        "data_relationships": [
            DataRelationshipDelta(
                from_item_key=r.from_item_key, to_item_key=r.to_item_key, kind=r.kind,
                predicate=r.predicate, rationale=r.rationale, provenance=provenance,
            )
            for r in batch.data_relationships
        ],
        "system_edges": [
            SystemEdgeDelta(
                service_slug=e.service_slug, kind=e.kind,
                discriminator=e.discriminator, rel=e.rel, role=e.role, realm=e.realm,
                order=e.order, provenance=provenance,
            )
            for e in batch.system_edges
        ],
    }
