"""Layer-1 sole-writer: turns typed L1 deltas into parameterised Neo4j MERGE
Cypher over the disjoint `:L1*` label namespace, and executes them.

This module is the ONLY graph-write path for the Layer-1 service/system model,
the exact mirror of `src/polymerhus/recon/domain/curator.py` for Layer 0 (design §10.6 / L1D-22).
The pure builders (`build_*_cypher`) never touch a driver; `l1_curate` / `enrich`
/ `reconcile` are the impure orchestrators that inject `project_id`, call
`merge_fn` per item, and skip+log single-item failures so one bad delta never
aborts a whole batch (fail-open, mirroring curator).

`merge_fn` defaults to `polymerhus.app.clients.neo4j_client.merge`, resolved lazily so
importing this module (or unit-testing the pure builders) never constructs a live
Neo4j driver.

Invariants enforced here (see docs/design/L1-MVP-plan.md §5):
  * idempotent MERGE on L1 identity (L1D-22): re-running a delta yields one node;
  * identity ⊥ membership (L1D-11): a unit is keyed on business function / kind,
    never on its member set, so `props` may change without churning identity;
  * `discriminator` defaults to the non-null `__singleton__` sentinel (L1D-9);
  * provenance + first/last_seen stamped on every write (L1D-25);
  * a System's kind is a plain identity ATTRIBUTE named `kind` (operator
    correction 2026-07-20), validated against the fixed `SYSTEM_KINDS`
    enumeration below - NO `:SystemKind` catalogue node and NO `OF_KIND` edge;
  * a DataRelationship's kind IS the relationship TYPE, drawn from the fixed
    `DATA_RELATIONSHIP_KINDS` allowlist and emitted uppercased (e.g.
    `-[:DERIVED_FROM]->`); an unknown kind is HARD-REJECTED, never a generic
    `DATA_RELATIONSHIP` edge and never a `:DataRelationshipKind` node. Relationship
    types cannot be parameterised in Cypher, so the value is interpolated - the
    `_SAFE_IDENT` guard PLUS the allowlist are load-bearing (mirrors how
    `SYSTEM_EDGE_RELS` is validated).

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

from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
    AggregatesDelta,
    DataFlowDelta,
    DataItemDelta,
    DataRelationshipDelta,
    DeleteOp,
    L0Ref,
    MergeOp,
    Provenance,
    RelabelOp,
    ServiceDelta,
    StripPropsOp,
    SurfacesAtDelta,
    SystemDelta,
    SystemEdgeDelta,
)

logger = logging.getLogger(__name__)

# The only L1 unit labels this sole-writer will emit (mirrors curator.ALLOWED_LABELS).
# Every unit also carries the `:L1TestableUnit` supertype label (L1D-3) so BFS can
# enumerate "every unit" in one query (FR-INDEXCARD) regardless of subtype.
L1_ALLOWED_LABELS = frozenset({"L1Service", "L1System"})

# FR-MERGE: the L1 unit labels a destructive reconciliation op (merge/delete) may
# target. Superset of L1_ALLOWED_LABELS by the flexible-identity `L1DataItem`
# (also a reconcilable unit). It NEVER contains an L0 label, so a reconciliation
# op can never DETACH DELETE / re-key an L0 node (the sole-writer boundary).
L1_RECONCILE_LABELS = L1_ALLOWED_LABELS | {"L1DataItem"}

# The known system-kinds enumeration (operator correction 2026-07-20: the
# `:SystemKind` catalogue nodes are gone; the kind is a plain `kind` attribute on
# the System, validated against THIS module-level constant). Single source of
# truth: reused both to VALIDATE a System's `kind` (typo guard) and to enumerate
# the kinds for the stale-asset-ownership sweep prompt (sweep.py). Extending it is
# a one-line data edit here - never a schema migration.
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
    ("WebPresentation", "Web presentation channel: how the app renders views and navigates "
                        "between them (rendering_model + navigation_model attributes)."),
    ("Sitemap", "Site structure / navigation map system."),
)
_KNOWN_KINDS = frozenset(kind_id for kind_id, _desc in SYSTEM_KINDS)

# FR-ENRICH: the FIXED DataRelationship allowlist (L1D-13/L1OP-2). Operator
# correction 2026-07-20: the kind IS the relationship TYPE (uppercased), so this
# allowlist is a hard security boundary - the value is interpolated into Cypher
# (Neo4j cannot parameterise a rel type), and a miss is a HARD REJECT (never a
# fallback to a generic edge). Only these six may become edge types.
DATA_RELATIONSHIP_KINDS: tuple[tuple[str, str], ...] = (
    ("derived_from", "The source item is computed/derived from the target item."),
    ("reflected_in", "The source item's value is reflected back in the target item."),
    ("equals_hash_of", "The source item equals a hash of the target item(s)."),
    ("copy_of", "The source item is a verbatim copy of the target item."),
    ("concatenation_of", "The source item is a concatenation involving the target item."),
    ("subset_of", "The source item is a subset/projection of the target item."),
)
_KNOWN_DATA_REL_KINDS = frozenset(k for k, _d in DATA_RELATIONSHIP_KINDS)
# kind -> the uppercase edge TYPE it becomes. Single source; reused by the builder
# and the merge re-point allowlist. Every value is a safe identifier by construction.
_DATA_REL_EDGE_TYPES: dict[str, str] = {k: k.upper() for k, _d in DATA_RELATIONSHIP_KINDS}

# Edge-label allowlists (rel labels are interpolated into Cypher, so they are
# validated against these fixed sets - defence in depth, like _SAFE_IDENT).
_DATA_FLOW_RELS = {"produces": "PRODUCES", "consumes": "CONSUMES"}
# The §6 System-edge taxonomy (L1D-18/L1D-21); sub-granularity rides on props.
# NOTE: RENDERED_BY is deliberately ABSENT - a Service reaches its web-presentation
# channel via EXPOSED_VIA (the WebPresentation System, carrying rendering_model +
# navigation_model as independent props), exactly as it reaches a REST/GraphQL API.
SYSTEM_EDGE_RELS = frozenset({
    "EXPOSED_VIA", "IDENTIFIED_BY", "AUTHENTICATED_BY", "AUTHORIZED_BY",
    "FRONTED_BY", "PROTECTED_BY", "ROUTED_BY", "SHAPES_DATA_OF",
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
    "project_id", "business_function_slug", "kind", "discriminator",
    "first_seen", "last_seen", "prov_job", "prov_model", "prov_prompt_id",
})


def _resolve_merge_fn(merge_fn):
    if merge_fn is None:
        from polymerhus.app.clients import neo4j_client
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
        f"- a System's `kind` (for systems / system_edges) must be one of: {kinds}. "
        "e.g. the authentication mechanism is `AuthenticationMechanism` (NOT "
        "'Authentication'); the authorization system is `AuthorizationSystem`.\n"
        f"- System-edge `rel` must be one of: {sys_rels}.\n"
        f"- a DataRelationship `kind` must be one of: {rel_kinds} (the kind becomes "
        "the edge type; anything else is rejected).\n"
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
    """Pure: MERGE one `System` on (project_id, kind, discriminator).

    The kind is a plain identity ATTRIBUTE named `kind` (operator correction
    2026-07-20) - no `:SystemKind` catalogue node, no `OF_KIND` edge. Raises
    ValueError if `kind` is not in the `SYSTEM_KINDS` enumeration (typo guard - an
    unrecognised kind would fragment the overlay). A null/empty discriminator is
    coerced to the `__singleton__` sentinel (never null, L1D-9)."""
    if delta.kind not in _KNOWN_KINDS:
        raise ValueError(
            f"Unknown system kind {delta.kind!r}; known: {sorted(_KNOWN_KINDS)}"
        )
    discriminator = delta.discriminator
    if not isinstance(discriminator, str) or not discriminator.strip():
        discriminator = L1_SINGLETON

    return build_unit_cypher(
        "L1System",
        {"kind": delta.kind, "discriminator": discriminator},
        delta.props,
        delta.provenance,
    )


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
                getattr(delta, "kind", None), exc_info=True,
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
        "ON CREATE SET d.prov_job = $prov_job, d.first_seen = datetime()",  # provenance-on-mint
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
        "ON CREATE SET s.prov_job = $prov_job, s.first_seen = datetime()",  # provenance-on-mint
        "MERGE (d:L1DataItem {item_key: $item_key, project_id: $project_id})",
        "ON CREATE SET d.prov_job = $prov_job, d.first_seen = datetime()",
        f"MERGE (s)-[r:{rel}]->(d)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.prov_job = $prov_job",
    ]
    if rel == "CONSUMES":
        lines.append("SET r.assumption = $assumption, r.assumption_rationale = $assumption_rationale")
    return "\n".join(lines), params


def build_data_relationship_cypher(delta: DataRelationshipDelta) -> tuple[str, dict]:
    """Pure: MERGE a `(:L1DataItem)-[:<KIND>]->(:L1DataItem)` edge whose TYPE is the
    kind (operator correction 2026-07-20), carrying the machine-checkable
    `predicate` + NL `rationale`.

    `kind` MUST be in the fixed `DATA_RELATIONSHIP_KINDS` allowlist; the uppercased
    value is interpolated as the relationship type (Neo4j cannot parameterise a rel
    type). An allowlist miss is a HARD REJECT (ValueError) - never a fallback to a
    generic edge and never a catalogue node. `_SAFE_IDENT` re-checks the derived
    label as defence in depth (mirrors `SYSTEM_EDGE_RELS`)."""
    from_key = _require_slug(delta.from_item_key, "DataRelationship from_item_key")
    to_key = _require_slug(delta.to_item_key, "DataRelationship to_item_key")
    rel = _DATA_REL_EDGE_TYPES.get(delta.kind)
    if rel is None:
        raise ValueError(
            f"Unknown DataRelationship kind {delta.kind!r}; allowed: {sorted(_KNOWN_DATA_REL_KINDS)}"
        )
    if not _SAFE_IDENT.match(rel):  # defence in depth: the label is interpolated
        raise ValueError(f"unsafe DataRelationship edge type {rel!r}")
    params = {
        "from_key": from_key, "to_key": to_key,
        "predicate": delta.predicate, "rationale": delta.rationale,
        "project_id": _PENDING_PROJECT_ID,
    }
    params.update(_prov_params(delta.provenance))
    cypher = "\n".join([
        "MERGE (a:L1DataItem {item_key: $from_key, project_id: $project_id})",
        "ON CREATE SET a.prov_job = $prov_job, a.first_seen = datetime()",  # provenance-on-mint
        "MERGE (b:L1DataItem {item_key: $to_key, project_id: $project_id})",
        "ON CREATE SET b.prov_job = $prov_job, b.first_seen = datetime()",
        f"MERGE (a)-[r:{rel}]->(b)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.predicate = $predicate, r.rationale = $rationale",
        "SET r.prov_job = $prov_job",
    ])
    return cypher, params


def build_system_edge_cypher(delta: SystemEdgeDelta) -> tuple[str, dict]:
    """Pure: MERGE a typed `(:L1Service)-[:<REL>]->(:L1System)` edge from the §6
    taxonomy (L1D-18). `rel` must be an allowed System-edge label; `kind`
    must be a known system kind; role/realm/order ride on props (L1D-21)."""
    slug = _require_slug(delta.service_slug, "SystemEdge service_slug")
    if delta.rel not in SYSTEM_EDGE_RELS:
        raise ValueError(f"Unknown System-edge rel {delta.rel!r}; known: {sorted(SYSTEM_EDGE_RELS)}")
    if delta.kind not in _KNOWN_KINDS:
        raise ValueError(f"Unknown system kind {delta.kind!r}")
    discriminator = delta.discriminator if (isinstance(delta.discriminator, str) and delta.discriminator.strip()) else L1_SINGLETON
    params = {
        "slug": slug, "kind": delta.kind, "discriminator": discriminator,
        "role": delta.role, "realm": delta.realm, "order": delta.order,
        "project_id": _PENDING_PROJECT_ID,
    }
    params.update(_prov_params(delta.provenance))
    # role/realm are part of the edge IDENTITY, not just props: one Service may be
    # AUTHORIZED_BY the AuthorizationSystem under several roles (seller AND
    # seller-admin) and AUTHENTICATED_BY the mechanism across several realms
    # (credential AND idp) - the §15 multi-role/multi-realm reality. Keying the
    # MERGE on rel ALONE collapses them to one edge (the last role wins), so the
    # non-null discriminators are folded into the MERGE relationship-property
    # pattern. `order` stays a plain prop (positional metadata, not identity).
    merge_key = {"role": delta.role, "realm": delta.realm}
    key_frag = ", ".join(f"{k}: ${k}" for k, v in merge_key.items() if v is not None)
    rel_pattern = f"r:{delta.rel} {{{key_frag}}}" if key_frag else f"r:{delta.rel}"
    lines = [
        "MERGE (s:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $project_id})",
        # provenance-on-write: a node this edge writer MINTS carries provenance
        # (ON CREATE only, so a node its primary writer already made keeps its own).
        "ON CREATE SET s.prov_job = $prov_job, s.first_seen = datetime()",
        "MERGE (sy:L1TestableUnit:L1System {kind: $kind, discriminator: $discriminator, project_id: $project_id})",
        "ON CREATE SET sy.prov_job = $prov_job, sy.first_seen = datetime()",
        f"MERGE (s)-[{rel_pattern}]->(sy)",
        "ON CREATE SET r.first_seen = datetime()",
        "SET r.last_seen = datetime()",
        "SET r.role = $role, r.realm = $realm, r.order = $order",
        "SET r.prov_job = $prov_job",
    ]
    return "\n".join(lines), params


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


# --- FR-MERGE: destructive reconciliation (merge / delete / relabel) -----------
# The three destructive ops the post-recon curation pass needs, permitted in this
# sole-writer ONLY (loop-constraints §"Sole-writer"). Each is idempotent,
# provenance-stamped, and re-points (never orphans) the edges of a node it
# removes or re-kinds. APOC is NOT available on the target Neo4j (5.26-community,
# 0 apoc procedures), so re-pointing is explicit per-rel-type over a FIXED
# allowlist rather than `apoc.refactor.mergeNodes`.

# EVIDENCED_BY: a System's cross-layer evidence edge - the semantic a mis-typed
# Service's AGGREGATES becomes when the unit is re-kinded to a System (§3 relabel
# mapping). Interpolated, so it is a safe identifier by construction.
_EVIDENCED_BY = "EVIDENCED_BY"

# The FIXED rel-type allowlist a merge re-points, both directions. Covers every
# L1 edge type the sole-writer emits: the §6 System taxonomy (SYSTEM_EDGE_RELS)
# plus the cross-layer / data-flow / data-relationship edges, plus EVIDENCED_BY so
# a System produced by an earlier relabel also merges cleanly. The data-relationship
# edges are now the SIX typed edge labels (the kind IS the type, operator correction
# 2026-07-20), NOT a single generic DATA_RELATIONSHIP; OF_KIND is gone with the
# `:SystemKind` catalogue. Sorted for deterministic Cypher; every entry is a safe
# uppercase identifier.
_REPOINT_REL_TYPES: tuple[str, ...] = tuple(sorted(
    {"AGGREGATES", "SURFACES_AT", "PRODUCES", "CONSUMES", _EVIDENCED_BY}
    | set(SYSTEM_EDGE_RELS)
    | set(_DATA_REL_EDGE_TYPES.values())
))

# Explicit relabel edge-remap table (L1D-18/§3): edges whose SEMANTICS change with
# a unit's type. Keyed (from_label, to_label) -> {old_rel: new_rel}. Extend here,
# never in Cypher. Both rel labels are trusted uppercase identifiers.
_RELABEL_EDGE_REMAP: dict[tuple[str, str], dict[str, str]] = {
    ("L1Service", "L1System"): {"AGGREGATES": _EVIDENCED_BY},
}


def _reconcile_identity_clause(identity: dict, prefix: str) -> tuple[str, dict]:
    """Build a `{k: $<prefix>_k, ...}` clause + params for a reconciliation MATCH.

    Identity KEYS are interpolated into Cypher, so each is validated as a safe
    identifier first (`_SAFE_IDENT`, the same Cypher-injection guard the cross-
    layer writers use); identity VALUES are always parameters. Rejects an empty
    map and any null/empty value (identity keys are non-null composites, mirroring
    every L0/L1 key). Keys sorted for deterministic Cypher."""
    if not isinstance(identity, dict) or not identity:
        raise ValueError("reconcile op requires a non-empty identity map")
    if not all(isinstance(k, str) and _SAFE_IDENT.match(k) for k in identity):
        raise ValueError(f"reconcile identity keys must be safe identifiers: {list(identity)}")
    for key, value in identity.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"reconcile identity value for {key!r} must be non-null/non-empty, got {value!r}")
    keys = sorted(identity)
    clause = ", ".join(f"{k}: ${prefix}_{k}" for k in keys)
    params = {f"{prefix}_{k}": identity[k] for k in keys}
    return clause, params


def _identity_marker(label: str, identity: dict) -> str:
    """A stable provenance string for a superseded / relabelled identity."""
    return f"{label}:" + ",".join(f"{k}={identity[k]}" for k in sorted(identity))


def build_merge_units_cypher(
    label: str, canonical_identity: dict, duplicate_identity: dict, provenance: Provenance
) -> tuple[str, dict]:
    """Pure: fold duplicate unit B into canonical A (both `:{label}`).

    Re-points EVERY in/out relationship of B onto A over the FIXED
    `_REPOINT_REL_TYPES` allowlist (both directions), then DETACH DELETEs B, then
    copies B's non-identity props A lacks and stamps a `superseded_from` marker.

    Ordering is deliberate: re-point and DELETE the duplicate BEFORE copying its
    props. Copying props includes the duplicate's identity-key value transiently;
    doing it while B still exists collides with B on the `IS UNIQUE` constraint
    (verified failure mode on the live 5.26 container). With B already gone, the
    two-SET idiom (`SET a += dupProps` then `SET a += canonProps`) yields: A keeps
    all its own prop values, gains B's B-only props, identity preserved.

    Idempotent: a second run cannot MATCH the (already-deleted) duplicate, so the
    statement matches nothing and is a no-op. Degenerate self-merge
    (canonical == duplicate) is filtered by the `elementId` guard - A is never
    deleted. Raises ValueError on a non-L1 label or a bad/unsafe identity."""
    if label not in L1_RECONCILE_LABELS:
        raise ValueError(
            f"merge label must be an L1 unit label ({sorted(L1_RECONCILE_LABELS)}), got {label!r}"
        )
    canon_clause, params = _reconcile_identity_clause(canonical_identity, "canon")
    dup_clause, dup_params = _reconcile_identity_clause(duplicate_identity, "dup")
    params.update(dup_params)
    params["project_id"] = _PENDING_PROJECT_ID
    params["dup_marker"] = _identity_marker(label, duplicate_identity)
    params.update(_prov_params(provenance))

    lines = [
        f"MATCH (canon:{label} {{{canon_clause}, project_id: $project_id}})",
        f"MATCH (dup:{label} {{{dup_clause}, project_id: $project_id}})",
        # never delete the canonical when canonical == duplicate (safe no-op)
        "WHERE elementId(canon) <> elementId(dup)",
        "WITH canon, dup, properties(canon) AS canonProps, properties(dup) AS dupProps",
    ]
    # re-point every allowlisted rel type, both directions, BEFORE deleting dup.
    # Unit CALL subqueries preserve the outer (single) row's cardinality. MERGE (not
    # CREATE) onto the canonical means a parallel same-type-same-target edge dedups
    # rather than duplicates (the intended merge semantics); its props are copied.
    for rel in _REPOINT_REL_TYPES:
        lines.append(
            f"CALL {{ WITH canon, dup MATCH (dup)-[r:{rel}]->(x) "
            f"MERGE (canon)-[nr:{rel}]->(x) SET nr += properties(r) DELETE r }}"
        )
        lines.append(
            f"CALL {{ WITH canon, dup MATCH (x)-[r:{rel}]->(dup) "
            f"MERGE (x)-[nr:{rel}]->(canon) SET nr += properties(r) DELETE r }}"
        )
    lines += [
        # DETACH DELETE drops any leftover non-allowlisted edge too; every L1 edge
        # type is in the allowlist, so nothing meaningful is ever orphaned.
        "DETACH DELETE dup",
        "WITH canon, canonProps, dupProps",
        "SET canon += dupProps",
        "SET canon += canonProps",
        "SET canon.superseded_from = coalesce(canon.superseded_from, []) + [$dup_marker]",
        "SET canon.superseded_prov_job = $prov_job",
        "SET canon.last_seen = datetime()",
    ]
    return "\n".join(lines), params


def build_delete_unit_cypher(
    label: str, identity: dict, provenance: Provenance
) -> tuple[str, dict]:
    """Pure: DETACH DELETE one L1 node keyed by (`label`, `identity`).

    `label` MUST be an L1 unit label (`L1_RECONCILE_LABELS`) - this guard is what
    keeps a delete op from ever touching an L0 node. A missing node is a safe
    no-op (the MATCH yields nothing). Deletion is terminal, so no provenance /
    audit row is written (out of scope per §3); `provenance` is accepted for a
    uniform op signature and logged by the caller. Raises ValueError on a non-L1
    label or a bad/unsafe identity."""
    if label not in L1_RECONCILE_LABELS:
        raise ValueError(
            f"delete label must be an L1 unit label ({sorted(L1_RECONCILE_LABELS)}), got {label!r}"
        )
    clause, params = _reconcile_identity_clause(identity, "id")
    params["project_id"] = _PENDING_PROJECT_ID
    cypher = "\n".join([
        f"MATCH (n:{label} {{{clause}, project_id: $project_id}})",
        "DETACH DELETE n",
    ])
    return cypher, params


def build_relabel_unit_cypher(
    from_label: str, to_label: str, identity: dict, new_identity: dict, provenance: Provenance
) -> tuple[str, dict]:
    """Pure: re-kind a mis-typed unit `:{from_label}` -> `:{to_label}`.

    Swaps the subtype label (the shared `:L1TestableUnit` supertype is untouched,
    since both operative subtypes carry it), re-keys identity (`identity` keys not
    in `new_identity` are REMOVEd; `new_identity` keys are SET), and re-points edges
    whose semantics change with the type per `_RELABEL_EDGE_REMAP` (e.g. a
    mis-typed Service's `AGGREGATES` becomes the System's `EVIDENCED_BY`). When the
    target is a System, the `kind` identity attribute is simply SET (no catalogue
    node, no `OF_KIND` edge - operator correction 2026-07-20). Provenance +
    `relabelled_from` stamped.

    Idempotent: a second run cannot re-MATCH the old label/key and is a no-op.
    Raises ValueError on a non-L1 (or equal) from/to label, an unsafe identity,
    or a System target with an unknown `kind`. A blank System discriminator is
    coerced to the `__singleton__` sentinel (never null, L1D-9)."""
    if from_label not in L1_ALLOWED_LABELS:
        raise ValueError(f"relabel from_label must be an operative L1 unit label, got {from_label!r}")
    if to_label not in L1_ALLOWED_LABELS:
        raise ValueError(f"relabel to_label must be an operative L1 unit label, got {to_label!r}")
    if from_label == to_label:
        raise ValueError(f"relabel from_label and to_label must differ, both {from_label!r}")

    working_new = dict(new_identity or {})
    if to_label == "L1System":
        kind = working_new.get("kind")
        if kind not in _KNOWN_KINDS:
            raise ValueError(f"relabel to L1System requires a known kind, got {kind!r}")
        disc = working_new.get("discriminator")
        if not isinstance(disc, str) or not disc.strip():
            working_new["discriminator"] = L1_SINGLETON

    old_clause, params = _reconcile_identity_clause(identity, "id")
    # validate the new identity keys/values with the same guard (they are both
    # interpolated as property names AND parameterised as values below).
    if not isinstance(working_new, dict) or not working_new:
        raise ValueError("relabel requires a non-empty new_identity map")
    if not all(isinstance(k, str) and _SAFE_IDENT.match(k) for k in working_new):
        raise ValueError(f"relabel new_identity keys must be safe identifiers: {list(working_new)}")
    for key, value in working_new.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"relabel new_identity value for {key!r} must be non-null/non-empty, got {value!r}")

    old_keys_to_remove = sorted(k for k in identity if k not in working_new)
    new_keys = sorted(working_new)

    lines = [
        f"MATCH (n:{from_label} {{{old_clause}, project_id: $project_id}})",
        f"REMOVE n:{from_label}",
        f"SET n:{to_label}",
    ]
    if old_keys_to_remove:
        lines.append("REMOVE " + ", ".join(f"n.{k}" for k in old_keys_to_remove))
    lines.append("SET " + ", ".join(f"n.{k} = $newid_{k}" for k in new_keys))
    lines.append("SET n.relabelled_from = $relabelled_from")
    lines.append("SET n.prov_job = $prov_job, n.prov_model = $prov_model, n.prov_prompt_id = $prov_prompt_id")
    lines.append("SET n.last_seen = datetime()")

    for old_rel, new_rel in sorted(_RELABEL_EDGE_REMAP.get((from_label, to_label), {}).items()):
        if not (_SAFE_IDENT.match(old_rel) and _SAFE_IDENT.match(new_rel)):  # defence in depth
            raise ValueError(f"unsafe relabel rel remap {old_rel!r}->{new_rel!r}")
        lines.append("WITH n")
        lines.append(
            f"CALL {{ WITH n MATCH (n)-[r:{old_rel}]->(x) "
            f"MERGE (n)-[nr:{new_rel}]->(x) SET nr += properties(r) DELETE r }}"
        )

    params["project_id"] = _PENDING_PROJECT_ID
    params["relabelled_from"] = _identity_marker(from_label, identity)
    params.update(_prov_params(provenance))
    for k in new_keys:
        params[f"newid_{k}"] = working_new[k]
    return "\n".join(lines), params


def reconcile(
    project_id: str,
    *,
    merges: list[MergeOp] | None = None,
    deletes: list[DeleteOp] | None = None,
    relabels: list[RelabelOp] | None = None,
    merge_fn=None,
) -> dict:
    """Execute a batch of destructive reconciliation ops (FR-MERGE), fail-open per
    op: one bad op (a bad/unsafe identity, a non-L1 or unknown label/kind, or a
    `merge_fn` exception) is skipped+logged and the batch continues - exactly like
    `enrich`. Returns per-category counts `{"merged", "deleted", "relabelled"}`.

    Every write is `:L1*` only (the builders reject any non-L1 label), so
    `reconcile` can never emit an L0 MERGE/DELETE."""
    merge_fn = _resolve_merge_fn(merge_fn)

    merged = 0
    for op in merges or []:
        try:
            cypher, params = build_merge_units_cypher(op.label, op.canonical, op.duplicate, op.provenance)
        except ValueError:
            logger.warning("reconcile.merge: skipping invalid op label=%r", getattr(op, "label", None), exc_info=True)
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("reconcile.merge: merge failed", exc_info=True)
            continue
        merged += 1

    deleted = 0
    for op in deletes or []:
        try:
            cypher, params = build_delete_unit_cypher(op.label, op.identity, op.provenance)
        except ValueError:
            logger.warning("reconcile.delete: skipping invalid op label=%r", getattr(op, "label", None), exc_info=True)
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("reconcile.delete: delete failed", exc_info=True)
            continue
        deleted += 1

    relabelled = 0
    for op in relabels or []:
        try:
            cypher, params = build_relabel_unit_cypher(
                op.from_label, op.to_label, op.identity, op.new_identity, op.provenance
            )
        except ValueError:
            logger.warning(
                "reconcile.relabel: skipping invalid op from=%r to=%r",
                getattr(op, "from_label", None), getattr(op, "to_label", None), exc_info=True,
            )
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("reconcile.relabel: relabel failed", exc_info=True)
            continue
        relabelled += 1

    return {"merged": merged, "deleted": deleted, "relabelled": relabelled}


# --- FR-TYPESEP-b: prop-strip (the re-homing backstop's second leg) ------------
# When a spine fact wrongly set on a Service (rendering_model / navigation_model /
# api_paradigm / perimeter) is re-homed to the correct System via a typed edge,
# the stale Service prop must be removed. A prop removal is an `:L1*` write, so
# the sole-writer discipline forces it to live HERE (not in curation.py). The prop
# keys are interpolated into the REMOVE clause (Neo4j cannot parameterise a
# property name), so each is validated as a safe identifier AND rejected if it is
# an identity / curator-managed key (`_RESERVED_PROPS`) - a strip can never orphan
# a node by dropping its identity, nor spoof provenance.


def build_strip_props_cypher(
    label: str, identity: dict, prop_keys, provenance: Provenance
) -> tuple[str, dict]:
    """Pure: REMOVE a fixed, validated set of non-identity props from one L1 unit.

    `label` MUST be an operative L1 unit label (`L1_ALLOWED_LABELS`) - the guard
    that keeps a strip from ever touching an L0 node (or the flexible-identity
    DataItem). `prop_keys` are each validated as a safe identifier (`_SAFE_IDENT`,
    the Cypher-injection guard) and rejected if reserved/identity
    (`_RESERVED_PROPS`), so an identity key can never be stripped. Keys are sorted
    + deduped for deterministic Cypher; provenance + `last_seen` are stamped.
    Idempotent: REMOVEing an absent prop is a no-op, and a missing node MATCHes
    nothing. Raises ValueError on a non-L1 label, an empty/unsafe identity, or an
    empty / unsafe / reserved prop-key set."""
    if label not in L1_ALLOWED_LABELS:
        raise ValueError(
            f"strip_props label must be an operative L1 unit label ({sorted(L1_ALLOWED_LABELS)}), got {label!r}"
        )
    clause, params = _reconcile_identity_clause(identity, "id")
    keys = list(prop_keys or [])
    if not keys:
        raise ValueError("strip_props requires at least one prop key")
    for key in keys:
        if not (isinstance(key, str) and _SAFE_IDENT.match(key)):
            raise ValueError(f"strip_props: unsafe prop key {key!r}")
        if key in _RESERVED_PROPS:
            raise ValueError(f"strip_props: cannot strip reserved/identity prop {key!r}")
    unique_keys = sorted(set(keys))
    params["project_id"] = _PENDING_PROJECT_ID
    params.update(_prov_params(provenance))
    cypher = "\n".join([
        f"MATCH (n:{label} {{{clause}, project_id: $project_id}})",
        "REMOVE " + ", ".join(f"n.{k}" for k in unique_keys),
        "SET n.last_seen = datetime()",
        "SET n.prov_job = $prov_job, n.prov_model = $prov_model, n.prov_prompt_id = $prov_prompt_id",
    ])
    return cypher, params


def strip_props(
    project_id: str, ops: list[StripPropsOp] | None, *, merge_fn=None
) -> int:
    """Execute a batch of prop-strip ops (FR-TYPESEP-b), fail-open per op: one bad
    op (a non-L1 label, a bad/unsafe identity, a reserved/unsafe prop key, or a
    `merge_fn` exception) is skipped+logged and the batch continues - exactly like
    `reconcile`. Returns the count stripped. Every write is `:L1*` only."""
    merge_fn = _resolve_merge_fn(merge_fn)
    stripped = 0
    for op in ops or []:
        try:
            cypher, params = build_strip_props_cypher(op.label, op.identity, op.prop_keys, op.provenance)
        except ValueError:
            logger.warning("strip_props: skipping invalid op label=%r", getattr(op, "label", None), exc_info=True)
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("strip_props: strip failed", exc_info=True)
            continue
        stripped += 1
    return stripped
