"""Unit tier: Steel pool discovery over the operator's Docker socket.

The Docker API is faked at the JSON boundary. The Unix-socket transport is
tested against a real local socket, so no Docker daemon and no Steel worker is
needed. The pool manager never creates, starts, stops, or removes a container.
"""
from __future__ import annotations

import json
import shutil
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from kali.steel_pool.docker_api import DockerAPIError, DockerUnixClient
from kali.steel_pool.pool import (
    Worker,
    WorkerRegistry,
    check_worker_health,
    discover_workers,
    parse_worker,
)

LABEL = "polymerhus.steel-pool=true"


def _container(
    container_id: str = "abc123def456",
    name: str = "/steel-worker-1",
    public_port: int | None = 55001,
    private_port: int = 3000,
    ip: str = "127.0.0.1",
    port_type: str = "tcp",
) -> dict:
    ports = []
    if public_port is not None:
        ports.append(
            {
                "IP": ip,
                "PrivatePort": private_port,
                "PublicPort": public_port,
                "Type": port_type,
            }
        )
    return {"Id": container_id, "Names": [name], "Ports": ports}


class _FakeDocker:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict | None]] = []

    def get_json(self, path: str, query: dict | None = None):
        self.calls.append((path, query))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _start_unix_server(socket_path, body: bytes, status: str = "200 OK"):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    record: dict = {}

    def serve() -> None:
        try:
            connection, _ = server.accept()
            with connection:
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                record["request"] = data.decode("latin-1")
                headers = (
                    f"HTTP/1.1 {status}\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n\r\n"
                )
                connection.sendall(headers.encode("latin-1") + body)
        finally:
            server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return record, thread


@pytest.fixture
def short_socket():
    """A Unix socket path short enough for the platform's AF_UNIX limit."""
    directory = Path(tempfile.mkdtemp(prefix="steel-pool-"))
    try:
        yield directory / "d.sock"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_unix_client_reads_json_over_a_real_socket(short_socket):
    body = json.dumps([{"Id": "abc"}]).encode()
    record, thread = _start_unix_server(short_socket, body)

    payload = DockerUnixClient(short_socket, timeout=2).get_json(
        "/containers/json", query={"filters": '{"label":["x"]}'}
    )
    thread.join(timeout=5)

    assert payload == [{"Id": "abc"}]
    request_line = record["request"].split("\r\n", 1)[0]
    assert request_line.startswith("GET /containers/json?")
    query = parse_qs(urlsplit(request_line.split(" ")[1]).query)
    assert query["filters"] == ['{"label":["x"]}']


def test_unix_client_wraps_a_missing_socket(short_socket):
    client = DockerUnixClient(short_socket, timeout=0.5)

    with pytest.raises(DockerAPIError):
        client.get_json("/containers/json")


def test_unix_client_wraps_an_http_error(short_socket):
    record, thread = _start_unix_server(
        short_socket, b'{"message":"boom"}', status="500 Internal Server Error"
    )

    with pytest.raises(DockerAPIError) as caught:
        DockerUnixClient(short_socket, timeout=2).get_json("/containers/json")
    thread.join(timeout=5)

    assert caught.value.status_code == 500
    assert "boom" in str(caught.value)


def test_unix_client_wraps_invalid_json(short_socket):
    record, thread = _start_unix_server(short_socket, b"not-json")

    with pytest.raises(DockerAPIError):
        DockerUnixClient(short_socket, timeout=2).get_json("/containers/json")
    thread.join(timeout=5)


def test_unix_client_exposes_no_container_write_methods(tmp_path):
    client = DockerUnixClient(tmp_path / "docker.sock")

    assert not hasattr(client, "post")
    assert not hasattr(client, "put")
    assert not hasattr(client, "delete")
    assert not hasattr(client, "request")


def test_parse_worker_builds_the_loopback_url():
    worker = parse_worker(_container(public_port=55001))

    assert worker == Worker(
        container_id="abc123def456",
        container_name="steel-worker-1",
        api_port=55001,
    )
    assert worker.url == "http://localhost:55001"


def test_parse_worker_builds_a_configured_host_url():
    worker = parse_worker(
        _container(public_port=55001), worker_host="host.docker.internal"
    )

    assert worker.host == "host.docker.internal"
    assert worker.url == "http://host.docker.internal:55001"


