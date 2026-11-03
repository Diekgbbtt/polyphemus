"""Seam under test: the form contract, the records, and the observed extractor.

Spec: `docs/design/steel-crawl-spec.md` sections 2.6, 8.1, 8.3, 8.4, and 12.

The form contract is the declared DOM shape an offered form carries (spec 8.1).
The observed extractor reads network flows and records the shape of a parameter,
never its value (spec 8.3 P1, P2). Each record carries its own provenance
literal, so a declared record can never claim to be observed and the two sources
never merge silently (spec 8.3). Expected values come from the spec, the
checked-in fixture pack, and a worked example, never from re-running the code.
"""
from __future__ import annotations

import json
from typing import Any

from polymerhus.recon.crawl.steel.parameters import (
    FormContract,
    FormField,
    extract_parameters,
)


def field(**overrides: Any) -> FormField:
    """One field contract with the values a test does not override."""
    payload: dict[str, Any] = {"name": "q", "type": "search", "label": "Search"}
    payload.update(overrides)
    return FormField(**payload)


def contract(**overrides: Any) -> FormContract:
    """One form contract with the values a test does not override."""
    payload: dict[str, Any] = {
        "root_selector": "#search-form",
        "action": "https://example.test/search",
        "method": "GET",
        "enctype": "application/x-www-form-urlencoded",
        "fields": (field(selector="#q"),),
        "submit_selector": "#search-form > button:nth-child(1)",
        "submit_text": "Search",
    }
    payload.update(overrides)
    return FormContract(**payload)


def flow(url: str, **overrides: Any) -> dict[str, Any]:
    """One flow mapping with the fields a test does not override."""
    payload: dict[str, Any] = {
        "flow_id": "flow_1",
        "method": "GET",
        "url": url,
        "request_body": "",
        "content_type": None,
    }
    payload.update(overrides)
    return payload


def test_a_cache_bust_query_key_is_not_an_observed_parameter():
    records = extract_parameters(
        flow("https://example.test/assets/app.js?v=9f2a&cb=1&page=42")
    )

    assert [record.name for record in records] == ["page"]
    assert records[0].location == "query"


def test_a_payload_sized_path_segment_or_query_key_is_not_a_parameter():
    long_token = "a1" * 150
    records = extract_parameters(
        flow(
            "https://example.test/items/" + long_token + "?page=42&" + "k" * 300 + "=1"
        )
    )

    # The long token is still a path identifier (its NAME comes from the
    # route word before it); the 300-char query key is not a parameter name.
    assert [(record.name, record.location) for record in records] == [
        ("page", "query"),
        ("items_id", "path"),
    ]


def test_a_payload_sized_previous_segment_does_not_become_a_name():
    records = extract_parameters(
        flow("https://example.test/" + "a1" * 150 + "/421")
    )

    # Both path identifiers name themselves `id`; the huge segment never
    # becomes a 300-character slug for the number that follows it. The two
    # shapes stay distinct records because the shape is part of the key.
    assert [
        (record.name, record.location, record.value_shape.type)
        for record in records
    ] == [("id", "path", "hex"), ("id", "path", "number")]


def test_the_extractor_records_identifier_path_segments_on_the_actual_endpoint():
    cases = [
        ("/orders/1234", "orders_id", "number"),
        ("/orders/550e8400-e29b-41d4-a716-446655440000", "orders_id", "uuid"),
        ("/blobs/deadbeefdeadbeef01", "blobs_id", "hex"),
        ("/sessions/AbC123xyz", "sessions_id", "token"),
    ]

    for path, name, kind in cases:
        records = extract_parameters(flow(f"https://example.test{path}"))
        assert [
            (record.name, record.location, record.value_shape.type)
            for record in records
        ] == [(name, "path", kind)]
        # The endpoint stays the actual path that answered; the path parameter
        # names the identifier segment, and the graph anchors it to that
        # observed endpoint (spec 8.3, 8.4).
        assert {record.endpoint_key for record in records} == {
            f"GET https://example.test{path}"
        }
        assert {record.endpoint_path for record in records} == {path}


def test_a_plain_route_word_and_a_short_number_are_not_identifiers():
    # A route word has no id shape, and a two-digit segment is an ordinary route
    # token, so neither mints a parameter or a template (spec 8.3).
    records = extract_parameters(
        flow("https://example.test/products/support/42")
    )

    assert records == ()
    assert extract_parameters(flow("https://example.test/products")) == ()


def test_the_extractor_records_a_query_parameter_as_a_shape_only():
    records = extract_parameters(
        flow("https://example.test/search?q=crawler-tool&page=42")
    )

    # The value never enters the record: a type and an eight-character length
    # band describe the value and cannot reconstruct it (spec 8.3, P2).
    assert [
        (
            record.name,
            record.location,
            record.value_shape.type,
            record.value_shape.length_band,
        )
        for record in records
    ] == [("q", "query", "string", 1), ("page", "query", "number", 0)]
    assert {record.endpoint_key for record in records} == {
        "GET https://example.test/search"
    }
    assert [record.source_flow_id for record in records] == ["flow_1", "flow_1"]
    assert [record.content_type for record in records] == [None, None]
    assert {record.provenance for record in records} == {"observed"}

    records = extract_parameters(
        {
            "flow_id": "flow_1",
            "method": "GET",
            "url": "https://example.test/search?q=crawler-tool&page=42",
            "request_body": "",
            "content_type": None,
        }
    )

    # The value never enters the record: a type and an eight-character length
    # band describe the value and cannot reconstruct it (spec 8.3, P2).
    assert [
        (
            record.name,
            record.location,
            record.value_shape.type,
            record.value_shape.length_band,
        )
        for record in records
    ] == [("q", "query", "string", 1), ("page", "query", "number", 0)]
    assert {record.endpoint_key for record in records} == {
        "GET https://example.test/search"
    }
    assert [record.source_flow_id for record in records] == ["flow_1", "flow_1"]
    assert [record.content_type for record in records] == [None, None]
    assert {record.provenance for record in records} == {"observed"}


