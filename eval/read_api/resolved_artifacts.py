"""Resolved Hunting/Skill artifacts behind one contract (unified workspace).

The resolved layer prefers the immutable schema-v2 inventory a Trial captured
beside its manifest, and otherwise collects the allowlisted files beneath the
Trial's ``project_id`` in the read-only project data root. It reuses
``orchestrator.project_artifacts.collect_project_artifacts`` - never a second
walker - and reuses the strict renderer in ``artifacts.py`` for grouping,
preview, and streaming.

Everything is validated the same way as the strict endpoint: allowlist,
containment, regular-file status, symlink absence, size, and SHA-256. A file
resolved from a detail response carries its digest into the content URL, so a
detail-to-content change is rejected rather than served. Failures are coded,
path-free ``ArtifactLookupError``s; import performs no I/O.
"""
from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from orchestrator.files import FileStore
from orchestrator.project_artifacts import (
    ProjectArtifactError,
    collect_project_artifacts,
)

from . import artifacts as artifact_reader
from .artifacts import (
    ARTIFACT_DIGEST_MISMATCH,
    ARTIFACT_NOT_FOUND,
    ArtifactDownload,
    ArtifactLookupError,
)
from .resolved import TrialContext, is_safe_identifier

TRIAL_SNAPSHOT = "trial_snapshot"
PROJECT_STORAGE = "project_storage"

REASON_NO_PROJECT = "project_id_unavailable"
REASON_NOT_ELIGIBLE = "instance_not_eligible"
REASON_DATA_ROOT_UNAVAILABLE = "project_data_unavailable"
# Stable, path-free reasons a stored v1 capture cannot be served.
REASON_MANIFEST_MISSING = "manifest_missing"
REASON_MANIFEST_INVALID = "manifest_invalid"
REASON_MANIFEST_UNREADABLE = "manifest_unreadable"
REASON_MANIFEST_TOO_LARGE = "manifest_too_large"
REASON_IDENTITY_MISMATCH = "trial_identity_mismatch"
REASON_PROJECT_MISMATCH = "project_id_mismatch"
# A symlink, special file or out-of-root manifest is never read.
REASON_MANIFEST_UNSAFE = "artifact_unsafe"

# The bounded manifest read: the bytes actually read, never a full read.
MANIFEST_MAX_BYTES = 1024 * 1024

# Per-entry provenance: a file copied into the Trial tree, or one read from the
# current project root. Additive; every resolved entry carries one.
ORIGIN_CAPTURED = "captured"
ORIGIN_CURRENT = "current"

# A v2 manifest keeps the schema-v2 capture path; anything else may still be a
# v1 store tree (v1 is the producer's definitive contract and needs no schema
# equality check to be admitted).
_STORE_SCHEMA_V2 = 2
# A stored tree that exists but is missing, mismatched or unsafe fails closed
# instead of silently reading the current project as if it were the capture.
_HARD_STORE_FAILURES = frozenset(
    {
        REASON_MANIFEST_MISSING,
        REASON_MANIFEST_INVALID,
        REASON_MANIFEST_UNREADABLE,
        REASON_MANIFEST_TOO_LARGE,
        REASON_IDENTITY_MISMATCH,
        REASON_PROJECT_MISMATCH,
        "artifact_unsafe",
        "artifact_unreadable",
    }
)

# A soft reason when a non-v2 manifest simply has no copied project subtree:
# matches the code the v2 loader used to raise for a non-v2 schema.
_NO_CAPTURE_REASON = artifact_reader.ARTIFACTS_UNAVAILABLE

_MANIFEST_FILENAME = artifact_reader.MANIFEST_FILENAME


@dataclass(frozen=True)
class ResolvedInventory:
    """One resolved artifact source: safe wire metadata plus a trusted root.

    ``root`` is the internal directory every ``relative_path`` resolves
    against; it is never serialized. ``entries`` are manifest-shaped mappings,
    already validated by the shared renderer.
    """

    status: str
    source: str
    project_id: str | None
    root: Path | None = field(repr=False)
    entries: tuple[dict[str, Any], ...]
    reason: str | None
    fallback_reason: str | None
    # Per-artifact internal read root, for a mixed capture+current inventory.
    # Never serialized; an entry without an explicit root uses `root`.
    roots: Mapping[str, Path] = field(default_factory=dict, repr=False, compare=False)
    # Path-free issues from a source that could not be read (never serialized as
    # a path). Additive; the stored capture survives them.
    issues: tuple[Mapping[str, str], ...] = ()


def _capture(project_id: str, root: Path, entries: tuple[dict[str, Any], ...]) -> ResolvedInventory:
    return ResolvedInventory(
        status="available",
        source=TRIAL_SNAPSHOT,
        project_id=project_id,
        root=root,
        entries=entries,
        reason=None,
        fallback_reason=None,
    )


