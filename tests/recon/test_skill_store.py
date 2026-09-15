"""#234 unit tier - the per-project skill store.

The store is the primary seam: an explicit-root temp store (the #220 auth-store
and hunting notes-store precedent). Tests assert external behaviour only - the
bytes read back, the files on disk, and the coded refusals - never internals.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.recon.domain import skills
from polymerhus.recon.domain.skills import (
    SecretRefusedError,
    SkillInvalidError,
    SkillSizeError,
    SkillStore,
    SkillTargetError,
)


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


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


# --- read: project-first resolution, fail-open ------------------------------


def test_write_procedure_creates_bundle_and_reads_back_stripped(tmp_path: Path) -> None:
    store = SkillStore(root_dir=tmp_path)

    store.write("proj-1", "auth_workflow", "procedure", _procedure())

    bundle = tmp_path / "proj-1" / "skills" / "auth_workflow"
    assert (bundle / "SKILL.md").is_file()
    assert (bundle / "references").is_dir()
    assert (bundle / "scripts").is_dir()
    assert (bundle / "assets").is_dir()
    body = store.read("auth_workflow", project_id="proj-1")
    assert body.startswith("# Procedure")
    assert not body.startswith("---")


def test_project_bundle_shadows_the_shared_catalogue(tmp_path: Path, monkeypatch) -> None:
    catalogue = tmp_path / "catalogue"
    shared = catalogue / "demo"
    shared.mkdir(parents=True)
    (shared / "SKILL.md").write_text("---\nname: demo\n---\n\n# Shared\n", encoding="utf-8")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", catalogue)
    store = SkillStore(root_dir=tmp_path / "data")

    store.write("proj-1", "demo", "procedure", _procedure("demo", "# Project\n"))

    assert store.read("demo", project_id="proj-1") == "# Project\n"


def test_a_project_without_a_bundle_reads_the_shared_skill_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    catalogue = tmp_path / "catalogue"
    shared = catalogue / "demo"
    shared.mkdir(parents=True)
    (shared / "SKILL.md").write_text("---\nname: demo\n---\n\n# Shared\n", encoding="utf-8")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", catalogue)
    store = SkillStore(root_dir=tmp_path / "data")

    assert store.read("demo", project_id="proj-1") == "# Shared\n"


def test_read_missing_skill_degrades_to_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path / "empty")
    store = SkillStore(root_dir=tmp_path / "data")

    assert store.read("nope", project_id="proj-1") == ""
    assert store.read("nope", project_id="proj-1", fallback="FB") == "FB"


# --- write: references target ------------------------------------------------


def test_write_reference_lands_under_references(tmp_path: Path) -> None:
    store = SkillStore(root_dir=tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", _procedure())

    store.write("proj-1", "auth_workflow", "references/roles", "# Roles\nadmin\n")

    ref = tmp_path / "proj-1" / "skills" / "auth_workflow" / "references" / "roles.md"
    assert ref.read_text(encoding="utf-8") == "# Roles\nadmin\n"


# --- write: coded refusals, nothing persisted -------------------------------


def test_write_refuses_malformed_frontmatter_without_persisting(tmp_path: Path) -> None:
    store = SkillStore(root_dir=tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", "no frontmatter at all\n")

    assert not (tmp_path / "proj-1" / "skills" / "auth_workflow" / "SKILL.md").exists()


def test_write_refuses_name_not_matching_the_bundle(tmp_path: Path) -> None:
    store = SkillStore(root_dir=tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", _procedure("something_else"))


def test_write_refuses_secret_shaped_content_without_persisting(tmp_path: Path) -> None:
    store = SkillStore(root_dir=tmp_path)
    secret_body = (
        "# Procedure\npassword: AKIAIOSFODNN7EXAMPLE\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n"
    )

    with pytest.raises(SecretRefusedError):
        store.write("proj-1", "auth_workflow", "procedure", _procedure(body=secret_body))

    assert not (tmp_path / "proj-1" / "skills" / "auth_workflow" / "SKILL.md").exists()


def test_write_refuses_oversized_content_without_persisting(tmp_path: Path) -> None:
    store = SkillStore(root_dir=tmp_path)
    huge = "# Procedure\n" + ("x" * (skills.REFERENCE_MAX_BYTES + 1))

    with pytest.raises(SkillSizeError):
        store.write("proj-1", "auth_workflow", "references/big", huge)

    assert not (
        tmp_path / "proj-1" / "skills" / "auth_workflow" / "references" / "big.md"
    ).exists()


@pytest.mark.parametrize(
    "target",
    ["", "procedure/extra", "references/../escape", "references/", "scripts/run", "/etc/passwd"],
)
def test_write_refuses_an_unsupported_or_unsafe_target(tmp_path: Path, target: str) -> None:
    store = SkillStore(root_dir=tmp_path)
    with pytest.raises(SkillTargetError):
        store.write("proj-1", "auth_workflow", target, "# x\n")


def test_a_failed_write_leaves_prior_content_intact(tmp_path: Path) -> None:
    store = SkillStore(root_dir=tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", _procedure(body="# First\n"))

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", "malformed\n")

    assert store.read("auth_workflow", project_id="proj-1") == "# First\n"
