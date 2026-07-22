"""Layer-1 read helpers: traversal-then-fetch across the layer boundary (DD-4).

The outer L1 analysis loop reads L1 nodes/cards (cheap); the L0 elements a
Service aggregates are fetched *lazily* by traversing the native `AGGREGATES`
edge only when concrete assets are needed (L1D-2 / L1D-32, spec §1.3 "cross-layer
edges are lazy fetch edges"). This module is the read counterpart of the
write-only `l1_curator` (mirroring how L0 splits `curator` (write) from
`graph_read` (read)).

`read_fn` defaults to `agent.app.clients.neo4j_client.read`, resolved lazily so
importing this module never constructs a live driver.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from agent.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def read_aggregated_l0(service_slug: str, project_id: str, *, read_fn=None) -> list[dict]:
    """Return the L0 nodes a Service AGGREGATES, by traversing the native
    `AGGREGATES` edge (the lazy cross-layer fetch hop). Each result is the L0
    node's property map plus a `_labels` key with its L0 labels. The traversal
    stays in one hop; nothing reconstructs an L0 key on the L1 side."""
    read_fn = _resolve_read_fn(read_fn)
    rows = read_fn(
        "MATCH (:L1Service {business_function_slug: $slug, project_id: $project_id})"
        "-[:AGGREGATES]->(l0) "
        "RETURN l0 {.*} AS props, labels(l0) AS labels",
        {"slug": service_slug, "project_id": project_id},
    )
    out: list[dict] = []
    for row in rows:
        props = dict(row.get("props") or {})
        props["_labels"] = list(row.get("labels") or [])
        out.append(props)
    return out
