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

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.domain.noise_filter import (
    IMAGE_EXTS,
    JS_EXTS,
    MEDIA_EXTS,
    STATIC_EXTS,
)
from polymerhus.recon.domain.types import AssetDelta, JobSpec, Observation

logger = logging.getLogger(__name__)

# The per-chunk packing threshold (#13's asset budget, reshaped 2026-10-21 by the
# F-013 correction). The builder stacks COHERENT endpoint MICRO-FAMILIES (one
# endpoint plus the headers and parameters that target it) until adding the next
# micro-family would exceed this count. The default is 300 because a 300-asset
# prompt stayed inside the analysis role's 200K compaction budget in the canary;
# the 1,128-endpoint katana bucket that defeated compaction cannot form here.
CHUNK_MAX_ASSETS = 300

# The family-internal order: the ANCHOR first, then what it owns (the operator's
# "parent endpoint -> its headers, parameters, secrets, technologies"). A type
# beyond this table sorts last; first-seen order breaks ties.
_FAMILY_RANK: dict[str, int] = {
    "BaseURL": 0, "Endpoint": 1, "Parameter": 2, "Secret": 3,
    "Header": 4, "Technology": 5, "Certificate": 6,
}

# Noise Endpoints are EXCLUDED from the stream for every downstream agent. Recon
# must keep producing them - jsluice mines `.js` bundles for parameters and
# endpoints, and static files carry technology evidence - but a static asset file or
# a build-output directory is not itself a surface an attack acts on, so an agent
# asked to assign or type one is being handed noise. The exclusion is at the STREAM,
# not per-role: no proposer wants them. This is the L1 counterpart of recon's
# `noise_filter.classify_endpoint`, and it stays inside `chunks_for_job` so recon
# production (the jsluice input) is untouched.
#
# Decision record (operator-ruled 2026-10-16, grounded on
# `docs/experiments/typist-expression-diagnosis.md`). The families are SINGLE-SOURCED
# from recon's `noise_filter` so the stream gate and recon's own classifier never
# drift. Two tiers, mirroring recon's recall bias (D15):
#   - HARD drop (never stream): the never-surface static families (stylesheets,
#     pre-processors, fonts, sourcemaps), the script bundles (`js`/`mjs`) and `wasm`.
#     A static stylesheet/font/sourcemap is never L1 surface, and recon's `.js`
#     bundles are recon INPUT (jsluice feeds the chained API candidates), not surface.
#   - RECALL-BIASED: images and media/archives drop ONLY under a presentational path
#     segment (`assets`/`static`), because `/uploads/x.png` and `/downloads/x.pdf`
#     can be real surface (SSRF / stored-XSS / path-traversal) - dropping them by
#     extension alone would lose that surface (the D15 recall bias).
# Signals, all case-insensitive on the bare path (query string and fragment stripped
# first, so a cache-busted `/app.js?v=2` is still recognised):
#   - a never-surface FILE EXTENSION (the hard-drop families);
#   - a presentational path DIRECTORY: a path SEGMENT equal to `assets` or `static`,
#     matched on whole segments - never substrings, so `/api/static-data/x` is real
#     API surface and stays. This rule drops ANY endpoint under it, which already
#     covers the recall-biased image/media families, and the `_next/static` layout.
_HARD_DROP_EXTS = STATIC_EXTS | JS_EXTS | {"wasm"}
_RECALL_BIASED_EXTS = IMAGE_EXTS | MEDIA_EXTS
_NOISE_SEGMENTS = frozenset({"assets", "static"})

# The CONNECTIVITY types are EXCLUDED from the stream for every downstream agent
# (operator decision 2026-10-15: `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md`
# T1, grounded on the arm H read). `Domain` / `IP` / `Port` / `Service` are how the
# target is REACHED, not surface an agent acts on - they are the topology's join
# keys between names, addresses and listeners. Before this gate they streamed, and
# the chunks they formed were not harmless: the assigner yielded no judgment on
# them (it admits `Endpoint` alone) while the typist typed mechanisms OFF them - a
# Domain chunk produced `RESTApi core-rest` plus singleton systems, and a port-scan
# chunk produced `RESTApi polymerhus-agent` and `IntegrationSystem postgresql`
# inferred from port numbers alone. Recon production stays untouched (L0 keeps the
# topology); the exclusion is at the STREAM, not per-role: no proposer is handed
# one. The list is deliberately NAMED: the `ADMIT_ALL` fork-H guarantee still holds
# for every NEW type a future recon tool emits - only these four are withheld.
_CONNECTIVITY_TYPES = frozenset({"Domain", "IP", "Port", "Service"})

