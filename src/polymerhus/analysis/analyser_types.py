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

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
    SystemDelta,
    SystemEdgeDelta,
    SystemEvidenceDelta,
)


class ServiceProposal(BaseModel):
    """A business-function Service the analyser judges to exist (L1D-4)."""

    business_function_slug: str
    props: dict = Field(default_factory=dict)


class SystemProposal(BaseModel):
    """A cross-cutting System the analyser judges to exist (L1D-4). `kind` must be
    a known system kind (the curator rejects kinds outside `SYSTEM_KINDS`).

    `evidence` carries the System's WITNESSES (ticket #354): the L0 nodes whose
    observation grounds the claim, each addressed by the domain's own L0 reference
    (`L0Ref`: label + the L0 node's identity keys). The sole-writer MATCHes each one
    and MERGEs an `EVIDENCED_BY` edge; a witness the graph does not hold produces no
    edge, and a claim with no witness stays an edgeless (but written) System."""

    kind: str
    discriminator: str = L1_SINGLETON
    props: dict = Field(default_factory=dict)
    evidence: list[L0Ref] = Field(default_factory=list)


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


# --- the assigner's model-facing component contract ---------------------------
#
# The assigner used to emit the shared `L1DeltaBatch` union. That union exposes
# four writable lists and the prompt tells each role to fill a different subset,
# so the model saw a contract larger than its job. Iteration E turned that gap
# into a malformed tool call that LiteLLM could not parse, and the whole chunk's
# judgments vanished. The component schema below states exactly one primitive:
# a Service owning a group of Endpoints. The internal curator still consumes
# `L1DeltaBatch`; `assigner_delta_to_batch` expands the groups at the seam.


class EndpointRef(BaseModel):
    """The L0 Endpoint identity an aggregation names."""

    method: str = Field(description="HTTP method, for example GET or POST.")
    path: str = Field(description="L0 path, for example /admin/index/index.")
    baseurl: str = Field(description="L0 base URL, for example http://target.")


class Aggregation(BaseModel):
    """One Service's ownership of a group of Endpoints."""

    service: str = Field(
        description="The exact business_function_slug of the Service that owns "
                    "these endpoints. Copy a slug from the inventory."
    )
    endpoints: list[EndpointRef] = Field(
        description="The L0 endpoints this Service aggregates."
    )
    evidence: str = Field(
        default="",
        description="One short sentence naming the path segment or parameter "
                    "that supports the ownership. Omit the aggregation when you "
                    "cannot cite evidence. Never write a placeholder object."
    )


class AssignerDelta(BaseModel):
    """The assigner's complete answer: one group per owning Service."""

    aggregations: list[Aggregation] = Field(
        description="One group per Service. The writer expands each group to one "
                    "AGGREGATES edge per endpoint."
    )


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


# --- the mechanism typist's model-facing component contracts -----------------
#
# The typist used to emit the same shared `L1DeltaBatch` union as the assigner.
# Its two structured turns each own one primitive: the extraction turn owns
# Systems and their witnesses; the linking turn owns the typed Service->System
# links. The component schemas state exactly that, and the prompts no longer
# tell the model to leave fields empty. The internal curator still consumes
# `L1DeltaBatch`; the mappings below build it at the seam.


class EndpointWitness(BaseModel):
    """An L0 Endpoint that witnesses a System."""

    method: str = Field(description="HTTP method.")
    path: str = Field(description="L0 path.")
    baseurl: str = Field(description="L0 base URL.")

    model_config = ConfigDict(extra="forbid")


class HeaderWitness(BaseModel):
    """An L0 Header that witnesses a System."""

    name: str = Field(description="Header name.")
    endpoint: str = Field(description="The endpoint path the header was seen on.")
    baseurl: str = Field(description="L0 base URL.")

    model_config = ConfigDict(extra="forbid")


class TechnologyWitness(BaseModel):
    """An L0 Technology that witnesses a System."""

    name: str = Field(description="Technology name.")
    version: str = Field(default="", description="Observed version, or empty.")

    model_config = ConfigDict(extra="forbid")


class CertificateWitness(BaseModel):
    """An L0 Certificate that witnesses a System."""

    subject_cn: str = Field(description="Certificate subject common name.")

    model_config = ConfigDict(extra="forbid")


class BaseURLWitness(BaseModel):
    """An L0 BaseURL that witnesses a System."""

    url: str = Field(description="L0 base URL.")

    model_config = ConfigDict(extra="forbid")


Witness = (
    EndpointWitness
    | HeaderWitness
    | TechnologyWitness
    | CertificateWitness
    | BaseURLWitness
)


class SystemAttributes(BaseModel):
    """The typed attributes a System carries."""

    description: str = Field(
        description="One or two sentences naming the mechanism and its "
                    "adversarial edge. This is the attribute the next batch reads."
    )
    pages: list[str] = Field(
        default_factory=list,
        description="For a WebPresentation, the member text/html page paths.",
    )
    rendering_model: str = Field(
        default="", description="The observed rendering model, when one applies."
    )


class SystemDefinition(BaseModel):
    """One System the typist judges to exist, with its witnesses."""

    kind: str = Field(description="A known System kind, for example ReverseProxy.")
    discriminator: str = Field(
        default="__singleton__",
        description="The System discriminator. Use __singleton__ when the kind "
                    "has one instance.",
    )
    attributes: SystemAttributes
    evidence: list[Witness] = Field(
        default_factory=list,
        description="The L0 nodes that witness the mechanism.",
    )


