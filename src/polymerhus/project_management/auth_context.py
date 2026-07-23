"""The AuthContext value-object contract and its validation invariant.

`auth_context` is the operator's declaration of how authenticated recon should
authenticate: an optional `cookies` list, an optional autonomous-login
`credentials` set (D23), optional role/realm-tagged credential sets (FR-AUTH),
and otherwise arbitrary HTTP headers emitted verbatim by the request-based
tools. It is a value object - defined wholly by its attributes, replaced rather
than mutated - so its invariant lives here, in one place, independent of both
the HTTP surface (api.py) that receives it and the settings use-case
(repository.save_project_settings) that persists it.
"""
from __future__ import annotations

import re

# auth_context keys that are structural, NOT HTTP headers. Every other key is
# treated as an arbitrary request header (name -> string value). `roles` /
# `default_role` tag multiple credential sets (FR-AUTH); `realm` tags a set's
# origin (credential vs IdP). This mirrors the header serialiser's reserved set
# (pod._RESERVED_AUTH_KEYS); the selector's auth._STRUCTURAL_KEYS is deliberately
# narrower (it keeps `realm` in a selected role's set - see that module's note).
_RESERVED_AUTH_CONTEXT_KEYS = {"cookies", "scope", "credentials", "roles", "default_role", "realm"}
# RFC 7230 header field-names are tokens; we accept the realistic subset
# (letters, digits, hyphen) that covers every auth header (Authorization,
# X-Api-Key, ...) and excludes shell/CRLF-dangerous characters.
_HTTP_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")


def validate_auth_context(auth_context: object) -> None:
    """Raise ValueError on any shape violation of the AuthContext contract:
    a dict with an OPTIONAL `cookies` list (each `{name, value}`), an optional
    string `scope`, and optional `credentials`.

    `cookies` (request-based crawling) and `credentials` (agentic login, D23-2)
    are INDEPENDENT items. A partial PUT may set either without the other, so
    an absent `cookies` key is valid; only a present-but-malformed one is an
    error. The registry merges partial PUTs recursively (see pg.save_settings)
    so setting one item never wipes the other."""
    if not isinstance(auth_context, dict):
        raise ValueError("auth_context must be an object")

    cookies = auth_context.get("cookies")
    if cookies is not None:
        if not isinstance(cookies, list):
            raise ValueError("auth_context.cookies must be a list")
        for cookie in cookies:
            if not isinstance(cookie, dict) or "name" not in cookie or "value" not in cookie:
                raise ValueError("each auth_context.cookies entry must be {name, value}")
            if not isinstance(cookie["name"], str) or not isinstance(cookie["value"], str):
                raise ValueError("auth_context.cookies entries must have string name/value")

    scope = auth_context.get("scope")
    if scope is not None and not isinstance(scope, str):
        raise ValueError("auth_context.scope must be a string")

    # D23: optional autonomous-login credentials (username/password/login_url
    # required; domain + form selectors optional). Absent is valid.
    credentials = auth_context.get("credentials")
    if credentials is not None:
        if not isinstance(credentials, dict):
            raise ValueError("auth_context.credentials must be an object")
        for field in ("username", "password", "login_url"):
            if not isinstance(credentials.get(field), str) or not credentials[field]:
                raise ValueError(f"auth_context.credentials.{field} must be a non-empty string")
        for field in ("domain", "username_selector", "password_selector", "submit_selector"):
            if field in credentials and not isinstance(credentials[field], str):
                raise ValueError(f"auth_context.credentials.{field} must be a string")

    # Arbitrary HTTP headers: auth_context is header-agnostic, so every key that
    # is not a reserved structural key is an HTTP header name -> string value,
    # emitted verbatim on the request-based tools (Authorization, X-Api-Key,
    # ...). `cookies` stays the one source of the `Cookie` header, so a literal
    # `Cookie` header is refused to avoid two sources of truth.
    for name, value in auth_context.items():
        if name in _RESERVED_AUTH_CONTEXT_KEYS:
            continue
        if name.lower() == "cookie":
            raise ValueError(
                "auth_context: set cookies via the `cookies` list, not a `Cookie` header"
            )
        if not _HTTP_HEADER_NAME_RE.match(name):
            raise ValueError(
                f"auth_context header name {name!r} is not a valid HTTP header token"
            )
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"auth_context header {name!r} value must be a non-empty string"
            )
        if "\r" in value or "\n" in value:
            raise ValueError(
                f"auth_context header {name!r} value must not contain CR or LF"
            )

    # FR-AUTH: optional role/realm-tagged credential sets. Each role's set is
    # itself a flat credential set, so it is validated by the SAME rules (recurse);
    # `roles`/`default_role`/`realm` are reserved, so the header loop above already
    # skipped them. A partial PUT setting one role deep-merges (pg.save_settings),
    # never wiping a sibling role.
    roles = auth_context.get("roles")
    if roles is not None:
        if not isinstance(roles, dict):
            raise ValueError("auth_context.roles must be an object mapping role -> credential set")
        for role_name, role_set in roles.items():
            if not isinstance(role_set, dict):
                raise ValueError(f"auth_context.roles.{role_name} must be an object")
            validate_auth_context(role_set)  # a role's set is a flat auth_context
    default_role = auth_context.get("default_role")
    if default_role is not None:
        if not isinstance(default_role, str):
            raise ValueError("auth_context.default_role must be a string")
        if default_role not in (roles or {}):
            raise ValueError(
                f"auth_context.default_role {default_role!r} has no matching entry in roles"
            )
    realm = auth_context.get("realm")
    if realm is not None and not isinstance(realm, str):
        raise ValueError("auth_context.realm must be a string")
