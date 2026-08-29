"""The sound unit-projection reader (#63, spec section 2.2; candidates-rewrite
spec section 3.6).

The unit projection is EXACTLY the unit's typed facets: the index-card spine
(key presence), the one-hop typed neighbour surface (per-family outgoing
Service->System edges with the target System's kind and the edge's role
presence), and the data axis (PRODUCES/CONSUMES counts, DataRelationship kinds
among the unit's items). Absence is not-yet-filled (the L1 convention): a
family with no edges simply has no entry - never a zero marker - so the
evaluation stage maps it to UNKNOWN (default-open), never FALSE (C12-b).

The candidates-rewrite (3.6) rebuilds this from the thin facet surface to the
RICH typed projection the L1 schema already supports: PRODUCES/CONSUMES edges
explode to the full DataItem node list (every property, not counts), each
outgoing Service->System edge unpacks its target System fully (kind,
discriminator, exposure, and the raw non-identity props), connected DataItems
resolve their relationship edges VERBATIM as kind chains (the edge type IS the
kind, L1D-13), and System units surface the System-to-System adjacency (D3):
their cooperating systems over the §6 System-edge families in both directions.
The legacy facet names (`kind`, `spine`, `edges`, `data_edges`,
`data_rel_kinds`) are unchanged so the predicate and consumers compile and pass
unchanged; the rich slots are additive.

The reader is pure mapping over the injectable raw read seam
(`(cypher, params) -> list[dict]`, the `neo4j_client.read` contract), resolved
lazily on first call like every read seam in this codebase (CODING_STANDARD
section 6). Traversal-then-fetch, one unit at a time: one read for the unit
row + its outgoing edges, one for the DataRelationship kind chains among the
unit's items, (System units only) one for the D3 cooperating-systems
adjacency, and one for the unit's aggregated L0 Endpoints over the native
`AGGREGATES` edge (#201 - a Service's own, a System's linked services' with
the owning service slug; L0 Headers out of scope). Every rich slot degrades
independently to empty (never a raise, never a prune signal - the #63/135
fail-open discipline).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from polymerhus.analysis.index_card import _SPINE_KEYS
from polymerhus.analysis.l1_curator import (
    DATA_RELATIONSHIP_KINDS,
    SYSTEM_EDGE_RELS,
    _DATA_FLOW_RELS,
)

# The validated DataRelationship edge types (kind uppercased - the edge type IS
# the kind, single-sourced per L1D-13/L1OP-2).
_DATA_REL_EDGE_TYPES = frozenset(k.upper() for k, _d in DATA_RELATIONSHIP_KINDS)
_DATA_EDGE_FAMILIES = frozenset(_DATA_FLOW_RELS.values())  # PRODUCES / CONSUMES
# The §6 System-edge families (L1D-18/L1D-21) the D3 cooperating-systems
# adjacency ranges over, both directions.
_SYSTEM_EDGE_RELS = frozenset(SYSTEM_EDGE_RELS)


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


@dataclass(frozen=True)
class DataItem:
    """A logical DataItem resolved from a PRODUCES/CONSUMES edge, every property
    carried (candidates-rewrite 3.6 defect 3): the semantic `item_key` plus the
    named trust slots when present (name/type/sensitivity, `fields`, `notes`)
    and the full raw non-identity props. Absent slots stay None/empty - absence
    is not-yet-filled, never a prune signal."""

    item_key: str | None = None
    name: str | None = None
    type: str | None = None
    sensitivity: str | None = None
    fields: tuple[str, ...] = ()
    notes: str | None = None
    props: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SystemInfo:
    """A System unpacked from its L1 node (candidates-rewrite 3.6 defect 3): the
    typed attributes the L1 System actually carries - `kind`, `discriminator`,
    `exposure`, the NL `description` - plus the full raw non-identity props
    (rendering_model / navigation_model / any trust-boundary facet the schema
    carries). Absent props stay None (not-yet-filled, fail-open). For a D3
    cooperating neighbor that is a served Service, kind=""Service"" and
    discriminator carries the business_function_slug."""

    kind: str = ""
    discriminator: str | None = None
    exposure: str | None = None
    description: str | None = None
    props: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeInfo:
    """One outgoing typed edge: the family (e.g. EXPOSED_VIA), the target
    System's kind, the edge's role attribute presence (L1D-21 rides
    sub-granularity on props; role is presence-only, never value-equal), and the
    full target-System unpack (`target`, absent when the hop fell short)."""

    family: str
    target_kind: str | None
    role: str | None = None
    target: SystemInfo | None = None


@dataclass(frozen=True)
class DataRelationship:
    """One functional-dependency edge between two of the unit's DataItems
    (L1D-13), resolved VERBATIM as a kind chain: `family` IS the edge type (the
    uppercased kind), with the ordered endpoints (when the walk saw them) and
    the machine-checkable predicate/rationale. Absent endpoint info stays None -
    absence is fail-open."""

    family: str
    from_item_key: str | None = None
    to_item_key: str | None = None
    from_item: DataItem | None = None
    to_item: DataItem | None = None
    predicate: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class AggregatedEndpoint:
    """One L0 Endpoint a unit aggregates via the native `AGGREGATES` edge
    (#201): the typed identity props (method/path/baseurl, present ones only)
    plus the owning service slug when the aggregate resolves through a System
    unit's LINKED services. Absent props stay None - absence is not-yet-filled,
    never a prune signal. L0 Headers are out of scope (they ride the BaseURLs
    linked to endpoints, never AGGREGATES)."""

    method: str | None = None
    path: str | None = None
    baseurl: str | None = None
    service_slug: str | None = None


@dataclass(frozen=True)
class UnitProjection:
    """The unit's typed facet surface (spec 2.2; rich slots per 3.6).

    `kind` is "Service" or a validated System kind. `spine` carries the PRESENT
    spine keys only. `edges` is family -> outgoing Service->System edges (empty
    for a System unit). `data_edges` is family -> count, `data_rel_kinds` the
    DataRelationship edge types among the unit's items. The rich slots are
    additive: `data_items` (family -> the full DataItem list of a data-flow
    edge), `data_relationships` (the ordered kind chains among the unit's
    items), and `cooperating_systems` (System units only: family -> the D3
    adjacency - the served Services + neighbouring Systems over the §6 System
    families, both directions; empty for a Service unit or when absent).
    `diagnostics` records malformation found at read time; the stage treats a
    projection carrying diagnostics as suspect and passes it (never prunes on a
    bug).
    """

    unit_id: str
    kind: str
    spine: Mapping[str, str]
    edges: Mapping[str, tuple[EdgeInfo, ...]]
    data_edges: Mapping[str, int]
    data_rel_kinds: frozenset[str]
    data_items: Mapping[str, tuple[DataItem, ...]] = field(default_factory=dict)
    data_relationships: tuple[DataRelationship, ...] = ()
    cooperating_systems: Mapping[str, tuple[SystemInfo, ...]] = field(default_factory=dict)
    aggregated_endpoints: tuple[AggregatedEndpoint, ...] = ()
    diagnostics: tuple[str, ...] = ()


def _identity_where(kind: str, key: str) -> str:
    """The L1 unit identity predicate (L1D-9/12): a Service is keyed on
    business_function_slug, a System on (kind, discriminator)."""
    if kind == "Service":
        return "(u:L1Service AND u.business_function_slug = $key)"
    return "(u:L1System AND u.kind = $kind AND u.discriminator = $key)"


def _split_unit_id(unit_id: str) -> tuple[str, str]:
    """Split the kind-qualified identity "<kind>:<key>" (a Service's
    business_function_slug, a System's kind+discriminator)."""
    if not isinstance(unit_id, str) or ":" not in unit_id:
        raise ValueError(f"unit_projection: malformed unit id {unit_id!r} "
                         f"(expected '<kind>:<key>')")
    kind, key = unit_id.split(":", 1)
    if not kind or not key:
        raise ValueError(f"unit_projection: malformed unit id {unit_id!r} "
                         f"(expected '<kind>:<key>')")
    return kind, key


def _data_item_from(tprops: dict) -> DataItem:
    """Pure: one DataItem record from a PRODUCES/CONSUMES target's props."""
    props = dict(tprops)
    return DataItem(
        item_key=props.get("item_key"),
        name=props.get("name"),
        type=props.get("type"),
        sensitivity=props.get("sensitivity"),
        fields=tuple(props.get("fields") or ()),
        notes=props.get("notes"),
        props=props,
    )


def _system_info_from(tprops: dict) -> SystemInfo:
    """Pure: one System unpack from a System node's props."""
    props = dict(tprops)
    return SystemInfo(
        kind=props.get("kind") or "",
        discriminator=props.get("discriminator"),
        exposure=props.get("exposure"),
        description=props.get("description"),
        props=props,
    )


def _aggregated_endpoint_from(tprops: dict) -> AggregatedEndpoint:
    """Pure: one AggregatedEndpoint from an L0 Endpoint node's props (the
    typed identity props, present ones only - absence is not-yet-filled)."""
    props = dict(tprops)
    return AggregatedEndpoint(
        method=props.get("method"),
        path=props.get("path"),
        baseurl=props.get("baseurl"),
    )


def _neighbor_info(tlabels, tprops: dict) -> SystemInfo:
    """Pure: one D3 cooperating neighbor from a System-edge hop's target node. A
    neighbouring System unpacks via `_system_info_from`; a served Service (the
    System is reached FROM it) is marked kind="Service" keyed by its slug."""
    props = dict(tprops)
    if "L1System" in (tlabels or []):
        return _system_info_from(props)
    return SystemInfo(
        kind="Service",
        discriminator=props.get("business_function_slug"),
        exposure=props.get("exposure"),
        description=props.get("service_contract"),
        props=props,
    )


def build_projection(project_id: str, unit_id: str, *, read_fn=None) -> UnitProjection | None:
    """Pure mapping: one unit's typed facets, via the injectable raw read seam.
    Returns None for an unknown unit (absence is not-yet-filled). Raises
    ValueError on a malformed unit id; the deterministic stage catches any
    reader failure and passes (fail-open, spec 2.4)."""
    read_fn = _resolve_read_fn(read_fn)
    kind, key = _split_unit_id(unit_id)
    where = _identity_where(kind, key)

    rows = read_fn(
        "MATCH (u:L1TestableUnit) "
        f"WHERE u.project_id = $project_id AND {where} "
        "OPTIONAL MATCH (u)-[r]->(m) "
        "RETURN labels(u) AS labels, properties(u) AS props, "
        "collect({family: type(r), tlabels: labels(m), "
        "tprops: properties(m), rprops: properties(r)}) AS edges",
        {"project_id": project_id, "kind": kind, "key": key},
    )
    if not rows:
        return None
    row = rows[0]

    labels = list(row.get("labels") or [])
    props = dict(row.get("props") or {})
    # The unit's kind FACET: "Service", or a System's own system kind (spec
    # 2.2 - System-anchored kind-is ranges over the unit's own kind). Unlike
    # the index-card's display kind, the projection surfaces the typed value.
    unit_kind = "Service" if "L1Service" in labels \
        else (props.get("kind") or "System") if "L1System" in labels else "Unit"
    # PRESENT spine keys only; a None prop is not-yet-filled (absent), never a
    # typed value - presence is what the spine-present clause ranges over.
    spine = {k: props[k] for k in _SPINE_KEYS if k in props and props[k] is not None}

    diagnostics: list[str] = []
    edges: dict[str, list[EdgeInfo]] = {}
    data_edges: dict[str, int] = {}
    data_items: dict[str, list[DataItem]] = {}
    for edge in row.get("edges") or []:
        family = edge.get("family") if isinstance(edge, dict) else None
        if not family:
            continue
        tprops = dict(edge.get("tprops") or {})
        rprops = dict(edge.get("rprops") or {})
        if family in _DATA_EDGE_FAMILIES:
            # defect 3: the data-flow edge resolves to the FULL DataItem node
            # list (every property), never just a count - the count stays for
            # the predicate's data-edge-exists clause.
            data_edges[family] = data_edges.get(family, 0) + 1
            data_items.setdefault(family, []).append(_data_item_from(tprops))
            continue
        if "L1System" in (edge.get("tlabels") or []):
            edges.setdefault(family, []).append(EdgeInfo(
                family=family,
                target_kind=tprops.get("kind"),
                role=rprops.get("role"),
                target=_system_info_from(tprops),
            ))

    # The DataRelationship kind chains among the unit's items, resolved
    # VERBATIM (the edge type IS the kind, L1D-13) with the ordered endpoints.
    # RETURN DISTINCT orders deterministically (family, from_key, to_key - all
    # returned columns), so the kind chains render in stable order (T5).
    data_rel_rows = read_fn(
        "MATCH (u:L1TestableUnit) "
        f"WHERE u.project_id = $project_id AND {where} "
        "MATCH (u)-[:PRODUCES|CONSUMES]->(item:L1DataItem) "
        "MATCH (u)-[:PRODUCES|CONSUMES]->(other:L1DataItem) "
        "MATCH (item)-[dr]->(other) "
        "RETURN DISTINCT type(dr) AS family, item.item_key AS from_key, "
        "other.item_key AS to_key, properties(dr) AS rprops "
        "ORDER BY family, from_key, to_key",
        {"project_id": project_id, "kind": kind, "key": key},
    )
    data_rel_kinds = frozenset(
        r["family"] for r in data_rel_rows
        if r.get("family") in _DATA_REL_EDGE_TYPES
    )
    data_relationships: list[DataRelationship] = []
    for r in data_rel_rows:
        family = r.get("family")
        if family not in _DATA_REL_EDGE_TYPES:
            continue
        rprops = dict(r.get("rprops") or {})
        from_key = r.get("from_key")
        to_key = r.get("to_key")
        data_relationships.append(DataRelationship(
            family=family,
            from_item_key=from_key,
            to_item_key=to_key,
            from_item=_lookup_item(from_key, data_items),
            to_item=_lookup_item(to_key, data_items),
            predicate=rprops.get("predicate"),
            rationale=rprops.get("rationale"),
        ))

    # D3 (candidates-rewrite 3.6 Q3): the System-to-System adjacency, ONLY for
    # a System unit - System-strict hunts see their cooperating systems over the
    # §6 System-edge families in both directions. Absent/empty degrades to an
    # empty slot, never a prune signal.
    cooperating_systems: dict[str, list[SystemInfo]] = {}
    if unit_kind != "Service":
        adj_rows = read_fn(
            "MATCH (u:L1TestableUnit) "
            f"WHERE u.project_id = $project_id AND {where} "
            "OPTIONAL MATCH (n)-[r]->(u) WHERE type(r) IN $sys_rels "
            "WITH u, collect({family: type(r), nlabels: labels(n), "
            "nprops: properties(n)}) AS ins "
            "OPTIONAL MATCH (u)-[r2]->(m) WHERE type(r2) IN $sys_rels "
            "RETURN collect({family: type(r2), nlabels: labels(m), "
            "nprops: properties(m)}) AS cooperating_outs, ins",
            {"project_id": project_id, "kind": kind, "key": key,
             "sys_rels": sorted(_SYSTEM_EDGE_RELS)},
        )
        for row_ in adj_rows:
            ins = row_.get("ins") or []
            outs = row_.get("cooperating_outs") or []
            for adj in [*ins, *outs]:
                family = adj.get("family") if isinstance(adj, dict) else None
                if not family:
                    continue
                nprops = dict(adj.get("nprops") or {})
                nlabels = list(adj.get("nlabels") or [])
                # a Service as the System's own identity is never a cooperator
                if "L1System" in nlabels and nprops.get("kind") == unit_kind \
                        and nprops.get("discriminator") == key:
                    continue
                cooperating_systems.setdefault(family, []).append(
                    _neighbor_info(nlabels, nprops))

    # #201: the unit's aggregated L0 Endpoints over the native `AGGREGATES`
    # edge (the L0 expansion for the agent). A Service unit aggregates its OWN
    # Endpoints; a System unit surfaces the Endpoints its LINKED services
    # aggregate (the system contract - each entry carries the owning service
    # slug). Scoped to the target unit's identity only - never the whole
    # surface (DD-4); L0 Headers are out of scope (they ride the BaseURLs
    # linked to endpoints, never AGGREGATES). A failing read degrades ONLY this
    # slot to empty + a diagnostic - never a raise, never a prune signal.
    aggregated_endpoints: list[AggregatedEndpoint] = []
    try:
        if unit_kind == "Service":
            agg_rows = read_fn(
                "MATCH (s:L1Service {business_function_slug: $key, "
                "project_id: $project_id})-[:AGGREGATES]->(e:Endpoint) "
                "RETURN e {.*} AS props "
                "ORDER BY e.baseurl, e.method, e.path",
                {"project_id": project_id, "kind": kind, "key": key},
            )
            aggregated_endpoints = [
                _aggregated_endpoint_from(row.get("props") or {})
                for row in agg_rows
            ]
        else:
            agg_rows = read_fn(
                "MATCH (:L1System {kind: $kind, discriminator: $key, "
                "project_id: $project_id})<-[r]-(s:L1Service)"
                "-[:AGGREGATES]->(e:Endpoint) "
                "WHERE type(r) IN $sys_rels "
                "RETURN s.business_function_slug AS slug, e {.*} AS props "
                "ORDER BY s.business_function_slug, e.baseurl, e.method, e.path",
                {"project_id": project_id, "kind": kind, "key": key,
                 "sys_rels": sorted(_SYSTEM_EDGE_RELS)},
            )
            aggregated_endpoints = [
                AggregatedEndpoint(
                    method=props.get("method"),
                    path=props.get("path"),
                    baseurl=props.get("baseurl"),
                    service_slug=row.get("slug"),
                )
                for row in agg_rows
                for props in [dict(row.get("props") or {})]
            ]
    except Exception as exc:  # noqa: BLE001 - fail-open: degrade the slot only
        diagnostics.append(f"aggregated_endpoints read degraded: {exc}")

    # Deterministic render ordering regardless of DB ordering: sort the slot by
    # (baseurl, method, path, service_slug) so the projection's aggregates are
    # stable across reads.
    aggregated_endpoints.sort(
        key=lambda ep: (ep.baseurl or "", ep.method or "", ep.path or "",
                        ep.service_slug or ""))

    return UnitProjection(
        unit_id=unit_id,
        kind=unit_kind,
        spine=spine,
        edges={f: tuple(e) for f, e in edges.items()},
        data_edges=dict(data_edges),
        data_rel_kinds=data_rel_kinds,
        data_items={f: tuple(items) for f, items in data_items.items()},
        data_relationships=tuple(data_relationships),
        cooperating_systems={f: tuple(s) for f, s in cooperating_systems.items()},
        aggregated_endpoints=tuple(aggregated_endpoints),
        diagnostics=tuple(diagnostics),
    )


def _lookup_item(item_key, data_items: dict) -> DataItem | None:
    """Best-effort join of a relationship endpoint onto the unit's data items
    (both endpoints are restricted to the unit's items, so a miss is unusual and
    degrades that slot only - never a raise)."""
    if item_key is None:
        return None
    for items in data_items.values():
        for item in items:
            if item.item_key == item_key:
                return item
    return None
