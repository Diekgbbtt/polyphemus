"""Authoritative Trial records in the read-only runs roots (#unmaterialized).

The materialized store is only one source. The harness also writes each finished
Trial's authoritative record (its ``trial.yaml``) under the configured runs
roots - arbitrary YAML names in arbitrary directories - and a Trial that timed
out before the materializer copied it must still be catalogueable, navigable
and honest about the results it does not have.

This module only *discovers and validates* those records: it walks the distinct
roots (dropping a bind-alias of one directory by its `(st_dev, st_ino)`), reads
the identity from the record *content* rather than its filename, and keeps a
record only when it carries a usable `(target_id, target_run_id, trial_id)` plus
a `terminal` and a `phases` list. Two physically distinct records that share one
identity are never arbitrated: the identity is reported as ambiguous instead.

The reader is total and fail-closed: a symlink or special file is never
followed, one malformed record never hides its valid siblings, and no host path
ever reaches the projected Trial. Import performs no I/O.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from orchestrator.files import FileStore

from .resolved import is_safe_identifier
from .trial_spend import _distinct_roots

# The catalogue issue a physically ambiguous identity is reported under. A
# path-free code, additive to the valid Trials, never a host location.
RUN_RECORD_AMBIGUOUS = "run_record_ambiguous"

# Only a YAML record can carry the harness's record fields; a stray JSON or a
# directory entry is never mistaken for one.
_YAML_SUFFIXES = (".yaml", ".yml")


@dataclass(frozen=True)
class RunRecord:
    """One validated authoritative record, with its trusted internal directory."""

    target_id: str
    target_run_id: str
    trial_id: str
    project_id: str | None
    instance_id: str | None
    start_phase: str | None
    terminal: str | None
    phases: tuple[Mapping, ...]
    eval_sha: str | None
    stack_fingerprint: str | None
    # The directory the record - and, beside it, any verdicts/diagnoses - lives
    # in. It is internal and never serialized.
    directory: Path = field(repr=False, compare=False)

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.target_id, self.target_run_id, self.trial_id)


@dataclass(frozen=True)
class RunRecordCatalog:
    """The unique records, the ambiguous identities, and their path-free issues."""

    records: Mapping[tuple[str, str, str], RunRecord]
    ambiguous: tuple[tuple[str, str, str], ...]
    issues: tuple[str, ...]

    def __contains__(self, identity: object) -> bool:
        return identity in self.records


def load_run_record_catalog(
    roots: object, *, files: FileStore | None = None
) -> RunRecordCatalog:
    """Every distinct root's records, deduplicated and arbitrated by identity."""
    store = files or FileStore()
    found: dict[tuple[str, str, str], list[RunRecord]] = {}
    for root in _distinct_roots(roots):  # type: ignore[arg-type]
        for record in _read_root(root, store):
            found.setdefault(record.identity, []).append(record)

    records: dict[tuple[str, str, str], RunRecord] = {}
    ambiguous: list[tuple[str, str, str]] = []
    for identity in sorted(found):
        group = found[identity]
        if len(group) == 1:
            records[identity] = group[0]
        else:
            ambiguous.append(identity)
    issues = (RUN_RECORD_AMBIGUOUS,) if ambiguous else ()
    return RunRecordCatalog(records=records, ambiguous=tuple(ambiguous), issues=issues)


def _read_root(root: str | Path, files: FileStore):
    """Every valid record under `root` (missing/unreadable root -> nothing)."""
    base = Path(root)
    if not base.is_dir():
        return
    real_root = os.path.realpath(str(base))
    for path in files.walk_regular_files(base):
        if path.suffix.lower() not in _YAML_SUFFIXES:
            continue
        # A record whose real path escaped the configured root (a symlinked
        # parent directory) is never read, so no external tree is ever exposed.
        if not _is_contained(real_root, path):
            continue
        try:
            payload = yaml.safe_load(files.read_text(path))
        except (yaml.YAMLError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        record = _parse_record(payload, path.parent)
        if record is not None:
            yield record


def _parse_record(payload: Mapping, directory: Path) -> RunRecord | None:
    """One record, or `None` when it is not an attributable Trial record.

    A spend-only record (identity plus counters, no `terminal`/`phases`) is not
    a Trial. The identity is taken from the validated content, never the name.
    """
    target_id = _safe_id(payload.get("target_id"))
    trial_id = _safe_id(payload.get("trial_id"))
    target_run_id = _safe_id(payload.get("target_run_id")) or _safe_id(
        payload.get("instance_id")
    )
    if not target_id or not trial_id or not target_run_id:
        return None
    terminal = payload.get("terminal")
    if not isinstance(terminal, str) or not terminal.strip():
        return None
    phases = payload.get("phases")
    if not isinstance(phases, list):
        return None
    return RunRecord(
        target_id=target_id,
        target_run_id=target_run_id,
        trial_id=trial_id,
        project_id=_safe_id(payload.get("project_id")),
        instance_id=_safe_id(payload.get("instance_id")),
        start_phase=_safe_id(payload.get("start_phase")),
        terminal=terminal.strip(),
        phases=tuple(item for item in phases if isinstance(item, Mapping)),
        eval_sha=_safe_id(payload.get("eval_sha")),
        stack_fingerprint=_safe_id(payload.get("stack_fingerprint")),
        directory=directory,
    )


def _safe_id(value: object) -> str | None:
    """One path-safe, single-segment identifier, or `None`."""
    return value if is_safe_identifier(value) else None


def _is_contained(real_root: str, path: Path) -> bool:
    """Whether `path` is the root or a descendant, after resolving symlinks."""
    real = os.path.realpath(str(path))
    return real == real_root or real.startswith(real_root + os.sep)


__all__ = [
    "RUN_RECORD_AMBIGUOUS",
    "RunRecord",
    "RunRecordCatalog",
    "load_run_record_catalog",
]
