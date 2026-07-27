"""Optimal-chunk feeding + the httpx-profile delivery gate (#13 + #14), realising
#20 increment 1 as ONE standalone module in the analysis read/chunk seam (the peer
of `l1_read` / `l1_inventory` / `index_card` / `delivery`).

The chunk-builder streams a recon job's immutable L0 DELTA (its `AssetDelta` list)
into ONE ordered, size-bounded sequence of `Chunk`s, and each proposer ROLE then
narrows that stream to the asset types it can meaningfully consume (`ROLE_ADMITS` /
`admit_for_role`, #34 D2/D7 - the lever #15 called asset-type-driven agent scoping).
This replaced the earlier two-way `service`/`data` CONCERN partition, which fixed
"which types matter" once and globally when the real constraint is per-agent (#34 D8).

It is a PURE function: the caller does the live reads (the profiled-origin set, the
deltas) and passes them in, so no L1 context is ever frozen onto a chunk - the
live-graph invariant the stale-context curation bug taught.

Composition (the clean seams):
  - `AssetDelta` / `Observation` / `JobSpec` come from `recon.domain.types` UNCHANGED
    (the ACL); `profiled_origins` REUSES `recon.domain.selectors.apply_selector`
    (no new profiling, no new predicate language - #14 D16 reuse-first).
  - `Chunk` lives HERE and is imported by `messages.py` (it promotes the
    increment-0 placeholder); this module has NO runtime import of `messages.py`.
"""
from __future__ import annotations

import logging
import math

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.domain.selectors import apply_selector
from polymerhus.recon.domain.types import AssetDelta, AssetSelector, JobSpec, Observation

logger = logging.getLogger(__name__)

# Provisional per-chunk asset budget (#13, fork B): tune on a katana-heavy run.
CHUNK_MAX_ASSETS = 100

# The httpx-profile gate applies ONLY to Parameter (#13 fork G), gated on its
# BaseURL origin, where the profile genuinely informs API-input vs web-form-field.
# Endpoint was gated too (#14) until #34 D1 dropped it: an unprofiled Endpoint is
# still assignable, and withholding it made a never-profiled target produce an
# ownerless attack surface indistinguishable from one with nothing to own (AMV-14).
_GATED_TYPES: frozenset[str] = frozenset({"Parameter"})

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
    "data_modeller": frozenset({"Parameter", "Header"}),
}

# The chunk-fed proposer roles, in dispatch order. `bootstrapper` / `anti_cluttering`
# are slice-less (they re-derive the whole live L1) and never receive a chunk.
CHUNK_ROLES: tuple[str, ...] = ("assigner", "mechanism_typist", "data_modeller")

# The valid httpx profiles (D16 `noise_filter.classify_profile`).
_PROFILE_VALUES = ["webapp", "restapi", "graphql_api"]
_HAS_PROFILE = AssetSelector(field="profile", op="equals", values=_PROFILE_VALUES)


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
    # True when this chunk was assembled at the phase-barrier and carries a
    # still-un-profiled gated asset (the AMV-14 fail-open flag; the proposer
    # treats it conservatively). Never silently dropped.
    flagged: bool = False


def profiled_origins(base_url_records: list[dict]) -> frozenset[str]:
    """The set of BaseURL origins carrying an httpx `profile` (#14 gate, D16
    reuse). Each record is a BaseURL's `{"baseurl": ..., "profile": ...}`
    projection. REUSES `apply_selector` for the 'has a profile' predicate, whose
    missing/blank-field default is exclusion (the correct fail-safe direction)."""
    matched = apply_selector(base_url_records, _HAS_PROFILE)
    return frozenset(r["baseurl"] for r in matched if r.get("baseurl"))


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


def _baseurl_of(asset: AssetDelta) -> str | None:
    """The BaseURL origin a gated asset hangs off, read from its identity."""
    bu = (asset.identity or {}).get("baseurl")
    return bu if isinstance(bu, str) and bu else None


def _gate(asset: AssetDelta, profiled: frozenset[str], barrier: bool) -> tuple[bool, bool]:
    """The #14 profile gate for one asset. Returns (admitted, flagged).

    Non-gated types are always admitted (flagged False), which since #34 D1 includes
    Endpoint. The one gated type (Parameter) is admitted when its BaseURL is
    profiled; when un-profiled it is WITHHELD at normal delivery (`barrier=False`)
    and admitted-but-FLAGGED at the phase-barrier (`barrier=True`) - the fail-open
    backstop."""
    if asset.type not in _GATED_TYPES:
        return True, False
    if _baseurl_of(asset) in profiled:
        return True, False
    # un-profiled gated asset
    if barrier:
        return True, True   # delivered flagged, never silently dropped
    return False, False     # withheld at delivery


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
    profiled: frozenset[str] = frozenset(),
    barrier: bool = False,
    max_assets: int = CHUNK_MAX_ASSETS,
) -> list[Chunk]:
    """Stream a job's L0 delta into ONE ordered, size-bounded, profile-gated `Chunk`
    sequence (#13 + #14, reshaped by #34 D8). EVERY asset type is streamed; the
    consuming role narrows via `admit_for_role`. Pure: `profiled` and the deltas are
    read by the caller and passed in. Total delivery semantics: an empty delta -> [];
    a malformed asset is excluded (never crashes); replay is deterministic (the
    `chunk_id` is a pure function of source_job + batch_index)."""
    observations = observations or []
    source_job = job.tool if job is not None else ""

    # 1. gate the stream, tracking per-asset flagged state.
    items: list[tuple[AssetDelta, bool]] = []
    for asset in assets:
        try:
            if not getattr(asset, "type", None):
                continue  # malformed: no type -> exclude, never crash
            admitted, flagged = _gate(asset, profiled, barrier)
            if admitted:
                items.append((asset, flagged))
        except Exception:  # any malformed asset degrades to exclusion, not a crash
            logger.warning("chunking: skipped a malformed asset", exc_info=True)
            continue
    if not items:
        return []  # empty / fully-gated delta -> no chunk (valid)

    # 2. batch-overflow the stream into ordered chunks (tail never dropped).
    budget = max(1, max_assets)
    total = math.ceil(len(items) / budget)
    chunks: list[Chunk] = []
    for idx in range(total):
        window = items[idx * budget:(idx + 1) * budget]
        window_assets = tuple(a for a, _ in window)
        chunks.append(Chunk(
            chunk_id=f"{source_job}:{idx}",
            source_job=source_job,
            assets=window_assets,
            observations=_observations_for(window_assets, observations),
            batch_index=idx,
            batch_total=total,
            flagged=any(f for _, f in window),
        ))
    return chunks


def routing_pairs(chunk: Chunk) -> list[tuple[Chunk, str]]:
    """Expand a chunk to its ordered (chunk, role) pairs (#13 3, reshaped by #34 D8):
    every chunk goes to every chunk-fed role, and `admit_for_role` decides what each
    one actually sees. A role admitting nothing from this chunk yields an empty batch,
    which the proposer already treats as a valid outcome. The schedule builder (2a)
    consumes this to sequence one pair per super-step."""
    return [(chunk, role) for role in CHUNK_ROLES]
