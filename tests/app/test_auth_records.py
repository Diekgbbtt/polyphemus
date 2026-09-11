"""T1 (#227): the auth record validation seam - overview and account shapes.

Unit tier, CODING_STANDARD sections 3/6/10: pure validation functions only
(value in, validated value or denoted refusal out), no I/O, no env var.
Every literal below comes from the #220 spec shapes, not from the
implementation - the tests pin the contract, the module honours it.
"""
import pytest

from polymerhus.app.auth import (
    AuthInvalidError,
    validate_account,
    validate_overview,
)


def _full_overview() -> dict:
    return {
        "login_endpoint": "/login",
        "required_headers": ["X-CSRF-Token"],
        "mechanism": "password-login",
        "defences": ["rate-limit"],
        "fingerprinting": "canvas",
        "technical_conditions": [
            {"name": "session-fresh", "check": "re-login when the session cookie is absent"},
        ],
        "notes": "operator ground truth",
    }


def _full_account() -> dict:
    return {
        "origin": "operator",
        "procedure": "password-login",
        "credentials": {
            "username": "ops-admin",
            "password": "s3cret",
            "login_url": "https://target.example/login",
            "domain": "target.example",
            "username_selector": "#user",
            "password_selector": "#pass",
            "submit_selector": "#go",
        },
        "tokens": {
            "session": {"value": "abc123", "location": "cookie", "target": "sessionid"},
            "api": {"value": "Bearer xyz", "location": "header", "expiry": "2026-10-01"},
            "vault": {"value": "v1", "location": "storage"},
        },
        "steel": {"profile": "ops-profile-1"},
        "snapshot": {
            "headers": {"Authorization": "Bearer xyz"},
            "cookies": [{"name": "sessionid", "value": "abc123"}],
            "params": {"next": "/dashboard"},
            "captured_at": "2026-09-10T12:00:00Z",
        },
        "notes": "seeded admin account",
    }


# --- valid records validate clean ---

def test_full_overview_validates_clean():
    assert validate_overview(_full_overview()) == _full_overview()


def test_empty_overview_is_valid():
    assert validate_overview({}) == {}


def test_full_account_validates_clean():
    assert validate_account(_full_account()) == _full_account()


def test_agent_origin_account_validates_clean():
    record = {"origin": "agent", "procedure": "self-registration"}
    assert validate_account(record) == record


# --- the closed contract: unknown fields and origins are refused ---

def test_overview_rejects_an_unknown_field():
    with pytest.raises(AuthInvalidError) as exc:
        validate_overview({"login_endpoint": "/login", "replay_manner": "fast"})
    assert "overview.replay_manner" in str(exc.value)


def test_account_rejects_an_unknown_field():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "produced": "x"})
    assert "account.produced" in str(exc.value)


def test_account_origin_is_a_closed_enum():
    for bad in ("human", "", None):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": bad})
        assert "account.origin" in str(exc.value)
    with pytest.raises(AuthInvalidError):
        validate_account({"procedure": "x"})  # origin missing


def test_refusal_is_a_denoted_value_error_naming_its_field():
    try:
        validate_account({"origin": "human"})
    except AuthInvalidError as e:
        assert isinstance(e, ValueError)
        assert e.field == "account.origin"
        assert "account.origin" in str(e)
    else:
        raise AssertionError("expected AuthInvalidError")


# --- credentials: username/password/login_url required, selectors optional ---

def test_credentials_require_username_password_login_url():
    base = {"username": "u", "password": "p", "login_url": "https://t.example/login"}
    assert validate_account({"origin": "agent", "credentials": dict(base)})["credentials"] == base
    for field in ("username", "password", "login_url"):
        missing = {k: v for k, v in base.items() if k != field}
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": "agent", "credentials": missing})
        assert exc.value.field == f"account.credentials.{field}"
        for bad in ("", 123):
            broken = dict(base)
            broken[field] = bad
            with pytest.raises(AuthInvalidError) as exc:
                validate_account({"origin": "agent", "credentials": broken})
            assert f"account.credentials.{field}" in str(exc.value)


def test_credentials_optional_selectors_must_be_strings():
    creds = {
        "username": "u",
        "password": "p",
        "login_url": "https://t.example/login",
        "domain": 5,
    }
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "credentials": creds})
    assert exc.value.field == "account.credentials.domain"


# --- technical conditions: optional list of {name, check} ---

def test_technical_conditions_require_name_and_check():
    good = {"technical_conditions": [{"name": "c", "check": "k"}]}
    assert validate_overview(good) == good
    for bad_entry in ({"name": "c"}, {"check": "k"}, {"name": "", "check": "k"}, ["c"]):
        with pytest.raises(AuthInvalidError) as exc:
            validate_overview({"technical_conditions": [bad_entry]})
        assert exc.value.field == "overview.technical_conditions[0]"
    with pytest.raises(AuthInvalidError) as exc:
        validate_overview({"technical_conditions": {"name": "c"}})
    assert exc.value.field == "overview.technical_conditions"


# --- snapshot cookies: {name, value} string objects, no CR/LF ---

def test_snapshot_cookies_require_string_name_and_value():
    good = {"origin": "agent", "snapshot": {"cookies": [{"name": "sid", "value": "A"}]}}
    assert validate_account(good) == good
    for bad_cookie in ({"name": "sid"}, {"name": "sid", "value": 5}, ["sid"]):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": "agent", "snapshot": {"cookies": [bad_cookie]}})
        assert exc.value.field == "account.snapshot.cookies[0]"


