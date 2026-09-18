"""#243 (T4) unit tier - the auth feed: identifier-bound, lazily resolved,
per-phase projected auth material from the shared store.

The feed replaces the settings-blob auth path (D223-4): the gateway verdict
binds only the account IDENTIFIER into the pipeline state, and each phase's
tool configuration resolves that account from the auth store at the point of
use, projecting only the subset its tools need - the flat request material
(headers/cookies) for request-based auth-eligible jobs, the persisted Steel
profile key for the crawler, nothing for non-auth jobs. Role/default_role
selection resolves over the account record, never the retired blob.

Each test names the feed contract it pins.
"""
import pytest

from polymerhus.app.auth.store import AuthStore
from polymerhus.recon.control import auth_feed
from polymerhus.recon.control.auth_feed import (
    project_auth_cookies,
    project_request_auth,
    project_steel_profile,
    resolve_account,
    select_account_role,
    serialize_auth_flags,
)


def _seeded_store(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        "p1",
        overview={"login_endpoint": "https://x/login"},
        accounts={
            "alice": {
                "credentials": {"username": "u", "password": "p",
                                "login_url": "https://x/login"},
                "tokens": {
                    "session": {"value": "TOK", "location": "cookie"},
                    "Authorization": {"value": "Bearer T", "location": "header"},
                    "csrf-store": {"value": "C", "location": "storage"},
                },
                "steel": {"profile": "p1-alice"},
                "snapshot": {
                    "headers": {"X-Api-Key": "K"},
                    "cookies": [{"name": "sid", "value": "S"}],
                },
                "roles": {
                    "admin": {"username": "a", "password": "p",
                              "login_url": "https://x/login"},
                },
                "default_role": "admin",
            },
        },
    )
    return store


# --- resolve_account: identifier in, record out, fail-open ---

def test_resolve_account_returns_the_named_record(tmp_path):
    store = _seeded_store(tmp_path)
    account = resolve_account("p1", "alice", store=store)
    assert account["steel"] == {"profile": "p1-alice"}


def test_resolve_account_unknown_name_fails_open_to_empty(tmp_path):
    store = _seeded_store(tmp_path)
    assert resolve_account("p1", "ghost", store=store) == {}


def test_resolve_account_missing_store_fails_open_to_empty(tmp_path):
    store = AuthStore(tmp_path)  # never seeded: empty bucket
    assert resolve_account("p1", "alice", store=store) == {}


# --- select_account_role: roles/default_role over the record ---

def test_select_account_role_returns_the_named_roles_credentials(tmp_path):
    account = resolve_account("p1", "alice", store=_seeded_store(tmp_path))
    assert select_account_role(account, "admin") == {
        "username": "a", "password": "p", "login_url": "https://x/login"}
    assert select_account_role(account, "ghost") == {}  # never another role's


def test_select_account_role_none_uses_default_role_then_flat_credentials(tmp_path):
    account = resolve_account("p1", "alice", store=_seeded_store(tmp_path))
    selected = select_account_role(account, None)
    assert selected["username"] == "a"  # default_role=admin

    flat = {"credentials": {"username": "u", "password": "p",
                            "login_url": "https://x/login"}}
    assert select_account_role(flat, None)["username"] == "u"  # no roles: flat creds
    assert select_account_role(None, None) == {}


def test_select_account_role_keeps_blob_map_shape_for_interface_b_probes():
    # The backward-recon seam hands caller-supplied {roles, default_role} maps
    # (analysis/anatomy.py): the same selector serves them, flat keys passing
    # through with the structural keys stripped.
    blob = {"roles": {"shopper": {"cookies": [{"name": "s", "value": "S"}]}},
            "default_role": "shopper"}
    assert select_account_role(blob, "shopper") == {
        "cookies": [{"name": "s", "value": "S"}]}
    assert select_account_role(blob, None) == {
        "cookies": [{"name": "s", "value": "S"}]}


# --- project_request_auth: snapshot + tokens by location ---

def test_project_request_auth_merges_snapshot_and_located_tokens(tmp_path):
    account = resolve_account("p1", "alice", store=_seeded_store(tmp_path))
    material = project_request_auth(account)
    assert material["X-Api-Key"] == "K"  # snapshot header
    assert material["Authorization"] == "Bearer T"  # header-located token
    names = {c["name"] for c in material["cookies"]}
    assert names == {"sid", "session"}  # snapshot + cookie-located token
    assert "csrf-store" not in str(material)  # storage-located: browser-bound


def test_project_request_auth_empty_account_projects_empty():
    assert project_request_auth({}) == {}
    assert project_request_auth(None) == {}


def test_project_auth_cookies_carries_only_cookies(tmp_path):
    account = resolve_account("p1", "alice", store=_seeded_store(tmp_path))
    cookies = project_auth_cookies(account)
    assert {c["name"] for c in cookies} == {"sid", "session"}
    assert project_auth_cookies({}) == []


def test_project_steel_profile_reads_the_persisted_key(tmp_path):
    account = resolve_account("p1", "alice", store=_seeded_store(tmp_path))
    assert project_steel_profile(account) == "p1-alice"
    assert project_steel_profile({}) is None


# --- serialize_auth_flags: per-tool header serialisation, unchanged behaviour ---

def test_serialize_httpx_cookie_string_not_dict_repr():
    flags = serialize_auth_flags(
        {"cookies": [{"name": "session", "value": "abc"}]}, "httpx")
    assert flags == "-H 'Cookie: session=abc'"


def test_serialize_arjun_uses_newline_joined_headers_flag():
    flags = serialize_auth_flags(
        {"cookies": [{"name": "s", "value": "v"}],
         "Authorization": "Bearer t"}, "arjun")
    assert flags.startswith("--headers ")
    assert "Authorization: Bearer t" in flags and "Cookie: s=v" in flags


def test_serialize_graphql_cop_uses_comma_joined_headers_flag():
    flags = serialize_auth_flags(
        {"cookies": [{"name": "s", "value": "v"}],
         "Authorization": "Bearer t"}, "graphql-cop")
    assert flags.startswith("--headers ")
    assert "," in flags and "Authorization:Bearer t" in flags


def test_serialize_kiterunner_uses_default_h_flag():
    flags = serialize_auth_flags(
        {"cookies": [{"name": "s", "value": "v"}]}, "kiterunner")
    assert flags == "-H 'Cookie: s=v'"


def test_serialize_structural_keys_never_become_headers():
    material = {"roles": {"a": {}}, "default_role": "a", "realm": "credential",
                "scope": "x", "credentials": {"username": "u"},
                "cookies": [{"name": "s", "value": "v"}],
                "Authorization": "Bearer t"}
    names = {name for name, _ in auth_feed._iter_auth_headers(material)}
    assert names == {"Cookie", "Authorization"}


def test_serialize_empty_material_collapses_to_empty():
    assert serialize_auth_flags({}, "httpx") == ""
    assert serialize_auth_flags(None, "httpx") == ""
    assert serialize_auth_flags({"roles": {}}, "httpx") == ""


def test_feed_module_exposes_no_blob_selector():
    # The blob-based role selector is gone: no select_auth_context here.
    assert not hasattr(auth_feed, "select_auth_context")
