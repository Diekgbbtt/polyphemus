"""The project-id-prefixed evidence-path contract (#288).

The assessor and diagnoser role prompts must name evidence paths in the one
shape the code resolves: a path relative to `<instance>/data` whose first
segment is the trial's `<project_id>/`.

`orchestrator/files.py` builds every evidence path as
`<data_root>/<project_id>/hunting/...`, and `orchestrator/store.py::materialize`
resolves a verdict row's chain path as `data_root / relative`, refusing any row
that escapes the data root. A prompt example that omits the segment therefore
sends a fresh subagent to the wrong directory and fails the chain at
materialize time.

This test pins the prompt text to the code's resolved path shape at that seam.
"""
from __future__ import annotations

from pathlib import Path

from orchestrator import assessment, diagnosis, files

PROJECT_ID = "ae3eb805-9a0c-4c14-8d55-05e23d48db46"
DATA_ROOT = Path("/instances/arm-a/data")

# The three concrete evidence families the prompts name, in the mandatory
# `<project_id>/`-prefixed form.
EXAMPLE_PREFIXES = (
    "<project_id>/hunting/orchestration/hunt_configs/",
    "<project_id>/hunting/hunter/test-specs/",
    "<project_id>/hunting/test-executor-pod/",
)


def _prompt_text(prompt: Path) -> str:
    assert prompt.exists(), f"prompt missing: {prompt}"
    return prompt.read_text(encoding="utf-8")


def test_assessment_prompt_states_the_project_prefixed_evidence_contract() -> None:
    text = _prompt_text(assessment.ASSESSMENT_PROMPT)
    for prefix in EXAMPLE_PREFIXES:
        assert prefix in text
    # The schema field states the mandatory first segment where a fresh
    # subagent reads the evidence chain contract.
    assert "begins with the `<project_id>/` segment" in text


def test_diagnoser_prompt_states_the_project_prefixed_evidence_contract() -> None:
    text = _prompt_text(diagnosis.DIAGNOSER_PROMPT)
    for prefix in EXAMPLE_PREFIXES:
        assert prefix in text
    assert "begins with the `<project_id>/` segment" in text


def test_code_resolves_every_evidence_path_under_the_project_segment() -> None:
    assert files.project_dir(DATA_ROOT, PROJECT_ID) == DATA_ROOT / PROJECT_ID
    for side in files.HUNT_CONFIG_SIDES:
        resolved = files.hunt_configs_dir(DATA_ROOT, PROJECT_ID, side)
        assert resolved.relative_to(DATA_ROOT) == (
            Path(PROJECT_ID) / "hunting/orchestration/hunt_configs" / side
        )
    fault = files.hunter_test_specs_fault_dir(
        DATA_ROOT, PROJECT_ID, "ssti", "produced"
    )
    assert fault.relative_to(DATA_ROOT) == (
        Path(PROJECT_ID) / "hunting/hunter/test-specs/ssti/produced"
    )
    assert files.pod_dir(DATA_ROOT, PROJECT_ID).relative_to(DATA_ROOT) == (
        Path(PROJECT_ID) / "hunting/test-executor-pod"
    )
