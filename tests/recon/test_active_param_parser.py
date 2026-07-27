# tests/recon/test_active_param_parser.py
from pathlib import Path

from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.active_param_parser import (
    parse_arjun,
    parse_ffuf,
    parse_kiterunner,
)

ARJUN_FIX = Path(__file__).parent / "fixtures" / "arjun.json"
FFUF_FIX = Path(__file__).parent / "fixtures" / "ffuf.json"
KITERUNNER_FIX = Path(__file__).parent / "fixtures" / "kiterunner.txt"


def test_registry_exposes_arjun_ffuf_kiterunner():
    assert get_parser("arjun") is parse_arjun
    assert get_parser("ffuf") is parse_ffuf
    assert get_parser("kiterunner") is parse_kiterunner


def test_arjun_query_method_yields_query_position_parameter_with_matching_edge():
    deltas = parse_arjun(ARJUN_FIX.read_text())

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    search_endpoint = next(e for e in endpoints if e.identity["path"] == "/search")
    assert search_endpoint.identity["method"] == "GET"
    assert search_endpoint.identity["baseurl"] == "https://api.example.com"

    baseurls = [d for d in deltas if d.type == "BaseURL"]
    assert any(b.identity["url"] == "https://api.example.com" for b in baseurls)

    params = [
        d for d in deltas
        if d.type == "Parameter" and d.identity.get("endpoint_path") == "/search"
    ]
    names = {p.identity["name"] for p in params}
    assert names == {"q", "page"}

    for p in params:
        assert p.identity["position"] == "query"
        assert p.identity["baseurl"] == "https://api.example.com"
        edge = next(e for e in p.edges if e.rel == "HAS_PARAMETER")
        assert edge.dir == "in"
        assert edge.node_type == "Endpoint"
        # node_identity must byte-match the Endpoint's own identity dict exactly
        assert edge.node_identity == search_endpoint.identity


def test_arjun_post_method_yields_body_position_parameter():
    deltas = parse_arjun(ARJUN_FIX.read_text())

    submit_endpoint = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/submit"
    )
    assert submit_endpoint.identity["method"] == "POST"

    params = [
        d for d in deltas
        if d.type == "Parameter" and d.identity.get("endpoint_path") == "/submit"
    ]
    assert len(params) == 1
    assert params[0].identity["name"] == "token"
    assert params[0].identity["position"] == "body"
    edge = next(e for e in params[0].edges if e.rel == "HAS_PARAMETER")
    assert edge.node_identity == submit_endpoint.identity


def test_arjun_malformed_input_tolerated():
    assert parse_arjun("not json at all") == []
    assert parse_arjun("[]") == []  # valid json but not a dict
    assert parse_arjun('{"https://x.com/a": "not-a-dict"}') == []
    assert parse_arjun("") == []


def test_arjun_tolerates_tool_progress_prepended_before_json():
    # arjun prints its own `[!]` progress lines to STDOUT, so a
    # `arjun ... && cat file` command hands the parser `[!] lines\n{JSON}`,
    # which is not a single JSON document. The parser must still recover the
    # discovered parameters from the embedded JSON rather than silently
    # dropping every finding (the live-run failure this guards against).
    progress = (
        "[!] Analysing HTTP response for anomalies\n"
        "[!] Processing chunks: 103/103\n"
    )
    deltas = parse_arjun(progress + ARJUN_FIX.read_text())

    params = [d for d in deltas if d.type == "Parameter"]
    names = {p.identity["name"] for p in params}
    assert {"q", "page"} <= names


def test_ffuf_results_yield_endpoint_deltas_with_status_and_mixed_codes():
    deltas = parse_ffuf(FFUF_FIX.read_text())

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 2

    admin = next(e for e in endpoints if e.identity["path"] == "/admin")
    assert admin.identity["method"] == "GET"
    assert admin.identity["baseurl"] == "https://example.com"
    assert admin.props["status_code"] == 200
    assert admin.props["source"] == "ffuf"

    backup = next(e for e in endpoints if e.identity["path"] == "/backup")
    assert backup.props["status_code"] == 403

    edge = next(e for e in admin.edges if e.rel == "HAS_ENDPOINT")
    assert edge.dir == "in"
    assert edge.node_type == "BaseURL"
    baseurl_delta = next(d for d in deltas if d.type == "BaseURL")
    assert edge.node_identity == baseurl_delta.identity