class SystemExtraction(BaseModel):
    """The extraction turn's complete answer."""

    systems: list[SystemDefinition] = Field(
        description="One entry per mechanism the reflection identified."
    )


class SystemLink(BaseModel):
    """One typed Service-to-System link."""

    service: str = Field(description="The exact business_function_slug.")
    kind: str = Field(description="The System kind.")
    discriminator: str = Field(default="__singleton__")
    relation: str = Field(
        description="One of EXPOSED_VIA, FRONTED_BY, PROTECTED_BY, ROUTED_BY, "
                    "IDENTIFIED_BY, AUTHENTICATED_BY, AUTHORIZED_BY, SHAPES_DATA_OF."
    )
    role: str | None = None
    realm: str | None = None
    order: int | None = None


class SystemLinking(BaseModel):
    """The linking turn's complete answer."""

    links: list[SystemLink] = Field(
        description="One typed Service-to-System link per evidenced pair."
    )


# The typist binds BOTH structured tools on every turn (reflection, extraction,
# linking), so the request shape never toggles. The prompt says which tool to
# call; the response format carries both.
TypistDelta = SystemExtraction | SystemLinking


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
    """Map the ADDITIVE proposals to their provenance-carrying deltas, keyed to
    match `l1_curator.enrich`'s kwargs. Provenance is system-supplied (the LLM
    never sets it), exactly as `proposals_to_deltas` does for the core deltas.

    Two categories: the typed `Service->System` edges (`system_edges`) and each
    System's `EVIDENCED_BY` witnesses (`system_evidence`, ticket #354) - one delta
    per witness, so a System with no witness maps to nothing and stays edgeless."""
    return {
        "system_edges": [
            SystemEdgeDelta(
                service_slug=e.service_slug, kind=e.kind,
                discriminator=e.discriminator, rel=e.rel, role=e.role, realm=e.realm,
                order=e.order, provenance=provenance,
            )
            for e in batch.system_edges
        ],
        "system_evidence": [
            SystemEvidenceDelta(
                kind=s.kind, discriminator=s.discriminator, l0=w, provenance=provenance,
            )
            for s in batch.systems
            for w in s.evidence
        ],
    }


def assigner_delta_to_batch(delta: AssignerDelta) -> L1DeltaBatch:
    """Expand the assigner's Service groups into the curator's per-endpoint union.

    One group becomes one `AggregatesProposal` per endpoint, carrying the group's
    evidence. The group-level evidence is the model-facing simplification; the
    curator's judgment envelope is per aggregate, so the same sentence rides each
    endpoint the group owns.
    """
    aggregates: list[AggregatesProposal] = []
    for group in delta.aggregations:
        evidence = [group.evidence.strip()] if group.evidence.strip() else []
        for endpoint in group.endpoints:
            aggregates.append(
                AggregatesProposal(
                    service_slug=group.service,
                    l0=L0Ref(
                        label="Endpoint",
                        identity={
                            "path": endpoint.path,
                            "method": endpoint.method,
                            "baseurl": endpoint.baseurl,
                        },
                    ),
                    evidence_refs=evidence,
                )
            )
    return L1DeltaBatch(aggregates=aggregates)


def witness_to_l0_ref(witness) -> L0Ref:
    """Map one typed witness to the writer's L0 reference shape."""
    if isinstance(witness, EndpointWitness):
        return L0Ref(label="Endpoint", identity={
            "path": witness.path,
            "method": witness.method,
            "baseurl": witness.baseurl,
        })
    if isinstance(witness, HeaderWitness):
        return L0Ref(label="Header", identity={
            "name": witness.name,
            "endpoint": witness.endpoint,
            "baseurl": witness.baseurl,
        })
    if isinstance(witness, TechnologyWitness):
        return L0Ref(label="Technology", identity={
            "name": witness.name,
            "version": witness.version,
        })
    if isinstance(witness, BaseURLWitness):
        return L0Ref(label="BaseURL", identity={"url": witness.url})
    return L0Ref(label="Certificate", identity={"subject_cn": witness.subject_cn})


def system_extraction_to_batch(extraction: SystemExtraction) -> L1DeltaBatch:
    """Map the extraction turn's typed Systems to the curator's union."""
    systems: list[SystemProposal] = []
    for definition in extraction.systems:
        props = {"description": definition.attributes.description}
        if definition.attributes.pages:
            props["pages"] = list(definition.attributes.pages)
        if definition.attributes.rendering_model:
            props["rendering_model"] = definition.attributes.rendering_model
        systems.append(
            SystemProposal(
                kind=definition.kind,
                discriminator=definition.discriminator,
                props=props,
                evidence=[
                    witness_to_l0_ref(witness) for witness in definition.evidence
                ],
            )
        )
    return L1DeltaBatch(systems=systems)


def system_linking_to_batch(linking: SystemLinking) -> L1DeltaBatch:
    """Map the linking turn's typed links to the curator's union."""
    return L1DeltaBatch(
        system_edges=[
            SystemEdgeProposal(
                service_slug=link.service,
                kind=link.kind,
                discriminator=link.discriminator,
                rel=link.relation,
                role=link.role,
                realm=link.realm,
                order=link.order,
            )
            for link in linking.links
        ]
    )
