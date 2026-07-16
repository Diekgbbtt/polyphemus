"""Typed records the Layer-1 sole-writer (`l1_curator`) consumes.

Mirrors the shape/discipline of `agent/recon/types.py` (pydantic BaseModel,
`Field(default_factory=...)`) so L1 deltas read like L0 AssetDeltas. These are
the *inputs* to the pure MERGE builders; the builders never touch a driver.

Design anchors:
  * `Provenance` / `JudgmentEnvelope` encode Interface agreement A (L1D-25): the
    judgment carried on every AGGREGATES cross-layer reference. Fields are fixed
    now even though the MVP only ever writes `status="committed"` (L1R-4).
  * `L0Ref` is the L0 identity tuple a cross-layer reference points at (L1D-2):
    L1 never reuses an L0 key as its own key; it references L0 *by* L0's key and
    resolves it only at concretisation (traversal-then-fetch, DD-4).
  * `ServiceDelta` / `SystemDelta` are the two operative `TestableUnit` subtypes
    (L1D-3); their identity keys are `(project_id, business_function_slug)`
    (L1D-12) and `(project_id, system_kind, discriminator=__singleton__)`
    (L1D-9). `identity ⊥ membership` (L1D-11): a unit is never keyed on its
    member set, so `props`/refs may change freely without churning identity.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The non-null discriminator sentinel (L1D-9 / L1R-2). A NULL discriminator would
# silently duplicate singleton Systems under Neo4j's null-uniqueness semantics,
# so the default is a real string, never None. Every existing L0 key component is
# a non-null composite (db/neo4j/schema.py), so this has no nullable-key analogue.
L1_SINGLETON = "__singleton__"


class Provenance(BaseModel):
    """Who/what produced this write. Stamped on every L1 node and cross-layer
    reference (provenance-on-write, mirroring the L0 curator obs provenance)."""

    job: str
    model: str | None = None
    prompt_id: str | None = None


class JudgmentEnvelope(BaseModel):
    """Interface agreement A (L1D-25): the judgment an `AGGREGATES` reference
    carries from day one. The MVP writes `status="committed"` only, but always
    carries `confidence`/`evidence_refs` so a low-confidence assignment can never
    masquerade as authoritative (L1R-4)."""

    confidence: float = 0.0
    status: Literal["provisional", "committed"] = "committed"
    evidence_refs: list[str] = Field(default_factory=list)
    provenance: Provenance
    ts: str | None = None  # ISO timestamp; stamped at write time when absent


class L0Ref(BaseModel):
    """The Layer-0 identity a cross-layer reference resolves to, keyed by L0's own
    key (L1D-2). `identity` is the L0 node's identity map WITHOUT project_id
    (injected from the owning L1 write's project scope at resolution time)."""

    label: str
    identity: dict


class ServiceDelta(BaseModel):
    """A business-function `Service` (L1D-3/L1D-4). Keyed `(project_id,
    business_function_slug)` (L1D-12); `props` hold the NL label + typed spine
    slots filled by later enrichment, never identity."""

    business_function_slug: str
    props: dict = Field(default_factory=dict)
    provenance: Provenance


class SystemDelta(BaseModel):
    """A cross-cutting technical `System` (L1D-3/L1D-4). Keyed `(project_id,
    system_kind, discriminator)` with `discriminator` defaulting to the
    non-null `__singleton__` sentinel (L1D-9). `system_kind` must be a known
    `SystemKind` id (controlled vocabulary, L1D-6)."""

    system_kind: str
    discriminator: str = L1_SINGLETON
    props: dict = Field(default_factory=dict)
    provenance: Provenance


class AggregatesDelta(BaseModel):
    """One assignment (Interface agreement A, L1D-25): a `Service` AGGREGATES a
    specific L0 element, carrying the judgment `envelope`.

    Physically encoded as a native `(:L1Service)-[:AGGREGATES {envelope}]->(:L0)`
    edge to the co-resident L0 node (operator decision, option A; spec §6). The
    L0 node identified by `l0` (label + identity tuple) is MATCHed, never
    created, so L1 never reuses an L0 key as its own identity (L1D-2) and the
    edge is the lazy fetch hop of traversal-then-fetch (DD-4)."""

    service_slug: str
    l0: L0Ref
    envelope: JudgmentEnvelope


# --- FR-ENRICH: DataItem (flexible identity) + trust/data-flow deltas ----------

class DataItemDelta(BaseModel):
    """A first-class L1 `DataItem` (L1D-13): a logical data element (session
    token, sales_figure, username), identity independent of the many L0 sites it
    surfaces at.

    **Flexible identity** (operator decision 2026-07-16, resolving L1OP-1):
    keyed `(project_id, item_key)` where `item_key` is a semantic slug the
    analyser assigns - mirroring Service `business_function_slug`. "Two data
    items across services are the same logical item" is therefore a *judgment*:
    the analyser assigns the same `item_key` to sites it judges to be one item.
    `identity ⊥ membership` (L1D-11): never keyed on the L0 sites it SURFACES_AT,
    so a new site never churns the item's identity."""

    item_key: str
    props: dict = Field(default_factory=dict)
    provenance: Provenance


class SurfacesAtDelta(BaseModel):
    """A cross-layer `SURFACES_AT` reference (spec §6): the DataItem `item_key`
    appears at a specific L0 site (`Parameter`/`Header`/response field). Native
    edge `(:L1DataItem)-[:SURFACES_AT]->(:L0)`; the L0 node is MATCHed, never
    created (like AGGREGATES)."""

    item_key: str
    l0: L0Ref
    provenance: Provenance


class DataFlowDelta(BaseModel):
    """A `PRODUCES`/`CONSUMES` edge between a Service and a DataItem (L1D-14, the
    Tier-1 trust substrate). `direction='produces'` writes `(:L1Service)
    -[:PRODUCES]->(:L1DataItem)`; `direction='consumes'` writes `[:CONSUMES]`
    and may carry a trust **assumption** predicate + NL rationale - the machine-
    checkable trust assumption ranging over the typed DataItem (derived, not
    asserted, because it hangs on a represented flow)."""

    service_slug: str
    item_key: str
    direction: Literal["produces", "consumes"]
    assumption: str | None = None          # predicate (on CONSUMES)
    assumption_rationale: str | None = None  # NL rationale
    provenance: Provenance


class DataRelationshipDelta(BaseModel):
    """A `DATA_RELATIONSHIP` edge between two DataItems (L1D-13): the functional-
    dependency invariants whose violation hides the trickiest faults.

    **Flexible/extensible vocabulary** (operator decision, resolving L1OP-2):
    `kind` references the `DataRelationshipKind` controlled-vocabulary catalogue
    (extensible by rows, like SystemKind), and sub-granularity rides on the
    `kind`/`predicate` props rather than on ever-more edge labels (L1D-21). The
    edge carries a machine-checkable `predicate` (e.g. `client_id = md5(email+id)`)
    + NL `rationale` (the predicate grammar/evaluation is deferred to the
    signature engine, NM-8; here the predicate is stored as text)."""

    from_item_key: str
    to_item_key: str
    kind: str
    predicate: str | None = None
    rationale: str | None = None
    provenance: Provenance


class SystemEdgeDelta(BaseModel):
    """A typed Service->System edge (L1D-18: cross-cutting systems are edges, not
    strings). `rel` is one of the §6 taxonomy labels (EXPOSED_VIA, FRONTED_BY,
    RENDERED_BY, AUTHENTICATED_BY, AUTHORIZED_BY, …); sub-granularity (role/realm/
    order) rides on props (L1D-21). Both endpoints are MERGEd by identity (the
    sole-writer owns L1 nodes); the System's kind must be known."""

    service_slug: str
    system_kind: str
    discriminator: str = L1_SINGLETON
    rel: str
    role: str | None = None
    realm: str | None = None
    order: int | None = None
    provenance: Provenance