# The sentinel admitting EVERY asset type. Load-bearing, not a convenience: with
# more than one allow-set an asset type no role names would be admitted by nobody
# and so silently dropped, losing the increment-1 fork-H guarantee. The generalist
# role holds the sentinel, so a new recon tool's output always lands somewhere.
ADMIT_ALL = "*"

# The per-ROLE admission table (#34 D7): every asset type a recon job produces is
# streamed, and each role narrows the stream to what it can meaningfully consume.
# Role strings match `messages.Role` (no runtime import of the control plane here).
ROLE_ADMITS: dict[str, frozenset[str] | str] = {
    "assigner": frozenset({"Endpoint"}),          # one judgment: who owns this Endpoint
    "mechanism_typist": ADMIT_ALL,                 # the generalist (see ADMIT_ALL)
}

# The chunk-fed proposer roles, in dispatch order. `bootstrapper` / `anti_cluttering`
# are slice-less (they re-derive the whole live L1) and never receive a chunk.
CHUNK_ROLES: tuple[str, ...] = ("assigner", "mechanism_typist")


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


def _endpoint_extension(path: str) -> str:
    """The lowercased extension of the path's final segment ("" when there is none),
    mirroring `noise_filter._extension` so both classifiers read a filename the same
    way."""
    filename = path.rpartition("/")[2]
    return filename.rpartition(".")[2] if "." in filename else ""


def is_noise_endpoint(asset: AssetDelta) -> bool:
    """True for an Endpoint that is noise from an L1 surface-modelling perspective:
    a never-surface extension (the hard-drop families - stylesheets, fonts, sourcemaps,
    scripts and wasm) or a path segment equal to `assets` / `static` (the latter covers
    the `_next/static` layout). Matching is case-insensitive. Image/media extensions are
    NOT hard-dropped: they drop only under a presentational segment (recall bias), which
    the segment rule already enforces. See `_HARD_DROP_EXTS` for the decision record.

    Only Endpoints are judged: a Parameter or Header discovered ON a script is a real
    finding and stays in the stream."""
    if getattr(asset, "type", None) != "Endpoint":
        return False
    path = (asset.identity or {}).get("path")
    if not isinstance(path, str):
        return False
    bare = path.split("?", 1)[0].split("#", 1)[0].lower()
    segments = [seg for seg in bare.split("/") if seg]
    if _endpoint_extension(bare) in _HARD_DROP_EXTS:
        return True
    # Every other extension - the recall-biased image/media families included - drops
    # only under a whole `assets`/`static` segment, so `/uploads/x.png` stays (the
    # `_RECALL_BIASED_EXTS` families share this condition by design; see the decision
    # record above).
    return bool(_NOISE_SEGMENTS.intersection(segments))


def is_connectivity_asset(asset: AssetDelta) -> bool:
    """True for a connectivity-scaffolding asset type (`Domain` / `IP` / `Port` /
    `Service`): the type is kept in L0 - the topology's join keys - and never
    streamed to any proposer (see `_CONNECTIVITY_TYPES` for the decision record)."""
    return getattr(asset, "type", None) in _CONNECTIVITY_TYPES


def _inbound_identity(asset: AssetDelta, node_type: str) -> dict:
    """The node identity of the asset's first inbound edge of `node_type`, else {}.
    The topology a delta carries lives on BOTH `identity` (baseurl/endpoint_path)
    AND its edges: a jsluice `Secret` has neither identity key - only a HAS_SECRET
    edge to its BaseURL."""
    for edge in getattr(asset, "edges", None) or ():
        try:
            if edge.dir == "in" and edge.node_type == node_type:
                return edge.node_identity or {}
        except AttributeError:  # a malformed edge never breaks the grouping
            continue
    return {}


