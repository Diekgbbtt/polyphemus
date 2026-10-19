"""Arm L (#384): the data-dependency validator refuses deployment origins.

The placed artifacts must stay deployment-neutral. An absolute URL with a host
in the auth context (a bootstrap capture) goes stale the moment the target is
redeployed on a new port - the arm K white-jotter failure - and a `base_url`
in the L1 surface carries the same poison in review-artifact form.

Unit tier over the REAL validator functions (importlib-loaded, as
`test_measure_gt_wellformedness.py` does).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = _REPO_ROOT / "tools" / "bootstrap" / "validate_data_dependencies.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "validate_data_dependencies_tool", _TOOL_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _account(credentials: dict) -> dict:
    return {"origin": "operator", "procedure": "password-login",
            "credentials": credentials}


def _project_dir(tmp_path: Path, accounts: dict) -> Path:
    auth = tmp_path / "auth"
    auth.mkdir(parents=True, exist_ok=True)
    (auth / "overview.yaml").write_text(
        yaml.safe_dump({"login_endpoint": "/api/login"}), encoding="utf-8"
    )
    (auth / "credentials.yaml").write_text(
        yaml.safe_dump({"accounts": accounts}), encoding="utf-8"
    )
    return tmp_path


def _base_credentials(**overrides) -> dict:
    creds = {"username": "alice", "password": "pw", "login_url": "/api/login"}
    creds.update(overrides)
    return creds


def test_a_path_login_url_is_accepted(tmp_path):
    project = _project_dir(tmp_path, {"alice": _account(_base_credentials())})
    assert [e for e in tool.check_auth(project) if ".login_url" in e] == []


def test_an_absolute_login_url_is_refused(tmp_path):
    project = _project_dir(
        tmp_path,
        {"alice": _account(_base_credentials(
            login_url="http://46.224.225.245:35493/api/login"))},
    )
    errors = tool.check_auth(project)
    assert any(".login_url" in e and "absolute" in e for e in errors), errors


def test_a_role_credential_set_is_checked_too(tmp_path):
    account = _account(_base_credentials())
    account["roles"] = {
        "sysAdmin": {"username": "admin", "password": "pw2",
                     "login_url": "http://46.224.225.245:35493/api/login"},
    }
    project = _project_dir(tmp_path, {"alice": account})
    errors = tool.check_auth(project)
    assert any("roles.sysAdmin.login_url" in e and "absolute" in e for e in errors), errors


def test_a_present_domain_is_refused(tmp_path):
    project = _project_dir(
        tmp_path, {"alice": _account(_base_credentials(domain="46.224.225.245"))}
    )
    errors = tool.check_auth(project)
    assert any("domain" in e for e in errors), errors


def test_an_absolute_url_anywhere_in_the_account_is_refused(tmp_path):
    creds = _base_credentials()
    creds["snapshot"] = {
        "headers": {"Origin": "http://46.224.225.245:35493"},
        "captured_at": "2026-10-17T19:50:54Z",
    }
    project = _project_dir(tmp_path, {"alice": _account(creds)})
    errors = tool.check_auth(project)
    assert any("absolute" in e and "snapshot" in e for e in errors), errors


def _l1_surface(tmp_path: Path, extra: dict) -> Path:
    doc = {
        "target": "example",
        "units": [
            {"label": "Service",
             "identity": {"business_function_slug": "svc"},
             "props": {}},
        ],
    }
    doc.update(extra)
    path = tmp_path / "l1-surface.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def test_a_base_url_in_the_l1_surface_is_refused(tmp_path):
    path = _l1_surface(tmp_path, {"base_url": "http://46.224.225.245:35493"})
    errors = tool.check_l1_surface(path)
    assert any("base_url" in e for e in errors), errors


def test_an_l1_surface_without_base_url_passes(tmp_path):
    path = _l1_surface(tmp_path, {})
    assert [e for e in tool.check_l1_surface(path) if "base_url" in e] == []
