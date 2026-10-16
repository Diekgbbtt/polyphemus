"""Unit predicates for the L0 read side (`l0_stream`): the identity map and the
slice -> `AssetDelta` projection.

The `Header` identity is `{name, endpoint, baseurl}` (operator ruling 2026-10-16):
the value is a PROP, not an identity key, and the endpoint scopes the header to
the path that returned it. `assets_from_slice` must rebuild exactly that split.
"""
from polymerhus.analysis.l0_stream import L0_IDENTITY_KEYS, assets_from_slice


def test_header_identity_keys_are_name_endpoint_baseurl():
    assert L0_IDENTITY_KEYS["Header"] == ("name", "endpoint", "baseurl")


def test_header_value_is_not_an_identity_key():
    # The response value must never be part of the identity: it is a prop (the
    # response-header VALUE), so it does not partition the identity space.
    assert "value" not in L0_IDENTITY_KEYS["Header"]


def test_assets_from_slice_splits_header_identity_from_value_prop():
    l0 = {"nodes": [{
        "type": "Header",
        "properties": {
            "name": "content-type", "endpoint": "/a", "baseurl": "https://h",
            "value": "text/html", "direction": "response",
            "project_id": "p", "first_seen": 1, "last_seen": 2,
        },
    }], "links": []}
    (asset,) = assets_from_slice(l0)
    assert asset.identity == {
        "name": "content-type", "endpoint": "/a", "baseurl": "https://h"}
    assert asset.props == {"value": "text/html", "direction": "response"}


def test_two_endpoints_headers_project_to_distinct_identities():
    """Two same-named headers on two endpoints under one BaseURL are two distinct
    identities on the read side - the endpoint scopes them apart."""
    nodes = [
        {"type": "Header", "properties": {
            "name": "x", "endpoint": "/a", "baseurl": "https://h",
            "value": "1", "direction": "response"}},
        {"type": "Header", "properties": {
            "name": "x", "endpoint": "/b", "baseurl": "https://h",
            "value": "2", "direction": "response"}},
    ]
    out = assets_from_slice({"nodes": nodes, "links": []})
    assert [a.identity["endpoint"] for a in out] == ["/a", "/b"]
    assert {a.props["value"] for a in out} == {"1", "2"}