def _with_origin(entries, origin: str) -> tuple[dict[str, Any], ...]:
    return tuple({**entry, "origin": origin} for entry in entries)


def resolve_inventory(
    store: str | Path | None,
    project_data_root: str | Path | None,
    context: TrialContext,
    *,
    files: FileStore,
) -> ResolvedInventory:
    """Pick the Trial's stored capture (v2 snapshot or v1 store), else raw.

    A v2 capture keeps its immutable inventory. Otherwise a non-v2 manifest with
    a copied `<project_id>/` subtree is read as the producer's definitive v1
    store: its saved files are the historical capture. When the raw project is
    also eligible, its files are merged per exact relative path with the stored
    copy winning; current-only files are labelled `current`.
    """
    store_reason: str | None = None
    if store:
        try:
            trial_dir = artifact_reader._resolve_trial(
                store, context.target_id, context.target_run_id, context.trial_id
            )
        except ArtifactLookupError as exc:
            store_reason = exc.code
        else:
            capture, store_reason, merge_current = _read_store_capture(
                trial_dir, context, files
            )
            if capture is not None:
                if not merge_current:
                    return capture
                return _merge_with_current(capture, project_data_root, context, files)
            if store_reason in _HARD_STORE_FAILURES:
                return _unavailable(context.project_id, store_reason, None)

    return _project_storage(project_data_root, context, files, store_reason)


def _read_store_capture(
    trial_dir: Path, context: TrialContext, files: FileStore
) -> tuple[ResolvedInventory | None, str, bool]:
    """The Trial's own stored inventory, or `(None, reason)` when unusable.

    The v2 snapshot wins first. A v1 (non-schema-2) manifest's identity and
    project are validated against the resolved context, then the copied
    `<project_id>/` subtree is collected. `reason` is a soft fallback code when
    the store simply holds no readable capture, and a hard code when the stored
    tree exists but is missing, mismatched or unsafe.

    The third element is whether current-only raw files may be merged in: true
    only for the v1 store capture, so a v2 snapshot stays capture-only.
    """
    # The manifest is validated - regular, contained, non-symlink, bounded -
    # before any loader can touch it, so a symlinked or oversized file is never
    # read and a malformed one is named, not silently reported missing.
    manifest, manifest_reason = _read_manifest_bounded(trial_dir)
    if manifest is None:
        return None, manifest_reason, False

    if manifest.get("schema_version") == _STORE_SCHEMA_V2:
        try:
            project_id, entries = artifact_reader._load_inventory(
                trial_dir, require_coherent=True, manifest=manifest
            )
        except ArtifactLookupError as exc:
            return None, exc.code, False
        root = trial_dir / project_id
        return _capture(project_id, root, _with_origin(entries, ORIGIN_CAPTURED)), "", False

    identity = _manifest_identity(manifest)
    expected = (context.target_id, context.target_run_id, context.trial_id)
    if identity != expected:
        return None, REASON_IDENTITY_MISMATCH, False
    project_id = manifest.get("project_id")
    if not is_safe_identifier(project_id):
        return None, REASON_MANIFEST_INVALID, False
    if context.project_id is not None and project_id != context.project_id:
        return None, REASON_PROJECT_MISMATCH, False
    project_root = trial_dir / project_id
    # A symlinked subtree is unsafe even when its target is missing (an
    # is_dir-only check would treat a broken link as "no store capture").
    if files.is_symlink(project_root):
        return None, REASON_MANIFEST_UNSAFE, False
    if not files.is_dir(project_root):
        # A v1 manifest with no copied subtree is not a store capture.
        return None, _NO_CAPTURE_REASON, False
    try:
        collected = collect_project_artifacts(trial_dir, project_id, files=files)
    except ProjectArtifactError as exc:
        return None, exc.failure, False
    entries = _with_origin(
        (artifact.as_manifest_entry() for artifact in collected), ORIGIN_CAPTURED
    )
    return _capture(project_id, project_root, entries), "", True


def _read_manifest_bounded(trial_dir: Path) -> tuple[Mapping | None, str | None]:
    """The manifest mapping, or `(None, reason)`; never reads a symlink/special.

    The file is checked with `lstat` (so a symlink is rejected without being
    followed), bounded to `MANIFEST_MAX_BYTES` on the bytes actually read, and
    parsed from those bytes: invalid UTF-8 or YAML is `manifest_invalid`, never
    an unhandled crash or a mislabelled `manifest_missing`.
    """
    path = trial_dir / _MANIFEST_FILENAME
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, REASON_MANIFEST_MISSING
    except OSError:
        return None, REASON_MANIFEST_UNREADABLE
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None, REASON_MANIFEST_UNSAFE
    if not _manifest_contained(trial_dir, path):
        return None, REASON_MANIFEST_UNSAFE
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MANIFEST_MAX_BYTES + 1)
    except OSError:
        return None, REASON_MANIFEST_UNREADABLE
    if len(raw) > MANIFEST_MAX_BYTES:
        return None, REASON_MANIFEST_TOO_LARGE
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return None, REASON_MANIFEST_INVALID
    if not isinstance(payload, Mapping):
        return None, REASON_MANIFEST_INVALID
    return payload, None


