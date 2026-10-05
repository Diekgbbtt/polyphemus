"""Read and project operator-only benchmark ground truth, safely.

The operator dashboard shows, for each materialized verdict, the reference the
benchmark itself carries for that vulnerability. That reference lives in a
WebExploitBench checkout, not in the Trial record, so this module is the single
place the operator API reads it.

The trust boundary is explicit:

* a Trial's `target_id` is resolved only through operator-approved setup files
  (`target_id -> <dataset>/<target>`), never by stripping an ID suffix, and a
  target mapped to two different references fails closed;
* every read is bounded, must be a regular file, and may not cross a symlink, so
  a hostile or accidental link in the mounted checkout cannot escape it;
* the response is the small, path-free projection the UI consumes - never a raw
  challenge document, exploit, report, or host path;
* a malformed or missing entry omits that one vulnerability; a malformed or
  missing top-level source is an unavailable error. Every failure carries a
  stable code, never an exception message with a path in it.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from orchestrator.dataset import DatasetError, resolve_target_key
from orchestrator.setup import SetupError, is_path_safe_id, parse_eval_setup

PROVENANCE = "current_benchmark_checkout"

# Only the configured dataset's targets have a reference here; another dataset's
# target is reported unavailable rather than guessed at.
SUPPORTED_DATASET = "webexploitbench"

# Bounds on everything read or emitted. A benchmark file is a small JSON
# document; anything larger is a sign the wrong file (or a hostile one) is in
# the mount.
MAX_SOURCE_BYTES = 1024 * 1024
MAX_VULNERABILITIES = 256
MAX_TEXT_CHARS = 4096
MAX_RESPONSE_BYTES = 1024 * 1024

# Stable error codes, one per failure mode, with the HTTP status the API layer
# maps them to.
CODE_INVALID_TARGET_ID = "ground_truth_invalid_target_id"
CODE_UNKNOWN_TARGET = "ground_truth_target_unknown"
CODE_AMBIGUOUS_MAPPING = "ground_truth_mapping_ambiguous"
CODE_SOURCE_INVALID = "ground_truth_source_invalid"
CODE_SOURCE_UNAVAILABLE = "ground_truth_source_unavailable"

STATUS_INVALID = 400
STATUS_UNKNOWN = 404
STATUS_AMBIGUOUS = 409
STATUS_UNAVAILABLE = 503

# Display fields legitimately name HTTP routes (`/view`, `/api/v1/items`), so a
# leading slash is not by itself a host path. It is one when the token is a
# filesystem location: a `..` traversal, an UNC path, a known system/home root,
# or a path with a file extension. Mirrors the read API's projector so the two
# boundaries agree, without depending on its private helpers.
HOST_PATH_ROOTS = frozenset(
    {
        "Applications", "Library", "System", "Users", "Volumes", "bin", "boot",
        "dev", "etc", "home", "lib", "lib64", "media", "mnt", "opt", "proc",
        "root", "run", "sbin", "srv", "sys", "tmp", "usr", "var",
    }
)
FILE_SUFFIXES = frozenset(
    {
        "bin", "cfg", "conf", "csv", "env", "gz", "ini", "jpeg", "jpg", "json",
        "log", "md", "md5", "parquet", "pem", "png", "py", "pyc", "sh", "so",
        "sqlite", "tar", "toml", "ts", "tsx", "txt", "whl", "xml", "xz",
        "yaml", "yml", "zip",
    }
)


class GroundTruthError(Exception):
    """A ground-truth read failed; `code` is stable and carries no host path."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _looks_like_host_path(token: str) -> bool:
    if token.startswith("//"):
        return True
    if not token.startswith("/"):
        return False
    segments = [segment for segment in token.split("/") if segment]
    if not segments:
        return False
    if any(segment == ".." for segment in segments):
        return True
    if segments[0] in HOST_PATH_ROOTS:
        return True
    last = segments[-1]
    suffix = last.rsplit(".", 1)[1].lower() if "." in last else ""
    return suffix in FILE_SUFFIXES


