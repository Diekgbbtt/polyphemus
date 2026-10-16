"""Contract predicates (integration tier) for the chunk stream + the per-role
admission table. Mechanises C1-C12/C27 of the catalogue attached to #34, which
reshapes the increment-1 chunk builder (#23) per D1/D2/D7/D8; C2-C4 and C12b are
REWRITTEN by #48 (dataplane-A1-decisions.md section 6), which REMOVES the
httpx-profile delivery gate entirely (`chunking._gate`/`_GATED_TYPES`/
`profiled_origins`/`barrier`/`Chunk.flagged`) rather than fixing it - #34 D1
already dropped the identical gate for Endpoint, and dropping the Parameter half
too empties `_GATED_TYPES`, making the whole apparatus permanently unreachable.

These range over the pure chunk-builder and `admit_for_role`; no live graph or
LLM (the builder is pure - reads are injected as arguments). Expected values come
from the spec, not recomputed. They gate the verifier and are NOT selected by the
tdd unit red/green loop.
"""
from polymerhus.analysis.chunking import (
    ROLE_ADMITS,
    Chunk,
    admit_for_role,
    chunks_for_job,
)
from polymerhus.recon.domain.types import AssetDelta, Edge, JobSpec, Observation

JOB = JobSpec(tool="katana", skill="crawl", command_template="t", produces=["BaseURL", "Endpoint"], consumes="BaseURL")
BU = "https://a"
BU2 = "https://b"


def _ep(path, baseurl=BU):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": baseurl})


def _param(name, baseurl=BU):
    return AssetDelta(type="Parameter", identity={"name": name, "baseurl": baseurl})


def _asset(t, **identity):
    return AssetDelta(type=t, identity=identity)


# --- C1: ONE stream, no concern partition -------------------------------------

def test_C1_single_stream_no_concern_partition():
    assets = [
        _asset("BaseURL", baseurl=BU), _asset("BaseURL", baseurl=BU2),
        _ep("/x"), _ep("/y", BU2), _asset("Technology", name="nginx"),
        _param("q"), _asset("Header", name="X-Api"), _asset("Secret", key="tok"),
        _asset("Subdomain", host="s.a"), _asset("Certificate", cn="a"),
    ]
    chunks = chunks_for_job(JOB, assets, target_assets=100)
    assert len(chunks) == 1
    (chunk,) = chunks
    assert chunk.chunk_id == "katana:0"          # no concern segment
    assert not hasattr(chunk, "concern")          # the attribute is gone, not defaulted
    assert len(chunk.assets) == 10                # every asset, each exactly once
    # the Header rides ONE chunk now, not two (it was dual-concern before #34 D8)
    assert sum(1 for a in chunk.assets if a.type == "Header") == 1


# --- C2 / C3 / C4 (#48): the profile gate is REMOVED, every Endpoint AND every
# Parameter streams regardless of BaseURL profile -------------------------------

def test_C2_endpoint_streams_regardless_of_profile():
    assets = [_ep("/x", BU), _ep("/y", BU2)]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {"/x", "/y"}
    assert not hasattr(chunk, "flagged")  # the field itself is gone, not defaulted False


def test_C3_parameter_streams_regardless_of_profile():
    """#48 section 6: the Parameter gate is REMOVED (not merely bypassed) - #34 D1's
    argument for Endpoint (withholding un-profiled surface makes a never-profiled
    target indistinguishable from an empty one) applies identically here."""
    assets = [_param("q", BU), _param("r", BU2)]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["name"] for a in chunk.assets} == {"q", "r"}


# --- C5: REWRITTEN 2026-10-15 (stream hygiene) - the connectivity types do not stream

