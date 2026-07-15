"""Unit tests for the D15 path-based endpoint noise classifier.

The classifier is pure; these tests pin the exact operator-approved DROP /
PRESERVE seed sets, the fingerprint rules, and the delta-level filter behavior
(hard-drop of static Endpoints, everything else untouched).
"""
import pytest

from agent.recon.noise_filter import classify_endpoint, filter_deltas, host_in_scope
from agent.recon.types import AssetDelta, Edge


# --- static-render path segments all drop ---------------------------------

@pytest.mark.parametrize("path", [
    # Non-JS assets under a static-render segment: dropped by the path rule.
    # (JS under these same segments is EXEMPT for D17 - see the JS test below.)
    "/assets/app.css",
    "/static/main.css",
    "/styles/site.scss",
    "/css/theme.css",
    "/fonts/glyphs.woff2",
    "/dist/bundle.css",
    "/build/output.html",
    "/node_modules/lib/index.html",
    "/vendor/lib.css",
    "/_next/static/chunks/pages/index.css",  # covered by the "static" segment
    "/ASSETS/App.css",                        # case-insensitive
])
def test_static_path_segments_drop(path):
    assert classify_endpoint(path) == "static"


# --- never-surface extensions all drop ------------------------------------

@pytest.mark.parametrize("ext", ["css", "scss", "less", "woff", "woff2", "ttf", "eot", "otf", "map"])
def test_static_extensions_drop(ext):
    assert classify_endpoint(f"/somewhere/thing.{ext}") == "static"


# --- fingerprinted / bundler CSS bundles drop -----------------------------
# NB: fingerprinted JS/.mjs bundles do NOT drop - they are attack surface for
# D17 (see test_javascript_always_surface_for_jsluice). Only CSS bundles, which
# are never jsluice input, remain droppable via the fingerprint/bundler rule.

@pytest.mark.parametrize("path", [
    "/main.deadbeef12.css",
    "/styles/app.4f3a2b1c.css",
    "/vendor.abc123.css",
    "/runtime.css",
])
def test_fingerprinted_css_bundles_drop(path):
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
    "/graphql",
])
def test_ambiguous_paths_kept(path):
    assert classify_endpoint(path) == "ambiguous"


# --- JavaScript is always surface (D17), even fingerprinted / under /static --

@pytest.mark.parametrize("path", [
    "/js/app.js",
    "/static/bundle.js",                 # under a drop-path but still JS
    "/static/js/main.8f3a2b1c.js",       # fingerprinted AND under /static
    "/bundle.abc123ef.js",               # fingerprinted at root
    "/assets/index-a1b2c3d4.js",         # fingerprinted under /assets
    "/vendor.js",                        # bundler marker
    "/app.mjs",
])
def test_javascript_always_surface_for_jsluice(path):
    # D15/D17 reconciliation: JS bundles are jsluice's input, never dropped as
    # presentational noise - the exemption wins over static-path + fingerprint.
    assert classify_endpoint(path) == "surface"


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
        _endpoint("/assets/main.4f3a2b1c.css"),             # static -> drop
        _endpoint("/static/main.4f3a2b1c.js"),              # JS -> keep (D17)
        _endpoint("/upload/photo.jpg"),                     # surface -> keep
        _endpoint("/api/v1/users"),                         # ambiguous -> keep
    ]
    kept = filter_deltas(deltas)
    kept_paths = [d.identity["path"] for d in kept if d.type == "Endpoint"]
    assert kept_paths == [
        "/static/main.4f3a2b1c.js", "/upload/photo.jpg", "/api/v1/users"
    ]
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


# --- out-of-scope BaseURL filtering (seed-domain scope) --------------------

@pytest.mark.parametrize("host,scope,expected", [
    ("example.com", "example.com", True),        # apex itself is in scope (D11)
    ("api.example.com", "example.com", True),     # subdomain
    ("a.b.example.com", "example.com", True),     # deep subdomain
    ("WWW.Example.com", "example.com", True),     # case-insensitive
    ("facebook.com", "example.com", False),       # unrelated social origin
    ("googletagmanager.com", "example.com", False),
    ("evil-example.com", "example.com", False),   # suffix trick, not a subdomain
    ("notexample.com", "example.com", False),
    ("app.example.com", "app.example.com", True), # exact-mode seed host
    ("api.example.com", "app.example.com", False),# sibling is out of an exact scope
])
def test_host_in_scope(host, scope, expected):
    assert host_in_scope(host, scope) is expected


def _baseurl(url):
    return AssetDelta(type="BaseURL", identity={"url": url})


def test_scope_filter_drops_out_of_scope_baseurls_and_anchored_children():
    in_base = _baseurl("https://api.example.com")
    out_base = _baseurl("https://www.facebook.com")
    # An Endpoint + a Technology, each edge-anchored to the out-of-scope host.
    out_ep = _endpoint("/tr", baseurl="https://www.facebook.com")
    out_tech = AssetDelta(
        type="Technology", identity={"name": "gtag", "version": "1"},
        edges=[Edge(rel="USES_TECHNOLOGY", dir="in", node_type="BaseURL",
                    node_identity={"url": "https://analytics.google.com"})],
    )
    in_ep = _endpoint("/api/users", baseurl="https://api.example.com")
    sub = AssetDelta(type="Subdomain", identity={"name": "x.example.com"})

    kept = filter_deltas(
        [in_base, out_base, out_ep, out_tech, in_ep, sub], scope_domain="example.com"
    )
    assert in_base in kept and in_ep in kept and sub in kept
    assert out_base not in kept and out_ep not in kept and out_tech not in kept


