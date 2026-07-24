"""Optimal-chunk feeding + the httpx-profile delivery gate (#13 + #14), realising
#20 increment 1 as ONE standalone module in the analysis read/chunk seam (the peer
of `l1_read` / `l1_inventory` / `index_card` / `delivery`).

The chunk-builder partitions a recon job's immutable L0 DELTA (its `AssetDelta`
list) by asset TYPE into single-CONCERN, size-bounded slices, applies the #14
profile gate, and emits type-coherent `Chunk`s. It is a PURE function: the caller
does the live reads (the profiled-origin set, the deltas) and passes them in, so no
L1 context is ever frozen onto a chunk - the live-graph invariant the stale-context
curation bug taught. Nothing here is wired into a caller yet (increment 1 is a
two-way door); the supervisor's schedule builder (2a) consumes `CONCERN_ROLES`.

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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.domain.selectors import apply_selector
from polymerhus.recon.domain.types import AssetDelta, AssetSelector, JobSpec, Observation

logger = logging.getLogger(__name__)

Concern = Literal["service", "data"]

# Provisional per-concern asset budget (#13, fork B): tune on a katana-heavy run.
CHUNK_MAX_ASSETS = 100

# Asset TYPE -> CONCERN partition (#13 fork F: Header is DUAL - service AND data).
_SERVICE_TYPES: frozenset[str] = frozenset({"BaseURL", "Endpoint", "Technology", "Certificate"})
_DATA_TYPES: frozenset[str] = frozenset({"Parameter", "Secret"})
_DUAL_TYPES: frozenset[str] = frozenset({"Header"})
# Pre-HTTP discovery types carry NO concern -> a pure discovery job yields [].
_PREHTTP_TYPES: frozenset[str] = frozenset(
    {"Subdomain", "IP", "Port", "DNSRecord", "Domain", "ExternalDomain", "ASN"}
)
# The httpx-profile gate applies only to these (Endpoint per #14; Parameter per
# #13 fork G - both gated on their BaseURL origin).
_GATED_TYPES: frozenset[str] = frozenset({"Endpoint", "Parameter"})

# The concern -> ordered proposer-role routing key (#13 3): a `service` chunk
# expands to two (chunk, role) pairs, a `data` chunk to one. Role strings match
# `messages.Role` (no runtime import of the control plane needed here).
CONCERN_ROLES: dict[Concern, tuple[str, ...]] = {
    "service": ("assigner", "mechanism_typist"),
    "data": ("data_modeller",),
}

# The valid httpx profiles (D16 `noise_filter.classify_profile`).
_PROFILE_VALUES = ["webapp", "restapi", "graphql_api"]
_HAS_PROFILE = AssetSelector(field="profile", op="equals", values=_PROFILE_VALUES)


class Chunk(BaseModel):
    """A type-coherent, size-bounded slice of one recon job's L0 delta for ONE
    concern - the immutable pure-function INPUT a proposer reasons over (#13).

    Total defaults so it composes into `AgentDispatch` exactly as the increment-0
    placeholder did (`AgentDispatch(chunk=Chunk(chunk_id=...))` stays valid). The
    chunk carries only the L0 delta; all L1 context is re-derived LIVE at the
    proposer, never frozen here."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_job: str = ""
    concern: Concern = "service"
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


def _concerns_of_type(asset_type: str) -> tuple[Concern, ...]:
    """The concern(s) an asset type routes to. Pre-HTTP types -> () (no concern);
    an unmapped type -> ('service',) with a log (#13 fork H: never dropped)."""
    if asset_type in _PREHTTP_TYPES:
        return ()
    concerns: list[Concern] = []
    if asset_type in _SERVICE_TYPES or asset_type in _DUAL_TYPES:
        concerns.append("service")
    if asset_type in _DATA_TYPES or asset_type in _DUAL_TYPES:
        concerns.append("data")
    if concerns:
        return tuple(concerns)
    logger.info("chunking: unmapped asset type %r -> service generalist", asset_type)
    return ("service",)


def _baseurl_of(asset: AssetDelta) -> str | None:
    """The BaseURL origin a gated asset hangs off, read from its identity."""
    bu = (asset.identity or {}).get("baseurl")
    return bu if isinstance(bu, str) and bu else None


def _gate(asset: AssetDelta, profiled: frozenset[str], barrier: bool) -> tuple[bool, bool]:
    """The #14 profile gate for one asset. Returns (admitted, flagged).

    Non-gated types are always admitted (flagged False). A gated type (Endpoint /
    Parameter) is admitted when its BaseURL is profiled; when un-profiled it is
    WITHHELD at normal delivery (`barrier=False`) and admitted-but-FLAGGED at the
    phase-barrier (`barrier=True`) - the fail-open backstop."""
    if asset.type not in _GATED_TYPES:
        return True, False
    if _baseurl_of(asset) in profiled:
        return True, False
    # un-profiled gated asset
    if barrier:
        return True, True   # delivered flagged, never silently dropped
    return False, False     # withheld at delivery


def _observations_for(assets: tuple[AssetDelta, ...], observations: list[Observation]) -> tuple[Observation, ...]:
    """The observations whose anchor asset is present in this chunk (single-concern
    coherence): an observation rides the chunk carrying the asset it anchors to."""
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
    """Partition a job's L0 delta into type-coherent, size-bounded, profile-gated
    `Chunk`s (#13 + #14). Pure: `profiled` and the deltas are read by the caller
    and passed in. Total delivery semantics: an empty / pre-HTTP-only delta -> [];
    a malformed asset is excluded (never crashes); replay is deterministic (the
    `chunk_id` is a pure function of source_job + concern + batch_index)."""
    observations = observations or []
    source_job = job.tool if job is not None else ""

    # 1. partition admitted assets by concern, tracking per-asset flagged state.
    per_concern: dict[Concern, list[tuple[AssetDelta, bool]]] = {"service": [], "data": []}
    for asset in assets:
        try:
            if not getattr(asset, "type", None):
                continue  # malformed: no type -> exclude, never crash
            admitted, flagged = _gate(asset, profiled, barrier)
            if not admitted:
                continue
            for concern in _concerns_of_type(asset.type):
                per_concern[concern].append((asset, flagged))
        except Exception:  # any malformed asset degrades to exclusion, not a crash
            logger.warning("chunking: skipped a malformed asset", exc_info=True)
            continue

    # 2. batch-overflow each concern into ordered chunks (tail never dropped).
    budget = max(1, max_assets)
    chunks: list[Chunk] = []
    for concern in ("service", "data"):
        items = per_concern[concern]
        if not items:
            continue  # empty concern -> no chunk (valid)
        total = math.ceil(len(items) / budget)
        for idx in range(total):
            window = items[idx * budget:(idx + 1) * budget]
            window_assets = tuple(a for a, _ in window)
            chunks.append(Chunk(
                chunk_id=f"{source_job}:{concern}:{idx}",
                source_job=source_job,
                concern=concern,
                assets=window_assets,
                observations=_observations_for(window_assets, observations),
                batch_index=idx,
                batch_total=total,
                flagged=any(f for _, f in window),
            ))
    return chunks


def routing_pairs(chunk: Chunk) -> list[tuple[Chunk, str]]:
    """Expand a chunk to its ordered (chunk, role) pairs via `CONCERN_ROLES`
    (#13 3): a `service` chunk -> [(chunk, 'assigner'), (chunk, 'mechanism_typist')];
    a `data` chunk -> [(chunk, 'data_modeller')]. The schedule builder (2a)
    consumes this to sequence one pair per super-step."""
    return [(chunk, role) for role in CONCERN_ROLES.get(chunk.concern, ())]
