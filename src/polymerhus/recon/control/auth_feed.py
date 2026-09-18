"""The auth feed (#223 T4 #243, D223-19): identifier-bound, lazily resolved,
per-phase projected auth material from the shared store.

The gateway verdict binds only the selected account's IDENTIFIER into the
pipeline state (`extra["auth_account"]`, never the material). Each phase's
tool configuration resolves that account from the auth store at the point of
use (the pipeline's per-job assembly, right before the phase runs) and
projects only the subset its tools need:

- request-based tools: the flat request material (headers/cookies) through
  the existing `extra["auth_context"]` transport, serialised per tool by
  `serialize_auth_flags` (the pod-side serialiser moved here unchanged -
  same flag tables, same reserved keys, same shell quoting);
- the crawler and browser tools: the account's persisted Steel profile key
  (`extra["steel_profile"]`, D223-14) plus the cookie subset for providers
  that seed the browser context;
- non-auth jobs: nothing - `use_auth` stays the single eligibility gate.

Role/default_role selection resolves over the account record
(`select_account_role`), replacing `select_auth_context` over the retired
settings blob (D223-4). The same selector serves caller-supplied
{roles, default_role} maps on the backward-recon seam (analysis/anatomy.py).

Fail-open throughout (D223-2): an unresolvable account projects to nothing,
loudly - collection runs unauthenticated, never blocked.
"""
from __future__ import annotations

import logging
import shlex
from typing import Iterator

logger = logging.getLogger(__name__)

# Keys the role selector strips: the role MAP and the default pointer. A
# selected role's set intentionally KEEPS `realm` (its own metadata tag) plus
# `cookies`/`credentials`; only the header serialiser drops `realm` below.
_STRUCTURAL_KEYS = ("roles", "default_role")


def select_account_role(account: dict | None, role: str | None = None) -> dict:
    """Return the credential set for `role`, resolved over the account record.

    Resolution order:

    - an explicit `role` -> that role's set under `account.roles` (an empty
      dict if the role is not configured - an unconfigured role gets NO
      creds, never another role's);
    - `role=None` + a configured `default_role` -> the default role's set;
    - `role=None` + no `default_role` -> the flat credentials: the record's
      own `credentials` when present, else the caller-supplied flat keys with
      the structural keys stripped (the backward-recon map shape).

    Never returns the `roles` / `default_role` structural keys, so the result
    is safe to hand straight to the header serialiser."""
    if not isinstance(account, dict):
        return {}
    roles = account.get("roles") or {}
    if role is None:
        role = account.get("default_role")
    if role is not None:
        selected = roles.get(role) or {}
        return dict(selected) if isinstance(selected, dict) else {}
    if isinstance(account.get("credentials"), dict):
        return dict(account["credentials"])
    return {k: v for k, v in account.items() if k not in _STRUCTURAL_KEYS}


def resolve_account(project_id: str, account_name: str, *, store=None) -> dict:
    """Read one account record from the shared store (fail-open to {}).

    `store` injects the bucket (tests); None resolves the production
    `AuthStore` lazily, so importing this module performs no I/O. A missing
    account or an unreadable store is a loud warn, never a raise - the caller
    runs that job unauthenticated (D223-2)."""
    try:
        if store is None:
            from polymerhus.app.auth.store import AuthStore  # noqa: PLC0415

            store = AuthStore()
        accounts = store.read(project_id, "accounts")
        if isinstance(accounts, dict):
            record = accounts.get(account_name)
            if isinstance(record, dict):
                return record
    except Exception:  # noqa: BLE001 - fail-open, loudly
        logger.warning("auth feed: account %r unresolvable for project %s; "
                       "running unauthenticated", account_name, project_id,
                       exc_info=True)
        return {}
    logger.warning("auth feed: account %r not on record for project %s; "
                   "running unauthenticated", account_name, project_id)
    return {}


def project_request_auth(account: dict | None) -> dict:
    """Project an account record onto the flat request material: snapshot
    headers plus header-located tokens as headers, snapshot cookies plus
    cookie-located tokens as the `cookies` list. Storage-located tokens are
    browser-bound and never replay over plain HTTP, so they are skipped."""
    if not isinstance(account, dict):
        return {}
    material: dict = {}
    snapshot = account.get("snapshot") or {}
    if isinstance(snapshot, dict):
        headers = snapshot.get("headers") or {}
        if isinstance(headers, dict):
            material.update({k: v for k, v in headers.items()
                             if isinstance(k, str) and isinstance(v, str) and v})
        cookies = snapshot.get("cookies") or []
        if isinstance(cookies, list):
            material["cookies"] = [
                c for c in cookies
                if isinstance(c, dict) and isinstance(c.get("name"), str)
                and isinstance(c.get("value"), str)]
    tokens = account.get("tokens") or {}
    if isinstance(tokens, dict):
        for name, entry in tokens.items():
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if not isinstance(value, str) or not value:
                continue
            location = entry.get("location")
            if location == "header" and isinstance(name, str) and name:
                material[name] = value
            elif location == "cookie" and isinstance(name, str) and name:
                material.setdefault("cookies", []).append(
                    {"name": name, "value": value})
    if not material or (set(material) == {"cookies"} and not material["cookies"]):
        return {}
    if "cookies" in material and not material["cookies"]:
        del material["cookies"]
    return material


