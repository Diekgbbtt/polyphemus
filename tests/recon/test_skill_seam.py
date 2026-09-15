"""#234 unit tier - the shared agent skill seam.

The seam helper is the one place agent owners collect the skill tools: the
read-only `load_skill` for every agent, plus the project-bound `write_skill`
only for agents whose procedure evolves a skill - so agents that execute no
evolving procedure keep the read-only surface and the write blast radius
stays explicit.
"""
from __future__ import annotations

import pytest

from polymerhus.recon.domain import skills


def test_read_only_agent_gets_load_skill_alone() -> None:
    tools = skills.build_skill_tools()

    assert [t.name for t in tools] == ["load_skill"]


def test_write_capable_agent_gets_load_skill_plus_bound_write_skill(tmp_path) -> None:
    store = skills.SkillStore(root_dir=tmp_path)

    tools = skills.build_skill_tools("proj-1", with_write_skill=True, store=store)

    assert [t.name for t in tools] == ["load_skill", "write_skill"]
    write_tool = tools[1]
    out = write_tool.invoke(
        {
            "skill": "auth_workflow",
            "target": "references/r",
            "content": "# R\n",
        }
    )
    assert out["ok"] is True
    assert (
        tmp_path / "proj-1" / "skills" / "auth_workflow" / "references" / "r.md"
    ).is_file()


def test_write_tool_without_project_is_a_wiring_defect() -> None:
    with pytest.raises(ValueError):
        skills.build_skill_tools(with_write_skill=True)
