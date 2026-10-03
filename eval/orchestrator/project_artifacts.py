"""The deterministic, allowlisted catalog of a Trial's project artifacts.

The materializer snapshots the hunting artifacts and the project-authored
skill bundles that belonged to a Trial (design: real eval project artifacts).
This module owns discovery only: it walks the exact allowlist from the spec,
classifies each regular file, and returns an order-stable inventory with
content digests. Publication, manifest integration, and the read API build on
top of it in later tasks.

Only regular files are eligible. Symlinks, sockets/devices, unsafe segments,
traversal, and paths that resolve outside the project root are rejected with a
coded `ProjectArtifactError` whose message never carries an absolute host path.
Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from orchestrator.files import HUNT_CONFIG_SIDES, HUNTER_TEST_SPEC_SIDES, FileStore

# The two artifact categories the manifest groups by (design: manifest).
CATEGORY_HUNTING = "hunting"
CATEGORY_SKILL = "skill"

# The exact `kind` vocabulary from the manifest design.
KIND_HUNT_CONFIG = "hunt_config"
KIND_TEST_SPEC = "test_spec"
KIND_POD_VARIANT = "pod_variant"
KIND_EXPERIMENT_LOG = "experiment_log"
KIND_POD_EXPORT = "pod_export"
KIND_SKILL_PROCEDURE = "skill_procedure"
KIND_SKILL_REFERENCE = "skill_reference"
KIND_SKILL_SCRIPT = "skill_script"
KIND_SKILL_ASSET = "skill_asset"

# The skill support directories; only these three recurse.
_SKILL_SUPPORT_DIRS = (
    ("references", KIND_SKILL_REFERENCE),
    ("scripts", KIND_SKILL_SCRIPT),
    ("assets", KIND_SKILL_ASSET),
)

# The project id must be one path-safe segment.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Characters that can change the meaning of a path segment: separators and NUL.
_PATH_SEPARATORS = ("/", "\\", "\x00")

_DEFAULT_MEDIA = ("application/octet-stream", "binary")
# Explicit extension -> (media type, representation), before the fallback.
_EXTENSION_MEDIA: dict[str, tuple[str, str]] = {
    ".yaml": ("application/yaml", "yaml"),
    ".yml": ("application/yaml", "yaml"),
    ".md": ("text/markdown", "markdown"),
    ".markdown": ("text/markdown", "markdown"),
    ".txt": ("text/plain", "text"),
    ".log": ("text/plain", "text"),
    ".json": ("application/json", "text"),
    ".csv": ("text/csv", "text"),
    ".tsv": ("text/tab-separated-values", "text"),
    ".py": ("text/x-python", "text"),
    ".sh": ("text/x-shellscript", "text"),
    ".bash": ("text/x-shellscript", "text"),
    ".zsh": ("text/x-shellscript", "text"),
    ".rb": ("text/x-ruby", "text"),
    ".js": ("text/javascript", "text"),
    ".mjs": ("text/javascript", "text"),
    ".cjs": ("text/javascript", "text"),
    ".ts": ("text/typescript", "text"),
    ".tsx": ("text/typescript", "text"),
    ".jsx": ("text/javascript", "text"),
    ".html": ("text/html", "text"),
    ".htm": ("text/html", "text"),
    ".css": ("text/css", "text"),
    ".xml": ("application/xml", "text"),
    ".toml": ("application/toml", "text"),
    ".ini": ("text/plain", "text"),
    ".cfg": ("text/plain", "text"),
    ".conf": ("text/plain", "text"),
    ".env": ("text/plain", "text"),
    ".sql": ("text/x-sql", "text"),
    ".go": ("text/x-go", "text"),
    ".rs": ("text/x-rust", "text"),
    ".java": ("text/x-java", "text"),
    ".c": ("text/x-c", "text"),
    ".h": ("text/x-c", "text"),
    ".cpp": ("text/x-c++", "text"),
    ".svg": ("image/svg+xml", "binary"),
    ".png": ("image/png", "binary"),
    ".jpg": ("image/jpeg", "binary"),
    ".jpeg": ("image/jpeg", "binary"),
    ".gif": ("image/gif", "binary"),
    ".webp": ("image/webp", "binary"),
    ".ico": ("image/x-icon", "binary"),
    ".pdf": ("application/pdf", "binary"),
    ".zip": ("application/zip", "binary"),
    ".gz": ("application/gzip", "binary"),
    ".tar": ("application/x-tar", "binary"),
    ".woff": ("font/woff", "binary"),
    ".woff2": ("font/woff2", "binary"),
    ".ttf": ("font/ttf", "binary"),
    ".otf": ("font/otf", "binary"),
    ".bin": ("application/octet-stream", "binary"),
}


class ProjectArtifactError(RuntimeError):
    """The project-artifact catalog could not be built safely.

    `failure` is the named code the materializer and read API act on
    (`artifact_unsafe`, `artifact_unreadable`); the message carries only
    project-relative descriptions, never an absolute host path.
    """

    def __init__(self, detail: str, *, failure: str = "artifact_unsafe") -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail


@dataclass(frozen=True)
class ProjectArtifact:
    """One allowlisted project file and its content metadata.

    `source_path` is the internal read handle; it is never serialized into the
    manifest (`as_manifest_entry` omits it).
    """

    artifact_id: str
    category: str
    kind: str
    relative_path: str
    media_type: str
    size_bytes: int
    sha256: str
    representation: str
    source_path: Path

    def as_manifest_entry(self) -> dict:
        """The manifest-facing mapping; the source path is deliberately absent."""
        return {
            "artifact_id": self.artifact_id,
            "category": self.category,
            "kind": self.kind,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "representation": self.representation,
        }


def artifact_manifest(
    entries: Sequence[ProjectArtifact],
    *,
    project_id: str,
    captured_at: str,
    snapshot_sha256: str,
) -> dict:
    """The canonical `project_artifacts` payload for `run-manifest.yaml`.

    Entries are re-sorted by POSIX-relative path so the serialized inventory is
    deterministic regardless of the caller's ordering.
    """
    ordered = sorted(entries, key=lambda entry: entry.relative_path)
    return {
        "status": "available",
        "project_id": project_id,
        "captured_at": captured_at,
        "snapshot_sha256": snapshot_sha256,
        "entries": [entry.as_manifest_entry() for entry in ordered],
    }


def collect_project_artifacts(
    data_root: str | Path,
    project_id: str,
    *,
    files: FileStore,
) -> tuple[ProjectArtifact, ...]:
    """The deterministic, allowlisted catalog of one project's artifacts.

    A missing project directory or any missing allowlisted subtree is a normal
    empty group. Anything unsafe under an allowlisted subtree raises
    `ProjectArtifactError` before any bytes are read.
    """
    _require_safe_segment(project_id, where="project_id")
    root = Path(data_root)
    project_root = root / project_id
    if not files.exists(project_root):
        return ()
    if files.is_symlink(project_root):
        raise ProjectArtifactError("project root is a symlink", failure="artifact_unsafe")
    if not files.is_dir(project_root):
        return ()

    candidates: dict[str, tuple[Path, str, str]] = {}

    def register(path: Path, category: str, kind: str) -> None:
        relative = _relative(project_root, path)
        resolved = Path(path).resolve()
        if not _within(Path(project_root).resolve(), resolved):
            raise ProjectArtifactError(
                f"artifact escapes the project root: {relative}",
                failure="artifact_unsafe",
            )
        candidates.setdefault(relative, (Path(path), category, kind))

    _collect_hunting(files, project_root, register)
    _collect_skills(files, project_root, register)

    artifacts: list[ProjectArtifact] = []
    for relative in sorted(candidates):
        path, category, kind = candidates[relative]
        try:
            payload = files.read_bytes(path)
        except OSError as exc:  # path-free, coded
            raise ProjectArtifactError(
                f"cannot read {relative}", failure="artifact_unreadable"
            ) from exc
        size = len(payload)
        try:
            size = files.file_size(path)
        except OSError:
            pass
        media_type, representation = _classify(relative)
        artifacts.append(
            ProjectArtifact(
                artifact_id=hashlib.sha256(relative.encode()).hexdigest(),
                category=category,
                kind=kind,
                relative_path=relative,
                media_type=media_type,
                size_bytes=size,
                sha256=hashlib.sha256(payload).hexdigest(),
                representation=representation,
                source_path=path,
            )
        )
    return tuple(artifacts)


# --- classification -----------------------------------------------------------


def _classify(relative_path: str) -> tuple[str, str]:
    """The explicit (media type, representation) for a relative path's suffix."""
    suffix = Path(relative_path).suffix.lower()
    return _EXTENSION_MEDIA.get(suffix, _DEFAULT_MEDIA)


