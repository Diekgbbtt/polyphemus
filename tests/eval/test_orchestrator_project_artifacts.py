"""The allowlisted project-artifact catalog (real eval project artifacts, Task 1).

The catalog is the deterministic, path-safe inventory the materializer
snapshots for a Trial. These tests pin the six allowlisted families, the
exclusion of neighboring files, the empty-catalog cases, and the rejection of
symlinks, unsafe segments, and special or escaped files - always without
leaking an absolute host path in the error text.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from orchestrator import project_artifacts
from orchestrator.files import FileStore
from orchestrator.project_artifacts import (
    ProjectArtifact,
    ProjectArtifactError,
    artifact_manifest,
    collect_project_artifacts,
)

PROJECT_ID = "proj-1"

MANIFEST_FIELDS = (
    "artifact_id",
    "category",
    "kind",
    "relative_path",
    "media_type",
    "size_bytes",
    "sha256",
    "representation",
)


def _write(root: Path, relative: str, content: bytes | str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def _build_full_project(root: Path) -> Path:
    """Every hunting and skill family under one project directory."""
    project = root / PROJECT_ID
    _write(project, "hunting/orchestration/hunt_configs/produced/hc-1.yaml", "hunt: 1\n")
    _write(project, "hunting/orchestration/hunt_configs/consumed/hc-2.yaml", "hunt: 2\n")
    _write(project, "hunting/hunter/test-specs/fault-a/produced/spec-1.yaml", "spec: 1\n")
    _write(project, "hunting/hunter/test-specs/fault-a/consumed/spec-2.yaml", "spec: 2\n")
    _write(project, "hunting/test-executor-pod/spec-1/variants/variant-1.yaml", "v: 1\n")
    _write(project, "hunting/test-executor-pod/spec-1/experiment-log/log-1.yaml", "log: 1\n")
    _write(project, "hunting/test-executor-pod/spec-1/export.yaml", "export: 1\n")
    _write(project, "skills/authn/SKILL.md", "# Authn\n")
    _write(project, "skills/authn/references/notes.md", "notes\n")
    _write(project, "skills/authn/references/deep/nested.md", "nested\n")
    _write(project, "skills/authn/scripts/run.sh", "echo hi\n")
    _write(project, "skills/authn/assets/logo.png", b"\x89PNG\r\n\x1a\n\x00\x01")
    return project


def test_collects_every_hunting_and_skill_family(tmp_path: Path) -> None:
    project = _build_full_project(tmp_path)
    files = FileStore()

    artifacts = collect_project_artifacts(tmp_path, PROJECT_ID, files=files)

    expected_paths = [
        "hunting/hunter/test-specs/fault-a/consumed/spec-2.yaml",
        "hunting/hunter/test-specs/fault-a/produced/spec-1.yaml",
        "hunting/orchestration/hunt_configs/consumed/hc-2.yaml",
        "hunting/orchestration/hunt_configs/produced/hc-1.yaml",
        "hunting/test-executor-pod/spec-1/experiment-log/log-1.yaml",
        "hunting/test-executor-pod/spec-1/export.yaml",
        "hunting/test-executor-pod/spec-1/variants/variant-1.yaml",
        "skills/authn/SKILL.md",
        "skills/authn/assets/logo.png",
        "skills/authn/references/deep/nested.md",
        "skills/authn/references/notes.md",
        "skills/authn/scripts/run.sh",
    ]
    assert [a.relative_path for a in artifacts] == expected_paths

    expected_kinds = {
        "hunting/orchestration/hunt_configs/consumed/hc-2.yaml": ("hunting", "hunt_config"),
        "hunting/orchestration/hunt_configs/produced/hc-1.yaml": ("hunting", "hunt_config"),
        "hunting/hunter/test-specs/fault-a/consumed/spec-2.yaml": ("hunting", "test_spec"),
        "hunting/hunter/test-specs/fault-a/produced/spec-1.yaml": ("hunting", "test_spec"),
        "hunting/test-executor-pod/spec-1/experiment-log/log-1.yaml": (
            "hunting",
            "experiment_log",
        ),
        "hunting/test-executor-pod/spec-1/export.yaml": ("hunting", "pod_export"),
        "hunting/test-executor-pod/spec-1/variants/variant-1.yaml": ("hunting", "pod_variant"),
        "skills/authn/SKILL.md": ("skill", "skill_procedure"),
        "skills/authn/assets/logo.png": ("skill", "skill_asset"),
        "skills/authn/references/deep/nested.md": ("skill", "skill_reference"),
        "skills/authn/references/notes.md": ("skill", "skill_reference"),
        "skills/authn/scripts/run.sh": ("skill", "skill_script"),
    }
    expected_media = {
        "skills/authn/SKILL.md": ("text/markdown", "markdown"),
        "skills/authn/assets/logo.png": ("image/png", "binary"),
        "skills/authn/references/deep/nested.md": ("text/markdown", "markdown"),
        "skills/authn/references/notes.md": ("text/markdown", "markdown"),
        "skills/authn/scripts/run.sh": ("text/x-shellscript", "text"),
    }

    by_path = {a.relative_path: a for a in artifacts}
    for artifact in artifacts:
        assert isinstance(artifact, ProjectArtifact)
        expected_category, expected_kind = expected_kinds[artifact.relative_path]
        assert artifact.category == expected_category
        assert artifact.kind == expected_kind
        expected_id = hashlib.sha256(artifact.relative_path.encode()).hexdigest()
        assert artifact.artifact_id == expected_id
        source = project / artifact.relative_path
        payload = source.read_bytes()
        assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
        assert artifact.size_bytes == len(payload)
        assert artifact.source_path == source
        assert artifact.relative_path.split("/") and not artifact.relative_path.startswith("/")
        if artifact.relative_path in expected_media:
            expected_media_type, expected_representation = expected_media[artifact.relative_path]
            assert artifact.media_type == expected_media_type
            assert artifact.representation == expected_representation
        else:
            assert artifact.media_type == "application/yaml"
            assert artifact.representation == "yaml"

    entry = by_path["skills/authn/SKILL.md"].as_manifest_entry()
    assert tuple(entry) == MANIFEST_FIELDS
    assert "source_path" not in entry


def test_excludes_neighboring_project_files(tmp_path: Path) -> None:
    project = _build_full_project(tmp_path)
    _write(project, "notes.md", "private\n")
    _write(project, "hunting/draft.yaml", "draft: 1\n")
    _write(project, "hunting/orchestration/hunt_configs/stray.yaml", "stray: 1\n")
    _write(project, "hunting/orchestration/hunt_configs/produced/ignore.md", "ignore\n")
    _write(project, "hunting/hunter/test-specs/fault-a/loose.yaml", "loose: 1\n")
    _write(project, "hunting/test-executor-pod/spec-1/notes.md", "notes\n")
    _write(project, "hunting/test-executor-pod/spec-1/extras/other.yaml", "other\n")
    _write(project, "skills/authn/extra/other.md", "other\n")
    _write(project, "skills/authn/references/notes.txt", "reference text\n")

    artifacts = collect_project_artifacts(tmp_path, PROJECT_ID, files=FileStore())

    relative = {a.relative_path for a in artifacts}
    assert "notes.md" not in relative
    assert "hunting/draft.yaml" not in relative
    assert "hunting/orchestration/hunt_configs/stray.yaml" not in relative
    assert "hunting/orchestration/hunt_configs/produced/ignore.md" not in relative
    assert "hunting/hunter/test-specs/fault-a/loose.yaml" not in relative
    assert "hunting/test-executor-pod/spec-1/notes.md" not in relative
    assert "hunting/test-executor-pod/spec-1/extras/other.yaml" not in relative
    assert "skills/authn/extra/other.md" not in relative
    assert "skills/authn/references/notes.txt" in relative


def test_accepts_domain_punctuation_in_dynamic_segments(tmp_path: Path) -> None:
    project = tmp_path / PROJECT_ID
    _write(
        project,
        "hunting/hunter/test-specs/fault:http:request/produced/a.yaml",
        "a: 1\n",
    )
    _write(project, "hunting/hunter/test-specs/fault::auth/consumed/b.yaml", "b: 1\n")
    _write(project, "hunting/test-executor-pod/spec:variant/variants/v.yaml", "v: 1\n")
    _write(project, "hunting/test-executor-pod/spec:variant/export.yaml", "e: 1\n")
    _write(project, "skills/skill:name/SKILL.md", "# skill\n")
    _write(project, "skills/skill:name/scripts/run:me.sh", "echo run\n")

    artifacts = collect_project_artifacts(tmp_path, PROJECT_ID, files=FileStore())

    expected = sorted(
        [
            "hunting/hunter/test-specs/fault:http:request/produced/a.yaml",
            "hunting/hunter/test-specs/fault::auth/consumed/b.yaml",
            "hunting/test-executor-pod/spec:variant/export.yaml",
            "hunting/test-executor-pod/spec:variant/variants/v.yaml",
            "skills/skill:name/SKILL.md",
            "skills/skill:name/scripts/run:me.sh",
        ]
    )
    assert [a.relative_path for a in artifacts] == expected

    kinds = {a.relative_path: a.kind for a in artifacts}
    assert kinds["hunting/hunter/test-specs/fault:http:request/produced/a.yaml"] == "test_spec"
    assert kinds["hunting/hunter/test-specs/fault::auth/consumed/b.yaml"] == "test_spec"
    assert kinds["hunting/test-executor-pod/spec:variant/variants/v.yaml"] == "pod_variant"
    assert kinds["hunting/test-executor-pod/spec:variant/export.yaml"] == "pod_export"
    assert kinds["skills/skill:name/SKILL.md"] == "skill_procedure"
    assert kinds["skills/skill:name/scripts/run:me.sh"] == "skill_script"
    for artifact in artifacts:
        assert artifact.artifact_id == hashlib.sha256(artifact.relative_path.encode()).hexdigest()


def test_missing_optional_directories_are_empty(tmp_path: Path) -> None:
    files = FileStore()

    assert collect_project_artifacts(tmp_path, PROJECT_ID, files=files) == ()

    (tmp_path / PROJECT_ID).mkdir(parents=True)
    assert collect_project_artifacts(tmp_path, PROJECT_ID, files=files) == ()

    (tmp_path / PROJECT_ID / "hunting").mkdir()
    assert collect_project_artifacts(tmp_path, PROJECT_ID, files=files) == ()


def test_rejects_symlink_inside_allowlisted_tree(tmp_path: Path) -> None:
    project = _build_full_project(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("outside\n", encoding="utf-8")
    link = project / "hunting/orchestration/hunt_configs/produced/evil.yaml"
    link.symlink_to(outside)

    with pytest.raises(ProjectArtifactError) as excinfo:
        collect_project_artifacts(tmp_path, PROJECT_ID, files=FileStore())

    assert excinfo.value.failure == "artifact_unsafe"
    assert str(tmp_path) not in str(excinfo.value)

    link.unlink()
    nested_dir = project / "skills/authn/references/external"
    nested_dir.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(ProjectArtifactError) as excinfo:
        collect_project_artifacts(tmp_path, PROJECT_ID, files=FileStore())
    assert excinfo.value.failure == "artifact_unsafe"
    assert str(tmp_path) not in str(excinfo.value)


def test_rejects_unsafe_project_and_dynamic_segments(tmp_path: Path) -> None:
    _build_full_project(tmp_path)
    files = FileStore()

    for bad_project in (
        ".",
        "..",
        "../evil",
        "a/b",
        "",
        "/abs",
        "nested/..",
        ".hidden",
        "back\\slash",
        "nul\x00id",
        "ctrl\x01id",
    ):
        with pytest.raises(ProjectArtifactError) as excinfo:
            collect_project_artifacts(tmp_path, bad_project, files=files)
        assert excinfo.value.failure == "artifact_unsafe"
        assert str(tmp_path) not in str(excinfo.value)

    # Everything that is not a safe single path segment is rejected for the
    # dynamic families too (fault key, spec id, skill name).
    for bad_segment in (".", "..", "a/b", "back\\slash", "nul\x00id", "ctrl\x01id"):
        with pytest.raises(ProjectArtifactError) as excinfo:
            project_artifacts._require_safe_dynamic_segment(bad_segment, where="skill_name")
        assert excinfo.value.failure == "artifact_unsafe"

    # End to end, through a real (creatable) unsafe directory name.
    for bad_name in ("back\\slash", "ctrl\x01name"):
        unsafe_skill = tmp_path / PROJECT_ID / "skills" / bad_name
        unsafe_skill.mkdir(parents=True)
        (unsafe_skill / "SKILL.md").write_text("# bad\n", encoding="utf-8")
        with pytest.raises(ProjectArtifactError) as excinfo:
            collect_project_artifacts(tmp_path, PROJECT_ID, files=files)
        assert excinfo.value.failure == "artifact_unsafe"
        assert str(tmp_path) not in str(excinfo.value)
        (unsafe_skill / "SKILL.md").unlink()
        unsafe_skill.rmdir()


def test_rejects_special_or_escaped_files(tmp_path: Path) -> None:
    project = _build_full_project(tmp_path)
    files = FileStore()

    fifo = project / "hunting/orchestration/hunt_configs/produced/pipe.yaml"
    os.mkfifo(fifo)
    with pytest.raises(ProjectArtifactError) as excinfo:
        collect_project_artifacts(tmp_path, PROJECT_ID, files=files)
    assert excinfo.value.failure == "artifact_unsafe"
    assert str(tmp_path) not in str(excinfo.value)
    fifo.unlink()

    outside_dir = tmp_path / "external-configs"
    outside_dir.mkdir()
    (outside_dir / "leak.yaml").write_text("leak: 1\n", encoding="utf-8")
    produced = project / "hunting/orchestration/hunt_configs/produced"
    for child in produced.iterdir():
        child.unlink()
    produced.rmdir()
    produced.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(ProjectArtifactError) as excinfo:
        collect_project_artifacts(tmp_path, PROJECT_ID, files=files)
    assert excinfo.value.failure == "artifact_unsafe"
    assert str(tmp_path) not in str(excinfo.value)


def test_artifact_manifest_is_deterministic_and_omits_source_path(tmp_path: Path) -> None:
    _build_full_project(tmp_path)
    artifacts = collect_project_artifacts(tmp_path, PROJECT_ID, files=FileStore())

    manifest = artifact_manifest(
        list(reversed(artifacts)),
        project_id=PROJECT_ID,
        captured_at="2026-10-03T00:00:00Z",
        snapshot_sha256="deadbeef",
    )

    assert manifest["status"] == "available"
    assert manifest["project_id"] == PROJECT_ID
    assert manifest["captured_at"] == "2026-10-03T00:00:00Z"
    assert manifest["snapshot_sha256"] == "deadbeef"
    paths = [entry["relative_path"] for entry in manifest["entries"]]
    assert paths == sorted(paths)
    for entry in manifest["entries"]:
        assert tuple(entry) == MANIFEST_FIELDS
