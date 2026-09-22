"""One-off: migrate the hunting stores' data onto the app-owned data root (#234).

The hunting stores moved from the module-owned root

    <repo>/src/polymerhus/attack/hunting/data/<project_id>/{orchestration,hunter,test-executor-pod,projects}/
    <repo>/src/polymerhus/attack/hunting/data/fault-kb.yaml

to the app-owned layout (`src/polymerhus/app/data_root.py::DATA_ROOT`)

    <repo>/data/<project_id>/hunting/{orchestration,hunter,test-executor-pod,projects}/
    <repo>/data/hunting/fault-kb.yaml

Contract (operator ruling, D234-15): copy -> verify -> delete. Every source file
must exist at the destination with identical bytes (sha256) before anything is
removed; a collision with differing content aborts that project and leaves it in
place. The legacy module `data/` package (`__init__.py`, `__pycache__`) is
removed once every project and the catalogue have moved.

Idempotent: a missing legacy root is a no-op, and a project already migrated
(only at the destination) is skipped.

    python tools/hunting/migrate_hunting_data_root.py --repo <repo> [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

# The buckets a legacy project directory may hold (the stores' per-project
# siblings). Anything else under a project dir is carried verbatim.
KNOWN_BUCKETS = ("orchestration", "hunter", "test-executor-pod", "projects")
CATALOGUE = "fault-kb.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _migrate_project(src: Path, dest: Path, *, dry_run: bool) -> str:
    """Copy one project tree src -> dest, verify, delete. Returns a status."""
    if not src.exists():
        return "absent"
    src_files = _files(src)
    collisions = [
        f for f in src_files
        if (dest / f.relative_to(src)).exists()
        and _sha256(dest / f.relative_to(src)) != _sha256(f)
    ]
    if collisions:
        return f"ABORT: {len(collisions)} destination file(s) differ"
    if dry_run:
        return f"dry-run: {len(src_files)} file(s) would move"

    for src_file in src_files:
        dst_file = dest / src_file.relative_to(src)
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
    # verify every source file landed byte-identical BEFORE deleting anything
    for src_file in src_files:
        dst_file = dest / src_file.relative_to(src)
        if not dst_file.exists() or _sha256(dst_file) != _sha256(src_file):
            return f"ABORT: verification failed for {dst_file}"

    shutil.rmtree(src)
    return f"moved {len(src_files)} file(s)"


def migrate(repo: Path, *, dry_run: bool = False) -> int:
    legacy_root = repo / "src" / "polymerhus" / "attack" / "hunting" / "data"
    data_root = repo / "data"
    if not legacy_root.exists():
        print(f"no legacy root at {legacy_root}; nothing to do")
        return 0

    failures = 0
    for child in sorted(legacy_root.iterdir()):
        if child.name in ("__init__.py", "__pycache__"):
            continue
        if child.name == CATALOGUE:
            dest = data_root / "hunting" / CATALOGUE
            if dest.exists() and _sha256(dest) != _sha256(child):
                print(f"ABORT catalogue: {dest} differs")
                failures += 1
                continue
            if dry_run:
                print(f"catalogue dry-run: would move -> {dest}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, dest)
            if _sha256(dest) != _sha256(child):
                print(f"ABORT catalogue: verification failed for {dest}")
                failures += 1
                continue
            child.unlink()
            print(f"catalogue -> {dest}")
            continue
        if not child.is_dir():
            print(f"carrying stray file {child.name} untouched")
            continue
        dest = data_root / child.name / "hunting"
        try:
            status = _migrate_project(child, dest, dry_run=dry_run)
        except OSError as exc:  # noqa: BLE001 - report, never a partial delete
            status = f"ABORT: {exc}"
        if status.startswith("ABORT"):
            failures += 1
        print(f"{child.name}: {status} -> {dest}")

    leftovers = [
        p for p in legacy_root.rglob("*")
        if p.is_file() and p.name != "__init__.py" and "__pycache__" not in p.parts
    ]
    if leftovers:
        if dry_run:
            print(f"dry-run: {len(leftovers)} legacy file(s) would move; the root would be removed")
            return failures
        print(f"legacy root still holds {len(leftovers)} file(s); leaving it in place")
        return failures or 1

    if not dry_run:
        shutil.rmtree(legacy_root)
        print(f"removed the legacy root {legacy_root}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="the repository root (default: inferred from this script)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return migrate(args.repo.resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
