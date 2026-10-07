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
# A record skipped for exceeding a read/scan budget, or a root whose traversal
# exhausted the shared scan budget before it finished. Both path-free.
RUN_RECORD_TOO_LARGE = "run_record_too_large"
RUN_RECORD_SCAN_LIMIT = "run_record_scan_limit"

# The producer's Trial-terminal vocabulary. trial.py assigns complete/blocked/
# timeout/stopped/failed; `_terminal_of` folds the phase terminals through
# FAILED_TERMINALS {failed, interrupted}; the spec names `interrupted` too. Any
# other value (an unknown word, a path, a non-string) is not a producer terminal
# and rejects the record. Named and test-overridable, but read at call time.
TRIAL_TERMINALS = frozenset(
    {"complete", "stopped", "timeout", "failed", "blocked", "interrupted"}
)

# Bounds that keep the reader additive and cheap. A single record is read at
# most up to `RECORD_MAX_BYTES`; one distinct root visits at most
# `SCAN_MAX_ENTRIES` filesystem entries to `SCAN_MAX_DEPTH` levels. All read at
# call time so a test can lower them without a real large fixture.
RECORD_MAX_BYTES = 1024 * 1024
SCAN_MAX_ENTRIES = 10_000
SCAN_MAX_DEPTH = 32

# Only a YAML record can carry the harness's record fields; a stray JSON or a
# directory entry is never mistaken for one.
_YAML_SUFFIXES = (".yaml", ".yml")

# Sentinels: a record that exceeded its byte bound, and a payload that could not
# be read/decoded. Distinct so an oversized file is never confused with a bad one.
_TOO_LARGE = object()
_INVALID = object()


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
    """Every distinct root's records, deduplicated and arbitrated by identity.

    A bind-alias of one directory is collapsed by `_distinct_roots` *before* its
    budget is spent, so listing one physical root twice never doubles the scan.
    A root that exhausts its entry/depth budget, or a record skipped for being
    too large, is reported as a path-free issue while the valid records found
    elsewhere keep their place.
    """
    # `files` is retained for call-site/interface stability; the bounded walk
    # below owns traversal and reading so a FileStore's unbounded reads (and its
    # behavior for every other caller) are never changed for this path.
    found: dict[tuple[str, str, str], list[RunRecord]] = {}
    issues: set[str] = set()
    for root in _distinct_roots(roots):  # type: ignore[arg-type]
        records, limited, too_large = _scan_root(root)
        if limited:
            issues.add(RUN_RECORD_SCAN_LIMIT)
        if too_large:
            issues.add(RUN_RECORD_TOO_LARGE)
        for record in records:
            found.setdefault(record.identity, []).append(record)

    records: dict[tuple[str, str, str], RunRecord] = {}
    ambiguous: list[tuple[str, str, str]] = []
    for identity in sorted(found):
        group = found[identity]
        if len(group) == 1:
            records[identity] = group[0]
        else:
            ambiguous.append(identity)
    if ambiguous:
        issues.add(RUN_RECORD_AMBIGUOUS)
    return RunRecordCatalog(
        records=records, ambiguous=tuple(ambiguous), issues=tuple(sorted(issues))
    )


def _scan_root(root: str | Path) -> tuple[list[RunRecord], bool, bool]:
    """The valid records under one root, plus its scan/oversize flags.

    Traversal itself is bounded: entries are counted as they are visited (files
    and directories alike), a directory below `SCAN_MAX_DEPTH` is never opened,
    and the walk stops the moment `SCAN_MAX_ENTRIES` is reached — it never
    enumerates an unbounded tree and slices the result. Symlinks and special
    files are never followed, and a record that reads past `RECORD_MAX_BYTES`
    is skipped (reported, not silently dropped).
    """
    base = Path(root)
    if not base.is_dir():
        return [], False, False
    real_root = os.path.realpath(str(base))
    records: list[RunRecord] = []
    limited = False
    too_large = False
    exhausted = False
    visited = 0
    # (directory, depth); the root itself is depth 0, its children depth 1.
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack and not exhausted:
        directory, depth = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            continue
        children: list[tuple[Path, int]] = []
        for entry in entries:
            if visited >= SCAN_MAX_ENTRIES:
                limited = True
                exhausted = True
                break
            visited += 1
            # The bound applies to every entry - file or directory - so a deep
            # file is skipped at the depth gate, never read and then discarded.
            # A depth skip is soft: the rest of this directory and its shallower
            # siblings are still scanned, so one deep branch cannot hide a
            # valid record beside it.
            if depth + 1 > SCAN_MAX_DEPTH:
                limited = True
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    children.append((Path(entry.path), depth + 1))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            path = Path(entry.path)
            if path.suffix.lower() not in _YAML_SUFFIXES:
                continue
            # A record whose real path escaped the root (a symlinked parent) is
            # never read, so no external tree is ever exposed.
            if not _is_contained(real_root, path):
                continue
            record = _read_record_file(path)
            if record is _TOO_LARGE:
                too_large = True
                continue
            if record is not None:
                records.append(record)
        for child in reversed(children):
            stack.append(child)
    return records, limited, too_large