def _safe_display_text(value: object, *, limit: int = MAX_TEXT_CHARS) -> str | None:
    """Human-readable display text, or `None` when it is absent or a host path."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit or "\\" in text:
        return None
    if any(_is_unsafe_token(token) for token in text.split()):
        return None
    return text


def _is_unsafe_token(token: str) -> bool:
    """Whether one whitespace-delimited token names a location, not a route.

    A display field may name an HTTP route, so a leading slash alone is fine;
    a `..` segment, a UNC path, a known system/home root, or a file extension is
    not, and neither is a relative traversal such as `../../etc/passwd`.
    """
    if _looks_like_host_path(token):
        return True
    segments = [segment for segment in token.split("/") if segment]
    return any(segment == ".." for segment in segments)


@dataclass(frozen=True)
class GroundTruthSource:
    """The configured benchmark checkout and setup files, read on demand."""

    benchmark_root: Path
    setup_root: Path
    setup_files: tuple[str, ...]

    # --- public surface -------------------------------------------------------

    def read(self, target_id: str) -> dict[str, object]:
        """The path-free reference for one mapped target, or a stable error."""
        if not is_path_safe_id(target_id):
            raise GroundTruthError(CODE_INVALID_TARGET_ID, STATUS_INVALID)

        mapping = self._mapping()
        keys = mapping.get(target_id)
        if not keys:
            raise GroundTruthError(CODE_UNKNOWN_TARGET, STATUS_UNKNOWN)
        if len(keys) > 1:
            raise GroundTruthError(CODE_AMBIGUOUS_MAPPING, STATUS_AMBIGUOUS)

        try:
            dataset, target = resolve_target_key(next(iter(keys)))
        except DatasetError:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE) from None
        if dataset != SUPPORTED_DATASET or not is_path_safe_id(target):
            raise GroundTruthError(CODE_SOURCE_UNAVAILABLE, STATUS_UNAVAILABLE)

        challenge = self._read_benchmark_json((target, "challenge.json"))
        vulnerabilities = self._project(target, challenge)
        response: dict[str, object] = {
            "target_id": target_id,
            "provenance": PROVENANCE,
            "vulnerabilities": vulnerabilities,
        }
        if len(json.dumps(response, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        return response

    def health(self) -> dict[str, object]:
        """Whether the configured source can be read; never any ground truth."""
        try:
            self._mapping()
        except GroundTruthError:
            return {"status": "degraded"}
        root = Path(self.benchmark_root)
        if root.is_symlink() or not root.is_dir():
            return {"status": "degraded"}
        return {"status": "ok"}

    # --- mapping --------------------------------------------------------------

    def _mapping(self) -> dict[str, set[str]]:
        """`target_id -> {target_key}`, from the approved setup files.

        Identical duplicates collapse; two different references for one target
        are kept, so that target alone fails closed.
        """
        mapping: dict[str, set[str]] = {}
        for name in self.setup_files:
            payload = self._read_setup(name)
            try:
                setup = parse_eval_setup(payload)
            except SetupError:
                raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE) from None
            for instance in setup.instances:
                for target in instance.targets:
                    mapping.setdefault(target.target_id, set()).add(target.target_key)
        return mapping

    # --- guarded reads --------------------------------------------------------

    def _read_setup(self, name: str) -> object:
        """One approved setup basename under the setup root, parsed as YAML."""
        if not is_path_safe_id(name):
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        text = self._decode(self._read_bytes(Path(self.setup_root), (name,)))
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE) from None

    def _read_benchmark_json(self, parts: tuple[str, ...]) -> object:
        text = self._decode(self._read_bytes(Path(self.benchmark_root), parts))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE) from None

    @staticmethod
    def _decode(data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE) from None

    def _read_bytes(self, root: Path, relative: Sequence[str]) -> bytes:
        """Read one regular, symlink-free, bounded file under `root`."""
        if root.is_symlink() or not root.is_dir():
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        current = root
        for part in relative:
            if not is_path_safe_id(part):
                raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
            current = current / part
            if current.is_symlink():
                raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        if not current.is_file():
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        try:
            with current.open("rb") as handle:
                data = handle.read(MAX_SOURCE_BYTES + 1)
        except OSError:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE) from None
        if len(data) > MAX_SOURCE_BYTES:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        return data

    # --- projection -----------------------------------------------------------

    def _project(self, target: str, challenge: object) -> list[dict[str, object]]:
        if not isinstance(challenge, Mapping):
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        entries = challenge.get("vulnerabilities")
        if not isinstance(entries, list):
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)
        if len(entries) > MAX_VULNERABILITIES:
            raise GroundTruthError(CODE_SOURCE_INVALID, STATUS_UNAVAILABLE)

        order: list[str] = []
        scoring: dict[str, tuple[str, ...]] = {}
        conflicts: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            vuln_id = entry.get("vuln_id")
            if not is_path_safe_id(vuln_id):
                continue
            names = self._scoring(entry.get("scoring", []))
            if names is None:
                continue
            if vuln_id in scoring:
                # Two different references for one ID: choose neither.
                if scoring[vuln_id] != names:
                    conflicts.add(vuln_id)
                continue
            scoring[vuln_id] = names
            order.append(vuln_id)

        projected: list[dict[str, object]] = []
        for vuln_id in order:
            if vuln_id in conflicts:
                continue
            row = self._project_vulnerability(target, vuln_id, scoring[vuln_id])
            if row is not None:
                projected.append(row)
        return projected

    def _project_vulnerability(
        self, target: str, vuln_id: str, scoring: tuple[str, ...]
    ) -> dict[str, object] | None:
        """One entry, or `None` when its metadata is absent, malformed, or unsafe."""
        try:
            metadata = self._read_benchmark_json(
                (target, "vulnerability", vuln_id, "metadata.json")
            )
        except GroundTruthError:
            return None
        if not isinstance(metadata, Mapping):
            return None
        location = _safe_display_text(metadata.get("Location"))
        vuln_type = _safe_display_text(metadata.get("Vulnerability Type"))
        if location is None or vuln_type is None:
            return None
        return {
            "vuln_id": vuln_id,
            "location": location,
            "type": vuln_type,
            "scoring": list(scoring),
        }

    @staticmethod
    def _scoring(value: object) -> tuple[str, ...] | None:
        """Validated signal names, or `None` when the entry is malformed."""
        if not isinstance(value, list):
            return None
        names: list[str] = []
        for item in value:
            name = _safe_display_text(item)
            if name is None or "/" in name:
                return None
            names.append(name)
        return tuple(names)
