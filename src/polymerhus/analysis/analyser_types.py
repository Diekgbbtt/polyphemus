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
here from the LLM's `evidence_refs` plus system provenance.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
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
    L0 element `l0`, with the analyser's `evidence_refs` as the grounding anchor.
    The MVP commits every structurally-valid assignment (status='committed'); the
    envelope's provenance is injected by the curate boundary, not the LLM.

    The `confidence` score was removed with the withholding gate: admit-all writes
    every structurally-valid aggregate
    (`docs/design/drop-aggregate-confidence.md`), so a gradable field has no
    consumer left."""

    service_slug: str
    l0: L0Ref
    evidence_refs: list[str] = Field(default_factory=list)


# --- FR-ENRICH LLM-facing proposals (no provenance; system-stamped at curate) --

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
    enrichment list (`system_edges`) lets one analyser pass propose the
    Service->System edges alongside the assignment."""

    services: list[ServiceProposal] = Field(default_factory=list)
    systems: list[SystemProposal] = Field(default_factory=list)
    aggregates: list[AggregatesProposal] = Field(default_factory=list)
    system_edges: list[SystemEdgeProposal] = Field(default_factory=list)


def proposals_to_deltas(
    batch: L1DeltaBatch, provenance: Provenance
) -> tuple[list[ServiceDelta], list[SystemDelta], list[AggregatesDelta]]:
    """Map LLM proposals to the curator's provenance-carrying deltas, stamping
    the system-supplied `provenance` (the LLM never sets it). The judgment
    envelope is built here: MVP writes status='committed' (L1R-4) while always
    carrying the LLM's evidence_refs."""
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
        "system_edges": [
            SystemEdgeDelta(
                service_slug=e.service_slug, kind=e.kind,
                discriminator=e.discriminator, rel=e.rel, role=e.role, realm=e.realm,
                order=e.order, provenance=provenance,
            )
            for e in batch.system_edges
        ],
    }
