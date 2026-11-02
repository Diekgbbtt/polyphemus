"""#223 amendment (2026-10-29): the authenticated-context oracle.

The one deterministic auth verdict is a browser request to
`overview.auth_probe.url`: 2xx is authenticated, 401/403/3xx is not, anything
else is indeterminate and stops the run. These tests pin the pure contract and
the model-facing text seams; the pipeline and crawl behaviour live in their
own tiers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.app.auth.probe import (
    AUTHENTICATED,
    INDETERMINATE,
    UNAUTHENTICATED,
    auth_probe_url,
    classify_probe,
    is_valid_probe_url,
    resolve_auth_probe,
)
from polymerhus.app.auth.records import AuthInvalidError, validate_overview
from polymerhus.recon.control import authn_loop as L

REPO = Path(__file__).resolve().parents[2]


# --- the pure oracle ----------------------------------------------------------


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_2xx_is_authenticated(status):
    assert classify_probe(status=status) == AUTHENTICATED


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 401, 403])
def test_redirect_and_auth_rejection_are_unauthenticated(status):
    assert classify_probe(status=status) == UNAUTHENTICATED


@pytest.mark.parametrize("status", [400, 404, 409, 429, 500, 502, None])
def test_everything_else_is_indeterminate(status):
    assert classify_probe(status=status) == INDETERMINATE


def test_a_followed_redirect_never_passes_even_with_a_2xx_final_response():
    # `steel browser navigate` follows a 302 to a 200 login page and reports
    # success. The fetch's `redirected` flag is the discriminator.
    assert classify_probe(status=200, redirected=True) == UNAUTHENTICATED


def test_probe_url_reads_only_the_url_key():
    assert auth_probe_url({"auth_probe": {"url": "/api/me"}}) == "/api/me"
    assert auth_probe_url({"auth_probe": {"url": 5}}) is None
    assert auth_probe_url({}) is None
    assert auth_probe_url(None) is None


def test_resolve_joins_a_relative_path_to_the_origin():
    overview = {"auth_probe": {"url": "/api/me"}}
    assert resolve_auth_probe(overview, "http://t.example:8080") == (
        "http://t.example:8080/api/me")
    assert resolve_auth_probe(overview, "http://t.example:8080/") == (
        "http://t.example:8080/api/me")


def test_resolve_never_rewrites_an_absolute_agent_minted_url():
    absolute = "https://live.example/api/me"
    assert resolve_auth_probe({"auth_probe": {"url": absolute}},
                              "http://t.example") == absolute


# --- the store shape ----------------------------------------------------------


def test_overview_accepts_a_deployment_neutral_probe_path():
    good = {"auth_probe": {"url": "/api/authentication"}}
    assert validate_overview(good) == good
    with_query = {"auth_probe": {"url": "/api/me?fields=id"}}
    assert validate_overview(with_query) == with_query


def test_overview_accepts_an_absolute_http_probe_for_agent_live_state():
    good = {"auth_probe": {"url": "https://target.example/api/me"}}
    assert validate_overview(good) == good


@pytest.mark.parametrize("bad", [
    None,
    "https://target.example/api/me",
    {},
    {"url": ""},
    {"url": 5},
    {"url": "api/me"},
    {"url": "//target.example/api/me"},
    {"url": "ftp://target.example/api/me"},
    {"url": "https://user:pass@target.example/api/me"},
    {"url": "/api/me#fragment"},
    {"url": "/api/me\n"},
    {"url": "/api/me", "status": 200},
])
def test_overview_refuses_a_malformed_probe(bad):
    with pytest.raises(AuthInvalidError):
        validate_overview({"auth_probe": bad})


def test_probe_url_shape_helper_is_shared():
    assert is_valid_probe_url("/api/me")
    assert is_valid_probe_url("https://target.example/api/me")
    assert not is_valid_probe_url("api/me")
    assert not is_valid_probe_url("//target.example/api/me")
    assert not is_valid_probe_url("https://user:pass@target.example/api/me")
    assert not is_valid_probe_url("/api/me#frag")


# --- the gate and the model-facing texts -------------------------------------


def test_declared_surface_with_no_accounts_runs_the_loop_to_mint():
    overview = {"login_endpoint": "/login",
                "auth_probe": {"url": "/api/me"}}
    assert L.classify_gate(overview, {}) == "run_loop"


def test_an_oracle_alone_declares_a_surface():
    assert L.declares_auth_surface({"auth_probe": {"url": "/api/me"}})


def test_gateway_prompt_names_the_oracle_and_forbids_fail_open():
    text = (REPO / "src" / "polymerhus" / "recon" / "control" / "prompts"
            / "auth-gateway.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "auth_probe" in text
    assert "2xx" in text
    assert "401" in text and "403" in text and "3xx" in text
    assert "indeterminate" in lower
    assert "redirected" in lower
    assert "mint" in lower
    assert "fail-closed" in lower or "does not fail open" in lower
    assert "authenticated landing" not in lower
    assert "fails open" not in lower
    assert "fail open with" not in lower
    assert "fail-open collection" not in lower


def test_branch_manner_names_the_oracle_and_carries_the_mint_path():
    from polymerhus.recon.control.orchestrator_agent import _BRANCH_MANNER

    text = "\n".join(_BRANCH_MANNER.values()).lower()
    assert "auth_probe" in text
    assert "2xx" in text
    assert "401" in text and "403" in text and "3xx" in text
    assert "indeterminate" in text
    assert "mint" in text or "sign-up" in text
    assert "fails open" not in text
    assert "fail open with" not in text
    assert "fail-open collection" not in text


def test_loop_hints_use_the_oracle_and_stop_on_indeterminate():
    hints = {
        "retrieved": L.RETRIEVED_HINT,
        "validation": L.VALIDATION_HINT,
        "generation": L.GENERATION_HINT,
        "signin": L.GENERATION_SIGNIN_HINT,
        "self_service": L.SELF_SERVICE_HINT,
    }
    for name, hint in hints.items():
        lower = hint.lower()
        assert "fails open" not in lower, name
        assert "fail open with" not in lower, name
        assert "fail-open collection" not in lower, name
    assert "auth_probe" in hints["retrieved"]
    assert "2xx" in hints["retrieved"]
    assert "indeterminate" in hints["validation"].lower()
    assert "mint" in hints["generation"].lower()
    assert "mint" in hints["signin"].lower()
    assert "missing bootstrap" in hints["self_service"].lower()
