"""The T10b retired-vocabulary guard (T10b #397).

The final sweep must leave no LIVE obsolete verbatim. This guard pins the
places where a stale name would silently re-enter a live path:

- the assessor and diagnoser prompts (a fresh subagent reads them as contract);
- the e2e fixture specs and the in-container driver (the reduced D4);
- the eval orchestrator modules (the loop and spec-set vocabulary).

Historical design docs and the explicit retirement notes are out of scope
here; a line that NAMES a retired term to refuse it is a guard, not a live
claim.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = REPO_ROOT / "eval"

RETIRED_IN_PROMPTS = (
    "hunt config",
    "hunt_config",
    "fault_class",
    "hunting/orchestration",
    "HuntConfig",
    "DispatchResult",
    "testing_pattern",
    "payload_vector_space",
    "interpretation_guidance",
)

RETIRED_IN_D4 = (
    "testing_pattern:",
    "payload_vector_space:",
    "interpretation_guidance:",
)


def test_the_assessment_prompt_uses_the_loop_and_spec_set_vocabulary() -> None:
    text = (EVAL / "prompts" / "assessment.md").read_text(encoding="utf-8")
    for term in RETIRED_IN_PROMPTS:
        assert term not in text, term
    assert "threat_modeller" in text
    assert "web_vulnerability_class" in text
    assert "loop:" in text


def test_the_diagnoser_prompt_uses_the_loop_and_spec_set_vocabulary() -> None:
    text = (EVAL / "prompts" / "diagnoser.md").read_text(encoding="utf-8")
    for term in RETIRED_IN_PROMPTS:
        assert term not in text, term
    assert "threat_modeller" in text
    assert "loop" in text


def test_the_e2e_fixtures_carry_only_the_reduced_d4() -> None:
    fixtures = sorted((REPO_ROOT / "tests" / "e2e" / "fixtures" / "specs").glob("*.yaml"))
    assert fixtures
    for path in fixtures:
        text = path.read_text(encoding="utf-8")
        for term in RETIRED_IN_D4:
            assert term not in text, f"{path.name}: {term}"
        assert "target_identity:" in text
        assert "verification_symptoms:" in text
        assert "assumptions:" in text
        assert "rationale:" in text


def test_the_e2e_driver_forwards_only_the_reduced_d4() -> None:
    text = (REPO_ROOT / "tests" / "e2e" / "harness" / "driver.py").read_text(
        encoding="utf-8"
    )
    assert '"target_identity"' in text
    assert '"verification_symptoms"' in text
    assert '"assumptions"' in text
    assert '"rationale"' in text
    # The retired fields appear only in the comment that records their removal.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for term in ("testing_pattern", "payload_vector_space", "interpretation_guidance"):
            assert term not in line, line


def test_no_eval_module_imports_the_retired_config_family_path_helper() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in EVAL.rglob("*.py")
        if "import hunt_configs_dir" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


def test_the_eval_setup_has_no_retired_configs_field() -> None:
    from orchestrator import setup

    fields = set(setup.PreloadedArtifacts.__dataclass_fields__)
    assert "models" in fields
    assert "configs" not in fields
