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
- the crawl and browser tools: the decoupled auth-context reference
  (`extra["browser_context_ref"]`) plus the gate metadata
  (`extra["browser_auth"]`: `auth_probe` and `login_url`; the pool store owns
  the context object);
- non-auth jobs: nothing - `use_auth` stays the single eligibility gate.

Role/default_role selection resolves over the account record
(`select_account_role`), replacing `select_auth_context` over the retired
settings blob (D223-4). The same selector serves caller-supplied
{roles, default_role} maps on the backward-recon seam (analysis/anatomy.py).

The helpers never raise: an unreadable store or a missing record returns an
empty projection, loudly. The pipeline treats an unresolvable GATEWAY-SELECTED
account as a fail-closed stop (D223-21), so a projection miss never becomes a
silent anonymous run.
"""
from __future__ import annotations

import logging
import shlex
from collections.abc import Mapping
from typing import Iterator
from urllib.parse import urlsplit

from polymerhus.app.auth.probe import resolve_auth_probe

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
    roles = account.get("roles")
    if not isinstance(roles, dict):
        roles = {}  # a malformed store shape degrades to no roles, never a raise
    if role is None:
        role = account.get("default_role")
    if role is not None:
        selected = roles.get(role) or {}
        return dict(selected) if isinstance(selected, dict) else {}
    if isinstance(account.get("credentials"), dict):
        return dict(account["credentials"])
    return {k: v for k, v in account.items() if k not in _STRUCTURAL_KEYS}


def resolve_account(project_id: str, account_name: str, *, store=None) -> dict:
    """Read one account record from the shared store (empty on a miss).

    `store` injects the bucket (tests); None resolves the production
    `AuthStore` lazily, so importing this module performs no I/O. A missing
    account or an unreadable store is a loud warn, never a raise; the pipeline
    fails closed when the gateway-selected account does not resolve
    (D223-21)."""
    try:
        if store is None:
            from polymerhus.app.auth.store import AuthStore  # noqa: PLC0415

            store = AuthStore()
        accounts = store.read(project_id, "accounts")
        if isinstance(accounts, dict):
            record = accounts.get(account_name)
            if isinstance(record, dict):
                return record
    except Exception:  # noqa: BLE001 - never a raise; the caller fails closed
        logger.warning("auth feed: account %r unresolvable for project %s",
                       account_name, project_id, exc_info=True)
        return {}
    logger.warning("auth feed: account %r not on record for project %s",
                   account_name, project_id)
    return {}


def resolve_accounts(project_id: str, *, store=None) -> dict:
    """Read the full account map for the crawl's session fan-out.

    A missing or unreadable store is a loud empty map; the caller's empty-map
    path is the anonymous fallback, never a crash."""
    try:
        if store is None:
            from polymerhus.app.auth.store import AuthStore  # noqa: PLC0415

            store = AuthStore()
        accounts = store.read(project_id, "accounts")
        if isinstance(accounts, dict):
            return accounts
    except Exception:  # noqa: BLE001 - fail-open, loudly
        logger.warning(
            "auth feed: accounts unresolvable for project %s",
            project_id,
            exc_info=True,
        )
    return {}


def resolve_overview(project_id: str, *, store=None) -> dict:
    """Read the operator-owned overview (the login-mechanism header fact)
    from the shared store (fail-open to {}).

    `store` injects the bucket (tests); None resolves the production
    `AuthStore` lazily, so importing this module performs no I/O. A missing
    overview or an unreadable store is a loud warn, never a raise - the
    caller projects with no headers."""
    try:
        if store is None:
            from polymerhus.app.auth.store import AuthStore  # noqa: PLC0415

            store = AuthStore()
        overview = store.read(project_id, "overview")
        if isinstance(overview, dict) and overview:
            return overview
    except Exception:  # noqa: BLE001 - fail-open, loudly
        logger.warning("auth feed: overview unresolvable for project %s; "
                       "projecting no headers", project_id, exc_info=True)
        return {}
    logger.warning("auth feed: no overview on record for project %s; "
                   "projecting no headers", project_id)
    return {}


def _parse_required_headers(overview: dict | None) -> dict:
    """Parse `overview.required_headers` (a list of `"Name: value"` strings)
    into a header map, split on the FIRST colon. A malformed entry (no
    colon, an empty name/value, a non-string) is skipped with a warning,
    never fatal - the header set degrades, the run never blocks."""
    if not isinstance(overview, dict):
        return {}
    required = overview.get("required_headers") or []
    if not isinstance(required, list):
        logger.warning("auth feed: overview required_headers is not a list; "
                       "projecting no headers")
        return {}
    headers: dict = {}
    for entry in required:
        if not isinstance(entry, str) or ":" not in entry:
            logger.warning("auth feed: skipping malformed required header "
                           "entry %r (want 'Name: value')", entry)
            continue
        name, _, value = entry.partition(":")
        name, value = name.strip(), value.strip()
        if not name or not value:
            logger.warning("auth feed: skipping malformed required header "
                           "entry %r (want 'Name: value')", entry)
            continue
        headers[name] = value
    return headers


def _dedupe_cookies(cookies: list[dict], *, replace: bool = True) -> list[dict]:
    """One cookie per name, first-seen order.

    With `replace=True` a later entry replaces the value; with `replace=False`
    the first entry wins. The snapshot uses first-wins (a repeated capture is
    the same cookie), and the token list then overrides the snapshot by name:
    the token entry is the deliberate auth fact.
    """
    merged: dict[str, dict] = {}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(value, str):
            continue
        if name in merged and not replace:
            continue
        merged[name] = {"name": name, "value": value}
    return list(merged.values())


def project_request_auth(account: dict | None,
                         overview: dict | None = None) -> dict:
    """Project an account record onto the flat request material.

    The header fact single-sources on the overview: `overview`'s
    `required_headers` plus header-located tokens as headers; the snapshot
    supplies cookies only (a stale `snapshot.headers` is ignored, never
    replayed), plus cookie-located tokens as the `cookies` list.
    Storage-located tokens are browser-bound and never replay over plain
    HTTP, so they are skipped. An absent/empty overview projects no headers,
    never a crash. Cookies are deduped by name: the token entry wins a
    collision, and duplicate snapshot names keep the first value."""
    if not isinstance(account, dict):
        return {}
    material: dict = {}
    material.update(_parse_required_headers(overview))
    snapshot_cookies: list[dict] = []
    token_cookies: list[dict] = []
    snapshot = account.get("snapshot") or {}
    if isinstance(snapshot, dict):
        cookies = snapshot.get("cookies") or []
        if isinstance(cookies, list):
            snapshot_cookies.extend(cookies)
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
                token_cookies.append({"name": name, "value": value})
    cookies = _dedupe_cookies(snapshot_cookies, replace=False)
    if token_cookies:
        cookies = _dedupe_cookies(cookies + token_cookies, replace=True)
    if cookies:
        material["cookies"] = cookies
    return material


def _account_probe(account: dict, origin: str | None) -> str | None:
    """The account's own probe, then its root URL, resolved against origin."""
    for key in ("auth_probe", "root_url"):
        value = account.get(key)
        if not isinstance(value, str) or not value:
            continue
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            return value
        if not origin:
            return value
        return f"{origin.rstrip('/')}/{value.lstrip('/')}"
    return None


