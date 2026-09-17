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
# and the FIXED sub-layouts the stores write into. The full fixed skeleton is
# enumerated here so no module store owns directory creation; a path keyed by a
# runtime id (a hunt fault key, a pod spec id) is the only thing a store ever
# creates lazily, and only its own leaf. Adding a fixed module dir is a change
# HERE, never a change in the module store.
PROJECT_SCAFFOLD: tuple[str, ...] = (
    "skills",
    "hunting/orchestration",
    "hunting/orchestration/hunt_configs/produced",
    "hunting/orchestration/hunt_configs/consumed",
    "hunting/hunter",
    "hunting/hunter/test-specs",
    "hunting/test-executor-pod",
)


def validate_path_component(value: str, what: str) -> str:
    """Reject a `value` that is not exactly one safe path component.

    Directory names derived from ids (project ids, skill names) are used
    verbatim on disk, so path separators, control characters, and
    dot-traversal forms are refused. Shared by every store on the data root
    so the rule is defined once.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"{what} must be a non-empty string")
    if value in (".", ".."):
        raise ValueError(f"{what} {value!r} is not a valid path component")
    if any(ch in value for ch in "/\\\x00") or any(ord(ch) < 32 for ch in value):
        raise ValueError(
            f"{what} {value!r} contains a path separator or control character"
        )
    return value


def _validate_project_id(project_id: str) -> str:
    """The project-id form of `validate_path_component`."""
    return validate_path_component(project_id, "project_id")


def project_dir(
    project_id: str, relative: str = "", root: str | Path | None = None
) -> Path:
    """The project directory on the app-owned data root, optionally under one
    `relative` scaffold path: ``<root>/<project_id>/<relative>``.

    This is the ONE resolver every module store derives its bucket from, so the
    layout is defined once (``PROJECT_SCAFFOLD``) and no store re-spells it.
    ``root`` overrides the fixed default (``DATA_ROOT``) for the tests'
    explicit temp roots; ``project_id`` is validated as one safe component.
    """
    base = Path(root) if root is not None else DATA_ROOT
    return base / _validate_project_id(project_id) / relative


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


__all__ = [
    "DATA_ROOT",
    "PROJECT_SCAFFOLD",
    "ensure_data_root",
    "ensure_project",
    "project_dir",
    "validate_path_component",
]
