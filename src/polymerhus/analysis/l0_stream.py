"""The LIVE L0 read that feeds the chunk stream (#34 wiring).

`chunks_for_job` is a pure function whose reads are injected by its caller; this
module is that caller's read side. It projects the project's current L0 surface out
of Neo4j back into `AssetDelta`s the chunk builder understands, and reconstructs the
project's triager `Observation`s (with their anchor) for the chunk builder to attach.

`read_baseurl_profiles` (the httpx-profile read the retained Parameter gate used)
was REMOVED by #48 alongside the gate itself (`chunking.py` module docstring) - it
had no consumer left once `chunking._gate`/`_GATED_TYPES`/`profiled_origins` were
removed.

WHY THE CUMULATIVE SURFACE, NOT A PER-JOB DELTA. A recon job's freshly-produced
`AssetDelta` list exists only inside the pod: `PodExport` carries counts, and L0
nodes carry `first_seen` / `last_seen` but no `source_job`, so "what did THIS job
produce" is not answerable from the graph. Adding it would mean changing the L0
sole-writer, which `loop-constraints.md` places on the escalate-never-edit list.
Re-reading the cumulative surface is also what the streaming design already
promises: each step re-reads the full current slice, which is exactly what makes
the final streamed pass equal the batch pass (L1D-23, the FR-STREAM ledger).

Fail-open: a read error degrades to an empty surface and never raises into the
caller, mirroring `l1_inventory` / `sweep` / `l1_read`.
"""
from __future__ import annotations

import logging

from polymerhus.recon.domain.types import AssetDelta, Observation

logger = logging.getLogger(__name__)

# The L0 identity keys per label - which of a node's properties form its identity.
# Single-sourced here for the read side; `pod._L0_REFERENCE_GUIDE` states the same
# keys to the LLM, and the two must not drift (an identity carrying a stray property
# is one the sole-writer's MATCH will not find).
L0_IDENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "BaseURL": ("url",),
    "Endpoint": ("path", "method", "baseurl"),
    "Parameter": ("name", "position", "endpoint_path", "baseurl"),
    "Header": ("name", "value", "baseurl"),
    "Technology": ("name", "version"),
    "Certificate": ("subject_cn",),
    # DPL-DEC-10 (dataplane-A1-decisions.md §6): a jsluice-mined Secret is Tier-1
    # trust substrate, so the data_modeller's reference gate needs its identity
    # shape too - added alongside the ROLE_ADMITS widening to {Parameter, Header,
    # Secret}.
    "Secret": ("value_hash",),
}

# Properties that are never part of an identity and never useful to a proposer.
_NOISE_PROPS = frozenset({"project_id", "first_seen", "last_seen", "element_id"})


def _identity_of(node_type: str, props: dict) -> dict:
    """The identity sub-dict of a node's property bag. An unknown label has no
    declared keys, so it falls back to the whole (de-noised) bag - the fork-H
    direction: an unmapped type is carried, not dropped."""
    keys = L0_IDENTITY_KEYS.get(node_type)
    if keys is None:
        return {k: v for k, v in props.items() if k not in _NOISE_PROPS}
    return {k: props[k] for k in keys if k in props}


def assets_from_slice(l0_slice: dict) -> list[AssetDelta]:
    """Project a `{nodes, links}` graph read back into `AssetDelta`s.

    Pure, so the conversion is testable without a driver. A node whose type is
    unknown to the identity map is still carried (its whole property bag becomes
    its identity); a node with no type is skipped."""
    out: list[AssetDelta] = []
    for node in (l0_slice or {}).get("nodes", []):
        node_type = node.get("type")
        if not node_type:
            continue
        props = dict(node.get("properties") or {})
        identity = _identity_of(node_type, props)
        rest = {k: v for k, v in props.items() if k not in identity and k not in _NOISE_PROPS}
        out.append(AssetDelta(type=node_type, identity=identity, props=rest))
    return out


def read_l0_assets(project_id: str, *, read_fn=None) -> list[AssetDelta]:
    """The project's CURRENT L0 surface as `AssetDelta`s, for the chunk builder.

    Reuses the analyser's own slice read (`pod.default_read_fn`), so the streamed
    path sees exactly the surface the batch path sees - including its exclusion of
    Observation nodes, which ride their own channel."""
    if read_fn is None:
        from polymerhus.analysis.pod import default_read_fn as read_fn
    try:
        return assets_from_slice(read_fn(project_id))
    except Exception:  # a read blip degrades to no surface, never crashes a run
        logger.warning("l0_stream: L0 read failed; degrading to empty surface", exc_info=True)
        return []


def read_observations(project_id: str, *, read_fn=None) -> list[Observation]:
    """The project's triager `Observation`s, with their ANCHOR reconstructed, for
    the chunk builder (dataplane-A1-decisions.md §11 step 0).

    `analyse_chunked` called `chunks_for_job` with no observations at all, so
    `Chunk.observations` was ALWAYS empty on the live path - the typist and the
    data-modeller both render observations but neither ever received one.
    `delivery.collect_observations` cannot be reused: it projects `_OBS_FIELDS`
    and DROPS the anchor entirely, while `chunking._observations_for` needs a real
    `Observation.anchor`. This is that missing read.

    An Observation node carries no anchor identity itself; the anchor is the OTHER
    end of the `(anchor)-[:HAS_OBSERVATION]->(Observation)` edge
    (`recon.domain.curator.build_observation_cypher`). The anchor's identity is
    reconstructed with the SAME `_identity_of` de-noising rule `assets_from_slice`
    uses, so an Observation's anchor and a chunk's own asset for that same node
    compute an IDENTICAL identity dict - which is what lets
    `chunking._observations_for`'s exact `(type, identity)` match actually fire.

    Fail-open: a read error degrades to no observations, never raises."""
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    try:
        rows = read_fn(
            "MATCH (a)-[:HAS_OBSERVATION]->(o:Observation) WHERE o.project_id = $project_id "
            "RETURN labels(a) AS anchor_labels, a {.*} AS anchor_props, o {.*} AS obs_props",
            {"project_id": project_id},
        )
    except Exception:  # a read blip degrades to no observations, never crashes a run
        logger.warning("l0_stream: observation read failed; degrading to no observations", exc_info=True)
        return []

    out: list[Observation] = []
    for row in rows:
        labels = [l for l in (row.get("anchor_labels") or []) if isinstance(l, str)]
        anchor_type = labels[0] if labels else None
        if not anchor_type:
            continue
        anchor_props = {k: v for k, v in dict(row.get("anchor_props") or {}).items()}
        identity = _identity_of(anchor_type, anchor_props)
        obs = dict(row.get("obs_props") or {})
        try:
            out.append(Observation(
                macro_kind=obs.get("macro_kind") or "",
                severity=obs.get("severity") or "",
                evidence=obs.get("evidence") or "",
                rationale=obs.get("rationale") or "",
                anchor={"type": anchor_type, "identity": identity},
                source_job=obs.get("source_job") or "",
                source_tool=obs.get("source_tool") or "",
            ))
        except Exception:  # a malformed row is skipped, never crashes the read
            logger.warning("l0_stream: skipped a malformed observation row", exc_info=True)
            continue
    return out


