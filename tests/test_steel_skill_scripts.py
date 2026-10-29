"""Unit tier: the canonical Steel skill scripts.

The scripts are run against a fake `steel` executable on PATH, so no browser,
no daemon, and no network are touched. The fake records argv and returns the
envelopes the pinned CLI uses. These tests pin the two things the scripts own:
the argv that reaches the CLI, and the JSON they return.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = (
    REPO_ROOT / "skills" / "internal" / "tools" / "steel-browser" / "references"
)

FAKE_STEEL = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

with open(os.environ["FAKE_STEEL_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")

trace_log = os.environ.get("FAKE_STEEL_TRACE_LOG")
if trace_log:
    with open(trace_log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "argv": sys.argv[1:],
            "trace": os.environ.get("KALI_STEEL_TRACE"),
        }, ensure_ascii=False) + "\n")

args = sys.argv[1:]
if args[:1] == ["--local"]:
    args = args[1:]


def out(payload, code=0):
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


if "--session" in args:
    session = args[args.index("--session") + 1]
    if session == "missing":
        sys.stderr.write(json.dumps({
            "error": {
                "code": "unknown_session",
                "message": "session 'missing' is not live",
                "recovery": {"action": "use_live"},
            },
        }))
        raise SystemExit(2)

if args[:1] == ["sessions"]:
    sub = args[1] if len(args) > 1 else ""
    if sub == "get":
        out({"data": {
            "id": "sid-1", "status": "live",
            "createdAt": "2026-01-01T00:00:00Z", "duration": 12,
            "eventCount": 0, "timeout": 0,
            "sessionViewerUrl": "http://viewer",
            "debugUrl": "http://viewer/v1/sessions/debug",
            "debuggerUrl": "http://debugger",
            "dimensions": {"width": 1280, "height": 720},
            "userAgent": "UA",
        }, "success": True})
    if sub in ("logs", "agent-logs", "traces"):
        out({"error": "Steel API request failed (404): not found",
             "error_code": "not_found", "success": False}, 5)

if args[:1] == ["browser"]:
    sub = args[1] if len(args) > 1 else ""
    if sub == "navigate":
        out({"data": {"url": args[2], "title": "Target"}, "success": True})
    if sub == "wait":
        out({"data": {}, "success": True})
    if sub == "eval":
        script = args[2]
        if "redirected" in script and "fetch" in script:
            mode = os.environ.get("FAKE_STEEL_ORACLE", "ok")
            if mode == "redirect":
                out({"data": {"status": 200, "redirected": True,
                              "url": "http://target/login"}, "success": True})
            if mode == "indeterminate":
                out({"data": {"status": 500, "redirected": False,
                              "url": "http://target/api/me"}, "success": True})
            out({"data": {"status": 200, "redirected": False,
                          "url": "http://target/api/me"}, "success": True})
        if "querySelectorAll" in script:
            out({"data": {
                "selector": "a", "count": 2, "scanned": 2,
                "returned": 1, "truncated": False,
                "elements": [{
                    "index": 0, "tag": "a", "text": "one",
                    "attributes": {"href": "/one"}, "visible": True,
                }],
            }, "success": True})
        out({"data": "OK", "success": True})
    if sub == "get":
        which = args[2]
        if which == "url":
            out({"data": "http://target/login", "success": True})
        if which == "title":
            out({"data": "Target", "success": True})
    if sub == "snapshot":
        out({"data": "- form\n  - textbox", "success": True})
    if sub == "screenshot":
        path = args[args.index("-o") + 1]
        Path(path).write_bytes(b"png")
        out({"data": {"path": path}, "success": True})

out({"error": "unhandled", "error_code": "unhandled", "success": False}, 1)
'''


@pytest.fixture()
def fake_steel(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "steel"
    executable.write_text(FAKE_STEEL, encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "calls.jsonl"
    trace_log = tmp_path / "traces.jsonl"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_STEEL_LOG": str(log),
        "FAKE_STEEL_TRACE_LOG": str(trace_log),
    }
    return env, log


def _run(script: str, *args: str, env: dict) -> tuple[int, dict, list[list[str]]]:
    result = subprocess.run(
        [sys.executable, str(REFERENCES / script), *args],
        capture_output=True, text=True, env=env, timeout=30,
    )
    try:
        output = json.loads(result.stdout)
    except ValueError:
        output = {"raw_stdout": result.stdout, "raw_stderr": result.stderr}
    calls = []
    log = Path(env["FAKE_STEEL_LOG"])
    if log.exists():
        calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result.returncode, output, calls


def _run_sh(script: str, *args: str, env: dict) -> tuple[int, dict, list[list[str]]]:
    result = subprocess.run(
        ["bash", str(REFERENCES / script), *args],
        capture_output=True, text=True, env=env, timeout=30,
    )
    try:
        output = json.loads(result.stdout)
    except ValueError:
        output = {"raw_stdout": result.stdout, "raw_stderr": result.stderr}
    calls = []
    log = Path(env["FAKE_STEEL_LOG"])
    if log.exists():
        calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result.returncode, output, calls


def test_auth_oracle_classifies_a_2xx_as_authenticated(fake_steel):
    env, _ = fake_steel
    code, output, calls = _run_sh(
        "auth-oracle.sh", "http://target/api/me",
        env={**env, "SESSION": "s1"},
    )
    assert code == 0
    assert output["outcome"] == "authenticated"
    assert output["success"] is True
    assert output["status"] == 200
    assert not [call for call in calls if call[:2] in (
        ["browser", "start"], ["browser", "stop"])]


def test_auth_oracle_fails_a_followed_redirect(fake_steel):
    env, _ = fake_steel
    code, output, _calls = _run_sh(
        "auth-oracle.sh", "http://target/api/me",
        env={**env, "SESSION": "s1", "FAKE_STEEL_ORACLE": "redirect"},
    )
    assert code == 0
    assert output["outcome"] == "unauthenticated"
    assert output["success"] is False
    assert output["redirected"] is True


def test_auth_oracle_does_not_pass_an_indeterminate_status(fake_steel):
    env, _ = fake_steel
    code, output, _calls = _run_sh(
        "auth-oracle.sh", "http://target/api/me",
        env={**env, "SESSION": "s1", "FAKE_STEEL_ORACLE": "indeterminate"},
    )
    assert code == 0
    assert output["outcome"] == "indeterminate"
    assert output["success"] is False


def test_load_eval_loads_waits_and_evals_without_lifecycle(fake_steel):
    env, _ = fake_steel

    code, output, calls = _run(
        "load-eval.py", "--session", "s1", "--url", "http://target/login",
        "--wait-selector", "form", "--eval", "document.title", env=env,
    )

    assert code == 0
    assert output["ok"] is True
    assert output["result"] == "OK"
    assert output["url"] == "http://target/login"
    assert output["title"] == "Target"
    assert not [call for call in calls if call[:2] in (
        ["browser", "start"], ["browser", "stop"])]
    eval_calls = [call for call in calls if call[:2] == ["browser", "eval"]]
    assert eval_calls and eval_calls[0][2] == "document.title"
    assert any(call[:2] == ["browser", "wait"] for call in calls)
    assert any(call[:3] == ["browser", "get", "url"] for call in calls)


def test_load_eval_returns_the_guard_error_for_a_missing_session(fake_steel):
    env, _ = fake_steel

    code, output, calls = _run(
        "load-eval.py", "--session", "missing", "--url",
        "http://target/login", "--eval", "1", env=env,
    )

    assert code == 2
    assert output["ok"] is False
    assert output["error"]["code"] == "unknown_session"
    assert output["stage"] == "navigate http://target/login"
    assert not [call for call in calls if call[:2] == ["browser", "eval"]]


def test_select_elements_escapes_the_selector_and_projects(fake_steel):
    env, _ = fake_steel

    code, output, calls = _run(
        "select-elements.py", "--session", "s1",
        "--selector", 'a[href="/x"]', "--attrs", "href,class",
        "--limit", "5", "--no-wait", env=env,
    )

    assert code == 0
    assert output["ok"] is True
    assert output["count"] == 2
    assert output["returned"] == 1
    assert output["elements"][0]["attributes"] == {"href": "/one"}
    eval_calls = [call for call in calls if call[:2] == ["browser", "eval"]]
    assert eval_calls
    script = eval_calls[0][2]
    assert 'a[href=\\"' in script
    assert '"attrs": ["href", "class"]' in script
    assert '"limit": 5' in script
    assert not [call for call in calls if call[:2] in (
        ["browser", "start"], ["browser", "stop"])]


def test_session_records_reports_unsupported_probes_and_evidence(fake_steel, tmp_path):
    env, _ = fake_steel

    code, output, calls = _run(
        "session-records.py", "--session", "s1",
        "--out-dir", str(tmp_path), env=env,
    )

    assert code == 0
    assert output["ok"] is True
    assert output["metadata"]["id"] == "sid-1"
    assert output["metadata"]["debugUrl"].endswith("/v1/sessions/debug")
    assert output["live_view"]["kind"] == "player"
    assert output["live_view"]["addressable"] is False
    assert output["live_view"]["scope"] == "active"
    assert output["records"]["logs"]["supported"] is False
    assert output["records"]["logs"]["error"]["code"] == "not_found"
    assert output["records"]["agent_logs"]["supported"] is False
    assert output["records"]["traces"]["supported"] is False
    assert output["snapshot"]["chars"] > 0
    assert output["screenshot"]["bytes"] == 3
    assert output["partial"] is False
    assert not [call for call in calls if call[:2] in (
        ["browser", "start"], ["browser", "stop"])]


def test_session_records_scopes_expected_probe_errors(fake_steel, tmp_path):
    env, _ = fake_steel
    env = {**env, "KALI_STEEL_TRACE": "/tmp/outer-trace.jsonl"}

    code, output, _ = _run(
        "session-records.py", "--session", "s1",
        "--out-dir", str(tmp_path), "--no-screenshot", env=env,
    )

    assert code == 0
    assert output["ok"] is True
    traces = [
        json.loads(line)
        for line in Path(env["FAKE_STEEL_TRACE_LOG"]).read_text().splitlines()
    ]
    by_probe = {}
    for entry in traces:
        argv = entry["argv"]
        if "sessions" in argv and "get" in argv:
            by_probe["get"] = entry["trace"]
        if "sessions" in argv and "logs" in argv:
            by_probe["logs"] = entry["trace"]
        if "browser" in argv and "snapshot" in argv:
            by_probe["snapshot"] = entry["trace"]
    assert by_probe["get"] == "/tmp/outer-trace.jsonl"
    assert by_probe["snapshot"] == "/tmp/outer-trace.jsonl"
    assert by_probe["logs"] is None
