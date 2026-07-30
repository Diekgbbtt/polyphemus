"""FR-INVENTORY: the current L1 identity inventory (at-write duplicate prevention).

The analyser drifts to synonym identities across passes (sign-in / signin / login)
because the "reuse the existing slug" hint relied on L1 nodes buried in a raw L0
slice dump that the data-modelling pass drops entirely. `read_l1_inventory` reads
the CURRENT L1 identities cheaply so every analyser prompt can pin them at the top
as an explicit, un-truncated "reuse these exact keys" block.

This is a READ helper (the write counterpart is `l1_curator`); it queries only the
`:L1*` namespace and never writes. `read_fn` defaults to
`polymerhus.app.clients.neo4j_client.read`, resolved lazily so importing this module
never constructs a live driver (mirrors `sweep.py` / `l1_read.py`).

Fail-open: a read error degrades to the empty inventory shape and never raises
into the caller (mirrors the analyser pod's degrade-to-empty discipline).
"""
from __future__ import annotations

import logging

from polymerhus.analysis.l1_types import L1_SINGLETON

logger = logging.getLogger(__name__)


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def _empty() -> dict:
    return {"services": [], "systems": [], "data_items": [],
            "service_contracts": {}, "system_descriptions": {},
            "data_item_fields": {}, "data_item_notes": {}}


def _render_system(row: dict) -> str:
    """Render a System identity as `kind` for a singleton, else `kind:disc`.
    A `__singleton__` discriminator (the non-null default, L1D-9) is elided so the
    reuse block shows the same shape the analyser must emit for a singleton."""
    kind = row.get("kind")
    disc = row.get("disc")
    if disc and disc != L1_SINGLETON:
        return f"{kind}:{disc}"
    return kind


def read_l1_inventory(project_id: str, *, read_fn=None) -> dict:
    """Return the project's current L1 identities as
    `{"services": [business_function_slug,...], "systems": ["kind" | "kind:disc",...],
    "data_items": [item_key,...], "service_contracts": {slug: service_contract}}`,
    each list sorted and deduped.

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

    `data_item_fields` (`{item_key: [field, ...]}`) and `data_item_notes`
    (`{item_key: notes}`) are the SAME additive pattern for DataItems (#48,
    dataplane-A1-decisions.md DPL-DEC-08/09): the flat `data_items` list stays
    unchanged, and the data-modeller reads the parallel maps to UNION its proposed
    `fields` with what is already persisted (so a re-proposal can never shrink the
    observed set) and to decide reuse-vs-coin against each item's discriminative
    `notes`.

    Fail-open: any read error degrades to the empty inventory shape and never raises
    into the caller."""
    read_fn = _resolve_read_fn(read_fn)
    try:
        service_rows = read_fn(
            "MATCH (n:L1Service) WHERE n.project_id = $project_id "
            "RETURN n.business_function_slug AS slug, n.service_contract AS contract",
            {"project_id": project_id},
        )
        system_rows = read_fn(
            "MATCH (n:L1System) WHERE n.project_id = $project_id "
            "RETURN n.kind AS kind, n.discriminator AS disc, n.description AS description",
            {"project_id": project_id},
        )
        data_rows = read_fn(
            "MATCH (n:L1DataItem) WHERE n.project_id = $project_id "
            "RETURN n.item_key AS item_key, n.fields AS fields, n.notes AS notes",
            {"project_id": project_id},
        )
    except Exception:  # fail-open: a read error degrades to the empty inventory
        logger.warning("read_l1_inventory failed for project=%s; fail-open to empty", project_id, exc_info=True)
        return _empty()

    services = sorted({r.get("slug") for r in service_rows if r.get("slug")})
    systems = sorted({_render_system(r) for r in system_rows if r.get("kind")})
    data_items = sorted({r.get("item_key") for r in data_rows if r.get("item_key")})
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
    data_item_fields = {
        r["item_key"]: list(r["fields"])
        for r in data_rows
        if r.get("item_key") and r.get("fields")
    }
    data_item_notes = {
        r["item_key"]: r["notes"]
        for r in data_rows
        if r.get("item_key") and (r.get("notes") or "").strip()
    }
    return {
        "services": services,
        "systems": systems,
        "data_items": data_items,
        "service_contracts": contracts,
        "system_descriptions": system_descriptions,
        "data_item_fields": data_item_fields,
        "data_item_notes": data_item_notes,
    }
