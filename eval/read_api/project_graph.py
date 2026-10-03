"""Manifest-backed historical project-graph reader (real eval project artifacts).

A completed Trial captures its L0/L1 graph once, beside `trial.yaml`, before
the instance can be torn down. This module serves those immutable bytes for the
dashboard: it resolves one Trial by its full identity below the configured
store, requires the atomic schema-v2 project snapshot, reads the fixed
`project-graph.json` filename named by the manifest (never a client path),
verifies the recorded SHA-256, and normalizes the decoded `GraphData`.

It never proxies, imports, or falls back to the operational project API. Every
failure is a coded, path-free error: unknown Trial is a 404; an unavailable or
historical snapshot, a missing file, and a digest disagreement are 409s with
stable codes. Import performs no I/O.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from orchestrator.project_graph import (
    PROJECT_GRAPH_FILENAME,
    ProjectGraphError,
    normalize_project_graph,
)

MANIFEST_FILENAME = "run-manifest.yaml"
STORE_SCHEMA_VERSION = 2

TRIAL_NOT_FOUND = "trial_not_found"
PROJECT_GRAPH_UNAVAILABLE = "project_graph_unavailable"
PROJECT_GRAPH_INVALID = "project_graph_invalid"
PROJECT_GRAPH_DIGEST_MISMATCH = "project_graph_digest_mismatch"

_PATH_SEPARATORS = ("/", "\\", "\x00")


class HistoricalProjectGraphError(RuntimeError):
    """A coded, path-free project-graph lookup failure.

    `code` is the safe HTTP `detail`; `status_code` is the mapped HTTP status.
    The message is the code itself, so no filesystem or manifest detail leaks.
    """

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def read_project_graph(
    store: str | Path,
    target_id: str,
    target_run_id: str,
    trial_id: str,
) -> dict[str, Any]:
    """The historical graph wrapper for one fully-identified Trial."""
    trial_dir = _resolve_trial(store, target_id, target_run_id, trial_id)
    manifest = _load_manifest(trial_dir)
    project_id, graph_meta = _require_available_snapshot(manifest)
    graph_bytes = _read_graph_bytes(trial_dir, graph_meta)
    graph = _decode_graph(graph_bytes, project_id)
    return {
        "status": "available",
        "captured_at": graph_meta["captured_at"],
        "sha256": graph_meta["sha256"],
        "graph": graph,
    }


def _resolve_trial(
    store: str | Path,
    target_id: str,
    target_run_id: str,
    trial_id: str,
) -> Path:
    """The Trial directory for the full identity, or a path-free 404/409."""
    if not all(
        _is_safe_segment(part) for part in (target_id, target_run_id, trial_id)
    ):
        # A path-like identifier can never name a real Trial.
        raise _error(TRIAL_NOT_FOUND, 404)
    root = Path(store)
    trial_dir = root / target_id / target_run_id / trial_id
    if not _is_within(root, trial_dir):
        # A symlinked ancestor resolved outside the store: a broken store, not
        # a missing Trial.
        raise _error(PROJECT_GRAPH_INVALID, 409)
    if not trial_dir.is_dir():
        raise _error(TRIAL_NOT_FOUND, 404)
    return trial_dir


def _load_manifest(trial_dir: Path) -> Mapping:
    manifest_path = trial_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise _error(PROJECT_GRAPH_UNAVAILABLE, 409)
    try:
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    if not isinstance(payload, Mapping):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    return payload


def _require_available_snapshot(manifest: Mapping) -> tuple[str, Mapping]:
    """The manifest's project id and graph metadata, when the snapshot is atomic."""
    if manifest.get("schema_version") != STORE_SCHEMA_VERSION:
        # Schema-v1 (or unversioned) Trials never captured a project snapshot.
        raise _error(PROJECT_GRAPH_UNAVAILABLE, 409)

    snapshot = manifest.get("project_snapshot")
    artifacts = manifest.get("project_artifacts")
    graph = manifest.get("project_graph")
    sections = (snapshot, artifacts, graph)
    if not all(
        isinstance(section, Mapping) and section.get("status") == "available"
        for section in sections
    ):
        # Atomic availability: graph, inventory, and snapshot share one state.
        raise _error(PROJECT_GRAPH_UNAVAILABLE, 409)

    project_id = manifest.get("project_id")
    if not _is_text(project_id):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    if any(section.get("project_id") != project_id for section in sections):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    captured_at = graph.get("captured_at")
    if not _is_text(captured_at) or any(
        section.get("captured_at") != captured_at for section in (snapshot, artifacts)
    ):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    if not _is_text(graph.get("sha256")):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    return project_id, graph


def _read_graph_bytes(trial_dir: Path, graph_meta: Mapping) -> bytes:
    """The immutable graph bytes, verified against the recorded digest."""
    graph_path = trial_dir / PROJECT_GRAPH_FILENAME
    if graph_path.is_symlink():
        raise _error(PROJECT_GRAPH_INVALID, 409)
    if not _is_within(trial_dir, graph_path):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    if not graph_path.is_file():
        # Absent (or a special file): a missing capture, never a client path.
        raise _error(PROJECT_GRAPH_UNAVAILABLE, 409)
    try:
        data = graph_path.read_bytes()
    except OSError:
        raise _error(PROJECT_GRAPH_UNAVAILABLE, 409)
    if hashlib.sha256(data).hexdigest() != graph_meta["sha256"]:
        raise _error(PROJECT_GRAPH_DIGEST_MISMATCH, 409)
    return data


def _decode_graph(graph_bytes: bytes, project_id: str) -> dict:
    """Strict UTF-8 JSON decoded and normalized through the shared GraphData rules."""
    try:
        payload = json.loads(graph_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _error(PROJECT_GRAPH_INVALID, 409)
    try:
        return normalize_project_graph(payload, project_id=project_id)
    except ProjectGraphError:
        raise _error(PROJECT_GRAPH_INVALID, 409)


def _is_safe_segment(segment: object) -> bool:
    """One path-safe segment: no separators, no `.`/`..`, no NUL/control chars."""
    if not isinstance(segment, str) or not segment or segment in (".", ".."):
        return False
    if any(char in segment for char in _PATH_SEPARATORS):
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in segment)


def _is_within(root: str | Path, path: str | Path) -> bool:
    """True when `path` resolves to `root` or a descendant of it."""
    root_resolved = Path(root).resolve()
    candidate = Path(path).resolve()
    return candidate == root_resolved or root_resolved in candidate.parents


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _error(code: str, status_code: int) -> HistoricalProjectGraphError:
    return HistoricalProjectGraphError(code, status_code)


__all__ = [
    "HistoricalProjectGraphError",
    "MANIFEST_FILENAME",
    "PROJECT_GRAPH_DIGEST_MISMATCH",
    "PROJECT_GRAPH_INVALID",
    "PROJECT_GRAPH_UNAVAILABLE",
    "TRIAL_NOT_FOUND",
    "read_project_graph",
]
