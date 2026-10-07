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

from collections.abc import Mapping
from dataclasses import dataclass, field
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
REASON_IDENTITY_MISMATCH = "trial_identity_mismatch"
REASON_PROJECT_MISMATCH = "project_id_mismatch"

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
        REASON_IDENTITY_MISMATCH,
        REASON_PROJECT_MISMATCH,
        "artifact_unsafe",
        "artifact_unreadable",
    }
)

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
    try:
        project_id, entries = artifact_reader._load_inventory(
            trial_dir, require_coherent=True
        )
    except ArtifactLookupError as exc:
        v2_reason = exc.code
    else:
        root = trial_dir / project_id
        return _capture(project_id, root, _with_origin(entries, ORIGIN_CAPTURED)), "", False

    manifest = _load_manifest(trial_dir)
    if manifest is None:
        return None, REASON_MANIFEST_MISSING, False
    if manifest.get("schema_version") == _STORE_SCHEMA_V2:
        return None, v2_reason, False
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
    if not files.is_dir(project_root):
        # A v1 manifest with no copied subtree is not a store capture.
        return None, v2_reason, False
    try:
        collected = collect_project_artifacts(trial_dir, project_id, files=files)
    except ProjectArtifactError as exc:
        return None, exc.failure, False
    entries = _with_origin(
        (artifact.as_manifest_entry() for artifact in collected), ORIGIN_CAPTURED
    )
    return _capture(project_id, project_root, entries), "", True


def _load_manifest(trial_dir: Path) -> Mapping | None:
    path = trial_dir / _MANIFEST_FILENAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return payload if isinstance(payload, Mapping) else None


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
    """Merge current-only raw files into a stored capture (stored copy wins)."""
    current = _collect_current(project_data_root, context, files)
    if current is None:
        return capture
    current_entries, current_root = current
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
    )


def _collect_current(
    project_data_root: str | Path | None, context: TrialContext, files: FileStore
) -> tuple[tuple[dict[str, Any], ...], Path] | None:
    project_id = context.project_id
    if project_id is None or not context.fallback_eligible or not project_data_root:
        return None
    try:
        collected = collect_project_artifacts(project_data_root, project_id, files=files)
    except ProjectArtifactError:
        # A broken current tree must never hide the Trial's stored capture.
        return None
    entries = _with_origin(
        (artifact.as_manifest_entry() for artifact in collected), ORIGIN_CURRENT
    )
    return entries, Path(project_data_root) / project_id


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
