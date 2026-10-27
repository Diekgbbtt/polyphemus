"""Unit tier: the MCP Steel gate.

The tests call the sync/async tool bodies directly. They prove the sanitizer
runs before the downstream executor, that an invalid command never reaches the
executor, and that a completed browser error is classified with a recovery
directive.
"""
from __future__ import annotations

import asyncio
import json

import kali.mcp_server as m
from kali.process_group import ProcessOutcome


def _result(stdout: str = "", stderr: str = "", returncode: int = 0) -> dict:
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "duration_ms": 1,
    }


def test_steel_exec_rejects_unknown_session_without_running(monkeypatch):
    calls = []

    monkeypatch.setattr(m, "_steel_version_ok", lambda: True)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})
    monkeypatch.setattr(m, "_run", lambda *args, **kwargs: calls.append(args) or {})

    out = m._steel_exec_sync(
        command='steel browser eval "document.body.innerText" --session wj-typo --json',
        session_id="gate",
        timeout_s=60,
    )

    assert out["error"]["code"] == "unknown_session"
    assert out["error"]["recovery"]["action"] == "use_live"
    assert calls == []


def test_steel_exec_allows_live_session_and_classifies_target_lost(monkeypatch):
    monkeypatch.setattr(m, "_steel_version_ok", lambda: True)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})
    monkeypatch.setattr(
        m,
        "_run",
        lambda *args, **kwargs: _result(
            stdout='{"error":"CDP error (Runtime.evaluate): Session with given id not found.","success":false}',
            returncode=1,
        ),
    )

    out = m._steel_exec_sync(
        command='steel browser eval "document.body.innerText" --session wj-live --json',
        session_id="gate",
        timeout_s=60,
    )

    assert out["error"]["code"] == "target_lost"
    assert out["error"]["recovery"]["action"] == "tab_new"
    assert out["error"]["recovery"]["fallback"] == "recreate_session"


def test_steel_exec_preserves_cli_error_for_cookies_list(monkeypatch):
    monkeypatch.setattr(m, "_steel_version_ok", lambda: True)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})
    monkeypatch.setattr(
        m,
        "_run",
        lambda *args, **kwargs: _result(
            stderr="error: unrecognized subcommand 'list'\n", returncode=2),
    )

    command = "steel browser cookies list --session wj-live --json"
    out = m._steel_exec_sync(command=command, session_id="gate", timeout_s=60)

    assert out["error"]["code"] == "invalid_command"
    assert "unrecognized subcommand" in out["stderr"]
    assert "cookies list" in command


class _Service:
    def __init__(self, result: dict | None = None):
        self.calls = 0
        self.result = result or _result()

    def execute(self, command, session_id, timeout_s, **kwargs):
        self.calls += 1
        out = dict(self.result)
        out.update({"exec_id": "exec-1", "http_artifact_refs": [],
                    "capture_warning": None})
        return out


def test_execute_command_rejects_embedded_unknown_session_without_running(monkeypatch):
    service = _Service()
    get_service_calls = []

    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})
    monkeypatch.setattr(m, "_get_service", lambda: get_service_calls.append(1) or service)

    out = asyncio.run(m.execute_command(
        'steel browser eval "document.body.innerText" --session wj-typo --json',
        "pod",
    ))

    assert out["error"]["code"] == "unknown_session"
    assert service.calls == 0
    assert get_service_calls == []


def test_execute_command_passes_non_steel_shell(monkeypatch):
    service = _Service(_result(stdout="hello\n"))
    monkeypatch.setattr(m, "_get_service", lambda: service)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})

    out = asyncio.run(m.execute_command("echo hello", "pod"))

    assert service.calls == 1
    assert out["stdout"] == "hello\n"
    assert "error" not in out


