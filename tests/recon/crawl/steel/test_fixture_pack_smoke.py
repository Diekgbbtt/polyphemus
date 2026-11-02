"""Smoke test: the pack imports and drives one synthetic crawl exchange.

No production steel-crawl module exists yet. This test proves the fixture pack
and the fake seams compose through their public surfaces, which is what every
later ticket builds on.
"""
from __future__ import annotations

from tests.recon.crawl.steel import fixtures, support


def test_fixture_pack_drives_one_fake_session_and_one_fake_cdp_exchange():
    exec_fn = support.FakeExecFn()
    exec_fn.queue(fixtures.load_cli("session"), fixtures.load_cli("stop"))
    session_command = [
        "steel",
        "browser",
        "sessions",
        "get",
        "--session",
        "crawl-fixture",
        "--json",
    ]

    session = exec_fn(session_command)
    stop = exec_fn(["steel", "browser", "stop", "--session", "crawl-fixture", "--json"])

    assert session["data"]["id"] == "9f8e7d6c-5b4a-4321-8765-fedcba987654"
    assert stop["data"]["stoppedSessions"] == ["crawl-fixture"]
    assert exec_fn.commands == [
        session_command,
        ["steel", "browser", "stop", "--session", "crawl-fixture", "--json"],
    ]

    transport = support.FakeCdpTransport(fixtures.load_cdp("http_flow"))
    transport.send("Page.enable")
    transport.send("Network.enable")
    events = list(transport.replay())
    body = transport.send("Network.getResponseBody", {"requestId": "1000.1"})

    assert [event.method for event in events] == [
        "Network.requestWillBeSent",
        "Network.responseReceived",
        "Network.loadingFinished",
    ]
    assert body["body"] == '{"items":["alpha","beta"],"page":2}'
    assert transport.sent_methods == [
        "Page.enable",
        "Network.enable",
        "Network.getResponseBody",
    ]
