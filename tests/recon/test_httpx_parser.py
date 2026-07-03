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


def test_path_bearing_url_normalizes_baseurl_to_scheme_netloc():
    # F2 regression guard: if httpx ever probes/emits a path- or port-bearing
    # `url` (e.g. from a redirect-following config), BaseURL identity and
    # Endpoint.baseurl must still normalize to scheme://netloc so the node
    # MERGEs with the same host discovered by every other tool - not split
    # into a distinct graph node keyed on the raw path-bearing string.
    deltas = parse('{"url":"https://host/some/path","status_code":200}\n')

    baseurl = next(d for d in deltas if d.type == "BaseURL")
    assert baseurl.identity == {"url": "https://host"}

    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert endpoint.identity["baseurl"] == "https://host"
    assert endpoint.identity["path"] == "/some/path"
