"""The sound unit-projection reader (#63, spec section 2.2).

The unit projection is EXACTLY the unit's typed facets: the index-card spine
(key presence), the one-hop typed neighbour surface (per-family outgoing
Service->System edges with the target System's kind and the edge's role
presence), and the data axis (PRODUCES/CONSUMES counts, DataRelationship kinds
among the unit's items). Absence is not-yet-filled (the L1 convention): a
family with no edges simply has no entry - never a zero marker - so the
evaluation stage maps it to UNKNOWN (default-open), never FALSE (C12-b).

The reader is pure mapping over the injectable raw read seam
(`(cypher, params) -> list[dict]`, the `neo4j_client.read` contract), resolved
lazily on first call like every read seam in this codebase (CODING_STANDARD
section 6). The analysis read seams (`index_cards`, `dfs_down`,
`index_card.py:86-115`) do NOT surface per-edge target kinds or rel props,
which the grammar's `reachable-via(family, {kind}, role?)` facet ranges over
(L1D-21 sub-granularity rides on edge props), so this reader is its own
read-only hop in the hunting context - it never writes (section 4: the L1
store's sole-writer is untouched).

Traversal-then-fetch, one unit at a time: ONE read for the unit row plus its
outgoing edges, ONE for the DataRelationship kinds among the unit's items
(both endpoints restricted to the unit's items - "among the unit's items").
The System-to-Services inverse hop (D3) does not exist yet; System units
therefore surface no outgoing edges, which is the honest typed surface of the
current L1 (spec section 3, D3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from polymerhus.analysis.index_card import _SPINE_KEYS
from polymerhus.analysis.l1_curator import (
    DATA_RELATIONSHIP_KINDS,
    _DATA_FLOW_RELS,
)

# The validated DataRelationship edge types (kind uppercased - the edge type IS
# the kind, single-sourced per L1D-13/L1OP-2).
_DATA_REL_EDGE_TYPES = frozenset(k.upper() for k, _d in DATA_RELATIONSHIP_KINDS)
_DATA_EDGE_FAMILIES = frozenset(_DATA_FLOW_RELS.values())  # PRODUCES / CONSUMES


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


@dataclass(frozen=True)
class EdgeInfo:
    """One outgoing typed edge: the family (e.g. EXPOSED_VIA), the target
    System's kind, and the edge's role attribute presence (L1D-21 rides
    sub-granularity on props; role is presence-only, never value-equal)."""

    family: str
    target_kind: str | None
    role: str | None = None


@dataclass(frozen=True)
class UnitProjection:
    """The unit's typed facet surface (spec 2.2).

    `kind` is "Service" or a validated System kind. `spine` carries the PRESENT
    spine keys only. `edges` is family -> outgoing Service->System edges
    (empty for a System unit: the inverse hop D3 is unlanded). `data_edges` is
    family -> count for PRODUCES/CONSUMES. `data_rel_kinds` is the
    DataRelationship edge types among the unit's items. `diagnostics` records
    malformation found at read time; the stage treats a projection carrying
    diagnostics as suspect and passes it (never prunes on a bug).
    """

    unit_id: str
    kind: str
    spine: Mapping[str, str]
    edges: Mapping[str, tuple[EdgeInfo, ...]]
    data_edges: Mapping[str, int]
    data_rel_kinds: frozenset[str]
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
    for edge in row.get("edges") or []:
        family = edge.get("family") if isinstance(edge, dict) else None
        if not family:
            continue
        tprops = dict(edge.get("tprops") or {})
        rprops = dict(edge.get("rprops") or {})
        if family in _DATA_EDGE_FAMILIES:
            data_edges[family] = data_edges.get(family, 0) + 1
            continue
        if "L1System" in (edge.get("tlabels") or []):
            edges.setdefault(family, []).append(EdgeInfo(
                family=family,
                target_kind=tprops.get("kind"),
                role=rprops.get("role"),
            ))

    data_rel_rows = read_fn(
        "MATCH (u:L1TestableUnit) "
        f"WHERE u.project_id = $project_id AND {where} "
        "MATCH (u)-[:PRODUCES|CONSUMES]->(item:L1DataItem) "
        "MATCH (u)-[:PRODUCES|CONSUMES]->(other:L1DataItem) "
        "MATCH (item)-[dr]->(other) "
        "RETURN DISTINCT type(dr) AS family",
        {"project_id": project_id, "kind": kind, "key": key},
    )
    data_rel_kinds = frozenset(
        r["family"] for r in data_rel_rows
        if r.get("family") in _DATA_REL_EDGE_TYPES
    )

    return UnitProjection(
        unit_id=unit_id,
        kind=unit_kind,
        spine=spine,
        edges={f: tuple(e) for f, e in edges.items()},
        data_edges=dict(data_edges),
        data_rel_kinds=data_rel_kinds,
        diagnostics=tuple(diagnostics),
    )
