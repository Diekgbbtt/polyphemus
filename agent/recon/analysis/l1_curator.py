"""Layer-1 sole-writer: turns typed L1 deltas into parameterised Neo4j MERGE
Cypher over the disjoint `:L1*` label namespace, and executes them.

This module is the ONLY graph-write path for the Layer-1 service/system model,
the exact mirror of `agent/recon/curator.py` for Layer 0 (design §10.6 / L1D-22).
The pure builders (`build_*_cypher`) never touch a driver; `l1_curate` /
`seed_system_kinds` are the impure orchestrators that inject `project_id`, call
`merge_fn` per item, and skip+log single-item failures so one bad delta never
aborts a whole batch (fail-open, mirroring curator).

`merge_fn` defaults to `agent.app.clients.neo4j_client.merge`, resolved lazily so
importing this module (or unit-testing the pure builders) never constructs a live
Neo4j driver.

Invariants enforced here (see docs/design/L1-MVP-plan.md §5):
  * idempotent MERGE on L1 identity (L1D-22): re-running a delta yields one node;
  * identity ⊥ membership (L1D-11): a unit is keyed on business function / kind,
    never on its member set, so `props` may change without churning identity;
  * `discriminator` defaults to the non-null `__singleton__` sentinel (L1D-9);
  * provenance + first/last_seen stamped on every write (L1D-25);
  * `SystemKind` is a controlled-vocabulary catalogue (L1D-6): a System's kind
    must be a known row, and adding a kind is a data write (a new seed row), not
    a schema migration.

Interface agreement A (the `AGGREGATES` cross-layer reference + judgment
envelope, L1D-25) is written by `build_aggregates_cypher` / `write_aggregates`
as a NATIVE edge (operator decision, option A): `(:L1Service)-[:AGGREGATES
{envelope}]->(:L0 node)` to the co-resident L0 node, matching the spec's §6
edge taxonomy. The L0 target is MATCHed (never created here), so L1 never
reuses an L0 key as its own and the L0 sole-writer (curator.py) is untouched;
the edge is the lazy fetch hop of traversal-then-fetch (DD-4, see
`l1_read.read_aggregated_l0`).
"""
from __future__ import annotations

import logging
import re

from agent.recon.analysis.l1_types import (
    L1_SINGLETON,
    AggregatesDelta,
    DataFlowDelta,
    DataItemDelta,
    DataRelationshipDelta,
    L0Ref,
    Provenance,
    ServiceDelta,
    SurfacesAtDelta,
    SystemDelta,
    SystemEdgeDelta,
)

logger = logging.getLogger(__name__)

# The only L1 unit labels this sole-writer will emit (mirrors curator.ALLOWED_LABELS).
# Every unit also carries the `:L1TestableUnit` supertype label (L1D-3) so BFS can
# enumerate "every unit" in one query (FR-INDEXCARD) regardless of subtype.
L1_ALLOWED_LABELS = frozenset({"L1Service", "L1System"})

# The seed SystemKind controlled vocabulary (L1D-6, spec §2.3). Extensible by
# adding rows here — never a schema migration. Kept per-project (keyed
# (id, project_id)) for tenant isolation and uniformity with every other
# project-scoped node; a later globalisation is a two-way door.
SYSTEM_KINDS: tuple[tuple[str, str], ...] = (
    ("WAF", "Web application firewall; perimeter request inspection/blocking."),
    ("CDN", "Content delivery / edge network fronting origin traffic."),
    ("ReverseProxy", "Reverse proxy / caching layer in front of an origin."),
    ("APIGateway", "API gateway routing and enforcing across backend services."),
    ("RESTApi", "REST API paradigm overlay that services expose through."),
    ("GraphQLApi", "GraphQL API paradigm overlay that services expose through."),
    ("IdentificationSystem", "Cookie / session identification system."),
    ("IntegrationSystem", "Cross-origin integration system (CSP / CORS)."),
    ("AuthenticationMechanism", "How credentials / tokens are minted and validated."),
    ("AuthorizationSystem", "Role / permission policy enforcement system."),
    ("RenderingSystem_SSR_UI", "Server-side-rendered UI rendering system."),
    ("RenderingSystem_CSR_JSMap", "Client-side-rendered JS-map rendering system."),
    ("Sitemap", "Site structure / navigation map system."),
)
_KNOWN_KINDS = frozenset(kind_id for kind_id, _desc in SYSTEM_KINDS)

