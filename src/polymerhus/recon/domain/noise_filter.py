"""Path-based endpoint noise classifier (forward-decision D15).

The recon attack surface is polluted by strictly presentational static assets
(stylesheets, fonts, fingerprinted bundles, images under `/assets/`), but a
blanket EXTENSION filter also discards USER-CONTROLLABLE media - a `.jpg`
referenced via a user-supplied `src` or served from `/upload/` is real surface
(SSRF / stored-XSS / path-traversal vectors). Extension alone cannot tell the
two apart, so this classifier keys on the URL PATH instead:

- DROP high-confidence static-render paths + never-surface extensions.
- PRESERVE user-content paths and ANY parameterized endpoint.
- Images are dropped ONLY when they sit under a static drop-path; anywhere
  else (root, ambiguous, user-content) they are kept.

The trade is deliberate (operator, D15): precision is traded for RECALL on
user-controllable media. A false-negative (keeping a truly-static asset) is
cheap noise; a false-positive (dropping a user-controllable image) loses real
surface. Recall is therefore protected by keeping the DROP rules
high-confidence, NOT by keeping ambiguous cases as tagged survivors.

`classify_endpoint` is pure and importable so the D16 profiling stream can
compose content-type refinement on top of the survivors. The removal is a
HARD DROP at the curator gate (`filter_deltas`): dropped Endpoints never reach
the graph, so D16 profiles only what survives this coarse first cut.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

from polymerhus.recon.domain.types import AssetDelta, Observation

# Cache-busting query keys (AMV-8 category 3): a `?v=15` / `?hash=abc` / `?t=...`
# is a version stamp on an otherwise-identical resource, never a real request
# parameter. Letting one satisfy the has-params check would let a static asset
# escape the static drop, and minting a `Parameter` for one pollutes the
# surface. Shared with `parsers._urls` (which strips these when minting
# Parameters) so both sites use the same list. Lower-cased; membership is exact
# on the key name.
CACHE_BUST_KEYS = frozenset({
    "v", "ver", "version", "hash", "t", "ts", "timestamp", "cache", "cb", "_",
})

# --- D16: webapp/restapi profiling ------------------------------------------
# Classify a probed URL from httpx-observable signals so API-specific tools
# (kiterunner, and any future api-mode ffuf) can be gated to the API surface
# via JobSpec.consumes_where, instead of firing against presentational web apps.
# A JSON-family content-type is the strong API signal; an api-indicating
# hostname LABEL is a cheap secondary hint. Everything else is a web app.
# Pure, deterministic, tolerant of missing/malformed input. Deliberately
# high-precision + minimal - extend the hint sets as needed.
Profile = Literal["webapp", "restapi", "graphql_api"]

_RESTAPI_CONTENT_MARKERS = ("json",)  # application/json, application/*+json, ...
_RESTAPI_HOST_LABELS = frozenset({"api", "apis", "rest", "graphql", "gateway"})
# Common GraphQL endpoint paths (normalized: lowercased, trailing slash
# stripped). A path match is the strongest available signal that a probed URL
# is a GraphQL surface, so it wins over the restapi/webapp content/host rules.
# Path-only heuristic - no new network I/O. An introspection `__schema` probe
# would additionally catch GraphQL under generic API hosts with a non-obvious
# path, but that needs active HTTP in the profiling stage (deliberately not done).
_GRAPHQL_PATHS = frozenset({
    "/graphql", "/api/graphql", "/v1/graphql", "/query",
    "/graphql/console", "/playground",
})


def classify_profile(content_type: str | None, url: str | None = None) -> Profile:
    """Return 'graphql_api' when the URL path is a known GraphQL endpoint;
    else 'restapi' when the response looks like an API (a JSON-family
    content-type, or an api-indicating hostname label); else 'webapp'."""
    host = ""
    path = ""
    if isinstance(url, str):
        # scheme://host[:port]/path?query -> bare host + path, tolerant of
        # missing parts.
        after_scheme = url.split("://", 1)[-1]
        host = after_scheme.split("/", 1)[0].split(":", 1)[0].lower()
        rest = after_scheme[len(after_scheme.split("/", 1)[0]):]
        path = rest.split("?", 1)[0].split("#", 1)[0].lower()
    # graphql_api takes precedence: a known GraphQL path is the strongest signal.
    normalized = path.rstrip("/") or "/"
    if normalized in _GRAPHQL_PATHS:
        return "graphql_api"
    if any(m in (content_type or "").lower() for m in _RESTAPI_CONTENT_MARKERS):
        return "restapi"
    if _RESTAPI_HOST_LABELS.intersection(host.split(".")):
        return "restapi"
    return "webapp"


Classification = Literal["static", "surface", "ambiguous"]

# Path segments that mark a strictly-presentational static-render tree. A path
# containing any of these (and no user-content marker / query param) is noise.
DROP_SEGMENTS = frozenset({
    "assets", "static", "styles", "css", "fonts",
    "dist", "build", "node_modules", "vendor",
    "_next", "chunks", "bower_components",
})

# Extensions that are NEVER user-controllable surface (stylesheets, fonts,
# sourcemaps). Presence of one of these on the filename is sufficient to drop.
STATIC_EXTS = frozenset({
    "css", "scss", "less", "woff", "woff2", "ttf", "eot", "otf", "map",
})

# Image extensions: these MAY be user-controllable, so they are dropped only
# when the path also sits under a DROP_SEGMENT; otherwise kept (recall bias).
IMAGE_EXTS = frozenset({
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp",
})

# Media / archive / document extensions (AMV-8 category 1). Like images, these
# MAY be user-uploaded content (a `/downloads/report.pdf`, a `/upload/clip.mp4`
# is real SSRF / stored-file / path-traversal surface), so they take the SAME
# recall-biased treatment: dropped only under a DROP_SEGMENT, else kept as
# ambiguous. A blanket extension drop would lose that surface (D15's recall
# bias). Truly-presentational families (fonts, stylesheets, sourcemaps) stay in
# the hard-static STATIC_EXTS above.
MEDIA_EXTS = frozenset({
    "mp3", "wav", "mp4", "webm", "mov", "avi", "mkv", "flac", "ogg",
    "pdf", "zip", "tar", "gz", "tgz", "rar", "7z", "bz2",
})

# JavaScript is PRIME attack surface: a `.js`/`.mjs` bundle is the input jsluice
# fetches to recover endpoints + secrets and to discover sourcemaps (forward
# decision D17), so a PRIMARY application bundle is never dropped - a
# fingerprinted SPA bundle (`main.8f3a2b1c.js`) under `/static` or `/assets`
# still reaches the graph for D17 to analyze. Without that exemption D15 would
# starve D17 of its primary input.
#
# AMV-8 category 2 refines the exemption: GENERATED JS - framework runtime,
# lazy-loaded chunks, installed deps, and vendored library bundles - are NOT
# application surface (the operator's "the JS files are the recon target, the
# generated chunk URLs are not application endpoints"). A `.js` is dropped when
# it carries a generated signal (a framework segment, a bundler/chunk/runtime
# marker, or a known vendor-library name). A content hash ALONE never drops a
# JS file, because the primary app bundle is itself fingerprinted.
JS_EXTS = frozenset({"js", "mjs"})

# Path segments that mint GENERATED JS (framework internals, code-split chunks,
# installed deps). A `.js` under one is a generated asset, not a primary bundle,
# so the keep-JS exemption does not apply. A subset of DROP_SEGMENTS - the
# framework/dependency dirs specifically, not the presentational ones (`/static`,
# `/assets` legitimately host the primary fingerprinted bundle, so JS there is
# still kept).
GENERATED_JS_SEGMENTS = frozenset({
    "node_modules", "_next", "chunks", "bower_components",
})

# Bundler / framework-runtime filename markers (optional plural), matched as a
# delimited token: `runtime.js`, `polyfills.js`, `chunk-3458.js`, `vendor.js`,
# `main-es2015.chunk.js`.
_GENERATED_JS_MARKER_RE = re.compile(
    r"(?:^|[.\-_])(?:chunk|runtime|polyfill|vendor)s?(?:[.\-_]|$)"
)

# Third-party library bundles pulled into a page (web3 / crypto / framework
# libs). Matched on the filename STEM prefix so versioned blobs collapse
# (`soljson-v0.8.21+commit.<hash>.js`, `ethers-5.7.2.js`). Deliberately a short,
# high-confidence list of names that are essentially never a first-party route
# file; extend as evidence accrues.
VENDOR_JS_PREFIXES = (
    "soljson", "ethers", "web3", "jquery", "bootstrap", "lodash", "moment",
    "angular", "react", "react-dom", "vue", "three", "d3",
)

# Browser-generated well-known files (AMV-8 category 6): a browser requests
# these automatically; they are not application surface. Matched on the exact
# BASENAME (the last path segment), lower-cased.
BROWSER_BASENAMES = frozenset({
    "favicon.ico", "robots.txt", "manifest.json", "site.webmanifest",
    "browserconfig.xml", "apple-touch-icon.png",
    "apple-touch-icon-precomposed.png",
})

# Analytics / telemetry path segments (AMV-8 category 4): first-party analytics
# collection endpoints (Google Analytics `/collect`, `gtag`, tracking pixels,
# beacons). A path containing one of these segments is telemetry, not
# application surface. High-confidence conventions only - generic `/events`,
# `/log` are deliberately excluded (too likely to be real API surface).
ANALYTICS_SEGMENTS = frozenset({
    "collect", "beacon", "pixel", "gtag", "analytics",
})

# Path segments that affirmatively mark user-controllable / user-uploaded
# content. Any of these forces PRESERVE regardless of extension.
PRESERVE_SEGMENTS = frozenset({
    "upload", "uploads", "media", "files",
    "download", "downloads", "attachment", "attachments",
    "avatar", "avatars", "user-content", "usercontent",
})

# Fingerprinted content-hashed bundle: `app.4f3a2b1c.js`, `main-deadbeef.css`,
# `x_1a2b3c4d.mjs`. A hex hash of >= 8 chars delimited before a js/css/mjs ext.
_FINGERPRINT_RE = re.compile(r"[.\-_][0-9a-f]{8,}\.(?:js|css|mjs)$")

# Bundler-marker filenames (`runtime.js`, `vendor.abc.js`, `polyfill-x.mjs`).
# Matched only as a delimited token to avoid dropping e.g. `vendored-data.json`.
_BUNDLER_MARKER_RE = re.compile(r"(?:^|[.\-_])(?:chunk|runtime|polyfill|vendor)(?:[.\-_]|$)")
_BUNDLE_EXTS = frozenset({"js", "css", "mjs"})


def _path_segments(path: str) -> list[str]:
    """Lowercased, non-empty path segments (query/fragment stripped)."""
    path = path.split("#", 1)[0].split("?", 1)[0].lower()
    return [seg for seg in path.split("/") if seg]


def _extension(filename: str) -> str:
    """Extension of a filename (after the last dot), lowercased, else ""."""
    if "." not in filename:
        return ""
    return filename.rpartition(".")[2]


def _is_fingerprinted_bundle(filename: str) -> bool:
    if _FINGERPRINT_RE.search(filename):
        return True
    if _extension(filename) in _BUNDLE_EXTS and _BUNDLER_MARKER_RE.search(filename):
        return True
    return False


def _is_generated_js(filename: str, seg_set: set[str]) -> bool:
    """True when a `.js`/`.mjs` file is GENERATED (framework runtime, code-split
    chunk, installed dep, or vendored library) rather than a primary application
    bundle - so the D17 keep-JS exemption must NOT apply. A content hash alone is
    deliberately NOT a signal here (the primary bundle is fingerprinted too)."""
    if seg_set & GENERATED_JS_SEGMENTS:
        return True
    if _GENERATED_JS_MARKER_RE.search(filename):
        return True
    stem = filename.rpartition(".")[0].lower()
    return any(stem == p or stem.startswith(p + "-") or stem.startswith(p + ".")
               for p in VENDOR_JS_PREFIXES)


def classify_endpoint(path: str, *, has_params: bool = False) -> Classification:
    """Classify an endpoint path as static noise, user-controllable surface, or
    ambiguous (kept by recall bias).

    Precedence (PRESERVE beats DROP so the recall bias always wins):
      1. a query parameter present            -> "surface"
      2. a user-content path segment          -> "surface"
      3. a browser well-known / analytics path -> "static" (never app surface)
      4. a JavaScript extension (.js/.mjs)     -> "surface" unless generated
      5. a never-surface extension            -> "static"
      6. a fingerprinted / bundler filename   -> "static"
      7. an image / media / archive extension -> "static" iff under a drop-path,
                                                 else "ambiguous" (recall bias)
      8. any static-render path segment       -> "static"
      9. otherwise                            -> "ambiguous"
    """
    if has_params:
        return "surface"

    segments = _path_segments(path or "/")
    seg_set = set(segments)

    if seg_set & PRESERVE_SEGMENTS:
        return "surface"

    filename = segments[-1] if segments else ""

    # Browser well-known files and analytics/telemetry paths are never
    # application surface - drop before the JS exemption so `/gtag/js` drops.
    if filename in BROWSER_BASENAMES or (seg_set & ANALYTICS_SEGMENTS):
        return "static"

    ext = _extension(filename)
    under_drop_path = bool(seg_set & DROP_SEGMENTS)

    # JavaScript is attack surface for D17 (jsluice): a PRIMARY bundle is kept
    # even when fingerprinted or under a presentational drop-path. GENERATED JS
    # (framework runtime, code-split chunks, installed deps, vendor libs) is not
    # application surface and drops (AMV-8 category 2).
    if ext in JS_EXTS:
        return "static" if _is_generated_js(filename, seg_set) else "surface"

    if ext in STATIC_EXTS:
        return "static"
    if _is_fingerprinted_bundle(filename):
        return "static"
    if ext in IMAGE_EXTS or ext in MEDIA_EXTS:
        return "static" if under_drop_path else "ambiguous"
    if under_drop_path:
        return "static"
    return "ambiguous"


# A minified JS member-expression mis-read as a path SEGMENT: a single-letter
# root (a minified variable name like `i`, `l`, `r`, `e`) followed by one or
# more dotted properties, matching the WHOLE segment. Catches the AMV-8 e2e
# residuals `i.document`, `l.number`, `r.dom.offsetHeight`, `e.do`,
# `i.visualViewport.scale`. Anchored + single-letter-root so real dotted
# filenames (`verify.js`, `login.do`, `main.8f3a2b1c.js`) never match - their
# root component is multi-character.
_JS_EXPR_SEGMENT_RE = re.compile(r"^[a-z]\.[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*$")


def is_malformed_concat_path(path: str) -> bool:
    """True when a path is a JS source fragment / templating artifact, not a
    real path (AMV-8 ticket 5, extended by the live e2e).

    Categories, all high-precision on markers essentially never in a real URL
    path (the path is percent-decoded first, so encoded forms are caught too):

    - **string-concatenation fragments** - jsluice/katana mis-read source like
      `fetch('/api/'+id)` and emit `/'+_(i[8])+'` / `/%27+_%28i%5B11%5D`:
      a literal quote/backtick, the `+_(` marker, or unbalanced brackets/parens.
    - **minified member-expression segments** - katana's JS crawl emits
      `/i.document.do`, `/l.number/e.do`, `/r.dom.offsetHeight`: a path segment
      that is entirely a single-letter-rooted dotted expression.
    - **template placeholders** - `/{{href}}` / `/%7B%7Bhref%7D%7D`: `{{`/`}}`.

    A real path (a `+` in a versioned filename, a multi-char dotted filename like
    `verify.js`, a real `/login.do`) has none of these, so it is not affected.

    Enforced at BOTH parse time (`parsers._urls.url_to_deltas`, so no delta is
    minted) and the curator gate (`filter_deltas`, so a fragment from any source
    is dropped) - defense in depth."""
    if not isinstance(path, str) or not path:
        return False
    decoded = unquote(path)
    if any(q in decoded for q in ("'", '"', "`")):
        return True
    if "+_(" in decoded:
        return True
    if "{{" in decoded or "}}" in decoded:  # templating placeholder
        return True
    for open_c, close_c in (("(", ")"), ("[", "]"), ("{", "}")):
        if decoded.count(open_c) != decoded.count(close_c):
            return True
    for seg in decoded.split("/"):
        if seg and _JS_EXPR_SEGMENT_RE.match(seg):
            return True
    return False


def _netloc_host(netloc: str) -> str:
    """Bare host from a URL netloc: strip userinfo and port, handle IPv6."""
    netloc = netloc.rsplit("@", 1)[-1]
    if netloc.startswith("["):            # IPv6 literal [::1]:443
        return netloc[1:].split("]", 1)[0].lower()
    return netloc.split(":", 1)[0].lower().rstrip(".")


def _host_of_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        return ""
    try:
        return _netloc_host(urlparse(url).netloc)
    except ValueError:
        return ""


def host_in_scope(host: str, scope_domain: str) -> bool:
    """True when `host` is the scope domain itself or a subdomain of it.

    The scope domain is the seeded target (D14): the exact host in exact mode,
    the registrable apex in wildcard mode. Both admit the domain itself (the
    apex is in scope and is explicitly probed, D11) and any subdomain of it.
    """
    host = (host or "").lower().rstrip(".")
    scope = (scope_domain or "").lower().rstrip(".")
    if not host or not scope:
        return False
    return host == scope or host.endswith("." + scope)


def _referenced_base_hosts(delta: AssetDelta) -> list[str]:
    """Hosts of every BaseURL this delta is anchored to: its own `url`/`baseurl`
    identity plus any BaseURL node its edges reference. A delta with none (a
    Subdomain / IP / Port / Domain) is not a URL-hosted asset and is never
    scope-filtered here - host scope for those is the discovery gate's job."""
    urls: list[str] = []
    for key in ("url", "baseurl"):
        val = delta.identity.get(key)
        if isinstance(val, str):
            urls.append(val)
    for edge in delta.edges:
        if edge.node_type == "BaseURL":
            val = edge.node_identity.get("url")
            if isinstance(val, str):
                urls.append(val)
    return [_host_of_url(u) for u in urls]