def test_snapshot_cookie_values_refuse_cr_lf():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {"origin": "agent", "snapshot": {"cookies": [{"name": "sid", "value": "a\r\nb"}]}}
        )
    assert exc.value.field == "account.snapshot.cookies[0]"


# --- snapshot headers: token names, no literal Cookie, clean values ---

def test_snapshot_headers_reject_a_non_token_name():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "snapshot": {"headers": {"Bad Header!": "v"}}})
    assert exc.value.field == "account.snapshot.headers.Bad Header!"


def test_snapshot_headers_reject_a_literal_cookie_header():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "snapshot": {"headers": {"Cookie": "sid=1"}}})
    assert "account.snapshot.headers.Cookie" in str(exc.value)


def test_snapshot_header_values_refuse_empty_and_cr_lf():
    for bad in ("", "a\r\nb"):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account(
                {"origin": "agent", "snapshot": {"headers": {"Authorization": bad}}}
            )
        assert exc.value.field == "account.snapshot.headers.Authorization"


# --- tokens: value + closed location, header names kept honest ---

def test_token_location_is_a_closed_enum():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {"origin": "agent", "tokens": {"s": {"value": "v", "location": "vault"}}}
        )
    assert exc.value.field == "account.tokens.s.location"


def test_token_value_is_required_nonempty_and_cr_lf_free():
    for bad_token in ({"location": "cookie"}, {"value": "", "location": "cookie"}):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": "agent", "tokens": {"s": bad_token}})
        assert exc.value.field == "account.tokens.s.value"
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {"origin": "agent", "tokens": {"s": {"value": "a\nb", "location": "storage"}}}
        )
    assert exc.value.field == "account.tokens.s.value"


def test_header_located_token_name_must_be_a_valid_header_token():
    good = {"origin": "agent", "tokens": {"Authorization": {"value": "B x", "location": "header"}}}
    assert validate_account(good) == good
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {"origin": "agent", "tokens": {"Bad Name!": {"value": "v", "location": "header"}}}
        )
    assert "account.tokens.Bad Name!" in str(exc.value)
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {"origin": "agent", "tokens": {"Cookie": {"value": "v", "location": "header"}}}
        )
    assert "account.tokens.Cookie" in str(exc.value)


def test_token_target_and_expiry_must_be_strings():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {"origin": "agent", "tokens": {"s": {"value": "v", "location": "cookie", "target": 5}}}
        )
    assert exc.value.field == "account.tokens.s.target"


# --- steel: minimal profile reference ---

def test_steel_reference_requires_a_profile():
    good = {"origin": "agent", "steel": {"profile": "prof-1"}}
    assert validate_account(good) == good
    for bad_steel in ({}, {"profile": ""}, {"profile": 5}, ["prof-1"]):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": "agent", "steel": bad_steel})
        assert exc.value.field == "account.steel.profile"


# --- snapshot shape corners ---

def test_snapshot_rejects_malformed_sections():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "snapshot": {"headers": [("A", "v")]}})
    assert exc.value.field == "account.snapshot.headers"
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "snapshot": {"cookies": {"sid": "A"}}})
    assert exc.value.field == "account.snapshot.cookies"
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "snapshot": {"params": [("a", "b")]}})
    assert exc.value.field == "account.snapshot.params"
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "snapshot": {"captured_at": 20260910}})
    assert exc.value.field == "account.snapshot.captured_at"
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "snapshot": {"graph_query": "MATCH (n)"}})
    assert exc.value.field == "account.snapshot.graph_query"


# --- roles: tagged credential sets validated by the same rules ---

def test_role_tagged_credential_sets_validate_recursively():
    record = {
        "origin": "operator",
        "roles": {
            "admin": {
                "username": "a",
                "password": "p",
                "login_url": "https://t.example/admin/login",
            },
            "shopper": {
                "username": "s",
                "password": "p",
                "login_url": "https://t.example/login",
            },
        },
        "default_role": "shopper",
    }
    assert validate_account(record) == record


def test_role_violation_names_its_role_and_field():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {
                "origin": "operator",
                "roles": {
                    "admin": {"username": "a", "login_url": "https://t.example/l"},
                },
            }
        )
    assert exc.value.field == "account.roles.admin.password"
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "operator", "roles": ["admin"]})
    assert exc.value.field == "account.roles"


def test_default_role_must_name_a_configured_role():
    with pytest.raises(AuthInvalidError) as exc:
        validate_account(
            {
                "origin": "operator",
                "roles": {"admin": {"username": "a", "password": "p", "login_url": "u"}},
                "default_role": "ghost",
            }
        )
    assert exc.value.field == "account.default_role"
    with pytest.raises(AuthInvalidError):
        validate_account({"origin": "operator", "default_role": "ghost"})


# --- procedure label and notes ---

def test_procedure_and_notes_must_be_string_labels():
    good = {"origin": "agent", "procedure": "self-registration", "notes": "fresh account"}
    assert validate_account(good) == good
    for bad in ("", 5):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": "agent", "procedure": bad})
        assert exc.value.field == "account.procedure"
    with pytest.raises(AuthInvalidError) as exc:
        validate_account({"origin": "agent", "notes": ["a"]})
    assert exc.value.field == "account.notes"


# --- import seam: no I/O, no env var ---

def test_importing_the_submodule_needs_no_env_var_and_performs_no_io():
    import os
    import subprocess
    import sys

    scrubbed = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": "src"}
    completed = subprocess.run(
        [sys.executable, "-c", "import polymerhus.app.auth; print('import-ok')"],
        capture_output=True,
        text=True,
        env=scrubbed,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "import-ok" in completed.stdout
