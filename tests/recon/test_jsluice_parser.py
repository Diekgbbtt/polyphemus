# tests/recon/test_jsluice_parser.py
import hashlib
import json
from pathlib import Path

from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.jsluice_parser import parse

FIX = Path(__file__).parent / "fixtures" / "jsluice.jsonl"

RAW_SECRET = "AKIAABCDEFGHIJKLMNOP"


def test_registry_exposes_jsluice():
    assert get_parser("jsluice") is parse


def test_parse_emits_endpoint_from_url_entry():
    deltas = parse(FIX.read_text())

    baseurls = {d.identity["url"] for d in deltas if d.type == "BaseURL"}
    assert "https://target.example.com" in baseurls

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 1
    endpoint = endpoints[0]
    assert endpoint.identity == {
        "path": "/api/v2/data",
        "method": "GET",
        "baseurl": "https://target.example.com",
    }
    assert endpoint.props["source"] == "jsluice"
    assert endpoint.props["url"] == "https://target.example.com/api/v2/data?id=1"


def test_parse_carries_runtime_prefix_chaining_provenance():
    """A chained record (jsluice_scan re-mints a literal under a batch-discovered
    request-path prefix) keeps both halves as Endpoint props, so the graph and
    the streamed analysis blocks show WHY the endpoint exists."""
    line = json.dumps(
        {
            "url": "https://t.example.com/api/login",
            "method": "POST",
            "base_url": "https://t.example.com",
            "source_url": "https://t.example.com/static/js/app.js",
            "chained_prefix": "/api",
            "chained_from": "https://t.example.com/login",
        }
    )
    endpoints = [d for d in parse(line) if d.type == "Endpoint"]
    assert len(endpoints) == 1
    assert endpoints[0].identity == {
        "path": "/api/login",
        "method": "POST",
        "baseurl": "https://t.example.com",
    }
    assert endpoints[0].props["chained_prefix"] == "/api"
    assert endpoints[0].props["chained_from"] == "https://t.example.com/login"


def test_parse_plain_entry_has_no_chaining_props():
    deltas = parse(FIX.read_text())
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert "chained_prefix" not in endpoint.props
    assert "chained_from" not in endpoint.props
    assert "origin_scope" not in endpoint.props
    baseurl = next(d for d in deltas if d.type == "BaseURL")
    assert "origin_scope" not in baseurl.props


def test_parse_foreign_chained_record_flows_provenance_and_marker():
    """A FOREIGN chained record (jsluice_scan re-mints a literal under an
    absolute-URL `baseURL`) flows its provenance to the Endpoint props AND the
    `origin_scope: "external"` no-probe marker to BOTH the Endpoint and the
    BaseURL delta (operator 2026-10-16)."""
    line = json.dumps(
        {
            "url": "https://api.comfy.org/login",
            "method": "POST",
            "base_url": "https://api.comfy.org",
            "source_url": "https://h.example.com/static/js/app.js",
            "chained_prefix": "https://api.comfy.org",
            "chained_from": "https://h.example.com/login",
            "origin_scope": "external",
        }
    )
    deltas = parse(line)
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert endpoint.identity == {
        "path": "/login",
        "method": "POST",
        "baseurl": "https://api.comfy.org",
    }
    assert endpoint.props["chained_prefix"] == "https://api.comfy.org"
    assert endpoint.props["chained_from"] == "https://h.example.com/login"
    assert endpoint.props["origin_scope"] == "external"
    # the foreign origin's BaseURL node is marked too (ffuf consumes BaseURLs)
    baseurl = next(d for d in deltas if d.type == "BaseURL")
    assert baseurl.identity == {"url": "https://api.comfy.org"}
    assert baseurl.props["origin_scope"] == "external"


def test_parse_foreign_literal_without_chaining_still_marked_external():
    """An absolute foreign literal in a bundle (record origin differs from the
    scanned origin) is marked `external` even though it carries no chaining
    provenance."""
    line = json.dumps(
        {"url": "https://other.example.com/x", "origin_scope": "external"}
    )
    deltas = parse(line)
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert endpoint.props["origin_scope"] == "external"
    assert "chained_prefix" not in endpoint.props
    baseurl = next(d for d in deltas if d.type == "BaseURL")
    assert baseurl.props["origin_scope"] == "external"


def test_endpoint_has_incoming_baseurl_edge():
    deltas = parse(FIX.read_text())
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert any(
        e.rel == "HAS_ENDPOINT" and e.dir == "in" and e.node_type == "BaseURL"
        and e.node_identity == {"url": "https://target.example.com"}
        for e in endpoint.edges
    )