# FR-ENRICH: the DataRelationship controlled vocabulary (L1D-13/L1OP-2), the
# functional-dependency invariants between DataItems. Extensible by adding rows
# here - never a schema migration (same discipline as SYSTEM_KINDS).
DATA_RELATIONSHIP_KINDS: tuple[tuple[str, str], ...] = (
    ("derived_from", "The source item is computed/derived from the target item."),
    ("reflected_in", "The source item's value is reflected back in the target item."),
    ("equals_hash_of", "The source item equals a hash of the target item(s)."),
    ("copy_of", "The source item is a verbatim copy of the target item."),
    ("concatenation_of", "The source item is a concatenation involving the target item."),
    ("subset_of", "The source item is a subset/projection of the target item."),
)
_KNOWN_DATA_REL_KINDS = frozenset(k for k, _d in DATA_RELATIONSHIP_KINDS)

# Edge-label allowlists (rel labels are interpolated into Cypher, so they are
# validated against these fixed sets - defence in depth, like _SAFE_IDENT).
_DATA_FLOW_RELS = {"produces": "PRODUCES", "consumes": "CONSUMES"}
# The §6 System-edge taxonomy (L1D-18/L1D-21); sub-granularity rides on props.
SYSTEM_EDGE_RELS = frozenset({
    "EXPOSED_VIA", "IDENTIFIED_BY", "AUTHENTICATED_BY", "AUTHORIZED_BY",
    "FRONTED_BY", "PROTECTED_BY", "ROUTED_BY", "SHAPES_DATA_OF", "RENDERED_BY",
    "ON_REQUEST_PATH", "DEPENDS_ON",
})

# Placeholder overwritten with the real project_id by the impure orchestrators
# before dispatch, exactly like curator._PENDING_PROJECT_ID.
_PENDING_PROJECT_ID = "__pending_project_id__"

# Keys a caller's `props` may NOT set: identity keys + curator-managed fields.
# Stripped defensively because L1 props originate from a less-trusted LLM (unlike
# L0 props from deterministic parsers), so they must never spoof identity or
# provenance.
_RESERVED_PROPS = frozenset({
    "project_id", "business_function_slug", "system_kind", "discriminator",
    "first_seen", "last_seen", "prov_job", "prov_model", "prov_prompt_id",
})

# Provenance markers for the SystemKind catalogue. Catalogue rows are
# deterministic controlled-vocabulary reference data (not LLM-produced), so their
# provenance is the curator function that wrote them rather than a model/prompt;
# they still carry a prov_job + first/last_seen so "provenance on every L1 node"
# (L1D-25) holds uniformly, incl. a kind auto-created as an OF_KIND target.
_SEED_PROV_JOB = "l1_curator:seed_system_kinds"
_OFKIND_PROV_JOB = "l1_curator:of_kind_autocreate"


def _resolve_merge_fn(merge_fn):
    if merge_fn is None:
        from agent.app.clients import neo4j_client
        merge_fn = neo4j_client.merge
    return merge_fn


