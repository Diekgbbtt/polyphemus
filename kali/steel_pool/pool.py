"""Steel worker discovery and health for the browser pool.

The pool belongs to the instance compose project. This module only reads the
local Docker socket, selects the containers the deployment labelled, reads each
container's address on the pool network, and probes the worker's
``GET /v1/health``. It assigns each replica one stable loopback public port from
``PUBLIC_PORT_BASE``; the browser MCP's reverse proxy owns that port.

The pool manager never creates, starts, stops, or removes a container. The
discovered count is the truth; a partial pool is a structured ``pool.warning``
event, never a fatal error.

The module is stdlib-only and performs no I/O at import.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import http.client
import ipaddress
import json
import math
import re
from typing import Any, Protocol

try:  # package layout
    from kali.steel_pool.docker_api import DockerAPIError
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.docker_api import DockerAPIError  # type: ignore[no-redef]

STEEL_API_PRIVATE_PORT = 3000
PUBLIC_PORT_BASE = 3100
POOL_NETWORK = "polymerhus-net"
HEALTH_PATH = "/v1/health"
_REPLICA_ORDINAL = re.compile(r"-(\d+)$")

__all__ = [
    "HEALTH_PATH",
    "POOL_NETWORK",
    "PUBLIC_PORT_BASE",
    "PoolReport",
    "STEEL_API_PRIVATE_PORT",
    "Worker",
    "WorkerRegistry",
    "check_worker_health",
    "discover_workers",
    "parse_worker",
]


class DockerClient(Protocol):
    """The read-only Docker API slice the pool needs."""

    def get_json(self, path: str, query: dict | None = None) -> Any: ...


def _port(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if not 0 < value < 65536:
        raise ValueError(f"{label} is out of range")
    return value


def _address(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a worker needs a container address")
    address = value.strip()
    if address != value:
        raise ValueError("a worker container address has surrounding whitespace")
    try:
        ipaddress.ip_address(address)
    except ValueError as exc:
        raise ValueError("a worker container address is not an IP address") from exc
    return address


@dataclass(frozen=True)
class Worker:
    """One reachable Steel API worker on the instance network.

    ``public_port`` is the loopback port the browser MCP reverse proxy binds.
    ``api_port`` is the worker's private API port inside its container.
    The raw API port is never published on the host.
    """

    container_id: str
    container_name: str
    container_ip: str
    public_port: int
    api_port: int = STEEL_API_PRIVATE_PORT

    def __post_init__(self) -> None:
        if not isinstance(self.container_id, str) or not self.container_id:
            raise ValueError("a worker needs a container id")
        if not isinstance(self.container_name, str) or not self.container_name:
            raise ValueError("a worker needs a container name")
        _address(self.container_ip)
        _port(self.public_port, "a worker public port")
        _port(self.api_port, "a worker API port")

    @property
    def url(self) -> str:
        """The loopback URL the CLI addresses through the reverse proxy."""
        return f"http://localhost:{self.public_port}"

    @property
    def upstream_url(self) -> str:
        """The direct container URL the proxy and health probe use."""
        return f"http://{self.container_ip}:{self.api_port}"


@dataclass(frozen=True)
class PoolReport:
    """The result of one discovery and health sweep."""

    workers: tuple[Worker, ...]
    healthy: tuple[Worker, ...]
    unhealthy: tuple[Worker, ...]
    warning: str | None

    @property
    def reachable(self) -> int:
        return len(self.healthy)


@dataclass(frozen=True)
class _Container:
    container_id: str
    container_name: str
    container_ip: str

    @property
    def ordinal(self) -> int | None:
        match = _REPLICA_ORDINAL.search(self.container_name)
        return int(match.group(1)) if match is not None else None


def _parse_container(container: object) -> _Container | None:
    """Project one Docker container into the pool's identity, or skip it.

    A container with no address on the pool network is not a pool worker.
    A malformed container entry raises ``DockerAPIError`` instead of being
    silently dropped.
    """
    if not isinstance(container, Mapping):
        raise DockerAPIError("a Docker container entry is not an object")
    container_id = container.get("Id")
    if not isinstance(container_id, str) or not container_id:
        raise DockerAPIError("a Docker container entry has no id")
    names = container.get("Names") or []
    if not isinstance(names, list):
        raise DockerAPIError(f"container {container_id} has malformed names")
    name = ""
    for candidate in names:
        if isinstance(candidate, str) and candidate.lstrip("/"):
            name = candidate.lstrip("/")
            break
    if not name:
        name = container_id[:12]
    settings = container.get("NetworkSettings")
    if settings is None:
        return None
    if not isinstance(settings, Mapping):
        raise DockerAPIError(f"container {container_id} has malformed networks")
    networks = settings.get("Networks")
    if networks is None:
        return None
    if not isinstance(networks, Mapping):
        raise DockerAPIError(f"container {container_id} has malformed networks")
    # Prefer the declared pool network; otherwise keep Docker's own network
    # order, which is stable for one container.
    ordered = list(networks.items())
    ordered.sort(key=lambda item: item[0] != POOL_NETWORK)
    for network_name, network in ordered:
        if not isinstance(network, Mapping):
            raise DockerAPIError(
                f"container {container_id} has a malformed network"
            )
        address = network.get("IPAddress")
        if not isinstance(address, str) or not address:
            continue
        try:
            ipaddress.ip_address(address)
        except ValueError as exc:
            raise DockerAPIError(
                f"container {container_id} on {network_name!r} has an "
                "invalid address"
            ) from exc
        return _Container(
            container_id=container_id,
            container_name=name,
            container_ip=address,
        )
    return None


def parse_worker(
    container: object,
    *,
    public_port: int,
    api_private_port: int = STEEL_API_PRIVATE_PORT,
) -> Worker | None:
    """Project one Docker container into a worker, or skip it."""
    identity = _parse_container(container)
    if identity is None:
        return None
    return Worker(
        container_id=identity.container_id,
        container_name=identity.container_name,
        container_ip=identity.container_ip,
        public_port=public_port,
        api_port=api_private_port,
    )


def _assign_ports(
    containers: list[_Container], base: int
) -> list[tuple[_Container, int]]:
    """Assign one stable public port per replica.

    A Compose replica ordinal (``-1``, ``-2``) owns ``base + ordinal - 1``, so
    a missing sibling never shifts the survivors. A name without an ordinal is
    ordered by name. Duplicate or out-of-range preferences fall through to the
    next free port.
    """
    ordered = sorted(
        containers,
        key=lambda item: (
            item.ordinal if item.ordinal is not None else base,
            item.container_name,
            item.container_id,
        ),
    )
    used: set[int] = set()
    assigned: list[tuple[_Container, int]] = []
    for index, container in enumerate(ordered):
        preferred = (
            base + container.ordinal - 1
            if container.ordinal is not None
            else base + index
        )
        port = preferred
        if port in used or not 0 < port < 65536:
            port = base
            while port in used or not 0 < port < 65536:
                port += 1
        used.add(port)
        assigned.append((container, port))
    return assigned


def discover_workers(
    client: DockerClient,
    label: str,
    *,
    api_private_port: int = STEEL_API_PRIVATE_PORT,
    public_port_base: int = PUBLIC_PORT_BASE,
) -> list[Worker]:
    """List labelled containers and project the ones with a pool address."""
    filters = json.dumps({"label": [label]})
    payload = client.get_json("/containers/json", query={"filters": filters})
    if not isinstance(payload, list):
        raise DockerAPIError("the Docker container list is not an array")
    containers: list[_Container] = []
    for entry in payload:
        identity = _parse_container(entry)
        if identity is not None:
            containers.append(identity)
    return [
        Worker(
            container_id=identity.container_id,
            container_name=identity.container_name,
            container_ip=identity.container_ip,
            public_port=port,
            api_port=api_private_port,
        )
        for identity, port in _assign_ports(containers, public_port_base)
    ]


def check_worker_health(worker: Worker, timeout_s: float) -> bool:
    """Probe ``GET /v1/health`` on one worker's container address."""
    connection = http.client.HTTPConnection(
        worker.container_ip, worker.api_port, timeout=timeout_s
    )
    try:
        connection.request(
            "GET",
            HEALTH_PATH,
            headers={"Host": f"localhost:{worker.api_port}"},
        )
        response = connection.getresponse()
        response.read()
        return 200 <= response.status < 300
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _noop_emit(event: str, **fields: Any) -> None:
    return None


