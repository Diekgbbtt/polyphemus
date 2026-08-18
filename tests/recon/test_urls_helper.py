# tests/recon/test_urls_helper.py
import pytest

from polymerhus.recon.domain.parsers._urls import (
    base_and_path,
    is_malformed_concat_path,
    registrable_domain,
    url_to_deltas,
)


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


# --- AMV-8 ticket 5: JS string-concatenation fragment guard ----------------

@pytest.mark.parametrize("path", [
    "/'+_(i[8])+'",                 # raw concat fragment
    "/%27+_%28i%5B11%5D",           # percent-encoded form
    "/api/'+id+'",                  # embedded quote
    "/x(unbalanced",                # unbalanced paren
    "/y[0]extra]",                  # unbalanced bracket
    '/"+token+"',                   # double-quote concat
    # AMV-8 e2e residuals: minified JS member-expression segments mis-read as
    # paths (single-letter root + dotted properties) ...
    "/i.document.do",
    "/l.number/e.do",
    "/r.dom.offsetHeight/r.do",
    "/i.visualViewport.scale/i.document.do",
    # ... and template placeholders (raw + percent-encoded {{href}}).
    "/{{href}}",
    "/%7B%7Bhref%7D%7D",
])
def test_is_malformed_concat_path_true(path):
    assert is_malformed_concat_path(path) is True


@pytest.mark.parametrize("path", [
    "/api/v1/users",
    "/",
    "/soljson-v0.8.21+commit.a1b2c3d4.js",   # a `+` is fine when balanced/quoteless
    "/search+results",
    "/api/(v1)/x",                            # balanced parens are not malformed
    # real multi-char dotted filenames/segments must NOT be flagged
    "/juice-shop/build/routes/verify.js",    # verify.js: root is not a single letter
    "/login.do",                             # a real Struts endpoint (multi-char root)
    "/api/Products",
    "/rest/user/whoami",
    "/v3/",
])
def test_is_malformed_concat_path_false(path):
    assert is_malformed_concat_path(path) is False


def test_url_to_deltas_drops_concat_fragment():
    assert url_to_deltas("https://h.example.com/'+_(i[8])+'", source="jsluice") == []
    assert url_to_deltas("https://h.example.com/%27+_%28x", source="jsluice") == []


def test_registrable_domain_strips_subdomains():
    assert registrable_domain("www.host.example.com") == "example.com"
    assert registrable_domain("example.com") == "example.com"
    assert registrable_domain("localhost") == "localhost"
