# tests/recon/test_graphql_parser.py
from pathlib import Path

from agent.recon.parsers import get_parser
from agent.recon.parsers.graphql_parser import parse, parse_findings

FIX = Path(__file__).parent / "fixtures" / "graphql_cop.json"


def test_registry_exposes_graphql_cop():
    assert get_parser("graphql-cop") is parse


def test_parse_emits_graphql_endpoint_when_url_derivable():
    deltas = parse(FIX.read_text())

    baseurls = [d for d in deltas if d.type == "BaseURL"]
    assert baseurls
    assert all(b.identity["url"] == "https://api.example.com" for b in baseurls)

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 1
    endpoint = endpoints[0]
    assert endpoint.identity["path"] == "/graphql"
    assert endpoint.identity["method"] == "POST"
    assert endpoint.identity["baseurl"] == "https://api.example.com"
    assert endpoint.props["endpoint_type"] == "graphql"
    assert endpoint.props["source"] == "graphql-cop"


def test_parse_endpoint_has_incoming_baseurl_edge():
    deltas = parse(FIX.read_text())
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert any(
        e.rel == "HAS_ENDPOINT" and e.dir == "in" and e.node_type == "BaseURL"
        and e.node_identity == {"url": "https://api.example.com"}
        for e in endpoint.edges
    )


def test_parse_returns_empty_when_url_not_derivable():
    stdout = """[
        {"title": "Introspection", "severity": "MEDIUM", "result": true}
    ]"""
    assert parse(stdout) == []


def test_parse_findings_returns_one_dict_for_failing_check_only():
    findings = parse_findings(FIX.read_text())
    assert len(findings) == 1
    finding = findings[0]
    assert finding["title"] == "Introspection"
    assert finding["severity"] == "MEDIUM"
    assert "curl" in finding["evidence"]


def test_parse_findings_defaults_severity_to_info_when_missing():
    stdout = """[
        {"title": "Some Check", "result": true, "curl_verify": "curl https://x/graphql"}
    ]"""
    findings = parse_findings(stdout)
    assert len(findings) == 1
    assert findings[0]["severity"] == "info"


def test_parse_tolerates_malformed_json():
    assert parse("not json") == []
    assert parse("") == []
    assert parse("{}") == []
    assert parse("null") == []
    assert parse('[1, 2, "str", {"title": "x"}]') == []


def test_parse_findings_tolerates_malformed_json():
    assert parse_findings("not json") == []
    assert parse_findings("") == []
    assert parse_findings("{}") == []
    assert parse_findings('[1, 2, "str"]') == []
