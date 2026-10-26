"""Unit tier: the MCP Steel gate.

The tests call the sync/async tool bodies directly. They prove the sanitizer
runs before the downstream executor, that an invalid command never reaches the
executor, and that a completed browser error is classified with a recovery
directive.
"""
from __future__ import annotations

import asyncio

import kali.mcp_server as m


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
