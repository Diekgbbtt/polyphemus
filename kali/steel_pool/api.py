"""Read-only worker API calls for session capture and release.

The pool manager addresses one Steel API worker on the operator's loopback.
The CLI remains the browser executor; this client only captures the session
context and releases a session as the fallback after ``browser stop``.

The module is stdlib-only and performs no I/O at import.
"""
from __future__ import annotations

import http.client
import json
import re
from urllib.parse import urlsplit

__all__ = ["WorkerAPI", "WorkerAPIError"]

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")


class WorkerAPIError(RuntimeError):
    """A worker API request failed or returned an unusable payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _session_component(session_id: object) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("the Steel session id is not a safe path component")
    return session_id


class WorkerAPI:
    """The worker API calls the pool needs, addressed at one loopback origin."""

    def __init__(self, base_url: str, *, timeout_s: float = 10.0) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or not parts.hostname:
            raise ValueError("the worker API URL must be an http origin")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError("the worker API URL must not carry a path or query")
        if timeout_s <= 0:
            raise ValueError("the worker API timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.host = parts.hostname
        self.port = parts.port or 80
        self.timeout_s = timeout_s

    def context(self, session_id: object) -> dict:
        """Read ``GET /v1/sessions/<id>/context``."""
        payload = self._request(
            "GET", f"/v1/sessions/{_session_component(session_id)}/context"
        )
        if not isinstance(payload, dict):
            raise WorkerAPIError("the worker context is not an object")
        return payload

    def release(self, session_id: object) -> bool:
        """Release a session. A 404 means it is already gone."""
        path = f"/v1/sessions/{_session_component(session_id)}/release"
        try:
            self._request("POST", path)
            return True
        except WorkerAPIError as exc:
            if exc.status_code == 404:
                return False
            raise

    def _request(self, method: str, path: str, body: dict | None = None):
        connection = http.client.HTTPConnection(
            self.host, self.port, timeout=self.timeout_s
        )
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            payload = response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise WorkerAPIError(
                f"{method} {path} on the Steel worker failed: {exc}"
            ) from exc
        finally:
            connection.close()
        if response.status >= 400:
            detail = payload[:200].decode("utf-8", "replace")
            raise WorkerAPIError(
                f"{method} {path} returned {response.status}: {detail}",
                status_code=response.status,
            )
        if not payload:
            return None
        try:
            return json.loads(payload)
        except ValueError as exc:
            raise WorkerAPIError(
                f"{method} {path} returned a non-JSON body"
            ) from exc