def vocabulary_prompt() -> str:
    """The controlled vocabularies the analyser LLM MUST draw from, rendered for
    the prompt. Single-sourced from the catalogues below so it never drifts: a
    proposal using a name outside these sets is rejected by the builders and
    silently dropped, so the LLM must be told the exact allowed values."""
    kinds = ", ".join(sorted(_KNOWN_KINDS))
    rel_kinds = ", ".join(sorted(_KNOWN_DATA_REL_KINDS))
    sys_rels = ", ".join(sorted(SYSTEM_EDGE_RELS))
    return (
        "CONTROLLED VOCABULARIES - use these EXACT values only:\n"
        f"- `system_kind` (for systems / system_edges) must be one of: {kinds}. "
        "e.g. the authentication mechanism is `AuthenticationMechanism` (NOT "
        "'Authentication'); the authorization system is `AuthorizationSystem`.\n"
        f"- System-edge `rel` must be one of: {sys_rels}.\n"
        f"- DataRelationship `kind` must be one of: {rel_kinds}.\n"
        "- A System's `discriminator` defaults to the literal string "
        "'__singleton__' unless the target genuinely has multiple instances of "
        "that kind (e.g. two different CDN products)."
    )


def _clean_props(props: dict) -> dict:
    cleaned: dict = {}
    for key, value in dict(props).items():
        if key in _RESERVED_PROPS:
            logger.warning("l1_curator: dropping reserved prop key %r from props", key)
            continue
        cleaned[key] = value
    return cleaned


def _prov_params(prov: Provenance) -> dict:
    return {"prov_job": prov.job, "prov_model": prov.model, "prov_prompt_id": prov.prompt_id}


def _identity_clause(identity: dict) -> tuple[str, dict]:
    """Build a deterministic `{k: $id_k, ...}` clause + its params (sorted keys)."""
    keys = sorted(identity.keys())
    clause = ", ".join(f"{k}: $id_{k}" for k in keys)
    params = {f"id_{k}": identity[k] for k in keys}
    return clause, params


def build_unit_cypher(
    label: str, identity: dict, props: dict, provenance: Provenance
) -> tuple[str, dict]:
    """Pure: parameterised MERGE for one L1 `TestableUnit` subtype.

    Raises ValueError if `label` is not an allowed L1 unit label, or if any
    identity component is null/empty (identity keys must be non-null composites,
    mirroring every L0 key; this is where the `__singleton__` sentinel earns its
    keep — a null discriminator would silently duplicate the node).

    Managed fields (`first_seen`/`last_seen`/`prov_*`) are SET after `n += props`
    so a caller's props can never clobber identity or provenance.
    """
    if label not in L1_ALLOWED_LABELS:
        raise ValueError(f"Unknown L1 unit label: {label!r}")
    for key, value in identity.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"L1 identity key {key!r} must be non-null/non-empty, got {value!r}")

    id_clause, params = _identity_clause(identity)
    params["project_id"] = _PENDING_PROJECT_ID
    params["props"] = _clean_props(props)
    params.update(_prov_params(provenance))

    cypher = "\n".join([
        f"MERGE (n:L1TestableUnit:{label} {{{id_clause}, project_id: $project_id}})",
        "ON CREATE SET n.first_seen = datetime()",
        "SET n += $props",
        "SET n.last_seen = datetime()",
        "SET n.prov_job = $prov_job, n.prov_model = $prov_model, n.prov_prompt_id = $prov_prompt_id",
    ])
    return cypher, params


def build_service_cypher(delta: ServiceDelta) -> tuple[str, dict]:
    """Pure: MERGE one business `Service` on (project_id, business_function_slug)."""
    slug = delta.business_function_slug
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError(f"L1Service requires a non-empty business_function_slug, got {slug!r}")
    return build_unit_cypher(
        "L1Service", {"business_function_slug": slug}, delta.props, delta.provenance
    )


