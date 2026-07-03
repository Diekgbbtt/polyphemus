# tests/recon/test_urls_helper.py
from agent.recon.parsers._urls import base_and_path, registrable_domain, url_to_deltas


def test_base_and_path_normal_url_with_path():
    assert base_and_path("https://host.example.com/a/b?x=1") == (
        "https://host.example.com",
        "/a/b",
    )


def test_base_and_path_bare_host_defaults_path_to_slash():
    assert base_and_path("https://host.example.com") == ("https://host.example.com", "/")


def test_base_and_path_no_scheme_returns_none():
    assert base_and_path("host.example.com/a") is None
    assert base_and_path("/just/a/path") is None


def test_base_and_path_non_string_returns_none():
    assert base_and_path(12345) is None
    assert base_and_path(None) is None


def test_base_and_path_default_port_not_stripped():
    assert base_and_path("https://host.example.com:443/a") == (
        "https://host.example.com:443",
        "/a",
    )


def test_url_to_deltas_emits_baseurl_endpoint_and_params_with_byte_matched_edges():
    deltas = url_to_deltas(
        "https://host.example.com/search?id=1&q=x", source="testtool"
    )

    baseurl = next(d for d in deltas if d.type == "BaseURL")
    assert baseurl.identity == {"url": "https://host.example.com"}

    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert endpoint.identity == {
        "path": "/search",
        "method": "GET",
        "baseurl": "https://host.example.com",
    }
    assert endpoint.props == {
        "url": "https://host.example.com/search?id=1&q=x",
        "source": "testtool",
    }
    edge = next(e for e in endpoint.edges if e.rel == "HAS_ENDPOINT")
    assert edge.dir == "in"
    assert edge.node_type == "BaseURL"
    assert edge.node_identity == baseurl.identity

    params = [d for d in deltas if d.type == "Parameter"]
    names = {p.identity["name"] for p in params}
    assert names == {"id", "q"}
    for p in params:
        assert p.identity["position"] == "query"
        assert p.identity["endpoint_path"] == "/search"
        assert p.identity["baseurl"] == "https://host.example.com"
        pedge = next(e for e in p.edges if e.rel == "HAS_PARAMETER")
        assert pedge.dir == "in"
        assert pedge.node_type == "Endpoint"
        assert pedge.node_identity == endpoint.identity


def test_url_to_deltas_method_uppercased():
    deltas = url_to_deltas("https://h.example.com/x", method="post", source="t")
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert endpoint.identity["method"] == "POST"


def test_url_to_deltas_non_string_method_defaults_to_get():
    deltas = url_to_deltas("https://h.example.com/x", method=12345, source="t")
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert endpoint.identity["method"] == "GET"


def test_url_to_deltas_extra_endpoint_props_merged():
    deltas = url_to_deltas(
        "https://h.example.com/x",
        source="t",
        extra_endpoint_props={"status_code": 200},
    )
    endpoint = next(d for d in deltas if d.type == "Endpoint")
    assert endpoint.props["status_code"] == 200
    assert endpoint.props["url"] == "https://h.example.com/x"
    assert endpoint.props["source"] == "t"


def test_url_to_deltas_invalid_url_returns_empty_list():
    assert url_to_deltas("not-a-url", source="t") == []
    assert url_to_deltas("", source="t") == []
    assert url_to_deltas(None, source="t") == []


def test_registrable_domain_strips_subdomains():
    assert registrable_domain("www.host.example.com") == "example.com"
    assert registrable_domain("example.com") == "example.com"
    assert registrable_domain("localhost") == "localhost"