def project_browser_auth(account: dict | None,
                         overview: dict | None = None,
                         origin: str | None = None) -> dict:
    """Project an account onto the crawl's gate metadata.

    The pool store is the only browser-state store, so this projection carries
    NO cookie, header, or storage values: the browser MCP restores them from
    the account's decoupled auth context. The only crawl inputs are the
    account's oracle (`auth_probe`, falling back to its `root_url`) and the
    optional `login_url` used by the legacy surface gate. The overview probe
    is the legacy fallback for an account that declares neither.

    An absent/empty projection carries no probe; an account without a login URL
    projects no login URL. The result is empty when neither exists."""
    if not isinstance(account, dict):
        return {}
    material: dict = {}
    probe = _account_probe(account, origin) or resolve_auth_probe(overview, origin)
    if probe:
        material["auth_probe"] = probe
    credentials = account.get("credentials")
    if isinstance(credentials, dict):
        login_url = credentials.get("login_url")
        if isinstance(login_url, str) and login_url:
            material["login_url"] = login_url
    return material


def project_browser_context(
    account: dict | None,
    *,
    project_id: str | None = None,
    account_name: str | None = None,
) -> str | None:
    """The account's decoupled auth-context reference, or None.

    The reference points to the browser-state object in the pool store. The
    auth store never holds the object. A stored reference wins; without one,
    the deterministic context key for the project and account is the contract.
    The retired `steel.state` key is not read.
    """
    if not isinstance(account, dict):
        return None
    stored = account.get("browser_context")
    ref = stored.get("ref") if isinstance(stored, dict) else None
    if project_id and account_name:
        from polymerhus.app.llm.browser_tools import (  # noqa: PLC0415
            browser_context_ref,
        )

        # The deterministic key is the contract. A stale value may name
        # another project's context; the project and account are the truth.
        return browser_context_ref(project_id, account_name)
    if isinstance(ref, str) and ref.startswith("steel-auth-"):
        return ref
    return None


