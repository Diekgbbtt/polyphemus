import json
import ssl
import subprocess
import urllib.request

from polymerhus.recon.scripts import jsluice_scan as js


# --------------------------- identification ------------------------------- #
def test_extract_sourcemap_url_from_comment_resolved_absolute():
    content = "console.log(1)\n//# sourceMappingURL=app.4f3a.js.map\n"
    assert js.extract_sourcemap_url(content, "https://h.example.com/static/app.4f3a.js") == (
        "https://h.example.com/static/app.4f3a.js.map"
    )


def test_extract_sourcemap_url_at_variant_comment():
    content = "x=1//@ sourceMappingURL=/maps/m.map"
    assert js.extract_sourcemap_url(content, "https://h.example.com/a/b.js") == (
        "https://h.example.com/maps/m.map"
    )


def test_extract_sourcemap_url_absent_returns_none():
    assert js.extract_sourcemap_url("no map here", "https://h/x.js") is None


def test_candidate_prefers_comment_over_fallback_probe():
    content = "//# sourceMappingURL=real.map"
    assert js.sourcemap_candidate(content, "https://h/x.js") == "https://h/real.map"


def test_candidate_falls_back_to_bundle_plus_map_when_no_comment():
    assert js.sourcemap_candidate("no comment", "https://h/x.js") == "https://h/x.js.map"


def test_candidate_direct_map_url_is_itself():
    assert js.sourcemap_candidate("", "https://h/x.js.map") == "https://h/x.js.map"


# ------------------------------- filtering -------------------------------- #
def test_should_scan_source_drops_presentational_and_map():
    for p in ("a/b.css", "x.scss", "img.png", "i.jpg", "p.jpeg", "g.gif", "v.svg", "m.map"):
        assert not js.should_scan_source(p), p


def test_should_scan_source_drops_webpack_and_node_modules():
    assert not js.should_scan_source("webpack/bootstrap/x.js")
    assert not js.should_scan_source("node_modules/react/index.js")


def test_should_scan_source_keeps_node_modules_internal():
    assert js.should_scan_source("node_modules/@acme/internal/secrets.js")


def test_should_scan_source_keeps_ordinary_source():
    assert js.should_scan_source("src/app/config.js")


# ------------------------------ sanitize ---------------------------------- #
def test_sanitize_strips_webpack_host_scheme_dot_slash_and_traversal():
    assert js.sanitize_source_path("webpack://myapp/./src/a.js") == "src/a.js"
    # generic scheme strip removes only `scheme://`, not the host (spec)
    assert js.sanitize_source_path("https://cdn/x/y.js") == "cdn/x/y.js"
    assert js.sanitize_source_path("./rel/mod.js") == "rel/mod.js"
    assert js.sanitize_source_path("../../etc/passwd") == "etc/passwd"


# --------------------------- extraction walk ------------------------------ #
def test_iter_sourcemap_sources_index_maps_content_and_nulls():
    smap = {
        "sources": ["src/a.js", "src/b.js", "src/c.js"],
        "sourcesContent": ["A", None],
    }
    got = list(js.iter_sourcemap_sources(smap))
    assert got == [("src/a.js", "A"), ("src/b.js", None), ("src/c.js", None)]


# ---------------------- end-to-end scan_bundles --------------------------- #
def _fake_run_jsluice_factory():
    """A jsluice stand-in: `urls` mode reports the base as a discovered URL,
    `secrets` mode reports one secret whose value is the scanned text (so we
    can assert exactly which bodies were scanned)."""
    def run(mode, text, base):
        if mode == "urls":
            return json.dumps({"url": base + "/found"})
        return json.dumps({"kind": "generic", "secret": text})
    return run


def test_scan_bundles_scans_bundle_and_recovered_sources_annotated():
    origin = "https://h.example.com"
    burl = f"{origin}/static/app.js"
    fetched = {
        burl: "code//# sourceMappingURL=app.js.map",
        f"{origin}/static/app.js.map": json.dumps(
            {"sources": ["src/x.js"], "sourcesContent": ["SECRET_BODY"]}
        ),
    }
    emitted = []
    js.scan_bundles(
        [burl],
        fetch=lambda u: fetched.get(u),
        run_jsluice=_fake_run_jsluice_factory(),
        emit=emitted.append,
    )
    objs = [json.loads(l) for l in emitted]
    secrets = [o["secret"] for o in objs if o.get("kind")]
    # Both the minified bundle body AND the recovered source body were scanned.
    assert "code//# sourceMappingURL=app.js.map" in secrets
    assert "SECRET_BODY" in secrets
    # Secrets carry the bundle origin as base_url so the parser can anchor them.
    assert all(o["base_url"] == origin for o in objs if o.get("kind"))


