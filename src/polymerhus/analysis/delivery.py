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

# The broad anchor an Observation is attached to via `(anchor)-[:HAS_OBSERVATION]->(o)`,
# and the identity key(s) picking out each anchor node's identity (curator
# ANCHOR_ALLOWLIST). The anchor is a RELATIONSHIP, not a node prop, so it must be
# re-materialised here into the `{type, identity}` shape the chunk/typist match on -
# without it every delivered observation is anchorless and matches nothing (the
# silent-empty-insight defect).
_ANCHOR_IDENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "Domain": ("name",),
    "Subdomain": ("name",),
    "BaseURL": ("url",),
    "IP": ("address",),
    "Service": ("name", "ip_address", "port_number"),
}


def _anchor_from(labels: list | None, props: dict | None) -> dict:
    """Rebuild the `{type, identity}` anchor from the HAS_OBSERVATION anchor node's
    labels + identity props. Empty dict when no broad anchor is attached (defensive;
    curation always attaches exactly one allowlisted anchor)."""
    props = props or {}
    for t in _ANCHOR_IDENTITY_KEYS:
        if labels and t in labels:
            identity = {k: props[k] for k in _ANCHOR_IDENTITY_KEYS[t] if props.get(k) is not None}
            return {"type": t, "identity": identity}
    return {}


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
        "OPTIONAL MATCH (anchor)-[:HAS_OBSERVATION]->(o) "
        "  WHERE any(l IN labels(anchor) WHERE l IN $anchor_labels) "
        "RETURN o { .id, .macro_kind, .severity, .evidence, .rationale, "
        ".source_job, .source_tool } AS o, "
        "labels(anchor) AS anchor_labels, "
        "anchor { .name, .url, .address, .ip_address, .port_number } AS anchor_props "
        "ORDER BY o.id",
        {"project_id": project_id, "anchor_labels": list(_ANCHOR_IDENTITY_KEYS)},
    )
    by_id: dict[str, dict] = {}
    for r in rows:
        o = dict(r.get("o") or {})
        oid = o.get("id")
        if oid is None or oid in by_id:
            continue  # dedup by id (an obs with >1 anchor row keeps the first)
        rec = {k: o.get(k) for k in _OBS_FIELDS}
        rec["anchor"] = _anchor_from(r.get("anchor_labels"), r.get("anchor_props"))
        by_id[oid] = rec
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
