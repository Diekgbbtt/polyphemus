"""Unit tier: the Steel browser contract sanitizer.

The sanitizer covers the contextual and state gaps the bare Steel CLI leaves
open. It does not replicate the CLI grammar and does not rewrite clear CLI
errors. Every refusal or classified failure returns an additive error envelope
with a recovery directive.
"""
from __future__ import annotations

from kali.steel_contract import (
    BrowserCommand,
    ContractError,
    classify_result,
    sanitize_shell_command,
    sanitize_steel_command,
)

LIVE = {"wj-live"}


def _result(stdout: str = "", stderr: str = "", returncode: int = 0) -> dict:
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "duration_ms": 1,
    }


def test_missing_session_is_rejected_before_execution():
    out = sanitize_steel_command(
        'steel browser navigate http://target/ --json', live_sessions=LIVE)
    assert isinstance(out, ContractError)
    assert out.code == "missing_session"
    assert out.retryable is True
    assert out.recovery and out.recovery["action"] == "fix_command"


def test_unknown_session_is_rejected_without_creating_a_session():
    out = sanitize_steel_command(
        'steel browser eval "document.body.innerText" --session wj-typo --json',
        live_sessions=LIVE)
    assert isinstance(out, ContractError)
    assert out.code == "unknown_session"
    assert out.fatal is False
    assert out.session == "wj-typo"
    assert out.recovery and out.recovery["action"] in {"start_session", "use_live"}


def test_live_session_is_allowed_for_navigate():
    out = sanitize_steel_command(
        'steel browser navigate http://target/ --session wj-live --json',
        live_sessions=LIVE)
    assert isinstance(out, BrowserCommand)
    assert out.verb == "navigate"
    assert out.session == "wj-live"


def test_start_on_live_session_is_refused():
    out = sanitize_steel_command(
        "steel browser start --session wj-live --json", live_sessions=LIVE)
    assert isinstance(out, ContractError)
    assert out.code == "session_taken"
    assert out.recovery and out.recovery["action"] == "use_live"


def test_start_on_absent_session_is_allowed():
    out = sanitize_steel_command(
        "steel browser start --session wj-new --json", live_sessions=LIVE)
    assert isinstance(out, BrowserCommand)
    assert out.verb == "start"
    assert out.session == "wj-new"


def test_cookies_list_is_not_rewritten_and_passes_the_cli_error():
    command = "steel browser cookies list --session wj-live --json"
    parsed = sanitize_steel_command(command, live_sessions=LIVE)
    assert isinstance(parsed, BrowserCommand)
    assert "cookies list" in parsed.canonical

    classified = classify_result(
        command,
        _result(stderr="error: unrecognized subcommand 'list'\n", returncode=2),
        session="wj-live",
        live_sessions=LIVE,
    )
    assert classified["error"]["code"] == "invalid_command"
    assert "cookies list" not in classified.get("canonical_command", "") or "cookies list" in command
    assert "unrecognized subcommand" in classified["stderr"]


def test_known_but_gone_session_returns_recreate_session():
    out = sanitize_steel_command(
        'steel browser eval "1" --session wj-gone --json',
        live_sessions=set(),
        known_sessions={"wj-gone"},
    )
    assert isinstance(out, ContractError)
    assert out.code == "session_missing"
    assert out.fatal is True
    assert out.recovery["action"] == "recreate_session"
    assert out.recovery["requires_state_restore"] is True


def test_a_typo_is_still_an_unknown_session():
    out = sanitize_steel_command(
        'steel browser eval "1" --session wj-typo --json',
        live_sessions={"wj-live"},
        known_sessions={"wj-live"},
    )
    assert isinstance(out, ContractError)
    assert out.code == "unknown_session"
    assert out.fatal is False
    assert out.recovery["action"] == "use_live"


def test_target_lost_returns_tab_new_recovery():
    command = 'steel browser eval "document.body.innerText" --session wj-live --json'
    out = classify_result(
        command,
        _result(
            stdout='{"error":"CDP error (Runtime.evaluate): Session with given id not found.","success":false}',
            returncode=1,
        ),
        session="wj-live",
        live_sessions=LIVE,
    )
    assert out["error"]["code"] == "target_lost"
    assert out["error"]["fatal"] is False
    assert out["error"]["recovery"]["action"] == "tab_new"
    assert out["error"]["recovery"]["fallback"] == "recreate_session"