def build_system_cypher(delta: SystemDelta) -> tuple[str, dict]:
    """Pure: MERGE one `System` on (project_id, system_kind, discriminator) plus
    its `OF_KIND` edge to the controlled-vocabulary `SystemKind` catalogue node.

    Raises ValueError if `system_kind` is not a known kind (typo guard — an
    unrecognised kind would fragment the overlay). A null/empty discriminator is
    coerced to the `__singleton__` sentinel (never null, L1D-9)."""
    if delta.system_kind not in _KNOWN_KINDS:
        raise ValueError(
            f"Unknown SystemKind {delta.system_kind!r}; known: {sorted(_KNOWN_KINDS)}"
        )
    discriminator = delta.discriminator
    if not isinstance(discriminator, str) or not discriminator.strip():
        discriminator = L1_SINGLETON

    cypher, params = build_unit_cypher(
        "L1System",
        {"system_kind": delta.system_kind, "discriminator": discriminator},
        delta.props,
        delta.provenance,
    )
    cypher += "\n" + "\n".join([
        "MERGE (k:SystemKind {id: $system_kind_id, project_id: $project_id})",
        "ON CREATE SET k.first_seen = datetime(), k.prov_job = $ofkind_prov_job",
        "MERGE (n)-[:OF_KIND]->(k)",
    ])
    params["system_kind_id"] = delta.system_kind
    params["ofkind_prov_job"] = _OFKIND_PROV_JOB
    return cypher, params


def build_systemkind_cypher(kind_id: str, description: str) -> tuple[str, dict]:
    """Pure: MERGE one `SystemKind` catalogue row on (id, project_id)."""
    if kind_id not in _KNOWN_KINDS:
        raise ValueError(f"Unknown SystemKind {kind_id!r}; known: {sorted(_KNOWN_KINDS)}")
    params = {
        "id": kind_id, "description": description,
        "project_id": _PENDING_PROJECT_ID, "prov_job": _SEED_PROV_JOB,
    }
    cypher = "\n".join([
        "MERGE (k:SystemKind {id: $id, project_id: $project_id})",
        "ON CREATE SET k.first_seen = datetime()",
        "SET k.description = $description",
        "SET k.last_seen = datetime()",
        "SET k.prov_job = $prov_job",
    ])
    return cypher, params


def seed_system_kinds(project_id: str, *, merge_fn=None) -> int:
    """Seed the controlled-vocabulary catalogue for a project. Idempotent
    (MERGE); returns the count of kinds written. Fail-open per row."""
    merge_fn = _resolve_merge_fn(merge_fn)
    seeded = 0
    for kind_id, description in SYSTEM_KINDS:
        cypher, params = build_systemkind_cypher(kind_id, description)
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("seed_system_kinds: failed for kind=%r", kind_id, exc_info=True)
            continue
        seeded += 1
    return seeded


def l1_curate(
    services: list[ServiceDelta],
    systems: list[SystemDelta],
    project_id: str,
    *,
    merge_fn=None,
) -> tuple[int, int]:
    """Execute each Service/System MERGE, skipping+logging single-item failures
    (bad slug, unknown kind, or a merge_fn exception) and continuing. Returns
    (services_merged, systems_merged). Mirrors curator.curate."""
    merge_fn = _resolve_merge_fn(merge_fn)

    services_merged = 0
    for delta in services:
        try:
            cypher, params = build_service_cypher(delta)
        except ValueError:
            logger.warning(
                "l1_curate: skipping service delta slug=%r",
                getattr(delta, "business_function_slug", None), exc_info=True,
            )
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("l1_curate: merge failed for service", exc_info=True)
            continue
        services_merged += 1

    systems_merged = 0
    for delta in systems:
        try:
            cypher, params = build_system_cypher(delta)
        except ValueError:
            logger.warning(
                "l1_curate: skipping system delta kind=%r",
                getattr(delta, "system_kind", None), exc_info=True,
            )
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("l1_curate: merge failed for system", exc_info=True)
            continue
        systems_merged += 1

    return services_merged, systems_merged


# --- Interface agreement A: the AGGREGATES cross-layer edge (L1D-25) ----------
# Encoded as a NATIVE relationship (operator decision, option A) from the L1
# Service to the actual co-resident L0 node, with the judgment envelope on the
# edge. Under topology D1 (L0 + L1 in one physical Neo4j) this is clean and needs
# no foreign key, matches the spec's §6 edge taxonomy, and makes the "lazy fetch
# edge" (§1.3) a real graph hop. The L0 target is MATCHed, never MERGEd, so this
# sole-writer can never create an L0 node (that is curator.py's sole right);
# idempotency comes from MERGE on the (Service)-[:AGGREGATES]->(L0) pattern.

