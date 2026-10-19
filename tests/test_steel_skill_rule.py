"""The steel-browser skill states the local-runtime rule (#390, D359-4).

Seam under test: `skills/steel-browser/SKILL.md`. Drift guard only - the
behaviour is pinned by `tests/test_steel_exec.py` and the resolver tests.
"""
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "steel-browser" / "SKILL.md"


def test_skill_names_the_endpoint_value_and_the_local_flag():
    text = SKILL.read_text(encoding="utf-8")
    assert "STEEL_BROWSER_API_URL" in text
    # The gateway injects `--local` in command mode.
    assert "--local" in text
    # Scripts are never rewritten, so the skill must say they pass it themselves.
    assert "Script text is never rewritten" in text or "script must pass `--local` itself" in text


def test_skill_marks_profiles_cloud_only_on_the_local_runtime():
    # #395: the local API strips profileId/persistProfile, so a local
    # --profile mount is a no-op. The skill must say so and name the local
    # state path (sessionContext) instead.
    text = SKILL.read_text(encoding="utf-8")
    assert "Profiles are cloud-only" in text
    assert "sessionContext" in text
    assert "t395-local-capability-profile-gap.md" in text