class WorkerRegistry:
    """Discover the labelled pool and record which workers are reachable."""

    def __init__(
        self,
        client: DockerClient,
        label: str,
        *,
        health_timeout_s: float = 2.0,
        health_check: Callable[[Worker, float], bool] = check_worker_health,
        emit: Callable[..., None] | None = None,
        api_private_port: int = STEEL_API_PRIVATE_PORT,
        public_port_base: int = PUBLIC_PORT_BASE,
    ) -> None:
        cleaned = (label or "").strip()
        if not cleaned:
            raise ValueError("the pool label is required")
        if not math.isfinite(health_timeout_s) or health_timeout_s <= 0:
            raise ValueError("the health timeout must be positive and finite")
        if (
            not isinstance(api_private_port, int)
            or isinstance(api_private_port, bool)
            or not 0 < api_private_port < 65536
        ):
            raise ValueError("the worker API port is out of range")
        if (
            not isinstance(public_port_base, int)
            or isinstance(public_port_base, bool)
            or not 0 < public_port_base < 65536
        ):
            raise ValueError("the public port base is out of range")
        self._client = client
        self._label = cleaned
        self._health_timeout_s = health_timeout_s
        self._health_check = health_check
        self._emit = emit or _noop_emit
        self._api_private_port = api_private_port
        self._public_port_base = public_port_base
        self._report: PoolReport | None = None

    @property
    def report(self) -> PoolReport | None:
        return self._report

    def refresh(self) -> PoolReport:
        """Run one discovery and health sweep and emit the pool events."""
        workers = discover_workers(
            self._client,
            self._label,
            api_private_port=self._api_private_port,
            public_port_base=self._public_port_base,
        )
        health = self._check_all(workers)
        healthy = tuple(
            worker for worker in workers if health.get(worker.container_id, False)
        )
        unhealthy = tuple(
            worker for worker in workers if not health.get(worker.container_id, False)
        )
        warning = None
        if not workers:
            warning = "no Steel workers are reachable"
        elif unhealthy:
            warning = (
                f"{len(unhealthy)} of {len(workers)} "
                "Steel workers are unreachable"
            )
        report = PoolReport(
            workers=tuple(workers),
            healthy=healthy,
            unhealthy=unhealthy,
            warning=warning,
        )
        self._report = report
        self._safe_emit(
            "pool.discovered",
            discovered=len(workers),
            healthy=len(healthy),
        )
        if warning is not None:
            self._safe_emit(
                "pool.warning",
                reason="pool_degraded",
                reachable=len(healthy),
                discovered=len(workers),
            )
        return report

    def _safe_emit(self, event: str, **fields: Any) -> None:
        """Emit a pool event; a logger failure never breaks discovery."""
        try:
            self._emit(event, **fields)
        except Exception:
            return None

    def _check_all(self, workers: list[Worker]) -> dict[str, bool]:
        if not workers:
            return {}
        results: dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(workers))) as executor:
            futures = {
                executor.submit(self._probe, worker): worker for worker in workers
            }
            for future in as_completed(futures):
                worker = futures[future]
                results[worker.container_id] = future.result()
        return results

    def _probe(self, worker: Worker) -> bool:
        try:
            return bool(self._health_check(worker, self._health_timeout_s))
        except Exception:
            return False
