"""Seam under test: the `steel-crawl/v2` manifest parser.

Spec: `docs/design/steel-crawl-spec.md` sections 8.4, 11, and 14; seam 9 of
`docs/design/steel-crawl-implementation-plan.md` section 3.

The parser turns the graph-bearing manifest into L0 deltas. Observed and
declared records keep their provenance; a parameter is anchored to the endpoint
its record names; scripts mint their URL as an Endpoint; realtime and error
records are not graph nodes; and the v1 path is unchanged.
"""
from __future__ import annotations

import json

from polymerhus.recon.domain.parsers.steel_parser import parse


def manifest() -> dict:
    return {
        "schema_version": "steel-crawl/v2",
        "run": {"crawl_run_id": "run-1"},
        "endpoints": [
            {
                "endpoint_id": "ep_obs",
                "provenance": "observed",
                "method": "GET",
                "url": "https://example.test/api/items?page=2",
                "path": "/api/items",
                "baseurl": "https://example.test",
                "status_code": 200,
                "source": "cdp",
                "resource_type": "XHR",
                "http_artifact_id": "http_1",
                "source_page_id": "page_1",
                "action_id": "act_1",
                "enctype": None,
                "field_names": [],
            },
            {
                "endpoint_id": "ep_dec",
                "provenance": "declared",
                "method": "POST",
                "url": "https://example.test/register",
                "path": "/register",
                "baseurl": "https://example.test",
                "status_code": None,
                "source": "dom",
                "resource_type": "document",
                "http_artifact_id": None,
                "source_page_id": "page_1",
                "action_id": None,
                "enctype": "application/x-www-form-urlencoded",
                "field_names": ["username", "password"],
            },
        ],
        "parameters": [
            {
                "parameter_id": "p_obs",
                "endpoint_id": "ep_obs",
                "provenance": "observed",
                "endpoint_path": "/api/items",
                "baseurl": "https://example.test",
                "position": "query",
                "name": "page",
                "value_shape": {"type": "number", "length_band": 0},
                "http_artifact_id": "http_1",
                "content_type": None,
                "field_type": None,
                "label": None,
                "options": None,
                "pattern": None,
                "min": None,
                "max": None,
            },
            {
                "parameter_id": "p_dec",
                "endpoint_id": "ep_dec",
                "provenance": "declared",
                "endpoint_path": "/register",
                "baseurl": "https://example.test",
                "position": "body",
                "name": "username",
                "value_shape": None,
                "http_artifact_id": None,
                "content_type": "application/x-www-form-urlencoded",
                "field_type": "text",
                "label": "Username",
                "options": [],
                "pattern": None,
                "min": None,
                "max": None,
            },
        ],
        "scripts": [
            {
                "script_url": "https://example.test/static/app.js",
                "script_id": "10",
                "provenance": "debugger",
            }
        ],
        "realtime": [{"request_id": "ws-1", "kind": "frame_sent"}],
        "errors": [{"code": "stale_element", "message": "gone"}],
        "stats": {},
    }


def test_v2_endpoints_keep_their_provenance_and_metadata():
    deltas = parse(json.dumps(manifest()))
    endpoints = [delta for delta in deltas if delta.type == "Endpoint"]

    observed = next(
        delta for delta in endpoints if delta.identity["path"] == "/api/items"
    )
    assert observed.identity == {
        "path": "/api/items",
        "method": "GET",
        "baseurl": "https://example.test",
    }
    assert observed.props["provenance"] == "observed"
    assert observed.props["status_code"] == 200
    assert observed.props["source"] == "cdp"
    assert observed.props["resource_type"] == "XHR"
    assert observed.props["http_artifact_id"] == "http_1"
    assert observed.props["source_page_id"] == "page_1"
    assert observed.props["action_id"] == "act_1"

    declared = next(
        delta for delta in endpoints if delta.identity["path"] == "/register"
    )
    assert declared.props["provenance"] == "declared"
    assert declared.props["source"] == "dom"
    assert declared.props["enctype"] == "application/x-www-form-urlencoded"
    assert declared.props["field_names"] == ["username", "password"]


