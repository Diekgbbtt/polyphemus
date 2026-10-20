"""The steel-browser skill is one runtime-agnostic surface (#395, D20).

Seam under test: `skills/steel-browser/SKILL.md`. Drift guard only - the
behaviour is pinned by the provider, wrapper, and gateway tests.
"""
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "steel-browser" / "SKILL.md"


def test_skill_has_no_runtime_branch_and_no_profile_language():
    text = SKILL.read_text(encoding="utf-8")
    assert "selected below this skill" in text
    assert "steel profile" not in text.lower()
    assert "--profile" not in text
    assert "--local" not in text
    assert "cloud-only" not in text.lower()


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
