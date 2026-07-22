"""FR-INVENTORY: the current L1 identity inventory (at-write duplicate prevention).

The analyser drifts to synonym identities across passes (sign-in / signin / login)
because the "reuse the existing slug" hint relied on L1 nodes buried in a raw L0
slice dump that the data-modelling pass drops entirely. `read_l1_inventory` reads
the CURRENT L1 identities cheaply so every analyser prompt can pin them at the top
as an explicit, un-truncated "reuse these exact keys" block.

This is a READ helper (the write counterpart is `l1_curator`); it queries only the
`:L1*` namespace and never writes. `read_fn` defaults to
`agent.app.clients.neo4j_client.read`, resolved lazily so importing this module
never constructs a live driver (mirrors `sweep.py` / `l1_read.py`).

Fail-open: a read error degrades to the empty inventory shape and never raises
into the caller (mirrors the analyser pod's degrade-to-empty discipline).
"""
from __future__ import annotations

import logging

from agent.recon.analysis.l1_types import L1_SINGLETON

logger = logging.getLogger(__name__)


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from agent.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def _empty() -> dict:
    return {"services": [], "systems": [], "data_items": []}


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
    "data_items": [item_key,...]}`, each list sorted and deduped.

    Fail-open: any read error degrades to `{"services": [], "systems": [],
    "data_items": []}` and never raises into the caller."""
    read_fn = _resolve_read_fn(read_fn)
    try:
        service_rows = read_fn(
            "MATCH (n:L1Service) WHERE n.project_id = $project_id "
            "RETURN n.business_function_slug AS slug",
            {"project_id": project_id},
        )
        system_rows = read_fn(
            "MATCH (n:L1System) WHERE n.project_id = $project_id "
            "RETURN n.kind AS kind, n.discriminator AS disc",
            {"project_id": project_id},
        )
        data_rows = read_fn(
            "MATCH (n:L1DataItem) WHERE n.project_id = $project_id "
            "RETURN n.item_key AS item_key",
            {"project_id": project_id},
        )
    except Exception:  # fail-open: a read error degrades to the empty inventory
        logger.warning("read_l1_inventory failed for project=%s; fail-open to empty", project_id, exc_info=True)
        return _empty()

    services = sorted({r.get("slug") for r in service_rows if r.get("slug")})
    systems = sorted({_render_system(r) for r in system_rows if r.get("kind")})
    data_items = sorted({r.get("item_key") for r in data_rows if r.get("item_key")})
    return {"services": services, "systems": systems, "data_items": data_items}