def test_the_form_fingerprint_is_stable_over_the_submission_shape():
    # The fingerprint names the submission a form produces, so it is stable over
    # everything the request body depends on and nothing else.
    assert contract().fingerprint == contract().fingerprint

    # A label and a checked state are projection detail, not submission shape.
    relabelled = contract(fields=(field(selector="#q", label="Keyword", checked=True),))
    assert relabelled.fingerprint == contract().fingerprint

    # Two identical forms on one page produce the same submission, so the root
    # selector is not part of the fingerprint (spec P4: once per state).
    assert contract(root_selector="#other").fingerprint == contract().fingerprint

    # DOM detail is not the submission shape: a new field ref and a new submit
    # selector are the same submission, so a re-rendered form is not submitted
    # twice in one state (spec P4).
    assert (
        contract(fields=(field(selector="#search-query"),)).fingerprint
        == contract().fingerprint
    )
    assert contract(submit_selector="#go").fingerprint == contract().fingerprint

    # Every semantic part of the submission shape moves it.
    for changed in (
        contract(method="POST"),
        contract(action="https://example.test/find"),
        contract(enctype="multipart/form-data"),
        contract(fields=(field(selector="#q", name="query"),)),
        contract(fields=(field(selector="#q", type="text"),)),
        contract(fields=(field(selector="#q", options=("a", "b")),)),
        contract(fields=(field(selector="#q", pattern="[a-z]+"),)),
        contract(fields=(field(selector="#q", min="1"),)),
        contract(fields=(field(selector="#q", max="9"),)),
    ):
        assert changed.fingerprint != contract().fingerprint


def test_the_extractor_reads_json_body_attributes_as_shapes_only():
    records = extract_parameters(
        flow(
            "https://example.test/api/orders/1234",
            method="POST",
            content_type="application/json",
            request_body=(
                '{"title": "A book", "count": 3, "published": true, '
                '"meta": {"tag": "new"}}'
            ),
        )
    )

    body = [record for record in records if record.location == "body"]
    assert [
        (record.name, record.value_shape.type, record.content_type)
        for record in body
    ] == [
        ("title", "string", "application/json"),
        ("count", "number", "application/json"),
        ("published", "boolean", "application/json"),
        ("meta.tag", "string", "application/json"),
    ]
    payload = json.dumps([record.model_dump(mode="json") for record in body])
    assert "A book" not in payload
    assert '"new"' not in payload


def test_the_extractor_reads_form_urlencoded_body_attributes():
    records = extract_parameters(
        flow(
            "https://example.test/search",
            method="POST",
            content_type="application/x-www-form-urlencoded",
            request_body="q=hello&page=2",
        )
    )

    body = [record for record in records if record.location == "body"]
    assert [
        (record.name, record.value_shape.type, record.content_type)
        for record in body
    ] == [
        ("q", "string", "application/x-www-form-urlencoded"),
        ("page", "number", "application/x-www-form-urlencoded"),
    ]
    payload = json.dumps([record.model_dump(mode="json") for record in body])
    assert "hello" not in payload


def test_the_extractor_reads_multipart_field_names_as_shapes():
    boundary = "----crawl"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="title"\r\n\r\n'
        "A book\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="count"\r\n\r\n'
        "3\r\n"
        f"--{boundary}--\r\n"
    )
    records = extract_parameters(
        flow(
            "https://example.test/upload",
            method="POST",
            content_type=f"multipart/form-data; boundary={boundary}",
            request_body=body,
        )
    )

    body_records = [record for record in records if record.location == "body"]
    assert [
        (record.name, record.value_shape.type, record.content_type)
        for record in body_records
    ] == [
        ("title", "string", "multipart/form-data"),
        ("count", "number", "multipart/form-data"),
    ]
    payload = json.dumps([record.model_dump(mode="json") for record in body_records])
    assert "A book" not in payload


def test_a_query_and_a_body_parameter_of_the_same_name_stay_distinct():
    records = extract_parameters(
        flow(
            "https://example.test/api?q=query",
            method="POST",
            content_type="application/json",
            request_body='{"q": "body"}',
        )
    )

    assert [(record.name, record.location) for record in records] == [
        ("q", "query"),
        ("q", "body"),
    ]


def test_a_repeated_body_key_is_deduplicated_by_location_and_kind():
    records = extract_parameters(
        flow(
            "https://example.test/search",
            method="POST",
            content_type="application/x-www-form-urlencoded",
            request_body="q=first&q=second",
        )
    )

    body = [record for record in records if record.location == "body"]
    assert [(record.name, record.value_shape.type) for record in body] == [
        ("q", "string")
    ]