def _baseurl_of(asset: AssetDelta) -> str:
    """The BaseURL an asset belongs to: its `baseurl` identity key, its own `url`
    (a BaseURL asset itself), or the node identity of its inbound BaseURL edge."""
    identity = getattr(asset, "identity", None) or {}
    baseurl = identity.get("baseurl")
    if isinstance(baseurl, str) and baseurl:
        return baseurl
    if getattr(asset, "type", None) == "BaseURL":
        url = identity.get("url")
        return url if isinstance(url, str) else ""
    url = _inbound_identity(asset, "BaseURL").get("url")
    return url if isinstance(url, str) else ""


def _endpoint_path_of(asset: AssetDelta) -> str:
    """The path of the Endpoint an asset hangs off.

    Every endpoint-anchored type carries its path under a type-specific identity
    key: an Endpoint has `path`; a Parameter and a Secret have `endpoint_path`;
    a Header has `endpoint` (operator ruling 2026-10-16). The inbound Endpoint
    edge remains the fallback for an older or parser-shaped delta. Empty means
    host-anchored.
    """
    identity = getattr(asset, "identity", None) or {}
    for key in ("endpoint_path", "endpoint", "path"):
        path = identity.get(key)
        if isinstance(path, str) and path:
            return path
    path = _inbound_identity(asset, "Endpoint").get("path")
    return path if isinstance(path, str) else ""


def _family_key(asset: AssetDelta) -> tuple:
    """Where the asset belongs in the graph (F-013 correction, 2026-10-21).

    - `("endpoint", baseurl, path)`: ONE endpoint micro-family - the Endpoint
      plus the Headers, Parameters and endpoint-anchored Secrets that target
      that path. This is the coherent unit the operator described; stacking
      these units is what keeps a chunk coupled to a real graph node instead of
      to an arbitrary content bucket.
    - `("host-meta", baseurl)`: the BaseURL and its genuinely host-level
      findings (Technologies, Certificates, host-level Secrets, and Headers
      that carry no endpoint path).
    - `("asset", type, identity)`: an anchorless asset (e.g. a Subdomain) keeps
      its own singleton family and still streams (the fork-H guarantee).
    """
    baseurl = _baseurl_of(asset)
    atype = getattr(asset, "type", None)
    if not baseurl:
        return ("asset", atype, _identity_key(getattr(asset, "identity", None) or {}))
    if atype in ("Endpoint", "Parameter", "Secret", "Header"):
        path = _endpoint_path_of(asset)
        if path:
            return ("endpoint", baseurl, path)
        return ("host-meta", baseurl)
    return ("host-meta", baseurl)


