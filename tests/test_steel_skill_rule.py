"""The steel-browser skill is one runtime-agnostic surface (#395, D20).

Seam under test: `skills/steel-browser/SKILL.md`. Drift guard only - the
behaviour is pinned by the provider, wrapper, and gateway tests.
"""
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "steel-browser" / "SKILL.md"

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
