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

from polymerhus.app.llm import skills
from polymerhus.app.llm.skills import (
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


# --- revisions: retrievable bodies with systematic provenance (D-W3-2) --------


def test_every_published_write_appends_a_revision_record(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    store.write(
        "proj-1",
        "auth_workflow",
        "procedure",
        "# Procedure\n",
        source_note_ids=["skill:auth_workflow:1", "skill:auth_workflow:2"],
    )

    revisions = store.revisions("proj-1", "auth_workflow")
    assert len(revisions) == 1
    record = revisions[0]
    assert set(record) == {
        "ordinal",
        "target",
        "file",
        "previous_version",
        "version",
        "source_note_ids",
        "written_at",
        "snapshot",
    }
    assert record["ordinal"] == 1
    assert record["target"] == "procedure"
    assert record["file"] == "SKILL.md"
    assert record["previous_version"] == "1.0"
    assert record["version"] == "1.1"
    assert record["source_note_ids"] == [
        "skill:auth_workflow:1",
        "skill:auth_workflow:2",
    ]
    assert record["written_at"]


def test_the_manifest_lives_in_the_skill_bundle_and_is_the_index(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    store.write("proj-1", "auth_workflow", "procedure", "# one\n")

    manifest = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow"
        / "revisions" / "manifest.yaml"
    )
    assert manifest.is_file()
    import yaml

    loaded = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert loaded == store.revisions("proj-1", "auth_workflow")


def test_the_previous_revision_body_stays_retrievable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# one\n")

    store.write("proj-1", "auth_workflow", "procedure", "# two\n")

    first = store.revision_content("proj-1", "auth_workflow", 1)
    second = store.revision_content("proj-1", "auth_workflow", 2)
    assert first and "version: '1.1'\n" in first and "# one\n" in first
    assert second and "version: '1.2'\n" in second and "# two\n" in second
    # The live bundle carries the newest revision, the store's version intact.
    assert "version: '1.2'\n" in (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert store.revisions("proj-1", "auth_workflow")[1]["previous_version"] == "1.1"
    assert store.revision_content("proj-1", "auth_workflow", 99) is None


def test_a_reference_write_is_recorded_with_the_unchanged_version(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# body\n")

    store.write(
        "proj-1", "auth_workflow", "references/roles", "# Roles\n",
        source_note_ids=["skill:auth_workflow:3"],
    )

    record = store.revisions("proj-1", "auth_workflow")[1]
    assert record["target"] == "references/roles"
    assert record["file"] == "references/roles.md"
    assert record["previous_version"] == record["version"] == "1.1"
    assert record["source_note_ids"] == ["skill:auth_workflow:3"]
    assert store.revision_content("proj-1", "auth_workflow", 2) == "# Roles\n"


def test_a_refused_write_appends_no_revision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# First\n")

    with pytest.raises(SkillTargetError):
        store.write("proj-1", "auth_workflow", "references/../escape", "# x\n")

    assert len(store.revisions("proj-1", "auth_workflow")) == 1


def test_a_corrupt_manifest_refuses_the_next_write_and_reads_fail_open(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# First\n")
    manifest = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow"
        / "revisions" / "manifest.yaml"
    )
    manifest.write_text("{not: [a record list", encoding="utf-8")

    with pytest.raises(skills.StoreUnavailableError):
        store.write("proj-1", "auth_workflow", "procedure", "# Second\n")

    # Fail-open reads: a corrupt revision index never breaks a read.
    assert store.revisions("proj-1", "auth_workflow") == []
    # Nothing was persisted: the refusal happened before the bundle write.
    assert store.read("auth_workflow", project_id="proj-1") == "# First\n"


def test_a_provenance_failure_raises_loudly_after_the_bundle_lands(
    tmp_path: Path, monkeypatch
) -> None:
    """Pins the ACCEPTED write ordering (D-W3-2): the bundle file lands first,
    so a provenance (snapshot or manifest) failure raises `store_unavailable`
    naming the landed file, while `SKILL.md` keeps the new body and version and
    the manifest keeps exactly its previous entries."""
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    store.write("proj-1", "auth_workflow", "procedure", "# First\n")
    real = skills.dump_text_atomic

    def fail_on_revisions_paths(path, text):
        if "revisions" in path.parts:
            raise skills.StoreUnavailableError(
                f"store_unavailable: cannot persist {path} (disk full)"
            )
        return real(path, text)

    monkeypatch.setattr(skills, "dump_text_atomic", fail_on_revisions_paths)

    with pytest.raises(skills.StoreUnavailableError) as excinfo:
        store.write("proj-1", "auth_workflow", "procedure", "# Second\n")

    # Loud, and naming the file whose revision could not be recorded.
    assert "SKILL.md" in str(excinfo.value)
    assert "its provenance record did not" in str(excinfo.value)
    # The bundle landed: the new body at the bumped version.
    text = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "version: '1.2'\n" in text and "# Second\n" in text
    # The manifest keeps its previous entries: the failed revision is neither
    # indexed nor half-written.
    revisions = store.revisions("proj-1", "auth_workflow")
    assert [r["ordinal"] for r in revisions] == [1]
    assert revisions[0]["version"] == "1.1"
    assert revisions[0]["previous_version"] == "1.0"


def test_revisions_of_an_unknown_skill_read_as_empty(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.revisions("proj-1", "never-written") == []
    assert store.revision_content("proj-1", "never-written", 1) is None


def test_concurrent_rewrites_append_one_revision_each(tmp_path: Path, monkeypatch) -> None:
    import threading

    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)
    bodies = [f"# Body {i}\n" for i in range(4)]
    errors: list = []

    def rewrite(i: int) -> None:
        try:
            store.write(
                "proj-1", "auth_workflow", "procedure", bodies[i],
                source_note_ids=[f"skill:auth_workflow:{i}"],
            )
        except Exception as exc:  # noqa: BLE001 - collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=rewrite, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    revisions = store.revisions("proj-1", "auth_workflow")
    assert [r["ordinal"] for r in revisions] == [1, 2, 3, 4]
    assert sorted(r["version"] for r in revisions) == ["1.1", "1.2", "1.3", "1.4"]
    assert store.read("auth_workflow", project_id="proj-1") in bodies


# --- write: coded refusals, nothing persisted -------------------------------


@pytest.mark.parametrize("reserved", sorted(skills.RESERVED_SKILL_NAMES))
def test_write_refuses_a_scaffold_owned_directory_name(
    tmp_path: Path, monkeypatch, reserved: str
) -> None:
    """`skills/lessons` and `skills/evolution` are scaffold-owned fixed
    directories, never skill bundles: a write refuses, and a read stays
    fail-open (the catalogue fallback)."""
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    store = _store(tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", reserved, "procedure", "# body\n")

    assert store.read(reserved, project_id="proj-1", fallback="FB") == "FB"
    assert not (
        tmp_path / "data" / "proj-1" / "skills" / reserved / "SKILL.md"
    ).exists()


def test_write_refuses_without_bootstrapped_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path / "empty")
    store = _store(tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", "# body\n")

    assert not (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    ).exists()


# --- write: the version rule (D-W3-2) ----------------------------------------


@pytest.mark.parametrize(
    "bootstrapped,expected",
    [("1", "1.1"), ("1.0", "1.1"), ("1.0.0", "1.1"), ("2.6", "2.7"), ("1.8.3", "1.9")],
)
def test_the_version_bump_accepts_major_minor_and_major_minor_patch(
    tmp_path: Path, monkeypatch, bootstrapped: str, expected: str
) -> None:
    """D-W3-2: the ratified suite carries `1.0.0`, so the one-minor bump reads
    major and minor, ignores the patch, and emits `major.(minor+1)`; the bare
    `major` keeps its historical missing-minor-is-0 reading."""
    monkeypatch.setattr(
        skills, "_SKILLS_ROOT", _catalogue(tmp_path, version=bootstrapped)
    )
    store = _store(tmp_path)

    store.write("proj-1", "auth_workflow", "procedure", "# body\n")

    text = (
        tmp_path / "data" / "proj-1" / "skills" / "auth_workflow" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert f"version: '{expected}'\n" in text


@pytest.mark.parametrize(
    "bootstrapped", ["nope", "1.", ".1", "1.2.3.4", "1.x", "-1.0", ""]
)
def test_the_version_bump_refuses_anything_but_the_ratified_forms(
    tmp_path: Path, monkeypatch, bootstrapped: str
) -> None:
    monkeypatch.setattr(
        skills, "_SKILLS_ROOT", _catalogue(tmp_path, version=bootstrapped)
    )
    store = _store(tmp_path)

    with pytest.raises(SkillInvalidError):
        store.write("proj-1", "auth_workflow", "procedure", "# body\n")


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
