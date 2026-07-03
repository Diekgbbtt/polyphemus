# tests/recon/test_jsluice_parser.py
import hashlib
from pathlib import Path

from agent.recon.parsers import get_parser
from agent.recon.parsers.jsluice_parser import parse

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
