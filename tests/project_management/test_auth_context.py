"""FR-AUTH unit tier — the role/realm-tagged auth_context selector + validation +
the structural-key guarantee that role tags never serialise as HTTP headers.

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md FR-AUTH ledger).
"""
import pytest

from polymerhus.recon.control.auth import select_auth_context
from polymerhus.recon.domain.pod import _iter_auth_headers
from polymerhus.project_management.auth_context import validate_auth_context


_ROLE_TAGGED = {
    "roles": {
        "admin": {"realm": "credential", "Authorization": "Bearer ADMIN", "cookies": [{"name": "sid", "value": "A"}]},
        "shopper": {"cookies": [{"name": "sid", "value": "S"}]},
    },
    "default_role": "shopper",
}


# --- AST-AUTH-01: a named role selects its OWN self-contained credentials ---

def test_selector_returns_the_named_roles_credentials():
    admin = select_auth_context(_ROLE_TAGGED, "admin")
    assert admin["Authorization"] == "Bearer ADMIN"
    assert admin["cookies"] == [{"name": "sid", "value": "A"}]
    # not the shopper's creds
    assert "Authorization" not in select_auth_context(_ROLE_TAGGED, "shopper")
    # an unconfigured role gets NO creds (never another role's)
    assert select_auth_context(_ROLE_TAGGED, "ghost") == {}


# --- AST-AUTH-02: role=None uses default_role, else flat; structural keys stripped ---

def test_selector_default_role_and_flat_fallback():
    # default_role=shopper -> shopper's set
    d = select_auth_context(_ROLE_TAGGED, None)
    assert d["cookies"] == [{"name": "sid", "value": "S"}]
    assert "roles" not in d and "default_role" not in d  # structural keys never in the selected set

    # no default_role -> the flat unroled creds (top-level keys), roles stripped
    flat_plus_roles = {"Authorization": "Bearer FLAT", "roles": {"admin": {"cookies": []}}}
    sel = select_auth_context(flat_plus_roles, None)
    assert sel == {"Authorization": "Bearer FLAT"}  # roles stripped, flat creds kept

    assert select_auth_context(None) == {} and select_auth_context({}) == {}


# --- AST-AUTH-04: validation recurses into each role with the same rules ---

def test_validation_recurses_into_roles():
    # a valid role-tagged context passes
    validate_auth_context(_ROLE_TAGGED)

    # a bad cookie INSIDE a role is rejected (same per-set rules)
    with pytest.raises(ValueError):
        validate_auth_context({"roles": {"admin": {"cookies": [{"name": "x"}]}}})  # missing value
    # a literal Cookie header inside a role is rejected
    with pytest.raises(ValueError):
        validate_auth_context({"roles": {"admin": {"Cookie": "sid=1"}}})
    # a non-string header value inside a role is rejected
    with pytest.raises(ValueError):
        validate_auth_context({"roles": {"admin": {"Authorization": 123}}})
    # roles must be an object
    with pytest.raises(ValueError):
        validate_auth_context({"roles": ["admin"]})
    # default_role must name a configured role
    with pytest.raises(ValueError):
        validate_auth_context({"roles": {"admin": {}}, "default_role": "nobody"})
    # realm must be a string
    with pytest.raises(ValueError):
        validate_auth_context({"roles": {"admin": {"realm": 5}}})


# --- AST-AUTH-05: structural keys NEVER serialise as HTTP headers ---

def test_structural_keys_never_serialised_as_headers():
    # select a role, then serialise its set to headers: roles/default_role/realm
    # must never appear as header NAMES (they are reserved in the pod serialiser too)
    admin = select_auth_context(_ROLE_TAGGED, "admin")
    header_names = {name for name, _ in _iter_auth_headers(admin)}
    assert "realm" not in header_names  # realm is metadata, not a header
    assert "roles" not in header_names and "default_role" not in header_names
    assert header_names == {"Cookie", "Authorization"}  # only real headers

    # defence in depth: even handing the FULL role-tagged context to the serialiser
    # (bypassing the selector) must not emit roles/default_role as headers
    names_full = {name for name, _ in _iter_auth_headers(_ROLE_TAGGED)}
    assert "roles" not in names_full and "default_role" not in names_full


# --- AST-AUTH-06: legacy flat auth_context is unchanged ---

def test_legacy_flat_auth_context_unchanged():
    legacy = {"cookies": [{"name": "sid", "value": "L"}], "Authorization": "Bearer LEGACY"}
    # selects to itself (no roles) and validates
    assert select_auth_context(legacy, None) == legacy
    validate_auth_context(legacy)
    # serialises exactly as before
    names = {name for name, _ in _iter_auth_headers(select_auth_context(legacy, None))}
    assert names == {"Cookie", "Authorization"}
