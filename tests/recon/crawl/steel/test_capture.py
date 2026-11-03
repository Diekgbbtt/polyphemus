"""Seam under test: the passive `CaptureSidecar` through a fake CDP transport.

Spec: `docs/design/steel-crawl-spec.md` sections 2.5, 9.1, 9.2, 9.5, and 12;
seam 8 of `docs/design/steel-crawl-implementation-plan.md` section 3.

The fixture stream is one CLI-triggered XHR. The fake transport replays the
checked-in event stream and answers the body fetch, and it records every
command the sidecar sends, so passivity is asserted on the wire rather than
inferred from the implementation. Expected values come from the fixture pack
and the spec, never from re-running the sidecar.
"""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from polymerhus.recon.crawl.steel.capture.sidecar import (
    CaptureSidecar,
    CaptureUnavailable,
)
from tests.recon.crawl.steel.fixtures import CdpEvent, CdpStream, load_cdp
from tests.recon.crawl.steel.support import FakeCdpTransport

# The fixture's one XHR: the body the fake serves and the digest of its
# decoded bytes (spec 10.1: body hashes are over decoded bytes).
BODY = '{"items":["alpha","beta"],"page":2}'
BODY_BYTES = BODY.encode("utf-8")
BODY_SHA256 = hashlib.sha256(BODY_BYTES).hexdigest()


def request_event(request_id: str) -> CdpEvent:
    """One `requestWillBeSent` event for a synthetic flow."""
    return CdpEvent(
        method="Network.requestWillBeSent",
        params={
            "requestId": request_id,
            "request": {
                "url": f"https://example.test/{request_id}",
                "method": "GET",
                "headers": {},
                "resourceType": "XHR",
            },
            "frameId": "FRAME-1",
            "type": "XHR",
            "wallTime": 1762000000.5,
            "initiator": {"type": "script"},
        },
    )


def finished_event(request_id: str) -> CdpEvent:
    """One `loadingFinished` event for a synthetic flow."""
    return CdpEvent(
        method="Network.loadingFinished",
        params={"requestId": request_id, "timestamp": 1000.9, "encodedDataLength": 10},
    )


def two_flow_stream(bodies: dict[str, str]) -> CdpStream:
    """A stream with one request/finish pair per queued body, in dict order."""
    events = []
    for request_id in bodies:
        events.append(request_event(request_id))
        events.append(finished_event(request_id))
    return CdpStream(events=events, bodies=bodies)


def frame_event(request_id: str, payload: str) -> CdpEvent:
    return CdpEvent(
        method="Network.webSocketFrameReceived",
        params={
            "requestId": request_id,
            "timestamp": 2000.4,
            "response": {"opcode": 1, "mask": False, "payloadData": payload},
        },
    )


def test_a_long_request_url_is_capped_and_keeps_its_original_length():
    long_url = "https://example.test/" + "a1" * 3000
    event = CdpEvent(
        method="Network.requestWillBeSent",
        params={
            "requestId": "r-long",
            "request": {
                "url": long_url,
                "method": "GET",
                "headers": {},
                "resourceType": "XHR",
            },
            "frameId": "FRAME-1",
            "type": "XHR",
            "wallTime": 1762000000.5,
        },
    )
    transport = FakeCdpTransport(
        CdpStream(events=[event, finished_event("r-long")], bodies={})
    )
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    sidecar.pump()

    flow = sidecar.flows[0]
    assert len(flow.url) == 2048
    assert flow.url_truncated is True
    assert flow.url_original_length == len(long_url)


def test_a_large_websocket_frame_keeps_a_bounded_prefix_and_its_digest():
    payload = "x" * 100
    transport = FakeCdpTransport(
        CdpStream(events=[frame_event("2000.1", payload)], bodies={})
    )
    sidecar = CaptureSidecar(
        transport,
        max_realtime_payload_bytes=32,
        max_realtime_total_bytes=1024,
        max_realtime_frames=10,
    )
    sidecar.attach()

    sidecar.pump()

    record = sidecar.realtime[0]
    assert record.payload == "x" * 32
    assert record.payload_size == 100
    assert record.payload_sha256 == hashlib.sha256(payload.encode()).hexdigest()
    assert record.payload_truncated is True


def test_the_realtime_run_budget_and_frame_count_bound_the_evidence():
    events = [
        frame_event("2000.1", "a" * 8),
        frame_event("2000.1", "b" * 8),
        frame_event("2000.1", "c" * 8),
    ]
    transport = FakeCdpTransport(CdpStream(events=events, bodies={}))
    sidecar = CaptureSidecar(
        transport,
        max_realtime_payload_bytes=8,
        max_realtime_total_bytes=10,
        max_realtime_frames=2,
    )
    sidecar.attach()

    sidecar.pump()

    # Two frames are retained; the third is dropped at the frame cap.
    assert [record.payload for record in sidecar.realtime] == ["a" * 8, "b" * 2]
    assert sidecar.realtime[1].payload_size == 8
    assert sidecar.realtime[1].payload_truncated is True