def _read_record_file(path: Path) -> RunRecord | object | None:
    """One record read through a bounded byte window.

    The bound is enforced on the bytes actually read (a `RECORD_MAX_BYTES + 1`
    window), never a pre-read stat followed by an unbounded read. Returns the
    record, `_TOO_LARGE`, or `None` for a missing/unreadable/non-record file.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read(RECORD_MAX_BYTES + 1)
    except OSError:
        return None
    if len(raw) > RECORD_MAX_BYTES:
        return _TOO_LARGE
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return _parse_record(payload, path.parent)


def _parse_record(payload: Mapping, directory: Path) -> RunRecord | None:
    """One record, or `None` when it is not an attributable Trial record.

    A spend-only record (identity plus counters, no `terminal`/`phases`) is not
    a Trial. The identity is taken from the validated content, never the name.
    A present-but-invalid `target_run_id` rejects the record rather than being
    reassigned to `instance_id`; the fallback is kept only for an absent key or
    an explicit `None`, matching the producer's own
    `record.get("target_run_id") or instance_id`. The terminal must be one of
    the producer's Trial terminals.
    """
    target_id = _safe_id(payload.get("target_id"))
    trial_id = _safe_id(payload.get("trial_id"))
    target_run_id = _resolve_target_run_id(payload)
    if not target_id or not trial_id or not target_run_id:
        return None
    terminal = payload.get("terminal")
    if not isinstance(terminal, str) or terminal not in TRIAL_TERMINALS:
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
        terminal=terminal,
        phases=tuple(item for item in phases if isinstance(item, Mapping)),
        eval_sha=_safe_id(payload.get("eval_sha")),
        stack_fingerprint=_safe_id(payload.get("stack_fingerprint")),
        directory=directory,
    )


def _resolve_target_run_id(payload: Mapping) -> str | None:
    """The Trial's `target_run_id`, or `None` when the record has no valid one.

    A present non-None value is honoured literally: an invalid one (wrong type,
    empty, path or traversal shaped) rejects the record and is never replaced by
    `instance_id`. Only an absent key or an explicit `None` falls back to the
    (validated) `instance_id`, which is exactly what the producer's
    `record.get("target_run_id") or instance_id` does.
    """
    if "target_run_id" in payload and payload.get("target_run_id") is not None:
        return _safe_id(payload.get("target_run_id"))
    return _safe_id(payload.get("instance_id"))


def _safe_id(value: object) -> str | None:
    """One path-safe, single-segment identifier, or `None`."""
    return value if is_safe_identifier(value) else None


def _is_contained(real_root: str, path: Path) -> bool:
    """Whether `path` is the root or a descendant, after resolving symlinks."""
    real = os.path.realpath(str(path))
    return real == real_root or real.startswith(real_root + os.sep)


__all__ = [
    "RUN_RECORD_AMBIGUOUS",
    "RUN_RECORD_SCAN_LIMIT",
    "RUN_RECORD_TOO_LARGE",
    "RECORD_MAX_BYTES",
    "SCAN_MAX_DEPTH",
    "SCAN_MAX_ENTRIES",
    "TRIAL_TERMINALS",
    "RunRecord",
    "RunRecordCatalog",
    "load_run_record_catalog",
]
