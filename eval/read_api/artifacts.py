"""Manifest-backed inventory, detail, and streamed raw content (Task 6).

Everything is served exclusively from an available, immutable schema-v2 project
snapshot: the artifact id resolves only through the manifest inventory, never
as a filesystem path, and every detail/content request re-validates the
allowlist, containment, regular-file status, symlink absence, recorded size, and
SHA-256 before a byte is exposed. Preview reads are bounded (512 KiB for text;
`yaml.safe_load` only up to 2 MiB) and raw content streams in bounded chunks.

Errors are path-free codes only; import performs no I/O.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime, time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from orchestrator.project_artifacts import classify_artifact

MANIFEST_FILENAME = "run-manifest.yaml"
STORE_SCHEMA_VERSION = 2

MAX_PREVIEW_BYTES = 512 * 1024
MAX_YAML_BYTES = 2 * 1024 * 1024
CHUNK_SIZE = 64 * 1024

TRIAL_NOT_FOUND = "trial_not_found"
ARTIFACT_NOT_FOUND = "artifact_not_found"
ARTIFACT_MISSING = "artifact_missing"
ARTIFACT_DIGEST_MISMATCH = "artifact_digest_mismatch"
ARTIFACT_UNSAFE = "artifact_unsafe"
ARTIFACTS_UNAVAILABLE = "project_artifacts_unavailable"
SNAPSHOT_UNAVAILABLE = "project_snapshot_unavailable"

_ENTRY_FIELDS = (
    "artifact_id",
    "category",
    "kind",
    "relative_path",
    "media_type",
    "size_bytes",
    "sha256",
    "representation",
)
_CATEGORIES = ("hunting", "skill")
_HUNT_KINDS = ("hunt_config", "test_spec", "pod_variant", "experiment_log", "pod_export")
_SKILL_KINDS = ("skill_procedure", "skill_reference", "skill_script", "skill_asset")
_REPRESENTATIONS = ("yaml", "markdown", "text", "binary")
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
# A strict RFC 7230 media-type token: no control characters, CR, or LF.
_MEDIA_TYPE = re.compile(
    r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+$"
)
# Media types that may execute or render when opened directly in a browser.
_ACTIVE_MEDIA_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "application/xml",
        "text/xml",
        "text/javascript",
        "application/javascript",
    }
)


class _UnsupportedYamlValue(Exception):
    """A parsed YAML value that cannot be represented as deterministic JSON."""


class ArtifactLookupError(RuntimeError):
    """A coded, path-free artifact lookup failure. `code` is the HTTP detail."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ArtifactDownload:
    """One raw artifact stream: safe filename, media type, size, and chunks."""

    filename: str
    media_type: str
    size_bytes: int
    chunks: Iterator[bytes] = field(repr=False)
    attachment: bool = True


@dataclass
class _Group:
    key: str
    label: str
    category: str
    entries: list[dict] = field(default_factory=list)
    children: dict[str, "_Group"] = field(default_factory=dict)


def list_artifacts(
    store: str | Path, target_id: str, target_run_id: str, trial_id: str
) -> dict[str, Any]:
    """The grouped inventory of one fully-identified, available Trial snapshot."""
    trial_dir = _resolve_trial(store, target_id, target_run_id, trial_id)
    project_id, entries = _load_inventory(trial_dir)
    return _inventory_body(project_id, entries)


def get_artifact(
    store: str | Path,
    target_id: str,
    target_run_id: str,
    trial_id: str,
    artifact_id: str,
) -> dict[str, Any]:
    """Metadata plus one bounded, safe representation for one artifact id."""
    trial_dir = _resolve_trial(store, target_id, target_run_id, trial_id)
    project_id, entries = _load_inventory(trial_dir)
    entry = _find_entry(entries, artifact_id)
    return _detail_body(
        trial_dir / project_id,
        entry,
        content_url=_content_url(
            target_id, target_run_id, trial_id, entry["artifact_id"]
        ),
    )


def stream_artifact(
    store: str | Path,
    target_id: str,
    target_run_id: str,
    trial_id: str,
    artifact_id: str,
) -> ArtifactDownload:
    """A bounded chunk iterator over the re-verified raw bytes of one artifact."""
    trial_dir = _resolve_trial(store, target_id, target_run_id, trial_id)
    project_id, entries = _load_inventory(trial_dir)
    entry = _find_entry(entries, artifact_id)
    return _download(trial_dir / project_id, entry)


