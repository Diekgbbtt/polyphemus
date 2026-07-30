"""Optimal-chunk feeding (#13), realising #20 increment 1 as ONE standalone module
in the analysis read/chunk seam (the peer of `l1_read` / `l1_inventory` /
`index_card` / `delivery`).

The chunk-builder streams a recon job's immutable L0 DELTA (its `AssetDelta` list)
into ONE ordered, size-bounded sequence of `Chunk`s, and each proposer ROLE then
narrows that stream to the asset types it can meaningfully consume (`ROLE_ADMITS` /
`admit_for_role`, #34 D2/D7 - the lever #15 called asset-type-driven agent scoping).
This replaced the earlier two-way `service`/`data` CONCERN partition, which fixed
"which types matter" once and globally when the real constraint is per-agent (#34 D8).

It is a PURE function: the caller does the live reads (the deltas) and passes them
in, so no L1 context is ever frozen onto a chunk - the live-graph invariant the
stale-context curation bug taught.

**The httpx-profile delivery gate (#14) is REMOVED, not consumed** (#48,
`dataplane-A1-decisions.md` section 6, DPL-DEC question 9, ratified 2026-07-30):
`#34 D1` already dropped it for `Endpoint` - withholding un-profiled surface made a
never-profiled target indistinguishable from an empty one (AMV-14) - and the same
argument applies to `Parameter`, the one type that still carried it. With both
gated types gone, the gate/`Chunk.flagged` apparatus is permanently unreachable, a
dormant seam `CODING_STANDARD.md` section 12 says should not be left to rot
silently. This does NOT touch `ROLE_ADMITS`/`admit_for_role` - the per-agent
type-narrowing mechanism is a separate, later stage over an already-built chunk.

Composition (the clean seams):
  - `AssetDelta` / `Observation` / `JobSpec` come from `recon.domain.types` UNCHANGED
    (the ACL).
  - `Chunk` lives HERE and is imported by `messages.py` (it promotes the
    increment-0 placeholder); this module has NO runtime import of `messages.py`.
"""
from __future__ import annotations

import logging
import math
import re

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.domain.types import AssetDelta, JobSpec, Observation

logger = logging.getLogger(__name__)

# Provisional per-chunk asset budget (#13, fork B): tune on a katana-heavy run.
CHUNK_MAX_ASSETS = 100

# Script Endpoints (`*.js`) are EXCLUDED from the stream for every downstream agent.
# Recon must keep producing them - jsluice mines them for parameters and endpoints,
# and they carry technology evidence - but a script file is not itself a surface an
# attack acts on, so an agent asked to assign or type one is being handed noise. The
# exclusion is at the STREAM, not per-role: no proposer wants them.
# The query string is stripped before matching so a cache-busted `/app.js?v=2` is
# still recognised as a script.
_SCRIPT_PATH = re.compile(r"\.js$", re.IGNORECASE)

# The sentinel admitting EVERY asset type. Load-bearing, not a convenience: with
# three allow-sets an asset type no role names would be admitted by nobody and so
# silently dropped, losing the increment-1 fork-H guarantee. The generalist role
# holds the sentinel, so a new recon tool's output always lands somewhere.
ADMIT_ALL = "*"

# The per-ROLE admission table (#34 D7): every asset type a recon job produces is
# streamed, and each role narrows the stream to what it can meaningfully consume.
# Role strings match `messages.Role` (no runtime import of the control plane here).
ROLE_ADMITS: dict[str, frozenset[str] | str] = {
    "assigner": frozenset({"Endpoint"}),          # one judgment: who owns this Endpoint
    "mechanism_typist": ADMIT_ALL,                 # the generalist (see ADMIT_ALL)
    # Widened to include Secret (#48, dataplane-A1-decisions.md section 6,
    # ratified 2026-07-30): a jsluice-mined Secret is Tier-1 trust substrate too -
    # #10's own responsibility statement names "parameters/headers/secrets/HTML"
    # as the lift surface. Endpoint stays OUT (question 8): SURFACES_AT targets
    # Parameter/Header/Secret only, never an Endpoint (DPL-DEC-10).
    "data_modeller": frozenset({"Parameter", "Header", "Secret"}),
}

# The chunk-fed proposer roles, in dispatch order. `bootstrapper` / `anti_cluttering`
# are slice-less (they re-derive the whole live L1) and never receive a chunk.
CHUNK_ROLES: tuple[str, ...] = ("assigner", "mechanism_typist", "data_modeller")