def _relative(project_root: Path, path: Path) -> str:
    try:
        return Path(path).relative_to(project_root).as_posix()
    except ValueError:
        return Path(path).name


def _within(root_resolved: Path, candidate_resolved: Path) -> bool:
    return candidate_resolved == root_resolved or root_resolved in candidate_resolved.parents


def _require_safe_segment(segment: str, *, where: str) -> str:
    if not isinstance(segment, str) or not _SAFE_SEGMENT.match(segment):
        raise ProjectArtifactError(
            f"unsafe {where}", failure="artifact_unsafe"
        )
    return segment


def _require_safe_dynamic_segment(segment: str, *, where: str) -> str:
    """A path-safe single segment for `<fault_key>`, `<spec_id>`, `<skill_name>`.

    Domain identifiers may carry punctuation (`fault:http:request`,
    `fault::auth`, `spec:variant`, `skill:name`), so this validates path safety
    instead of a restrictive character allowlist: no empty/`.`/`..`, no path
    separators or NUL, and no control characters.
    """
    if not isinstance(segment, str) or not segment or segment in (".", ".."):
        raise ProjectArtifactError(f"unsafe {where}", failure="artifact_unsafe")
    if any(char in segment for char in _PATH_SEPARATORS):
        raise ProjectArtifactError(f"unsafe {where}", failure="artifact_unsafe")
    if any(ord(char) < 32 or ord(char) == 127 for char in segment):
        raise ProjectArtifactError(f"unsafe {where}", failure="artifact_unsafe")
    return segment


