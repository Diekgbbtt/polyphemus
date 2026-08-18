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
