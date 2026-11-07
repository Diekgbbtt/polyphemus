"""The steel-browser skill is one one-tool contract.

Seam under test: the skill text. The behaviour is pinned by the server, CLI,
and lease tests. This file is a drift guard: the skill must teach the one
bound `browser` tool, never a shell lifecycle and never a session-management
verb.
"""
import re
from pathlib import Path

SKILL_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills" / "internal" / "tools" / "steel-browser"
)
SKILL = SKILL_DIR / "SKILL.md"
CONTRACT = SKILL_DIR / "references" / "contract.md"

# Runtime and identity words the one skill must never teach. `\b` keeps the
# durable-state field names (`localStorage`, `sessionStorage`) legal.
_FORBIDDEN_SKILL_WORDS = re.compile(
    r"\b(?:cloud|self-hosted|local|deployment|profile|sessioncontext|endpoint)\b",
    re.IGNORECASE,
)


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_skill_has_no_runtime_branch_and_no_profile_language():
    text = _skill()
    assert 'browser(command="start"' in text
    assert 'browser(command="exec"' in text
    assert "--profile" not in text
    assert "--local" not in text
    assert "STEEL_API_KEY" not in text
    assert "STEEL_BROWSER_API_URL" not in text
    # `storage local|session` is a command literal, not a runtime word.
    scanned = text.replace("storage local|session", "storage-scope")
    assert _FORBIDDEN_SKILL_WORDS.findall(scanned) == []


def test_skill_teaches_only_the_one_bound_tool():
    text = _skill()
    for command in ('browser(command="start"', 'browser(command="exec"', 'browser(command="end"'):
        assert command in text, command
    for absent in (
        "browser_start",
        "browser_exec",
        "browser_end",
        "browser_status",
        "pool_status",
        "release_owner",
        "steel_exec",
        "shell `exec`",
        "sessions get",
        "steel browser",
        "browser start",
        "browser stop",
        "--session",
    ):
        assert absent not in text, absent


def test_skill_keeps_the_browser_command_grammar():
    text = _skill()
    for token in (
        "navigate", "snapshot", "batch", "fill", "wait", "eval", "get text",
        "cookies", "storage local|session", "screenshot", "diff", "find",
        "`--` boundary",
    ):
        assert token in text, token


def test_skill_names_the_durable_state_fields_and_the_restore_limit():
    text = _skill()
    for field in ("cookies", "localStorage", "sessionStorage", "indexedDB"):
        assert field in text
    assert "not restored" in text
    assert "durable" in text


def test_skill_states_the_auth_gate_signals():
    text = _skill()
    assert "login redirect" in text
    assert "401" in text and "403" in text
    assert "3xx" in text
    assert "indeterminate" in text
    assert "auth_probe" in text
    assert "reduced coverage" in text


def test_skill_pins_the_tool_contract_and_reference():
    text = _skill()
    assert "version: '4.0.0'" in text
    assert "references/contract.md" in text
    assert "no status, owner, or session-management tool" in text.lower()
    assert "--inactivity-timeout" not in text
    assert "steel-real" not in text
    assert CONTRACT.is_file()


def test_contract_reference_pins_the_error_and_state_surface():
    contract = CONTRACT.read_text(encoding="utf-8")
    for token in (
        "pool_exhausted",
        "session_in_use",
        "no_session",
        "invalid_command",
        "browser_error",
        "restore_failed",
        "store_error",
        "lease_error",
        "auth_probe",
        "indeterminate",
        "data.results",
        "HTTP history",
        "not restored",
    ):
        assert token in contract, token


def test_skill_never_teaches_a_session_or_stop_owner():
    text = _skill().lower()
    for absent in (
        "stop owner",
        "dead-man",
        "session_taken",
        "session_missing",
        "default session",
    ):
        assert absent not in text, absent
