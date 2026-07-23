# tests/recon/test_graphql_parser.py
from pathlib import Path

from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.graphql_parser import parse, parse_findings

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


def test_parse_with_target_url_uses_it_over_regex_derivation():
    deltas = parse(FIX.read_text(), target_url="https://different.example.com/graphql")

    baseurls = [d for d in deltas if d.type == "BaseURL"]
    assert baseurls
    assert all(b.identity["url"] == "https://different.example.com" for b in baseurls)

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 1
    endpoint = endpoints[0]
    assert endpoint.identity["path"] == "/graphql"
    assert endpoint.identity["baseurl"] == "https://different.example.com"


def test_parse_with_target_url_derives_endpoint_when_no_curl_verify():
    # No curl_verify at all in the checks - regex fallback would return [],
    # but target_url makes derivation deterministic.
    stdout = """[
        {"title": "Introspection", "severity": "MEDIUM", "result": true}
    ]"""
    deltas = parse(stdout, target_url="https://api.example.com/graphql")

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 1
    assert endpoints[0].identity["baseurl"] == "https://api.example.com"
    assert endpoints[0].identity["path"] == "/graphql"


def test_parse_findings_with_target_url_attaches_baseurl_anchor():
    findings = parse_findings(
        FIX.read_text(), target_url="https://api.example.com/graphql"
    )
    assert len(findings) == 1
    anchor = findings[0]["anchor"]
    assert anchor == {
        "type": "BaseURL",
        "identity": {"url": "https://api.example.com"},
    }


def test_parse_findings_anchor_survives_curate_path():
    """Regression test for the silent-drop bug: an Endpoint anchor is not in
    `curator.ANCHOR_ALLOWLIST`, so `build_observation_cypher` raised
    `ValueError` and `curate` skipped+logged every graphql-cop finding. The
    finding anchor must be BaseURL (a broad, allow-listed anchor) so the
    Observation reaches Neo4j instead of being silently dropped."""
    from polymerhus.recon.domain.curator import build_observation_cypher
    from polymerhus.recon.domain.findings import finding_to_observation

    findings = parse_findings(
        FIX.read_text(), target_url="https://api.example.com/graphql"
    )
    assert len(findings) == 1

    observation = finding_to_observation(
        findings[0], source_job="graphql-cop-job", source_tool="graphql-cop"
    )
    assert observation is not None

    query, params = build_observation_cypher(observation)
    assert "MERGE" in query
    assert params["anchor_url"] == "https://api.example.com"


def test_parse_findings_without_target_url_has_no_anchor_key_when_undeterminable():
    stdout = """[
        {"title": "Some Check", "result": true}
    ]"""
    findings = parse_findings(stdout)
    assert len(findings) == 1
    assert "anchor" not in findings[0]