def _manifest_contained(trial_dir: Path, path: Path) -> bool:
    """Whether the manifest's real path stays inside the Trial directory."""
    real = os.path.realpath(str(path))
    root = os.path.realpath(str(trial_dir))
    return real == root or real.startswith(root + os.sep)


def _manifest_identity(manifest: Mapping) -> tuple[str, str, str] | None:
    target_id = manifest.get("target_id")
    trial_id = manifest.get("trial_id")
    target_run_id = manifest.get("target_run_id") or manifest.get("instance_id")
    if not all(is_safe_identifier(part) for part in (target_id, target_run_id, trial_id)):
        return None
    return (target_id, target_run_id, trial_id)


def _merge_with_current(
    capture: ResolvedInventory,
    project_data_root: str | Path | None,
    context: TrialContext,
    files: FileStore,
) -> ResolvedInventory:
    """Merge current-only raw files into a stored capture (stored copy wins).

    A current-source failure is never swallowed: the safe capture is kept and a
    path-free issue is attached, so the wire says the stored artifacts are the
    readable ones rather than silently claiming a complete inventory.
    """
    current = _collect_current(project_data_root, context, files)
    if current.reason is not None:
        return _with_issue(capture, current.reason)
    if current.entries is None or current.root is None:
        # Ineligible/unconfigured source: not an error, nothing to merge.
        return capture
    current_entries, current_root = current.entries, current.root
    merged: dict[str, dict[str, Any]] = {
        entry["relative_path"]: entry for entry in capture.entries
    }
    roots: dict[str, Path] = {}
    if capture.root is not None:
        for entry in capture.entries:
            roots[entry["artifact_id"]] = capture.root
    added = False
    for entry in current_entries:
        if entry["relative_path"] in merged:
            continue
        merged[entry["relative_path"]] = entry
        roots[entry["artifact_id"]] = current_root
        added = True
    if not added:
        return capture
    ordered = tuple(merged[path] for path in sorted(merged))
    return ResolvedInventory(
        status="available",
        source=capture.source,
        project_id=capture.project_id,
        root=capture.root,
        entries=ordered,
        reason=None,
        fallback_reason=capture.fallback_reason,
        roots=roots,
        issues=capture.issues,
    )


@dataclass(frozen=True)
class _CurrentSource:
    """The outcome of reading the current project root.

    `entries is None and reason is None` means the source did not apply (no
    project id, an ineligible instance, or an unconfigured root); a non-None
    `reason` is a path-free failure the caller reports as an issue.
    """

    entries: tuple[dict[str, Any], ...] | None
    root: Path | None
    reason: str | None


def _collect_current(
    project_data_root: str | Path | None, context: TrialContext, files: FileStore
) -> _CurrentSource:
    project_id = context.project_id
    if project_id is None or not context.fallback_eligible or not project_data_root:
        return _CurrentSource(None, None, None)
    root = Path(project_data_root)
    if not files.is_dir(root):
        # A configured-but-missing/unreadable root is not the normal empty project.
        return _CurrentSource(None, None, REASON_DATA_ROOT_UNAVAILABLE)
    try:
        collected = collect_project_artifacts(root, project_id, files=files)
    except ProjectArtifactError as exc:
        return _CurrentSource(None, None, exc.failure)
    entries = _with_origin(
        (artifact.as_manifest_entry() for artifact in collected), ORIGIN_CURRENT
    )
    return _CurrentSource(entries, root / project_id, None)


def _with_issue(inventory: ResolvedInventory, reason: str) -> ResolvedInventory:
    """The same inventory plus one `project_storage` issue (idempotent)."""
    issue = {"source": PROJECT_STORAGE, "reason": reason}
    if issue in inventory.issues:
        return inventory
    return replace(inventory, issues=(*inventory.issues, issue))