def test_ffuf_tolerates_tool_results_table_prepended_before_json():
    # ffuf prints its human-readable results table to STDOUT, so a
    # `ffuf ... && cat file` command hands the parser `<table>\n{JSON}`, which
    # is not a single JSON document. The parser must still recover the endpoints
    # from the embedded JSON rather than silently dropping every finding.
    table = (
        ".gitattributes      [Status: 200, Size: 1, Words: 1, Lines: 1]\n"
        "robots.txt          [Status: 200, Size: 2, Words: 1, Lines: 1]\n"
    )
    deltas = parse_ffuf(table + FFUF_FIX.read_text())

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 2  # identical to the clean-JSON case


def test_ffuf_malformed_input_tolerated():
    assert parse_ffuf("not json") == []
    assert parse_ffuf("[]") == []
    assert parse_ffuf('{"results": "not-a-list"}') == []
    assert parse_ffuf('{"results": ["not-a-dict"]}') == []
    assert parse_ffuf("") == []


def test_ffuf_non_empty_non_json_stdout_logs_warning(caplog):
    # ffuf ran but its JSON never reached us (e.g. `-of json` with no `-o`
    # destination, so stdout is the human banner/progress). This must be a
    # visible signal, not a silent [] - "parser got garbage" != "found nothing".
    banner = "        /'___\\  /'___\\\n.bashrc [Status: 200, Size: 819]\n"
    with caplog.at_level("WARNING"):
        assert parse_ffuf(banner) == []
    assert any(
        r.levelname == "WARNING" and "not valid JSON" in r.getMessage()
        for r in caplog.records
    )


def test_ffuf_empty_stdout_does_not_warn(caplog):
    # A genuinely empty result (empty stdout) is not an error - stay silent.
    with caplog.at_level("WARNING"):
        assert parse_ffuf("") == []
        assert parse_ffuf("   \n") == []
    assert caplog.records == []


def test_kiterunner_json_lines_yield_endpoint_deltas():
    deltas = parse_kiterunner(KITERUNNER_FIX.read_text())

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    users = next(e for e in endpoints if e.identity["path"] == "/v1/users")
    assert users.identity["method"] == "GET"
    assert users.identity["baseurl"] == "https://api.example.com"
    assert users.props["status_code"] == 200
    assert users.props["source"] == "kiterunner"

    orders = next(e for e in endpoints if e.identity["path"] == "/v1/orders")
    assert orders.identity["method"] == "POST"
    assert orders.props["status_code"] == 401

    edge = next(e for e in users.edges if e.rel == "HAS_ENDPOINT")
    assert edge.dir == "in"
    assert edge.node_type == "BaseURL"
    baseurl_delta = next(
        d for d in deltas
        if d.type == "BaseURL" and d.identity["url"] == "https://api.example.com"
    )
    assert edge.node_identity == baseurl_delta.identity


def test_kiterunner_text_fallback_line_parsed():
    deltas = parse_kiterunner(KITERUNNER_FIX.read_text())

    orphan = next(
        d for d in deltas if d.type == "Endpoint" and d.identity["path"] == "/v1/orphan"
    )
    assert orphan.identity["method"] == "GET"
    assert orphan.props["status_code"] == 404
    assert orphan.props["source"] == "kiterunner"


def test_kiterunner_info_and_garbage_lines_skipped():
    deltas = parse_kiterunner('{"level":"info","message":"x"}\ngarbage\n\n')
    assert deltas == []


def test_kiterunner_malformed_input_tolerated():
    assert parse_kiterunner("") == []
    assert parse_kiterunner("\n\n") == []


def test_kiterunner_endpoints_carry_restapi_provenance_profile():
    # D16 split: kiterunner only runs on an API surface, so its discovered routes
    # are restapi by provenance - Endpoint.profile is stamped without re-probing.
    from polymerhus.recon.domain.parsers.active_param_parser import parse_kiterunner
    out = parse_kiterunner(
        '{"method":"GET","target":"https://h","path":"/api/v1/users",'
        '"responses":[{"sc":200}]}\n'
    )
    eps = [d for d in out if d.type == "Endpoint"]
    assert eps and all(d.props.get("profile") == "restapi" for d in eps)
