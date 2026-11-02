"""Seam under test: the fake CDP transport the capture sidecar will call.

The fake replays a checked-in event stream in order, answers the body fetch,
and records every command the consumer sends so a test can assert the sidecar
stayed passive.
"""
from __future__ import annotations

import pytest

from tests.recon.crawl.steel.fixtures import load_cdp
from tests.recon.crawl.steel.support import FakeCdpTransport

BODY = '{"items":["alpha","beta"],"page":2}'


def test_replay_yields_the_ordered_event_stream():
    transport = FakeCdpTransport(load_cdp("http_flow"))

    assert [event.method for event in transport.replay()] == [
        "Network.requestWillBeSent",
        "Network.responseReceived",
        "Network.loadingFinished",
    ]


def test_send_returns_an_empty_result_for_a_control_command_and_records_it():
    transport = FakeCdpTransport(load_cdp("http_flow"))

    assert transport.send("Network.enable") == {}
    assert transport.sent_methods == ["Network.enable"]


def test_send_records_every_method_and_params_in_order():
    transport = FakeCdpTransport(load_cdp("http_flow"))

    transport.send("Page.enable")
    transport.send("Runtime.enable", {"maxDepth": 4})

    assert transport.sent_methods == ["Page.enable", "Runtime.enable"]
    assert transport.sent[0].params == {}
    assert transport.sent[1].params == {"maxDepth": 4}


def test_get_response_body_serves_the_fixture_body():
    transport = FakeCdpTransport(load_cdp("http_flow"))

    result = transport.send("Network.getResponseBody", {"requestId": "1000.1"})

    assert result == {"body": BODY, "base64Encoded": False}
    assert transport.sent_methods == ["Network.getResponseBody"]


def test_get_response_body_for_an_unknown_request_fails_loudly():
    transport = FakeCdpTransport(load_cdp("http_flow"))

    with pytest.raises(KeyError, match="missing"):
        transport.send("Network.getResponseBody", {"requestId": "missing"})