def test_execute_command_classifies_target_lost(monkeypatch):
    service = _Service(_result(
        stdout='{"error":"CDP error (Runtime.evaluate): Session with given id not found.","success":false}',
        returncode=1,
    ))
    monkeypatch.setattr(m, "_get_service", lambda: service)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})

    out = asyncio.run(m.execute_command(
        'steel browser eval "document.body.innerText" --session wj-live --json',
        "pod",
    ))

    assert service.calls == 1
    assert out["error"]["code"] == "target_lost"
    assert out["error"]["recovery"]["action"] == "tab_new"


def test_execute_command_rejects_mixed_sessions_before_running(monkeypatch):
    service = _Service()
    monkeypatch.setattr(m, "_get_service", lambda: service)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live", "wj-other"})

    out = asyncio.run(m.execute_command(
        "steel browser snapshot --session wj-live --json; "
        "steel browser snapshot --session wj-other --json",
        "pod",
    ))

    assert out["error"]["code"] == "ambiguous_session"
    assert service.calls == 0


def test_steel_exec_returns_session_missing_for_a_known_gone_session(monkeypatch):
    monkeypatch.setattr(m, "_steel_version_ok", lambda: True)
    monkeypatch.setattr(m, "_live_session_names", lambda: set())
    monkeypatch.setattr(m, "known_session_names", lambda: {"wj-gone"})
    calls = []
    monkeypatch.setattr(m, "_run", lambda *args, **kwargs: calls.append(args) or {})

    out = m._steel_exec_sync(
        command='steel browser eval "1" --session wj-gone --json',
        session_id="gate", timeout_s=30)

    assert out["error"]["code"] == "session_missing"
    assert out["error"]["fatal"] is True
    assert out["error"]["recovery"]["action"] == "recreate_session"
    assert calls == []


def test_execute_command_returns_session_missing_for_a_known_gone_session(
        monkeypatch):
    service = _Service()
    monkeypatch.setattr(m, "_get_service", lambda: service)
    monkeypatch.setattr(m, "_live_session_names", lambda: set())
    monkeypatch.setattr(m, "known_session_names", lambda: {"wj-gone"})

    out = asyncio.run(m.execute_command(
        'steel browser eval "1" --session wj-gone --json', "pod"))

    assert out["error"]["code"] == "session_missing"
    assert out["error"]["recovery"]["action"] == "recreate_session"
    assert service.calls == 0


def test_apply_steel_events_prefers_the_first_guard_error():
    result = _result(stdout="echo output\n")
    events = [
        {"verb": "get", "session": "wj-live", "decision": "allow",
         "returncode": 0, "error": None},
        {"verb": "eval", "session": "wj-live", "decision": "allow",
         "returncode": 1,
         "error": {"code": "target_lost", "message": "target gone",
                   "recovery": {"action": "tab_new"}}},
    ]

    out = m._apply_steel_events(result, events)

    assert out["error"]["code"] == "target_lost"
    assert out["returncode"] == 2
    assert out["stdout"] == "echo output\n"
    assert len(out["steel_events"]) == 2


