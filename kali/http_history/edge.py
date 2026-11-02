"""The HTTP-history ingest edge: a separate Kali process, never an MCP tool.

Spec: `docs/design/steel-crawl-spec.md` section 10.2.

The crawler posts normalized artifacts here in batches of at most 100 artifacts
or 8 MiB. The edge validates each artifact with the canonical model, strips the
bearer token before anything else, and calls ``record_if_absent`` so a replay is
a counted duplicate rather than a failed write. It listens on the compose network
only; it is not registered in the MCP server and it logs no request header or
body.

The store factory is injected: production builds one per project under the
history root, and the unit test supplies a fake.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from kali.http_history.models import HttpArtifact
from kali.http_history.store import HttpHistoryStore

MAX_ARTIFACTS = 100
MAX_BYTES = 8 * 1024 * 1024


class IngestStore(Protocol):
    """The one store operation the edge needs."""

    def record_if_absent(
        self, artifact: HttpArtifact, bodies: dict[str, bytes] | None = None
    ) -> bool: ...


class EdgeServer(ThreadingHTTPServer):
    """The threaded edge server with its injected store and batch limits."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        store_factory: Callable[[str], IngestStore],
        token: str,
        *,
        max_artifacts: int = MAX_ARTIFACTS,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        super().__init__(address, EdgeHandler)
        self.store_factory = store_factory
        self.token = token
        self.max_artifacts = max(1, max_artifacts)
        self.max_bytes = max(1, max_bytes)


class EdgeHandler(BaseHTTPRequestHandler):
    """One POST /v1/ingest request, authenticated and bounded."""

    server: EdgeServer

    def do_POST(self) -> None:  # noqa: N802 - the stdlib handler API
        if self.path != "/v1/ingest":
            self._json(404, {"error": "not_found"})
            return
        if self.headers.get("Authorization") != f"Bearer {self.server.token}":
            self._json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"error": "empty_body"})
            return
        if length > self.server.max_bytes:
            self._json(413, {"error": "batch_too_large"})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, Mapping):
            self._json(400, {"error": "invalid_payload"})
            return
        project_id = payload.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            self._json(400, {"error": "missing_project_id"})
            return
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            self._json(400, {"error": "missing_artifacts"})
            return
        if len(artifacts) > self.server.max_artifacts:
            self._json(413, {"error": "too_many_artifacts"})
            return
        bodies = _decode_bodies(payload.get("bodies"))
        created = duplicates = rejected = 0
        errors: list[dict[str, str]] = []
        try:
            store = self.server.store_factory(project_id)
        except Exception as exc:  # noqa: BLE001 - a store failure is a 500
            self._json(500, {"error": "store_unavailable", "detail": str(exc)})
            return
        for raw_artifact in artifacts:
            try:
                artifact = HttpArtifact.model_validate(raw_artifact)
                if store.record_if_absent(artifact, bodies):
                    created += 1
                else:
                    duplicates += 1
            except Exception as exc:  # noqa: BLE001 - one bad artifact never fails the batch
                rejected += 1
                errors.append({"message": str(exc)[:500]})
        self._json(
            200,
            {
                "created": created,
                "duplicates": duplicates,
                "rejected": rejected,
                "errors": errors,
            },
        )

    def _json(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the request log: it must never carry a token or a body."""
        return


def _decode_bodies(raw: Any) -> dict[str, bytes]:
    """The base64 body map keyed by the artifact's `sha256:` reference."""
    bodies: dict[str, bytes] = {}
    if not isinstance(raw, list):
        return bodies
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        digest = item.get("sha256")
        data = item.get("data")
        encoding = item.get("encoding")
        if not isinstance(digest, str) or not isinstance(data, str):
            continue
        if encoding != "base64":
            continue
        try:
            bodies[f"sha256:{digest}"] = base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            continue
    return bodies


class StoreCache:
    """One `HttpHistoryStore` per project, created lazily and kept open."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = str(root)
        self._stores: dict[str, HttpHistoryStore] = {}
        self._lock = threading.Lock()

    def __call__(self, project_id: str) -> HttpHistoryStore:
        with self._lock:
            store = self._stores.get(project_id)
            if store is None:
                store = HttpHistoryStore(self._root, project_id)
                self._stores[project_id] = store
            return store


def create_edge_server(
    store_factory: Callable[[str], IngestStore],
    token: str,
    host: str = "0.0.0.0",
    port: int = 8001,
    *,
    max_artifacts: int = MAX_ARTIFACTS,
    max_bytes: int = MAX_BYTES,
) -> EdgeServer:
    """Build the edge server without starting it (the test's seam)."""
    if not token:
        raise ValueError("the HTTP-history edge requires a bearer token")
    return EdgeServer(
        (host, port),
        store_factory,
        token,
        max_artifacts=max_artifacts,
        max_bytes=max_bytes,
    )


def main() -> None:
    token = os.environ.get("KALI_HTTP_HISTORY_EDGE_TOKEN", "")
    if not token:
        raise SystemExit(
            "KALI_HTTP_HISTORY_EDGE_TOKEN is required to start the HTTP-history edge"
        )
    host = os.environ.get("KALI_HTTP_HISTORY_EDGE_HOST", "0.0.0.0")
    port = int(os.environ.get("KALI_HTTP_HISTORY_EDGE_PORT", "8001"))
    root = os.environ.get("KALI_HTTP_HISTORY_ROOT", "/data")
    server = create_edge_server(StoreCache(root), token, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


__all__ = [
    "EdgeHandler",
    "EdgeServer",
    "IngestStore",
    "MAX_ARTIFACTS",
    "MAX_BYTES",
    "StoreCache",
    "create_edge_server",
    "main",
]