# --- Trial and manifest resolution ----------------------------------------------


def _resolve_trial(
    store: str | Path, target_id: str, target_run_id: str, trial_id: str
) -> Path:
    if not all(_safe_segment(part) for part in (target_id, target_run_id, trial_id)):
        raise _error(TRIAL_NOT_FOUND, 404)
    root = Path(store)
    trial_dir = root / target_id / target_run_id / trial_id
    if not _is_within(root, trial_dir):
        raise _error(ARTIFACT_UNSAFE, 409)
    if not trial_dir.is_dir():
        raise _error(TRIAL_NOT_FOUND, 404)
    return trial_dir


def _load_inventory(
    trial_dir: Path,
    *,
    require_coherent: bool = False,
    manifest: Mapping | None = None,
) -> tuple[str, list[dict]]:
    """The manifest's project id and its validated, allowlisted inventory entries.

    The strict historical contract accepts a schema-v2 capture whose sections
    are individually available. `require_coherent=True` additionally demands
    the atomic snapshot fingerprint (`project_snapshot.snapshot_sha256` ==
    `project_artifacts.snapshot_sha256`); the resolved layer uses that stricter
    form so a digest-inconsistent capture is never served as a Trial snapshot.

    A caller that has already read and validated the manifest (the resolved
    layer's pre-read guard) passes it as `manifest=` so this loader never touches
    the file again - a symlinked or oversized manifest is never read here.
    """
    if manifest is None:
        manifest_path = trial_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise _error(SNAPSHOT_UNAVAILABLE, 409)
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            raise _error(ARTIFACT_UNSAFE, 409)
        if not isinstance(manifest, Mapping):
            raise _error(ARTIFACT_UNSAFE, 409)

    if manifest.get("schema_version") != STORE_SCHEMA_VERSION:
        raise _error(ARTIFACTS_UNAVAILABLE, 409)

    snapshot = manifest.get("project_snapshot")
    artifacts = manifest.get("project_artifacts")
    graph = manifest.get("project_graph")
    sections = (snapshot, artifacts, graph)
    if not all(
        isinstance(section, Mapping) and section.get("status") == "available"
        for section in sections
    ):
        raise _error(SNAPSHOT_UNAVAILABLE, 409)

    project_id = manifest.get("project_id")
    if not _safe_segment(project_id):
        raise _error(ARTIFACT_UNSAFE, 409)
    if any(section.get("project_id") != project_id for section in sections):
        raise _error(ARTIFACT_UNSAFE, 409)

    if require_coherent:
        snapshot_fingerprint = snapshot.get("snapshot_sha256")
        artifacts_fingerprint = artifacts.get("snapshot_sha256")
        if (
            not _is_text(snapshot_fingerprint)
            or snapshot_fingerprint != artifacts_fingerprint
        ):
            raise _error(SNAPSHOT_UNAVAILABLE, 409)

    raw_entries = artifacts.get("entries")
    if not isinstance(raw_entries, list):
        raise _error(ARTIFACT_UNSAFE, 409)
    entries = [_validated_entry(raw) for raw in raw_entries]
    return project_id, entries