# Supersedes the pre-2026-10-15 contract ("every type is streamed, pre-HTTP
# included", #34 D8 - kept in git history). The operator decision
# (`docs/design/plans/2026-10-15-streamed-pipeline-corrections.md`, T1) grounds on
# the arm H read: Domain, IP, Port and Service streamed through this filter, but
# the chunks they formed were not harmless. The assigner yielded no turn (it
# admits Endpoint alone), while the typist typed mechanism noise off them - a
# Domain chunk produced `RESTApi core-rest` plus singletons, and a port-scan chunk
# produced `RESTApi polymerhus-agent` and `IntegrationSystem postgresql` from port
# numbers. Those four types are the stream's connectivity scaffolding, not surface
# a proposer acts on. L0 keeps them (the topology needs them) and the exclusion is
# at the STREAM, not per-role: no proposer is handed one.

def test_C5_connectivity_types_are_excluded_from_the_stream():
    assets = [_asset("Subdomain", host="s.a"), _asset("IP", address="1.2.3.4"),
              _asset("Port", number=443), _asset("Domain", name="a"),
              _asset("Service", name="http", port="443"), _ep("/x")]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.type for a in chunk.assets} == {"Subdomain", "Endpoint"}


def test_C5b_only_connectivity_assets_queue_no_chunk():
    """A delta of connectivity assets alone builds no chunk, so the pass schedules
    no dispatch and no agent turn can be yielded from it."""
    assets = [_asset("Domain", name="a"), _asset("IP", address="1.2.3.4"),
              _asset("Port", number=443), _asset("Service", name="http")]
    assert chunks_for_job(JOB, assets) == []


# --- C6: ordering / overflow --------------------------------------------------

def test_C6_overflow_ordered_tail_kept():
    assets = [_asset("Technology", name=f"t{i}") for i in range(250)]
    chunks = chunks_for_job(JOB, assets, target_assets=100)
    assert len(chunks) == 3
    assert [c.batch_index for c in chunks] == [0, 1, 2]
    assert all(c.batch_total == 3 for c in chunks)
    assert [len(c.assets) for c in chunks] == [100, 100, 50]
    assert len([a for c in chunks for a in c.assets]) == 250  # tail never dropped


# --- C7: malformed asset excluded, never crashes ------------------------------

def test_C7_malformed_asset_excluded_not_crashed():
    good = _ep("/x", BU)
    no_type = AssetDelta(type="", identity={"path": "/z", "baseurl": BU})
    (chunk,) = chunks_for_job(JOB, [good, no_type])
    assert len(chunk.assets) == 1
    assert chunk.assets[0].identity["path"] == "/x"


# --- C8: replay determinism ---------------------------------------------------

def test_C8_replay_yields_identical_chunks():
    assets = [_ep("/x", BU), _param("q", BU), _asset("Technology", name="nginx")]
    a = chunks_for_job(JOB, assets)
    b = chunks_for_job(JOB, assets)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert a == b


# --- C9 / C10 / C11 / C12: the per-role admission table (D7) ------------------

def _mixed_chunk(extra=()):
    return Chunk(chunk_id="katana:0", source_job="katana", assets=(
        _ep("/x"), _param("q"), _asset("Header", name="X-Api"),
        _asset("Technology", name="nginx"), _asset("Subdomain", host="s.a"), *extra,
    ))


def test_C9_assigner_admits_endpoints_only():
    admitted = admit_for_role(_mixed_chunk(), "assigner")
    assert len(admitted) == 1
    assert admitted[0].type == "Endpoint"


def test_C11_mechanism_typist_admits_everything_including_unmapped():
    chunk = _mixed_chunk(extra=(_asset("Frobnicate", x="1"),))
    admitted = admit_for_role(chunk, "mechanism_typist")
    assert len(admitted) == 6
    assert any(a.type == "Frobnicate" for a in admitted)  # fork H: never dropped
    assert ROLE_ADMITS["mechanism_typist"] == "*"


def test_C12_no_admissible_assets_yields_empty():
    chunk = Chunk(chunk_id="katana:0", assets=(_param("q"), _param("r")))
    assert admit_for_role(chunk, "assigner") == ()  # empty-valid, not an error


# --- C27: script Endpoints are excluded from the stream -----------------------

