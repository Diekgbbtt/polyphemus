"""#364: the analysis-side READ-ONLY form of the one shared `auth_store` tool.

Unit tier (CODING_STANDARD sections 5/6/8/10): every test drives the REAL tool
object built by `build_auth_store_tool(..., read_only=True)` over an explicit-root
temp store. The literals below come from the #364 decision record
(`docs/design/analysis-auth-store-view-364-adr.md`) and the record shapes, never
from the implementation: the tests pin the contract, the module honours it.

The three guarantees under test:
  * the read view carries NAMES, SHAPES, AND STATUSES - never a secret value;
  * no write path is reachable (a write command is refused before the store is
    touched, and the bound schema cannot even express a value to write);
  * the tool keeps the shared `auth_store` name, so the census the ticket
    measured counts the analysis-side reads.
"""
from __future__ import annotations

import json

import yaml

from polymerhus.app.auth.store import AuthStore
from polymerhus.app.auth.tool import (
    AUTH_STORE_READ_CONTRACT,
    REDACTED,
    build_auth_store_tool,
)

PROJECT = "proj-auth-read-1"

# The independent source of truth for the marker: the decision record's literal.
MARKER = "<redacted>"

# Every one of these is a real secret a request replayer would need - and none
# of them may appear anywhere in the read view.
PASSWORD = "hunter2-do-not-leak"
ROLE_PASSWORD = "role-password-do-not-leak"
TOKEN_VALUE = "tok-abc-do-not-leak"
COOKIE_VALUE = "JSESSIONID-VALUE-do-not-leak"
SNAPSHOT_HEADER_VALUE = "csrf-header-value-do-not-leak"
SNAPSHOT_PARAM_VALUE = "csrf-param-do-not-leak"
SECRETS = (
    PASSWORD, ROLE_PASSWORD, TOKEN_VALUE, COOKIE_VALUE,
    SNAPSHOT_HEADER_VALUE, SNAPSHOT_PARAM_VALUE,
)


def _seeded_store(tmp_path) -> AuthStore:
    """One fully-populated account: credentials, a role set, a header token, a
    cookie token, a Steel reference, a request snapshot, the loop-asserted
    status. Seeded through the store seam, never through the tool."""
    store = AuthStore(tmp_path)
    store.write(
        PROJECT,
        "overview",
        {
            "login_endpoint": "https://t.example/login",
            "required_headers": ["X-CSRF-Token"],
            "mechanism": "form post plus a session cookie",
            "technical_conditions": [
                {"name": "no-session-cookie", "check": "no Set-Cookie on the login response"},
            ],
            "notes": "operator ground truth",
        },
        origin="operator",
    )
    store.write(
        PROJECT,
        "accounts.alice-bootstrap",
        {
            "procedure": "password-login",
            "credentials": {
                "username": "alice",
                "password": PASSWORD,
                "login_url": "https://t.example/login",
            },
            "roles": {
                "admin": {
                    "username": "alice-root",
                    "password": ROLE_PASSWORD,
                    "login_url": "https://t.example/admin/login",
                },
            },
            "default_role": "admin",
            "tokens": {
                "X-Auth-Token": {
                    "value": TOKEN_VALUE,
                    "location": "header",
                    "expiry": "2026-11-01T00:00:00+00:00",
                },
                "session": {
                    "value": COOKIE_VALUE,
                    "location": "cookie",
                    "target": "t.example",
                },
            },
            "steel": {"profile": "proj-auth-read-1-alice"},
            "snapshot": {
                "headers": {"X-CSRF-Token": SNAPSHOT_HEADER_VALUE},
                "cookies": [{"name": "JSESSIONID", "value": COOKIE_VALUE}],
                "params": {"_csrf": SNAPSHOT_PARAM_VALUE},
                "captured_at": "2026-10-18T10:00:00+00:00",
            },
            "status": "valid",
            "notes": "minted by the bootstrap",
        },
    )
    return store


class _WriteSpyStore(AuthStore):
    """A store whose write seam is a tripwire: the read-only view must never
    reach it, so a call here fails the test loudly instead of silently writing."""

    def __init__(self, root):
        super().__init__(root)
        self.writes = 0

    def write(self, *args, **kwargs):  # noqa: D102 - the tripwire is the point
        self.writes += 1
        raise AssertionError("the read-only auth view reached the write seam")


def _readonly_tool(tmp_path, store=None):
    return build_auth_store_tool(
        PROJECT, store if store is not None else _seeded_store(tmp_path),
        read_only=True)


# --- the shared name, the bound handle, the argument surface ------------------

def test_read_only_mode_keeps_the_shared_tool_name(tmp_path):
    """The census the ticket measured counts calls by tool NAME: the analysis
    read must be the same `auth_store` the recon roles bind, never a second
    face (`auth_view`) that no existing measurement knows."""
    tool = _readonly_tool(tmp_path)
    assert tool.name == "auth_store"


