"""FR-INVENTORY: the current L1 identity inventory (at-write duplicate prevention).

The analyser drifts to synonym identities across passes (sign-in / signin / login)
because the "reuse the existing slug" hint relied on L1 nodes buried in a raw L0
slice dump. `read_l1_inventory` reads the CURRENT L1 identities cheaply so every
analyser prompt can pin them at the top as an explicit, un-truncated "reuse these
exact keys" block.

This is a READ helper (the write counterpart is `l1_curator`); it queries only the
`:L1*` namespace and never writes. `read_fn` defaults to
`polymerhus.app.clients.neo4j_client.read`, resolved lazily so importing this module
never constructs a live driver (mirrors `sweep.py` / `l1_read.py`).

Fail-open: a read error degrades to the empty inventory shape and never raises
into the caller (mirrors the analyser pod's degrade-to-empty discipline).
"""
from __future__ import annotations

import logging

from polymerhus.analysis.l1_curator import SYSTEM_EDGE_RELS
from polymerhus.analysis.l1_types import elide_singleton

logger = logging.getLogger(__name__)

# Keys that are identity / provenance / lifecycle BOOKKEEPING on an `:L1System`,
# never a "notable attribute" for the L1 graph block. `description` is excluded too:
# it is surfaced on its own line (`system_descriptions`). Mirrors
# `l1_curator._RESERVED_PROPS` minus the service-only `business_function_slug`.
_SYSTEM_BOOKKEEPING = frozenset({
    "project_id", "kind", "discriminator", "description",
    "first_seen", "last_seen", "prov_job", "prov_model", "prov_prompt_id",
})


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def _empty() -> dict:
    return {"services": [], "systems": [],
            "service_contracts": {}, "system_descriptions": {},
            "system_details": {}, "edges": [],
            "application_overview": ""}


def _render_system(row: dict) -> str:
    """Render a System identity as `kind` for a singleton, else `kind:disc`.
    A `__singleton__` discriminator (the non-null default, L1D-9) is elided so the
    reuse block shows the same shape the analyser must emit for a singleton."""
    kind = row.get("kind")
    disc = elide_singleton(row.get("disc"))
    if disc:
        return f"{kind}:{disc}"
    return kind


def _read_edges(read_fn, project_id: str) -> list[dict]:
    """The typed `Service -> System` edges of the project's L1 graph, filtered to
    the §6 `SYSTEM_EDGE_RELS` allowlist (imported, never duplicated) and shaped for
    the prompt block: `{service_slug, rel, system_key, role, realm, order}` with the
    `system_key` rendered by the same `_render_system` rule as the Systems list, so
    an edge's endpoint names the exact key a proposer must reuse. role/realm/order
    are None when unset (they ride the edge's props, L1D-21). Stable sort by
    (service_slug, rel, system_key, role, realm, order)."""
    edge_rows = read_fn(
        "MATCH (s:L1Service)-[r]->(y:L1System) "
        "WHERE s.project_id = $project_id AND y.project_id = $project_id "
        "RETURN s.business_function_slug AS service_slug, type(r) AS rel, "
        "y.kind AS kind, y.discriminator AS disc, "
        "r.role AS role, r.realm AS realm, r.order AS order",
        {"project_id": project_id},
    )
    edges = []
    for r in edge_rows:
        if r.get("rel") not in SYSTEM_EDGE_RELS or not r.get("service_slug") or not r.get("kind"):
            continue
        edges.append({
            "service_slug": r["service_slug"],
            "rel": r["rel"],
            "system_key": _render_system(r),
            "role": r.get("role"),
            "realm": r.get("realm"),
            "order": r.get("order"),
        })
    edges.sort(key=lambda e: (
        e["service_slug"], e["rel"], e["system_key"],
        e["role"] or "", e["realm"] or "",
        "" if e["order"] is None else str(e["order"]),
    ))
    return edges