# --- traversal ----------------------------------------------------------------


def _enter_dir(files: FileStore, project_root: Path, directory: Path) -> bool:
    """True when `directory` is a real, contained directory to enumerate."""
    relative = _relative(project_root, directory)
    if files.is_symlink(directory):
        raise ProjectArtifactError(
            f"symlinked directory is not allowed: {relative}", failure="artifact_unsafe"
        )
    if not files.is_dir(directory):
        return False
    if not _within(Path(project_root).resolve(), Path(directory).resolve()):
        raise ProjectArtifactError(
            f"directory escapes the project root: {relative}", failure="artifact_unsafe"
        )
    return True


def _assert_regular(files: FileStore, project_root: Path, path: Path) -> None:
    if files.is_symlink(path):
        raise ProjectArtifactError(
            f"symlink is not allowed: {_relative(project_root, path)}",
            failure="artifact_unsafe",
        )
    if not files.is_file(path):
        raise ProjectArtifactError(
            f"special file is not allowed: {_relative(project_root, path)}",
            failure="artifact_unsafe",
        )


def _collect_yaml_flat(
    files: FileStore,
    project_root: Path,
    directory: Path,
    register: Callable[[Path, str, str], None],
    category: str,
    kind: str,
) -> None:
    """Direct `*.yaml` children only: hunting patterns do not recurse."""
    if not _enter_dir(files, project_root, directory):
        return
    for entry in files.glob(directory, "*.yaml"):
        if files.is_symlink(entry):
            raise ProjectArtifactError(
                f"symlink is not allowed: {_relative(project_root, entry)}",
                failure="artifact_unsafe",
            )
        if files.is_dir(entry):
            continue
        _assert_regular(files, project_root, entry)
        register(entry, category, kind)


def _child_dirs(
    files: FileStore,
    project_root: Path,
    parent: Path,
    where: str,
) -> list[Path]:
    """Path-safe child directories of `parent`; a symlinked child is unsafe."""
    if not _enter_dir(files, project_root, parent):
        return []
    found: list[Path] = []
    for entry in files.glob(parent, "*"):
        if files.is_symlink(entry):
            raise ProjectArtifactError(
                f"symlink is not allowed: {_relative(project_root, entry)}",
                failure="artifact_unsafe",
            )
        if files.is_dir(entry):
            _require_safe_dynamic_segment(entry.name, where=where)
            found.append(entry)
    return found


