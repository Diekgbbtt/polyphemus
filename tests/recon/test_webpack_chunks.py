import json
import ssl
import urllib.request

from polymerhus.recon.scripts import webpack_chunks as wc


# ---------------------- chunk-map extraction ------------------------------- #
def test_extract_chunk_map_from_webpack_runtime_object():
    text = (
        "window.webpackJsonp=window.webpackJsonp||[];"
        '({"0":"e97b6a900e6dba28655c","1":"96068045d4dfa0835db0"})'
    )
    assert wc.extract_webpack_chunk_map(text) == {
        "0": "e97b6a900e6dba28655c",
        "1": "96068045d4dfa0835db0",
    }


def test_extract_chunk_map_handles_unquoted_id_keys():
    text = '{0:"e97b6a900e6dba28655c",1:"96068045d4dfa0835db0",2:"cccccccccccc"}'
    assert wc.extract_webpack_chunk_map(text) == {
        "0": "e97b6a900e6dba28655c",
        "1": "96068045d4dfa0835db0",
        "2": "cccccccccccc",
    }


def test_extract_chunk_map_handles_whitespace_and_newlines():
    text = '{\n  "0": "e97b6a900e6dba28655c",\n  "1": "96068045d4dfa0835db0"\n}'
    assert wc.extract_webpack_chunk_map(text) == {
        "0": "e97b6a900e6dba28655c",
        "1": "96068045d4dfa0835db0",
    }


def test_extract_chunk_map_ignores_non_hash_object():
    assert wc.extract_webpack_chunk_map('var cfg={"name":"app","debug":true}') == {}


def test_extract_chunk_map_ignores_short_hex_values():
    # A real content hash is >=8 hex chars; a map of short tokens is not one.
    assert wc.extract_webpack_chunk_map('{0:"abc",1:"def"}') == {}


def test_extract_chunk_map_requires_at_least_two_entries():
    assert wc.extract_webpack_chunk_map('{0:"e97b6a900e6dba28655c"}') == {}


def test_extract_chunk_map_takes_the_first_map_when_several_present():
    text = '{0:"e97b6a900e6dba28655c",1:"96068045d4dfa0835db0"} ... {9:"ffffffffffff"}'
    assert wc.extract_webpack_chunk_map(text) == {
        "0": "e97b6a900e6dba28655c",
        "1": "96068045d4dfa0835db0",
    }


# ------------------------ chunk URL resolution ----------------------------- #
def test_resolve_chunk_url_uses_the_bundle_directory():
    assert wc.resolve_chunk_url(
        "http://h/static/js/manifest.847c1a77e1df892a8f1a.js",
        "8",
        "8adec4d4ce480535d13c",
    ) == "http://h/static/js/8.8adec4d4ce480535d13c.js"


def test_resolve_chunk_url_at_origin_root():
    assert wc.resolve_chunk_url("http://h/manifest.a1b2c3d4.js", "0", "deadbeefcafe") == (
        "http://h/0.deadbeefcafe.js"
    )


def test_resolve_chunk_url_ignores_a_query_string():
    assert wc.resolve_chunk_url("http://h/js/manifest.abc.js?v=1", "3", "0123456789abcdef") == (
        "http://h/js/3.0123456789abcdef.js"
    )


# --------------------------- scan_bundles ---------------------------------- #
def test_scan_bundles_emits_resolved_chunk_urls_from_a_manifest():
    manifest = "http://h/static/js/manifest.847c1a77e1df892a8f1a.js"
    fetched = {
        manifest: '{0:"e97b6a900e6dba28655c",1:"96068045d4dfa0835db0"}'
    }
    emitted = []
    wc.scan_bundles([manifest], fetch=lambda u: fetched.get(u), emit=emitted.append)

    urls = [json.loads(line)["webpack_chunk_url"] for line in emitted]
    assert urls == [
        "http://h/static/js/0.e97b6a900e6dba28655c.js",
        "http://h/static/js/1.96068045d4dfa0835db0.js",
    ]


def test_scan_bundles_dedups_chunk_urls_across_bundles():
    m1 = "http://h/js/manifest.1.js"
    m2 = "http://h/js/manifest.2.js"
    map_text = '{0:"e97b6a900e6dba28655c",1:"96068045d4dfa0835db0"}'
    fetched = {m1: map_text, m2: map_text}
    emitted = []
    wc.scan_bundles([m1, m2], fetch=lambda u: fetched.get(u), emit=emitted.append)
    assert len(emitted) == 2


def test_scan_bundles_emits_nothing_without_a_map():
    emitted = []
    wc.scan_bundles(
        ["http://h/app.js"],
        fetch=lambda u: "var x = 1; // no chunk map here",
        emit=emitted.append,
    )
    assert emitted == []


def test_scan_bundles_skips_unfetchable_bundles():
    emitted = []
    wc.scan_bundles(["http://h/dead.js"], fetch=lambda u: None, emit=emitted.append)
    assert emitted == []


# ------------- real collaborator (the pod-side fetch boundary) ------------- #
def test_real_fetch_tolerates_untrusted_tls(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"manifest-bytes"

    def fake_urlopen(req, **kwargs):
        captured["context"] = kwargs.get("context")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = wc._real_fetch("https://self-signed.example.com/manifest.js")

    assert out == "manifest-bytes"
    ctx = captured["context"]
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False
