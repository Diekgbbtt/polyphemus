"""#234 unit tier - the `write_skill` agent tool.

Real tool invocations against a temp-rooted store (the #220 auth-store tool
precedent). Tests assert the coded envelopes and the on-disk result, never
tool internals.

Metadata ownership (D234-15): a `procedure` write carries the body alone; the
store composes the frontmatter from the operator-bootstrapped metadata and
bumps `metadata.version` one minor per write.
"""
from __future__ import annotations

from pathlib import Path

from polymerhus.app.llm import skills
from polymerhus.app.llm.skills import SkillStore

BODY = "# Procedure\nstep one\n"


def _catalogue(tmp_path: Path) -> Path:
    catalogue = tmp_path / "catalogue"
    for skill, description in (
        ("auth_workflow", "The project's authentication procedure."),
        ("another-skill", "Another project skill."),
    ):
        bundle = catalogue / skill
        bundle.mkdir(parents=True)
        (bundle / "SKILL.md").write_text(
            "---\n"
            f"name: {skill}\n"
            f"description: {description}\n"
            "metadata:\n"
            "  version: '1.0'\n"
            "---\n\n# Seed\n",
            encoding="utf-8",
        )
    return catalogue


def _bind(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    return skills.build_write_skill_tool(
        "proj-1", store=SkillStore(root_dir=tmp_path / "data")
    )


def test_write_procedure_first_use_creates_bundle_and_returns_ok(
    tmp_path: Path, monkeypatch
) -> None:
    tool = _bind(tmp_path, monkeypatch)

    out = tool.invoke(
        {"skill": "auth_workflow", "target": "procedure", "content": BODY}
    )

    assert out["ok"] is True
    assert out["skill"] == "auth_workflow"
    assert out["target"] == "procedure"
    sk = tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    assert sk.read_text(encoding="utf-8").startswith("---\n")


def test_write_reference_lands_in_the_bundle(tmp_path: Path, monkeypatch) -> None:
    tool = _bind(tmp_path, monkeypatch)
    tool.invoke(
        {"skill": "auth_workflow", "target": "procedure", "content": BODY}
    )

    out = tool.invoke(
        {
            "skill": "auth_workflow",
            "target": "references/roles",
            "content": "# Roles\nadmin\n",
        }
    )

    assert out["ok"] is True
    ref = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow"
        / "references" / "roles.md"
    )
    assert ref.read_text(encoding="utf-8") == "# Roles\nadmin\n"


def test_any_project_skill_is_writable(tmp_path: Path, monkeypatch) -> None:
    tool = _bind(tmp_path, monkeypatch)

    out = tool.invoke(
        {"skill": "another-skill", "target": "procedure", "content": "# body\n"}
    )

    assert out["ok"] is True
    assert (
        tmp_path / "data" / "proj-1" / "skills" / "another-skill" / "SKILL.md"
    ).is_file()


def test_write_without_bootstrapped_metadata_refuses_in_band(
    tmp_path: Path, monkeypatch
) -> None:
    tool = _bind(tmp_path, monkeypatch)

    out = tool.invoke(
        {"skill": "unbootstrapped", "target": "procedure", "content": "# body\n"}
    )

    assert out["ok"] is False
    assert out["error"] == "skill_invalid"
    assert not (
        tmp_path / "data" / "proj-1" / "skills" / "unbootstrapped" / "SKILL.md"
    ).exists()


def test_write_unsupported_target_refuses_in_band(tmp_path: Path, monkeypatch) -> None:
    tool = _bind(tmp_path, monkeypatch)

    out = tool.invoke(
        {"skill": "auth_workflow", "target": "scripts/run", "content": "# x\n"}
    )

    assert out["ok"] is False
    assert out["error"] == "skill_target"


def test_write_unsafe_skill_name_refuses_in_band(tmp_path: Path, monkeypatch) -> None:
    tool = _bind(tmp_path, monkeypatch)

    out = tool.invoke(
        {"skill": "../escape", "target": "references/r", "content": "# x\n"}
    )

    assert out["ok"] is False
    assert out["error"] == "skill_invalid"


def test_source_note_ids_are_accepted_as_log_only_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    tool = _bind(tmp_path, monkeypatch)

    out = tool.invoke(
        {
            "skill": "auth_workflow",
            "target": "procedure",
            "content": BODY,
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
        {"skill": "auth_workflow", "target": "procedure", "content": BODY}
    )

    assert out["ok"] is False
    assert out["error"] == "store_unavailable"


def test_write_skill_description_carries_contract_verbatim() -> None:
    assert (
        skills.WRITE_SKILL_CONTRACT
        in skills.build_write_skill_tool("p").description
    )


def test_source_note_ids_rides_the_surface_with_zero_prose() -> None:
    assert "source_note_ids" not in skills.WRITE_SKILL_CONTRACT

    schema = skills.build_write_skill_tool("p").args_schema.model_json_schema()
    assert "source_note_ids" in schema["properties"]
    assert "description" not in schema["properties"]["source_note_ids"]

    for name in ("meta/meta-write-skill", "meta/meta-usage-skill"):
        assert "source_note" not in skills.skill_for(name)