def project_sessions(
    project_id: str,
    accounts: Mapping[str, dict] | None,
    *,
    origin: str | None = None,
) -> list[dict]:
    """One JSON-ready crawl session per account.

    The account is the session: its `role` (or `default_role`) names the
    privilege surface, `root_url` is that surface's featured entry (default
    `/`), and `auth_probe` is that session's own oracle. A missing or empty
    probe is deliberately `None`: the crawl falls back to the root URL.

    `origin` resolves the committed root-relative paths against the target's
    canonical origin. The pool record carries the resulting absolute values.
    A malformed account is skipped; an empty account map is the anonymous
    fallback, which the crawl pod owns.
    """
    if not isinstance(accounts, Mapping):
        return []
    sessions: list[dict] = []
    for account_name, account in accounts.items():
        if not isinstance(account_name, str) or not isinstance(account, dict):
            continue
        if account.get("status") == "not_valid":
            continue
        role = account.get("role")
        if not isinstance(role, str) or not role:
            role = account.get("default_role")
        if not isinstance(role, str) or not role:
            role = None
        root = account.get("root_url")
        if not isinstance(root, str) or not root:
            root = "/"
        root_url = _resolve_session_url(root, origin)
        probe = account.get("auth_probe")
        auth_probe = (
            _resolve_session_url(probe, origin)
            if isinstance(probe, str) and probe
            else None
        )
        credentials = account.get("credentials")
        login_url = (
            credentials.get("login_url")
            if isinstance(credentials, dict)
            and isinstance(credentials.get("login_url"), str)
            and credentials.get("login_url")
            else None
        )
        procedure = account.get("procedure")
        sessions.append(
            {
                "account": account_name,
                "role": role,
                "root_url": root_url,
                "auth_probe": auth_probe,
                "login_url": login_url,
                "browser_context_ref": project_browser_context(
                    account,
                    project_id=project_id,
                    account_name=account_name,
                ),
                "procedure": (
                    procedure
                    if isinstance(procedure, str) and procedure
                    else None
                ),
                "anonymous": False,
            }
        )
    return sessions


def _resolve_session_url(value: str, origin: str | None) -> str:
    """Resolve a session URL against the target origin; keep absolute URLs."""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return value
    if not origin:
        return value
    return f"{origin.rstrip('/')}/{value.lstrip('/')}"


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