def test_scan_bundles_fetches_source_when_content_null():
    origin = "https://h"
    burl = f"{origin}/a.js"
    fetched = {
        burl: "x//# sourceMappingURL=a.js.map",
        f"{origin}/a.js.map": json.dumps({"sources": ["src/y.js"], "sourcesContent": [None]}),
        f"{origin}/src/y.js": "FETCHED_SOURCE",
    }
    emitted = []
    js.scan_bundles([burl], fetch=lambda u: fetched.get(u),
                    run_jsluice=_fake_run_jsluice_factory(), emit=emitted.append)
    secrets = [json.loads(l)["secret"] for l in emitted if json.loads(l).get("kind")]
    assert "FETCHED_SOURCE" in secrets


def test_scan_bundles_dedups_identical_source_bodies_by_hash():
    origin = "https://h"
    b1, b2 = f"{origin}/1.js", f"{origin}/2.js"
    dup_map = json.dumps({"sources": ["s.js"], "sourcesContent": ["DUP"]})
    fetched = {
        b1: "a//# sourceMappingURL=1.js.map", f"{origin}/1.js.map": dup_map,
        b2: "b//# sourceMappingURL=2.js.map", f"{origin}/2.js.map": dup_map,
    }
    emitted = []
    js.scan_bundles([b1, b2], fetch=lambda u: fetched.get(u),
                    run_jsluice=_fake_run_jsluice_factory(), emit=emitted.append)
    secrets = [json.loads(l)["secret"] for l in emitted if json.loads(l).get("kind")]
    assert secrets.count("DUP") == 1  # identical source scanned once across bundles


def test_scan_bundles_dedups_processed_map_urls():
    origin = "https://h"
    b1, b2 = f"{origin}/x.js.map", f"{origin}/x.js.map"  # same direct map twice
    calls = []

    def fetch(u):
        calls.append(u)
        return json.dumps({"sources": [], "sourcesContent": []})

    js.scan_bundles([b1, b2], fetch=fetch, run_jsluice=_fake_run_jsluice_factory(), emit=lambda x: None)
    assert calls.count(f"{origin}/x.js.map") == 1


def test_scan_bundles_survives_unfetchable_and_bad_json():
    emitted = []
    js.scan_bundles(
        ["https://h/dead.js", "https://h/bad.js"],
        fetch=lambda u: None if "dead" in u else "notjson//# sourceMappingURL=bad.js.map",
        run_jsluice=lambda m, t, b: "not-json-line\n" if m == "urls" else "",
        emit=emitted.append,
    )
    # No crash; malformed jsluice lines are dropped, unreachable bundle skipped.
    assert emitted == []


# ------------- resource-relative resolution + runtime-prefix chaining ------ #
# The arm J comfyui/white-jotter diagnosis (2026-10-16): jsluice resolved every
# relative literal against the ORIGIN root (a Vite bundle's `./commands-x.js`
# import became the 404 `/commands-x.js`), and root-relative literals missed
# the runtime prefix their call site actually had (`/login` under axios
# `defaults.baseURL: "/api"`). These lock both halves.
def test_scan_bundles_resolves_against_scanned_resource_not_origin():
    origin = "https://h.example.com"
    burl = f"{origin}/assets/index-abc.js"
    map_url = f"{origin}/assets/index-abc.js.map"
    bases = []

    def run(mode, text, base):
        bases.append((mode, base))
        return ""

    fetched = {
        burl: "x//# sourceMappingURL=index-abc.js.map",
        map_url: json.dumps({"sources": ["src/x.js"], "sourcesContent": ["SRC"]}),
    }
    js.scan_bundles(
        [burl], fetch=lambda u: fetched.get(u), run_jsluice=run, emit=lambda line: None
    )
    url_bases = [base for mode, base in bases if mode == "urls"]
    assert url_bases == [burl, burl]  # bundle body AND recovered source
    assert all(base != origin for base in url_bases)