def _collect_hunting(
    files: FileStore,
    project_root: Path,
    register: Callable[[Path, str, str], None],
) -> None:
    hunting_root = project_root / "hunting"

    config_root = hunting_root / "orchestration" / "hunt_configs"
    for side in HUNT_CONFIG_SIDES:
        _collect_yaml_flat(
            files, project_root, config_root / side, register, CATEGORY_HUNTING, KIND_HUNT_CONFIG
        )

    specs_root = hunting_root / "hunter" / "test-specs"
    for fault_dir in _child_dirs(files, project_root, specs_root, "fault_key"):
        for side in HUNTER_TEST_SPEC_SIDES:
            _collect_yaml_flat(
                files,
                project_root,
                fault_dir / side,
                register,
                CATEGORY_HUNTING,
                KIND_TEST_SPEC,
            )

    pod_root = hunting_root / "test-executor-pod"
    for spec_dir in _child_dirs(files, project_root, pod_root, "spec_id"):
        _collect_yaml_flat(
            files, project_root, spec_dir, register, CATEGORY_HUNTING, KIND_POD_EXPORT
        )
        _collect_yaml_flat(
            files,
            project_root,
            spec_dir / "variants",
            register,
            CATEGORY_HUNTING,
            KIND_POD_VARIANT,
        )
        _collect_yaml_flat(
            files,
            project_root,
            spec_dir / "experiment-log",
            register,
            CATEGORY_HUNTING,
            KIND_EXPERIMENT_LOG,
        )


def _collect_tree(
    files: FileStore,
    project_root: Path,
    directory: Path,
    register: Callable[[Path, str, str], None],
    category: str,
    kind: str,
) -> None:
    """Recursively collect every regular file below a skill support directory."""
    stack = [directory]
    while stack:
        current = stack.pop()
        if not _enter_dir(files, project_root, current):
            continue
        for entry in files.glob(current, "*"):
            if files.is_symlink(entry):
                raise ProjectArtifactError(
                    f"symlink is not allowed: {_relative(project_root, entry)}",
                    failure="artifact_unsafe",
                )
            if files.is_dir(entry):
                stack.append(entry)
            elif files.is_file(entry):
                register(entry, category, kind)
            else:
                raise ProjectArtifactError(
                    f"special file is not allowed: {_relative(project_root, entry)}",
                    failure="artifact_unsafe",
                )


def _collect_skills(
    files: FileStore,
    project_root: Path,
    register: Callable[[Path, str, str], None],
) -> None:
    skills_root = project_root / "skills"
    if not _enter_dir(files, project_root, skills_root):
        return
    for skill_dir in files.glob(skills_root, "*"):
        if files.is_symlink(skill_dir):
            raise ProjectArtifactError(
                f"symlink is not allowed: {_relative(project_root, skill_dir)}",
                failure="artifact_unsafe",
            )
        if not files.is_dir(skill_dir):
            continue
        _require_safe_dynamic_segment(skill_dir.name, where="skill_name")
        skill_md = skill_dir / "SKILL.md"
        if files.is_symlink(skill_md):
            raise ProjectArtifactError(
                f"symlink is not allowed: {_relative(project_root, skill_md)}",
                failure="artifact_unsafe",
            )
        if files.is_file(skill_md):
            register(skill_md, CATEGORY_SKILL, KIND_SKILL_PROCEDURE)
        elif files.exists(skill_md) and not files.is_dir(skill_md):
            raise ProjectArtifactError(
                f"special file is not allowed: {_relative(project_root, skill_md)}",
                failure="artifact_unsafe",
            )
        for support, kind in _SKILL_SUPPORT_DIRS:
            _collect_tree(
                files,
                project_root,
                skill_dir / support,
                register,
                CATEGORY_SKILL,
                kind,
            )


__all__ = [
    "CATEGORY_HUNTING",
    "CATEGORY_SKILL",
    "KIND_EXPERIMENT_LOG",
    "KIND_HUNT_CONFIG",
    "KIND_POD_EXPORT",
    "KIND_POD_VARIANT",
    "KIND_SKILL_ASSET",
    "KIND_SKILL_PROCEDURE",
    "KIND_SKILL_REFERENCE",
    "KIND_SKILL_SCRIPT",
    "KIND_TEST_SPEC",
    "ProjectArtifact",
    "ProjectArtifactError",
    "artifact_manifest",
    "collect_project_artifacts",
]
