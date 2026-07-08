"""Unit tests for the D15 path-based endpoint noise classifier.

The classifier is pure; these tests pin the exact operator-approved DROP /
PRESERVE seed sets, the fingerprint rules, and the delta-level filter behavior
(hard-drop of static Endpoints, everything else untouched).
"""
import pytest

from agent.recon.noise_filter import classify_endpoint, filter_deltas
from agent.recon.types import AssetDelta, Edge


# --- static-render path segments all drop ---------------------------------

@pytest.mark.parametrize("path", [
    "/assets/app.js",
    "/static/main.js",
    "/styles/site.js",
    "/css/theme.js",
    "/fonts/glyphs.js",
    "/dist/bundle.js",
    "/build/output.js",
    "/node_modules/lib/index.js",
    "/vendor/lib.js",
    "/_next/static/chunks/pages/index.js",  # covered by the "static" segment
    "/ASSETS/App.js",                        # case-insensitive
])
def test_static_path_segments_drop(path):
    assert classify_endpoint(path) == "static"


# --- never-surface extensions all drop ------------------------------------

@pytest.mark.parametrize("ext", ["css", "scss", "less", "woff", "woff2", "ttf", "eot", "otf", "map"])
def test_static_extensions_drop(ext):
    assert classify_endpoint(f"/somewhere/thing.{ext}") == "static"


# --- fingerprinted / bundler filenames drop -------------------------------

@pytest.mark.parametrize("path", [
    "/js/app.4f3a2b1c.js",
    "/main.deadbeef12.css",
    "/x-1a2b3c4d.mjs",
    "/scripts/app_0a1b2c3d4e5f.js",
    "/runtime.js",
    "/vendor.abc123.js",
    "/polyfill-modern.mjs",
    "/chunk.2.js",
])
def test_fingerprinted_bundles_drop(path):
    assert classify_endpoint(path) == "static"


def test_bundler_marker_not_matched_as_substring():
    """`vendored-data.json` contains 'vendor' but is not a delimited bundler
    token in a js/css/mjs file - it must NOT drop (high-confidence only)."""
    assert classify_endpoint("/api/vendored-data.json") == "ambiguous"


# --- PRESERVE beats DROP: user-content path segments ----------------------

@pytest.mark.parametrize("seg", [
    "upload", "uploads", "media", "files",
    "download", "downloads", "attachment", "attachments",
    "avatar", "avatars", "user-content", "usercontent",
])
def test_user_content_segments_preserved(seg):
    # even with an otherwise-static image extension
    assert classify_endpoint(f"/{seg}/pic.png") == "surface"


def test_query_param_always_preserved_even_under_drop_path():
    """A parameterized endpoint is surface regardless of path/extension."""
    assert classify_endpoint("/assets/app.js", has_params=True) == "surface"
    assert classify_endpoint("/static/x.css", has_params=True) == "surface"


# --- image recall bias -----------------------------------------------------

@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp"])
def test_image_under_drop_path_drops(ext):
    assert classify_endpoint(f"/assets/logo.{ext}") == "static"


@pytest.mark.parametrize("path", [
    "/photo.jpg",              # root, ambiguous -> kept
    "/gallery/pic.png",        # non-drop, non-preserve -> kept
    "/upload/user123.jpg",     # user-content -> kept (surface)
    "/media/clip.gif",         # user-content -> kept (surface)
])
def test_user_controllable_images_kept(path):
    assert classify_endpoint(path) != "static"


# --- ambiguous / real endpoints kept --------------------------------------

@pytest.mark.parametrize("path", [
    "/api/v1/users",
    "/login",
    "/",
    "/js/app.js",              # "js" is NOT a listed drop segment -> kept
    "/graphql",
])
def test_ambiguous_paths_kept(path):
    assert classify_endpoint(path) == "ambiguous"


def test_empty_path_kept():
    assert classify_endpoint("") == "ambiguous"


# --- filter_deltas: hard-drop only static Endpoints -----------------------

def _endpoint(path, baseurl="https://h", url=None):
    return AssetDelta(
        type="Endpoint",
        identity={"path": path, "method": "GET", "baseurl": baseurl},
        props={"url": url or f"{baseurl}{path}", "source": "katana"},
        edges=[Edge(rel="HAS_ENDPOINT", dir="in", node_type="BaseURL",
                    node_identity={"url": baseurl})],
    )


def test_filter_drops_static_endpoints_keeps_surface():
    deltas = [
        AssetDelta(type="BaseURL", identity={"url": "https://h"}),
        _endpoint("/assets/app.css"),                       # static -> drop
        _endpoint("/static/main.4f3a2b1c.js"),              # static -> drop
        _endpoint("/upload/photo.jpg"),                     # surface -> keep
        _endpoint("/api/v1/users"),                         # ambiguous -> keep
    ]
    kept = filter_deltas(deltas)
    kept_paths = [d.identity["path"] for d in kept if d.type == "Endpoint"]
    assert kept_paths == ["/upload/photo.jpg", "/api/v1/users"]
    # BaseURL always survives
    assert any(d.type == "BaseURL" for d in kept)


def test_filter_uses_url_query_to_preserve_parameterized_endpoint():
    """An endpoint under a drop-path but with a query string is kept because its
    recorded URL carries params (has_params derived from props['url'])."""
    d = _endpoint("/assets/render", url="https://h/assets/render?src=http://x")
    assert filter_deltas([d]) == [d]


def test_filter_leaves_non_endpoint_labels_untouched():
    params = [
        AssetDelta(type="Parameter", identity={"name": "id", "position": "query",
                                               "endpoint_path": "/x", "baseurl": "https://h"}),
        AssetDelta(type="Technology", identity={"name": "nginx", "baseurl": "https://h"}),
        AssetDelta(type="Header", identity={"name": "server", "baseurl": "https://h"}),
    ]
    assert filter_deltas(params) == params


def test_filter_drops_static_endpoint_missing_url_prop():
    """No url in props -> has_params False -> path alone decides (static drops)."""
    d = AssetDelta(type="Endpoint",
                   identity={"path": "/assets/x.css", "method": "GET", "baseurl": "https://h"},
                   props={"source": "steel"})
    assert filter_deltas([d]) == []
