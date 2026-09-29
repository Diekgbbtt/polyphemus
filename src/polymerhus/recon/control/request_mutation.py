# src/polymerhus/recon/control/request_mutation.py
"""The #238 follow-up mutation transport (#238 design section 10).

`apply_mutation` is the ONE pure controller function that turns a CANONICAL
request plus a typed, closed mutation into the EFFECTIVE request Kali must put on
the wire. Two properties are load-bearing:

* the canonical request is IMMUTABLE - the function returns a new value and never
  edits its input (both are frozen pydantic models);
* a mutation can never broaden the target scope: the effective URL's scheme and
  authority must equal the canonical's, or the mutation is refused.

The value it produces (`EffectiveRequest`) is what crosses the MCP/Kali seam, so
Kali never reinterprets a mutation - it executes the already-materialized
request. No header value or body content is ever logged here.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.domain.rate_limit import (
    BodyMutation,
    HeaderMutation,
    Mutation,
    PathMutation,
    QueryMutation,
)

CANONICAL_MUTATION_ID = "canonical"
"""The `mutation_id` of an effective request that applies no mutation at all."""

_FORBIDDEN_HEADERS = frozenset({"host"})
"""A `Host` header would retarget the request to another virtual host, which is
a scope change, not a bounded mutation."""


class CanonicalRequest(BaseModel):
    """The unmutated request shape. `headers` is an ordered tuple of pairs so the
    caller's duplicates survive into `apply_mutation` (which then follows HTTP
    list semantics)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str = "GET"
    url: str
    headers: tuple[tuple[str, str], ...] = ()
    body_ref: str | None = None


class EffectiveRequest(BaseModel):
    """The concrete request to execute: method, URL, allowed headers, and an
    optional body REFERENCE (never inline content). `mutation_id` is the
    evidence-correlation handle back to the variant that produced it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mutation_id: str = CANONICAL_MUTATION_ID
    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body_ref: str | None = None


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc


def _apply_query(url: str, mutation: QueryMutation) -> str:
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if mutation.replace:
        pairs = [(k, v) for k, v in pairs if k != mutation.name]
    pairs.append((mutation.name, mutation.value))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def _apply_path(url: str, mutation: PathMutation) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path + mutation.suffix, parts.query,
         parts.fragment)
    )


def apply_mutation(
    request: CanonicalRequest, mutation: Mutation | None
) -> EffectiveRequest:
    """Materialize the effective request exactly once. `mutation=None` returns the
    canonical request unchanged (with `mutation_id="canonical"`). The caller's
    `request` is never modified."""
    headers = {name: value for name, value in request.headers}
    url = request.url
    body_ref = request.body_ref
    mutation_id = CANONICAL_MUTATION_ID

    if isinstance(mutation, HeaderMutation):
        if mutation.name.strip().lower() in _FORBIDDEN_HEADERS:
            raise ValueError(
                f"a {mutation.name!r} header mutation would retarget the request"
            )
        mutation_id = mutation.mutation_id
        if mutation.replace or mutation.name not in headers:
            headers[mutation.name] = mutation.value
        else:
            headers[mutation.name] = f"{headers[mutation.name]}, {mutation.value}"
    elif isinstance(mutation, QueryMutation):
        mutation_id = mutation.mutation_id
        url = _apply_query(url, mutation)
    elif isinstance(mutation, PathMutation):
        mutation_id = mutation.mutation_id
        url = _apply_path(url, mutation)
    elif isinstance(mutation, BodyMutation):
        mutation_id = mutation.mutation_id
        body_ref = mutation.body_ref
    elif mutation is not None:
        raise TypeError(f"unsupported mutation type: {type(mutation).__name__}")

    if _origin(url) != _origin(request.url):
        raise ValueError("a mutation must not change the request's scheme or host")

    return EffectiveRequest(
        mutation_id=mutation_id,
        method=request.method,
        url=url,
        headers=headers,
        body_ref=body_ref,
    )