def _validated_entry(raw: object) -> dict:
    """One inventory entry, re-checked against the Task 1 contract and allowlist."""
    if not isinstance(raw, Mapping):
        raise _error(ARTIFACT_UNSAFE, 409)
    entry = {field: raw.get(field) for field in _ENTRY_FIELDS}
    if not _is_text(entry["artifact_id"]):
        raise _error(ARTIFACT_UNSAFE, 409)
    if entry["category"] not in _CATEGORIES:
        raise _error(ARTIFACT_UNSAFE, 409)
    if entry["kind"] not in _HUNT_KINDS + _SKILL_KINDS:
        raise _error(ARTIFACT_UNSAFE, 409)
    if entry["representation"] not in _REPRESENTATIONS:
        raise _error(ARTIFACT_UNSAFE, 409)
    if not _is_text(entry["relative_path"]) or not _is_text(entry["media_type"]):
        raise _error(ARTIFACT_UNSAFE, 409)
    if not _is_media_type(entry["media_type"]):
        # A MIME containing CR/LF (or any control character) must never reach a
        # response header.
        raise _error(ARTIFACT_UNSAFE, 409)
    if not _is_text(entry["sha256"]):
        raise _error(ARTIFACT_UNSAFE, 409)
    if not _is_count(entry["size_bytes"]):
        raise _error(ARTIFACT_UNSAFE, 409)
    # The artifact id is derived from the path; a mismatch could smuggle a path.
    expected_id = hashlib.sha256(entry["relative_path"].encode("utf-8")).hexdigest()
    if entry["artifact_id"] != expected_id:
        raise _error(ARTIFACT_UNSAFE, 409)
    group = _allowlist_group(entry["relative_path"], entry["kind"])
    if group is None:
        raise _error(ARTIFACT_UNSAFE, 409)
    expected_category = "skill" if entry["kind"] in _SKILL_KINDS else "hunting"
    if entry["category"] != expected_category:
        raise _error(ARTIFACT_UNSAFE, 409)
    # The media type and representation are a pure function of the path suffix;
    # a forged pair (e.g. an SVG as text/plain) is unsafe metadata.
    expected_media_type, expected_representation = classify_artifact(
        entry["relative_path"]
    )
    if (
        entry["media_type"] != expected_media_type
        or entry["representation"] != expected_representation
    ):
        raise _error(ARTIFACT_UNSAFE, 409)
    return entry


def _find_entry(entries: list[dict], artifact_id: object) -> dict:
    """Resolve an id strictly through the inventory - never as a path."""
    if _is_text(artifact_id):
        for entry in entries:
            if entry["artifact_id"] == artifact_id:
                return entry
    raise _error(ARTIFACT_NOT_FOUND, 404)


# --- shared rendering over any trusted, validated inventory ----------------------


def _inventory_body(project_id: str, entries: list[dict]) -> dict[str, Any]:
    """The grouped inventory body shared by strict and resolved callers."""
    return {
        "status": "available",
        "project_id": project_id,
        "groups": _build_groups(entries),
    }


def _detail_body(project_root: Path, entry: Mapping, *, content_url: str) -> dict[str, Any]:
    """Metadata plus one bounded preview for one validated entry.

    `project_root` is the trusted directory the entry's `relative_path` is
    rooted at; it is never serialized. `content_url` is supplied by the caller
    so a resolved caller can bind the digest it just returned.
    """
    path = _verified_artifact(project_root, entry)
    return {
        "entry": dict(entry),
        "preview": _preview(path, entry),
        "content_url": content_url,
    }


def _download(project_root: Path, entry: Mapping) -> ArtifactDownload:
    """A bounded stream over one validated, re-verified artifact."""
    path = _verified_artifact(project_root, entry)
    return ArtifactDownload(
        filename=_safe_filename(entry["relative_path"]),
        media_type=entry["media_type"],
        size_bytes=entry["size_bytes"],
        chunks=_iter_file(path),
        attachment=_is_attachment(entry),
    )


# --- allowlist and file verification --------------------------------------------


def _allowlist_group(relative_path: str, kind: str) -> tuple[str, ...] | None:
    """The group key path for an allowlisted entry, or None when it is not one."""
    if (
        not isinstance(relative_path, str)
        or relative_path.startswith("/")
        or "\\" in relative_path
    ):
        return None
    parts = relative_path.split("/")
    if not parts or any(not _safe_segment(part) for part in parts):
        return None

    if kind == "hunt_config":
        # HuntConfigs may nest below `produced`/`consumed` (any number of safe
        # segments); the side is always segment 3 and the leaf a `.yaml` file.
        if (
            len(parts) >= 5
            and parts[:3] == ["hunting", "orchestration", "hunt_configs"]
            and parts[3] in ("produced", "consumed")
            and parts[-1].endswith(".yaml")
        ):
            return ("hunt-configs", parts[3])
    elif kind == "test_spec":
        if (
            len(parts) == 6
            and parts[:3] == ["hunting", "hunter", "test-specs"]
            and parts[4] in ("produced", "consumed")
            and parts[5].endswith(".yaml")
        ):
            return ("test-specs", parts[3])
    elif kind in ("pod_variant", "experiment_log", "pod_export"):
        if len(parts) >= 3 and parts[:2] == ["hunting", "test-executor-pod"]:
            spec_id = parts[2]
            if (
                kind == "pod_variant"
                and len(parts) == 5
                and parts[3] == "variants"
                and parts[4].endswith(".yaml")
            ):
                return ("pod-executions", spec_id)
            if (
                kind == "experiment_log"
                and len(parts) == 5
                and parts[3] == "experiment-log"
                and parts[4].endswith(".yaml")
            ):
                return ("pod-executions", spec_id)
            if kind == "pod_export" and len(parts) == 4 and parts[3].endswith(".yaml"):
                return ("pod-executions", spec_id)
    elif kind == "skill_procedure":
        if len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md":
            return ("skills", parts[1], "procedure")
    elif kind in ("skill_reference", "skill_script", "skill_asset"):
        support = {
            "skill_reference": "references",
            "skill_script": "scripts",
            "skill_asset": "assets",
        }[kind]
        if len(parts) >= 4 and parts[0] == "skills" and parts[2] == support:
            return ("skills", parts[1], support)
    return None


