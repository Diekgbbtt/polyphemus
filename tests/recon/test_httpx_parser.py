# tests/recon/test_httpx_parser.py
from pathlib import Path
from agent.recon.parsers import get_parser
from agent.recon.parsers.httpx_parser import parse

FIX = Path(__file__).parent / "fixtures" / "httpx_probe.jsonl"

def test_registry_exposes_httpx():
    assert get_parser("httpx") is parse

def test_parse_emits_baseurl_endpoint_tech_cert():
    deltas = parse(FIX.read_text())
    types = [d.type for d in deltas]
    assert types.count("BaseURL") == 2
    assert "Endpoint" in types
    tech = [d for d in deltas if d.type == "Technology"]
    assert {("nginx"), ("React"), ("cloudflare")} <= {d.identity["name"] for d in tech}
    cert = [d for d in deltas if d.type == "Certificate"]
    assert cert and cert[0].identity["subject_cn"] == "app.example.com"

def test_endpoint_has_incoming_baseurl_edge():
    deltas = parse(FIX.read_text())
    ep = next(d for d in deltas if d.type == "Endpoint")
    assert any(e.rel == "HAS_ENDPOINT" and e.node_type == "BaseURL" for e in ep.edges)

def test_malformed_line_skipped():
    deltas = parse('{"url":"https://a","status_code":200}\nNOT JSON\n')
    assert any(d.type == "BaseURL" for d in deltas)
