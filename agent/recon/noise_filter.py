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
      3. a never-surface extension            -> "static"
      4. a fingerprinted / bundler filename   -> "static"
      5. an image extension                   -> "static" iff under a drop-path,
                                                 else "ambiguous"
      6. any static-render path segment       -> "static"
      7. otherwise                            -> "ambiguous"
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

    if ext in STATIC_EXTS:
        return "static"
    if _is_fingerprinted_bundle(filename):
        return "static"
    if ext in IMAGE_EXTS:
        return "static" if under_drop_path else "ambiguous"
    if under_drop_path:
        return "static"
    return "ambiguous"


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


def filter_deltas(deltas: list[AssetDelta]) -> list[AssetDelta]:
    """Drop Endpoint deltas classified as static noise; pass everything else
    (BaseURL, Parameter, and all other labels) through untouched.

    A dropped static Endpoint is param-less by construction (a parameterized
    endpoint classifies "surface" and is kept), so its associated Parameter
    deltas do not exist and nothing is orphaned. BaseURL deltas are never
    dropped - hosts are always legitimate surface.
    """
    kept: list[AssetDelta] = []
    for delta in deltas:
        if delta.type == "Endpoint":
            path = delta.identity.get("path", "/")
            if classify_endpoint(path, has_params=_endpoint_has_params(delta)) == "static":
                continue
        kept.append(delta)
    return kept
