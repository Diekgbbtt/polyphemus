"""AMV-8 end-filtering-system gate assertions (catalogue in
`docs/design/amv-8-filtering-assertions.md`).

These are the verification GATE for AMV-8, not red/green unit scaffolding: each
test realises a predicate (C1-C7 contract, E1-E3 walkthrough) derived from the
operator's junk taxonomy, and drives the REAL classifier / gate / parsers. They
stay RED until the six slices land, GREEN when the gate drops the taxonomy.

Expected kept/dropped sets are the operator intent, never recomputed the way the
classifier computes them.
"""
import json

import pytest

from polymerhus.recon.domain.curator import curate
from polymerhus.recon.domain.noise_filter import filter_deltas
from polymerhus.recon.domain.parsers import jsluice_parser, katana_parser
from polymerhus.recon.domain.types import AssetDelta, Edge

BASE = "https://juice-shop.test"


def _endpoint(path, *, url=None, baseurl=BASE, source="katana"):
    return AssetDelta(
        type="Endpoint",
        identity={"path": path, "method": "GET", "baseurl": baseurl},
        props={"url": url or f"{baseurl}{path}", "source": source},
        edges=[Edge(rel="HAS_ENDPOINT", dir="in", node_type="BaseURL",
                    node_identity={"url": baseurl})],
    )


def _kept_paths(deltas):
    return [d.identity["path"] for d in deltas if d.type == "Endpoint"]


def _param_names(deltas):
    return [d.identity["name"] for d in deltas if d.type == "Parameter"]


# --- C1  cache-bust outlier (ticket 1) -------------------------------------

def test_C1_cachebust_query_does_not_escape_static_drop_and_mints_no_param():
    cache_busted = _endpoint("/main.css", url=f"{BASE}/main.css?v=15")
    real_param = _endpoint("/api/users", url=f"{BASE}/api/users?id=5")

    kept = filter_deltas([cache_busted, real_param])

    assert _kept_paths(kept) == ["/api/users"]          # cache-bust css dropped

    # cache-bust key is not surface; a real param still is (asserted at the
    # parser seam, where Parameter deltas are minted from the query string).
    cb_deltas = katana_parser.parse(json.dumps(
        {"request": {"endpoint": f"{BASE}/main.js?v=15", "method": "GET"}}))
    real_deltas = katana_parser.parse(json.dumps(
        {"request": {"endpoint": f"{BASE}/api/users?id=5", "method": "GET"}}))
    assert _param_names(cb_deltas) == []                 # no `v` Parameter
    assert _param_names(real_deltas) == ["id"]           # real param survives


# --- C2  static media / archive, recall-biased (ticket 2) ------------------

def test_C2_media_archive_recall_bias():
    deltas = [
        _endpoint("/assets/promo.mp4"),          # under drop-path -> drop
        _endpoint("/downloads/report.pdf"),      # PRESERVE segment  -> keep
        _endpoint("/clip.webm"),                 # ambiguous root    -> keep
    ]
    assert set(_kept_paths(filter_deltas(deltas))) == {
        "/downloads/report.pdf", "/clip.webm",
    }


# --- C3  primary vs generated JS (ticket 3, the sharp one) -----------------

def test_C3_primary_js_kept_generated_js_dropped():
    deltas = [
        _endpoint("/main.js"),                       # primary   -> keep
        _endpoint("/app.js"),                        # primary   -> keep
        _endpoint("/chunks/3458.js"),                # chunk     -> drop
        _endpoint("/_next/static/chunks/abc.js"),    # framework -> drop
        _endpoint("/runtime.js"),                    # bundler   -> drop
        _endpoint("/polyfills.js"),                  # bundler   -> drop
        _endpoint("/vendor.js"),                     # bundler   -> drop
    ]
    assert set(_kept_paths(filter_deltas(deltas))) == {"/main.js", "/app.js"}


# --- C4  browser-generated + analytics basenames/paths (ticket 4) ----------

def test_C4_browser_and_analytics_junk_dropped():
    deltas = [
        _endpoint("/favicon.ico"),
        _endpoint("/robots.txt"),
        _endpoint("/manifest.json"),
        _endpoint("/site.webmanifest"),
        _endpoint("/browserconfig.xml"),
        _endpoint("/apple-touch-icon.png"),
        _endpoint("/gtag/js"),
        _endpoint("/collect"),
        _endpoint("/beacon"),
        _endpoint("/pixel"),
        _endpoint("/api/login"),                     # real surface -> keep
    ]
    assert _kept_paths(filter_deltas(deltas)) == ["/api/login"]