def test_the_read_only_schema_cannot_express_a_write(tmp_path):
    """`value` is not on the read-only schema, so a write-shaped payload has no
    field to ride; `command` and `path` are the whole request surface."""
    tool = _readonly_tool(tmp_path)
    assert set(tool.args) == {"command", "path"}
    assert "project_id" not in tool.args
    assert tool.args["command"]["description"].count("read") >= 1
    assert "full redacted state" in tool.args["path"]["description"]
    assert "accounts.alice" in tool.args["path"]["description"]


def test_the_read_view_reads_the_projects_state(tmp_path):
    tool = _readonly_tool(tmp_path)
    out = tool.invoke({"command": "read", "path": ""})
    assert out["ok"] is True and out["command"] == "read" and out["path"] == ""
    assert out["value"]["overview"]["login_endpoint"] == "https://t.example/login"
    assert "alice-bootstrap" in out["value"]["accounts"]


def test_the_read_view_bound_to_one_project_never_reads_a_sibling(tmp_path):
    store = _seeded_store(tmp_path)
    store.write("proj-other", "accounts.bob.notes", "sibling secret")
    out = _readonly_tool(tmp_path, store).invoke({"command": "read", "path": ""})
    assert "bob" not in out["value"]["accounts"]


def test_a_narrow_path_projects_the_redacted_field(tmp_path):
    out = _readonly_tool(tmp_path).invoke(
        {"command": "read", "path": "overview.login_endpoint"})
    assert out == {"ok": True, "command": "read",
                   "path": "overview.login_endpoint",
                   "value": "https://t.example/login"}


def test_a_missing_path_is_a_valid_empty(tmp_path):
    out = _readonly_tool(tmp_path).invoke(
        {"command": "read", "path": "accounts.nobody"})
    assert out == {"ok": True, "command": "read",
                   "path": "accounts.nobody", "value": {}}


def test_the_email_keyed_path_resolves_the_canonical_account(tmp_path):
    """#247 continuity: the symbolic layer's name canonicalisation is the
    store's, reused rather than re-implemented, so both name forms address the
    one record here too."""
    out = _readonly_tool(tmp_path).invoke({
        "command": "read",
        "path": "accounts.alice@t.example-bootstrap.status"})
    assert out["value"] == "valid"


# --- no write path is reachable ----------------------------------------------

def test_a_write_command_is_refused_and_never_reaches_the_store(tmp_path):
    spy = _WriteSpyStore(tmp_path)
    store = _seeded_store(tmp_path)
    tool = build_auth_store_tool(PROJECT, spy, read_only=True)
    before = (tmp_path / PROJECT / "auth" / "credentials.yaml").read_text(
        encoding="utf-8")

    out = tool.invoke({
        "command": "write",
        "path": "accounts.mallory",
        "value": {"credentials": {"username": "m", "password": "p",
                                  "login_url": "https://t.example/login"}},
    })

    assert out["ok"] is False
    assert out["error"] == "auth_readonly"
    assert "read-only" in out["detail"]
    assert spy.writes == 0, "the write seam must never be reached"
    after = (tmp_path / PROJECT / "auth" / "credentials.yaml").read_text(
        encoding="utf-8")
    assert after == before, "a refused write mutates nothing"
    # And the sibling account the test seeded through the real store is intact.
    assert store.read(PROJECT, "accounts.alice-bootstrap")["status"] == "valid"


def test_every_non_read_command_is_refused_the_same_way(tmp_path):
    tool = _readonly_tool(tmp_path)
    for command in ("write", "drop", "authenticate", ""):
        out = tool.invoke({"command": command, "path": "accounts.alice-bootstrap"})
        assert out["ok"] is False, command
        assert out["error"] == "auth_readonly", command


def test_a_degraded_store_degrades_to_an_envelope(tmp_path):
    store = AuthStore(tmp_path)
    bucket = tmp_path / PROJECT / "auth"
    bucket.mkdir(parents=True)
    (bucket / "credentials.yaml").write_text("{{{not yaml", encoding="utf-8")
    out = build_auth_store_tool(PROJECT, store, read_only=True).invoke(
        {"command": "read", "path": ""})
    # An unreadable bucket reads as a valid empty (the store's own fail-open).
    assert out["ok"] is True
    assert out["value"]["accounts"] == {}


# --- the redaction level (the decision the ticket requires) -------------------

def test_cookie_values_are_redacted_and_cookie_names_are_kept(tmp_path):
    """The recorded decision (D364-2): the cookie NAME is the request shape the
    typist needs, the value is the reusable credential - so names stay and
    values become the marker."""
    out = _readonly_tool(tmp_path).invoke(
        {"command": "read", "path": "accounts.alice-bootstrap.snapshot"})
    snapshot = out["value"]
    assert snapshot["cookies"] == [{"name": "JSESSIONID", "value": MARKER}]
    assert snapshot["captured_at"] == "2026-10-18T10:00:00+00:00"


def test_token_names_locations_and_statuses_are_kept(tmp_path):
    out = _readonly_tool(tmp_path).invoke(
        {"command": "read", "path": "accounts.alice-bootstrap.tokens"})
    assert out["value"]["session"]["location"] == "cookie"
    assert out["value"]["session"]["target"] == "t.example"
    assert out["value"]["X-Auth-Token"]["location"] == "header"
    assert out["value"]["X-Auth-Token"]["expiry"] == "2026-11-01T00:00:00+00:00"
    assert out["value"]["session"]["value"] == MARKER
    assert out["value"]["X-Auth-Token"]["value"] == MARKER


