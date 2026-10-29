"""The auth-replication gate (#395, Q6).

The authoritative signal is the recorded authenticated-context oracle
(`overview.auth_probe`): a browser request to that URL answers 2xx only for an
authenticated context, and 401/403/3xx for an unauthenticated one. The
provider asks that oracle before falling back to the legacy surface gate.

The legacy fallback trusts one of two signals:

- the response to an authenticated part of the surface is not a login
  redirect, a 401, a 403, or any other 3xx;
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
    # The oracle contract: a 3xx is not an authenticated context, even when a
    # browser follows it to a 200 login page. This is the legacy surface gate;
    # the recorded `auth_probe` is the authoritative oracle when present.
    if status is not None and 300 <= status <= 399:
        return {"authenticated": False, "reason": f"http_{status}"}
    if _storage_marker_present(storage, local_storage):
        return {"authenticated": True, "signal": "application_state"}
    if status is None or status == 0:
        return {"authenticated": False, "reason": "no_response"}
    if status >= 400:
        return {"authenticated": False, "reason": f"http_{status}"}
    return {"authenticated": True, "signal": "authenticated_surface"}


__all__ = ["evaluate_auth_gate"]
