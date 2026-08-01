# tests/recon/test_katana_parser.py
from pathlib import Path
from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.katana_parser import parse

FIX = Path(__file__).parent / "fixtures" / "katana.jsonl"


def test_registry_exposes_katana():
    assert get_parser("katana") is parse


def test_parse_emits_baseurl_and_endpoint():
    deltas = parse(FIX.read_text())

    baseurls = [d for d in deltas if d.type == "BaseURL"]
    assert baseurls
    assert all(b.identity["url"] == "https://app.example.com" for b in baseurls)

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 2

    dashboard = next(e for e in endpoints if e.identity["path"] == "/dashboard")
    assert dashboard.identity["method"] == "GET"
    assert dashboard.identity["baseurl"] == "https://app.example.com"
    assert dashboard.props["status_code"] == 200
    assert dashboard.props["content_type"] == "text/html"
    assert dashboard.props["source"] == "katana"

    search = next(e for e in endpoints if e.identity["path"] == "/search")
    assert search.identity["method"] == "GET"


def test_endpoint_has_incoming_baseurl_edge():
    deltas = parse(FIX.read_text())
    dashboard = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/dashboard"
    )
    assert any(
        e.rel == "HAS_ENDPOINT" and e.dir == "in" and e.node_type == "BaseURL"
        and e.node_identity == {"url": "https://app.example.com"}
        for e in dashboard.edges
    )


def test_query_params_emit_parameter_deltas_with_edge():
    deltas = parse(FIX.read_text())
    params = [d for d in deltas if d.type == "Parameter"]
    assert len(params) == 2

    names = {p.identity["name"] for p in params}
    assert names == {"id", "q"}

    search = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/search"
    )

    for p in params:
        assert p.identity["position"] == "query"
        assert p.identity["endpoint_path"] == "/search"
        assert p.identity["baseurl"] == "https://app.example.com"
        assert any(
            e.rel == "HAS_PARAMETER" and e.dir == "in" and e.node_type == "Endpoint"
            and e.node_identity == search.identity
            for e in p.edges
        )


def test_dashboard_endpoint_has_no_parameters():
    deltas = parse(FIX.read_text())
    dashboard = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/dashboard"
    )
    params_for_dashboard = [
        d for d in deltas
        if d.type == "Parameter" and d.identity.get("endpoint_path") == "/dashboard"
    ]
    assert params_for_dashboard == []
    assert dashboard  # sanity


def test_malformed_line_skipped():
    deltas = parse(
        '{"request":{"endpoint":"https://a.example.com/x","method":"GET"},'
        '"response":{"status_code":200}}\nNOT JSON\n'
    )
    assert any(d.type == "BaseURL" for d in deltas)
    assert any(d.type == "Endpoint" for d in deltas)


def test_missing_request_endpoint_skipped():
    deltas = parse('{"response":{"status_code":200}}\n{"request":{}}\n')
    assert deltas == []


def test_katana_form_extraction_emits_body_parameters():
    # Param discovery: with -fx katana emits response.forms[] = {method, action,
    # enctype, parameters:[names]}. The parser turns a POST form's parameters
    # into body Parameter deltas anchored to the form's action Endpoint.
    from polymerhus.recon.domain.parsers.katana_parser import parse
    line = (
        '{"request":{"endpoint":"https://h/","method":"GET"},'
        '"response":{"status_code":200,"headers":{"Content-Type":"text/html"},'
        '"forms":[{"method":"POST","action":"https://h/login",'
        '"parameters":["user","pass"]}]}}\n'
    )
    out = parse(line)
    params = {(d.identity["name"], d.identity["position"]) for d in out if d.type == "Parameter"}
    assert ("user", "body") in params
    assert ("pass", "body") in params
    assert any(d.type == "Endpoint" and d.identity["path"] == "/login" for d in out)


def test_content_type_read_from_response_headers():
    # Issue #52 regression: katana's response object has no top-level
    # content_type key - it only appears as response.headers["Content-Type"].
    from polymerhus.recon.domain.parsers.katana_parser import parse
    line = (
        '{"request":{"endpoint":"https://h/page","method":"GET"},'
        '"response":{"status_code":200,"headers":{"Content-Type":"application/json"}}}\n'
    )
    out = parse(line)
    endpoint = next(d for d in out if d.type == "Endpoint")
    assert endpoint.props["content_type"] == "application/json"


def test_katana_get_form_parameters_are_query_position():
    from polymerhus.recon.domain.parsers.katana_parser import parse
    line = (
        '{"request":{"endpoint":"https://h/","method":"GET"},'
        '"response":{"forms":[{"method":"GET","action":"https://h/search",'
        '"parameters":["q"]}]}}\n'
    )
    out = parse(line)
    params = {(d.identity["name"], d.identity["position"]) for d in out if d.type == "Parameter"}
    assert ("q", "query") in params
