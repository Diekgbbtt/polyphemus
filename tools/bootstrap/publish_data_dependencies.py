#!/usr/bin/env python3
"""Publish the data dependencies to the eval host's designed location.

The eval system reads one directory per target at a fixed path on the eval host
(`/root/eval-dd/data/<target>/`, pinned by the setups YAMLs): the operator KB
and its L1 surface rendering, the judge-only research notes and surface map,
and the AuthContext (`auth/{overview,credentials}.yaml` plus `skills/authn/`).
The setup helpers place those files through the data-dependency endpoints when
a trial is configured, so the directory has to hold exactly one coherent set.

This command is the missing link between a regeneration and an eval run: it
assembles the set from the run's two local roots (the committed KB root and the
gitignored staging root), replaces the target's directory on the eval host, and
verifies the landing by content hash. It never prints file contents - the
credentials ride as bytes - and it refuses to publish an incomplete set.

Usage:

  python3 tools/bootstrap/publish_data_dependencies.py \
      --kbs eval/data/webexploitbench \
      --staging eval/data-dependencies \
      --ssh eval-server-polyphemus \
      --dest /root/eval-dd/data \
      [--targets dataease,comfyui] [--backup] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# The KB-side files the eval host expects beside the target's directory
# (setups YAML header, `Data dependencies live in one directory per target`).
KB_FILES: tuple[str, ...] = (
    "operator_kb.md",
    "l1-surface.yaml",
    "research-notes.md",
    "surface-map.md",
)
# The AuthContext paths the trial's placement helper reads.
AUTH_OVERVIEW = "auth/overview.yaml"
AUTH_CREDENTIALS = "auth/credentials.yaml"
SKILL_DIR = "skills/authn"


class PublishError(RuntimeError):
    """The set cannot be published as-is; the message names the defect."""


def _hash_tree(root: Path) -> dict[str, str]:
    """Relative path -> sha256 for every file under `root`."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            digests[str(path.relative_to(root))] = digest
    return digests


def _copy_into(source: Path, destination: Path) -> None:
    """Copy one artifact, creating its destination subdirectory when needed."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def assemble_set(kb_dir: Path, staging_dir: Path, into: Path) -> dict[str, str]:
    """Build one target's publishable tree in `into`; returns its hash tree.

    The set is the design's list and nothing else: the four KB files, the auth
    pair (when the staging root carries it), and the authn skill directory
    (when it exists). Assessment records stay out: they are review artifacts,
    not inputs to an eval trial.
    """
    if not (kb_dir / "operator_kb.md").is_file():
        raise PublishError(f"{kb_dir}: operator_kb.md is missing")
    if not (kb_dir / "l1-surface.yaml").is_file():
        raise PublishError(f"{kb_dir}: l1-surface.yaml is missing")
    overview = staging_dir / AUTH_OVERVIEW
    if not overview.is_file():
        raise PublishError(
            f"{staging_dir}: {AUTH_OVERVIEW} is missing (the AuthContext is incomplete)"
        )
    for name in KB_FILES:
        source = kb_dir / name
        if source.is_file():
            _copy_into(source, into / name)
    for name in (AUTH_OVERVIEW, AUTH_CREDENTIALS):
        source = staging_dir / name
        if source.is_file():
            _copy_into(source, into / name)
    skill = staging_dir / SKILL_DIR
    if skill.is_dir():
        shutil.copytree(skill, into / SKILL_DIR)
    hashes = _hash_tree(into)
    # The AuthContext is the point of the placement: refuse a set that cannot
    # give the trial a sign-in procedure.
    if AUTH_OVERVIEW not in hashes:
        raise PublishError(f"{staging_dir}: {AUTH_OVERVIEW} did not assemble")
    return hashes


def rsync_argv(local: Path, ssh: str, remote: Path, *, delete: bool = True) -> list[str]:
    """The rsync command that replaces one target's directory on the host."""
    argv = ["rsync", "-a", "--checksum", "-e", "ssh"]
    if delete:
        argv.append("--delete")
    argv += [f"{local}/", f"{ssh}:{remote}/"]
    return argv


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _remote_hashes(ssh: str, remote: Path) -> dict[str, str]:
    command = (
        f"cd {remote} && find . -type f | sort | "
        "xargs -r sha256sum | awk '{print substr($0, 67) \" \" $1}'"
    )
    result = _run(["ssh", ssh, command])
    if result.returncode != 0:
        raise PublishError(f"hash read on {ssh}:{remote} failed: {result.stderr.strip()}")
    hashes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, digest = line.partition(" ")
        name = name.removeprefix("./")
        if name:
            hashes[name] = digest
    return hashes


