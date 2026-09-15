"""The app-layer data-root and per-project scaffold owner (#234).

One shared module owns the on-disk data root every module writes under, so
the layout is defined once and no module scaffolds its own directories:

    <data_root>/<project_id>/
    ├── skills/                 # the skills module owns this
    ├── hunting/
    │   ├── orchestration/      # HuntStore
    │   ├── hunter/             # HunterMemoryStore
    │   └── test-executor-pod/  # PodMemoryStore
    └── ...                     # later module dirs, same one-dir-per-module rule

``ensure_data_root()`` runs at system bootstrap (``app.main`` startup) and
``ensure_project()`` runs at project creation
(``project_management.repository.create_project``). Both create-if-absent and
are idempotent: they never remove or overwrite existing state. A module store
then writes only the files it owns inside its already-created directory.

This module performs no I/O at import (CODING_STANDARD section 6); the root is
resolved inside the functions. The fixed default root lives outside the
``src/`` package tree at ``<codebase_root>/data/`` - the tests inject an
explicit temp root (the ``hunt_store`` / #220 auth-store precedent).
"""
from __future__ import annotations

from pathlib import Path

# src/polymerhus/app/data_root.py -> parents = [app, polymerhus, src, <root>].
# The data root lives at the repo root, OUTSIDE the src/ package tree, so the
# on-disk distribution is a deployment concern, not a package-data one.
DATA_ROOT = Path(__file__).resolve().parents[3] / "data"

# Every directory ``ensure_project`` creates for a project: the module buckets
# the built modules write under. Adding a module dir is a change HERE, never a
# change in the module store.
PROJECT_SCAFFOLD: tuple[str, ...] = (
    "skills",
    "hunting/orchestration",
    "hunting/hunter",
    "hunting/test-executor-pod",
)


def _validate_project_id(project_id: str) -> str:
    """Reject a ``project_id`` that is not exactly one safe path component.

    The project id is used verbatim as a directory name, so only path
    separators, control characters, and dot-traversal forms are refused.
    """
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("data_root: project_id must be a non-empty string")
    if project_id in (".", ".."):
        raise ValueError(
            f"data_root: project_id {project_id!r} is not a valid path component"
        )
    if any(ch in project_id for ch in "/\\\x00") or any(
        ord(ch) < 32 for ch in project_id
    ):
        raise ValueError(
            f"data_root: project_id {project_id!r} contains a path separator or "
            "control character"
        )
    return project_id


def ensure_data_root(root: str | Path | None = None) -> Path:
    """Create the data root if absent and return it (idempotent, fail-safe).

    ``root`` overrides the fixed default (``DATA_ROOT``) - the tests' explicit
    temp root. Existing content is never touched.
    """
    base = Path(root) if root is not None else DATA_ROOT
    base.mkdir(parents=True, exist_ok=True)
    return base


def ensure_project(project_id: str, root: str | Path | None = None) -> Path:
    """Create the whole per-project scaffold under the data root (idempotent).

    Creates ``<root>/<project_id>`` and every directory in ``PROJECT_SCAFFOLD``,
    creating the data root first. Returns the project directory. Existing files
    are never removed or overwritten.
    """
    base = ensure_data_root(root)
    project_dir = base / _validate_project_id(project_id)
    for relative in PROJECT_SCAFFOLD:
        (project_dir / relative).mkdir(parents=True, exist_ok=True)
    return project_dir


__all__ = ["DATA_ROOT", "PROJECT_SCAFFOLD", "ensure_data_root", "ensure_project"]
