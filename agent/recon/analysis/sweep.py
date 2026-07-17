"""FR-SWEEP: the end-of-phase sweeps (L1D-24).

Two DERIVED queries, run once the recon phase-barrier clears (spec §7.2 step 6) -
neither is a stored table; both are computed from the sole-writer + MERGE
guarantees:

  * stale_pool: assignable L0 assets with **no inbound AGGREGATES edge** - the
    assets the analyser did not confidently assign to any Service (the §15
    `/healthz` case). A derived query, not a structure (L1D-24).
  * missing_system_kinds: `SystemKind` catalogue rows with **no instantiated
    :L1System** (nothing `OF_KIND` them) - the system kinds not yet identified on
    this target, for the best-effort missing-systems sweep over the registry.

Read-only; the write counterpart is `l1_curator`. `read_fn` defaults to
`agent.app.clients.neo4j_client.read`, resolved lazily so importing this module
never constructs a live driver.
"""
from __future__ import annotations

import re

# Interpolated into Cypher (Neo4j cannot parameterise a label), so validate as a
# strict identifier first - defence in depth, mirroring l1_curator._SAFE_IDENT.
# `\Z` (absolute end) not `$`, so a trailing newline cannot slip past the guard.
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")

# The L0 labels a Service can aggregate. `Endpoint` is the primary assignable
# asset (the §15 walkthrough assigns endpoints; a stray `/healthz` falls to the
# stale pool). Headers/Technologies/Certificates are System EVIDENCED_BY evidence,
# not Service members, so they are excluded from the stale pool by default. The
# caller may widen the set for a project whose surface aggregates other labels.
DEFAULT_ASSIGNABLE_LABELS: tuple[str, ...] = ("Endpoint",)


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from agent.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def stale_pool(
    project_id: str,
    *,
    labels: tuple[str, ...] = DEFAULT_ASSIGNABLE_LABELS,
    read_fn=None,
) -> list[dict]:
    """Return the assignable L0 nodes of `labels` with no inbound AGGREGATES edge
    (the derived stale set). Each row is the L0 node's property map plus a
    `_label` key naming its L0 label. Raises ValueError on an unsafe label."""
    read_fn = _resolve_read_fn(read_fn)
    out: list[dict] = []
    for label in labels:
        if not isinstance(label, str) or not _SAFE_IDENT.match(label):
            raise ValueError(f"stale_pool: unsafe L0 label {label!r}")
        rows = read_fn(
            f"MATCH (n:{label}) WHERE n.project_id = $project_id "
            "AND NOT ( (:L1Service)-[:AGGREGATES]->(n) ) "
            "RETURN n {.*} AS props",
            {"project_id": project_id},
        )
        for r in rows:
            props = dict(r.get("props") or {})
            props["_label"] = label
            out.append(props)
    return out


def stale_pool_count(
    project_id: str,
    *,
    labels: tuple[str, ...] = DEFAULT_ASSIGNABLE_LABELS,
    read_fn=None,
) -> int:
    """Count of the stale set (cheaper than materialising it for a summary)."""
    read_fn = _resolve_read_fn(read_fn)
    total = 0
    for label in labels:
        if not isinstance(label, str) or not _SAFE_IDENT.match(label):
            raise ValueError(f"stale_pool_count: unsafe L0 label {label!r}")
        rows = read_fn(
            f"MATCH (n:{label}) WHERE n.project_id = $project_id "
            "AND NOT ( (:L1Service)-[:AGGREGATES]->(n) ) "
            "RETURN count(n) AS c",
            {"project_id": project_id},
        )
        total += rows[0]["c"] if rows else 0
    return total


def missing_system_kinds(project_id: str, *, read_fn=None) -> list[str]:
    """Return the `SystemKind` catalogue ids with no instantiated :L1System
    (nothing OF_KIND them) - the system kinds unrepresented on this target. The
    best-effort missing-systems sweep iterates the registry, not a hardcoded
    list, so it tracks the extensible SystemKind vocabulary automatically."""
    read_fn = _resolve_read_fn(read_fn)
    rows = read_fn(
        "MATCH (k:SystemKind) WHERE k.project_id = $project_id "
        "AND NOT ( (:L1System)-[:OF_KIND]->(k) ) "
        "RETURN k.id AS id ORDER BY id",
        {"project_id": project_id},
    )
    return [r["id"] for r in rows]