def test_pump_records_the_fixture_xhr_flow_end_to_end():
    transport = FakeCdpTransport(load_cdp("http_flow"))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    flows = sidecar.pump()

    assert transport.sent_methods == [
        "Page.enable",
        "Network.enable",
        "Network.setCacheDisabled",
        "Runtime.enable",
        "Debugger.enable",
        "Network.getResponseBody",
    ]
    assert transport.sent[-1].params == {"requestId": "1000.1"}
    assert len(flows) == 1
    flow = flows[0]
    assert flow.request_id == "1000.1"
    assert flow.method == "GET"
    assert flow.url == "https://example.test/api/items?page=2"
    assert flow.status == 200
    assert flow.resource_type == "XHR"
    assert flow.frame_id == "FRAME-1"
    assert flow.request_headers == {"Accept": "application/json"}
    assert flow.response_headers == {"Content-Type": "application/json"}
    assert flow.mime_type == "application/json"
    assert flow.connection == "keep-alive"
    assert flow.http_version == "http/1.1"
    assert flow.encoded_data_length == 39
    assert flow.initiator == {
        "type": "script",
        "lineNumber": 0,
        "columnNumber": 61,
        "scriptId": "10",
    }
    assert flow.response_body == BODY_BYTES
    assert flow.response_body_sha256 == BODY_SHA256
    assert flow.body_original_size == len(BODY_BYTES)
    assert flow.body_truncated is False
    assert flow.body_truncation_reason is None
    assert flow.error is None
    assert flow.finished is True
    assert sidecar.flows == flows


def test_the_flow_carries_the_context_set_before_the_request():
    transport = FakeCdpTransport(load_cdp("http_flow"))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()
    sidecar.set_context("page-7", "action-3")

    flow = sidecar.pump()[0]

    assert flow.page_id == "page-7"
    assert flow.action_id == "action-3"
    assert flow.attribution == "action"
    # The context is read at request time; clearing it never rewrites a flow
    # that already started (spec 9.5).
    sidecar.clear_context()
    assert sidecar.flows[0].page_id == "page-7"
    assert sidecar.flows[0].attribution == "action"


def test_a_page_visit_without_an_action_is_page_attribution():
    transport = FakeCdpTransport(load_cdp("http_flow"))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()
    sidecar.set_context("page-7")

    flow = sidecar.pump()[0]

    assert flow.page_id == "page-7"
    assert flow.action_id is None
    assert flow.attribution == "page"


def test_an_unattributed_flow_keeps_unknown_attribution():
    sidecar = CaptureSidecar(FakeCdpTransport(load_cdp("http_flow")))
    sidecar.attach()

    flow = sidecar.pump()[0]

    assert flow.page_id is None
    assert flow.action_id is None
    assert flow.attribution == "unknown"


def test_a_small_response_cap_truncates_the_body_and_records_the_original_size():
    transport = FakeCdpTransport(load_cdp("http_flow"))
    sidecar = CaptureSidecar(transport, max_response_bytes=16)

    sidecar.attach()
    flow = sidecar.pump()[0]

    assert flow.response_body == BODY_BYTES[:16]
    assert flow.body_truncated is True
    assert flow.body_truncation_reason == "response_cap"
    assert flow.body_original_size == len(BODY_BYTES)
    # The store is keyed by what it actually retains, so the digest names the
    # truncated prefix rather than a body the store cannot return.
    assert flow.response_body_sha256 == hashlib.sha256(BODY_BYTES[:16]).hexdigest()
    assert sidecar.bodies.get(flow.response_body_sha256).data == BODY_BYTES[:16]


def test_the_run_cap_truncates_a_later_body_and_names_the_run_limit():
    first, second = "0123456789", "abcdefghij"
    sidecar = CaptureSidecar(
        FakeCdpTransport(two_flow_stream({"first": first, "second": second})),
        max_run_bytes=12,
    )

    sidecar.attach()
    flows = sidecar.pump()

    assert flows[0].response_body == first.encode("utf-8")
    assert flows[0].body_truncated is False
    assert flows[1].response_body == second.encode("utf-8")[:2]
    assert flows[1].body_truncated is True
    assert flows[1].body_truncation_reason == "run_cap"
    assert flows[1].body_original_size == len(second)
    assert sidecar.bodies.retained_bytes == 12


