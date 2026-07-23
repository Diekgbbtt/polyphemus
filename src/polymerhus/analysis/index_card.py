"""FR-INDEXCARD: the token-light index-card projection + DFS-down (L1D-27 / DD-4).

Two read shapes drive the L1 outer analysis loop:

  * BFS reads **index-cards** - a compact per-unit projection carrying the typed
    spine, NL handles, and **edge-degree by family** (counts), NOT the raw member
    set. Iterating every unit while pulling its full aggregated member set would
    blow the token budget (DD-4); a Service that AGGREGATES tens of thousands of
    L0 elements has a card whose `edge_degree.AGGREGATES` is a single integer.
    Depth is fetched only for the unit currently under analysis.
  * DFS-down is one typed hop per edge family (Service -> its Systems/DataItems),
    fetched lazily for the unit under analysis.

Read-only; the write counterpart is `l1_curator`. `read_fn` defaults to
`polymerhus.app.clients.neo4j_client.read`, resolved lazily.
"""
from __future__ import annotations

import re
from collections import Counter

# `\Z` (absolute end) not `$`, so a trailing newline cannot slip past the guard.
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")

# The typed spine slots surfaced on the card (§5.1). Present ones are lifted into
# `spine`; the rest of the unit's own props become `nl_handles`.
_SPINE_KEYS = (
    "api_paradigm", "navigation_model", "rendering_model", "auth_methods",
    "exposure", "business_function",
)

# Identity + curator-managed keys, never surfaced as NL handles.
_MANAGED_KEYS = frozenset({
    "project_id", "business_function_slug", "kind", "discriminator",
    "first_seen", "last_seen", "prov_job", "prov_model", "prov_prompt_id",
})


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def _card_from_row(row: dict) -> dict:
    """Pure: build one index-card from a projected unit row `{labels, props,
    rels}`. `rels` is the list of outgoing edge types (with duplicates); it is
    reduced to a per-family DEGREE count - the member nodes themselves are never
    carried."""
    labels = list(row.get("labels") or [])
    props = dict(row.get("props") or {})
    rels = [t for t in (row.get("rels") or []) if t]

    kind = "Service" if "L1Service" in labels else "System" if "L1System" in labels else "Unit"
    if kind == "Service":
        key: dict = {"business_function_slug": props.get("business_function_slug")}
        label = props.get("business_function_slug")
    elif kind == "System":
        key = {"kind": props.get("kind"), "discriminator": props.get("discriminator")}
        label = props.get("kind")
    else:
        key, label = {}, None

    spine = {k: props[k] for k in _SPINE_KEYS if k in props}
    nl_handles = {
        k: v for k, v in props.items()
        if k not in _MANAGED_KEYS and k not in _SPINE_KEYS
    }
    return {
        "kind": kind,
        "key": key,
        "label": label,
        "spine": spine,
        # edge-degree BY FAMILY (counts), never the member set (DD-4 token discipline)
        "edge_degree": dict(Counter(rels)),
        "salience": props.get("salience") or props.get("label"),
        "nl_handles": nl_handles,
    }


def index_cards(project_id: str, *, read_fn=None) -> list[dict]:
    """Return one token-light index-card per L1 unit (Service + System) in the
    project. Each card carries the unit's own spine/NL props + edge-degree by
    family - never the aggregated member set (DD-4). OPTIONAL MATCH keeps
    zero-degree units (a freshly-bootstrapped Service with no members yet)."""
    read_fn = _resolve_read_fn(read_fn)
    rows = read_fn(
        "MATCH (u:L1TestableUnit) WHERE u.project_id = $project_id "
        "OPTIONAL MATCH (u)-[r]->() "
        "RETURN labels(u) AS labels, properties(u) AS props, collect(type(r)) AS rels",
        {"project_id": project_id},
    )
    return [_card_from_row(r) for r in rows]


def dfs_down(project_id: str, business_function_slug: str, rel: str, *, read_fn=None) -> list[dict]:
    """One typed hop down from a Service via edge family `rel` (e.g. EXPOSED_VIA,
    AUTHORIZED_BY, CONSUMES): return the neighbouring L1 nodes. Fetched lazily for
    the unit under analysis (not in the BFS hot loop). Raises ValueError on an
    unsafe rel label."""
    read_fn = _resolve_read_fn(read_fn)
    if not isinstance(rel, str) or not _SAFE_IDENT.match(rel):
        raise ValueError(f"dfs_down: unsafe relationship label {rel!r}")
    rows = read_fn(
        f"MATCH (:L1Service {{business_function_slug: $slug, project_id: $project_id}})"
        f"-[r:{rel}]->(m) "
        "RETURN labels(m) AS labels, properties(m) AS props",
        {"slug": business_function_slug, "project_id": project_id},
    )
    return [{"labels": list(r.get("labels") or []), "props": dict(r.get("props") or {})} for r in rows]
