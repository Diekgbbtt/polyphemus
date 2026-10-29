"""The steel-browser skill is one runtime-agnostic surface (#395, D20).

Seam under test: `skills/internal/tools/steel-browser/SKILL.md`. Drift guard
only - the behaviour is pinned by the provider, wrapper, and gateway tests.
"""
import re
from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[1]
    / "skills" / "internal" / "tools" / "steel-browser" / "SKILL.md"
)

# Runtime and identity words the one skill must never teach. `\b` keeps the
# durable-state field names (`localStorage`, `sessionStorage`) legal.
_FORBIDDEN_SKILL_WORDS = re.compile(
    r"\b(?:cloud|self-hosted|local|deployment|profile|sessioncontext|endpoint)\b",
    re.IGNORECASE,
)


def test_skill_has_no_runtime_branch_and_no_profile_language():
    text = SKILL.read_text(encoding="utf-8")
    assert "selected below this skill" in text
    assert "--profile" not in text
    assert "--local" not in text
    assert "STEEL_API_KEY" not in text
    assert "STEEL_BROWSER_API_URL" not in text
    # `storage local` is a CLI literal, not a deployment word.
    scanned = text.replace("storage local|session", "storage-scope")
    assert _FORBIDDEN_SKILL_WORDS.findall(scanned) == []


def test_skill_teaches_the_gateway_and_the_bare_shell_surface():
    """The hunting and exploit agents bind a plain shell `exec`, not
    `steel_exec`; the one skill must teach both surfaces without a runtime
    branch."""
    text = SKILL.read_text(encoding="utf-8")
    assert "`steel_exec` gateway" in text
    assert "shell `exec`" in text


def test_skill_names_the_four_durable_state_fields_and_the_cli_limit():
    text = SKILL.read_text(encoding="utf-8")
    for field in ("cookies", "localStorage", "sessionStorage", "indexedDB"):
        assert field in text
    assert "CLI `start` has no state field" in text
    assert "reuse a live session" in text


def test_skill_states_the_auth_gate_signals():
    text = SKILL.read_text(encoding="utf-8")
    assert "login redirect" in text
    assert "401" in text and "403" in text
    assert "storage-located" in text
    assert "reduced coverage" in text


def test_skill_pins_the_current_contract_and_references():
    text = SKILL.read_text(encoding="utf-8")
    assert "version: '2.1.0'" in text
    for token in (
        "steel_events", "shell_returncode", "browser batch", "browser find",
        "browser diff", "sessions get", "--inactivity-timeout 300000",
        "has no effect",
    ):
        assert token in text
    assert "--inactivity-timeout 0" not in text
    assert "steel-real" not in text
    references = SKILL.parent / "references"
    for name in (
        "contract.md", "load-eval.py", "select-elements.py", "session-records.py",
    ):
        assert name in text
        assert (references / name).is_file()


def test_contract_reference_pins_the_error_and_record_surface():
    contract = (SKILL.parent / "references" / "contract.md").read_text(
        encoding="utf-8")
    for token in (
        "unknown_session", "session_missing", "recreate_session",
        "requires_state_restore", "session_taken", "target_lost",
        "browser_stuck", "invalid_command", "steel_events", "shell_returncode",
        "not_found", "no video recording", "HTTP history",
    ):
        assert token in contract
    assert "logs" in contract and "agent-logs" in contract and "traces" in contract


def test_lifecycle_scripts_mark_ownership_after_start():
    references = SKILL.parent / "references"
    for name in (
        "eval-inline.sh", "eval-interact.sh", "extract-reads.sh",
        "interact-batch.sh", "navigate-read.sh", "session-lifecycle.sh",
        "spider-bounded.sh",
    ):
        text = (references / name).read_text(encoding="utf-8")
        assert "SESSION_NAMED" not in text
        assert "SESSION_OWNED=1\nSTART_JSON" not in text
        start = text.index("START_JSON=$(steel browser start")
        assert text.index("SESSION_OWNED=1", start) > start
        assert "--inactivity-timeout 300000" in text
        assert "--inactivity-timeout 0" not in text


def test_read_scripts_never_create_sessions():
    references = SKILL.parent / "references"
    for name in ("load-eval.py", "select-elements.py", "session-records.py"):
        text = (references / name).read_text(encoding="utf-8")
        assert "browser start" not in text
        assert "browser stop" not in text
        assert "steel-real" not in text
