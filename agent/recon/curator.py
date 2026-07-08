"""Generic curator: turns typed AssetDelta/Observation records into parameterised
Neo4j MERGE Cypher and executes them.

This module is the ONLY graph-write path for recon assets (design §10.6).
`build_asset_cypher`/`build_observation_cypher` are pure - they never touch a
driver. `curate` is the impure orchestrator: it injects `project_id`, calls
`merge_fn` per item, and skips+logs single-item failures so one bad delta
never aborts a whole batch.

`merge_fn` defaults to `agent.app.clients.neo4j_client.merge`, resolved lazily
inside `curate` so importing this module (or unit-testing the pure builders)
never constructs a live Neo4j driver.
"""
from __future__ import annotations

import hashlib
import json
import logging

from agent.recon.types import AssetDelta, Edge, Observation

logger = logging.getLogger(__name__)

# Layer-0 node labels (design §10.3), excluding Observation which is written
# only via build_observation_cypher.
ALLOWED_LABELS = frozenset({
    "Domain", "Subdomain", "IP", "Port", "Service", "DNSRecord", "BaseURL",
    "Endpoint", "Parameter", "Header", "Certificate", "Technology", "Secret",
    "Traceroute", "ExternalDomain",
})

# Observation anchors are DELIBERATELY restricted to broad, well-identified
# nodes. The triager (skills/recon/triager/writing-observations) is instructed
# to re-anchor a finding UP to the owning broad asset (e.g. a Technology/Endpoint
# finding -> its BaseURL), naming the narrow element in the observation evidence.
# An out-of-allowlist anchor (Endpoint/Technology/Parameter/...) is therefore a
# TRIAGER error, correctly dropped here; the fix belongs in the triager prompt,
# NOT in widening this set (which only masks mis-anchoring and fragments the
# host-level observation graph). See the writing-observations skill's Edit 3.
ANCHOR_ALLOWLIST = frozenset({"Domain", "Subdomain", "BaseURL", "IP", "Service"})

# Placeholder value used by the pure builders; curate() overwrites it with the
# real project_id before dispatching to merge_fn.
_PENDING_PROJECT_ID = "__pending_project_id__"


def _identity_clause(prefix: str, identity: dict) -> tuple[str, dict]:
    """Build a deterministic `{k: $prefix_k, ...}` clause fragment + its params."""
    keys = sorted(identity.keys())
    clause = ", ".join(f"{k}: ${prefix}{k}" for k in keys)
    params = {f"{prefix}{k}": identity[k] for k in keys}
    return clause, params


def build_asset_cypher(delta: AssetDelta) -> tuple[str, dict]:
    """Pure: build a parameterised MERGE for one AssetDelta (+ its edges).

    Raises ValueError if delta.type is not an allowed Layer-0 label.
    """
    if delta.type not in ALLOWED_LABELS:
        raise ValueError(f"Unknown asset label: {delta.type!r}")

    id_clause, params = _identity_clause("id_", delta.identity)
    params["project_id"] = _PENDING_PROJECT_ID
    params["props"] = dict(delta.props)

    lines = [
        f"MERGE (n:{delta.type} {{{id_clause}, project_id: $project_id}})",
        "ON CREATE SET n.first_seen = datetime()",
        "SET n.last_seen = datetime()",
        "SET n += $props",
    ]

    for i, edge in enumerate(delta.edges):
        prefix = f"e{i}_"
        e_clause, e_params = _identity_clause(prefix, edge.node_identity)
        params.update(e_params)
        lines.append(f"MERGE (m{i}:{edge.node_type} {{{e_clause}, project_id: $project_id}})")
        if edge.dir == "in":
            lines.append(f"MERGE (m{i})-[:{edge.rel}]->(n)")
        else:
            lines.append(f"MERGE (n)-[:{edge.rel}]->(m{i})")

    return "\n".join(lines), params


def build_observation_cypher(obs: Observation) -> tuple[str, dict]:
    """Pure: build a parameterised MERGE for one Observation + its anchor edge.

    Raises ValueError if the anchor type is outside the broad-anchor allowlist.
    """
    anchor_type = obs.anchor.get("type")
    anchor_identity = obs.anchor.get("identity", {})
    if anchor_type not in ANCHOR_ALLOWLIST:
        raise ValueError(f"Observation anchor type not allowed: {anchor_type!r}")

    anchor_canonical = json.dumps(obs.anchor, sort_keys=True)
    obs_id = hashlib.sha1(
        f"{obs.macro_kind}|{obs.evidence}|{anchor_canonical}|{obs.source_tool}".encode()
    ).hexdigest()

    a_clause, params = _identity_clause("anchor_", anchor_identity)
    params["project_id"] = _PENDING_PROJECT_ID
    params["obs_id"] = obs_id
    params["macro_kind"] = obs.macro_kind
    params["severity"] = obs.severity
    params["evidence"] = obs.evidence
    params["rationale"] = obs.rationale
    params["source_job"] = obs.source_job
    params["source_tool"] = obs.source_tool

    lines = [
        f"MERGE (a:{anchor_type} {{{a_clause}, project_id: $project_id}})",
        "MERGE (o:Observation {id: $obs_id})",
        "SET o.macro_kind = $macro_kind",
        "SET o.severity = $severity",
        "SET o.evidence = $evidence",
        "SET o.rationale = $rationale",
        "SET o.source_job = $source_job",
        "SET o.source_tool = $source_tool",
        "SET o.observed_at = datetime()",
        "SET o.project_id = $project_id",
        "MERGE (a)-[:HAS_OBSERVATION]->(o)",
    ]

    return "\n".join(lines), params


def curate(
    assets: list[AssetDelta],
    observations: list[Observation],
    project_id: str,
    *,
    merge_fn=None,
) -> tuple[int, int]:
    """Execute each asset/observation MERGE, skipping+logging single-item
    failures (bad label, bad anchor, or a merge_fn exception) and continuing.

    Returns (assets_merged, observations_merged) counts of successful merges.
    """
    if merge_fn is None:
        from agent.app.clients import neo4j_client
        merge_fn = neo4j_client.merge

    assets_merged = 0
    for delta in assets:
        try:
            cypher, params = build_asset_cypher(delta)
        except ValueError:
            logger.warning("curate: skipping asset delta with unknown type=%r", delta.type, exc_info=True)
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("curate: merge failed for asset type=%r", delta.type, exc_info=True)
            continue
        assets_merged += 1

    observations_merged = 0
    for obs in observations:
        try:
            cypher, params = build_observation_cypher(obs)
        except ValueError:
            logger.warning("curate: skipping observation with disallowed anchor=%r", obs.anchor, exc_info=True)
            continue
        params["project_id"] = project_id
        try:
            merge_fn(cypher, params)
        except Exception:
            logger.warning("curate: merge failed for observation macro_kind=%r", obs.macro_kind, exc_info=True)
            continue
        observations_merged += 1

    return assets_merged, observations_merged
