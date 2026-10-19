"""State-preserving Steel session teardown (#395, D359-10 follow-up).

The local Steel runtime has no profile store, so a session's identity leaves
with the session unless the caller captures it first. This module is the ONE
construction point for that sequence:

1. ``capture_session_context`` reads ``GET /v1/sessions/<id>/context``, the
   live browser state (``cookies``, ``localStorage``, ``sessionStorage``,
   ``indexedDB``).
2. ``save_session_context`` writes it atomically to a caller-owned file.
3. ``release_session`` ends the session (``POST .../release``); the API closes
   the browser and the container init reaps the Chromium children (the
   ``init: true`` compose setting).

``teardown_with_state`` runs the three in order and always releases, even when
the capture fails, so an unreadable state can never leave a session alive.
``restore_session`` feeds a stored context back through the create call's
``sessionContext`` field, the same shape the capture returns.

The endpoint comes from the shared ``STEEL_BROWSER_API_URL`` resolver (#390);
an explicit ``base_url`` (the SDK-native origin form) overrides it for tests.
The module performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.steel_endpoint import steel_browser_api_url

API_KEY_ENV = "STEEL_API_KEY"
DEFAULT_TIMEOUT_S = 60.0


class SteelStateError(RuntimeError):
    """A Steel session-state call failed, or no endpoint was configured."""


def _base_url(base_url: str | None) -> str:
    origin = (base_url or steel_browser_api_url() or "").strip().rstrip("/")
    if not origin:
        raise SteelStateError(
            "STEEL_BROWSER_API_URL is unset and no base_url was given; "
            "there is no Steel runtime to address"
        )
    # Accept the CLI form too: the HTTP client mounts every route under /v1.
    if origin.endswith("/v1"):
        origin = origin[: -len("/v1")].rstrip("/")
    return origin


def _headers() -> dict[str, str]:
    headers = {"content-type": "application/json"}
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers


def _request(
    method: str,
    path: str,
    *,
    base_url: str | None,
    body: dict | None,
    client: httpx.Client | None,
    timeout: float,
) -> dict:
    origin = _base_url(base_url)
    url = f"{origin}/v1{path}"
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        response = http.request(method, url, json=body, headers=_headers())
    except httpx.HTTPError as exc:
        raise SteelStateError(f"{method} {url} failed: {exc}") from exc
    finally:
        if owns_client:
            http.close()
    if response.status_code >= 400:
        raise SteelStateError(
            f"{method} {url} answered {response.status_code}: {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise SteelStateError(
            f"{method} {url} returned non-JSON: {response.text[:300]}"
        ) from exc


def capture_session_context(
    session_id: str,
    *,
    base_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Read the live browser state of ``session_id`` (cookies + storage)."""
    if not session_id:
        raise SteelStateError("session_id is required")
    return _request(
        "GET",
        f"/sessions/{session_id}/context",
        base_url=base_url,
        body=None,
        client=client,
        timeout=timeout,
    )


def save_session_context(path: str | os.PathLike[str], context: dict) -> Path:
    """Write the captured context atomically to ``path`` and return the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, json.dumps(context, indent=2, sort_keys=True) + "\n")
    return target


def load_session_context(path: str | os.PathLike[str]) -> dict:
    """Read a stored context; a missing or malformed file raises."""
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SteelStateError(f"cannot read session state {target}: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SteelStateError(f"session state {target} is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SteelStateError(f"session state {target} is not a JSON object")
    return data


def create_session(
    session_context: dict | None = None,
    *,
    fields: dict | None = None,
    base_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Create a session, optionally restoring a stored ``session_context``."""
    body = dict(fields or {})
    if session_context is not None:
        body["sessionContext"] = session_context
    return _request(
        "POST",
        "/sessions",
        base_url=base_url,
        body=body,
        client=client,
        timeout=timeout,
    )


def release_session(
    session_id: str,
    *,
    base_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Release ``session_id``; the API ends the session and kills the browser."""
    if not session_id:
        raise SteelStateError("session_id is required")
    return _request(
        "POST",
        f"/sessions/{session_id}/release",
        base_url=base_url,
        body=None,
        client=client,
        timeout=timeout,
    )


def teardown_with_state(
    session_id: str,
    store_path: str | os.PathLike[str],
    *,
    base_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Capture, store, then release. The release always runs.

    A capture that fails still releases the session, then raises, so a broken
    state read never leaks a live session. The return carries the captured
    context, the store path, and the release response.
    The captured context carries cookies and storage values: never log it.
    """
    context: dict | None = None
    capture_error: Exception | None = None
    try:
        context = capture_session_context(
            session_id, base_url=base_url, client=client, timeout=timeout
        )
    except SteelStateError as exc:
        capture_error = exc
    state_path = None
    save_error: Exception | None = None
    if context is not None:
        try:
            state_path = save_session_context(store_path, context)
        except OSError as exc:
            save_error = exc
    release = release_session(
        session_id, base_url=base_url, client=client, timeout=timeout
    )
    if capture_error is not None or save_error is not None:
        detail = capture_error if capture_error is not None else save_error
        raise SteelStateError(
            f"session state was not saved; session {session_id} released: {detail}"
        )
    return {
        "session_id": session_id,
        "state_path": str(state_path),
        "context": context,
        "release": release,
    }


def restore_session(
    store_path: str | os.PathLike[str],
    *,
    fields: dict | None = None,
    base_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Create a session that restores a previously stored context."""
    return create_session(
        load_session_context(store_path),
        fields=fields,
        base_url=base_url,
        client=client,
        timeout=timeout,
    )


__all__ = [
    "API_KEY_ENV",
    "SteelStateError",
    "capture_session_context",
    "create_session",
    "load_session_context",
    "release_session",
    "restore_session",
    "save_session_context",
    "teardown_with_state",
]