def read_l1_inventory(project_id: str, *, read_fn=None, settings_fn=None) -> dict:
    """Return the project's current L1 identities as
    `{"services": [business_function_slug,...], "systems": ["kind" | "kind:disc",...],
    "service_contracts": {slug: service_contract}}`, each list sorted and deduped.

    `service_contracts` is ADDITIVE (#29): `services` stays a plain list of slugs, so
    the six existing call sites and the four prompts fed by `_inventory_block` are
    untouched, and a consumer that wants the routing profile reads the parallel map.
    Only Services that actually carry a contract appear in it - absence keeps meaning
    not-yet-filled.

    `system_descriptions` is the same ADDITIVE pattern for Systems (#9): the flat
    `systems` list is unchanged, and a consumer that wants the adversarial
    characterisation reads the parallel `{system_key: description}` map (keyed by the
    same `_render_system` shape). The mechanism-typist reads it to decide new-vs-extend
    and to COMPOUND the description on extension (grilled #9).

    `application_overview` is the KB's macro framing (W-d): the `## Overview`
    paragraph the deterministic scaffold persists to `settings` when it writes
    the skeleton. It is NOT a graph node (operator decision: a skeleton
    attribute), so it is read from settings, not from a `:L1*` label. It is the
    framing a proposer prepends to the Service it is reasoning about.

    `system_details` and `edges` are the L1-GRAPH additions (operator ruling
    2026-10-16): the Assigner's first human message POSTS the current graph, so the
    read surfaces a System's non-bookkeeping attributes (`system_details`, keyed by
    the same `_render_system` shape) and the typed `Service -> System` edges
    (`edges`, filtered to `l1_curator.SYSTEM_EDGE_RELS` - the allowlist is imported,
    never duplicated). Both are ADDITIVE to the existing keys; the flat
    `services`/`systems` lists and the `service_contracts`/`system_descriptions`
    maps are unchanged. A previous graph_view-capable Assigner degraded quality and
    bloated context (retained decision), so the graph is delivered as a prompt block
    from this per-dispatch read, never a tool the model calls.

    Fail-open: any read error degrades to the empty inventory shape and never raises
    into the caller. The EDGE read has its OWN try, so a failing edge query drops
    `edges` to [] without discarding the identity reads above it."""
    read_fn = _resolve_read_fn(read_fn)
    if settings_fn is None:
        from polymerhus.app.clients import pg

        settings_fn = pg.load_settings
    try:
        overview = (settings_fn(project_id) or {}).get("application_overview") or ""
    except Exception:  # fail-open: no framing is better than no inventory
        logger.warning("read application_overview failed for project=%s", project_id,
                       exc_info=True)
        overview = ""
    try:
        service_rows = read_fn(
            "MATCH (n:L1Service) WHERE n.project_id = $project_id "
            "RETURN n.business_function_slug AS slug, n.service_contract AS contract",
            {"project_id": project_id},
        )
        system_rows = read_fn(
            "MATCH (n:L1System) WHERE n.project_id = $project_id "
            "RETURN n.kind AS kind, n.discriminator AS disc, n.description AS description, "
            "properties(n) AS props",
            {"project_id": project_id},
        )
    except Exception:  # fail-open: a read error degrades to the empty inventory
        logger.warning("read_l1_inventory failed for project=%s; fail-open to empty", project_id, exc_info=True)
        return _empty()

    services = sorted({r.get("slug") for r in service_rows if r.get("slug")})
    systems = sorted({_render_system(r) for r in system_rows if r.get("kind")})
    contracts = {
        r["slug"]: r["contract"]
        for r in service_rows
        if r.get("slug") and (r.get("contract") or "").strip()
    }
    system_descriptions = {
        _render_system(r): r["description"]
        for r in system_rows
        if r.get("kind") and (r.get("description") or "").strip()
    }
    system_details = {}
    for r in system_rows:
        if not r.get("kind"):
            continue
        props = r.get("props") or {}
        details = {
            k: v for k, v in props.items()
            if k not in _SYSTEM_BOOKKEEPING and v is not None
        }
        if details:
            system_details[_render_system(r)] = details
    try:
        edges = _read_edges(read_fn, project_id)
    except Exception:  # fail-open: the graph block degrades to no edges
        logger.warning("read_l1_inventory edges failed for project=%s; fail-open to no edges",
                       project_id, exc_info=True)
        edges = []
    return {
        "services": services,
        "systems": systems,
        "service_contracts": contracts,
        "system_descriptions": system_descriptions,
        "system_details": system_details,
        "edges": edges,
        "application_overview": overview,
    }
