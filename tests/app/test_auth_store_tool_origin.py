"""Arm L (#384): the auth tool renders the project's canonical target origin.

The stored data-dependency artifacts carry NO deployment origin: a bootstrap
capture (host:port) goes stale the moment the target is redeployed, which is
exactly how the arm K white-jotter auth gateway thrashed. The store keeps
deployment-neutral paths; every READ resolves them against the project's
canonical origin - `settings.recon.target_seed`, the same fact the recon
pipeline probes and the eval front routes.

Unit tier: the REAL tool object over an explicit-root temp store and an
injected settings reader (CODING_STANDARD 5/6/8/10).
"""
from __future__ import annotations

from polymerhus.app.auth.store import AuthStore
from polymerhus.app.auth.tool import build_auth_store_tool

PROJECT = "proj-auth-origin-1"
PASSWORD = "pw-literal"


def _store(tmp_path, *, login_url="/api/login", with_domain=None):
    store = AuthStore(tmp_path)
    credentials = {"username": "alice", "password": PASSWORD, "login_url": login_url}
    if with_domain is not None:
        credentials["domain"] = with_domain
    store.write(
        PROJECT,
        "accounts.alice",
        {"procedure": "password-login", "credentials": credentials},
        origin="operator",
    )
    return store


def _settings(seed):
    def settings_fn(project_id):
        assert project_id == PROJECT
        return {"target_seed": seed} if seed else {}

    return settings_fn


def test_relative_login_url_resolves_against_the_project_origin(tmp_path):
    tool = build_auth_store_tool(
        PROJECT, _store(tmp_path), settings_fn=_settings("t-abc.target")
    )
    out = tool.invoke({"command": "read", "path": "accounts.alice.credentials"})
    assert out["ok"] is True
    # the path resolves against the canonical origin, and the informational
    # `domain` is back-filled when the artifact carried none
    assert out["value"]["login_url"] == "http://t-abc.target/api/login"
    assert out["value"]["domain"] == "t-abc.target"


def test_the_full_read_resolves_accounts_too(tmp_path):
    tool = build_auth_store_tool(
        PROJECT, _store(tmp_path), settings_fn=_settings("t-abc.target")
    )
    value = tool.invoke({"command": "read", "path": ""})["value"]
    assert (
        value["accounts"]["alice"]["credentials"]["login_url"]
        == "http://t-abc.target/api/login"
    )


def test_read_only_view_resolves_and_stays_redacted(tmp_path):
    tool = build_auth_store_tool(
        PROJECT,
        _store(tmp_path),
        read_only=True,
        settings_fn=_settings("t-abc.target"),
    )
    value = tool.invoke({"command": "read", "path": "accounts.alice"})["value"]
    assert value["credentials"]["login_url"] == "http://t-abc.target/api/login"
    assert value["credentials"]["domain"] == "t-abc.target"
    assert value["credentials"]["password"] == "<redacted>"


def test_a_seed_with_a_scheme_is_preserved(tmp_path):
    tool = build_auth_store_tool(
        PROJECT, _store(tmp_path), settings_fn=_settings("https://app.example.com")
    )
    out = tool.invoke({"command": "read", "path": "accounts.alice.credentials"})
    assert out["value"]["login_url"] == "https://app.example.com/api/login"


def test_an_absolute_login_url_is_left_untouched(tmp_path):
    tool = build_auth_store_tool(
        PROJECT,
        _store(tmp_path, login_url="https://minted.example/session/login"),
        settings_fn=_settings("t-abc.target"),
    )
    out = tool.invoke({"command": "read", "path": "accounts.alice.credentials"})
    assert out["value"]["login_url"] == "https://minted.example/session/login"


def test_an_explicit_domain_is_never_overwritten(tmp_path):
    tool = build_auth_store_tool(
        PROJECT,
        _store(tmp_path, with_domain="keep.example"),
        settings_fn=_settings("t-abc.target"),
    )
    out = tool.invoke({"command": "read", "path": "accounts.alice.credentials"})
    assert out["value"]["domain"] == "keep.example"


def test_no_seed_leaves_paths_untouched(tmp_path):
    tool = build_auth_store_tool(
        PROJECT, _store(tmp_path), settings_fn=_settings(None)
    )
    out = tool.invoke({"command": "read", "path": "accounts.alice.credentials"})
    assert out["value"]["login_url"] == "/api/login"
    assert "domain" not in out["value"]


def test_a_settings_read_failure_degrades_to_no_resolution(tmp_path):
    def boom(project_id):
        raise RuntimeError("settings unavailable")

    tool = build_auth_store_tool(PROJECT, _store(tmp_path), settings_fn=boom)
    out = tool.invoke({"command": "read", "path": "accounts.alice.credentials"})
    assert out["ok"] is True
    assert out["value"]["login_url"] == "/api/login"