def test_discover_uses_the_configured_worker_host():
    client = _FakeDocker([_container()])

    workers = discover_workers(
        client, LABEL, worker_host="host.docker.internal"
    )

    assert [worker.url for worker in workers] == [
        "http://host.docker.internal:55001"
    ]


def test_parse_worker_skips_an_unpublished_api_port():
    assert parse_worker(_container(public_port=None)) is None


def test_parse_worker_skips_another_private_port():
    payload = _container(public_port=9223, private_port=9222)

    assert parse_worker(payload) is None


def test_parse_worker_skips_a_non_tcp_mapping():
    assert parse_worker(_container(port_type="udp")) is None


def test_parse_worker_prefers_the_loopback_binding():
    payload = _container()
    payload["Ports"] = [
        {"IP": "0.0.0.0", "PrivatePort": 3000, "PublicPort": 55001, "Type": "tcp"},
        {"IP": "127.0.0.1", "PrivatePort": 3000, "PublicPort": 55002, "Type": "tcp"},
    ]

    worker = parse_worker(payload)

    assert worker.api_port == 55002


def test_parse_worker_uses_the_short_id_when_the_name_is_missing():
    worker = parse_worker({"Id": "abc123def4567890", "Names": [], "Ports": [
        {"IP": "127.0.0.1", "PrivatePort": 3000, "PublicPort": 55001, "Type": "tcp"}
    ]})

    assert worker.container_name == "abc123def456"


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-container",
        {"Names": ["/x"], "Ports": []},
        {"Id": "abc", "Names": ["/x"], "Ports": "bad"},
        {"Id": "abc", "Names": ["/x"], "Ports": ["bad"]},
    ],
)
def test_parse_worker_rejects_malformed_payloads(payload):
    with pytest.raises(DockerAPIError):
        parse_worker(payload)


def test_discover_reads_the_label_filter():
    client = _FakeDocker([_container()])

    workers = discover_workers(client, LABEL)

    assert len(workers) == 1
    path, query = client.calls[0]
    assert path == "/containers/json"
    assert json.loads(query["filters"]) == {"label": [LABEL]}


def test_discover_returns_an_empty_list_without_containers():
    assert discover_workers(_FakeDocker([]), LABEL) == []


def test_discover_rejects_a_non_list_payload():
    with pytest.raises(DockerAPIError):
        discover_workers(_FakeDocker({"Id": "abc"}), LABEL)


def test_discover_wraps_a_client_failure():
    with pytest.raises(DockerAPIError):
        discover_workers(_FakeDocker(DockerAPIError("down")), LABEL)


