"""The auth record shapes and their validation invariant (#220, T1).

Pure logic, no I/O: importing this module touches no driver, no file, and
needs no env var (CODING_STANDARD section 6). The record rules mirror the
retired settings-blob validator's shape rules (credential fields,
`{name, value}` cookies, the header-name token rule, no literal `Cookie`
header, no CR/LF, role-shape discipline) plus the new closed origin/location
enums and the steel-reference / request-snapshot shapes - mirrored, never
imported upward, since the shared bottom must not point at the operator
surface (D220-7). The blob validator itself is retired (#223 T4 #243, D223-4).

Record-level keys are a closed contract (anything else is a loud refusal);
nested entry bags follow the mirrored lenient posture (required keys
enforced, extras tolerated) except where the spec closes them.
"""
from __future__ import annotations

import copy
import re


class AuthInvalidError(ValueError):
    """The denoted refusal: names the offending field in both the message
    and the `field` attribute, so callers (tool, seed face) can quote it."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"auth_invalid: {field} {reason}")
        self.field = field


def _fail(field: str, reason: str) -> None:
    raise AuthInvalidError(field, reason)


_OVERVIEW_KEYS = frozenset(
    {
        "login_endpoint",
        "required_headers",
        "mechanism",
        "defences",
        "fingerprinting",
        "technical_conditions",
        "anti-bot",
        "http-client-replayability",
        "notes",
    }
)

_ACCOUNT_KEYS = frozenset(
    {
        "origin",
        "procedure",
        "credentials",
        "tokens",
        "steel",
        "snapshot",
        "notes",
        "roles",
        "default_role",
        # #223 D223-14/D223-18 (settled): the loop-asserted validity fact and
        # the server-stamped selection-recency fact. Both are validated here;
        # `updated_at` is STAMPED by the store (never trusted from the client).
        "status",
        "updated_at",
    }
)

# #223 D223-14 (settled): the typed validity fact the loop writes when it
# validates or fails a session - absent until asserted, never any third value.
_ACCOUNT_STATUSES = frozenset({"valid", "not_valid"})

_ORIGINS = frozenset({"operator", "agent"})


_CREDENTIAL_OPTIONAL_STRINGS = frozenset(
    {"domain", "username_selector", "password_selector", "submit_selector"}
)

# Mirror of the retired settings-blob header-name rule: RFC
# 7230 field-names are tokens; the realistic subset (letters, digits, hyphen)
# covers every auth header and excludes shell/CRLF-dangerous characters.
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")

_SNAPSHOT_KEYS = frozenset({"headers", "cookies", "params", "captured_at"})


def _check_credentials(credentials: object, field: str) -> None:
    # Mirror of the D23 credential rules: username/password/login_url are
    # required non-empty strings; domain + form selectors are optional
    # strings. Nested bags stay lenient (extras tolerated).
    if not isinstance(credentials, dict):
        _fail(field, "must be an object")
    for required in ("username", "password", "login_url"):
        value = credentials.get(required)
        if not isinstance(value, str) or not value:
            _fail(f"{field}.{required}", "must be a non-empty string")
    for optional in _CREDENTIAL_OPTIONAL_STRINGS:
        if optional in credentials and not isinstance(credentials[optional], str):
            _fail(f"{field}.{optional}", "must be a string")


def _check_snapshot(snapshot: object) -> None:
    if not isinstance(snapshot, dict):
        _fail("account.snapshot", "must be an object")
    for key in snapshot:
        if key not in _SNAPSHOT_KEYS:
            _fail(f"account.snapshot.{key}", "is not a known snapshot field")
    headers = snapshot.get("headers")
    if headers is not None:
        if not isinstance(headers, dict):
            _fail("account.snapshot.headers", "must be an object")
        _check_header_map(headers, "account.snapshot.headers")
    cookies = snapshot.get("cookies")
    if cookies is not None:
        if not isinstance(cookies, list):
            _fail("account.snapshot.cookies", "must be a list")
        for i, cookie in enumerate(cookies):
            cookie_field = f"account.snapshot.cookies[{i}]"
            if (
                not isinstance(cookie, dict)
                or not isinstance(cookie.get("name"), str)
                or not isinstance(cookie.get("value"), str)
            ):
                _fail(cookie_field, "must be {name, value} with string name/value")
            for slot in ("name", "value"):
                if "\r" in cookie[slot] or "\n" in cookie[slot]:
                    _fail(cookie_field, f"{slot} must not contain CR or LF")
    params = snapshot.get("params")
    if params is not None:
        if not isinstance(params, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in params.items()
        ):
            _fail("account.snapshot.params", "must be an object of string to string")
    if "captured_at" in snapshot and not isinstance(snapshot["captured_at"], str):
        _fail("account.snapshot.captured_at", "must be a string")


def _check_header_map(headers: dict, field: str) -> None:
    # Mirror of the retired settings-blob header loop: `cookies` stays the one
    # source of the `Cookie` header (a literal one is refused to avoid two
    # sources of truth); names must be header tokens; values are non-empty
    # CR/LF-free.
    for name, value in headers.items():
        entry_field = f"{field}.{name}"
        if not isinstance(name, str) or not _HEADER_NAME_RE.match(name):
            _fail(entry_field, "is not a valid HTTP header token")
        if name.lower() == "cookie":
            _fail(entry_field, "set cookies via the `cookies` list, not a `Cookie` header")
        if not isinstance(value, str) or not value:
            _fail(entry_field, "value must be a non-empty string")
        if "\r" in value or "\n" in value:
            _fail(entry_field, "value must not contain CR or LF")


_TOKEN_LOCATIONS = frozenset({"cookie", "header", "storage"})


def _check_tokens(tokens: object) -> None:
    if not isinstance(tokens, dict):
        _fail("account.tokens", "must be an object")
    for name, entry in tokens.items():
        token_field = f"account.tokens.{name}"
        if not isinstance(name, str) or not name:
            _fail("account.tokens", "token names must be non-empty strings")
        if not isinstance(entry, dict):
            _fail(token_field, "must be an object")
        value = entry.get("value")
        if not isinstance(value, str) or not value:
            _fail(f"{token_field}.value", "must be a non-empty string")
        if "\r" in value or "\n" in value:
            _fail(f"{token_field}.value", "must not contain CR or LF")
        location = entry.get("location")
        if location not in _TOKEN_LOCATIONS:
            _fail(f"{token_field}.location", "must be cookie, header, or storage")
        if location == "header":
            # A header-located token is emitted under its own name, so the
            # name keeps the header-name rule and `Cookie` stays reserved for
            # the `cookies` list (same mirror as the snapshot header map).
            if not _HEADER_NAME_RE.match(name):
                _fail(token_field, "a header-located token name must be a valid HTTP header token")
            if name.lower() == "cookie":
                _fail(token_field, "set cookies via the `cookies` list, not a `Cookie` token")
        for optional in ("target", "expiry"):
            if optional in entry and not isinstance(entry[optional], str):
                _fail(f"{token_field}.{optional}", "must be a string")


def _check_steel(steel: object) -> None:
    # The minimal durable reference: the cloud profile key only (D220-4).
    # Nothing else is required, so extras ride along unchecked.
    if not isinstance(steel, dict):
        _fail("account.steel.profile", "must be an object carrying a profile")
    profile = steel.get("profile")
    if not isinstance(profile, str) or not profile:
        _fail("account.steel.profile", "must be a non-empty string")


def validate_overview(record: object) -> dict:
    """Validate an operator-owned login-mechanism overview (all fields
    optional): value in, validated value out, denoted refusal on violation."""
    if not isinstance(record, dict):
        _fail("overview", "must be an object")
    for key in record:
        if key not in _OVERVIEW_KEYS:
            _fail(f"overview.{key}", "is not a known overview field")
    for key in (
        "login_endpoint",
        "mechanism",
        "fingerprinting",
        "notes",
    ):
        if key in record and not isinstance(record[key], str):
            _fail(f"overview.{key}", "must be a string")
    for key in ("required_headers", "defences"):
        if key in record and (
            not isinstance(record[key], list)
            or not all(isinstance(v, str) and v for v in record[key])
        ):
            _fail(f"overview.{key}", "must be a list of non-empty strings")
    # #237: the anti-bot defence type (a free-form vendor/challenge name, or
    # null for none) and the HTTP-client replayability fact (a real boolean;
    # absent or null is UNKNOWN, deliberately distinct from a recorded false).
    anti_bot = record.get("anti-bot")
    if anti_bot is not None and (not isinstance(anti_bot, str) or not anti_bot):
        _fail("overview.anti-bot", "must be a non-empty string or null")
    replayability = record.get("http-client-replayability")
    if replayability is not None and not isinstance(replayability, bool):
        _fail("overview.http-client-replayability", "must be a boolean or null")
    conditions = record.get("technical_conditions")
    if conditions is not None:
        if not isinstance(conditions, list):
            _fail("overview.technical_conditions", "must be a list")
        for i, entry in enumerate(conditions):
            entry_field = f"overview.technical_conditions[{i}]"
            if not isinstance(entry, dict):
                _fail(entry_field, "must be an object")
            for required in ("name", "check"):
                value = entry.get(required)
                if not isinstance(value, str) or not value:
                    _fail(entry_field, f"must carry a non-empty string {required!r}")
    return copy.deepcopy(record)


def validate_account(record: object) -> dict:
    """Validate one named account bundle (credentials, tokens, steel
    reference, request snapshot, the loop-asserted validity fact, the
    server-stamped recency fact): value in, validated value out."""
    if not isinstance(record, dict):
        _fail("account", "must be an object")
    for key in record:
        if key not in _ACCOUNT_KEYS:
            _fail(f"account.{key}", "is not a known account field")
    if record.get("origin") not in _ORIGINS:
        _fail("account.origin", 'must be "operator" or "agent"')
    procedure = record.get("procedure")
    if procedure is not None and (not isinstance(procedure, str) or not procedure):
        _fail("account.procedure", "must be a non-empty string")
    credentials = record.get("credentials")
    if credentials is not None:
        _check_credentials(credentials, "account.credentials")
    roles = record.get("roles")
    if roles is not None:
        # Mirror of the FR-AUTH role discipline at account level: each role's
        # set is itself a credential set, validated by the SAME rules
        # (recurse); `default_role` must name a configured role.
        if not isinstance(roles, dict):
            _fail("account.roles", "must be an object mapping role to credential set")
        for role_name, role_set in roles.items():
            _check_credentials(role_set, f"account.roles.{role_name}")
    default_role = record.get("default_role")
    if default_role is not None:
        if not isinstance(default_role, str) or default_role not in (roles or {}):
            _fail("account.default_role", "must name a configured entry in roles")
    tokens = record.get("tokens")
    if tokens is not None:
        _check_tokens(tokens)
    steel = record.get("steel")
    if steel is not None:
        _check_steel(steel)
    snapshot = record.get("snapshot")
    if snapshot is not None:
        _check_snapshot(snapshot)
    if "notes" in record and not isinstance(record["notes"], str):
        _fail("account.notes", "must be a string")
    # #223 D223-14 (settled): absent until the loop asserts it; any present
    # value outside the closed pair is a loud refusal (never a third state,
    # D223-3 - exhaustion is a failed authentication, recorded `not_valid`).
    if "status" in record:
        status = record["status"]
        if not isinstance(status, str) or status not in _ACCOUNT_STATUSES:
            _fail("account.status", 'must be "valid" or "not_valid"')
    # #223 D223-18 (settled): the server-stamped recency fact. Validation
    # requires only the stamp shape (a string) - the STORE decides the value
    # (stamped on every write and seed, a client-supplied value overwritten,
    # never trusted), so no forged ordering can ever validate its way in.
    if "updated_at" in record and not isinstance(record["updated_at"], str):
        _fail("account.updated_at", "must be a string")
    return copy.deepcopy(record)


def select_recent_usable_account(accounts: object) -> str | None:
    """The deterministic account selection (#223 D223-18): the most recently
    updated USABLE account's name (`updated_at` descending - a missing stamp
    sorts oldest, so pre-#241 records lose to stamped ones); ties fall back
    to list position, newest last. The descending order is a plain string
    comparison, correct because every stamp comes from the store's one
    `_utcnow_iso` seam (aware UTC ISO-8601, always the same `+00:00` shape) -
    never parse here, the format is pinned by the seam's own test. Usable
    means not known-bad: a `not_valid` record is skipped (the loop asserted
    it failed - re-selecting it would replay a dead session). No usable
    account (or no mapping at all) is None, never a raise - the gateway maps
    that onto its missing-data path."""
    if not isinstance(accounts, dict):
        return None
    best: str | None = None
    best_stamp = ""
    best_pos = -1
    for pos, (name, record) in enumerate(accounts.items()):
        if not isinstance(record, dict):
            continue
        if record.get("status") == "not_valid":
            continue
        stamp = record.get("updated_at")
        key = stamp if isinstance(stamp, str) else ""
        if best is None or key > best_stamp or (key == best_stamp and pos > best_pos):
            best, best_stamp, best_pos = name, key, pos
    return best
