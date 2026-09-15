"""#234 unit tier - the per-project skill store.

The store is the primary seam: an explicit-root temp store (the #220 auth-store
and hunting notes-store precedent). Tests assert external behaviour only - the
bytes read back, the files on disk, and the coded refusals - never internals.

Metadata ownership (D234-15): a `procedure` write carries the body alone. The
store composes the frontmatter from the operator-bootstrapped metadata - the
project's own on later writes, the shared catalogue's copied over on the first -
and bumps `metadata.version` one minor per write.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.recon.domain import skills
from polymerhus.recon.domain.skills import (
    SkillInvalidError,
    SkillStore,
    SkillTargetError,
)


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


def _catalogue(
    tmp_path: Path,
    skill: str = "auth_workflow",
    version: str = "1.0",
    frontmatter: str | None = None,
) -> Path:
    """A temp shared catalogue holding one A3-conforming skill (the
    operator-bootstrapped metadata source)."""
    catalogue = tmp_path / "catalogue"
    bundle = catalogue / skill
    bundle.mkdir(parents=True, exist_ok=True)
    text = frontmatter or (
        "---\n"
        f"name: {skill}\n"
        "description: The project's authentication procedure.\n"
        "metadata:\n"
        f"  version: '{version}'\n"
        "---\n\n# Seed\n"
    )
    (bundle / "SKILL.md").write_text(text, encoding="utf-8")
    return catalogue


def _store(tmp_path: Path) -> SkillStore:
    return SkillStore(root_dir=tmp_path / "data")


# --- read: project-first resolution, fail-open ------------------------------


def test_first_update_copies_catalogue_metadata_and_bumps_the_version(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    store.write("proj-1", "auth_workflow", "procedure", "# Procedure\nstep one\n")

    sk = tmp_path / "data" / "proj-1" / "skills" / "auth_workflow"
    assert (sk / "SKILL.md").is_file()
    assert (sk / "references").is_dir()
    assert (sk / "scripts").is_dir()
    assert (sk / "assets").is_dir()
    text = (sk / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: auth_workflow\n" in text
    assert "description: The project's authentication procedure.\n" in text
    assert "version: '1.1'\n" in text  # copied 1.0, minor bumped once
    assert store.read("auth_workflow", project_id="proj-1") == "# Procedure\nstep one\n"


def test_later_updates_bump_the_projects_own_version(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    store.write("proj-1", "auth_workflow", "procedure", "# one\n")
    store.write("proj-1", "auth_workflow", "procedure", "# two\n")

    text = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "version: '1.2'\n" in text
    assert store.read("auth_workflow", project_id="proj-1") == "# two\n"


def test_procedure_write_ignores_frontmatter_in_the_body(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    store.write(
        "proj-1",
        "auth_workflow",
        "procedure",
        "---\nname: injected\ndescription: injected.\n---\n\n# Real\n",
    )

    assert store.read("auth_workflow", project_id="proj-1") == "# Real\n"
    text = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "injected" not in text


def test_project_bundle_shadows_the_shared_catalogue(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path, "demo"))
    store = _store(tmp_path)

    store.write("proj-1", "demo", "procedure", "# Project\n")

    assert store.read("demo", project_id="proj-1") == "# Project\n"


def test_a_project_without_a_bundle_reads_the_shared_skill_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path, "demo"))
    store = _store(tmp_path)

    assert store.read("demo", project_id="proj-1") == "# Seed\n"


def test_read_missing_skill_degrades_to_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path / "empty")
    store = _store(tmp_path)

    assert store.read("nope", project_id="proj-1") == ""
    assert store.read("nope", project_id="proj-1", fallback="FB") == "FB"


# --- write: references target ------------------------------------------------


def test_write_reference_lands_under_references(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# body\n")

    store.write("proj-1", "auth_workflow", "references/roles", "# Roles\nadmin\n")

    ref = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow"
        / "references" / "roles.md"
    )
    assert ref.read_text(encoding="utf-8") == "# Roles\nadmin\n"


# --- write: coded refusals, nothing persisted -------------------------------


def test_write_refuses_without_bootstrapped_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path / "empty")
    store = _store(tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", "# body\n")

    assert not (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    ).exists()


def test_write_refuses_a_malformed_bootstrap_version(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path, version="nope"))
    store = _store(tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", "# body\n")


def test_write_refuses_a_bootstrap_missing_a_required_key(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        skills,
        "_SKILLS_ROOT",
        _catalogue(
            tmp_path,
            frontmatter="---\nname: auth_workflow\nmetadata:\n  version: '1.0'\n---\n\n# Seed\n",
        ),
    )
    store = _store(tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", "# body\n")


@pytest.mark.parametrize(
    "target",
    ["", "procedure/extra", "references/../escape", "references/", "scripts/run", "/etc/passwd"],
)
def test_write_refuses_an_unsupported_or_unsafe_target(tmp_path: Path, target: str) -> None:
    store = _store(tmp_path)
    with pytest.raises(SkillTargetError):
        store.write("proj-1", "auth_workflow", target, "# x\n")


def test_write_refuses_non_text_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "references/r", {"not": "text"})


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b"])
def test_write_refuses_an_unsafe_skill_or_project_id(tmp_path: Path, bad: str) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.write("proj-1", bad, "references/r", "# x\n")
    with pytest.raises(ValueError):
        store.write(bad, "auth_workflow", "references/r", "# x\n")


def test_read_with_an_unsafe_project_id_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path / "empty")
    store = _store(tmp_path)

    assert store.read("nope", project_id="../escape", fallback="FB") == "FB"


def test_concurrent_writers_converge_without_losing_files(
    tmp_path: Path, monkeypatch
) -> None:
    import threading

    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# seed\n")
    errors: list = []

    def write_reference(i: int) -> None:
        try:
            store.write(
                "proj-1", "auth_workflow", f"references/r{i}", f"# R{i}\n"
            )
        except Exception as exc:  # noqa: BLE001 - collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=write_reference, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    for i in range(8):
        ref = (
            tmp_path / "data" / "proj-1" / "skills" / "auth_workflow"
            / "references" / f"r{i}.md"
        )
        assert ref.read_text(encoding="utf-8") == f"# R{i}\n"


def test_concurrent_procedure_rewrites_leave_one_whole_file(
    tmp_path: Path, monkeypatch
) -> None:
    import threading

    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    bodies = [f"# Body {i}\n" for i in range(4)]

    def rewrite(i: int) -> None:
        store.write("proj-1", "auth_workflow", "procedure", bodies[i])

    threads = [threading.Thread(target=rewrite, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    final = store.read("auth_workflow", project_id="proj-1")
    assert final in bodies  # whole, never interleaved


def test_a_failed_write_leaves_prior_content_intact(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# First\n")

    with pytest.raises(SkillTargetError):
        store.write("proj-1", "auth_workflow", "references/../escape", "# x\n")

    assert store.read("auth_workflow", project_id="proj-1") == "# First\n"
