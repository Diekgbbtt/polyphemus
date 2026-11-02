"""Seam under test: the CDP event-stream fixtures.

Each stream is an ordered replay of the events one capture concern consumes,
plus the response bodies the sidecar fetches on `loadingFinished`.
"""
from __future__ import annotations

import json

import pytest

from tests.recon.crawl.steel.fixtures import CdpStream, FixtureError, load_cdp


def _methods(stream):
    return [event.method for event in stream.events]


def test_load_cdp_returns_a_typed_ordered_stream():
    stream = load_cdp("http_flow")

    assert isinstance(stream, CdpStream)
    assert _methods(stream) == [
        "Network.requestWillBeSent",
        "Network.responseReceived",
        "Network.loadingFinished",
    ]
    assert stream.events[0].params["request"]["url"] == "https://example.test/api/items?page=2"


def test_http_flow_pairs_the_loading_finished_event_with_its_body():
    stream = load_cdp("http_flow")
    request_id = stream.events[2].params["requestId"]

    assert request_id == "1000.1"
    assert json.loads(stream.bodies[request_id]) == {"items": ["alpha", "beta"], "page": 2}


def test_realtime_stream_covers_handshake_and_both_frame_directions():
    stream = load_cdp("realtime")

    assert _methods(stream) == [
        "Network.webSocketCreated",
        "Network.webSocketWillSendHandshakeRequest",
        "Network.webSocketHandshakeResponseReceived",
        "Network.webSocketFrameSent",
        "Network.webSocketFrameReceived",
        "Network.webSocketClosed",
    ]
    handshake = stream.events[2].params["response"]
    assert handshake["status"] == 101


def test_browser_stream_covers_script_frame_and_dialog():
    stream = load_cdp("browser")

    assert _methods(stream) == [
        "Debugger.scriptParsed",
        "Page.frameNavigated",
        "Page.javascriptDialogOpening",
    ]
    script, frame, dialog = (event.params for event in stream.events)
    assert script["url"] == "https://example.test/static/app.js"
    assert frame["frame"]["url"] == "https://example.test/products"
    assert dialog["type"] == "confirm"


def test_cdp_fixture_with_non_list_events_fails_loudly(tmp_path):
    path = tmp_path / "cdp" / "broken.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"events": {"method": "Page.enable"}}), encoding="utf-8")

    with pytest.raises(FixtureError, match="CdpStream") as excinfo:
        load_cdp("broken", root=tmp_path)

    assert "events" in str(excinfo.value)