def test_parse_emits_redacted_secret_from_secret_entry():
    deltas = parse(FIX.read_text())

    secrets = [d for d in deltas if d.type == "Secret"]
    assert len(secrets) == 1
    secret = secrets[0]

    expected_hash = hashlib.sha1(RAW_SECRET.encode()).hexdigest()
    assert secret.identity == {"value_hash": expected_hash}
    assert secret.identity["value_hash"] != RAW_SECRET

    assert secret.props["kind"] == "aws-access-key"
    assert secret.props["source"] == "jsluice"
    assert secret.props["redacted"] is True


def test_secret_has_incoming_baseurl_edge_when_base_url_present():
    deltas = parse(FIX.read_text())
    secret = next(d for d in deltas if d.type == "Secret")
    assert any(
        e.rel == "HAS_SECRET" and e.dir == "in" and e.node_type == "BaseURL"
        and e.node_identity == {"url": "https://target.example.com"}
        for e in secret.edges
    )


def test_raw_secret_value_never_appears_in_any_delta():
    deltas = parse(FIX.read_text())
    for delta in deltas:
        assert RAW_SECRET not in str(delta.identity)
        assert RAW_SECRET not in str(delta.props)
        for edge in delta.edges:
            assert RAW_SECRET not in str(edge.node_identity)


def test_malformed_line_skipped():
    # The fixture mixes one url line, one secret line, and one garbage line.
    # The garbage line must be dropped without costing us the valid deltas.
    deltas = parse(FIX.read_text())

    # url line (`...?id=1`) -> BaseURL + Endpoint + Parameter(id); secret line ->
    # BaseURL + Secret. Param discovery now surfaces the query param too.
    assert len(deltas) == 5
    assert sum(1 for d in deltas if d.type == "Endpoint") == 1
    assert sum(1 for d in deltas if d.type == "Secret") == 1
    assert sum(1 for d in deltas if d.type == "BaseURL") == 2
    assert sum(1 for d in deltas if d.type == "Parameter") == 1


def test_non_string_values_skipped_not_raised():
    # A dict line with a non-string secret/url must be skipped, not crash
    # parse() (which would lose every prior valid delta).
    assert parse('{"kind":"x","secret":12345}') == []
    assert parse('{"url":12345}') == []


def test_secret_derives_baseurl_from_source_url_when_base_url_missing():
    line = (
        '{"kind": "generic-api-key", "secret": "sk_live_abcdef123456", '
        '"source_url": "https://cdn.example.com/assets/app.js"}'
    )
    deltas = parse(line)
    secret = next(d for d in deltas if d.type == "Secret")
    assert any(
        e.rel == "HAS_SECRET" and e.node_identity == {"url": "https://cdn.example.com"}
        for e in secret.edges
    )


def test_secret_emitted_without_edge_when_no_base_url_context():
    line = '{"kind": "generic-api-key", "secret": "sk_live_zzzzzz999999"}'
    deltas = parse(line)
    secrets = [d for d in deltas if d.type == "Secret"]
    assert len(secrets) == 1
    assert secrets[0].edges == []


def test_missing_url_and_secret_keys_skipped():
    deltas = parse('{"foo": "bar"}\n{"type": "fetch"}\n')
    assert deltas == []


# --- REAL jsluice output shape (regression: the parser dropped every real secret) ---
# jsluice `secrets` emits the value under a nested `data` OBJECT, e.g.
#   {"kind":"AWSAccessKey","data":{"key":"AKIA...","secret":"wJal..."},"severity":"high",...}
# The parser previously read a top-level `entry["secret"]` string, which real
# jsluice NEVER emits, so it silently dropped 100% of real findings. The fixtures
# used a fabricated {"kind":..,"secret":..} shape that matched the code but not the
# tool (mock-shaped-to-code). These cases pin the REAL shape.
import json as _json

_REAL_AWS = _json.dumps({
    "kind": "AWSAccessKey",
    "data": {"key": "AKIAIOSFODNN7EXAMPLE", "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"},
    "filename": "/tmp/x", "severity": "high",
    "base_url": "https://target.example.com",
})
_REAL_GCP = _json.dumps({
    "kind": "gcpKey",
    "data": {"key": "AIzaSyA-example1234567890abcdefghijklmno"},
    "severity": "low", "base_url": "https://target.example.com",
})


def test_parse_emits_secret_from_real_jsluice_data_object():
    deltas = parse(_REAL_AWS)
    secrets = [d for d in deltas if d.type == "Secret"]
    assert len(secrets) == 1, "the real jsluice `data`-object shape must yield a Secret"
    s = secrets[0]
    assert s.props["kind"] == "AWSAccessKey"
    assert s.props["source"] == "jsluice"
    assert s.props["redacted"] is True
    assert "value_hash" in s.identity


