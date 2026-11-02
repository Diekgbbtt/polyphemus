"""The authenticated-context oracle (#223 amendment, 2026-10-29).

The one deterministic question the auth gateway asks is whether the loaded
browser session carries an authenticated context. The oracle answers it with a
URL that the external bootstrapper (or the recon orchestrator) proved is
reachable only with authentication:

- 2xx: the context is authenticated;
- 401, 403, or any 3xx: the context is not authenticated;
- anything else (network error, 5xx, 4xx other than 401/403): indeterminate.

A 3xx is a failure even when the browser follows it to a 200 page. A redirect
to a login page is not an authenticated landing.

The stored probe path is deployment-neutral (for example `/api/me`). The
model-facing auth-store read and the browser feed resolve it against the
project's canonical origin, so the artifact never bakes in a host.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

PROBE_KEY = "auth_probe"
"""The overview key carrying the oracle: `{url: <path or absolute URL>}`."""

ProbeOutcome = Literal["authenticated", "unauthenticated", "indeterminate"]
"""The oracle's three outcomes. Only `authenticated` passes."""

AUTHENTICATED: ProbeOutcome = "authenticated"
UNAUTHENTICATED: ProbeOutcome = "unauthenticated"
INDETERMINATE: ProbeOutcome = "indeterminate"


def auth_probe_url(overview: Any) -> str | None:
    """The stored probe URL from an overview, or None when absent/malformed.

    A valid value is a root-relative path (`/api/me`) or an absolute http(s)
    URL (agent-minted live state). The data-dependency validator forbids the
    absolute form in committed artifacts; the store accepts both so a live
    agent write is never refused. Malformed input yields None, never a raise.
    """
    if not isinstance(overview, Mapping):
        return None
    probe = overview.get(PROBE_KEY)
    if not isinstance(probe, Mapping):
        return None
    url = probe.get("url")
    if not isinstance(url, str) or not url:
        return None
    return url


def resolve_auth_probe(overview: Any, origin: str | None) -> str | None:
    """Resolve the stored probe against `origin` when it is a relative path.

    An absolute URL is returned unchanged (agent-minted live state). A
    relative path with no origin is returned unchanged: the browser resolves
    it against the page it is already on, and the caller can still use it.
    """
    url = auth_probe_url(overview)
    if url is None:
        return None
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return url
    if not origin:
        return url
    return f"{origin.rstrip('/')}/{url.lstrip('/')}"


def classify_probe(
    *,
    status: int | None,
    redirected: bool = False,
) -> ProbeOutcome:
    """Classify one browser response to the oracle.

    `redirected` is the browser fetch's own flag. A followed redirect is a
    3xx by contract, even when the final response is 2xx: an unauthenticated
    request that lands on a login page must not pass. A missing status or any
    status outside the fixed sets is indeterminate, never a pass.
    """
    if redirected:
        return UNAUTHENTICATED
    if status is None:
        return INDETERMINATE
    if 200 <= status <= 299:
        return AUTHENTICATED
    if status in (401, 403) or 300 <= status <= 399:
        return UNAUTHENTICATED
    return INDETERMINATE


def is_valid_probe_url(url: str) -> bool:
    """Whether `url` is a well-formed oracle target.

    Root-relative paths are the deployment-neutral form. Absolute URLs are
    accepted for agent-minted live state, but only http(s), with a host and
    no userinfo. Fragments and whitespace are refused: a fragment never
    reaches the server, so it cannot be the oracle.
    """
    if not isinstance(url, str) or not url:
        return False
    if any(ch in url for ch in "\r\n\t ") or "#" in url:
        return False
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and not parsed.username
            and not parsed.password
        )
    return url.startswith("/") and not url.startswith("//")


__all__ = [
    "PROBE_KEY",
    "ProbeOutcome",
    "AUTHENTICATED",
    "UNAUTHENTICATED",
    "INDETERMINATE",
    "auth_probe_url",
    "resolve_auth_probe",
    "classify_probe",
    "is_valid_probe_url",
]
