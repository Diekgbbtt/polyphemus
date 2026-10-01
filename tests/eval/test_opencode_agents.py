"""The eval harness's opencode role agents (#297).

The subagent commands (OPERATOR.md 2.9/2.10/2.12/2.13) run
`opencode run --agent <role>`, so every role the harness dispatches must ship as
an agent under `.opencode/agent/` and name its contract prompt under
`eval/prompts/`. These tests pin that wiring so a renamed prompt or a dropped
agent fails here rather than silently at dispatch time.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / ".opencode" / "agent"

# role agent id -> the contract prompt it must reference.
ROLES = {
    "eval-assessor": "eval/prompts/assessment.md",
    "eval-diagnoser": "eval/prompts/diagnoser.md",
    "eval-aligner": "eval/prompts/alignment.md",
    "eval-surfer": "eval/prompts/surfer.md",
}


@pytest.mark.parametrize("role,prompt", sorted(ROLES.items()))
def test_role_agent_names_its_contract_prompt(role: str, prompt: str) -> None:
    text = (AGENT_DIR / f"{role}.md").read_text(encoding="utf-8")

    assert prompt in text
    assert "mode: all" in text
    assert "model: opencode-go/deepseek-v4.1-flash" in text


def test_every_role_agent_exists() -> None:
    for role in ROLES:
        assert (AGENT_DIR / f"{role}.md").is_file(), role


def test_orchestrator_agent_still_ships() -> None:
    assert (AGENT_DIR / "eval-orchestrator.md").is_file()