def test_run_merges_a_guard_denial_even_when_the_shell_returns_zero(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KALI_WORKDIR", str(tmp_path))
    events = [
        {"verb": "eval", "session": "wj-typo", "decision": "deny",
         "returncode": 2,
         "error": {"code": "unknown_session", "message": "not live",
                   "recovery": {"action": "use_live"}}},
    ]

    def fake_run(command, **kwargs):
        with open(kwargs["env"]["KALI_STEEL_TRACE"], "a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")
        return ProcessOutcome(
            stdout="echo survived\n", stderr="", returncode=0, duration_ms=1
        )

    monkeypatch.setattr(m, "run_in_process_group", fake_run)

    out = m._run("echo survived; bash -c 'steel browser eval 1 --session wj-typo --json'",
                 "gate", 30)

    assert out["stdout"] == "echo survived\n"
    assert out["returncode"] == 2
    assert out["error"]["code"] == "unknown_session"
    assert out["error"]["recovery"]["action"] == "use_live"


def test_run_gives_the_guard_a_one_second_reporting_grace(tmp_path, monkeypatch):
    guard = tmp_path / "steel_guard.py"
    guard.write_text("#!/bin/sh\n", encoding="utf-8")
    guard.chmod(guard.stat().st_mode | 0o100)
    monkeypatch.setenv("KALI_STEEL_GUARD", str(guard))
    monkeypatch.setenv("KALI_WORKDIR", str(tmp_path))
    seen = {}

    def fake_run(command, **kwargs):
        seen["timeout_s"] = kwargs["timeout_s"]
        return ProcessOutcome(stdout="ok\n", stderr="", returncode=0, duration_ms=1)

    monkeypatch.setattr(m, "run_in_process_group", fake_run)

    m._run("steel browser sessions --json", "gate", 30)

    assert seen["timeout_s"] == 31


def test_run_keeps_the_exact_timeout_for_a_non_steel_command(tmp_path, monkeypatch):
    guard = tmp_path / "steel_guard.py"
    guard.write_text("#!/bin/sh\n", encoding="utf-8")
    guard.chmod(guard.stat().st_mode | 0o100)
    monkeypatch.setenv("KALI_STEEL_GUARD", str(guard))
    monkeypatch.setenv("KALI_WORKDIR", str(tmp_path))
    seen = {}

    def fake_run(command, **kwargs):
        seen["timeout_s"] = kwargs["timeout_s"]
        return ProcessOutcome(stdout="ok\n", stderr="", returncode=0, duration_ms=1)

    monkeypatch.setattr(m, "run_in_process_group", fake_run)

    m._run("echo ok", "gate", 30)

    assert seen["timeout_s"] == 30


def test_run_without_events_keeps_the_legacy_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("KALI_WORKDIR", str(tmp_path))
    monkeypatch.setattr(
        m,
        "run_in_process_group",
        lambda *args, **kwargs: ProcessOutcome(
            stdout="ok\n", stderr="", returncode=0, duration_ms=1
        ),
    )

    out = m._run("echo ok", "gate", 30)

    assert out == {"stdout": "ok\n", "stderr": "", "returncode": 0,
                   "duration_ms": out["duration_ms"]}
    assert "steel_events" not in out


def test_execute_command_merges_the_service_guard_events(monkeypatch):
    service = _Service(_result(stdout="echo survived\n"))
    service.result["steel_events"] = [
        {"verb": "eval", "session": "wj-typo", "decision": "deny",
         "returncode": 2,
         "error": {"code": "unknown_session", "message": "not live",
                   "recovery": {"action": "use_live"}}},
    ]
    monkeypatch.setattr(m, "_get_service", lambda: service)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})

    out = asyncio.run(m.execute_command(
        "echo pre; bash -c 'steel browser eval 1 --session wj-typo --json'",
        "pod",
    ))

    assert service.calls == 1
    assert out["error"]["code"] == "unknown_session"
    assert out["returncode"] == 2


def test_steel_exec_preserves_a_guard_error_without_reclassifying(monkeypatch):
    monkeypatch.setattr(m, "_steel_version_ok", lambda: True)
    monkeypatch.setattr(m, "_live_session_names", lambda: {"wj-live"})
    guard_error = {"code": "target_lost", "message": "target gone",
                   "retryable": False, "fatal": False,
                   "recovery": {"action": "tab_new"}}
    monkeypatch.setattr(
        m, "_run",
        lambda *args, **kwargs: _result(stdout="") | {
            "error": guard_error,
            "steel_events": [{"verb": "eval", "decision": "allow",
                              "error": guard_error}],
        },
    )

    out = m._steel_exec_sync(
        command='steel browser eval "1" --session wj-live --json',
        session_id="gate", timeout_s=30)

    assert out["error"]["code"] == "target_lost"
    assert out["error"]["recovery"]["action"] == "tab_new"