def test_the_same_body_is_stored_once_against_the_run_cap():
    same = "same-body"
    sidecar = CaptureSidecar(
        FakeCdpTransport(two_flow_stream({"first": same, "second": same})),
        max_run_bytes=len(same),
    )

    sidecar.attach()
    flows = sidecar.pump()

    assert [flow.response_body for flow in flows] == [same.encode("utf-8")] * 2
    assert [flow.response_body_sha256 for flow in flows] == [
        hashlib.sha256(same.encode("utf-8")).hexdigest()
    ] * 2
    assert sidecar.bodies.retained_bytes == len(same)


class UnreachableTransport:
    """A transport whose CDP target refuses every command."""

    def send(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        raise ConnectionError("connection refused")

    def replay(self) -> Iterator[Any]:
        return iter(())


def test_a_transport_that_cannot_attach_raises_capture_unavailable():
    sidecar = CaptureSidecar(UnreachableTransport())

    with pytest.raises(CaptureUnavailable) as excinfo:
        sidecar.attach()

    assert excinfo.value.code == "capture_unavailable"
    assert sidecar.attached is False


def test_pump_before_attach_fails_closed():
    sidecar = CaptureSidecar(FakeCdpTransport(load_cdp("http_flow")))

    with pytest.raises(CaptureUnavailable):
        sidecar.pump()


def test_a_body_fetch_failure_is_a_flow_error_not_a_capture_failure():
    stream = load_cdp("http_flow")
    transport = FakeCdpTransport(CdpStream(events=stream.events, bodies={}))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    flows = sidecar.pump()

    assert len(flows) == 1
    flow = flows[0]
    assert flow.finished is True
    assert flow.status == 200
    assert flow.response_body is None
    assert flow.response_body_sha256 is None
    assert "no body queued" in flow.error


def test_loading_failed_records_the_error_text_and_finishes_the_flow():
    transport = FakeCdpTransport(
        CdpStream(
            events=[
                request_event("failed-1"),
                CdpEvent(
                    method="Network.loadingFailed",
                    params={
                        "requestId": "failed-1",
                        "timestamp": 1001.0,
                        "type": "XHR",
                        "errorText": "net::ERR_CONNECTION_REFUSED",
                    },
                ),
            ]
        )
    )
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    flows = sidecar.pump()

    assert len(flows) == 1
    flow = flows[0]
    assert flow.error == "net::ERR_CONNECTION_REFUSED"
    assert flow.finished is True
    assert flow.status is None
    # A failed load has no body to fetch.
    assert "Network.getResponseBody" not in transport.sent_methods


def test_attach_enables_the_capture_domains_and_sends_no_action_method():
    transport = FakeCdpTransport(load_cdp("http_flow"))

    CaptureSidecar(transport).attach()

    assert transport.sent_methods == [
        "Page.enable",
        "Network.enable",
        "Network.setCacheDisabled",
        "Runtime.enable",
        "Debugger.enable",
    ]


class Base64Transport:
    """A transport whose body is base64-encoded, as CDP may return it."""

    def __init__(self, events: tuple[CdpEvent, ...], body: bytes) -> None:
        self._events = events
        self._body = body
        self.sent: list[str] = []

    def send(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        self.sent.append(method)
        if method == "Network.getResponseBody":
            return {
                "body": base64.b64encode(self._body).decode("ascii"),
                "base64Encoded": True,
            }
        return {}

    def replay(self) -> Iterator[CdpEvent]:
        yield from self._events


def test_a_base64_body_is_decoded_before_hashing():
    body = b"hello"
    transport = Base64Transport(
        (request_event("b64"), finished_event("b64")), body
    )
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    flow = sidecar.pump()[0]

    assert flow.response_body == body
    assert flow.response_body_sha256 == hashlib.sha256(body).hexdigest()


def test_a_non_body_resource_is_finished_without_a_body_fetch():
    stream = CdpStream(
        events=[
            CdpEvent(
                method="Network.requestWillBeSent",
                params={
                    "requestId": "img-1",
                    "request": {
                        "url": "https://example.test/cover.png",
                        "method": "GET",
                        "headers": {},
                        "resourceType": "Image",
                    },
                    "type": "Image",
                    "wallTime": 1762000000.5,
                },
            ),
            finished_event("img-1"),
        ]
    )
    transport = FakeCdpTransport(stream)
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    flow = sidecar.pump()[0]

    assert flow.resource_type == "Image"
    assert flow.finished is True
    assert flow.response_body is None
    assert flow.response_body_sha256 is None
    assert flow.error is None
    assert "Network.getResponseBody" not in transport.sent_methods
