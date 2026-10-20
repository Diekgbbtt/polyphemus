"""The one `steel` wrapper (#395, D359-13).

It hides local mode from the skill and fixes the local user agent after a
start. A fake real binary records argv, so the test never reaches Steel.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[1] / "kali" / "steel_wrapper.sh"


def _fake_real(tmp_path: Path) -> tuple[Path, Path]:
    calls = tmp_path / "calls.jsonl"
    real = tmp_path / "steel-real"
    real.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(calls)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print(json.dumps({'success': True, 'argv': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    real.chmod(0o755)
    return real, calls


def _run(tmp_path, *argv, endpoint=None):
    real, calls = _fake_real(tmp_path)
    env = {**os.environ, "STEEL_REAL_BINARY": str(real)}
    env.pop("STEEL_BROWSER_API_URL", None)
    if endpoint:
        env["STEEL_BROWSER_API_URL"] = endpoint
    result = subprocess.run(
        ["bash", str(WRAPPER), *argv],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    recorded = [
        json.loads(line) for line in calls.read_text().splitlines()
    ] if calls.exists() else []
    return result, recorded


def test_local_browser_command_gets_the_local_flag(tmp_path):
    result, calls = _run(
        tmp_path, "browser", "cookies", "--json",
        endpoint="http://steel.test:3000/v1")
    assert calls == [["--local", "browser", "cookies", "--json"]]
    assert json.loads(result.stdout)["success"] is True


def test_cloud_command_is_unchanged(tmp_path):
    _, calls = _run(tmp_path, "browser", "cookies", "--json")
    assert calls == [["browser", "cookies", "--json"]]


def test_an_explicit_local_flag_is_not_duplicated(tmp_path):
    _, calls = _run(
        tmp_path, "--local", "browser", "cookies", "--json",
        endpoint="http://steel.test:3000/v1")
    assert calls == [["--local", "browser", "cookies", "--json"]]


def test_version_and_login_pass_through(tmp_path):
    _, calls = _run(
        tmp_path, "--version", endpoint="http://steel.test:3000/v1")
    assert calls == [["--version"]]


def test_local_start_sets_the_fixed_user_agent_before_navigation(tmp_path):
    result, calls = _run(
        tmp_path, "browser", "start", "--session", "s1", "--json",
        endpoint="http://steel.test:3000/v1")
    assert calls[0] == ["--local", "browser", "start", "--session", "s1", "--json"]
    assert calls[1][:6] == [
        "browser", "set", "useragent", "--local", "--session", "s1"]
    assert calls[1][-1].startswith("Mozilla/5.0")
    assert "Chrome/155" in calls[1][-1]
    assert "Headless" not in calls[1][-1]
    # The start envelope is unchanged; the follow-up is discarded.
    assert json.loads(result.stdout)["argv"][:2] == ["--local", "browser"]


def test_cloud_start_does_not_set_the_user_agent(tmp_path):
    _, calls = _run(tmp_path, "browser", "start", "--session", "s1", "--json")
    assert calls == [["browser", "start", "--session", "s1", "--json"]]


def test_script_text_is_left_alone_but_direct_calls_are_wrapped(tmp_path):
    _, calls = _run(
        tmp_path, "scrape", "https://example.com", "--json",
        endpoint="http://steel.test:3000/v1")
    assert calls[0][0] == "--local"