def _health_server(status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status":"ok"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_health_check_accepts_a_2xx_response():
    server, thread = _health_server(200)
    worker = Worker("abc", "worker-1", server.server_address[1])
    try:
        assert check_worker_health(worker, timeout_s=2) is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_health_check_rejects_a_5xx_response():
    server, thread = _health_server(500)
    worker = Worker("abc", "worker-1", server.server_address[1])
    try:
        assert check_worker_health(worker, timeout_s=2) is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_health_check_rejects_a_closed_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    worker = Worker("abc", "worker-1", port)

    assert check_worker_health(worker, timeout_s=0.2) is False


def _registry(client, size: int = 2, health=None, events=None):
    health = health or {}
    events = events if events is not None else []
    registry = WorkerRegistry(
        client,
        LABEL,
        size,
        health_timeout_s=0.01,
        health_check=lambda worker, timeout: health.get(worker.container_id, True),
        emit=lambda event, **fields: events.append((event, fields)),
    )
    return registry, events


def test_registry_reports_a_full_healthy_pool():
    client = _FakeDocker([_container("a", "/w1", 55001), _container("b", "/w2", 55002)])
    registry, events = _registry(client, size=2)

    report = registry.refresh()

    assert [worker.container_id for worker in report.healthy] == ["a", "b"]
    assert report.unhealthy == ()
    assert report.warning is None
    assert [event for event, _ in events] == ["pool.discovered"]
    assert events[0][1]["healthy"] == 2


def test_registry_warns_when_the_pool_is_underfilled():
    client = _FakeDocker([_container("a", "/w1", 55001)])
    registry, events = _registry(client, size=3)

    report = registry.refresh()

    assert len(report.healthy) == 1
    assert report.warning == "1 of 3 Steel workers are reachable"
    assert [event for event, _ in events] == ["pool.discovered", "pool.warning"]
    assert events[1][1]["reachable"] == 1
    assert events[1][1]["configured"] == 3


def test_registry_warns_when_no_worker_is_discovered():
    registry, events = _registry(_FakeDocker([]), size=2)

    report = registry.refresh()

    assert report.healthy == ()
    assert report.warning == "0 of 2 Steel workers are reachable"
    assert events[0][1]["discovered"] == 0


def test_registry_separates_unhealthy_workers():
    client = _FakeDocker([_container("a", "/w1", 55001), _container("b", "/w2", 55002)])
    registry, _ = _registry(client, size=2, health={"a": True, "b": False})

    report = registry.refresh()

    assert [worker.container_id for worker in report.healthy] == ["a"]
    assert [worker.container_id for worker in report.unhealthy] == ["b"]
    assert report.warning == "1 of 2 Steel workers are reachable"


def test_registry_treats_a_health_exception_as_unhealthy():
    client = _FakeDocker([_container("a", "/w1", 55001)])

    def fail(worker, timeout):
        raise RuntimeError("probe failed")

    registry = WorkerRegistry(
        client,
        LABEL,
        1,
        health_timeout_s=0.01,
        health_check=fail,
    )

    report = registry.refresh()

    assert report.healthy == ()
    assert [worker.container_id for worker in report.unhealthy] == ["a"]


def test_registry_events_do_not_carry_worker_urls():
    client = _FakeDocker([_container("a", "/w1", 55001)])
    registry, events = _registry(client, size=1)

    registry.refresh()

    assert "http://" not in json.dumps(events)


@pytest.mark.parametrize(
    "size,label",
    [(0, LABEL), (-1, LABEL), (1, ""), (1, "   ")],
)
def test_registry_rejects_an_invalid_configuration(size, label):
    with pytest.raises(ValueError):
        WorkerRegistry(_FakeDocker([]), label, size)


@pytest.mark.parametrize(
    "host", ["", "   ", "http://worker", "worker/api", "two words"]
)
def test_registry_rejects_an_invalid_worker_host(host):
    with pytest.raises(ValueError):
        WorkerRegistry(_FakeDocker([]), LABEL, 1, worker_host=host)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_registry_rejects_an_invalid_health_timeout(timeout):
    with pytest.raises(ValueError):
        WorkerRegistry(_FakeDocker([]), LABEL, 1, health_timeout_s=timeout)


def test_registry_tolerates_an_emit_failure():
    client = _FakeDocker([_container("a", "/w1", 55001)])

    def fail(event, **fields):
        raise RuntimeError("log sink down")

    registry = WorkerRegistry(
        client,
        LABEL,
        1,
        health_timeout_s=0.01,
        health_check=lambda worker, timeout: True,
        emit=fail,
    )

    report = registry.refresh()

    assert report.reachable == 1


@pytest.mark.parametrize(
    "container_id,name,port",
    [
        ("", "w", 55001),
        (1, "w", 55001),
        ("a", "", 55001),
        ("a", "w", 0),
        ("a", "w", 70000),
        ("a", "w", "55001"),
        ("a", "w", True),
    ],
)
def test_worker_rejects_an_invalid_identity(container_id, name, port):
    with pytest.raises(ValueError):
        Worker(container_id, name, port)


@pytest.mark.parametrize(
    "socket_path,timeout",
    [("", 1), ("  ", 1), ("/tmp/docker.sock", 0), ("/tmp/docker.sock", float("nan"))],
)
def test_docker_client_rejects_an_invalid_configuration(socket_path, timeout):
    with pytest.raises(ValueError):
        DockerUnixClient(socket_path, timeout=timeout)


@pytest.mark.parametrize("port", [0, 70000, True, "3000"])
def test_registry_rejects_an_invalid_api_port(port):
    with pytest.raises(ValueError):
        WorkerRegistry(
            _FakeDocker([]), LABEL, 1, health_timeout_s=1, api_private_port=port
        )


def test_registry_keeps_the_last_report():
    client = _FakeDocker([_container("a", "/w1", 55001)])
    registry, _ = _registry(client, size=1)

    assert registry.report is None
    report = registry.refresh()

    assert registry.report is report
