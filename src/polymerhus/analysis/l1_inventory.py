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

from polymerhus.analysis.l1_types import elide_singleton
from polymerhus.analysis.overview import empty_overview, normalize_overview

logger = logging.getLogger(__name__)


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def _empty() -> dict:
    return {"services": [], "systems": [],
            "service_contracts": {}, "system_descriptions": {},
            "application_overview": empty_overview()}


def _render_system(row: dict) -> str:
    """Render a System identity as `kind` for a singleton, else `kind:disc`.
    A `__singleton__` discriminator (the non-null default, L1D-9) is elided so the
    reuse block shows the same shape the analyser must emit for a singleton."""
    kind = row.get("kind")
    disc = elide_singleton(row.get("disc"))
    if disc:
        return f"{kind}:{disc}"
    return kind


def read_application_overview(project_id: str, *, settings_fn=None) -> dict:
    """The project's normalized structured Overview, from settings ONLY.

    Settings-only by design (no graph read): the hunting sites call it once per
    dispatch / gate turn, where a full inventory read would be waste. Returns
    the normalized `{domain, description, journeys}` shape; a legacy prose
    value maps to `description`. Fail-open: any read error degrades to the
    empty shape and never raises."""
    if settings_fn is None:
        from polymerhus.app.clients import pg

        settings_fn = pg.load_settings
    try:
        value = (settings_fn(project_id) or {}).get("application_overview")
    except Exception:  # fail-open: no framing is better than a crash
        logger.warning("read application_overview failed for project=%s", project_id,
                       exc_info=True)
        return empty_overview()
    return normalize_overview(value)


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

    `application_overview` is the KB's macro framing (W-d, structured
    2026-10-17): the `## Overview` block the deterministic scaffold persists to
    `settings` when it writes the skeleton. It is NOT a graph node (operator
    decision: a skeleton attribute), so it is read from settings, not from a
    `:L1*` label, and normalized to `{domain, description, journeys}`. It is
    the framing the four item-consuming agents receive as a dedicated message
    (the Q4 model).

    Fail-open: any read error degrades to the empty inventory shape and never raises
    into the caller."""
    read_fn = _resolve_read_fn(read_fn)
    overview = read_application_overview(project_id, settings_fn=settings_fn)
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
    return {
        "services": services,
        "systems": systems,
        "service_contracts": contracts,
        "system_descriptions": system_descriptions,
        "application_overview": overview,
    }
