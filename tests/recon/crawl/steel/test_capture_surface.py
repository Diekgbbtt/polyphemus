"""Seam under test: the capture surface beyond the HTTP flow.

Spec: `docs/design/steel-crawl-spec.md` sections 2.5, 9.2, 9.3, and 9.4;
seam 8 of `docs/design/steel-crawl-implementation-plan.md` section 3.

The WebSocket handshake is an HTTP artifact, both frame directions are realtime
records, `Debugger.scriptParsed` becomes a `ScriptAsset` with an absolute URL,
`Page.frameNavigated` records the frame, an HTTP/3 flow keeps `http_version=h3`,
and a JavaScript dialog is auto-dismissed with the configured prompt text. No
source-map request is ever issued.
"""
from __future__ import annotations

from polymerhus.recon.crawl.steel.capture.sidecar import CaptureSidecar
from tests.recon.crawl.steel.fixtures import CdpStream, load_cdp
from tests.recon.crawl.steel.support import FakeCdpTransport


def test_the_websocket_handshake_is_an_http_flow_and_both_frame_directions_are_kept():
    transport = FakeCdpTransport(load_cdp("realtime"))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    flows = sidecar.pump()

    assert [flow.resource_type for flow in flows] == ["WebSocket"]
    handshake = flows[0]
    assert handshake.url == "wss://example.test/socket"
    assert handshake.method == "GET"
    assert handshake.status == 101
    assert handshake.finished is True
    assert handshake.response_headers == {
        "Upgrade": "websocket",
        "Connection": "Upgrade",
    }
    assert "Network.getResponseBody" not in transport.sent_methods

    assert [record.kind for record in sidecar.realtime] == [
        "websocket_created",
        "handshake_request",
        "handshake_response",
        "frame_sent",
        "frame_received",
        "closed",
    ]
    sent, received = sidecar.realtime[3], sidecar.realtime[4]
    assert (sent.direction, sent.opcode, sent.payload) == (
        "sent",
        1,
        '{"subscribe":"items"}',
    )
    assert (received.direction, received.opcode, received.payload) == (
        "received",
        1,
        '{"event":"ready"}',
    )


def test_a_parsed_script_becomes_an_asset_without_fetching_its_source_map():
    transport = FakeCdpTransport(load_cdp("browser"))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    sidecar.pump()

    assert len(sidecar.scripts) == 1
    script = sidecar.scripts[0]
    assert script.script_url == "https://example.test/static/app.js"
    assert script.script_id == "10"
    assert script.provenance == "debugger"
    assert all("source" not in url and ".map" not in url for url in [script.script_url])
    assert "Network.getResponseBody" not in transport.sent_methods


def test_a_frame_navigation_records_the_frame_url_and_parent():
    transport = FakeCdpTransport(load_cdp("browser"))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    sidecar.pump()

    assert len(sidecar.frames) == 1
    frame = sidecar.frames[0]
    assert frame.frame_id == "FRAME-1"
    assert frame.url == "https://example.test/products"
    assert frame.parent_frame_id is None


def test_a_javascript_dialog_is_auto_dismissed_and_recorded():
    transport = FakeCdpTransport(load_cdp("browser"))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    sidecar.pump()

    assert len(sidecar.dialogs) == 1
    dialog = sidecar.dialogs[0]
    assert dialog.message == "Discard changes?"
    assert dialog.dialog_type == "confirm"
    command = transport.sent[-1]
    assert command.method == "Page.handleJavaScriptDialog"
    assert command.params == {"accept": True, "promptText": "test"}
    assert not any(
        method.startswith(("Page.navigate", "Input.", "DOM."))
        for method in transport.sent_methods
    )


def test_an_http_3_flow_keeps_the_h3_version():
    stream = load_cdp("http_flow")
    events = []
    for event in stream.events:
        if event.method == "Network.responseReceived":
            response = dict(event.params["response"])
            response["protocol"] = "h3"
            params = dict(event.params)
            params["response"] = response
            events.append(type(event)(method=event.method, params=params))
        else:
            events.append(event)
    transport = FakeCdpTransport(CdpStream(events=events, bodies=stream.bodies))
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    flow = sidecar.pump()[0]

    assert flow.http_version == "h3"


def test_a_duplicate_script_url_is_recorded_once():
    stream = load_cdp("browser")
    script_event = stream.events[0]
    transport = FakeCdpTransport(
        CdpStream(events=[script_event, script_event], bodies={})
    )
    sidecar = CaptureSidecar(transport)
    sidecar.attach()

    sidecar.pump()

    assert len(sidecar.scripts) == 1