class Chunk(BaseModel):
    """A size-bounded slice of one recon job's L0 delta - the immutable
    pure-function INPUT a proposer reasons over (#13).

    Carries EVERY streamed asset type (#34 D8 dropped the `concern` tag); the
    consuming role narrows it via `admit_for_role`. Total defaults so it composes
    into `AgentDispatch` exactly as the increment-0 placeholder did
    (`AgentDispatch(chunk=Chunk(chunk_id=...))` stays valid). The chunk carries only
    the L0 delta; all L1 context is re-derived LIVE at the proposer, never frozen
    here."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_job: str = ""
    assets: tuple[AssetDelta, ...] = ()
    observations: tuple[Observation, ...] = ()
    batch_index: int = 0
    batch_total: int = 1


def admit_for_role(chunk: Chunk, role: str) -> tuple[AssetDelta, ...]:
    """Narrow a chunk to the asset types `role` can meaningfully consume (#34 D7).

    Stream order is preserved. An unknown role admits nothing (a role that has not
    declared itself must not silently receive the whole stream). An empty result is
    VALID - the proposer degrades to an empty batch, which is how a chunk with
    nothing for this role is meant to end."""
    admits = ROLE_ADMITS.get(role)
    if admits is None:
        logger.info("chunking: role %r has no admission entry -> admits nothing", role)
        return ()
    if admits == ADMIT_ALL:
        return chunk.assets
    return tuple(a for a in chunk.assets if a.type in admits)


def is_script_endpoint(asset: AssetDelta) -> bool:
    """True for an Endpoint whose path is a JavaScript file (`*.js`).

    Only Endpoints are judged: a Parameter or Header discovered ON a script is a real
    finding and stays in the stream."""
    if getattr(asset, "type", None) != "Endpoint":
        return False
    path = (asset.identity or {}).get("path")
    if not isinstance(path, str):
        return False
    bare = path.split("?", 1)[0].split("#", 1)[0]
    return bool(_SCRIPT_PATH.search(bare))


def _observations_for(assets: tuple[AssetDelta, ...], observations: list[Observation]) -> tuple[Observation, ...]:
    """The observations whose anchor asset is present in this chunk: an observation
    rides the chunk carrying the asset it anchors to. Consumed by the mechanism-typist
    and the data-modeller; the Assigner does not render them (#34 D5)."""
    keys = {(a.type, _identity_key(a.identity)) for a in assets}
    out = [
        o for o in observations
        if (o.anchor.get("type"), _identity_key(o.anchor.get("identity") or {})) in keys
    ]
    return tuple(out)


def _identity_key(identity: dict) -> tuple:
    """A hashable, order-stable key for an identity dict (for membership tests)."""
    return tuple(sorted((k, str(v)) for k, v in (identity or {}).items()))


def chunks_for_job(
    job: JobSpec,
    assets: list[AssetDelta],
    observations: list[Observation] | None = None,
    *,
    max_assets: int = CHUNK_MAX_ASSETS,
) -> list[Chunk]:
    """Stream a job's L0 delta into ONE ordered, size-bounded `Chunk` sequence
    (#13, reshaped by #34 D8, the profile gate removed by #48 section 6). EVERY
    asset type is streamed; the consuming role narrows via `admit_for_role`.
    Pure: the deltas are read by the caller and passed in. Total delivery
    semantics: an empty delta -> []; a malformed asset is excluded (never
    crashes); replay is deterministic (the `chunk_id` is a pure function of
    source_job + batch_index)."""
    observations = observations or []
    source_job = job.tool if job is not None else ""

    # 1. filter the stream (malformed assets, script Endpoints).
    items: list[AssetDelta] = []
    for asset in assets:
        try:
            if not getattr(asset, "type", None):
                continue  # malformed: no type -> exclude, never crash
            if is_script_endpoint(asset):
                continue  # script file: kept in L0, never streamed to an agent
            items.append(asset)
        except Exception:  # any malformed asset degrades to exclusion, not a crash
            logger.warning("chunking: skipped a malformed asset", exc_info=True)
            continue
    if not items:
        return []  # empty delta -> no chunk (valid)

    # 2. batch-overflow the stream into ordered chunks (tail never dropped).
    budget = max(1, max_assets)
    total = math.ceil(len(items) / budget)
    chunks: list[Chunk] = []
    for idx in range(total):
        window_assets = tuple(items[idx * budget:(idx + 1) * budget])
        chunks.append(Chunk(
            chunk_id=f"{source_job}:{idx}",
            source_job=source_job,
            assets=window_assets,
            observations=_observations_for(window_assets, observations),
            batch_index=idx,
            batch_total=total,
        ))
    return chunks


def routing_pairs(chunk: Chunk) -> list[tuple[Chunk, str]]:
    """Expand a chunk to its ordered (chunk, role) pairs (#13 3, reshaped by #34 D8):
    every chunk goes to every chunk-fed role, and `admit_for_role` decides what each
    one actually sees. A role admitting nothing from this chunk yields an empty batch,
    which the proposer already treats as a valid outcome. The schedule builder (2a)
    consumes this to sequence one pair per super-step."""
    return [(chunk, role) for role in CHUNK_ROLES]