def _project_storage(
    project_data_root: str | Path | None,
    context: TrialContext,
    files: FileStore,
    fallback_reason: str | None,
) -> ResolvedInventory:
    project_id = context.project_id
    if project_id is None:
        return _unavailable(None, REASON_NO_PROJECT, fallback_reason)
    if not context.fallback_eligible:
        return _unavailable(project_id, REASON_NOT_ELIGIBLE, fallback_reason)
    if not project_data_root:
        return _unavailable(project_id, REASON_DATA_ROOT_UNAVAILABLE, fallback_reason)
    if not files.is_dir(Path(project_data_root)):
        # Configured but absent/unreadable: an explicit reason, not an empty success.
        return _unavailable(project_id, REASON_DATA_ROOT_UNAVAILABLE, fallback_reason)
    try:
        collected = collect_project_artifacts(project_data_root, project_id, files=files)
    except ProjectArtifactError as exc:
        return _unavailable(project_id, exc.failure, fallback_reason)
    entries = _with_origin(
        (artifact.as_manifest_entry() for artifact in collected), ORIGIN_CURRENT
    )
    return ResolvedInventory(
        status="available",
        source=PROJECT_STORAGE,
        project_id=project_id,
        root=Path(project_data_root) / project_id,
        entries=entries,
        reason=None,
        fallback_reason=fallback_reason,
    )


def _unavailable(
    project_id: str | None, reason: str, fallback_reason: str | None
) -> ResolvedInventory:
    return ResolvedInventory(
        status="unavailable",
        source=PROJECT_STORAGE,
        project_id=project_id,
        root=None,
        entries=(),
        reason=reason,
        fallback_reason=fallback_reason,
    )


def inventory_response(
    inventory: ResolvedInventory,
    target_id: str,
    target_run_id: str,
    trial_id: str,
) -> dict[str, Any]:
    """The resolved inventory wire body (never carries a trusted root)."""
    body: dict[str, Any] = {
        "status": inventory.status,
        "source": inventory.source,
        "project_id": inventory.project_id,
        "fallback_reason": inventory.fallback_reason,
        # Path-free issues from a source that could not be read; additive, so an
        # older client ignores an empty list.
        "issues": [dict(issue) for issue in inventory.issues],
        "groups": [],
    }
    if inventory.status == "available":
        body["groups"] = artifact_reader._build_groups(list(inventory.entries))
    else:
        body["reason"] = inventory.reason
    return body


def detail_response(
    inventory: ResolvedInventory,
    target_id: str,
    target_run_id: str,
    trial_id: str,
    artifact_id: object,
) -> dict[str, Any]:
    """Metadata plus one bounded preview for one inventory-issued artifact id."""
    entry = _require_entry(inventory, artifact_id)
    content_url = _content_url(
        target_id, target_run_id, trial_id, entry["artifact_id"], entry["sha256"]
    )
    return artifact_reader._detail_body(
        _entry_root(inventory, entry), entry, content_url=content_url
    )


def content_download(
    inventory: ResolvedInventory,
    artifact_id: object,
    expected_sha256: object,
) -> ArtifactDownload:
    """A bounded stream whose bytes must match the digest the detail returned."""
    entry = _require_entry(inventory, artifact_id)
    if not isinstance(expected_sha256, str) or expected_sha256 != entry["sha256"]:
        # The inventory is a view of current project storage: a change between
        # detail and content is rejected rather than serving unverified bytes.
        raise ArtifactLookupError(ARTIFACT_DIGEST_MISMATCH, 409)
    return artifact_reader._download(_entry_root(inventory, entry), entry)


def _entry_root(inventory: ResolvedInventory, entry: Mapping) -> Path:
    """The trusted read root for one entry (a mixed inventory has several)."""
    root = inventory.roots.get(entry["artifact_id"], inventory.root)
    if root is None:
        raise ArtifactLookupError(REASON_DATA_ROOT_UNAVAILABLE, 409)
    return root


def _require_entry(inventory: ResolvedInventory, artifact_id: object) -> Mapping:
    if inventory.status != "available" or inventory.root is None:
        raise ArtifactLookupError(
            inventory.reason or REASON_DATA_ROOT_UNAVAILABLE, 409
        )
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ArtifactLookupError(ARTIFACT_NOT_FOUND, 404)
    for entry in inventory.entries:
        if entry["artifact_id"] == artifact_id:
            return entry
    raise ArtifactLookupError(ARTIFACT_NOT_FOUND, 404)


def _content_url(
    target_id: str,
    target_run_id: str,
    trial_id: str,
    artifact_id: str,
    sha256: str,
) -> str:
    return (
        "/trials/{}/{}/{}/resolved-artifacts/{}/content?expected_sha256={}".format(
            quote(target_id, safe=""),
            quote(target_run_id, safe=""),
            quote(trial_id, safe=""),
            quote(artifact_id, safe=""),
            quote(sha256, safe=""),
        )
    )


__all__ = [
    "PROJECT_STORAGE",
    "ResolvedInventory",
    "TRIAL_SNAPSHOT",
    "content_download",
    "detail_response",
    "inventory_response",
    "resolve_inventory",
]