def test_v2_parameters_keep_their_provenance_and_anchor_to_their_endpoint():
    deltas = parse(json.dumps(manifest()))
    parameters = [delta for delta in deltas if delta.type == "Parameter"]

    observed = next(
        delta
        for delta in parameters
        if delta.identity["name"] == "page"
        and delta.identity["position"] == "query"
    )
    assert observed.identity == {
        "name": "page",
        "position": "query",
        "endpoint_path": "/api/items",
        "baseurl": "https://example.test",
    }
    assert observed.props["provenance"] == "observed"
    assert observed.props["value_shape_type"] == "number"
    assert observed.props["value_shape_length_band"] == 0
    assert observed.props["http_artifact_id"] == "http_1"
    assert observed.edges[0].node_identity == {
        "path": "/api/items",
        "method": "GET",
        "baseurl": "https://example.test",
    }

    declared = next(
        delta
        for delta in parameters
        if delta.identity["name"] == "username"
        and delta.identity["position"] == "body"
    )
    assert declared.props["provenance"] == "declared"
    assert declared.props["field_type"] == "text"
    assert declared.props["label"] == "Username"
    assert declared.props["content_type"] == "application/x-www-form-urlencoded"
    assert declared.props["options"] == []
    assert declared.edges[0].node_identity == {
        "path": "/register",
        "method": "POST",
        "baseurl": "https://example.test",
    }


def test_v2_graph_props_are_neo4j_safe_scalars():
    deltas = parse(json.dumps(manifest()))

    for delta in deltas:
        for key, value in delta.props.items():
            assert not isinstance(value, dict), (delta.type, key, value)


def test_a_v2_script_mints_a_steel_script_endpoint():
    deltas = parse(json.dumps(manifest()))
    script = next(
        delta
        for delta in deltas
        if delta.type == "Endpoint" and delta.identity["path"] == "/static/app.js"
    )

    assert script.props["source"] == "steel-script"
    assert script.props["script_id"] == "10"
    assert script.props["provenance"] == "debugger"


def test_v2_realtime_and_errors_are_not_graph_deltas():
    deltas = parse(json.dumps(manifest()))

    assert {delta.type for delta in deltas} <= {"BaseURL", "Endpoint", "Parameter"}
    assert not any(
        delta.identity.get("name") == "ws-1" for delta in deltas
    )


def test_the_manifest_parameter_wins_over_the_url_query_projection():
    deltas = parse(json.dumps(manifest()))
    page_params = [
        delta
        for delta in deltas
        if delta.type == "Parameter"
        and delta.identity["name"] == "page"
        and delta.identity["position"] == "query"
    ]

    assert len(page_params) == 1
    assert page_params[0].props["provenance"] == "observed"


def test_a_v2_parameter_with_an_unknown_endpoint_is_skipped():
    data = manifest()
    data["parameters"].append(
        {
            "parameter_id": "p_missing",
            "endpoint_id": "missing",
            "provenance": "observed",
            "endpoint_path": "/missing",
            "baseurl": "https://example.test",
            "position": "query",
            "name": "orphan",
        }
    )

    deltas = parse(json.dumps(data))

    assert not any(
        delta.type == "Parameter" and delta.identity.get("name") == "orphan"
        for delta in deltas
    )


def test_a_malformed_v2_manifest_is_partial_not_an_exception():
    deltas = parse(
        '{"schema_version": "steel-crawl/v2", "endpoints": "bad", '
        '"parameters": "bad", "scripts": "bad"}'
    )

    assert deltas == []


def test_a_v1_manifest_still_takes_the_v1_path():
    deltas = parse(
        '{"endpoints": [{"method": "GET", "url": '
        '"https://example.test/legacy", "query": ["id"], "status": 200}], '
        '"js_urls": []}'
    )

    assert any(delta.type == "Endpoint" for delta in deltas)
    assert any(delta.type == "Parameter" for delta in deltas)