def _delta_out_of_scope(delta: AssetDelta, scope_domain: str) -> bool:
    """A URL-hosted delta is out of scope when ANY BaseURL it is anchored to
    sits outside the seed domain's subtree. Dropping every delta anchored to an
    out-of-scope BaseURL (the BaseURL, its Endpoints, Headers, Technology,
    Certificate, Parameters) removes the host cleanly with no orphaned stub -
    the edges that would otherwise MERGE-recreate it are dropped too."""
    hosts = _referenced_base_hosts(delta)
    if not hosts:
        return False
    return any(not host_in_scope(h, scope_domain) for h in hosts)


def _delta_is_www_redundant(delta: AssetDelta) -> bool:
    """A `www.`-prefixed host is conventionally the same web content as the bare
    host, so it must not become a second Subdomain / BaseURL (dedup, D-www).

    - a `Subdomain` named `www.<x>` dups its parent host: dropping it here means
      httpx (which reads Subdomain nodes from the graph in a later phase) never
      probes it, so no `www.` BaseURL is ever produced;
    - a `BaseURL` (or an Endpoint/Header/... anchored to one) on a `www.` host
      dedups to the non-www host and is dropped with its children (belt, for the
      apex/gau/katana paths that can mint a `www.` BaseURL directly).
    """
    if delta.type == "Subdomain":
        name = delta.identity.get("name", "")
        return isinstance(name, str) and name.lower().startswith("www.")
    return any(h.startswith("www.") for h in _referenced_base_hosts(delta))


