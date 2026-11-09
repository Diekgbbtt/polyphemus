"""#243 (T4) unit tier - the auth feed: identifier-bound, lazily resolved,
per-phase projected auth material from the shared store.

The feed replaces the settings-blob auth path (D223-4): the gateway verdict
binds only the account IDENTIFIER into the pipeline state, and each phase's
tool configuration resolves that account from the auth store at the point of
use, projecting only the subset its tools need - the flat request material
(headers/cookies) for request-based auth-eligible jobs, the decoupled
auth-context reference for the crawl, nothing for non-auth jobs. Role/default_role
selection resolves over the account record, never the retired blob.

Each test names the feed contract it pins.
"""
import pytest

from polymerhus.app.auth.store import AuthStore
from polymerhus.recon.control import auth_feed
from polymerhus.recon.control.auth_feed import (
    project_browser_auth,
    project_request_auth,
    project_browser_context,
    project_sessions,
    resolve_account,
    resolve_accounts,
    resolve_overview,
    select_account_role,
    serialize_auth_flags,
)


def _seeded_store(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        "p1",
        overview={"login_endpoint": "https://x/login",
                  "required_headers": ["X-Api-Key: K",
                                       "Authorization: Bearer OLD"]},
        accounts={
            "alice": {
                "credentials": {"username": "u", "password": "p",
                                "login_url": "https://x/login"},
                "tokens": {
                    "session": {"value": "TOK", "location": "cookie"},
                    "Authorization": {"value": "Bearer T", "location": "header"},
                    "csrf-store": {"value": "C", "location": "storage",
                                   "target": "https://x.example"},
                },
                "browser_context": {"ref": "steel-auth-p1-alice"},
                "snapshot": {
                    # Stale by design: snapshot headers are NEVER replayed -
                    # the header fact single-sources on overview.required_headers.
                    "headers": {"X-Snapshot": "OLD"},
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


def _request_material(store, project="p1", name="alice"):
    # The caller shape: the pipeline resolves the account AND the overview
    # from the store, then projects with the overview passed in.
    account = resolve_account(project, name, store=store)
    overview = resolve_overview(project, store=store)
    return project_request_auth(account, overview)


# --- resolve_account: identifier in, record out, fail-open ---

def test_resolve_account_returns_the_named_record(tmp_path):
    store = _seeded_store(tmp_path)
    account = resolve_account("p1", "alice", store=store)
    assert account["browser_context"] == {"ref": "steel-auth-p1-alice"}


def test_resolve_accounts_returns_the_full_map(tmp_path):
    store = _seeded_store(tmp_path)

    accounts = resolve_accounts("p1", store=store)

    assert set(accounts) == {"alice"}
    assert accounts["alice"]["browser_context"] == {
        "ref": "steel-auth-p1-alice"
    }


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


def test_select_account_role_malformed_roles_shape_degrades_to_empty():
    # A non-dict `roles` (malformed store shape) never raises into the
    # caller - explicit roles miss, and role=None falls to flat credentials.
    assert select_account_role({"roles": ["admin"]}, "admin") == {}
    assert select_account_role(
        {"roles": ["admin"],
         "credentials": {"username": "u", "password": "p",
                         "login_url": "https://x/login"}}, None)["username"] == "u"


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


# --- resolve_overview: operator header fact in, fail-open out ---

def test_resolve_overview_returns_the_operator_header_fact(tmp_path):
    store = _seeded_store(tmp_path)
    overview = resolve_overview("p1", store=store)
    assert overview["required_headers"] == ["X-Api-Key: K",
                                            "Authorization: Bearer OLD"]


def test_resolve_overview_unknown_project_fails_open_to_empty(tmp_path):
    store = AuthStore(tmp_path)  # never seeded: empty bucket
    assert resolve_overview("p1", store=store) == {}


# --- project_request_auth: overview headers + snapshot cookies + tokens ---

def test_project_request_auth_merges_overview_headers_and_located_tokens(tmp_path):
    material = _request_material(_seeded_store(tmp_path))
    assert material["X-Api-Key"] == "K"  # overview.required_headers
    # A header-located token overrides the same-named overview entry.
    assert material["Authorization"] == "Bearer T"
    names = {c["name"] for c in material["cookies"]}
    assert names == {"sid", "session"}  # snapshot + cookie-located token
    assert "csrf-store" not in str(material)  # storage-located: browser-bound


def test_project_request_auth_ignores_snapshot_headers(tmp_path):
    # The scrubbed redundancy: a stale snapshot.headers entry never replays,
    # even when the overview carries no such header.
    material = _request_material(_seeded_store(tmp_path))
    assert "X-Snapshot" not in material


def test_project_request_auth_malformed_required_header_skipped_loudly(caplog):
    import logging
    account = {"snapshot": {"cookies": [{"name": "sid", "value": "S"}]}}
    overview = {"required_headers": ["X-Ok: v", "bogus-no-colon",
                                     "X-Empty: ", ": no-name", 42]}
    with caplog.at_level(logging.WARNING):
        material = project_request_auth(account, overview)
    assert material["X-Ok"] == "v"  # the well-formed entry still lands
    assert material["cookies"] == [{"name": "sid", "value": "S"}]
    assert "bogus-no-colon" in caplog.text  # skipped loudly, never fatal


def test_project_request_auth_empty_overview_projects_no_headers(tmp_path):
    # Absent/empty overview: the header set is empty (never a crash), while
    # snapshot cookies and located tokens still ride.
    account = resolve_account("p1", "alice", store=_seeded_store(tmp_path))
    for overview in (None, {}, {"login_endpoint": "https://x/login"}):
        material = project_request_auth(account, overview)
        assert "X-Api-Key" not in material
        assert "Authorization" in material  # header-located token still lands
        assert {c["name"] for c in material["cookies"]} == {"sid", "session"}


def test_project_request_auth_first_colon_splits_name_from_value():
    # A value carrying its own colon parses on the FIRST colon only.
    material = project_request_auth(
        {}, {"required_headers": ["X-Callback: https://x.example/cb"]})
    assert material == {"X-Callback": "https://x.example/cb"}


def test_project_request_auth_empty_account_projects_empty():
    assert project_request_auth({}, {}) == {}
    assert project_request_auth(None, None) == {}


def _session_accounts(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        "p1",
        accounts={
            "admin": {
                "role": "super_administrator",
                "root_url": "/index.php/admin/Index/index.html",
                "auth_probe": "/index.php/admin/Index/index.html",
                "credentials": {
                    "username": "admin",
                    "password": "pw",
                    "login_url": "/index.php/admin/Login/index.html",
                },
            },
            "member": {
                "role": "member",
                "root_url": "/index.php/index/user/index.html",
                "credentials": {
                    "username": "m",
                    "password": "pw",
                    "login_url": "/index.php/index/user/login.html",
                },
            },
            "baseline": {
                "credentials": {
                    "username": "b",
                    "password": "pw",
                    "login_url": "/index.php/index/user/login.html",
                },
            },
        },
    )
    return store


def test_project_sessions_one_entry_per_account_with_defaults(tmp_path):
    store = _session_accounts(tmp_path)
    accounts = store.read("p1", "accounts")

    sessions = project_sessions("p1", accounts, origin="http://target.test")

    assert [session["account"] for session in sessions] == [
        "admin", "member", "baseline"
    ]
    admin, member, baseline = sessions

    assert admin["role"] == "super_administrator"
    assert admin["root_url"] == (
        "http://target.test/index.php/admin/Index/index.html"
    )
    assert admin["auth_probe"] == (
        "http://target.test/index.php/admin/Index/index.html"
    )
    assert admin["login_url"] == "/index.php/admin/Login/index.html"
    assert admin["browser_context_ref"] == "steel-auth-p1-admin"
    assert admin["anonymous"] is False

    assert member["role"] == "member"
    assert member["root_url"] == (
        "http://target.test/index.php/index/user/index.html"
    )
    assert member["auth_probe"] is None

    assert baseline["role"] is None
    assert baseline["root_url"] == "http://target.test/"
    assert baseline["auth_probe"] is None


def test_project_sessions_keeps_absolute_and_defaults_default_role():
    accounts = {
        "legacy": {
            "default_role": "admin",
            "root_url": "https://member.example/app",
            "auth_probe": "https://member.example/me",
        },
        "broken": None,
    }

    sessions = project_sessions("p1", accounts, origin="http://target.test")

    assert len(sessions) == 1
    session = sessions[0]
    assert session["account"] == "legacy"
    assert session["role"] == "admin"
    assert session["root_url"] == "https://member.example/app"
    assert session["auth_probe"] == "https://member.example/me"


def test_project_sessions_skips_stale_accounts():
    accounts = {
        "valid": {"status": "valid", "root_url": "/valid"},
        "stale": {"status": "not_valid", "root_url": "/stale"},
        "unknown": {"root_url": "/unknown"},
    }

    sessions = project_sessions("p1", accounts, origin="http://target.test")

    assert [session["account"] for session in sessions] == [
        "valid",
        "unknown",
    ]


def test_project_sessions_empty_accounts_is_the_anonymous_fallback():
    assert project_sessions("p1", {}, origin="http://target.test") == []
    assert project_sessions("p1", None, origin="http://target.test") == []


def test_project_browser_auth_carries_only_probe_and_login_url(tmp_path):
    store = _seeded_store(tmp_path)
    account = resolve_account("p1", "alice", store=store)
    overview = dict(
        resolve_overview("p1", store=store),
        auth_probe={"url": "/api/me"},
    )
    material = project_browser_auth(
        account, overview, origin="https://app.test"
    )
    assert material == {
        "auth_probe": "https://app.test/api/me",
        "login_url": "https://x/login",
    }
    assert "cookies" not in material
    assert "headers" not in material
    assert "storage" not in material


def test_project_browser_auth_never_projects_snapshot_or_token_material(tmp_path):
    store = _seeded_store(tmp_path)
    material = project_browser_auth(
        resolve_account("p1", "alice", store=store),
        resolve_overview("p1", store=store),
    )
    text = str(material)
    assert "X-Snapshot" not in text
    assert "sid" not in text
    assert "csrf-store" not in text


def test_project_browser_auth_ignores_storage_tokens():
    account = {
        "tokens": {
            "csrf-store": {"value": "C", "location": "storage"},
            "ok": {"value": "V", "location": "storage", "target": "https://x.example"},
        },
    }
    assert project_browser_auth(account) == {}


def test_project_browser_auth_resolves_the_oracle_path():
    overview = {"auth_probe": {"url": "/api/authentication"}}
    material = project_browser_auth({}, overview, origin="http://t.example:8080")
    assert material["auth_probe"] == "http://t.example:8080/api/authentication"


def test_project_browser_auth_keeps_an_absolute_oracle():
    overview = {"auth_probe": {"url": "https://live.example/api/me"}}
    material = project_browser_auth({}, overview, origin="http://t.example")
    assert material["auth_probe"] == "https://live.example/api/me"


def test_project_browser_auth_empty_projects_empty():
    assert project_browser_auth({}, {}) == {}
    assert project_browser_auth(None, None) == {}


def test_project_browser_auth_carries_a_login_url_alone():
    assert project_browser_auth(
        {"credentials": {"login_url": "https://x/login"}}, {}
    ) == {"login_url": "https://x/login"}


def test_project_browser_context_reads_a_valid_reference():
    assert project_browser_context(
        {"browser_context": {"ref": "steel-auth-p1-alice"}}
    ) == "steel-auth-p1-alice"
    assert project_browser_context({}) is None


def test_project_browser_context_computes_the_deterministic_key():
    assert project_browser_context(
        {}, project_id="proj1", account_name="alice"
    ) == "steel-auth-proj1-alice"


@pytest.mark.parametrize(
    "legacy",
    ["alice", "../escape", "a" * 200, "old-session-name", ""],
)
def test_project_browser_context_replaces_a_legacy_reference(legacy):
    account = {"steel": {"state": legacy}}

    assert project_browser_context(
        account, project_id="proj1", account_name="alice"
    ) == "steel-auth-proj1-alice"


def test_project_browser_context_does_not_trust_another_projects_reference():
    account = {"browser_context": {"ref": "steel-auth-other-bob"}}

    assert project_browser_context(
        account, project_id="proj1", account_name="alice"
    ) == "steel-auth-proj1-alice"


def test_project_browser_context_ignores_the_retired_steel_key():
    assert project_browser_context({"steel": {"state": "steel-p1-alice"}}) is None


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
