"""A read-only Docker API client over the operator's Unix socket.

The pool manager sees the pool host's Docker socket through the operator's
tunnel. It only lists containers and reads their published ports. The client
exposes a single GET operation, so no code path can create, start, stop, or
remove a container.

The client is stdlib-only and performs no I/O at import.
"""
from __future__ import annotations

import http.client
import json
import math
import os
import socket
from urllib.parse import urlencode

__all__ = ["DockerAPIError", "DockerUnixClient"]


class DockerAPIError(RuntimeError):
    """A Docker API request failed or returned an unusable payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _UnixHTTPConnection(http.client.HTTPConnection):
    """An ``HTTPConnection`` whose transport is a Unix domain socket."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._socket_path)
        except BaseException:
            sock.close()
            raise
        self.sock = sock


class DockerUnixClient:
    """A read-only Docker API client bound to one Unix socket."""

    def __init__(
        self,
        socket_path: str | os.PathLike[str],
        *,
        timeout: float = 10.0,
    ) -> None:
        if not str(socket_path).strip():
            raise ValueError("a Docker socket path is required")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        self.socket_path = str(socket_path)
        self.timeout = timeout

    def get_json(self, path: str, query: dict | None = None):
        """GET ``path`` and decode the JSON body.

        A missing socket, a transport error, a non-2xx response, or a body
        that is not JSON raises ``DockerAPIError``.
        """
        if not path.startswith("/"):
            raise ValueError("Docker API paths must start with '/'")
        target = path
        if query:
            target = f"{path}?{urlencode(query)}"
        connection = _UnixHTTPConnection(self.socket_path, self.timeout)
        try:
            connection.request("GET", target, headers={"Host": "localhost"})
            response = connection.getresponse()
            body = response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise DockerAPIError(
                f"GET {path} over {self.socket_path} failed: {exc}"
            ) from exc
        finally:
            connection.close()
        if response.status >= 400:
            detail = body[:200].decode("utf-8", "replace")
            raise DockerAPIError(
                f"GET {path} returned {response.status}: {detail}",
                status_code=response.status,
            )
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError as exc:
            raise DockerAPIError(
                f"GET {path} returned a non-JSON body"
            ) from exc
