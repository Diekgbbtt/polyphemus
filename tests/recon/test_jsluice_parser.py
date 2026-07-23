# tests/recon/test_jsluice_parser.py
import hashlib
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

    # url line -> BaseURL + Endpoint; secret line -> BaseURL + Secret.
    assert len(deltas) == 4
    assert sum(1 for d in deltas if d.type == "Endpoint") == 1
    assert sum(1 for d in deltas if d.type == "Secret") == 1
    assert sum(1 for d in deltas if d.type == "BaseURL") == 2


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