def test_extract_base_prefixes_from_config_and_joined_idioms():
    assert js.extract_base_prefixes(
        've.defaults.baseURL="/api",ve.defaults.withCredentials=!0'
    ) == ["/api"]
    assert js.extract_base_prefixes('return this.api_base+"/internal"+o') == ["/internal"]
    assert js.extract_base_prefixes("axios.create({baseURL:'/v2/'})") == ["/v2"]
    assert js.extract_base_prefixes('baseURL:"/api";baseURL:"/api"') == ["/api"]
    # An absolute-URL base is not a PATH prefix - it is captured separately as a
    # foreign base (`extract_foreign_bases`) and chained last (operator
    # 2026-10-16). `extract_base_prefixes` stays path-only so the path-prefix
    # cap always keeps the target-origin prefixes.
    assert js.extract_base_prefixes('baseURL:"https://api.comfy.org"') == []
    # Root and file-shaped values are not path prefixes.
    assert js.extract_base_prefixes('baseURL:"/";baseURL:"/app.js"') == []
    capped = "".join(f'baseURL:"/p{i}";' for i in range(6))
    assert js.extract_base_prefixes(capped) == ["/p0", "/p1", "/p2", "/p3"]


def test_extract_foreign_bases_from_absolute_baseurl_config():
    # Operator 2026-10-16: absolute-URL bases are captured (the old skip is
    # reversed) and chained as the LATEST failover. They are extracted in a
    # separate, capped list so a foreign base never evicts a target path prefix.
    assert js.extract_foreign_bases(
        'axios.create({baseURL:"https://api.comfy.org"})'
    ) == ["https://api.comfy.org"]
    assert js.extract_foreign_bases(
        "baseURL: 'http://svc.internal:8080/v1/'"
    ) == ["http://svc.internal:8080/v1"]
    assert js.extract_foreign_bases('baseURL:"https://api.comfy.org";baseURL:"https://api.comfy.org"') == [
        "https://api.comfy.org"
    ]
    # A path-relative base and a root are not foreign bases.
    assert js.extract_foreign_bases('baseURL:"/api";baseURL:"/"') == []
    capped = "".join(f'baseURL:"https://h{i}.example.com";' for i in range(6))
    assert js.extract_foreign_bases(capped) == [f"https://h{i}.example.com" for i in range(4)]


def test_chained_record_guards():
    origin = "https://g.example.com"
    assert js._chained_record(origin, "/api", {"url": origin + "/api/books"}) is None
    assert js._chained_record(origin, "/api", {"url": origin + "/"}) is None
    assert js._chained_record(origin, "/api", {"url": origin + "/api"}) is None
    # Static assets are never API routes under a prefix.
    assert js._chained_record(origin, "/api", {"url": origin + "/assets/index-abc.js"}) is None
    assert js._chained_record(origin, "/api", {"url": origin + "/a/vendor-x.css"}) is None
    # Directory-like / trailing-slash literals now MINT (operator ruling
    # 2026-10-16): the base path stays systematically identifiable, so a `/dist/`
    # under `/api` is kept as a candidate rather than rejected.
    made_dir = js._chained_record(origin, "/api", {"url": origin + "/dist/"})
    assert made_dir is not None and made_dir["url"] == origin + "/api/dist/"
    # The ROOT path stays rejected.
    assert js._chained_record(origin, "/api", {"url": origin + "/"}) is None
    assert js._chained_record(
        origin, "/api", {"url": "https://other.example.com/login"}
    ) is None
    rec = js._chained_record(origin, "/api", {"url": origin + "/search?k=1", "method": "GET"})
    assert rec == {
        "url": origin + "/api/search?k=1",
        "method": "GET",
        "chained_prefix": "/api",
        "chained_from": origin + "/search?k=1",
    }
    # `.json` is NOT filtered: it can be a real API path (only unambiguously
    # static asset extensions are skipped).
    kept = js._chained_record(origin, "/api", {"url": origin + "/data/x.json", "method": "GET"})
    assert kept is not None and kept["url"] == origin + "/api/data/x.json"
    # A literal that resolved under the resource's own directory is an
    # asset/module reference, NOT a request path - skip it even without a
    # static extension (the `./locales/en/main.json` family).
    bundle = {"source_url": origin + "/assets/index--PH2IHOc.js"}
    assert js._chained_record(
        origin, "/api", {"url": origin + "/assets/locales/en/main.json", **bundle}
    ) is None
    kept_root = js._chained_record(origin, "/api", {"url": origin + "/system_stats", **bundle})
    assert kept_root is not None and kept_root["url"] == origin + "/api/system_stats"
    # A root-served bundle has no directory discriminator: every literal stays
    # a candidate.
    assert js._chained_record(
        origin, "/api", {"url": origin + "/anything.json", "source_url": origin + "/app.js"}
    ) is not None