def _verified_artifact(project_root: Path, entry: Mapping) -> Path:
    """Re-check path safety, type, size, and digest; return the verified path."""
    target = project_root / entry["relative_path"]
    if not _is_within(project_root, target):
        raise _error(ARTIFACT_UNSAFE, 409)
    if target.is_symlink():
        raise _error(ARTIFACT_UNSAFE, 409)
    if not target.is_file():
        # Absent or a special file: a missing inventory file.
        raise _error(ARTIFACT_MISSING, 409)
    try:
        size = target.stat().st_size
    except OSError:
        raise _error(ARTIFACT_MISSING, 409)
    if size != entry["size_bytes"]:
        raise _error(ARTIFACT_DIGEST_MISMATCH, 409)
    if _stream_digest(target) != entry["sha256"]:
        raise _error(ARTIFACT_DIGEST_MISMATCH, 409)
    return target


def _stream_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError:
        raise _error(ARTIFACT_MISSING, 409)
    return digest.hexdigest()


def _iter_file(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            yield chunk


# --- previews -------------------------------------------------------------------


def _preview(path: Path, entry: Mapping) -> dict[str, Any]:
    if entry["representation"] == "binary":
        return {"text": None, "parsed": None, "truncated": False, "parse_error": None}

    truncated = entry["size_bytes"] > MAX_PREVIEW_BYTES
    head = _read_head(path, MAX_PREVIEW_BYTES + 1)
    if truncated:
        head = head[:MAX_PREVIEW_BYTES]
    text = _decode_preview(head, truncated=truncated)
    if text is None:
        return {"text": None, "parsed": None, "truncated": truncated, "parse_error": "invalid_utf8"}

    if entry["representation"] == "yaml" and entry["size_bytes"] <= MAX_YAML_BYTES:
        parsed, error = _parse_yaml(path)
        if error is not None:
            return {"text": text, "parsed": None, "truncated": truncated, "parse_error": error}
        return {"text": text, "parsed": parsed, "truncated": truncated, "parse_error": None}
    # Markdown/text, and YAML beyond 2 MiB (download-only), carry text only.
    return {"text": text, "parsed": None, "truncated": truncated, "parse_error": None}


def _read_head(path: Path, count: int) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(count)
    except OSError:
        raise _error(ARTIFACT_MISSING, 409)


def _decode_preview(head: bytes, *, truncated: bool) -> str | None:
    """Strict UTF-8, trimming a genuinely incomplete trailing sequence.

    A final trim is valid only when the error is an *unexpected end of data* at
    the very end of the buffer (a multibyte code point cut by the byte-limit
    boundary). An invalid start byte, invalid continuation byte, or any earlier
    error is real corruption and reports `invalid_utf8`.
    """
    try:
        return head.decode("utf-8")
    except UnicodeDecodeError as exc:
        if (
            truncated
            and exc.reason == "unexpected end of data"
            and exc.end == len(head)
        ):
            try:
                return head[: exc.start].decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None


def _parse_yaml(path: Path) -> tuple[Any, str | None]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise _error(ARTIFACT_MISSING, 409)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "invalid_utf8"
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return None, "invalid_yaml"
    try:
        return _json_safe(loaded), None
    except _UnsupportedYamlValue:
        return None, "unsupported_yaml_value"


def _json_safe(value: Any) -> Any:
    """Convert a `yaml.safe_load` value into a deterministic JSON-safe structure.

    `!!binary` (bytes), `!!set`, non-finite floats, and any other value that has
    no faithful JSON form raise `_UnsupportedYamlValue`; dates and times convert
    to their stable ISO 8601 string. Mapping keys are coerced to strings, with a
    collision treated as unsupported.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        raise _UnsupportedYamlValue()
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = _json_safe_key(key)
            if safe_key in converted:
                raise _UnsupportedYamlValue()
            converted[safe_key] = _json_safe(item)
        return converted
    raise _UnsupportedYamlValue()


def _json_safe_key(key: Any) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, float):
        if math.isfinite(key):
            return repr(key)
        raise _UnsupportedYamlValue()
    if key is None:
        return "null"
    if isinstance(key, (datetime, date, time)):
        return key.isoformat()
    raise _UnsupportedYamlValue()


# --- grouping -------------------------------------------------------------------


_LABELS = {
    "hunt-configs": "Hunt configs",
    "test-specs": "Test specs",
    "pod-executions": "Pod executions",
    "skills": "Skills",
    "produced": "Produced",
    "consumed": "Consumed",
    "procedure": "Procedure",
    "references": "References",
    "scripts": "Scripts",
    "assets": "Assets",
}


def _build_groups(entries: list[dict]) -> list[dict]:
    roots: dict[str, _Group] = {}
    for entry in entries:
        group_key = _allowlist_group(entry["relative_path"], entry["kind"])
        if group_key is None:
            raise _error(ARTIFACT_UNSAFE, 409)
        category = entry["category"]
        prefix: list[str] = []
        level = roots
        for segment in group_key:
            prefix.append(segment)
            key = "/".join(prefix)
            if key not in level:
                level[key] = _Group(key=key, label=_LABELS.get(segment, segment), category=category)
            node = level[key]
            level = node.children
        node.entries.append(entry)
    return _serialize_groups(roots)


def _serialize_groups(level: Mapping[str, _Group]) -> list[dict]:
    groups: list[dict] = []
    for key in sorted(level):
        node = level[key]
        groups.append(
            {
                "key": node.key,
                "label": node.label,
                "category": node.category,
                "entries": sorted(node.entries, key=lambda entry: entry["relative_path"]),
                "children": _serialize_groups(node.children),
            }
        )
    return groups


# --- content helpers --------------------------------------------------------------


def _content_url(
    target_id: str, target_run_id: str, trial_id: str, artifact_id: str
) -> str:
    return "/trials/{}/{}/{}/artifacts/{}/content".format(
        quote(target_id, safe=""),
        quote(target_run_id, safe=""),
        quote(trial_id, safe=""),
        quote(artifact_id, safe=""),
    )


def _safe_filename(relative_path: str) -> str:
    name = relative_path.rsplit("/", 1)[-1]
    safe = _SAFE_FILENAME.sub("_", name).strip("._") or "artifact"
    return safe


def _is_attachment(entry: Mapping) -> bool:
    if entry["representation"] == "binary":
        return True
    return entry["media_type"] in _ACTIVE_MEDIA_TYPES


def _safe_segment(segment: object) -> bool:
    if not isinstance(segment, str) or not segment or segment in (".", ".."):
        return False
    if any(char in segment for char in ("/", "\\", "\x00")):
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in segment)


def _is_within(root: str | Path, path: str | Path) -> bool:
    root_resolved = Path(root).resolve()
    candidate = Path(path).resolve()
    return candidate == root_resolved or root_resolved in candidate.parents


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_media_type(value: object) -> bool:
    return isinstance(value, str) and bool(_MEDIA_TYPE.match(value))


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _error(code: str, status_code: int) -> ArtifactLookupError:
    return ArtifactLookupError(code, status_code)


__all__ = [
    "ArtifactDownload",
    "ArtifactLookupError",
    "ARTIFACT_DIGEST_MISMATCH",
    "ARTIFACT_MISSING",
    "ARTIFACT_NOT_FOUND",
    "ARTIFACT_UNSAFE",
    "ARTIFACTS_UNAVAILABLE",
    "SNAPSHOT_UNAVAILABLE",
    "get_artifact",
    "list_artifacts",
    "stream_artifact",
]