def _observations_for(assets: tuple[AssetDelta, ...], observations: list[Observation]) -> tuple[Observation, ...]:
    """The observations that belong to this chunk. An observation rides the chunk
    when its anchor is either an asset in the chunk OR the PARENT broad anchor of one
    (via the curator's pure `broaden_anchor`, e.g. a `/rest/*` Endpoint -> its
    BaseURL). The parent hop is essential: the triager anchors observations UP to a
    broad asset (curator ANCHOR_ALLOWLIST drops Endpoint/Header/Parameter anchors), so
    a service chunk of Endpoints would otherwise carry NONE of its BaseURL's insights.
    Consumed by the mechanism-typist; the Assigner does not render them (#34 D5)."""
    from polymerhus.recon.domain.curator import broaden_anchor

    keys: set[tuple] = set()
    for a in assets:
        keys.add((a.type, _identity_key(a.identity)))
        parent = broaden_anchor({"type": a.type, "identity": a.identity or {}})
        if parent:
            keys.add((parent["type"], _identity_key(parent["identity"])))
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
    """Stream a job's L0 delta into ordered, topology-cohesive `Chunk`s (#13,
    reshaped by #34 D8, the profile gate removed by #48 section 6, the family
    chunker added 2026-10-15/T3). EVERY asset type that survives the
    stream-hygiene gate is streamed (malformed assets, noise Endpoints and the
    connectivity types never enter a chunk); the consuming role then narrows via
    `admit_for_role`. Pure: the deltas are read by the caller and passed in.
    Total delivery semantics: an empty delta -> []; a malformed asset is excluded
    (never crashes); replay is deterministic (the `chunk_id` is a pure function of
    source_job + batch_index).

    Three stream-level transforms, in order:

    1. FILTER - malformed assets, noise Endpoints (`is_noise_endpoint`) and the
       connectivity types (`is_connectivity_asset`) never enter the stream;
    2. COLLAPSE - the first occurrence of each `(type, identity)` wins; recon
       re-emits its BaseURL, response Headers and Technologies once per crawled
       transaction, and this is where that per-transaction flood ends;
    3. GROUP - the stream becomes coherent endpoint MICRO-FAMILIES
       (`_family_key`): one family per `(baseurl, endpoint path)` holding the
       Endpoint plus the Headers/Parameters/Secrets that target it, and one
       host-meta family per BaseURL. Families are added whole; a chunk closes
       before adding a family would exceed `CHUNK_MAX_ASSETS`, so it follows the
       graph and never an array position. The tail is never dropped."""
    observations = observations or []
    source_job = job.tool if job is not None else ""

    # 1. filter the stream (malformed assets, noise Endpoints, connectivity types).
    items: list[AssetDelta] = []
    for asset in assets:
        try:
            if not getattr(asset, "type", None):
                continue  # malformed: no type -> exclude, never crash
            if is_noise_endpoint(asset):
                continue  # static asset path: kept in L0, never streamed to an agent
            if is_connectivity_asset(asset):
                continue  # Domain/IP/Port/Service: kept in L0, never streamed to an agent
            items.append(asset)
        except Exception:  # any malformed asset degrades to exclusion, not a crash
            logger.warning("chunking: skipped a malformed asset", exc_info=True)
            continue
    if not items:
        return []  # empty delta -> no chunk (valid)

    # 2. collapse the per-transaction repeats: first (type, identity) wins.
    deduped: list[AssetDelta] = []
    seen: set[tuple] = set()
    for asset in items:
        key = (asset.type, _identity_key(asset.identity or {}))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(asset)

    # 3. group the deduped stream into coherent endpoint micro-families, order-
    # stable on first sight. A family is one endpoint plus the headers/parameters/
    # secrets that target that endpoint path; host-level findings ride host-meta.
    families: dict[tuple, list[AssetDelta]] = {}
    for asset in deduped:
        families.setdefault(_family_key(asset), []).append(asset)

    # 4. stack whole micro-families until adding the next would exceed the cap.
    # A single family above the cap is split only as a pathological safety valve.
    order = {id(asset): idx for idx, asset in enumerate(deduped)}
    windows: list[list[AssetDelta]] = []
    window: list[AssetDelta] = []
    hard_cap = max(1, max_assets)
    for members in families.values():
        members.sort(key=lambda a: (_FAMILY_RANK.get(a.type, 99), order[id(a)]))
        for start in range(0, len(members), hard_cap):
            group = members[start:start + hard_cap]
            if window and len(window) + len(group) > hard_cap:
                windows.append(window)
                window = []
            window.extend(group)
            if len(window) >= hard_cap:
                windows.append(window)
                window = []
    if window:
        windows.append(window)  # the tail is never dropped

    # 5. materialise the ordered chunks (deterministic ids and totals).
    total = len(windows)
    return [
        Chunk(
            chunk_id=f"{source_job}:{idx}",
            source_job=source_job,
            assets=tuple(window),
            observations=_observations_for(tuple(window), observations),
            batch_index=idx,
            batch_total=total,
        )
        for idx, window in enumerate(windows)
    ]


def routing_pairs(chunk: Chunk) -> list[tuple[Chunk, str]]:
    """Expand a chunk to its ordered (chunk, role) pairs (#13 3, reshaped by #34 D8):
    every chunk goes to every chunk-fed role, and `admit_for_role` decides what each
    one actually sees. A role admitting nothing from this chunk yields an empty batch,
    which the proposer already treats as a valid outcome. The schedule builder (2a)
    consumes this to sequence one pair per super-step."""
    return [(chunk, role) for role in CHUNK_ROLES]