def test_scan_bundles_chains_literals_with_batch_runtime_prefix():
    origin = "https://j.example.com"
    app = f"{origin}/static/js/app.js"
    chunk = f"{origin}/static/js/8.chunk.js"
    app_text = 'var ve=t("mtWM");ve.defaults.baseURL="/api",ve.defaults.withCredentials=!0'
    chunk_text = 'this.$axios.post("/login",{u:"x"})'
    fetched = {app: app_text, chunk: chunk_text}

    def run(mode, text, base):
        if mode != "urls":
            return ""
        if text == chunk_text:
            return json.dumps(
                {"url": origin + "/login", "method": "POST", "bodyParams": ["u"]}
            )
        return ""

    emitted = []
    # Prefix bundle SECOND: the join is post-batch, so scan order must not
    # matter - the lazy chunk's literal still gets chained.
    js.scan_bundles(
        [chunk, app], fetch=lambda u: fetched.get(u), run_jsluice=run, emit=emitted.append
    )
    objs = [json.loads(line) for line in emitted]
    originals = [o for o in objs if o.get("url") == origin + "/login"]
    chained = [o for o in objs if o.get("chained_prefix")]
    assert len(originals) == 1  # the literal itself is kept (a real route, too)
    assert len(chained) == 1
    assert chained[0]["url"] == origin + "/api/login"
    assert chained[0]["method"] == "POST"
    assert chained[0]["bodyParams"] == ["u"]
    assert chained[0]["chained_from"] == origin + "/login"
    assert chained[0]["base_url"] == origin


def test_chained_record_carries_the_call_name_method_hint():
    """#365: an axios-shaped record names its verb only in `type` (jsluice's
    generic call matcher emits `method: ""`), so the re-minted twin must carry
    the call name for `jsluice_parser` to derive the write method from. A
    record without `type` keeps its exact shape (no phantom key)."""
    origin = "https://g.example.com"
    out = js._chained_record(
        origin, "/api", {"url": origin + "/login", "method": "", "type": "this.$axios.post"}
    )
    assert out is not None
    assert out["type"] == "this.$axios.post"
    plain = js._chained_record(origin, "/api", {"url": origin + "/login", "method": "GET"})
    assert plain is not None and "type" not in plain
    # the foreign failover twin carries the hint too
    foreign = js._foreign_chained_record(
        origin,
        "https://api.comfy.org",
        {"url": origin + "/login", "method": "", "type": "this.$axios.post"},
    )
    assert foreign is not None and foreign["type"] == "this.$axios.post"
    foreign_plain = js._foreign_chained_record(
        origin, "https://api.comfy.org", {"url": origin + "/login", "method": "GET"}
    )
    assert foreign_plain is not None and "type" not in foreign_plain


def test_scan_bundles_chained_axios_hint_mints_the_write_method():
    """#365 end to end at the production boundary: jsluice reports
    `this.$axios.post("/login")` as `{"method": "", "type": "this.$axios.post"}`;
    the chained twin (the `/api/login` node D-2 saw as a status-less GET) must
    carry the hint so the parser mints POST."""
    from polymerhus.recon.domain.parsers.jsluice_parser import parse

    origin = "https://m.example.com"
    app = f"{origin}/static/js/app.js"
    chunk = f"{origin}/static/js/8.chunk.js"
    app_text = 'var ve=t("mtWM");ve.defaults.baseURL="/api"'
    chunk_text = 'this.$axios.post("/login")'
    fetched = {app: app_text, chunk: chunk_text}

    def run(mode, text, base):
        if mode == "urls" and text == chunk_text:
            return json.dumps(
                {"url": origin + "/login", "method": "", "type": "this.$axios.post"}
            )
        return ""

    emitted = []
    js.scan_bundles(
        [app, chunk], fetch=lambda u: fetched.get(u), run_jsluice=run, emit=emitted.append
    )
    deltas = parse("\n".join(emitted))
    methods = {
        d.identity["path"]: d.identity["method"]
        for d in deltas
        if d.type == "Endpoint" and d.identity.get("baseurl") == origin
    }
    assert methods["/api/login"] == "POST"  # the chained twin carries the hint
    assert methods["/login"] == "POST"  # the literal record keeps its own