def test_real_secret_value_never_appears_in_any_delta():
    """The raw key/secret under `data` must be hashed, never stored verbatim."""
    for raw in ("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"):
        for d in parse(_REAL_AWS):
            blob = _json.dumps({"identity": d.identity, "props": d.props})
            assert raw not in blob, f"raw secret leaked in {d.type} delta"


def test_secret_with_only_a_key_subfield_still_emits():
    """A finding whose `data` has only `key` (no `secret`) must still be captured."""
    secrets = [d for d in parse(_REAL_GCP) if d.type == "Secret"]
    assert len(secrets) == 1 and secrets[0].props["kind"] == "gcpKey"


def test_two_distinct_real_secrets_get_distinct_hashes():
    deltas = parse(_REAL_AWS + "\n" + _REAL_GCP)
    hashes = {d.identity["value_hash"] for d in deltas if d.type == "Secret"}
    assert len(hashes) == 2, "distinct secrets must not collide on value_hash"


# --- #365: the write method jsluice names only in `type` (the CALL NAME) ------- #
# jsluice sets `method` itself for its fetch / XMLHttpRequest.open /
# $.get|$.post|$.ajax matchers only. Every other client-style call is matched by
# the generic "other function calls with a URL-like argument" matcher, which
# emits `{"method": "", "type": "<call name>"}` - e.g. white-jotter's
# `this.$axios.post("/login")` -> `"type": "this.$axios.post"`. The parser is the
# one place that turns a record into an Endpoint, so the call-name verb is
# recovered HERE; the reprofile probe arbitrates the hint against the live route.

def _endpoint_method(line: str) -> str:
    out = parse(line)
    return next(d for d in out if d.type == "Endpoint").identity["method"]


def test_write_method_is_derived_from_the_axios_style_call_name():
    assert _endpoint_method(
        '{"url":"https://t/api/register","method":"","type":"this.$axios.post"}\n'
    ) == "POST"
    assert _endpoint_method(
        '{"url":"https://t/api/orders/1","method":"","type":"axios.put"}\n'
    ) == "PUT"
    assert _endpoint_method(
        '{"url":"https://t/api/orders/1","method":"","type":"api.patch"}\n'
    ) == "PATCH"
    assert _endpoint_method(
        '{"url":"https://t/api/orders/1","method":"","type":"$http.delete"}\n'
    ) == "DELETE"


def test_read_style_call_names_keep_the_get_default():
    # `router.push("/admin")` and a bare string literal carry no write verb: the
    # pre-#365 GET default stands (an unhinted route must stay GET-shaped).
    assert _endpoint_method(
        '{"url":"https://t/admin","method":"","type":"router.push"}\n'
    ) == "GET"
    assert _endpoint_method(
        '{"url":"https://t/admin","method":"","type":"stringLiteral"}\n'
    ) == "GET"
    assert _endpoint_method('{"url":"https://t/admin"}\n') == "GET"


def test_an_explicit_method_always_wins_over_the_call_name():
    # jsluice's own matchers name the method when they can (fetch init, $.post,
    # XMLHttpRequest.open); that statement is never overridden by the call name.
    assert _endpoint_method(
        '{"url":"https://t/api/search","method":"POST","type":"$.get"}\n'
    ) == "POST"


def test_derived_method_is_normalized_to_upper_case():
    assert _endpoint_method(
        '{"url":"https://t/api/register","method":"","type":"this.$axios.Post"}\n'
    ) == "POST"


def test_jsluice_urls_emit_query_and_body_parameters():
    # Param discovery: jsluice `urls` mode already emits queryParams/bodyParams
    # arrays per discovered URL; the parser now turns them into Parameter deltas
    # (query params at position=query, body params at position=body) anchored to
    # the Endpoint via HAS_PARAMETER.
    from polymerhus.recon.domain.parsers.jsluice_parser import parse
    line = (
        '{"url":"https://h/api/login?next=x","method":"POST",'
        '"queryParams":["next"],"bodyParams":["username","password"]}\n'
    )
    out = parse(line)
    params = {(d.identity["name"], d.identity["position"]) for d in out if d.type == "Parameter"}
    assert ("next", "query") in params
    assert ("username", "body") in params
    assert ("password", "body") in params
    # each Parameter hangs off the discovered Endpoint
    for d in out:
        if d.type == "Parameter":
            assert any(e.rel == "HAS_PARAMETER" and e.node_type == "Endpoint" for e in d.edges)
