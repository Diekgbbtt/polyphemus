"""The T10b retired-vocabulary guard (T10b #397).

The final sweep must leave no LIVE obsolete verbatim. This guard pins the
places where a stale name would silently re-enter a live path:

- the assessor and diagnoser prompts (a fresh subagent reads them as contract);
- the e2e fixture specs and the in-container driver (the reduced D4);
- the eval orchestrator modules (the threat and spec-set vocabulary).

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


def test_the_assessment_prompt_uses_the_threat_and_spec_set_vocabulary() -> None:
    text = (EVAL / "prompts" / "assessment.md").read_text(encoding="utf-8")
    for term in RETIRED_IN_PROMPTS:
        assert term not in text, term
    assert "threat_modeller" in text
    assert "web_vulnerability_class" in text
    assert "threat:" in text


def test_the_diagnoser_prompt_uses_the_threat_and_spec_set_vocabulary() -> None:
    text = (EVAL / "prompts" / "diagnoser.md").read_text(encoding="utf-8")
    for term in RETIRED_IN_PROMPTS:
        assert term not in text, term
    assert "threat_modeller" in text
    assert "threat" in text


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


# --- the live docs/setups sweep (T10b review AC5) -----------------------------

def test_the_eval_setups_carry_no_live_hunting_cap_claim() -> None:
    setups = sorted((EVAL / "setups").glob("*.yaml"))
    assert setups
    for path in setups:
        for line in path.read_text(encoding="utf-8").splitlines():
            lowered = line.lower()
            if "hunting cap" in lowered:
                assert "removed" in lowered or "no hunting cap" in lowered, (
                    f"{path.name}: stale hunting-cap claim: {line.strip()}"
                )
            assert "consumed hunt config" not in lowered, path.name
            assert "consumed hunt-config" not in lowered, path.name
            assert "consumed config" not in lowered, path.name


def test_the_operator_doc_carries_no_live_retired_vocabulary() -> None:
    text = (EVAL / "OPERATOR.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        lowered = line.lower()
        if "hunting cap" in lowered:
            assert "removed" in lowered or "legacy" in lowered, line.strip()
        assert "hunt store" not in lowered, line.strip()
        assert "fault class" not in lowered, line.strip()
        assert "consumed hunt config" not in lowered, line.strip()


def test_the_hunts_store_glossary_entry_names_the_live_stores() -> None:
    text = (REPO_ROOT / "src" / "polymerhus" / "attack" / "hunting" / "CONTEXT.md").read_text(
        encoding="utf-8"
    )
    start = text.index("- **hunts_store tool**")
    end = text.index("\n- **notes tool**", start)
    entry = text[start:end]
    assert "ThreatModelStore" in entry
    assert "HunterMemoryStore" in entry
    assert "config store tool" not in entry
    assert "fault_class" not in entry
    assert "produced/consumed config files" not in entry


def test_the_pod_e1_walkthrough_uses_the_reduced_d4() -> None:
    text = (
        REPO_ROOT / "docs" / "design" / "hunting-67-test-executor-pod-spec.md"
    ).read_text(encoding="utf-8")
    start = text.index("E1 - One trivial real run")
    end = text.index("\nE2 - Full chain", start)
    section = text[start:end]
    for term in ("testing_pattern", "payload_vector_space", "interpretation_guidance"):
        assert term not in section, term
    assert "target_identity" in section
    assert "verification_symptoms" in section


def test_the_observability_recipe_names_live_hunting_tracing() -> None:
    text = (REPO_ROOT / "docs" / "design" / "observability-recipe.md").read_text(
        encoding="utf-8"
    )
    for line in text.splitlines():
        lowered = line.lower()
        if "retired" in lowered or "historical" in lowered or "dead" in lowered:
            continue
        for dead in (
            "hunt_orchestrator.py",
            "orchestrator_tracing.py",
            "orchestrator_gate_span",
            "trace_gate_step",
        ):
            assert dead not in line, line.strip()
    assert "hunting_tracing.py" in text


def test_the_eval_spec_family_helper_uses_the_dispatch_id() -> None:
    import re

    text = (EVAL / "orchestrator" / "files.py").read_text(encoding="utf-8")
    assert re.search(r"\bfault_key\b", text) is None
    assert "hunter_test_specs_family_dir" in text
    assert "dispatch_id" in text


def test_the_eval_engine_carries_no_live_hunting_cap_claim() -> None:
    for path in sorted(EVAL.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            lowered = line.lower()
            if "hunting cap" not in lowered:
                continue
            assert (
                "removed" in lowered or "legacy" in lowered
            ), f"{path.name}: {line.strip()}"


def test_the_eval_engine_has_no_fault_key_parameter() -> None:
    # The hunter store key is the threat dispatch id; the retired `fault_key`
    # folder is never a live eval path.
    offenders = []
    for path in sorted(EVAL.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "fault_key" in line and "fault_keyword" not in line:
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, offenders


# --- the live eval/hunting store sweep (T10b review residual) -----------------

# A line that NAMES a retired thing and classifies it is a historical record,
# not a live claim. The allowlist is explicit: a new line without one of these
# markers fails the guard.
_HISTORICAL_MARKERS = (
    "retir",
    "historical",
    "deleted",
    "legacy",
    "removed",
    "no runtime",
    "no hunt-store",
    "not read",
    "disposed",
    "no live claim",
)


def _assert_no_live_phrase(relative: str, phrase: str) -> None:
    path = REPO_ROOT / relative
    text = path.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in text.splitlines()
        if phrase in line.lower()
        and not any(marker in line.lower() for marker in _HISTORICAL_MARKERS)
    ]
    assert not offenders, f"{relative}: live {phrase!r}: {offenders}"


def test_the_live_eval_paths_name_the_threat_model_store() -> None:
    for relative in (
        "eval/CONTEXT.md",
        "eval/orchestrator/instances.py",
        "eval/OPERATOR.md",
    ):
        _assert_no_live_phrase(relative, "hunt store")
        _assert_no_live_phrase(relative, "hunt_store.py")


def test_the_live_hunting_paths_name_the_live_stores() -> None:
    for relative in (
        "src/polymerhus/attack/hunting/CONTEXT.md",
        "src/polymerhus/attack/hunting/prompts/hunting-agent.md",
        "src/polymerhus/attack/hunting/pod/pod_memory.py",
    ):
        _assert_no_live_phrase(relative, "hunt store")
        _assert_no_live_phrase(relative, "hunt stores")

    prompt = (
        REPO_ROOT / "src/polymerhus/attack/hunting/prompts/hunting-agent.md"
    ).read_text(encoding="utf-8")
    assert "previous hunt stores" not in prompt
    assert "previous spec sets" in prompt


def test_the_operator_doc_points_at_the_live_project_lock() -> None:
    text = (EVAL / "OPERATOR.md").read_text(encoding="utf-8")
    assert "polymerhus.app.memory.store.project_lock" in text
    _assert_no_live_phrase("eval/OPERATOR.md", "hunt_store.py")