def test_C27_js_script_endpoints_are_excluded_for_every_agent():
    """Recon keeps producing them (jsluice mines them); no proposer wants them."""
    assets = [
        _ep("/orders/42"), _ep("/static/app.js"), _ep("/bundle.JS"),
        _ep("/main.js?v=2"), _ep("/js/api/orders"),   # a /js/ path segment is NOT a script
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {"/orders/42", "/js/api/orders"}


def test_C27b_non_endpoint_assets_found_on_scripts_survive():
    """A Parameter or Header discovered on a script is a real finding."""
    assets = [
        _ep("/app.js"),
        AssetDelta(type="Parameter", identity={"name": "token", "baseurl": BU}),
        AssetDelta(type="Header", identity={"name": "X-Api"}),
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert sorted(a.type for a in chunk.assets) == ["Header", "Parameter"]


# --- C27c-C27f: the L0 noise gate is GENERALIZED off `*.js` alone -------------
#
# The stream-level gate now drops every Endpoint that is noise from an L1
# surface-modelling perspective, so no proposer is handed one. Two independent
# signals on the bare path (query/fragment stripped first):
#   - a never-surface FILE EXTENSION (.js/.mjs/.map/.css, case-insensitive);
#   - a presentational path DIRECTORY, matched on whole path SEGMENTS - never
#     substrings, so `/api/static-data/x` is real API surface and stays.
# Recon production is untouched: it keeps producing `.js` for jsluice, and the
# exclusion fires only here, inside the stream builder.

def test_C27c_noise_extensions_are_excluded():
    assets = [
        _ep("/orders/42"),          # kept
        _ep("/app.js?v=2"),         # query stripped -> still a script
        _ep("/x.MJS"),              # case-insensitive .mjs
        _ep("/style/main.css"),     # stylesheet
        _ep("/bundle.js.map"),      # sourcemap
        _ep("/main.css#frag"),      # fragment stripped
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {"/orders/42"}


def test_C27d_noise_directories_excluded_by_segment_not_substring():
    """`assets` / `static` drop as whole SEGMENTS, never as substrings, case-insensitively."""
    assets = [
        _ep("/assets/api/users"),            # the `assets` segment -> dropped
        _ep("/static/app"),                  # the `static` segment -> dropped
        _ep("/x/static/y"),                  # `static` anywhere as a segment -> dropped
        _ep("/Assets/fonts/roboto.woff2"),   # CASE-insensitive dir rule ONLY (woff2 is not a noise ext) -> dropped
        _ep("/STATIC/data.json"),            # CASE-insensitive dir rule ONLY (json is not a noise ext) -> dropped
        _ep("/api/static-data/x"),           # `static-data` is NOT the `static` segment -> kept
        _ep("/assetsomething/x"),            # substring, NOT a segment -> kept
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {"/api/static-data/x", "/assetsomething/x"}


def test_C27e_next_layout_drops_via_the_static_segment_rule():
    """The segment rule pins the `_next/static` layout: its `static` segment drops it.
    `/_next` alone is not noise, and `_next` has no segment of its own in the rule."""
    assets = [
        _ep("/_next/data/orders.json"),        # `_next` alone is not noise -> kept
        _ep("/_next/static/chunks/main.js"),   # the `_next/static` layout -> dropped
        _ep("/assets/data.json"),              # the `assets` segment -> dropped
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {"/_next/data/orders.json"}


def test_C27f_non_endpoint_assets_on_noise_paths_survive():
    """A Parameter anchored on `/app.js` (or on an `assets` path) is a real finding."""
    assets = [
        _ep("/app.js"),
        AssetDelta(type="Parameter", identity={"name": "token", "baseurl": BU}),
        AssetDelta(type="Parameter", identity={"name": "sid", "baseurl": "https://a/assets"}),
        AssetDelta(type="Header", identity={"name": "X-Api"}),
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert sorted(a.type for a in chunk.assets) == ["Header", "Parameter", "Parameter"]


# --- C27g-C27j (2026-10-16, operator-ruled): the gate reuses recon's families -----
#
# The stream gate now SINGLE-SOURCES its extension families from recon's
# `noise_filter` (`STATIC_EXTS`/`JS_EXTS`/`IMAGE_EXTS`/`MEDIA_EXTS`), so the two
# classifiers never drift. Drop policy is two-tier, mirroring recon's recall bias
# (D15): the never-surface static families (stylesheets, fonts, sourcemaps), the
# script bundles (js/mjs) and wasm are a HARD drop; the image/media families drop
# ONLY under a whole `assets`/`static` segment, so `/uploads/x.png` and
# `/downloads/x.pdf` stay in the stream (user-controllable surface).

def test_C27g_hard_static_and_script_families_never_stream():
    assets = [
        _ep("/orders/42"),              # kept
        _ep("/styles/app.scss"),        # stylesheet pre-processor
        _ep("/styles/app.less"),
        _ep("/fonts/glyphs.woff2"),     # font
        _ep("/fonts/glyphs.ttf"),
        _ep("/app.wasm"),               # wasm
        _ep("/x.mjs"),                  # es module
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {"/orders/42"}


def test_C27h_recall_biased_media_stay_outside_presentational_segments():
    """Recon's recall bias (D15) carried into L1: a user-upload/download URL can be
    real surface (SSRF / stored-XSS / path-traversal), so an image/media extension
    is NOT a hard drop - it must keep streaming from `/uploads`, `/downloads`, etc."""
    assets = [
        _ep("/uploads/photo.png"),
        _ep("/downloads/report.pdf"),
        _ep("/media/clip.mp4"),
        _ep("/user-content/avatar.jpg"),
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {
        "/uploads/photo.png", "/downloads/report.pdf",
        "/media/clip.mp4", "/user-content/avatar.jpg",
    }


def test_C27i_recall_biased_media_drop_under_a_presentational_segment():
    assets = [
        _ep("/assets/logo.png"),
        _ep("/static/hero.jpg"),
        _ep("/downloads/assets/report.pdf"),   # an `assets` segment anywhere -> dropped
        _ep("/orders/42"),
    ]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.identity["path"] for a in chunk.assets} == {"/orders/42"}


def test_C27j_gate_families_are_single_sourced_from_noise_filter():
    """No drift: the gate's hard-drop + recall-biased sets ARE the recon families,
    never a private copy (the two classifiers must agree)."""
    from polymerhus.analysis import chunking
    from polymerhus.recon.domain import noise_filter

    assert chunking._HARD_DROP_EXTS >= noise_filter.STATIC_EXTS | noise_filter.JS_EXTS | {"wasm"}
    assert chunking._RECALL_BIASED_EXTS == noise_filter.IMAGE_EXTS | noise_filter.MEDIA_EXTS


def _obs_on(anchor_type, identity):
    return Observation(macro_kind="k", severity="info", evidence="e", rationale="r",
                       anchor={"type": anchor_type, "identity": identity},
                       source_job="triager", source_tool="triager")


def test_C28_baseurl_anchored_observation_rides_via_its_endpoints_parent():
    """Silent-empty-insight fix (chunking half). Observations are anchored UP to the
    BaseURL (curator ANCHOR_ALLOWLIST drops narrow anchors), so a chunk of Endpoints
    must carry its BaseURL's observations via the parent hop (`broaden_anchor`), even
    when the BaseURL node itself is not an asset in the chunk. An observation on an
    UNRELATED BaseURL must NOT ride."""
    on_bu = _obs_on("BaseURL", {"url": BU})            # parent of /x
    on_other = _obs_on("BaseURL", {"url": BU2})        # unrelated
    # `profiled=` dropped: the httpx-profile gate was retired entirely (#48 section
    # 6, ratified 2026-07-30, mirroring #34 D1's identical Endpoint retirement) -
    # Endpoint was never a gated type anyway, so this test's subject (parent-hop
    # observation broadening) is unaffected by the gate's removal.
    (chunk,) = chunks_for_job(JOB, [_ep("/x")], [on_bu, on_other])
    riding = [(o.anchor["type"], o.anchor["identity"]) for o in chunk.observations]
    assert ("BaseURL", {"url": BU}) in riding          # inherited from the endpoint's parent
    assert ("BaseURL", {"url": BU2}) not in riding      # unrelated BaseURL excluded


# --- D1-D8 (2026-10-15, T3): the topology-cohesive family chunker --------------
#
# The diagnosis (`docs/experiments/typist-feed-quality-diagnosis.md`) showed the
# positional 100-slice turning katana's per-transaction repeats into 12 chunks of
# ~10 facts x10, ~144k chars each. The builder now: keeps the FIRST occurrence of
# each (type, identity); groups the stream into topology families - a host's
# metadata family (BaseURL + Headers + Technologies + Certificates + host-level
# Secrets) and one endpoints family per (baseurl, content-class bucket)
# (Endpoints + their Parameters + endpoint-anchored Secrets); and closes a chunk
# once the accumulated families cross the SOFT target, so a family is atomic and
# chunks follow the graph, never an array position.

def _hdr(name, baseurl=BU, endpoint="/"):
    # Operator ruling 2026-10-16: Header identity is {name, endpoint, baseurl},
    # the value being a prop. The default endpoint `/` keeps these fixtures'
    # per-transaction repeats collapsing onto one identity.
    return AssetDelta(
        type="Header", identity={"name": name, "endpoint": endpoint, "baseurl": baseurl})


def _tech(name, baseurl=BU):
    return AssetDelta(
        type="Technology", identity={"name": name, "version": ""},
        edges=[Edge(rel="USES_TECHNOLOGY", dir="in", node_type="BaseURL",
                    node_identity={"url": baseurl})],
    )


def _ep_ct(path, content_type, baseurl=BU):
    return AssetDelta(
        type="Endpoint", identity={"path": path, "method": "GET", "baseurl": baseurl},
        props={"content_type": content_type},
    )


def _param_on(name, endpoint_path, baseurl=BU):
    return AssetDelta(
        type="Parameter",
        identity={"name": name, "position": "query", "endpoint_path": endpoint_path,
                  "baseurl": baseurl},
    )


def test_D1_identity_dedup_first_occurrence_wins():
    """A crawled transaction re-emits its BaseURL, Headers and Technologies for
    every request. The stream keeps the FIRST occurrence of each (type, identity)
    and drops the repeats - the very asset object the first transaction streamed."""
    first = _hdr("server")
    assets = [first, *[_hdr("server") for _ in range(9)], _ep("/x"), _ep("/x")]
    (chunk,) = chunks_for_job(JOB, assets)
    assert len(chunk.assets) == 2
    assert chunk.assets[0] is first
    assert sum(1 for a in chunk.assets if a.type == "Header") == 1


def test_D2_a_family_never_splits_and_the_chunk_closes_after_it():
    """Families are atomic: the chunk closes once the families added so far cross
    the soft target, never mid-family (the positional slice split at exactly 100)."""
    host_a_meta = [_asset("BaseURL", url=BU)] + [_hdr(f"h{i}") for i in range(59)]
    host_a_endpoints = [_ep(f"/p{i}") for i in range(60)]
    host_b_meta = [_asset("BaseURL", url=BU2)] + [_hdr(f"b{i}", BU2) for i in range(59)]
    chunks = chunks_for_job(JOB, host_a_meta + host_a_endpoints + host_b_meta,
                            target_assets=100)
    assert [len(c.assets) for c in chunks] == [120, 60]   # 60+60 crosses 100; the tail closes
    assert {a.identity["path"] for a in chunks[0].assets if a.type == "Endpoint"} \
        == {f"/p{i}" for i in range(60)}
    assert all(a.type != "Endpoint" for a in chunks[1].assets)


def test_D3_a_family_larger_than_the_target_goes_whole():
    """No static cap: one bucket family of 150 Endpoints is ONE cohesive chunk,
    not a 100+50 slice (cohesion wins over the target)."""
    chunks = chunks_for_job(JOB, [_ep(f"/pg{i}") for i in range(150)], target_assets=100)
    assert [len(c.assets) for c in chunks] == [150]


def test_D4_endpoints_split_into_sub_buckets_by_content_class():
    """Endpoints of one host split by what they SERVE (html / client-side code /
    UI visuals / data / other), so a chunk is homogeneous in surface class."""
    assets = [
        _ep_ct("/", "text/html; charset=utf-8"),
        _ep_ct("/app-widget", "application/javascript"),
        _ep_ct("/logo.png", "image/png"),
        _ep_ct("/config", "application/json"),
        _ep_ct("/mystery", "application/octet-stream"),
    ]
    got = {a.identity["path"]: i
           for i, c in enumerate(chunks_for_job(JOB, assets, target_assets=1))
           for a in c.assets}
    assert got == {"/": 0, "/app-widget": 1, "/logo.png": 2, "/config": 3, "/mystery": 4}
    # a small surface still lands in ONE chunk: families never split for size
    assert len(chunks_for_job(JOB, assets)) == 1


def test_D5_parameters_ride_their_endpoints_bucket_parent_first():
    chunks = chunks_for_job(JOB, [
        _ep_ct("/page", "text/html"), _param_on("q", "/page"),
        _ep_ct("/chunk", "application/javascript"), _param_on("v", "/chunk"),
    ], target_assets=1)
    assert len(chunks) == 2
    assert [a.type for a in chunks[0].assets] == ["Endpoint", "Parameter"]   # parent first
    assert chunks[0].assets[1].identity["name"] == "q"
    assert [a.type for a in chunks[1].assets] == ["Endpoint", "Parameter"]
    assert chunks[1].assets[1].identity["name"] == "v"


def test_D6_katana_shaped_stream_collapses_to_one_cohesive_chunk():
    """The arm H regression: 30 crawled transactions of one host, each re-emitting
    the BaseURL, its response headers and one Technology, plus a gated `.js`
    Endpoint. The positional builder produced 12 chunks of ~144k chars; the
    family builder produces ONE chunk of the 9 unique assets. (`date` is absent:
    the parser never mints it - operator ruling 2026-10-16.)"""
    assets = []
    for i in range(30):
        assets.append(_asset("BaseURL", url=BU))
        assets.append(_ep(f"/assets/chunk{i}.js"))
        for name in ("content-type", "content-length", "server", "etag",
                     "cache-control", "expires", "connection"):
            assets.append(_hdr(name))
        assets.append(_tech("Nginx:1.31.6"))
    (chunk,) = chunks_for_job(JOB, assets)
    assert len(chunk.assets) == 9
    assert chunk.assets[0].type == "BaseURL"      # the host anchor leads its family
    assert {a.type for a in chunk.assets} == {"BaseURL", "Header", "Technology"}
    assert sum(1 for a in chunk.assets if a.type == "Header") == 7


def test_D7_unattached_assets_keep_their_own_family_and_still_stream():
    """Fork-H: an asset whose identity carries no topology anchor keeps its own
    singleton family - it is never withheld, only deduped."""
    assets = [_asset("Subdomain", name="s.a"), _asset("Subdomain", name="s.a"), _ep("/x")]
    (chunk,) = chunks_for_job(JOB, assets)
    assert {a.type for a in chunk.assets} == {"Subdomain", "Endpoint"}
    assert len(chunk.assets) == 2


def test_D8_host_level_secret_rides_the_host_family_via_its_edge():
    """jsluice Secrets carry no identity anchor; their inbound HAS_SECRET edge is
    the topology signal. The asset rides its BaseURL's metadata family."""
    secret = AssetDelta(
        type="Secret", identity={"value_hash": "h1"},
        edges=[Edge(rel="HAS_SECRET", dir="in", node_type="BaseURL",
                    node_identity={"url": BU})],
    )
    (chunk,) = chunks_for_job(JOB, [_asset("BaseURL", url=BU), secret, _hdr("server")])
    assert {a.type for a in chunk.assets} == {"BaseURL", "Secret", "Header"}
    assert chunk.assets[0].type == "BaseURL"
