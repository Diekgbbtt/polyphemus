"""Steel worker discovery and health for the browser pool.

The operator owns the Steel API containers and the SSH tunnels. This module
only reads the local Docker socket, selects the containers the operator
labelled, derives ``http://localhost:<published-port>``, and probes the
worker's ``GET /v1/health``.

The pool manager never creates, starts, stops, or removes a container.
The configured pool size is compared with the reachable workers, and a lower
count raises a structured ``pool.warning`` event.

The module is stdlib-only and performs no I/O at import.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import http.client
import json
import math
from typing import Any, Protocol

try:  # package layout
    from kali.steel_pool.docker_api import DockerAPIError
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.docker_api import DockerAPIError  # type: ignore[no-redef]

STEEL_API_PRIVATE_PORT = 3000
HEALTH_PATH = "/v1/health"

__all__ = [
    "HEALTH_PATH",
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


@dataclass(frozen=True)
class Worker:
    """One reachable Steel API worker on the operator's loopback."""

    container_id: str
    container_name: str
    api_port: int

    def __post_init__(self) -> None:
        if not isinstance(self.container_id, str) or not self.container_id:
            raise ValueError("a worker needs a container id")
        if not isinstance(self.container_name, str) or not self.container_name:
            raise ValueError("a worker needs a container name")
        if not isinstance(self.api_port, int) or isinstance(self.api_port, bool):
            raise ValueError("a worker API port must be an integer")
        if not 0 < self.api_port < 65536:
            raise ValueError("a worker API port is out of range")

    @property
    def url(self) -> str:
        return f"http://localhost:{self.api_port}"


@dataclass(frozen=True)
class PoolReport:
    """The result of one discovery and health sweep."""

    workers: tuple[Worker, ...]
    healthy: tuple[Worker, ...]
    unhealthy: tuple[Worker, ...]
    configured_size: int
    warning: str | None

    @property
    def reachable(self) -> int:
        return len(self.healthy)


def parse_worker(
    container: object,
    *,
    api_private_port: int = STEEL_API_PRIVATE_PORT,
) -> Worker | None:
    """Project one Docker container into a worker, or skip it.

    A container with no published API port is not part of the pool.
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
    ports = container.get("Ports")
    if ports is None:
        return None
    if not isinstance(ports, list):
        raise DockerAPIError(f"container {container_id} has malformed ports")
    candidates: list[tuple[int, int]] = []
    for entry in ports:
        if not isinstance(entry, Mapping):
            raise DockerAPIError(f"container {container_id} has a malformed port")
        if entry.get("PrivatePort") != api_private_port:
            continue
        if entry.get("Type") != "tcp":
            continue
        public_port = entry.get("PublicPort")
        if isinstance(public_port, bool) or not isinstance(public_port, int):
            continue
        if not 0 < public_port < 65536:
            continue
        bound_loopback = entry.get("IP") in ("127.0.0.1", "::1")
        candidates.append((0 if bound_loopback else 1, public_port))
    if not candidates:
        return None
    candidates.sort()
    return Worker(
        container_id=container_id,
        container_name=name,
        api_port=candidates[0][1],
    )


def discover_workers(
    client: DockerClient,
    label: str,
    *,
    api_private_port: int = STEEL_API_PRIVATE_PORT,
) -> list[Worker]:
    """List labelled containers and project the ones with a published API."""
    filters = json.dumps({"label": [label]})
    payload = client.get_json("/containers/json", query={"filters": filters})
    if not isinstance(payload, list):
        raise DockerAPIError("the Docker container list is not an array")
    workers: list[Worker] = []
    for container in payload:
        worker = parse_worker(container, api_private_port=api_private_port)
        if worker is not None:
            workers.append(worker)
    return workers


def check_worker_health(worker: Worker, timeout_s: float) -> bool:
    """Probe ``GET /v1/health`` on one worker."""
    connection = http.client.HTTPConnection(
        "localhost", worker.api_port, timeout=timeout_s
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
        configured_size: int,
        *,
        health_timeout_s: float = 2.0,
        health_check: Callable[[Worker, float], bool] = check_worker_health,
        emit: Callable[..., None] | None = None,
        api_private_port: int = STEEL_API_PRIVATE_PORT,
    ) -> None:
        cleaned = (label or "").strip()
        if not cleaned:
            raise ValueError("the pool label is required")
        if not isinstance(configured_size, int) or isinstance(configured_size, bool):
            raise ValueError("the configured pool size must be a positive integer")
        if configured_size < 1:
            raise ValueError("the configured pool size must be a positive integer")
        if not math.isfinite(health_timeout_s) or health_timeout_s <= 0:
            raise ValueError("the health timeout must be positive and finite")
        if (
            not isinstance(api_private_port, int)
            or isinstance(api_private_port, bool)
            or not 0 < api_private_port < 65536
        ):
            raise ValueError("the worker API port is out of range")
        self._client = client
        self._label = cleaned
        self._configured_size = configured_size
        self._health_timeout_s = health_timeout_s
        self._health_check = health_check
        self._emit = emit or _noop_emit
        self._api_private_port = api_private_port
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
        )
        health = self._check_all(workers)
        healthy = tuple(
            worker for worker in workers if health.get(worker.container_id, False)
        )
        unhealthy = tuple(
            worker for worker in workers if not health.get(worker.container_id, False)
        )
        warning = None
        if len(healthy) < self._configured_size:
            warning = (
                f"{len(healthy)} of {self._configured_size} "
                "Steel workers are reachable"
            )
        report = PoolReport(
            workers=tuple(workers),
            healthy=healthy,
            unhealthy=unhealthy,
            configured_size=self._configured_size,
            warning=warning,
        )
        self._report = report
        self._safe_emit(
            "pool.discovered",
            discovered=len(workers),
            healthy=len(healthy),
            configured=self._configured_size,
        )
        if warning is not None:
            self._safe_emit(
                "pool.warning",
                reason="pool_underfilled",
                reachable=len(healthy),
                configured=self._configured_size,
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
