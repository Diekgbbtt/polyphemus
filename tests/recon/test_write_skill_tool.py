"""#234 unit tier - the `write_skill` agent tool.

Real tool invocations against a temp-rooted store (the #220 auth-store tool
precedent). Tests assert the coded envelopes and the on-disk result, never
tool internals.
"""
from __future__ import annotations

from pathlib import Path

from polymerhus.recon.domain import skills
from polymerhus.recon.domain.skills import SkillStore


def _bind(tmp_path: Path):
    return skills.build_write_skill_tool("proj-1", store=SkillStore(root_dir=tmp_path))


def _procedure(name: str = "auth_workflow", body: str = "# Procedure\nstep one\n") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "description: The project's authentication procedure.\n"
        "version: '1'\n"
        "inputs: []\n"
        "---\n\n"
        f"{body}"
    )


def test_write_procedure_first_use_creates_bundle_and_returns_ok(
    tmp_path: Path,
) -> None:
    tool = _bind(tmp_path)

    out = tool.invoke(
        {"skill": "auth_workflow", "target": "procedure", "content": _procedure()}
    )

    assert out["ok"] is True
    assert out["skill"] == "auth_workflow"
    assert out["target"] == "procedure"
    bundle = tmp_path / "proj-1" / "skills" / "auth_workflow"
    assert (bundle / "SKILL.md").read_text(encoding="utf-8").startswith("---\n")


def test_write_reference_lands_in_the_bundle(tmp_path: Path) -> None:
    tool = _bind(tmp_path)
    tool.invoke(
        {"skill": "auth_workflow", "target": "procedure", "content": _procedure()}
    )

    out = tool.invoke(
        {
            "skill": "auth_workflow",
            "target": "references/roles",
            "content": "# Roles\nadmin\n",
        }
    )

    assert out["ok"] is True
    ref = tmp_path / "proj-1" / "skills" / "auth_workflow" / "references" / "roles.md"
    assert ref.read_text(encoding="utf-8") == "# Roles\nadmin\n"


def test_any_project_skill_is_writable(tmp_path: Path) -> None:
    tool = _bind(tmp_path)

    out = tool.invoke(
        {
            "skill": "another-skill",
            "target": "procedure",
            "content": _procedure("another-skill"),
        }
    )

    assert out["ok"] is True
    assert (
        tmp_path / "proj-1" / "skills" / "another-skill" / "SKILL.md"
    ).is_file()


def test_write_malformed_content_refuses_in_band_without_persisting(
    tmp_path: Path,
) -> None:
    tool = _bind(tmp_path)

    out = tool.invoke(
        {"skill": "auth_workflow", "target": "procedure",
         "content": "no frontmatter\n"}
    )

    assert out["ok"] is False
    assert out["error"] == "skill_invalid"
    assert not (tmp_path / "proj-1" / "skills" / "auth_workflow" / "SKILL.md").exists()


def test_write_unsupported_target_refuses_in_band(tmp_path: Path) -> None:
    tool = _bind(tmp_path)

    out = tool.invoke(
        {"skill": "auth_workflow", "target": "scripts/run", "content": "# x\n"}
    )

    assert out["ok"] is False
    assert out["error"] == "skill_target"


def test_source_note_ids_are_accepted_as_log_only_provenance(tmp_path: Path) -> None:
    tool = _bind(tmp_path)

    out = tool.invoke(
        {
            "skill": "auth_workflow",
            "target": "procedure",
            "content": _procedure(),
            "source_note_ids": ["note-1", "note-2"],
        }
    )

    assert out["ok"] is True


def test_a_collapsed_store_degrades_to_store_unavailable_never_a_raise() -> None:
    class CollapsedStore:
        def write(self, *args, **kwargs):
            raise RuntimeError("disk gone")

    tool = skills.build_write_skill_tool("proj-1", store=CollapsedStore())

    out = tool.invoke(
        {"skill": "auth_workflow", "target": "procedure", "content": _procedure()}
    )

    assert out["ok"] is False
    assert out["error"] == "store_unavailable"


def test_write_skill_description_carries_contract_verbatim() -> None:
    assert (
        skills.WRITE_SKILL_CONTRACT
        in skills.build_write_skill_tool("p").description
    )
