"""The filesystem seam over the #234 app-owned data root (ticket #270).

The trial reads the persisted-state predicates (the authn skill bundle, the
pre-mined hunt configs) and writes its own bootstrap state through one
`FileStore`. It is the injectable filesystem seam: tests pass a temp-rooted
instance or a subclass that scripts the consumed-count sequence to model the
cap race (R7). The layout helpers mirror the app's own `<data_root>` layout
(`src/polymerhus/app/data_root.py`), so the harness and the pipeline address
the SAME produced/consumed inbox - never a bespoke copy.

Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from pathlib import Path

# The two hunt-config sides. `consumed` is the cap metric (D8): every file the
# pipeline's lazy read moved there counts, mounted/pre-mined files included.
HUNT_CONFIG_SIDES = ("produced", "consumed")


def project_dir(data_root: str | Path, project_id: str) -> Path:
    """`<data_root>/<project_id>`: the one per-project data bucket."""
    return Path(data_root) / project_id


def skills_dir(data_root: str | Path, project_id: str) -> Path:
    """`<data_root>/<project_id>/skills`: the per-project skill bundles."""
    return project_dir(data_root, project_id) / "skills"


def authn_skill_path(data_root: str | Path, project_id: str) -> Path:
    """The project-authored `authn` bundle's `SKILL.md` (D13).

    The `SkillStore` resolves a project skill at exactly this location, so the
    predicate reads what the loader reads.
    """
    return skills_dir(data_root, project_id) / "authn" / "SKILL.md"


def hunt_configs_dir(data_root: str | Path, project_id: str, side: str) -> Path:
    """`<data_root>/<project_id>/hunting/orchestration/hunt_configs/<side>`."""
    if side not in HUNT_CONFIG_SIDES:
        raise ValueError(f"hunt config side must be one of {HUNT_CONFIG_SIDES}, got {side!r}")
    return (
        project_dir(data_root, project_id)
        / "hunting"
        / "orchestration"
        / "hunt_configs"
        / side
    )


class FileStore:
    """The local filesystem implementation of the trial's file seam.

    A missing file/directory is the normal absent case (`exists` False, an
    empty listing), never a raise - the predicates treat absence as a named
    block, and a store that cannot look at a missing path must not crash the
    gate. Writes create parents so the trial can bootstrap a fresh project
    directory without a separate scaffold step.
    """

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def read_text(self, path: str | Path) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_text(self, path: str | Path, text: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def list_files(self, directory: str | Path) -> list[Path]:
        """Regular files directly under `directory`, sorted; missing -> []."""
        base = Path(directory)
        if not base.is_dir():
            return []
        return sorted(p for p in base.iterdir() if p.is_file())

    def walk_files(self, directory: str | Path) -> list[Path]:
        """Every regular file under `directory` recursively, sorted; missing -> []."""
        base = Path(directory)
        if not base.is_dir():
            return []
        return sorted(p for p in base.rglob("*") if p.is_file())

    def count_files(self, directory: str | Path) -> int:
        """The number of regular files directly under `directory`."""
        return len(self.list_files(directory))
