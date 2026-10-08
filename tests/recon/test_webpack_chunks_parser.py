import json

from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.webpack_chunks_parser import parse


def _line(url: str) -> str:
    return json.dumps({"webpack_chunk_url": url})


def test_registry_exposes_webpack_chunks():
    assert get_parser("webpack_chunks") is parse


def test_parse_mints_baseurl_and_endpoint_with_webpack_source():
    deltas = parse(_line("http://h/static/js/8.8adec4d4ce480535d13c.js"))

    baseurls = {d.identity["url"] for d in deltas if d.type == "BaseURL"}
    assert baseurls == {"http://h"}

    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(endpoints) == 1
    endpoint = endpoints[0]
    assert endpoint.identity == {
        "path": "/static/js/8.8adec4d4ce480535d13c.js",
        "method": "GET",
        "baseurl": "http://h",
    }
    assert endpoint.props["source"] == "webpack"
    assert endpoint.props["url"] == "http://h/static/js/8.8adec4d4ce480535d13c.js"


def test_endpoint_has_incoming_baseurl_edge():
    deltas = parse(_line("http://h/static/js/8.8adec4d4ce480535d13c.js"))
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert any(
        e.rel == "HAS_ENDPOINT"
        and e.dir == "in"
        and e.node_type == "BaseURL"
        and e.node_identity == {"url": "http://h"}
        for e in endpoint.edges
    )


def test_parse_ignores_malformed_and_unrelated_lines():
    stdout = "\n".join(
        [
            "not json {{{",
            json.dumps({"something": "else"}),
            "",
            _line("http://h/a/0.deadbeef01.js"),
        ]
    )
    endpoints = [d for d in parse(stdout) if d.type == "Endpoint"]
    assert [e.identity["path"] for e in endpoints] == ["/a/0.deadbeef01.js"]


def test_parse_empty_stdout_is_empty():
    assert parse("") == []
