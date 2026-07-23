# tests/recon/test_httpx_parser.py
from pathlib import Path
from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers.httpx_parser import parse

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


def test_endpoint_source_is_the_tool_name():
    # source must be the tool ("httpx"), not the skill/phase name.
    deltas = parse(FIX.read_text())
    ep = next(d for d in deltas if d.type == "Endpoint")
    assert ep.props["source"] == "httpx"


def test_every_baseurl_belongs_to_its_source_subdomain():
    """Strong constraint: no orphan BaseURLs - every httpx BaseURL must carry a
    BELONGS_TO edge to the Subdomain it was probed from (httpx `input`)."""
    deltas = parse(FIX.read_text())
    baseurls = [d for d in deltas if d.type == "BaseURL"]
    assert baseurls
    for b in baseurls:
        belongs = [e for e in b.edges
                   if e.rel == "BELONGS_TO" and e.node_type == "Subdomain"]
        assert belongs, f"BaseURL {b.identity} has no BELONGS_TO->Subdomain edge"
    # the app.example.com probe links to Subdomain{name: app.example.com}
    app = next(b for b in baseurls if b.identity["url"] == "https://app.example.com")
    assert app.edges[0].node_identity == {"name": "app.example.com"}

def test_malformed_line_skipped():
    deltas = parse('{"url":"https://a","status_code":200}\nNOT JSON\n')
    assert any(d.type == "BaseURL" for d in deltas)


def test_parse_emits_headers_with_baseurl_edge():
    # httpx `-irh` includes response headers under the `header` key (a map of
    # already-lowercased name -> value). Each becomes a Header node keyed on
    # {name, baseurl} with the value as a prop and an inbound HAS_HEADER edge
    # from the BaseURL: (BaseURL)-[:HAS_HEADER]->(Header).
    line = (
        '{"url":"https://h.example.com","status_code":200,'
        '"header":{"server":"nginx","content_type":"text/html","cf_ray":"abc123"}}\n'
    )
    deltas = parse(line)

    headers = [d for d in deltas if d.type == "Header"]
    by_name = {d.identity["name"]: d for d in headers}
    assert set(by_name) == {"server", "content_type", "cf_ray"}
    assert by_name["server"].identity == {"name": "server", "baseurl": "https://h.example.com"}
    assert by_name["server"].props == {"value": "nginx"}

    edge = by_name["server"].edges[0]
    assert edge.rel == "HAS_HEADER"
    assert edge.dir == "in"
    assert edge.node_type == "BaseURL"
    assert edge.node_identity == {"url": "https://h.example.com"}


def test_parse_no_headers_when_header_field_absent():
    # No `header` key (httpx run without -irh, or malformed) -> zero Header deltas.
    deltas = parse('{"url":"https://a.example.com","status_code":200}\n')
    assert not [d for d in deltas if d.type == "Header"]


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


def test_baseurl_and_endpoint_carry_webapp_restapi_profile():
    # D16: httpx sets a `profile` prop on both the BaseURL and its root Endpoint,
    # derived from content-type (JSON-family -> restapi) else webapp.
    api = parse('{"url":"https://x.example.com","status_code":200,"content_type":"application/json"}\n')
    assert next(d for d in api if d.type == "BaseURL").props["profile"] == "restapi"
    assert next(d for d in api if d.type == "Endpoint").props["profile"] == "restapi"

    app = parse('{"url":"https://x.example.com","status_code":200,"content_type":"text/html"}\n')
    assert next(d for d in app if d.type == "BaseURL").props["profile"] == "webapp"


def test_reprofile_job_uses_the_httpx_parser_to_profile_a_crawler_minted_baseurl():
    # D27: the reprofile pass re-probes BaseURLs a crawler minted without a
    # profile (e.g. a JS-derived API host jsluice recovered). It reuses the
    # httpx parser (registered under `httpx_reprofile`), so the re-probe of such
    # a host classifies it restapi via the same classify_profile path - which is
    # exactly what gates kiterunner downstream.
    assert get_parser("httpx_reprofile") is parse
    reprobed = get_parser("httpx_reprofile")(
        '{"url":"https://api.internal.example.com","status_code":200,'
        '"content_type":"application/json"}\n'
    )
    assert next(d for d in reprobed if d.type == "BaseURL").props["profile"] == "restapi"