def project_auth_cookies(account: dict | None) -> list:
    """The cookie subset of the request projection, for browser-context
    seeding providers. Empty when the account carries no cookies."""
    material = project_request_auth(account)
    cookies = material.get("cookies") or []
    return list(cookies) if isinstance(cookies, list) else []


def project_steel_profile(account: dict | None) -> str | None:
    """The account's persisted Steel profile key (D223-14), or None when the
    account mounts no profile."""
    if not isinstance(account, dict):
        return None
    steel = account.get("steel") or {}
    if isinstance(steel, dict):
        profile = steel.get("profile")
        if isinstance(profile, str) and profile:
            return profile
    return None


# Tools whose auth-cookie flag is `--headers "Cookie: ..."` rather than the
# `-H "Cookie: ..."` form shared by httpx/katana/ffuf/kiterunner (design §4 table).
_HEADERS_FLAG_TOOLS = {"arjun"}

# graphql-cop's own --headers format: ALL headers in one comma-joined
# "Key:Value,Key2:Value2" argument (no space after the colon) - distinct from
# both the default repeated -H flag and arjun's newline-joined --headers blob.
_COMMA_HEADERS_FLAG_TOOLS = {"graphql-cop"}

# The flat material is header-agnostic: `cookies` is the structured source of
# the `Cookie` header, and every OTHER key (except these reserved structural
# ones, which are not HTTP headers) is emitted verbatim as its own request
# header. The role/realm structural keys (`roles`, `default_role`, `realm`;
# the retired blob shape) stay reserved, so even a caller-supplied map that
# still carries them can never leak out as HTTP headers (defence in depth -
# the selector already strips roles/default_role; `realm` is a role's own
# metadata tag). `scope`/`credentials` are likewise never headers.
_RESERVED_AUTH_KEYS = {"cookies", "scope", "credentials", "roles", "default_role", "realm"}


def _iter_auth_headers(material: dict) -> Iterator[tuple[str, str]]:
    """Yield `(name, value)` HTTP header pairs from the flat material.

    - `cookies` (`[{name, value}, ...]`) is joined into the peculiar pair-form
      `Cookie` header value (`k=v; k2=v2`) - the Cookie header wants key=value
      pairs, not one opaque token.
    - every other key except the reserved structural keys is an arbitrary
      header (Authorization, X-Api-Key, ...), yielded verbatim. A literal
      `Cookie` key is skipped (the API layer rejects it; the `cookies` list
      is the one source of the Cookie header).
    """
    cookies = material.get("cookies") or []
    cookie_str = "; ".join(
        f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value")
    )
    if cookie_str:
        yield ("Cookie", cookie_str)
    for name, value in material.items():
        if name in _RESERVED_AUTH_KEYS or name.lower() == "cookie":
            continue
        if isinstance(value, str) and value:
            yield (name, value)


def serialize_auth_flags(material: dict | None, tool: str) -> str:
    """Serialize the flat request material into tool-appropriate header CLI flags.

    Header-agnostic: the `cookies` list becomes the `Cookie` header and any
    other key (except the reserved structural keys) becomes its own header.
    Every `name: value` is shell-quoted (`shlex`) so an operator-supplied
    token can never break the command string.

    `-H`-flag tools take one repeatable flag per header; arjun's `--headers`
    takes all headers in a single newline-separated argument; graphql-cop's
    `--headers` takes all headers in a single comma-joined `Key:Value`
    argument (no space after the colon). Returns "" when nothing applies, so
    a template's `{auth_flags}` slot collapses to nothing rather than leaving
    a dangling flag behind. Request-tool only - the Steel crawl injects
    cookies via CDP separately.
    """
    if not isinstance(material, dict) or not material:
        return ""
    pairs = list(_iter_auth_headers(material))
    if not pairs:
        return ""
    if tool in _HEADERS_FLAG_TOOLS:
        blob = "\n".join(f"{name}: {value}" for name, value in pairs)
        return f"--headers {shlex.quote(blob)}"
    if tool in _COMMA_HEADERS_FLAG_TOOLS:
        blob = ",".join(f"{name}:{value}" for name, value in pairs)
        return f"--headers {shlex.quote(blob)}"
    return " ".join(f"-H {shlex.quote(f'{name}: {value}')}" for name, value in pairs)
