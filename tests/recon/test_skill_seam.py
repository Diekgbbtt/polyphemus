"""#234 unit tier - the shared agent skill seam.

The seam helper is the one place agent owners collect the skill tools: the
read-only `load_skill` for every agent, plus `write_skill` only when a
writable skill set is configured - so non-auth agents keep the read-only
surface and the write blast radius stays explicit.
"""
from __future__ import annotations

from polymerhus.recon.domain import skills


def test_read_only_agent_gets_load_skill_alone() -> None:
    tools = skills.build_skill_tools()

    assert [t.name for t in tools] == ["load_skill"]


def test_configured_agent_gets_load_skill_plus_bound_write_skill(tmp_path) -> None:
    store = skills.SkillStore(root_dir=tmp_path)

    tools = skills.build_skill_tools(
        "proj-1", writable_skills=("auth_workflow",), store=store
    )

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
    out = write_tool.invoke(
        {"skill": "other", "target": "references/r", "content": "# R\n"}
    )
    assert out == {
        "ok": False,
        "error": "skill_read_only",
        "detail": (
            "skill_read_only: 'other' is outside your writable set; "
            "a live run never mutates the shared skills/ catalogue"
        ),
    }


def test_empty_writable_set_stays_read_only() -> None:
    assert [t.name for t in skills.build_skill_tools("proj-1", ())] == ["load_skill"]


def test_writable_set_without_project_is_a_wiring_defect() -> None:
    import pytest

    with pytest.raises(ValueError):
        skills.build_skill_tools(writable_skills=("auth_workflow",))
