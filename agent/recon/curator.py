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

# D8 - deterministic re-anchor repair (forward-decision D8, operator-approved
# 2026-07-08). The triager is supposed to re-anchor a finding UP to the owning
# broad asset, but when it fails and anchors on a narrow primitive the
# observation is silently dropped (build_observation_cypher raises, curate
# skips). This is a belt-and-suspenders safety net on the deterministic curator
# path: it re-anchors UP by PURE identity-key derivation (NOT graph traversal -
# operator explicitly accepted this divergence from D8's literal wording), which
# covers 100% of the measured drops because the owning broad asset's id is
# already carried in the narrow node's own identity for four of the five types:
#   - Endpoint / Header / Parameter  ->  owning BaseURL, via the `baseurl` key
#   - Port                           ->  owning IP,      via `ip_address` (or `ip`)
# Each rule: narrow type -> (broad type, broad node's id key, ordered tuple of
# candidate keys on the narrow anchor's identity holding the owner id). The
# first non-empty candidate wins (canonical key first, then the minimal alias).
# Technology (global {name, version}, no owner key in its identity) is
# deliberately absent: it is not repairable by pure derivation and falls through
# to the unchanged drop-and-log path, exactly like today.
_REANCHOR_RULES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "Endpoint": ("BaseURL", "url", ("baseurl",)),
    "Header": ("BaseURL", "url", ("baseurl",)),
    "Parameter": ("BaseURL", "url", ("baseurl",)),
    "Port": ("IP", "address", ("ip_address", "ip")),
}

# Placeholder value used by the pure builders; curate() overwrites it with the
# real project_id before dispatching to merge_fn.
_PENDING_PROJECT_ID = "__pending_project_id__"


def broaden_anchor(anchor: dict) -> dict | None:
    """Pure D8 re-anchor repair: if `anchor` sits on a narrow primitive whose
    owning broad asset is derivable from the anchor's own identity, return a new
    broad anchor dict `{"type": ..., "identity": {...}}`; otherwise return None
    (the caller then drops-and-logs, unchanged pre-D8 behavior).

    Derivation is by identity key ONLY - no graph/driver access, so this stays
    pure and unit-testable like the rest of this module. Not repairable (returns
    None): Technology and any narrow anchor missing its owner key, non-primitive
    pseudo-types, and malformed input.
    """
    if not isinstance(anchor, dict):
        return None
    rule = _REANCHOR_RULES.get(anchor.get("type"))
    if rule is None:
        return None
    broad_type, broad_key, candidate_keys = rule
    identity = anchor.get("identity")
    if not isinstance(identity, dict):
        return None
    for key in candidate_keys:
        owner = identity.get(key)
        if owner:
            return {"type": broad_type, "identity": {broad_key: owner}}
    return None


def _reanchor_evidence_suffix(anchor: dict) -> str:
    """Render the narrow anchor's identity into a deterministic evidence suffix
    so the re-anchored observation still names the narrow element it came from.
    Sorted keys keep the string (and therefore the obs_id hash) stable."""
    identity = anchor.get("identity")
    narrow_type = anchor.get("type")
    if isinstance(identity, dict) and identity:
        rendered = ", ".join(f"{k}={identity[k]}" for k in sorted(identity))
        return f" [re-anchored from {narrow_type} {{{rendered}}}]"
    return f" [re-anchored from {narrow_type}]"


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

    Raises ValueError if the anchor type is outside the broad-anchor allowlist
    AND cannot be deterministically re-anchored UP to a broad owner (D8).
    """
    anchor = obs.anchor
    evidence = obs.evidence
    anchor_type = anchor.get("type")

    if anchor_type not in ANCHOR_ALLOWLIST:
        # D8: try to re-anchor UP before rejecting. On success, the narrow
        # anchor's identity is preserved in evidence and both anchor+evidence
        # flow into obs_id below, so the repaired observation gets one stable id.
        broadened = broaden_anchor(anchor)
        if broadened is not None:
            evidence = evidence + _reanchor_evidence_suffix(anchor)
            anchor = broadened
            anchor_type = anchor.get("type")

    anchor_identity = anchor.get("identity", {})
    if anchor_type not in ANCHOR_ALLOWLIST:
        raise ValueError(f"Observation anchor type not allowed: {anchor_type!r}")

    anchor_canonical = json.dumps(anchor, sort_keys=True)
    obs_id = hashlib.sha1(
        f"{obs.macro_kind}|{evidence}|{anchor_canonical}|{obs.source_tool}".encode()
    ).hexdigest()

    a_clause, params = _identity_clause("anchor_", anchor_identity)
    params["project_id"] = _PENDING_PROJECT_ID
    params["obs_id"] = obs_id
    params["macro_kind"] = obs.macro_kind
    params["severity"] = obs.severity
    params["evidence"] = evidence
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
