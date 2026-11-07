"""Seam under test: the crawl's raw CDP transport.

A real local WebSocket server stands in for the worker's CDP proxy. The
transport must connect its socket to the container address but present the
worker's localhost Host, because Chrome rejects any other Host.
"""
from __future__ import annotations

import json
import socket
import threading

import pytest

from polymerhus.recon.crawl.steel.live import LiveCdpTransport, LiveCrawlError


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class _CdpServer:
    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.methods: list[str] = []
        self.session_ids: list[str | None] = []
        self.port = _free_port()
        self._server = None
        self._thread = None

    def __enter__(self):
        from websockets.sync.server import serve

        def handler(connection):
            self.hosts.append(connection.request.headers["Host"])
            for raw in connection:
                message = json.loads(raw)
                self.methods.append(message["method"])
                self.session_ids.append(message.get("sessionId"))
                method = message["method"]
                if method == "Target.getTargets":
                    result = {
                        "targetInfos": [
                            {
                                "type": "page",
                                "targetId": "target-1",
                                "url": "https://app.test/",
                            }
                        ]
                    }
                elif method == "Target.attachToTarget":
                    result = {"sessionId": "session-1"}
                elif method == "Fail.command":
                    connection.send(
                        json.dumps(
                            {
                                "id": message["id"],
                                "error": {"message": "the command failed"},
                            }
                        )
                    )
                    continue
                else:
                    result = {}
                connection.send(json.dumps({"id": message["id"], "result": result}))

        self._server = serve(handler, "127.0.0.1", self.port)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._thread.join(timeout=5)
        return None


def test_transport_connects_lazily_through_the_container_socket_with_localhost_host():
    with _CdpServer() as server:
        transport = LiveCdpTransport(
            lambda: (f"ws://127.0.0.1:{server.port}/", f"localhost:{server.port}")
        )
        try:
            transport.send("Page.enable")
        finally:
            transport.close()

    assert server.hosts == [f"localhost:{server.port}"]
    assert server.methods == [
        "Target.getTargets",
        "Target.attachToTarget",
        "Page.enable",
    ]
    assert server.session_ids == [None, None, "session-1"]
    assert transport.session_id == "session-1"


def test_transport_does_not_connect_before_the_endpoint_exists():
    calls: list[int] = []

    def endpoint():
        calls.append(1)
        return None

    transport = LiveCdpTransport(endpoint)

    with pytest.raises(LiveCrawlError):
        transport.send("Page.enable")
    assert calls == [1]
    transport.close()


def test_transport_close_before_connect_is_a_noop():
    transport = LiveCdpTransport(lambda: None)

    transport.close()
    transport.close()


def test_transport_surfaces_a_cdp_error():
    with _CdpServer() as server:
        transport = LiveCdpTransport(
            lambda: (f"ws://127.0.0.1:{server.port}/", f"localhost:{server.port}")
        )
        try:
            with pytest.raises(LiveCrawlError, match="the command failed"):
                transport.send("Fail.command")
        finally:
            transport.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        ("not-a-url", "localhost:3000"),
        ("http://127.0.0.1:3000/", "localhost:3000"),
        ("ws://127.0.0.1:3000/", ""),
        ("ws://127.0.0.1:3000/", "http://localhost"),
    ],
)
def test_transport_rejects_an_invalid_endpoint(endpoint):
    transport = LiveCdpTransport(lambda: endpoint)

    with pytest.raises(LiveCrawlError):
        transport.send("Page.enable")
    transport.close()