def test_no_secret_value_survives_anywhere_in_the_read_view(tmp_path):
    """The load-bearing assertion: the WHOLE read view, serialised, contains not
    one secret literal - on a full read and on every narrow path a turn could
    choose."""
    tool = _readonly_tool(tmp_path)
    paths = ("", "overview", "accounts", "accounts.alice-bootstrap",
             "accounts.alice-bootstrap.credentials",
             "accounts.alice-bootstrap.roles",
             "accounts.alice-bootstrap.tokens",
             "accounts.alice-bootstrap.snapshot")
    for path in paths:
        rendered = json.dumps(tool.invoke({"command": "read", "path": path}))
        for secret in SECRETS:
            assert secret not in rendered, f"{secret!r} leaked on path {path!r}"


def test_a_secret_leaf_is_unaddressable_by_a_narrow_path(tmp_path):
    """Redaction is applied BEFORE the projection, so a path that names a secret
    slot directly still reads the marker - never the value."""
    tool = _readonly_tool(tmp_path)
    for path in ("accounts.alice-bootstrap.credentials.password",
                 "accounts.alice-bootstrap.roles.admin.password",
                 "accounts.alice-bootstrap.tokens.session.value",
                 "accounts.alice-bootstrap.tokens.X-Auth-Token.value",
                 "accounts.alice-bootstrap.snapshot.cookies.0.value",
                 "accounts.alice-bootstrap.snapshot.headers.X-CSRF-Token",
                 "accounts.alice-bootstrap.snapshot.params._csrf"):
        out = tool.invoke({"command": "read", "path": path})
        assert out["value"] in (MARKER, {}, [MARKER]), path


def test_the_identity_and_the_request_shape_stay_visible(tmp_path):
    """What the typist types a request shape FROM: the account identity, the
    login URL, the required header names, the procedure, the status."""
    tool = _readonly_tool(tmp_path)
    record = tool.invoke(
        {"command": "read", "path": "accounts.alice-bootstrap"})["value"]
    assert record["credentials"]["username"] == "alice"
    assert record["credentials"]["login_url"] == "https://t.example/login"
    assert record["status"] == "valid"
    assert record["procedure"] == "password-login"
    assert record["steel"] == {"profile": "proj-auth-read-1-alice"}
    overview = tool.invoke({"command": "read", "path": "overview"})["value"]
    assert overview["required_headers"] == ["X-CSRF-Token"]
    assert overview["mechanism"] == "form post plus a session cookie"


def test_the_marker_is_the_decided_literal():
    """The marker is one literal, shared by the redactor and the contract."""
    assert REDACTED == MARKER
    assert MARKER in AUTH_STORE_READ_CONTRACT


# --- the model-facing contract ------------------------------------------------

def test_the_read_only_description_carries_the_read_contract(tmp_path):
    desc = _readonly_tool(tmp_path).description
    assert desc == AUTH_STORE_READ_CONTRACT


def test_the_contract_teaches_the_redaction_and_the_read_only_rule():
    for marker in ("READ-ONLY", "auth_readonly", "overview", "required_headers",
                   "account", "tokens", "snapshot", "status", "dot-path",
                   "valid empty", "store_unavailable", "<redacted>"):
        assert marker in AUTH_STORE_READ_CONTRACT, f"contract missing {marker!r}"
    assert "never" in AUTH_STORE_READ_CONTRACT.lower()


def test_read_only_envelopes_are_json_serializable(tmp_path):
    tool = _readonly_tool(tmp_path)
    for call in ({"command": "read", "path": ""},
                 {"command": "read", "path": "accounts.nobody"},
                 {"command": "read", "path": "accounts.alice-bootstrap.tokens"},
                 {"command": "write", "path": "accounts.alice-bootstrap.notes",
                  "value": "refused"}):
        json.dumps(tool.invoke(call))


def test_the_read_only_view_never_writes_a_bucket(tmp_path):
    """A read of an unseeded project creates nothing on disk: the read-only view
    is not a bucket-creating write path in disguise."""
    build_auth_store_tool(PROJECT, AuthStore(tmp_path),
                          read_only=True).invoke({"command": "read", "path": ""})
    assert not (tmp_path / PROJECT / "auth").exists()


def test_the_raw_store_state_is_unchanged_after_reads(tmp_path):
    """The redaction is a VIEW: the store on disk keeps the real values, so the
    recon/gateway consumers are untouched."""
    store = _seeded_store(tmp_path)
    _readonly_tool(tmp_path, store).invoke({"command": "read", "path": ""})
    on_disk = yaml.safe_load(
        (tmp_path / PROJECT / "auth" / "credentials.yaml").read_text(
            encoding="utf-8"))
    assert on_disk["accounts"]["alice-bootstrap"]["credentials"]["password"] == PASSWORD
    assert store.read(PROJECT, "accounts.alice-bootstrap.tokens.session.value") \
        == COOKIE_VALUE
