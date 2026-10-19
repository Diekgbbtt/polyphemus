"""Gateway integration against the `steel` CLI scaffold (#395).

The real `steel_exec` tool drives the scaffold on PATH, so the routing, the
`--local` injection, the catalogue guard, the variadic-boundary guard, and the
envelope are all exercised end to end without docker or the cloud.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

import kali.mcp_server as m
from tests.support import steel_cli_scaffold as scaffold

STEEL_EXEC = m.steel_exec.fn


def _steel_exec(**kwargs):
    return asyncio.run(STEEL_EXEC(**kwargs))


@pytest.fixture()
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setenv("KALI_WORKDIR", str(root))
    return root


@pytest.fixture()
def steel(tmp_path, monkeypatch):
    return scaffold.install(tmp_path, monkeypatch)


def _joined(handle):
    return [" ".join(call) for call in scaffold.calls(handle)]


def test_command_mode_injects_local_and_completes_a_lifecycle(workroot, tmp_path, monkeypatch):
    handle = scaffold.install(tmp_path, monkeypatch)
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://steel.test:3000/v1")

    start = _steel_exec(
        command="steel browser start --session s1 --session-timeout 600000 --json",
        session_id="s1",
    )
    assert start["returncode"] == 0, start
    assert json.loads(start["stdout"])["success"] is True
    assert any("browser start" in call and "--local" in call for call in _joined(handle))

    navigating = _steel_exec(
        command="steel browser navigate https://example.com --session s1 --json",
        session_id="s1",
    )
    assert json.loads(navigating["stdout"])["data"]["title"] == "Example Domain"

    stopped = _steel_exec(command="steel browser stop --session s1 --json", session_id="s1")
    assert json.loads(stopped["stdout"])["data"]["stoppedSessions"] == ["s1"]
    assert scaffold.read_state(handle)["sessions"] == {}


def test_no_injection_when_the_endpoint_is_unset(workroot, tmp_path, monkeypatch):
    handle = scaffold.install(tmp_path, monkeypatch)
    monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)
    out = _steel_exec(command="steel browser sessions --json", session_id="s1")
    assert out["returncode"] == 0
    assert all("--local" not in call for call in _joined(handle))


def test_catalogue_guard_refuses_a_live_name(workroot, tmp_path, monkeypatch):
    handle = scaffold.install(tmp_path, monkeypatch)
    subprocess.run(["steel", "browser", "start", "--session", "taken", "--json"],
                   capture_output=True, text=True)
    out = _steel_exec(command="steel browser start --session taken --json", session_id="s1")
    assert out["returncode"] == 2
    assert out["stderr"].startswith("refused:session-taken")
    # The refusal dispatched no start of its own: the one live session is the
    # direct one, not a tool-created twin.
    assert list(scaffold.read_state(handle)["sessions"]) == ["taken"]


def test_variadic_without_boundary_refused_never_executed(workroot, steel):
    out = _steel_exec(
        command="steel browser fill --session s1 --json '#u' 'v'", session_id="s1"
    )
    assert out["returncode"] == 2
    assert out["stderr"].startswith("refused:variadic-boundary")
    assert not any("fill" in call for call in _joined(steel))


def test_variadic_with_boundary_runs_and_the_value_survives(workroot, steel):
    _steel_exec(command="steel browser start --session s1 --json", session_id="s1")
    filled = _steel_exec(
        command='steel browser fill --session s1 --json "#u" -- "standard_user"',
        session_id="s1",
    )
    assert filled["returncode"] == 0, filled
    read = _steel_exec(
        command="steel browser get value '#u' --session s1 --json", session_id="s1"
    )
    assert json.loads(read["stdout"])["data"]["value"] == "standard_user"


def test_envelope_shape_is_unchanged(workroot, steel):
    out = _steel_exec(command="steel browser sessions --json", session_id="s1")
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}
