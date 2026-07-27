"""Evidence-derived API-root scoping for the API-enumeration tools (D16 split).

`kiterunner` needs a base path to fuzz routes under. Rather than fuzz a host
root (imprecise, wordlist-dependent) or guess from a broad api-noun list, we
derive the base from the EVIDENCE already in the graph: the host's own
`restapi`-profiled Endpoint paths.

The residual heuristic is confined to two constants: `API_NOUNS` (segments that
mark an API mount / paradigm boundary) and the `^v\\d+$` version pattern.
Version tokens are deliberately NOT nouns and never part of a derived prefix -
they are left inside the fuzz space so kiterunner's own `v1`/`v2` wordlist
entries discover them, including unlinked/deprecated ("zombie") versions.

`AssetSelector` is a per-asset predicate and cannot aggregate a host's endpoint
set, so this derivation runs in kiterunner's input-preparation seam (the same
seam jsluice batching uses). Everything here is pure, deterministic (stable
ordering) and unit-testable without a network or Neo4j.
"""
from __future__ import annotations

import re

# API mount / paradigm boundary segments. A resource name (`users`, `orders`)
# is deliberately NOT here: we cut at the LAST noun, so a resource noun would
# push the cut too deep and defeat the fuzz-and-descend goal. Resources are
# handled by the parent-directory fallback instead. Ratified with the operator
# (workflow #28); extend as needed.
API_NOUNS = frozenset({
    "api", "apis", "rest", "restapi", "graphql", "gql", "rpc", "jsonrpc",
    "grpc", "soap", "xmlrpc", "gateway", "data",
    # infra / audience mounts
    "internal", "external", "private", "partner", "edge", "proxy",
})

_VERSION_RE = re.compile(r"^v\d+$")


def _segments(path: str) -> list[str]:
    """Non-empty, lower-cased path segments."""
    return [s for s in path.lower().split("/") if s]


def derive_api_prefix(path: str) -> str:
    """The API-root prefix to scope a fuzzer under, for one endpoint path.

    Cut at the LAST api-noun segment (versions are not nouns); the prefix is the
    path up to and including that segment. If the path has no api-noun, fall
    back to the endpoint's parent directory. Always returns a `/`-bounded
    prefix (at minimum `/`).
    """
    segs = _segments(path)
    if not segs:
        return "/"

    last_noun = -1
    for i, seg in enumerate(segs):
        if seg in API_NOUNS and not _VERSION_RE.match(seg):
            last_noun = i

    if last_noun >= 0:
        return "/" + "/".join(segs[: last_noun + 1]) + "/"

    # No api-noun anywhere: parent directory of the endpoint.
    if len(segs) <= 1:
        return "/"
    return "/" + "/".join(segs[:-1]) + "/"


def derive_scan_targets(base_url: str, restapi_paths: list[str], cap: int = 3) -> list[str]:
    """Derive the kiterunner scan-target URLs for one host.

    Groups the host's `restapi` endpoint paths by their derived api-root prefix,
    keeps the `cap` prefixes covering the most endpoints (deterministic:
    coverage desc, then prefix asc), and returns `<base_url><prefix>` per kept
    prefix. `base_url` is a `scheme://netloc` with no trailing slash.
    """
    counts: dict[str, int] = {}
    for path in restapi_paths:
        prefix = derive_api_prefix(path)
        counts[prefix] = counts.get(prefix, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    kept = [prefix for prefix, _ in ranked[:cap]]
    return [f"{base_url}{prefix}" for prefix in kept]
