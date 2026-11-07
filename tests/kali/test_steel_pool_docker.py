"""Unit tier: Steel pool discovery over the instance's Docker socket.

The Docker API is faked at the JSON boundary. The Unix-socket transport is
tested against a real local socket, so no Docker daemon and no Steel worker is
needed. The pool manager never creates, starts, stops, or removes a container.

The workers are normal containers on the instance network. Discovery reads the
container IP and assigns a stable loopback public port per replica; there is no
published port and no operator tunnel.
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
    PUBLIC_PORT_BASE,
    Worker,
    WorkerRegistry,
    check_worker_health,
    discover_workers,
    parse_worker,
)

LABEL = "polymerhus.steel-pool=true"


def _container(
    container_id: str = "abc123def456",
    name: str = "/ph-test-steel-worker-1",
    ip: str | None = "172.20.0.5",
    private_port: int = 3000,
    port_type: str = "tcp",
) -> dict:
    payload: dict = {"Id": container_id, "Names": [name], "Ports": []}
    if ip is not None:
        payload["NetworkSettings"] = {
            "Networks": {"polymerhus-net": {"IPAddress": ip}}
        }
    payload["Ports"] = (
        [
            {
                "IP": "0.0.0.0",
                "PrivatePort": private_port,
                "PublicPort": 55001,
                "Type": port_type,
            }
        ]
        if ip is None
        else []
    )
    return payload


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


def test_parse_worker_builds_the_loopback_public_url():
    worker = parse_worker(_container(), public_port=3100)

    assert worker == Worker(
        container_id="abc123def456",
        container_name="ph-test-steel-worker-1",
        container_ip="172.20.0.5",
        public_port=3100,
    )
    assert worker.url == "http://localhost:3100"
    assert worker.upstream_url == "http://172.20.0.5:3000"


def test_parse_worker_uses_the_first_pool_network_by_sorted_name():
    payload = _container(ip=None)
    payload["NetworkSettings"] = {
        "Networks": {
            "zeta-net": {"IPAddress": "172.30.0.9"},
            "polymerhus-net": {"IPAddress": "172.20.0.5"},
        }
    }

    worker = parse_worker(payload, public_port=3101)

    assert worker.container_ip == "172.20.0.5"


def test_parse_worker_falls_back_to_the_first_network_with_an_address():
    payload = _container(ip=None)
    payload["NetworkSettings"] = {
        "Networks": {
            "zeta-net": {"IPAddress": "172.30.0.9"},
            "alpha-net": {"IPAddress": "172.40.0.2"},
        }
    }

    worker = parse_worker(payload, public_port=3102)

    assert worker.container_ip == "172.30.0.9"


def test_parse_worker_skips_a_container_with_no_network_address():
    assert parse_worker(_container(ip=None), public_port=3100) is None


def test_parse_worker_ignores_a_published_port():
    payload = _container(ip="172.20.0.5")
    payload["Ports"] = [
        {"IP": "0.0.0.0", "PrivatePort": 3000, "PublicPort": 55001, "Type": "tcp"}
    ]

    worker = parse_worker(payload, public_port=3100)

    assert worker.container_ip == "172.20.0.5"
    assert worker.public_port == 3100


def test_parse_worker_uses_the_short_id_when_the_name_is_missing():
    worker = parse_worker(
        {"Id": "abc123def4567890", "Names": [], "NetworkSettings": {
            "Networks": {"polymerhus-net": {"IPAddress": "172.20.0.5"}}
        }},
        public_port=3100,
    )

    assert worker.container_name == "abc123def456"


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-container",
        {"Names": ["/x"], "NetworkSettings": {}},
        {"Id": "abc", "Names": ["/x"], "NetworkSettings": {"Networks": "bad"}},
        {"Id": "abc", "Names": ["/x"], "NetworkSettings": {"Networks": {"n": "bad"}}},
    ],
)
def test_parse_worker_rejects_malformed_payloads(payload):
    with pytest.raises(DockerAPIError):
        parse_worker(payload, public_port=3100)


def test_discover_assigns_ports_by_compose_ordinal_not_api_order():
    client = _FakeDocker(
        [
            _container("b", "/ph-x-steel-worker-2", "172.20.0.6"),
            _container("a", "/ph-x-steel-worker-1", "172.20.0.5"),
        ]
    )

    workers = discover_workers(client, LABEL)

    assert [(worker.container_name, worker.public_port) for worker in workers] == [
        ("ph-x-steel-worker-1", PUBLIC_PORT_BASE),
        ("ph-x-steel-worker-2", PUBLIC_PORT_BASE + 1),
    ]
    assert [worker.container_ip for worker in workers] == ["172.20.0.5", "172.20.0.6"]


def test_discover_keeps_a_replica_port_stable_when_a_sibling_is_missing():
    client = _FakeDocker(
        [_container("b", "/ph-x-steel-worker-2", "172.20.0.6")]
    )

    workers = discover_workers(client, LABEL)

    assert [(worker.container_name, worker.public_port) for worker in workers] == [
        ("ph-x-steel-worker-2", PUBLIC_PORT_BASE + 1)
    ]


def test_discover_gives_unordered_names_unique_ports():
    client = _FakeDocker(
        [
            _container("a", "/plain-a", "172.20.0.5"),
            _container("b", "/plain-b", "172.20.0.6"),
        ]
    )

    workers = discover_workers(client, LABEL)

    assert sorted(worker.public_port for worker in workers) == [
        PUBLIC_PORT_BASE,
        PUBLIC_PORT_BASE + 1,
    ]


def test_discover_gives_duplicate_ordinals_unique_ports():
    client = _FakeDocker(
        [
            _container("a", "/x-worker-1", "172.20.0.5"),
            _container("b", "/y-worker-1", "172.20.0.6"),
        ]
    )

    workers = discover_workers(client, LABEL)

    assert sorted(worker.public_port for worker in workers) == [
        PUBLIC_PORT_BASE,
        PUBLIC_PORT_BASE + 1,
    ]


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


def _worker(container_id: str = "abc", name: str = "worker-1", **kwargs) -> Worker:
    return Worker(
        container_id=container_id,
        container_name=name,
        container_ip="127.0.0.1",
        public_port=kwargs.pop("public_port", 3100),
        **kwargs,
    )


def test_health_check_accepts_a_2xx_response():
    server, thread = _health_server(200)
    worker = _worker(api_port=server.server_address[1])
    try:
        assert check_worker_health(worker, timeout_s=2) is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_health_check_rejects_a_5xx_response():
    server, thread = _health_server(500)
    worker = _worker(api_port=server.server_address[1])
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
    worker = _worker(api_port=port)

    assert check_worker_health(worker, timeout_s=0.2) is False


def _registry(client, health=None, events=None):
    health = health or {}
    events = events if events is not None else []
    return WorkerRegistry(
        client,
        LABEL,
        health_timeout_s=0.01,
        health_check=lambda worker, timeout: health.get(worker.container_id, True),
        emit=lambda event, **fields: events.append((event, fields)),
    ), events


def test_registry_reports_a_full_healthy_pool_without_a_configured_size():
    client = _FakeDocker(
        [
            _container("a", "/ph-x-steel-worker-1", "172.20.0.5"),
            _container("b", "/ph-x-steel-worker-2", "172.20.0.6"),
        ]
    )
    registry, events = _registry(client)

    report = registry.refresh()

    assert [worker.container_id for worker in report.healthy] == ["a", "b"]
    assert report.unhealthy == ()
    assert report.warning is None
    assert [event for event, _ in events] == ["pool.discovered"]
    assert events[0][1]["healthy"] == 2


def test_registry_warns_when_a_worker_is_unhealthy():
    client = _FakeDocker(
        [
            _container("a", "/ph-x-steel-worker-1", "172.20.0.5"),
            _container("b", "/ph-x-steel-worker-2", "172.20.0.6"),
        ]
    )
    registry, events = _registry(client, health={"a": True, "b": False})

    report = registry.refresh()

    assert [worker.container_id for worker in report.healthy] == ["a"]
    assert [worker.container_id for worker in report.unhealthy] == ["b"]
    assert report.warning == "1 of 2 Steel workers are unreachable"
    assert [event for event, _ in events] == ["pool.discovered", "pool.warning"]
    assert events[1][1]["reachable"] == 1
    assert events[1][1]["discovered"] == 2


def test_registry_warns_when_no_worker_is_discovered():
    registry, events = _registry(_FakeDocker([]))

    report = registry.refresh()

    assert report.healthy == ()
    assert report.warning == "no Steel workers are reachable"
    assert events[0][1]["discovered"] == 0


def test_registry_treats_a_health_exception_as_unhealthy():
    client = _FakeDocker([_container("a", "/ph-x-steel-worker-1")])

    def fail(worker, timeout):
        raise RuntimeError("probe failed")

    registry = WorkerRegistry(
        client,
        LABEL,
        health_timeout_s=0.01,
        health_check=fail,
    )

    report = registry.refresh()

    assert report.healthy == ()
    assert [worker.container_id for worker in report.unhealthy] == ["a"]


def test_registry_events_do_not_carry_worker_urls():
    client = _FakeDocker([_container("a", "/ph-x-steel-worker-1")])
    registry, events = _registry(client)

    registry.refresh()

    assert "http://" not in json.dumps(events)


@pytest.mark.parametrize("label", ["", "   "])
def test_registry_rejects_an_invalid_label(label):
    with pytest.raises(ValueError):
        WorkerRegistry(_FakeDocker([]), label)


@pytest.mark.parametrize(
    "base", [0, -1, 70000, True, "3100"]
)
def test_registry_rejects_an_invalid_public_port_base(base):
    with pytest.raises(ValueError):
        WorkerRegistry(
            _FakeDocker([]), LABEL, public_port_base=base, health_timeout_s=1
        )


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_registry_rejects_an_invalid_health_timeout(timeout):
    with pytest.raises(ValueError):
        WorkerRegistry(_FakeDocker([]), LABEL, health_timeout_s=timeout)


def test_registry_tolerates_an_emit_failure():
    client = _FakeDocker([_container("a", "/ph-x-steel-worker-1")])

    def fail(event, **fields):
        raise RuntimeError("log sink down")

    registry = WorkerRegistry(
        client,
        LABEL,
        health_timeout_s=0.01,
        health_check=lambda worker, timeout: True,
        emit=fail,
    )

    report = registry.refresh()

    assert report.reachable == 1


@pytest.mark.parametrize(
    "container_id,name,ip,public_port,api_port",
    [
        ("", "w", "172.20.0.5", 3100, 3000),
        (1, "w", "172.20.0.5", 3100, 3000),
        ("a", "", "172.20.0.5", 3100, 3000),
        ("a", "w", "", 3100, 3000),
        ("a", "w", "http://x", 3100, 3000),
        ("a", "w", "two words", 3100, 3000),
        ("a", "w", "172.20.0.5", 0, 3000),
        ("a", "w", "172.20.0.5", 70000, 3000),
        ("a", "w", "172.20.0.5", "3100", 3000),
        ("a", "w", "172.20.0.5", True, 3000),
        ("a", "w", "172.20.0.5", 3100, 0),
        ("a", "w", "172.20.0.5", 3100, 70000),
    ],
)
def test_worker_rejects_an_invalid_identity(
    container_id, name, ip, public_port, api_port
):
    with pytest.raises(ValueError):
        Worker(container_id, name, ip, public_port, api_port)


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
            _FakeDocker([]), LABEL, health_timeout_s=1, api_private_port=port
        )


def test_registry_keeps_the_last_report():
    client = _FakeDocker([_container("a", "/ph-x-steel-worker-1")])
    registry, _ = _registry(client)

    assert registry.report is None
    report = registry.refresh()

    assert registry.report is report