# Neo4j cannot parameterise a label or property name, so the L0 label + identity
# keys are interpolated into Cypher; validate them as strict identifiers first.
# `\Z` (absolute end) not `$` (which also matches before a trailing newline), so a
# label/key like "Endpoint\n" cannot slip past the injection guard.
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")

# Endpoint-template key (L1D-32 / ratified door D5). A path segment that is all
# digits or a UUID is an instance identifier; collapsing it to `{id}` yields the
# template key so concretisation can later dedup `/products/1`, `/products/2`, ...
# to one representative (the full equivalence-class reducer is NM-10). The key
# MUST be written at assignment time - it cannot be reconstructed from concrete
# paths after the fact (the spec's assumption that katana already yields
# templates is false; katana emits concrete paths).
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def endpoint_template(path: str) -> str:
    """Pure: derive the endpoint-template key from a concrete path by replacing
    each numeric or UUID segment with the `{id}` placeholder. Idempotent (a path
    already templated, or with no id segments, is returned unchanged). Preserves
    a trailing/leading slash structure by templating per `/`-segment."""
    if not isinstance(path, str) or not path:
        return path
    return "/".join("{id}" if (seg.isdigit() or _UUID_RE.match(seg)) else seg
                    for seg in path.split("/"))


def build_aggregates_cypher(delta: AggregatesDelta) -> tuple[str, dict]:
    """Pure: MERGE the native `(:L1Service)-[:AGGREGATES {envelope}]->(:L0)` edge
    to the co-resident L0 node identified by `delta.l0` (label + identity tuple),
    carrying the full judgment envelope (L1D-25) as edge properties.

    The L0 node is MATCHed (never MERGEd): if it does not exist the whole
    statement is a no-op - no edge, and crucially no L0 node is created here.
    Raises ValueError on an empty service_slug, an unsafe/empty L0 label, an
    empty L0 identity, or unsafe identity keys (Cypher-injection guard). `ts` is
    server-stamped when the envelope carries none."""
    slug = delta.service_slug
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError(f"AggregatesDelta requires a non-empty service_slug, got {slug!r}")
    l0 = delta.l0
    if not isinstance(l0.label, str) or not _SAFE_IDENT.match(l0.label):
        raise ValueError(f"AggregatesDelta requires a safe L0 label, got {l0.label!r}")
    if not isinstance(l0.identity, dict) or not l0.identity:
        raise ValueError("AggregatesDelta requires a non-empty L0 identity map")
    if not all(isinstance(k, str) and _SAFE_IDENT.match(k) for k in l0.identity):
        raise ValueError(f"AggregatesDelta L0 identity keys must be safe identifiers: {list(l0.identity)}")

    env = delta.envelope
    id_keys = sorted(l0.identity)
    l0_clause = ", ".join(f"{k}: $l0_{k}" for k in id_keys)
    params = {
        "project_id": _PENDING_PROJECT_ID,
        "slug": slug,
        "confidence": float(env.confidence),
        "status": env.status,
        "evidence_refs": list(env.evidence_refs),
        "prov_job": env.provenance.job,
        "prov_model": env.provenance.model,
        "prov_prompt_id": env.provenance.prompt_id,
        "ts": env.ts,
    }
    for k in id_keys:
        params[f"l0_{k}"] = l0.identity[k]

    lines = [
        # MATCH (never MERGE) the L0 target: l1_curator must never create L0 nodes.
        f"MATCH (l0:{l0.label} {{{l0_clause}, project_id: $project_id}})",
        # MERGE (not SET) the Service endpoint: this writer references the unit,
        # it does not own it (bootstrap/enrichment own the Service node).
        "MERGE (s:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $project_id})",
        "MERGE (s)-[r:AGGREGATES]->(l0)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.confidence = $confidence, r.status = $status, r.evidence_refs = $evidence_refs",
        "SET r.prov_job = $prov_job, r.prov_model = $prov_model, r.prov_prompt_id = $prov_prompt_id",
        "SET r.ts = coalesce($ts, toString(datetime()))",
    ]
    # Endpoint-template key (L1D-32): preserve it on the AGGREGATES edge at
    # assignment when the aggregated L0 element is an Endpoint with a path. Kept
    # on the L1-side edge because l1_curator must not write the L0 node.
    if l0.label == "Endpoint" and isinstance(l0.identity.get("path"), str):
        params["endpoint_template"] = endpoint_template(l0.identity["path"])
        lines.append("SET r.endpoint_template = $endpoint_template")

    return "\n".join(lines), params


