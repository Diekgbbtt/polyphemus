"""HTTPFlow normalization preserves the wire truth (fake flows, no mitmproxy)."""
from __future__ import annotations

from kali.http_history.models import CaptureContext
from kali.http_history.normalize import normalize_flow
from tests.kali.fakes import FakeError, FakeFlow, FakeMessage


def _context(**overrides):
    base = dict(session_id="s1", run_id="r1", spec_id="spec", variant_ref="v0", exec_id="e1")
    base.update(overrides)
    return CaptureContext(**base)


def test_duplicate_headers_and_order_are_preserved():
    flow = FakeFlow(
        request=FakeMessage(
            method="POST",
            url="https://target.example/login",
            headers=[["content-type", "application/json"], ["x-dup", "a"], ["x-dup", "b"]],
        )
    )
    artifact, _bodies = normalize_flow(flow, project_id="proj-1", capture_context=_context())
    assert artifact.request.headers == [
        ("content-type", "application/json"),
        ("x-dup", "a"),
        ("x-dup", "b"),
    ]


def test_cookies_and_query_are_additive_while_headers_survive():
    flow = FakeFlow(
        request=FakeMessage(
            url="https://target.example/search?q=1&q=2&page=3",
            headers=[["cookie", "sid=abc; theme=dark"]],
        )
    )
    artifact, _ = normalize_flow(flow, project_id="proj-1", capture_context=_context())
    assert ("cookie", "sid=abc; theme=dark") in artifact.request.headers
    assert {(c.name, c.value) for c in artifact.request.cookies} == {
        ("sid", "abc"),
        ("theme", "dark"),
    }
    assert [(q.name, q.value) for q in artifact.request.query] == [
        ("q", "1"),
        ("q", "2"),
        ("page", "3"),
    ]


def test_form_values_are_parsed_from_urlencoded_body():
    flow = FakeFlow(
        request=FakeMessage(
            method="POST",
            url="https://target.example/login",
            headers=[["content-type", "application/x-www-form-urlencoded"]],
            content=b"user=alice&pass=hunter2",
        )
    )
    artifact, bodies = normalize_flow(flow, project_id="proj-1", capture_context=_context())
    assert [(f.name, f.value) for f in artifact.request.form] == [
        ("user", "alice"),
        ("pass", "hunter2"),
    ]
    assert bodies[artifact.request.body_ref] == b"user=alice&pass=hunter2"
    assert artifact.request.capture_state == "captured"


def test_binary_body_is_stored_without_heuristic_decoding():
    payload = b"\x00\x01\x02\xff"
    flow = FakeFlow(
        request=FakeMessage(method="POST", content=payload),
        response=FakeMessage(status=200, reason="OK", content=payload),
    )
    artifact, bodies = normalize_flow(flow, project_id="proj-1", capture_context=_context())
    assert artifact.request.body_encoding == "binary"
    assert artifact.response.body_encoding == "binary"
    assert bodies[artifact.request.body_ref] == payload


def test_oversized_body_is_omitted_with_state_size_hash_and_reason():
    payload = b"x" * 4096
    flow = FakeFlow(request=FakeMessage(method="POST", content=payload))
    artifact, bodies = normalize_flow(
        flow, project_id="proj-1", capture_context=_context(), max_body_bytes=1024
    )
    assert artifact.request.capture_state == "omitted"
    assert artifact.request.body_ref is None
    assert artifact.request.body_size == 4096
    assert artifact.request.body_hash and len(artifact.request.body_hash) == 64
    assert "limit" in (artifact.request.capture_reason or "")
    assert bodies == {}


def test_flow_without_response_records_a_structured_error():
    flow = FakeFlow(
        request=FakeMessage(method="GET", url="https://target.example/"),
        response=None,
        error=FakeError("TLS handshake failed"),
    )
    artifact, _ = normalize_flow(flow, project_id="proj-1", capture_context=_context())
    assert artifact.response is None
    assert artifact.error is not None
    assert artifact.error.message == "TLS handshake failed"


def test_redirect_and_duplicate_requests_are_distinct_artifacts():
    redirect = FakeFlow(
        request=FakeMessage(method="GET", url="https://target.example/old"),
        response=FakeMessage(status=302, reason="Found", headers=[["location", "/new"]]),
    )
    duplicate = FakeFlow(
        request=FakeMessage(method="GET", url="https://target.example/old"),
        response=FakeMessage(status=302, reason="Found", headers=[["location", "/new"]]),
    )
    first, _ = normalize_flow(redirect, project_id="proj-1", capture_context=_context())
    second, _ = normalize_flow(duplicate, project_id="proj-1", capture_context=_context())
    assert first.artifact_id != second.artifact_id
    assert first.response.status == 302


def test_timing_and_connection_metadata_are_recorded():
    flow = FakeFlow(
        request=FakeMessage(timestamp_start=100.0, timestamp_end=100.0),
        response=FakeMessage(status=200, reason="OK", timestamp_start=100.01, timestamp_end=100.05),
    )
    artifact, _ = normalize_flow(flow, project_id="proj-1", capture_context=_context())
    assert artifact.timings.total_ms > 0
    assert artifact.connection.client_address == "172.30.0.2:40000"
    assert artifact.connection.server_address == "93.184.216.34:443"
    assert artifact.connection.tls is True
    assert artifact.connection.sni == "target.example"
    assert artifact.connection.alpn == "h2"


def test_response_set_cookie_is_parsed_and_raw_header_kept():
    flow = FakeFlow(
        response=FakeMessage(
            status=200,
            reason="OK",
            headers=[["set-cookie", "sid=abc; Path=/"], ["set-cookie", "theme=dark; Path=/"]],
        )
    )
    artifact, _ = normalize_flow(flow, project_id="proj-1", capture_context=_context())
    assert {(c.name, c.value) for c in artifact.response.cookies} == {
        ("sid", "abc"),
        ("theme", "dark"),
    }
    assert ("set-cookie", "sid=abc; Path=/") in artifact.response.headers