def test_scan_bundles_no_chained_without_prefix_in_batch():
    origin = "https://k.example.com"
    burl = f"{origin}/static/js/8.chunk.js"

    def run(mode, text, base):
        return json.dumps({"url": origin + "/login"}) if mode == "urls" else ""

    emitted = []
    fetched = {burl: 'this.$axios.post("/login",{u:"x"})'}
    js.scan_bundles([burl], fetch=lambda u: fetched.get(u), run_jsluice=run, emit=emitted.append)
    objs = [json.loads(line) for line in emitted]
    assert any(o.get("url") == origin + "/login" for o in objs)  # the literal WAS scanned
    assert not any(o.get("chained_prefix") for o in objs)


# ------------- foreign-origin baseURL chaining (latest failover) ------------ #
# Operator ruling 2026-10-16: `baseURL:"https://api.comfy.org"` + a `/login`
# literal is the foreign API call. The candidate is minted as the FULL foreign
# URL, `base_url` is the FOREIGN origin (so the graph gets the foreign BaseURL
# node and the URL streams for adjacent-service reasoning), and it is marked
# `origin_scope: "external"` so no active phase probes it. It is the LATEST
# failover: minted only when the literal produced no target-origin candidate,
# and emitted after every target candidate.
def test_foreign_chained_record_mints_full_foreign_url():
    origin = "https://h.example.com"
    rec = {"url": origin + "/login", "method": "POST",
           "source_url": origin + "/app.js", "bodyParams": ["u"]}
    out = js._foreign_chained_record(origin, "https://api.comfy.org", rec)
    assert out == {
        "url": "https://api.comfy.org/login",
        "method": "POST",
        "chained_prefix": "https://api.comfy.org",
        "chained_from": origin + "/login",
        "base_url": "https://api.comfy.org",
        "origin_scope": "external",
        "bodyParams": ["u"],
    }


def test_foreign_chained_record_keeps_shared_guards():
    origin = "https://h.example.com"
    # root, static asset, and a literal already foreign are not chained.
    assert js._foreign_chained_record(origin, "https://api.comfy.org", {"url": origin + "/"}) is None
    assert js._foreign_chained_record(
        origin, "https://api.comfy.org", {"url": origin + "/a/x.js"}
    ) is None
    assert js._foreign_chained_record(
        origin, "https://api.comfy.org", {"url": "https://other.example.com/x"}
    ) is None
    # a resource-dir literal (module reference) is not chained either
    assert js._foreign_chained_record(
        origin, "https://api.comfy.org",
        {"url": origin + "/assets/locales/en.json", "source_url": origin + "/assets/app.js"},
    ) is None


def test_scan_bundles_mints_foreign_candidate_when_no_target_prefix():
    origin = "https://c.example.com"
    app = f"{origin}/static/js/app.js"
    chunk = f"{origin}/static/js/8.chunk.js"
    app_text = 'axios.create({baseURL:"https://api.comfy.org"})'
    chunk_text = 'axios.post("/login",{u:"x"})'
    fetched = {app: app_text, chunk: chunk_text}

    def run(mode, text, base):
        if mode == "urls" and text == chunk_text:
            return json.dumps({"url": origin + "/login", "method": "POST", "bodyParams": ["u"]})
        return ""

    emitted = []
    js.scan_bundles([app, chunk], fetch=lambda u: fetched.get(u),
                    run_jsluice=run, emit=emitted.append)
    objs = [json.loads(line) for line in emitted]
    foreign = [o for o in objs if o.get("chained_prefix") == "https://api.comfy.org"]
    assert len(foreign) == 1
    f = foreign[0]
    assert f["url"] == "https://api.comfy.org/login"
    assert f["base_url"] == "https://api.comfy.org"  # the FOREIGN origin
    assert f["origin_scope"] == "external"
    assert f["chained_from"] == origin + "/login"
    assert f["method"] == "POST"
    assert f["bodyParams"] == ["u"]
    # the target literal itself is still kept (candidate set is additive)
    assert any(o.get("url") == origin + "/login" for o in objs)