def snapshot(ssh: str, dest: Path) -> str:
    """Archive the host's whole data root beside it; returns the archive path.

    One snapshot before any change, not one per target: the archive lands
    outside `dest` (as a sibling), so the data root itself keeps containing
    exactly the target directories.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = f"{dest}-pre-publish-{stamp}.tar.gz"
    result = _run(
        ["ssh", ssh, f"tar -czf {archive} -C {dest.parent} {dest.name}"]
    )
    if result.returncode != 0:
        raise PublishError(f"snapshot to {archive} failed: {result.stderr.strip()}")
    return archive


@dataclass
class TargetResult:
    target: str
    files: int = 0
    published: bool = False
    notes: list[str] = field(default_factory=list)


def publish(
    target: str,
    *,
    kb_dir: Path,
    staging_dir: Path,
    ssh: str,
    dest: Path,
    dry_run: bool,
    workdir: Path,
) -> TargetResult:
    result = TargetResult(target=target)
    if not kb_dir.is_dir() or not staging_dir.is_dir():
        raise PublishError(
            f"{target}: expected sources {kb_dir} and {staging_dir} to exist"
        )
    assembled = workdir / target
    assembled.mkdir(parents=True)
    hashes = assemble_set(kb_dir, staging_dir, assembled)
    result.files = len(hashes)
    if dry_run:
        result.notes.append("dry run: assembled and hashed, nothing sent")
        return result
    sent = _run(rsync_argv(assembled, ssh, dest / target))
    if sent.returncode != 0:
        raise PublishError(f"{target}: rsync failed: {sent.stderr.strip()}")
    landed = _remote_hashes(ssh, dest / target)
    if landed != hashes:
        extra = {k: v for k, v in landed.items() if k not in hashes}
        missing = {k: v for k, v in hashes.items() if k not in landed}
        mismatch = {
            k for k in hashes if k in landed and hashes[k] != landed[k]
        }
        raise PublishError(
            f"{target}: landing verification failed "
            f"(extra={sorted(extra)}, missing={sorted(missing)}, "
            f"mismatch={sorted(mismatch)})"
        )
    result.published = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kbs", required=True, type=Path, help="the committed KB root")
    parser.add_argument(
        "--staging", required=True, type=Path, help="the gitignored staging root"
    )
    parser.add_argument("--ssh", required=True, help="the ssh host (an alias is fine)")
    parser.add_argument(
        "--dest", required=True, type=Path, help="the eval host's data root"
    )
    parser.add_argument(
        "--targets",
        help="comma-separated subset; defaults to every target under --kbs",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="snapshot the target's current directory on the host first",
    )
    parser.add_argument("--dry-run", action="store_true", help="assemble only")
    args = parser.parse_args(argv)

    if args.targets:
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    else:
        targets = sorted(p.name for p in args.kbs.iterdir() if p.is_dir())
    if not targets:
        print("no targets to publish", file=sys.stderr)
        return 2

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="publish-dd-") as tmp:
        workdir = Path(tmp)
        if args.backup and not args.dry_run:
            archive = snapshot(args.ssh, args.dest)
            print(f"snapshot: {args.ssh}:{archive}")
        for target in targets:
            kb_dir = args.kbs / target
            staging_dir = args.staging / target
            try:
                result = publish(
                    target,
                    kb_dir=kb_dir,
                    staging_dir=staging_dir,
                    ssh=args.ssh,
                    dest=args.dest,
                    dry_run=args.dry_run,
                    workdir=workdir,
                )
            except PublishError as failure:
                failures.append(f"{target}: {failure}")
                print(f"FAIL {target}: {failure}", file=sys.stderr)
                continue
            state = "assembled" if args.dry_run else "published"
            print(f"OK   {target}: {result.files} file(s) {state}")
    if failures:
        print(f"\n{len(failures)} target(s) failed; nothing else was published", file=sys.stderr)
        return 1
    if not args.dry_run:
        print(f"\n{len(targets)} target(s) published to {args.ssh}:{args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
