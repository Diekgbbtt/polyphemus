# tests/recon/test_takeover_parser.py
from pathlib import Path

from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.takeover_parser import parse, parse_findings

FIX = Path(__file__).parent / "fixtures" / "subdomain_takeover.json"


def test_registry_exposes_subdomain_takeover():
    assert get_parser("subdomain_takeover") is parse


def test_parse_findings_returns_one_finding_for_vulnerable_entry_only():
    findings = parse_findings(FIX.read_text())
    assert len(findings) == 1
    finding = findings[0]
    assert finding["title"] == "potential_subdomain_takeover"
    assert finding["anchor"] == {"type": "Subdomain", "identity": {"name": "old.example.com"}}
    assert "dangling-bucket.s3.amazonaws.com" in finding["evidence"]
    assert finding["severity"]


def test_parse_findings_safe_entry_yields_no_finding():
    stdout = """[
        {"subdomain": "safe.example.com", "service": "", "vulnerable": false, "cname": ""}
    ]"""
    assert parse_findings(stdout) == []


def test_parse_emits_external_domain_when_dangling_cname_present():
    deltas = parse(FIX.read_text())

    external_domains = [d for d in deltas if d.type == "ExternalDomain"]
    assert len(external_domains) == 1
    ext = external_domains[0]
    assert ext.identity == {"domain": "dangling-bucket.s3.amazonaws.com"}


def test_parse_external_domain_has_incoming_edge_from_parent_domain():
    deltas = parse(FIX.read_text())
    ext = next(d for d in deltas if d.type == "ExternalDomain")
    assert any(
        e.rel == "HAS_EXTERNAL_DOMAIN" and e.dir == "in" and e.node_type == "Domain"
        and e.node_identity == {"name": "example.com"}
        for e in ext.edges
    )


def test_parse_returns_empty_when_no_dangling_cname():
    stdout = """[
        {"subdomain": "old.example.com", "service": "aws/s3", "vulnerable": true, "cname": ""}
    ]"""
    assert parse(stdout) == []


def test_parse_returns_empty_when_no_vulnerable_entries():
    stdout = """[
        {"subdomain": "safe.example.com", "service": "", "vulnerable": false, "cname": ""}
    ]"""
    assert parse(stdout) == []


def test_parse_tolerates_malformed_json():
    assert parse("not json") == []
    assert parse("") == []
    assert parse("{}") == []
    assert parse("null") == []
    assert parse('[1, 2, "str", {"subdomain": "x"}]') == []


def test_parse_findings_tolerates_malformed_json():
    assert parse_findings("not json") == []
    assert parse_findings("") == []
    assert parse_findings("{}") == []
    assert parse_findings('[1, 2, "str"]') == []


def test_parse_tolerates_non_string_fields():
    stdout = """[
        {"subdomain": 12345, "service": true, "vulnerable": true, "cname": ["not", "a", "string"]}
    ]"""
    assert parse(stdout) == []
    assert parse_findings(stdout) == []


def test_parse_supports_jsonl_input_shape():
    stdout = (
        '{"subdomain": "old.example.com", "service": "aws/s3", "vulnerable": true, '
        '"cname": "dangling-bucket.s3.amazonaws.com"}\n'
        '{"subdomain": "www.example.com", "service": "", "vulnerable": false, "cname": ""}\n'
    )
    findings = parse_findings(stdout)
    assert len(findings) == 1
    assert findings[0]["anchor"]["identity"]["name"] == "old.example.com"

    deltas = parse(stdout)
    external_domains = [d for d in deltas if d.type == "ExternalDomain"]
    assert len(external_domains) == 1
