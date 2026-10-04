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
from .resolved import TrialContext

TRIAL_SNAPSHOT = "trial_snapshot"
PROJECT_STORAGE = "project_storage"

REASON_NO_PROJECT = "project_id_unavailable"
REASON_NOT_ELIGIBLE = "instance_not_eligible"
REASON_DATA_ROOT_UNAVAILABLE = "project_data_unavailable"

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


def resolve_inventory(
    store: str | Path | None,
    project_data_root: str | Path | None,
    context: TrialContext,
    *,
    files: FileStore,
) -> ResolvedInventory:
    """Pick the captured schema-v2 inventory, else the raw project storage."""
    fallback_reason: str | None = None
    if store:
        try:
            trial_dir = artifact_reader._resolve_trial(
                store, context.target_id, context.target_run_id, context.trial_id
            )
            project_id, entries = artifact_reader._load_inventory(
                trial_dir, require_coherent=True
            )
        except ArtifactLookupError as exc:
            # A missing, unavailable, unsafe, or digest-inconsistent capture is
            # never served; the strict endpoint remains the integrity report.
            fallback_reason = exc.code
        else:
            return ResolvedInventory(
                status="available",
                source=TRIAL_SNAPSHOT,
                project_id=project_id,
                root=trial_dir / project_id,
                entries=tuple(entries),
                reason=None,
                fallback_reason=None,
            )

    return _project_storage(project_data_root, context, files, fallback_reason)


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
    entries = tuple(artifact.as_manifest_entry() for artifact in collected)
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
    return artifact_reader._detail_body(inventory.root, entry, content_url=content_url)


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
    return artifact_reader._download(inventory.root, entry)


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
