# tests/recon/test_passive_url_parser.py
from pathlib import Path

from agent.recon.parsers import get_parser
from agent.recon.parsers.passive_url_parser import parse_gau, parse_paramspider

GAU_FIX = Path(__file__).parent / "fixtures" / "gau.txt"
PARAMSPIDER_FIX = Path(__file__).parent / "fixtures" / "paramspider.txt"


def test_registry_exposes_gau_and_paramspider():
    assert get_parser("gau") is parse_gau
    assert get_parser("paramspider") is parse_paramspider


def test_gau_parses_baseurl_and_endpoints():
    deltas = parse_gau(GAU_FIX.read_text())

    baseurls = [d for d in deltas if d.type == "BaseURL"]
    assert baseurls
    assert all(b.identity["url"] == "https://app.example.com" for b in baseurls)

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 2

    dashboard = next(e for e in endpoints if e.identity["path"] == "/dashboard")
    assert dashboard.identity["method"] == "GET"
    assert dashboard.identity["baseurl"] == "https://app.example.com"
    assert dashboard.props["source"] == "gau"

    search = next(e for e in endpoints if e.identity["path"] == "/search")
    assert search.props["source"] == "gau"


def test_gau_query_params_emit_parameter_deltas_with_matching_edge():
    deltas = parse_gau(GAU_FIX.read_text())

    search_endpoint = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/search"
    )
    params = [
        d for d in deltas
        if d.type == "Parameter" and d.identity.get("endpoint_path") == "/search"
    ]
    assert len(params) == 2

    names = {p.identity["name"] for p in params}
    assert names == {"id", "q"}

    for p in params:
        assert p.identity["position"] == "query"
        assert p.identity["baseurl"] == "https://app.example.com"
        edge = next(e for e in p.edges if e.rel == "HAS_PARAMETER")
        assert edge.dir == "in"
        assert edge.node_type == "Endpoint"
        # node_identity must byte-match the Endpoint's own identity dict exactly
        assert edge.node_identity == search_endpoint.identity


def test_gau_garbage_and_blank_lines_skipped():
    deltas = parse_gau("\n\nnot a valid url at all\n")
    assert deltas == []


def test_paramspider_extracts_params_and_handles_fuzz_values():
    deltas = parse_paramspider(PARAMSPIDER_FIX.read_text())

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 1
    assert endpoints[0].props["source"] == "paramspider"

    params = [d for d in deltas if d.type == "Parameter"]
    names = {p.identity["name"] for p in params}
    assert names == {"id", "q"}
    # FUZZ is the placeholder value, not a param name - must not leak into identity
    assert all("FUZZ" not in p.identity["name"] for p in params)


def test_paramspider_garbage_line_skipped():
    deltas = parse_paramspider("garbage-line-not-a-url\n")
    assert deltas == []
