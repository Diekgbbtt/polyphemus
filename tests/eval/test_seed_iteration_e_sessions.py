"""The iteration-E preflight's all-session planner and mint loop."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = (
    _REPO
    / "docs"
    / "experiments"
    / "hunt-enhancement"
    / "iteration-e-siyucms-2026-11-08"
    / "seed_iteration_e.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("seed_iteration_e", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _load()


def _accounts() -> dict:
    return {
        "admin": {
            "role": "super_administrator",
            "root_url": "/index.php/admin/Index/index.html",
            "auth_probe": "/index.php/admin/Index/index.html",
            "procedure": "sign-in-admin-backend",
            "credentials": {
                "username": "admin",
                "password": "admin",
                "login_url": "/index.php/admin/Login/index.html",
            },
        },
        "member": {
            "role": "member",
            "root_url": "/index.php/index/user/index.html",
            "procedure": "sign-in-member",
            "credentials": {
                "username": "member@example.test",
                "password": "pw",
                "login_url": "/index.php/index/user/login.html",
            },
        },
        "baseline": {
            "credentials": {
                "username": "baseline",
                "password": "pw",
                "login_url": "/login",
            },
        },
        "no-credentials": {"role": "broken"},
    }


def test_plan_sessions_one_entry_per_credential_account():
    specs = seed.plan_sessions(
        _accounts(), host="t-1.target", project_id="p1"
    )

    assert [spec.account for spec in specs] == ["admin", "member", "baseline"]
    admin, member, baseline = specs

    assert admin.role == "super_administrator"
    assert admin.root_url == (
        "http://t-1.target/index.php/admin/Index/index.html"
    )
    assert admin.auth_probe == (
        "http://t-1.target/index.php/admin/Index/index.html"
    )
    assert admin.ref == "steel-auth-p1-admin"
    assert admin.login_page == "/index.php/admin/Login/index.html"
    assert admin.username == "admin"

    assert member.role == "member"
    assert member.auth_probe == member.root_url
    assert member.ref == "steel-auth-p1-member"

    assert baseline.role is None
    assert baseline.root_url == "http://t-1.target/"
    assert baseline.auth_probe == "http://t-1.target/"
    assert baseline.ref == "steel-auth-p1-baseline"


def test_mint_planned_sessions_continues_after_one_failure():
    specs = seed.plan_sessions(
        _accounts(), host="t-1.target", project_id="p1"
    )
    written: list[tuple[str, str]] = []

    def mint(spec):
        if spec.account == "member":
            raise RuntimeError("member sign-in returned no PHPSESSID")
        return f"cookie-{spec.account}"

    def write(spec, value):
        written.append((spec.account, value))

    results = seed.mint_planned_sessions(specs, mint=mint, write=write)

    assert [minted for _spec, minted, _error in results] == [
        True,
        False,
        True,
    ]
    assert results[1][2] == "member sign-in returned no PHPSESSID"
    assert written == [
        ("admin", "cookie-admin"),
        ("baseline", "cookie-baseline"),
    ]