def test_scan_bundles_prefers_target_prefix_over_foreign_base():
    origin = "https://d.example.com"
    app = f"{origin}/static/js/app.js"
    chunk = f"{origin}/static/js/8.chunk.js"
    app_text = 'x.defaults.baseURL="/api";axios.create({baseURL:"https://api.comfy.org"})'
    chunk_text = 'axios.post("/login")'
    fetched = {app: app_text, chunk: chunk_text}

    def run(mode, text, base):
        if mode == "urls" and text == chunk_text:
            return json.dumps({"url": origin + "/login", "method": "POST"})
        return ""

    emitted = []
    js.scan_bundles([app, chunk], fetch=lambda u: fetched.get(u),
                    run_jsluice=run, emit=emitted.append)
    objs = [json.loads(line) for line in emitted]
    targets = [o for o in objs if o.get("chained_prefix") == "/api"]
    foreigns = [o for o in objs if o.get("origin_scope") == "external"]
    assert len(targets) == 1 and targets[0]["url"] == origin + "/api/login"
    assert foreigns == []  # a target-origin candidate existed: no foreign chaining


def test_scan_bundles_emits_foreign_candidates_last():
    origin = "https://e.example.com"
    app = f"{origin}/app.js"
    app_text = 'x.defaults.baseURL="/api";axios.create({baseURL:"https://api.comfy.org"})'
    c1 = f"{origin}/c1.js"
    c2 = f"{origin}/c2.js"
    fetched = {app: app_text, c1: "A", c2: "B"}

    def run(mode, text, base):
        if mode != "urls":
            return ""
        if text == "A":  # target candidate /api/login
            return json.dumps({"url": origin + "/login"})
        if text == "B":  # already under /api -> no target candidate -> foreign
            return json.dumps({"url": origin + "/api/thing"})
        return ""

    emitted = []
    js.scan_bundles([app, c1, c2], fetch=lambda u: fetched.get(u),
                    run_jsluice=run, emit=emitted.append)
    objs = [json.loads(line) for line in emitted]
    target_i = next(i for i, o in enumerate(objs) if o.get("chained_prefix") == "/api")
    foreign_i = next(
        i for i, o in enumerate(objs) if o.get("chained_prefix") == "https://api.comfy.org"
    )
    assert foreign_i > target_i  # foreign candidates are emitted last
    assert objs[foreign_i]["url"] == "https://api.comfy.org/api/thing"


def test_scan_bundles_marks_foreign_literal_records_external():
    origin = "https://f.example.com"
    b = f"{origin}/app.js"
    foreign_url = "https://api.other.com/v1/x"

    def run(mode, text, base):
        return json.dumps({"url": foreign_url}) if mode == "urls" else ""

    emitted = []
    js.scan_bundles([b], fetch=lambda u: "body", run_jsluice=run, emit=emitted.append)
    objs = [json.loads(line) for line in emitted]
    rec = next(o for o in objs if o.get("url") == foreign_url)
    assert rec["origin_scope"] == "external"


# ------------- real collaborators (the untested pod-side boundary) -------- #
# scan_bundles is injected with fakes above, so _real_fetch / _real_run_jsluice
# had zero coverage - both shipped broken from the D17 rewrite. These lock the
# contract with their external dependency (subprocess / urllib) without needing
# the network or the jsluice binary.
def test_real_run_jsluice_reads_raw_js_from_stdin(monkeypatch):
    """jsluice treats every stdin token as a FILENAME unless --raw-input/-j is
    given, so piping JS source without it makes jsluice try to `open` the source
    text as files and emit nothing (the live "jsluice consumed N bundles,
    produced 0 assets" symptom). _real_run_jsluice pipes the bundle text on
    stdin, so it MUST pass -j/--raw-input - exactly what the pre-D17 template
    (`jsluice urls -j -R <base>`) did before the rewrite dropped it."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        captured["input"] = kwargs.get("input")

        class _Proc:
            stdout = ""

        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    js._real_run_jsluice("urls", "var x = 1;", "https://h.example.com")

    assert captured["input"] == "var x = 1;"  # the JS body goes in on stdin
    assert "-j" in captured["args"] or "--raw-input" in captured["args"]


def test_real_fetch_tolerates_untrusted_tls(monkeypatch):
    """Recon egress fetches bundles from arbitrary/misconfigured targets, so a
    self-signed or otherwise untrusted HTTPS cert (a local vuln-by-design target,
    a mis-issued prod cert) must NOT abort the fetch - just as the Go crawlers
    (katana/httpx) ignore TLS errors. _real_fetch must therefore pass an SSL
    context that does not verify certs; the default verifying context silently
    turns every https bundle into a None fetch."""
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"bundle-bytes"

    def fake_urlopen(req, **kwargs):
        captured["context"] = kwargs.get("context")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = js._real_fetch("https://self-signed.example.com/main.js")

    assert out == "bundle-bytes"
    ctx = captured["context"]
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False