# --- C5  jsluice concat fragment (ticket 5) --------------------------------

def test_C5_concat_fragment_dropped_real_path_kept():
    deltas = [
        _endpoint("/api/data", source="jsluice"),
        _endpoint("/'+_(i[8])+'", source="jsluice"),
        _endpoint("/%27+_%28i%5B11%5D", source="jsluice"),
    ]
    assert _kept_paths(filter_deltas(deltas)) == ["/api/data"]


# --- C6  idempotency + no-orphan + empty-valid (cross-cutting) -------------

def test_C6_gate_is_idempotent_no_orphan_and_empty_valid():
    batch = [
        _endpoint("/assets/app.css"),                # static -> drop, param-less
        _endpoint("/api/live"),                      # keep
    ]
    once = filter_deltas(batch)
    twice = filter_deltas(once)
    assert once == twice                             # pure / idempotent
    assert _param_names(once) == []                  # no orphaned Parameter
    assert filter_deltas([]) == []                   # empty is valid, not error


# --- C7  scope composition regression (category 5) -------------------------

def test_C7_out_of_scope_cdn_js_dropped_and_composes_with_noise():
    merged = []
    cdn_js = _endpoint("/x.js", baseurl="https://cdnjs.cloudflare.com")
    in_junk = _endpoint("/chunks/3458.js")           # in-scope generated js
    in_real = _endpoint("/api/orders")               # in-scope real surface
    base = AssetDelta(type="BaseURL", identity={"url": BASE})

    assets_merged, _ = curate(
        [base, cdn_js, in_junk, in_real], [], "p_test",
        merge_fn=lambda cypher, params: merged.append(params),
        scope_domain="juice-shop.test",
    )
    # BaseURL + /api/orders survive; cdn .js (scope) and chunk .js (noise) drop.
    assert assets_merged == 2


# --- E1  katana junk-laden crawl walkthrough -------------------------------

_KATANA_LINES = [
    "/juice-shop/node_modules/express/lib/router/index.js",
    "/main.js",
    "/polyfills.js",
    "/chunk-3458.js",
    "/soljson-v0.8.21+commit.a1b2c3d4.js",
    "/ethers.js",
    "/assets/logo.svg",
    "/favicon.ico",
    "/robots.txt",
    "/main.css?v=14",
    "/api/Products",
    "/rest/user/login",
]


def _katana_stdout(paths):
    return "\n".join(
        json.dumps({"request": {"endpoint": f"{BASE}{p}", "method": "GET"},
                    "response": {"status_code": 200, "content_type": "text/html"}})
        for p in paths
    )


def test_E1_katana_junk_never_becomes_endpoint():
    deltas = katana_parser.parse(_katana_stdout(_KATANA_LINES))
    kept = filter_deltas(deltas, scope_domain="juice-shop.test")

    assert set(_kept_paths(kept)) == {
        "/main.js", "/api/Products", "/rest/user/login",
    }
    assert _param_names(kept) == []                  # cache-bust `v` not orphaned
    assert any(d.type == "BaseURL" for d in kept)    # BaseURL intact


# --- E2  jsluice concat + secret walkthrough -------------------------------

def test_E2_jsluice_concat_dropped_secret_kept():
    stdout = "\n".join([
        json.dumps({"url": f"{BASE}/api/graphql", "method": "POST", "type": "fetch"}),
        json.dumps({"url": f"{BASE}/'+_(i[8])+'", "method": "GET"}),
        json.dumps({"kind": "aws-access-key",
                    "data": {"secret": "AKIAEXAMPLEKEY0001"},
                    "base_url": BASE}),
    ])
    deltas = jsluice_parser.parse(stdout)
    kept = filter_deltas(deltas, scope_domain="juice-shop.test")

    assert _kept_paths(kept) == ["/api/graphql"]
    secrets = [d for d in kept if d.type == "Secret"]
    assert len(secrets) == 1 and secrets[0].props.get("redacted") is True


# --- E3  MERGE convergence over the cleaned surface ------------------------

def test_E3_rerun_adds_no_new_endpoint_identity():
    deltas = katana_parser.parse(_katana_stdout(_KATANA_LINES))

    def run():
        merged = []
        curate([*deltas], [], "p_test",
               merge_fn=lambda cypher, params: merged.append(params),
               scope_domain="juice-shop.test")
        return merged

    first, second = run(), run()
    ep_count_first = sum(1 for p in first if p.get("id_path"))
    assert ep_count_first == 3                        # 3 real Endpoints
    assert len(first) == len(second)                  # idempotent, 0 new
