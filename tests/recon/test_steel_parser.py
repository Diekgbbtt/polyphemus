# tests/recon/test_steel_parser.py
from pathlib import Path

from agent.recon.parsers import get_parser
from agent.recon.parsers.steel_parser import parse

FIX = Path(__file__).parent / "fixtures" / "steel_manifest.json"


def test_registry_exposes_steel_crawl():
    assert get_parser("steel_crawl") is parse


def test_parse_emits_baseurl_and_endpoints():
    deltas = parse(FIX.read_text())

    baseurls = {d.identity["url"] for d in deltas if d.type == "BaseURL"}
    assert baseurls == {"https://app.example.com"}

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    # 2 endpoints from manifest + 1 endpoint from js_urls
    assert len(endpoints) == 3

    search = next(e for e in endpoints if e.identity["path"] == "/search")
    assert search.identity["method"] == "GET"
    assert search.identity["baseurl"] == "https://app.example.com"
    assert search.props["status_code"] == 200
    assert search.props["source"] == "steel"

    login = next(e for e in endpoints if e.identity["path"] == "/login")
    assert login.identity["method"] == "POST"
    assert login.props["status_code"] == 200
    assert login.props["source"] == "steel"


def test_endpoint_has_incoming_baseurl_edge():
    deltas = parse(FIX.read_text())
    search = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/search"
    )
    assert any(
        e.rel == "HAS_ENDPOINT" and e.dir == "in" and e.node_type == "BaseURL"
        and e.node_identity == {"url": "https://app.example.com"}
        for e in search.edges
    )


def test_query_param_emits_parameter_delta_with_edge():
    deltas = parse(FIX.read_text())
    search = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/search"
    )
    params = [
        d for d in deltas
        if d.type == "Parameter" and d.identity["endpoint_path"] == "/search"
    ]
    assert len(params) == 1
    param = params[0]
    assert param.identity == {
        "name": "id",
        "position": "query",
        "endpoint_path": "/search",
        "baseurl": "https://app.example.com",
    }
    assert any(
        e.rel == "HAS_PARAMETER" and e.dir == "in" and e.node_type == "Endpoint"
        and e.node_identity == search.identity
        for e in param.edges
    )


def test_body_param_emits_parameter_delta_with_edge():
    deltas = parse(FIX.read_text())
    login = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/login"
    )
    params = [
        d for d in deltas
        if d.type == "Parameter" and d.identity["endpoint_path"] == "/login"
    ]
    assert len(params) == 1
    param = params[0]
    assert param.identity == {
        "name": "username",
        "position": "body",
        "endpoint_path": "/login",
        "baseurl": "https://app.example.com",
    }
    assert any(
        e.rel == "HAS_PARAMETER" and e.dir == "in" and e.node_type == "Endpoint"
        and e.node_identity == login.identity
        for e in param.edges
    )


def test_js_url_emits_endpoint_with_steel_js_source():
    deltas = parse(FIX.read_text())
    endpoints = [d for d in deltas if d.type == "Endpoint"]
    js_endpoint = next(
        e for e in endpoints if e.identity["path"] == "/static/bundle.js"
    )
    assert js_endpoint.identity["method"] == "GET"
    assert js_endpoint.props["source"] == "steel-js"
    assert js_endpoint.props["url"] == "https://app.example.com/static/bundle.js"
    assert any(
        e.rel == "HAS_ENDPOINT" and e.dir == "in" and e.node_type == "BaseURL"
        and e.node_identity == {"url": "https://app.example.com"}
        for e in js_endpoint.edges
    )


def test_malformed_json_returns_empty_list():
    assert parse("not json") == []


def test_non_dict_json_returns_empty_list():
    assert parse("42") == []
    assert parse("[1, 2, 3]") == []


def test_empty_dict_returns_empty_list():
    assert parse("{}") == []


def test_missing_endpoints_and_js_urls_keys_tolerated():
    assert parse('{"foo": "bar"}') == []


def test_none_endpoints_and_js_urls_tolerated():
    assert parse('{"endpoints": null, "js_urls": null}') == []


def test_non_list_query_does_not_char_iterate():
    manifest = (
        '{"endpoints": [{"method": "GET", "url": "https://x.example.com/p", '
        '"query": "id", "body": [], "status": 200}], "js_urls": []}'
    )
    deltas = parse(manifest)
    params = [d for d in deltas if d.type == "Parameter"]
    assert params == []
    # sanity: endpoint still emitted
    assert any(d.type == "Endpoint" for d in deltas)


def test_non_list_body_does_not_char_iterate():
    manifest = (
        '{"endpoints": [{"method": "POST", "url": "https://x.example.com/p", '
        '"query": [], "body": "token", "status": 200}], "js_urls": []}'
    )
    deltas = parse(manifest)
    params = [d for d in deltas if d.type == "Parameter"]
    assert params == []
    assert any(d.type == "Endpoint" for d in deltas)


def test_duplicate_body_params_deduped():
    manifest = (
        '{"endpoints": [{"method": "POST", "url": "https://x.example.com/p", '
        '"query": [], "body": ["token", "token"], "status": 200}], "js_urls": []}'
    )
    deltas = parse(manifest)
    body_params = [
        d for d in deltas
        if d.type == "Parameter" and d.identity["position"] == "body"
    ]
    assert len(body_params) == 1
    assert body_params[0].identity["name"] == "token"


def test_dict_shaped_query_and_body_params_handled_defensively():
    manifest = (
        '{"endpoints": [{"method": "GET", "url": "https://x.example.com/p", '
        '"query": [{"name": "page"}], "body": [{"name": "token"}], "status": 200}], '
        '"js_urls": []}'
    )
    deltas = parse(manifest)
    params = [d for d in deltas if d.type == "Parameter"]
    names_positions = {(p.identity["name"], p.identity["position"]) for p in params}
    assert names_positions == {("page", "query"), ("token", "body")}