def _has_meaningful_query(url: str) -> bool:
    """True when the URL carries a query with at least one NON-cache-bust key.

    A `?v=15` / `?hash=abc` is a version stamp, not a real parameter (AMV-8
    category 3), so it must not count as "has params" - otherwise a cache-busted
    static asset (`/main.css?v=15`) would satisfy the has-params short-circuit
    and escape the static drop."""
    try:
        query = urlparse(url).query
    except ValueError:
        return False
    if not query:
        return False
    keys = parse_qs(query, keep_blank_values=True).keys()
    return any(k.lower() not in CACHE_BUST_KEYS for k in keys)


def _endpoint_has_params(delta: AssetDelta) -> bool:
    """True when the endpoint's recorded URL carries a MEANINGFUL query string.
    The URL in `props` already reflects the discovered query (parsers build
    Parameter deltas FROM it), so it is the authoritative signal without
    cross-referencing sibling Parameter deltas. Cache-bust-only queries do not
    count (see `_has_meaningful_query`)."""
    url = delta.props.get("url")
    if not isinstance(url, str) or not url:
        return False
    return _has_meaningful_query(url)


def filter_deltas(
    deltas: list[AssetDelta], scope_domain: str | None = None
) -> list[AssetDelta]:
    """Central curator-gate hard filter. Two independent drops:

    1. Static-noise Endpoints (D15): a param-less presentational Endpoint
       (`/assets/app.css`, fonts, images under a static path) is dropped. A
       dropped static Endpoint is param-less by construction, so no Parameter
       delta is orphaned.

    2. Out-of-scope hosts (when `scope_domain` is given): httpx and katana
       surface BaseURLs that are not the target - social/analytics/integration
       origins linked from the page (facebook.com, googletagmanager.com, ...).
       A BaseURL must be the seed domain or a subdomain of it; any delta
       anchored to an out-of-scope BaseURL (the BaseURL and its Endpoints,
       Headers, Technology, Certificate, Parameters) is dropped together, so
       nothing is orphaned. Deltas with no BaseURL anchor (Subdomain, IP, Port,
       Domain, DNSRecord) are untouched here - their scope is the D14 discovery
       gate, not this URL filter.
    """
    kept: list[AssetDelta] = []
    for delta in deltas:
        if delta.type == "Endpoint":
            path = delta.identity.get("path", "/")
            # A JS string-concatenation fragment is not a real path (AMV-8) -
            # drop it whatever its params look like.
            if is_malformed_concat_path(path):
                continue
            if classify_endpoint(path, has_params=_endpoint_has_params(delta)) == "static":
                continue
        # www.<host> dedups to <host> (unconditional - the www convention holds
        # whether the seed was exact or wildcard).
        if _delta_is_www_redundant(delta):
            continue
        if scope_domain and _delta_out_of_scope(delta, scope_domain):
            continue
        kept.append(delta)
    return kept


def filter_observations(
    observations: list[Observation], scope_domain: str | None = None
) -> list[Observation]:
    """Drop observations whose anchor is a URL-hosted node (BaseURL) outside
    scope_domain, mirroring filter_deltas for assets. Non-URL anchors
    (Domain/Subdomain/IP/Service) are untouched - their scope is the D14
    discovery gate, not this URL filter. No-op when scope_domain is falsy.

    Fail-open: an observation whose anchor host cannot be resolved is kept -
    scope filtering never drops an observation it cannot classify.
    """
    if not scope_domain:
        return observations

    kept: list[Observation] = []
    for obs in observations:
        anchor = obs.anchor if isinstance(obs.anchor, dict) else {}
        # Only BaseURL anchors are URL-hosted (the sole URL-bearing type in
        # ANCHOR_ALLOWLIST); every other anchor type is out of this filter's scope.
        if anchor.get("type") == "BaseURL":
            identity = anchor.get("identity")
            url = ""
            if isinstance(identity, dict):
                for key in ("url", "baseurl", "name"):
                    val = identity.get(key)
                    if isinstance(val, str) and val:
                        url = val
                        break
            host = _host_of_url(url)
            if host and not host_in_scope(host, scope_domain):
                continue
        kept.append(obs)
    return kept