def write_aggregates(
    deltas: list[AggregatesDelta], project_id: str, *, merge_fn=None
) -> int:
    """Execute each AGGREGATES ref MERGE, skipping+logging single-item failures
    and continuing (fail-open). Returns the count written. Mirrors l1_curate."""
    merge_fn = _resolve_merge_fn(merge_fn)
    written = 0
    for delta in deltas:
        try:
            cypher, params = build_aggregates_cypher(delta)
        except ValueError:
            logger.warning(
                "write_aggregates: skipping ref service=%r",
                getattr(delta, "service_slug", None), exc_info=True,
            )
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("write_aggregates: merge failed", exc_info=True)
            continue
        written += 1
    return written


# --- FR-ENRICH: DataItem + trust/data-flow + relationship writers -------------

def _require_slug(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _l0_match_clause(l0: L0Ref) -> tuple[str, dict]:
    """Build a `MATCH (l0:<Label> {<identity>, project_id})` fragment + params,
    validating the interpolated label + identity keys as safe identifiers
    (Cypher-injection guard). The L0 node is MATCHed, never created (L1D-2)."""
    if not isinstance(l0.label, str) or not _SAFE_IDENT.match(l0.label):
        raise ValueError(f"unsafe L0 label {l0.label!r}")
    if not isinstance(l0.identity, dict) or not l0.identity:
        raise ValueError("empty L0 identity")
    if not all(isinstance(k, str) and _SAFE_IDENT.match(k) for k in l0.identity):
        raise ValueError(f"unsafe L0 identity keys: {list(l0.identity)}")
    id_keys = sorted(l0.identity)
    clause = ", ".join(f"{k}: $l0_{k}" for k in id_keys)
    params = {f"l0_{k}": l0.identity[k] for k in id_keys}
    return f"MATCH (l0:{l0.label} {{{clause}, project_id: $project_id}})", params


def build_dataitem_cypher(delta: DataItemDelta) -> tuple[str, dict]:
    """Pure: MERGE one `:L1DataItem` on its flexible semantic key
    (project_id, item_key). identity ⊥ membership: never keyed on its L0 sites."""
    item_key = _require_slug(delta.item_key, "DataItem item_key")
    params = {"item_key": item_key, "project_id": _PENDING_PROJECT_ID, "props": _clean_props(delta.props)}
    params.update(_prov_params(delta.provenance))
    cypher = "\n".join([
        "MERGE (d:L1DataItem {item_key: $item_key, project_id: $project_id})",
        "ON CREATE SET d.first_seen = datetime()",
        "SET d += $props",
        "SET d.last_seen = datetime()",
        "SET d.prov_job = $prov_job, d.prov_model = $prov_model, d.prov_prompt_id = $prov_prompt_id",
    ])
    return cypher, params


def build_surfaces_at_cypher(delta: SurfacesAtDelta) -> tuple[str, dict]:
    """Pure: MERGE the native cross-layer `(:L1DataItem)-[:SURFACES_AT]->(:L0)`
    edge. The DataItem is MERGEd (owned by L1); the L0 site is MATCHed, never
    created."""
    item_key = _require_slug(delta.item_key, "SurfacesAt item_key")
    match_clause, params = _l0_match_clause(delta.l0)
    params["item_key"] = item_key
    params["project_id"] = _PENDING_PROJECT_ID
    params.update(_prov_params(delta.provenance))
    cypher = "\n".join([
        match_clause,
        "MERGE (d:L1DataItem {item_key: $item_key, project_id: $project_id})",
        "MERGE (d)-[r:SURFACES_AT]->(l0)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.prov_job = $prov_job",
    ])
    return cypher, params


def build_data_flow_cypher(delta: DataFlowDelta) -> tuple[str, dict]:
    """Pure: MERGE a `(:L1Service)-[:PRODUCES|CONSUMES]->(:L1DataItem)` edge. A
    CONSUMES edge carries the trust `assumption` predicate + rationale (L1D-14)."""
    slug = _require_slug(delta.service_slug, "DataFlow service_slug")
    item_key = _require_slug(delta.item_key, "DataFlow item_key")
    rel = _DATA_FLOW_RELS.get(delta.direction)
    if rel is None:
        raise ValueError(f"DataFlow direction must be produces|consumes, got {delta.direction!r}")
    params = {
        "slug": slug, "item_key": item_key, "project_id": _PENDING_PROJECT_ID,
        "assumption": delta.assumption, "assumption_rationale": delta.assumption_rationale,
    }
    params.update(_prov_params(delta.provenance))
    lines = [
        "MERGE (s:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $project_id})",
        "MERGE (d:L1DataItem {item_key: $item_key, project_id: $project_id})",
        f"MERGE (s)-[r:{rel}]->(d)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.prov_job = $prov_job",
    ]
    if rel == "CONSUMES":
        lines.append("SET r.assumption = $assumption, r.assumption_rationale = $assumption_rationale")
    return "\n".join(lines), params


def build_data_relationship_cypher(delta: DataRelationshipDelta) -> tuple[str, dict]:
    """Pure: MERGE a `(:L1DataItem)-[:DATA_RELATIONSHIP {kind}]->(:L1DataItem)`
    edge carrying the machine-checkable `predicate` + NL `rationale`, and ensure
    the `kind`'s controlled-vocabulary catalogue row exists. `kind` must be known
    (extend via DATA_RELATIONSHIP_KINDS, not schema)."""
    from_key = _require_slug(delta.from_item_key, "DataRelationship from_item_key")
    to_key = _require_slug(delta.to_item_key, "DataRelationship to_item_key")
    if delta.kind not in _KNOWN_DATA_REL_KINDS:
        raise ValueError(f"Unknown DataRelationship kind {delta.kind!r}; known: {sorted(_KNOWN_DATA_REL_KINDS)}")
    params = {
        "from_key": from_key, "to_key": to_key, "kind": delta.kind,
        "predicate": delta.predicate, "rationale": delta.rationale,
        "project_id": _PENDING_PROJECT_ID,
    }
    params.update(_prov_params(delta.provenance))
    cypher = "\n".join([
        "MERGE (a:L1DataItem {item_key: $from_key, project_id: $project_id})",
        "MERGE (b:L1DataItem {item_key: $to_key, project_id: $project_id})",
        "MERGE (a)-[r:DATA_RELATIONSHIP {kind: $kind}]->(b)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.predicate = $predicate, r.rationale = $rationale",
        "SET r.prov_job = $prov_job",
        "MERGE (k:DataRelationshipKind {id: $kind, project_id: $project_id})",
        "ON CREATE SET k.first_seen = datetime(), k.prov_job = $prov_job",
    ])
    return cypher, params


def build_system_edge_cypher(delta: SystemEdgeDelta) -> tuple[str, dict]:
    """Pure: MERGE a typed `(:L1Service)-[:<REL>]->(:L1System)` edge from the §6
    taxonomy (L1D-18). `rel` must be an allowed System-edge label; `system_kind`
    must be known; role/realm/order ride on props (L1D-21) when present."""
    slug = _require_slug(delta.service_slug, "SystemEdge service_slug")
    if delta.rel not in SYSTEM_EDGE_RELS:
        raise ValueError(f"Unknown System-edge rel {delta.rel!r}; known: {sorted(SYSTEM_EDGE_RELS)}")
    if delta.system_kind not in _KNOWN_KINDS:
        raise ValueError(f"Unknown SystemKind {delta.system_kind!r}")
    discriminator = delta.discriminator if (isinstance(delta.discriminator, str) and delta.discriminator.strip()) else L1_SINGLETON
    params = {
        "slug": slug, "system_kind": delta.system_kind, "discriminator": discriminator,
        "role": delta.role, "realm": delta.realm, "order": delta.order,
        "project_id": _PENDING_PROJECT_ID,
    }
    params.update(_prov_params(delta.provenance))
    lines = [
        "MERGE (s:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $project_id})",
        "MERGE (sy:L1TestableUnit:L1System {system_kind: $system_kind, discriminator: $discriminator, project_id: $project_id})",
        f"MERGE (s)-[r:{delta.rel}]->(sy)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.role = $role, r.realm = $realm, r.order = $order",
        "SET r.prov_job = $prov_job",
    ]
    return "\n".join(lines), params


def seed_data_relationship_kinds(project_id: str, *, merge_fn=None) -> int:
    """Seed the DataRelationship controlled-vocabulary catalogue (idempotent)."""
    merge_fn = _resolve_merge_fn(merge_fn)
    seeded = 0
    for kind_id, description in DATA_RELATIONSHIP_KINDS:
        cypher = "\n".join([
            "MERGE (k:DataRelationshipKind {id: $id, project_id: $project_id})",
            "ON CREATE SET k.first_seen = datetime()",
            "SET k.description = $description, k.last_seen = datetime(), k.prov_job = $prov_job",
        ])
        params = {"id": kind_id, "description": description, "project_id": project_id,
                  "prov_job": "l1_curator:seed_data_relationship_kinds"}
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("seed_data_relationship_kinds: failed for kind=%r", kind_id, exc_info=True)
            continue
        seeded += 1
    return seeded


def _write_each(builder, deltas, project_id, merge_fn, what: str) -> int:
    """Shared fail-open write loop: build+merge each delta, skip+log on failure."""
    written = 0
    for delta in deltas:
        try:
            cypher, params = builder(delta)
        except ValueError:
            logger.warning("%s: skipping invalid delta", what, exc_info=True)
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("%s: merge failed", what, exc_info=True)
            continue
        written += 1
    return written


def enrich(
    project_id: str,
    *,
    data_items: list[DataItemDelta] | None = None,
    surfaces_at: list[SurfacesAtDelta] | None = None,
    data_flows: list[DataFlowDelta] | None = None,
    data_relationships: list[DataRelationshipDelta] | None = None,
    system_edges: list[SystemEdgeDelta] | None = None,
    merge_fn=None,
) -> dict:
    """Write a batch of enrichment deltas, fail-open. Order matters: DataItems
    are written before the edges that reference them (SURFACES_AT / flows /
    relationships MERGE the items by identity too, so order is defensive, not
    required). Returns per-category counts."""
    merge_fn = _resolve_merge_fn(merge_fn)
    return {
        "data_items": _write_each(build_dataitem_cypher, data_items or [], project_id, merge_fn, "enrich.data_item"),
        "surfaces_at": _write_each(build_surfaces_at_cypher, surfaces_at or [], project_id, merge_fn, "enrich.surfaces_at"),
        "data_flows": _write_each(build_data_flow_cypher, data_flows or [], project_id, merge_fn, "enrich.data_flow"),
        "data_relationships": _write_each(build_data_relationship_cypher, data_relationships or [], project_id, merge_fn, "enrich.data_relationship"),
        "system_edges": _write_each(build_system_edge_cypher, system_edges or [], project_id, merge_fn, "enrich.system_edge"),
    }
