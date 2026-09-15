"""The app-layer data-root ownership seam (#234).

One shared app-layer module owns the per-project data root and every scaffold
directory, so no module scaffolds its own writes. These tests cross the public
scaffold seam only: the returned paths and the directories that exist on disk
after ``ensure_data_root`` / ``ensure_project``. No live infrastructure.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.app.data_root import (
    PROJECT_SCAFFOLD,
    ensure_data_root,
    ensure_project,
)


def test_ensure_data_root_creates_and_returns_the_root(tmp_path: Path) -> None:
    root = tmp_path / "data"
    assert not root.exists()

    returned = ensure_data_root(root=root)

    assert returned == root
    assert root.is_dir()


def test_ensure_data_root_is_idempotent_and_never_destructive(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_data_root(root=root)
    existing = root / "from-a-prior-boot.txt"
    existing.write_text("keep me", encoding="utf-8")

    ensure_data_root(root=root)

    assert existing.read_text(encoding="utf-8") == "keep me"


def test_ensure_project_creates_the_whole_scaffold(tmp_path: Path) -> None:
    root = tmp_path / "data"

    project_dir = ensure_project("proj-1", root=root)

    assert project_dir == root / "proj-1"
    for rel in PROJECT_SCAFFOLD:
        assert (project_dir / rel).is_dir(), f"missing scaffold dir {rel}"


def test_ensure_project_scaffold_is_idempotent_and_never_destructive(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    project_dir = ensure_project("proj-1", root=root)
    kept = project_dir / "skills" / "already-here.md"
    kept.write_text("keep me", encoding="utf-8")

    ensure_project("proj-1", root=root)

    assert kept.read_text(encoding="utf-8") == "keep me"


def test_ensure_project_isolates_projects(tmp_path: Path) -> None:
    root = tmp_path / "data"

    ensure_project("proj-a", root=root)

    assert (root / "proj-a" / "skills").is_dir()
    assert not (root / "proj-b").exists()


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b", "a\x00b"])
def test_ensure_project_rejects_an_unsafe_project_id(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        ensure_project(bad, root=tmp_path / "data")
