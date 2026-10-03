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

import os
import stat
import tempfile
from pathlib import Path

# The two hunt-config sides. `consumed` is the cap metric (D8): every file the
# pipeline's lazy read moved there counts, mounted/pre-mined files included.
HUNT_CONFIG_SIDES = ("produced", "consumed")
# The two hunter test-spec sides; mirrors the hunter store's produced/consumed
# inbox (the mover owns the produced -> consumed rename).
HUNTER_TEST_SPEC_SIDES = ("produced", "consumed")


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


def hunter_test_specs_dir(data_root: str | Path, project_id: str) -> Path:
    """`<data_root>/<project_id>/hunting/hunter/test-specs`: the spec families.

    Each child is a `<fault_key>/` folder holding the produced/consumed
    `TestImplementationSpec` files (mirrors `hunter_memory.py`, #234).
    """
    return project_dir(data_root, project_id) / "hunting" / "hunter" / "test-specs"


def hunter_test_specs_fault_dir(
    data_root: str | Path, project_id: str, fault_key: str, side: str
) -> Path:
    """`<hunter_test_specs_dir>/<fault_key>/<side>`: one spec family's one inbox.

    The pipeline's lazy read looks exactly here, so a pre-mined spec lands in
    the same produced/ inbox the mover drains - never a bespoke path.
    """
    if side not in HUNTER_TEST_SPEC_SIDES:
        raise ValueError(
            f"hunter test-spec side must be one of {HUNTER_TEST_SPEC_SIDES}, got {side!r}"
        )
    return hunter_test_specs_dir(data_root, project_id) / fault_key / side


def pod_dir(data_root: str | Path, project_id: str) -> Path:
    """`<data_root>/<project_id>/hunting/test-executor-pod`: the pod bucket."""
    return project_dir(data_root, project_id) / "hunting" / "test-executor-pod"


def pod_spec_dir(data_root: str | Path, project_id: str, spec_id: str) -> Path:
    """`<pod_dir>/<spec_id>`: one spec's variants, experiment logs, and export."""
    return pod_dir(data_root, project_id) / spec_id


def pod_experiment_logs_dir(data_root: str | Path, project_id: str, spec_id: str) -> Path:
    """`<pod_spec_dir>/experiment-log`: the per-order D6 experiment-log slices."""
    return pod_spec_dir(data_root, project_id, spec_id) / "experiment-log"


def pod_variants_dir(data_root: str | Path, project_id: str, spec_id: str) -> Path:
    """`<pod_spec_dir>/variants`: the minted `TestImplementationSpec` variants."""
    return pod_spec_dir(data_root, project_id, spec_id) / "variants"


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

    def is_file(self, path: str | Path) -> bool:
        """True only for a regular file; missing is the normal absent case."""
        return Path(path).is_file()

    def is_dir(self, path: str | Path) -> bool:
        """True only for a directory; missing is the normal absent case."""
        return Path(path).is_dir()

    def glob(self, directory: str | Path, pattern: str) -> list[Path]:
        """Matching paths directly under `directory`, sorted; missing -> []."""
        base = Path(directory)
        if not self.is_dir(base):
            return []
        return sorted(base.glob(pattern))

    def read_text(self, path: str | Path) -> str:
        return Path(path).read_text(encoding="utf-8")

    def read_bytes(self, path: str | Path) -> bytes:
        """Raw bytes: the artifact store copies evidence without decoding it."""
        return Path(path).read_bytes()

    def write_text(self, path: str | Path, text: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def write_text_atomic(self, path: str | Path, text: str) -> None:
        """Write via a sibling temp file + `os.replace` (atomic rename).

        A crash leaves either the old file or the new one, never a truncated
        `verdicts.yaml` the close-verify reader would misread as invalid.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def write_bytes_atomic(self, path: str | Path, data: bytes) -> None:
        """Write bytes via a sibling temp file + `os.replace` (atomic rename).

        The artifact store copies evidence byte-for-byte; a crash leaves either
        the old copy or the complete new one, never a truncated chain file that
        the post-copy resolution check would misread.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def list_files(self, directory: str | Path) -> list[Path]:
        """Regular files directly under `directory`, sorted; missing -> []."""
        base = Path(directory)
        if not self.is_dir(base):
            return []
        return sorted(p for p in base.iterdir() if self.is_file(p))

    def list_dirs(self, directory: str | Path) -> list[Path]:
        """Subdirectories directly under `directory`, sorted; missing -> []."""
        base = Path(directory)
        if not self.is_dir(base):
            return []
        return sorted(p for p in base.iterdir() if self.is_dir(p))

    def walk_files(self, directory: str | Path) -> list[Path]:
        """Every regular file under `directory` recursively, sorted; missing -> []."""
        base = Path(directory)
        if not self.is_dir(base):
            return []
        return sorted(p for p in base.rglob("*") if self.is_file(p))

    def walk_regular_files(self, directory: str | Path) -> list[Path]:
        """Every true regular file under `directory` recursively, sorted.

        Unlike `walk_files` (which follows symlinks through `Path.is_file`),
        this uses `lstat` so a symlink or special file is never reported as an
        eligible regular file. Missing directories return `[]`.
        """
        base = Path(directory)
        if not self.is_dir(base):
            return []
        found: list[Path] = []
        for candidate in base.rglob("*"):
            try:
                mode = candidate.lstat().st_mode
            except OSError:
                continue
            if stat.S_ISREG(mode):
                found.append(candidate)
        return sorted(found)

    def is_symlink(self, path: str | Path) -> bool:
        """True when `path` itself (not its target) is a symlink; missing -> False."""
        return Path(path).is_symlink()

    def file_size(self, path: str | Path) -> int:
        """The size in bytes of `path` as reported by `stat`."""
        return Path(path).stat().st_size

    def count_files(self, directory: str | Path) -> int:
        """The number of regular files directly under `directory`."""
        return len(self.list_files(directory))
