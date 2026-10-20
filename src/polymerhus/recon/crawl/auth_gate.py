"""The auth-replication gate (#395, Q6).

A replicated session is not trusted until one of two signals verifies it:

- the response to an authenticated part of the surface is not a login
  redirect, a 401, or a 403;
- the live application state carries a replicated storage marker.

An explicit rejection wins over an application-state marker: stale storage
must never turn a 401 or a login redirect into a pass. The gate never passes
on a cookie name alone.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def _same_login_url(final_url: str | None, login_url: str | None) -> bool:
    if not final_url or not login_url:
        return False
    final = urlsplit(final_url)
    login = urlsplit(login_url)
    if (final.scheme, final.netloc) != (login.scheme, login.netloc):
        return False
    final_path = (final.path or "/").rstrip("/") or "/"
    login_path = (login.path or "/").rstrip("/") or "/"
    return final_path == login_path or final_path.startswith(login_path + "/")


def _storage_marker_present(storage: dict | None,
                            local_storage: dict | None) -> bool:
    if not isinstance(storage, dict) or not isinstance(local_storage, dict):
        return False
    for origin, expected in storage.items():
        if not isinstance(expected, dict):
            continue
        actual = local_storage.get(origin)
        if not isinstance(actual, dict):
            continue
        for key, value in expected.items():
            if actual.get(key) == value:
                return True
    return False


def evaluate_auth_gate(
    *,
    status: int | None,
    final_url: str | None,
    login_url: str | None = None,
    storage: dict | None = None,
    local_storage: dict | None = None,
) -> dict:
    """Return `{authenticated, signal|reason}` for one surface response."""
    if _same_login_url(final_url, login_url):
        return {"authenticated": False, "reason": "login_redirect"}
    if status in (401, 403):
        return {"authenticated": False, "reason": f"http_{status}"}
    if _storage_marker_present(storage, local_storage):
        return {"authenticated": True, "signal": "application_state"}
    if status is None or status == 0:
        return {"authenticated": False, "reason": "no_response"}
    if status >= 400:
        return {"authenticated": False, "reason": f"http_{status}"}
    return {"authenticated": True, "signal": "authenticated_surface"}


__all__ = ["evaluate_auth_gate"]
