"""Deterministic replay planning.

Replay accepts a closed vocabulary of *data* overrides - never a shell command,
never an expression. The source record is treated as immutable input; the
result is a fresh plan that the capture path sends.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kali.http_history.models import NameValue, RequestRecord

ALLOWED_OVERRIDES = frozenset(
    {
        "method",
        "url",
        "path",
        "query",
        "header",
        "headers",
        "cookie",
        "cookies",
        "body",
        "form",
        "json",
    }
)


class ReplayOverrideError(ValueError):
    """An override outside the closed vocabulary, or malformed."""


@dataclass
class ReplayPlan:
    method: str
    url: str
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""
    replay_kind: str = "baseline"


def _as_mapping(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ReplayOverrideError(f"{name!r} override must be an object")
    return {str(k): v for k, v in value.items()}


def _set_header(headers: list[tuple[str, str]], name: str, value: str) -> None:
    lowered = name.lower()
    headers[:] = [(k, v) for k, v in headers if k.lower() != lowered]
    headers.append((name, value))


def _cookie_header(cookies: list[NameValue]) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in cookies)


def apply_overrides(
    request: RequestRecord,
    body: bytes | None,
    overrides: dict | None,
) -> ReplayPlan:
    overrides = overrides or {}
    unknown = set(overrides) - ALLOWED_OVERRIDES
    if unknown:
        raise ReplayOverrideError(
            f"unsupported replay override(s): {sorted(unknown)}; allowed: "
            f"{sorted(ALLOWED_OVERRIDES)}"
        )

    method = str(overrides.get("method") or request.method or "GET").upper()
    url = str(overrides.get("url") or request.url or "")
    if "path" in overrides:
        parts = urlsplit(url)
        path = str(overrides["path"])
        if not path.startswith("/"):
            path = "/" + path
        url = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    if "query" in overrides:
        query_overrides = _as_mapping(overrides["query"], "query")
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        replaced = {name: value for name, value in pairs}
        order = [name for name, _ in pairs]
        for name, value in query_overrides.items():
            if name not in replaced:
                order.append(name)
            replaced[name] = value
        query = urlencode([(name, replaced[name]) for name in order])
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    headers = list(request.headers)
    header_overrides = {**_as_mapping(overrides.get("header", {}), "header"),
                        **_as_mapping(overrides.get("headers", {}), "headers")}
    for name, value in header_overrides.items():
        _set_header(headers, name, str(value))

    cookies = {c.name: c.value for c in request.cookies}
    cookie_overrides = {**_as_mapping(overrides.get("cookie", {}), "cookie"),
                        **_as_mapping(overrides.get("cookies", {}), "cookies")}
    if cookie_overrides:
        cookies.update({str(k): str(v) for k, v in cookie_overrides.items()})
        _set_header(headers, "cookie", _cookie_header([NameValue(name=k, value=v) for k, v in cookies.items()]))

    new_body = body or b""
    if "body" in overrides:
        raw = overrides["body"]
        new_body = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
    if "form" in overrides:
        form_overrides = _as_mapping(overrides["form"], "form")
        new_body = urlencode([(k, v) for k, v in form_overrides.items()]).encode("utf-8")
        _set_header(headers, "content-type", "application/x-www-form-urlencoded")
    if "json" in overrides:
        new_body = json.dumps(overrides["json"]).encode("utf-8")
        _set_header(headers, "content-type", "application/json")

    return ReplayPlan(
        method=method,
        url=url,
        headers=headers,
        body=new_body,
        replay_kind="mutated" if overrides else "baseline",
    )
