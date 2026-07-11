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
from urllib.parse import urlparse

from agent.recon.types import AssetDelta

# --- D16: webapp/webapi profiling ------------------------------------------
# Classify a probed URL from httpx-observable signals so API-specific tools
# (kiterunner, and any future api-mode ffuf) can be gated to the API surface
# via JobSpec.consumes_where, instead of firing against presentational web apps.
# A JSON-family content-type is the strong API signal; an api-indicating
# hostname LABEL is a cheap secondary hint. Everything else is a web app.
# Pure, deterministic, tolerant of missing/malformed input. Deliberately
# high-precision + minimal - extend the hint sets as needed.
Profile = Literal["webapp", "webapi"]

_WEBAPI_CONTENT_MARKERS = ("json",)  # application/json, application/*+json, ...
_WEBAPI_HOST_LABELS = frozenset({"api", "apis", "rest", "graphql", "gateway"})


def classify_profile(content_type: str | None, url: str | None = None) -> Profile:
    """Return 'webapi' when the response looks like an API (a JSON-family
    content-type, or an api-indicating hostname label), else 'webapp'."""
    if any(m in (content_type or "").lower() for m in _WEBAPI_CONTENT_MARKERS):
        return "webapi"
    host = ""
    if isinstance(url, str):
        # scheme://host[:port][/path] -> bare host, tolerant of missing parts.
        host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    if _WEBAPI_HOST_LABELS.intersection(host.split(".")):
        return "webapi"
    return "webapp"


Classification = Literal["static", "surface", "ambiguous"]

# Path segments that mark a strictly-presentational static-render tree. A path
# containing any of these (and no user-content marker / query param) is noise.
DROP_SEGMENTS = frozenset({
    "assets", "static", "styles", "css", "fonts",
    "dist", "build", "node_modules", "vendor",
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

# JavaScript is NEVER dropped as noise: a `.js`/`.mjs` bundle is prime attack
# surface (it is the input jsluice fetches to recover endpoints + secrets and
# to discover sourcemaps - forward decision D17). This exemption wins over the
# static-path and fingerprint drops below, so a fingerprinted SPA bundle under
# `/static` or `/assets` still reaches the graph for D17 to analyze. Without it
# D15 would starve D17 of its primary input (the two features collide - the
# bundles D15 calls "noise" for surface-mapping are D17's gold for extraction).
JS_EXTS = frozenset({"js", "mjs"})

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


def classify_endpoint(path: str, *, has_params: bool = False) -> Classification:
    """Classify an endpoint path as static noise, user-controllable surface, or
    ambiguous (kept by recall bias).

    Precedence (PRESERVE beats DROP so the recall bias always wins):
      1. a query parameter present            -> "surface"
      2. a user-content path segment          -> "surface"
      3. a JavaScript extension (.js/.mjs)     -> "surface" (D17 attack surface)
      4. a never-surface extension            -> "static"
      5. a fingerprinted / bundler filename   -> "static"
      6. an image extension                   -> "static" iff under a drop-path,
                                                 else "ambiguous"
      7. any static-render path segment       -> "static"
      8. otherwise                            -> "ambiguous"
    """
    if has_params:
        return "surface"

    segments = _path_segments(path or "/")
    seg_set = set(segments)

    if seg_set & PRESERVE_SEGMENTS:
        return "surface"

    filename = segments[-1] if segments else ""
    ext = _extension(filename)
    under_drop_path = bool(seg_set & DROP_SEGMENTS)

    # JavaScript is attack surface for D17 (jsluice), never presentational
    # noise - keep it even when fingerprinted or under a static drop-path.
    if ext in JS_EXTS:
        return "surface"

    if ext in STATIC_EXTS:
        return "static"
    if _is_fingerprinted_bundle(filename):
        return "static"
    if ext in IMAGE_EXTS:
        return "static" if under_drop_path else "ambiguous"
    if under_drop_path:
        return "static"
    return "ambiguous"


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


def _endpoint_has_params(delta: AssetDelta) -> bool:
    """True when the endpoint's recorded URL carries a query string. The URL in
    `props` already reflects the discovered query (parsers build Parameter
    deltas FROM it), so it is the authoritative signal without cross-referencing
    sibling Parameter deltas."""
    url = delta.props.get("url")
    if not isinstance(url, str) or not url:
        return False
    try:
        return bool(urlparse(url).query)
    except ValueError:
        return False


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