def test_session_missing_returns_recreate_session():
    command = 'steel browser eval "document.body.innerText" --session wj-live --json'
    out = classify_result(
        command,
        _result(stderr="Session not found\n", returncode=1),
        session="wj-live",
        live_sessions=set(),
    )
    assert out["error"]["code"] == "session_missing"
    assert out["error"]["fatal"] is True
    assert out["error"]["recovery"]["action"] == "recreate_session"
    assert out["error"]["recovery"]["requires_state_restore"] is True


def test_browser_stuck_returns_fatal_recreate_session():
    command = "steel browser snapshot --session wj-live --json"
    out = classify_result(
        command,
        _result(stderr="timeout after 30s", returncode=124),
        session="wj-live",
        live_sessions=LIVE,
    )
    assert out["error"]["code"] == "browser_stuck"
    assert out["error"]["fatal"] is True
    assert out["error"]["recovery"]["action"] == "recreate_session"


def test_connection_refused_returns_browser_unavailable():
    command = "steel browser sessions --json"
    out = classify_result(
        command,
        _result(stderr="connect ECONNREFUSED 127.0.0.1:3000", returncode=1),
        session=None,
        live_sessions=LIVE,
    )
    assert out["error"]["code"] == "browser_unavailable"
    assert out["error"]["fatal"] is True
    assert out["error"]["recovery"]["action"] == "recreate_session"


def test_shell_scan_validates_embedded_steel_commands():
    command = (
        'echo start; steel browser navigate http://target/ --session wj-typo --json; '
        'echo done'
    )
    out = sanitize_shell_command(command, live_sessions=LIVE)
    assert isinstance(out, ContractError)
    assert out.code == "unknown_session"
    assert out.session == "wj-typo"


def test_clear_cli_error_behind_zero_exit_is_classified():
    command = (
        "steel browser get text --session wj-live --json | "
        "python3 -c 'print(1)'"
    )
    out = classify_result(
        command,
        _result(
            stderr="error: the following required arguments were not provided: <SELECTOR>\n",
            returncode=0,
        ),
        session="wj-live",
        live_sessions=LIVE,
    )
    assert out["error"]["code"] == "cli_error"
    assert out["error"]["fatal"] is False
    assert out["error"]["retryable"] is True


def test_error_envelope_is_additive():
    err = ContractError(
        code="unknown_session",
        message="unknown session",
        retryable=False,
        fatal=False,
        recovery={"action": "use_live", "reason": "use a live session"},
        session="wj-typo",
    )
    env = err.envelope()
    assert env["returncode"] != 0
    assert env["error"]["code"] == "unknown_session"
    assert env["error"]["recovery"]["action"] == "use_live"
    assert set(env) >= {"stdout", "stderr", "returncode", "duration_ms", "error"}


def test_empty_snapshot_adds_a_tab_new_warning():
    command = "steel browser snapshot --session wj-live --json"
    out = classify_result(
        command,
        _result(stdout='{"data":"(no interactive elements)","success":true}', returncode=0),
        session="wj-live",
        live_sessions=LIVE,
    )
    assert "error" not in out
    assert out["warning"]["code"] == "empty_target"
    assert out["warning"]["recovery"]["action"] == "tab_new"


def test_multi_command_result_does_not_emit_empty_warning():
    command = (
        'echo start; steel browser get url --session wj-live --json; echo end'
    )
    out = classify_result(
        command,
        _result(
            stdout='=== url ===\n{"data":"http://target/","success":true}\n',
            returncode=0,
        ),
        session="wj-live",
        live_sessions=LIVE,
    )
    assert "error" not in out
    assert "warning" not in out


def test_successful_page_text_mentioning_target_error_is_not_classified():
    command = 'steel browser eval "document.body.innerText" --session wj-live --json'
    out = classify_result(
        command,
        _result(
            stdout='{"data":"Session with given id not found is a page phrase","success":true}',
            returncode=0,
        ),
        session="wj-live",
        live_sessions=LIVE,
    )
    assert "error" not in out


def test_non_browser_steel_command_is_allowed():
    out = sanitize_steel_command("steel --version", live_sessions=LIVE)
    assert isinstance(out, BrowserCommand)
    assert out.verb == ""
    assert out.session is None