def test_scope_filter_noop_without_scope_domain():
    # non-www host so only the scope rule is under test here.
    out_base = _baseurl("https://facebook.com")
    # No scope_domain -> scope filtering is disabled (backward compatible).
    assert filter_deltas([out_base]) == [out_base]


def test_scope_filter_keeps_apex_and_composes_with_noise_drop():
    apex = _baseurl("https://example.com")
    static_ep = _endpoint("/assets/app.css", baseurl="https://example.com")  # noise
    js_ep = _endpoint("/static/main.abcd1234.js", baseurl="https://example.com")  # kept
    kept = filter_deltas([apex, static_ep, js_ep], scope_domain="example.com")
    assert apex in kept and js_ep in kept
    assert static_ep not in kept  # D15 noise drop still applies within scope


# --- www dedup: www.<host> is the same content as <host> -------------------

def test_www_subdomain_dropped():
    subs = [
        AssetDelta(type="Subdomain", identity={"name": "www.example.com"}),   # drop
        AssetDelta(type="Subdomain", identity={"name": "api.example.com"}),   # keep
        AssetDelta(type="Subdomain", identity={"name": "example.com"}),       # keep
    ]
    kept = [d.identity["name"] for d in filter_deltas(subs)]
    assert kept == ["api.example.com", "example.com"]


def test_www_baseurl_and_children_dropped():
    www_base = _baseurl("https://www.example.com")
    www_ep = _endpoint("/x", baseurl="https://www.example.com")
    keep_base = _baseurl("https://example.com")
    kept = filter_deltas([www_base, www_ep, keep_base])
    assert keep_base in kept
    assert www_base not in kept and www_ep not in kept


# --- D16 webapp/restapi profiling ---


def test_classify_profile_json_content_type_is_restapi():
    from agent.recon.noise_filter import classify_profile
    assert classify_profile("application/json") == "restapi"
    assert classify_profile("application/hal+json; charset=utf-8") == "restapi"


def test_classify_profile_html_or_missing_is_webapp():
    from agent.recon.noise_filter import classify_profile
    assert classify_profile("text/html; charset=utf-8") == "webapp"
    assert classify_profile(None) == "webapp"
    assert classify_profile("", "https://www.example.com") == "webapp"


def test_classify_profile_api_hostname_label_is_restapi():
    from agent.recon.noise_filter import classify_profile
    # host label match, even with a non-JSON content-type
    assert classify_profile("text/html", "https://api.example.com") == "restapi"
    assert classify_profile("text/html", "https://graphql.example.com/") == "restapi"
    assert classify_profile("text/html", "https://gw.api.example.com:443/x") == "restapi"
    # a substring like 'capillary' must NOT false-match (label-exact, not substring)
    assert classify_profile("text/html", "https://capillary.example.com") == "webapp"


# --- graphql_api profile (path heuristic, precedence over restapi/webapp) ---


@pytest.mark.parametrize("url", [
    "https://example.com/graphql",
    "https://example.com/graphql/",            # trailing slash normalized
    "https://example.com/api/graphql",
    "https://example.com/v1/graphql",
    "https://example.com/query",
    "https://example.com/graphql/console",
    "https://example.com/playground",
    "https://EXAMPLE.com/GraphQL",             # case-insensitive path
    "https://example.com/graphql?query=x",     # query string ignored
])
def test_classify_profile_graphql_path_is_graphql_api(url):
    from agent.recon.noise_filter import classify_profile
    # A JSON content-type would otherwise say restapi - the graphql path wins.
    assert classify_profile("application/json", url) == "graphql_api"


def test_graphql_api_takes_precedence_over_restapi_and_webapp():
    from agent.recon.noise_filter import classify_profile
    # graphql path beats a plain HTML app (would be webapp) ...
    assert classify_profile("text/html", "https://example.com/graphql") == "graphql_api"
    # ... and beats an api hostname label (would be restapi).
    assert classify_profile("text/html", "https://api.example.com/graphql") == "graphql_api"
    # A plain HTML app stays webapp; a JSON api host stays restapi.
    assert classify_profile("text/html", "https://example.com/") == "webapp"
    assert classify_profile("application/json", "https://api.example.com/users") == "restapi"


def test_non_graphql_paths_do_not_false_match():
    from agent.recon.noise_filter import classify_profile
    # substrings / near-misses must not match (path-exact, not substring)
    assert classify_profile("text/html", "https://example.com/graphql-docs") == "webapp"
    assert classify_profile("text/html", "https://example.com/mygraphql") == "webapp"
    assert classify_profile("text/html", "https://example.com/querybuilder") == "webapp"
