"""Unit tier: the per-replica loopback reverse proxy.

A real local HTTP server and a real local WebSocket server stand in for the
Steel worker. The proxy owns one loopback port, forwards both protocols to the
worker's container address, keeps the client's Host, and rewrites the session
create response's `websocketUrl`.
"""
from __future__ import annotations

import json
import socket
import socketserver
import threading
import time

import pytest

from kali.steel_pool.pool import Worker
from kali.steel_pool.proxy import ProxyError, WorkerProxy


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class _RawHTTPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.server.record = getattr(self.server, "record", [])
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length") or 0)
        body = rest
        while len(body) < length:
            chunk = self.request.recv(4096)
            if not chunk:
                break
            body += chunk
        self.server.record.append(
            {
                "method": method,
                "path": path,
                "headers": headers,
                "body": body[:length],
            }
        )
        response = self.server.response(method, path, headers, body[:length])
        self.request.sendall(response)
        try:
            self.request.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class _HTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_http(response):
    server = _HTTPServer(("127.0.0.1", 0), _RawHTTPHandler)
    server.response = response
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_http(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def fixed_response(body: bytes, status: str = "200 OK", content_type="application/json"):
    return (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("latin-1") + body


def raw_request(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def parse_response(raw: bytes) -> tuple[int, dict[str, str], bytes]:
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return status, headers, body


def _worker(upstream_port: int, public_port: int) -> Worker:
    return Worker(
        container_id="c1",
        container_name="steel-worker-1",
        container_ip="127.0.0.1",
        public_port=public_port,
        api_port=upstream_port,
    )


@pytest.fixture
def proxy_factory():
    created: list[WorkerProxy] = []

    def make(upstream_port: int, *, public_port: int | None = None):
        proxy = WorkerProxy(
            _worker(upstream_port, public_port or free_port())
        )
        proxy.start()
        created.append(proxy)
        return proxy

    yield make
    for proxy in created:
        proxy.stop()


def test_proxy_forwards_http_and_keeps_the_client_host(proxy_factory):
    server, thread = start_http(lambda *_: fixed_response(b'{"ok":true}'))
    proxy = proxy_factory(server.server_address[1])
    try:
        raw = raw_request(
            proxy.port,
            (
                "GET /v1/health HTTP/1.1\r\n"
                f"Host: localhost:{proxy.port}\r\n"
                "Connection: keep-alive\r\n\r\n"
            ).encode("latin-1"),
        )
    finally:
        stop_http(server, thread)

    status, _, body = parse_response(raw)
    assert status == 200
    assert json.loads(body) == {"ok": True}
    recorded = server.record[0]
    assert recorded["method"] == "GET"
    assert recorded["path"] == "/v1/health"
    assert recorded["headers"]["host"] == f"localhost:{proxy.port}"
    assert recorded["headers"]["connection"] == "close"


def test_proxy_forwards_a_post_body(proxy_factory):
    server, thread = start_http(lambda *_: fixed_response(b'{"ok":true}'))
    proxy = proxy_factory(server.server_address[1])
    payload = b'{"name":"crawl-fixture"}'
    try:
        raw_request(
            proxy.port,
            (
                "POST /v1/sessions HTTP/1.1\r\n"
                f"Host: localhost:{proxy.port}\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Content-Type: application/json\r\n\r\n"
            ).encode("latin-1")
            + payload,
        )
    finally:
        stop_http(server, thread)

    assert server.record[0]["body"] == payload


def test_proxy_rewrites_the_session_create_websocket_url(proxy_factory):
    payload = json.dumps(
        {
            "id": "steel-1",
            "name": "crawl-fixture",
            "websocketUrl": "ws://172.20.0.5:3000/v1/sessions/steel-1",
            "status": "live",
        }
    ).encode()

    def response(*_):
        return fixed_response(payload)

    server, thread = start_http(response)
    proxy = proxy_factory(server.server_address[1])
    try:
        raw = raw_request(
            proxy.port,
            (
                "POST /v1/sessions HTTP/1.1\r\n"
                f"Host: localhost:{proxy.port}\r\n"
                "Content-Length: 0\r\n\r\n"
            ).encode("latin-1"),
        )
    finally:
        stop_http(server, thread)

    _, headers, body = parse_response(raw)
    data = json.loads(body)
    assert data["websocketUrl"] == f"ws://localhost:{proxy.port}/"
    assert data["id"] == "steel-1"
    assert int(headers["content-length"]) == len(body)


def test_proxy_leaves_other_json_and_non_json_bodies_alone(proxy_factory):
    def response(method, path, headers, body):
        if path == "/v1/sessions":
            return fixed_response(b'{"websocketUrl":"ws://x/"}\n')
        return fixed_response(b"not-json", content_type="text/plain")

    server, thread = start_http(response)
    proxy = proxy_factory(server.server_address[1])
    try:
        sessions = parse_response(
            raw_request(
                proxy.port,
                (
                    "GET /v1/sessions HTTP/1.1\r\n"
                    f"Host: localhost:{proxy.port}\r\n\r\n"
                ).encode("latin-1"),
            )
        )
        other = parse_response(
            raw_request(
                proxy.port,
                (
                    "GET /other HTTP/1.1\r\n"
                    f"Host: localhost:{proxy.port}\r\n\r\n"
                ).encode("latin-1"),
            )
        )
    finally:
        stop_http(server, thread)

    assert json.loads(sessions[2])["websocketUrl"] == f"ws://localhost:{proxy.port}/"
    assert other[2] == b"not-json"


def test_proxy_dechunks_a_chunked_response(proxy_factory):
    def response(*_):
        return (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
            b"7\r\n{\"id\":1\r\n"
            b"2\r\n}\n\r\n"
            b"0\r\n\r\n"
        )

    server, thread = start_http(response)
    proxy = proxy_factory(server.server_address[1])
    try:
        raw = raw_request(
            proxy.port,
            (
                "GET /v1/sessions HTTP/1.1\r\n"
                f"Host: localhost:{proxy.port}\r\n\r\n"
            ).encode("latin-1"),
        )
    finally:
        stop_http(server, thread)

    status, headers, body = parse_response(raw)
    assert status == 200
    assert "transfer-encoding" not in headers
    assert int(headers["content-length"]) == len(body)
    assert json.loads(body) == {"id": 1}


def test_proxy_reports_an_unreachable_upstream(proxy_factory):
    proxy = proxy_factory(free_port())

    raw = raw_request(
        proxy.port,
        (
            "GET /v1/health HTTP/1.1\r\n"
            f"Host: localhost:{proxy.port}\r\n\r\n"
        ).encode("latin-1"),
    )

    status, _, body = parse_response(raw)
    assert status == 502
    assert json.loads(body)["error"]["code"] == "proxy_upstream_unavailable"


def test_proxy_forwards_a_websocket_and_keeps_the_host(proxy_factory):
    from websockets.sync.server import serve

    hosts: list[str] = []

    def handler(connection):
        hosts.append(connection.request.headers["Host"])
        for message in connection:
            connection.send(f"echo:{message}")

    upstream_port = free_port()
    server = serve(handler, "127.0.0.1", upstream_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy = proxy_factory(upstream_port)
    try:
        from websockets.sync.client import connect

        sock = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
        with connect(
            f"ws://localhost:{proxy.port}/",
            sock=sock,
            proxy=None,
            open_timeout=5,
        ) as connection:
            connection.send("hello")
            assert connection.recv(timeout=5) == "echo:hello"
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert hosts == [f"localhost:{proxy.port}"]


def test_proxy_start_and_stop_release_the_port(proxy_factory):
    port = free_port()
    proxy = proxy_factory(free_port(), public_port=port)
    proxy.stop()

    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.1", "", "   "])
def test_proxy_rejects_a_non_loopback_bind(host):
    with pytest.raises(ValueError):
        WorkerProxy(_worker(3000, 3100), bind_host=host)


def test_proxy_rejects_a_second_start():
    proxy = WorkerProxy(_worker(3000, free_port()))
    proxy.start()
    try:
        with pytest.raises(ProxyError):
            proxy.start()
    finally:
        proxy.stop()
