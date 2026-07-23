"""FR-PODSTREAM: the batch-mode delivery/completeness guarantee for the analyser.

The analyser is a pure `f(L0-slice + observations) -> L1-deltas` (`L1D-22`). In the
batch-default substrate (`L1D-23`) it PULLS its input from the graph after the
recon phase barrier. This module makes that pull complete and non-duplicating:

  * every curated `AssetDelta` reaches the analyser via the L0-slice read
    (one node per identity, MERGE-deduped) - see `pod.default_read_fn`, which now
    EXCLUDES `Observation` nodes from the slice so they are not double-delivered;
  * every triager `Observation` reaches the analyser via the dedicated
    `observations` channel, deduped by the Observation `id` - `collect_observations`.

Delivery is at-least-once across runs (each pull re-reads the whole graph) made
safe by the analyser's idempotent MERGE writes. Streaming (push-at-recon-time)
stays deferred (`NM-7`); batch is the default (`L1D-23`).

Read-only; `read_fn` defaults to `polymerhus.app.clients.neo4j_client.read`, resolved
lazily so importing this module never constructs a live driver.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The Observation properties surfaced to the analyser's `observations` input - the
# triager's adversarial insight (macro_kind/severity/evidence/rationale) plus its
# provenance, keyed by the stable dedup `id`.
_OBS_FIELDS = ("id", "macro_kind", "severity", "evidence", "rationale", "source_job", "source_tool")


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def collect_observations(project_id: str, *, read_fn=None) -> list[dict]:
    """Return the project's triager `Observation` records for delivery to the
    analyser, DEDUPED by Observation `id` (the stable sha1 the curator MERGEs on),
    ordered by id for determinism. Each row is the observation's insight fields.
    Read-only; the Cypher DISTINCT-by-id plus the id-keyed dict make re-delivery
    idempotent at the input level."""
    read_fn = _resolve_read_fn(read_fn)
    rows = read_fn(
        "MATCH (o:Observation) WHERE o.project_id = $project_id "
        "RETURN o { .id, .macro_kind, .severity, .evidence, .rationale, "
        ".source_job, .source_tool } AS o ORDER BY o.id",
        {"project_id": project_id},
    )
    by_id: dict[str, dict] = {}
    for r in rows:
        o = dict(r.get("o") or {})
        oid = o.get("id")
        if oid is None or oid in by_id:
            continue  # dedup by id (defensive; the query is already 1 row per node)
        by_id[oid] = {k: o.get(k) for k in _OBS_FIELDS}
    return list(by_id.values())


def deliver_observations(project_id: str, *, read_fn=None) -> list[dict]:
    """Fail-open wrapper around `collect_observations`: a read failure degrades to
    an EMPTY delivery so the analyser still runs over the asset slice rather than
    crashing (mirrors the analyser pod's fail-open discipline)."""
    try:
        return collect_observations(project_id, read_fn=read_fn)
    except Exception:  # fail-open: never crash the analyser on a delivery read error
        logger.warning("deliver_observations: observation read failed for project=%s; "
                       "degrading to empty delivery", project_id, exc_info=True)
        return []
