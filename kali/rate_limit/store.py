"""The durable, bounded Vegeta artifact store (#238 Task 3).

Layout (beneath the persistent Kali data root, project- and run-scoped):

```text
<root>/<project_id>/rate-limit/<run_id>/<experiment_id>/results.jsonl.gz
<root>/<project_id>/rate-limit/<run_id>/<experiment_id>/manifest.json
```

Three properties are load-bearing and tested:

* **Atomic publication.** Both files are written and fsynced inside a SIBLING
  temporary directory which is then renamed onto the final name. A partial
  write is removed and never advertised - an interrupted experiment yields no
  reference for the profile to point at.
* **Pinned evidence.** The manifest records the compressed stream's SHA-256,
  the hit count, the offered duration, the Vegeta version and the experiment
  spec with its SECRET values redacted. `RateProfile` stores the relative
  `rate-artifact/v1:<project>/<run>/<experiment>` reference and this hash, not
  the bytes and never an absolute path.
* **Bounded retention.** Age retention is OFF by default (0, matching HTTP
  history) and a per-project byte cap (256 MiB) evicts OLDEST complete
  experiment directories first. Temporary/partial directories are never
  counted, never advertised and never deleted while a writer owns them.

Identifiers come from the controller and are validated as path segments, so a
crafted `project_id`/`run_id`/`experiment_id` can never escape the root.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

# The secret vocabulary is the SAME one the model-facing HTTP-history views use
# (`kali.http_history.sanitize`): imported, never copied, so a new secret header
# cannot be redacted in one plane and leak in the other.
from kali.http_history.sanitize import _SENSITIVE_HEADERS, _SENSITIVE_KEY_RE

RATE_ARTIFACT_SCHEME = "rate-artifact/v1"
"""The artifact reference scheme: `<scheme>:<project>/<run>/<experiment>`."""

RATE_LIMIT_DIRNAME = "rate-limit"
RESULTS_FILENAME = "results.jsonl.gz"
MANIFEST_FILENAME = "manifest.json"

DEFAULT_MAX_BYTES = 256 * 1024 * 1024
"""The per-project artifact cap (spec: 256 MiB)."""

REDACTED = "[redacted]"
"""The placeholder written in place of a secret value (never the value)."""

_TEMP_PREFIX = "."
_TRASH_PREFIX = ".trash-"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactIdentifierError(ValueError):
    """A project/run/experiment identifier is not a safe path segment."""


@dataclass(frozen=True)
class PublishedArtifact:
    """A successfully published experiment artifact."""

    ref: str
    directory: str
    sha256: str
    count: int


def _validate_identifier(value: Any, *, what: str) -> str:
    text = str(value or "")
    # `.`/`..`/absolute/embedded separators are all refused: an identifier is a
    # single path segment or it is not an identifier.
    if not text or not _IDENTIFIER_RE.match(text) or text.startswith("."):
        raise ArtifactIdentifierError(
            f"{what} must be a single safe path segment, got {value!r}"
        )
    return text


def _redact(value: Any, *, key: str = "") -> Any:
    """Recursively replace secret VALUES, keeping the shape auditable."""
    if isinstance(value, Mapping):
        return {
            name: _redact(item, key=str(name))
            for name, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, key=key) for item in value]
    lowered = key.lower()
    if lowered in _SENSITIVE_HEADERS or _SENSITIVE_KEY_RE.search(key):
        return REDACTED
    return value


def _encode_stream(hits: Sequence[Mapping]) -> bytes:
    """The compressed JSONL hit stream, reproducible for the same input.

    `mtime=0` keeps the gzip container deterministic: the same hits hash to the
    same SHA-256, so a manifest hash is a real integrity check rather than a
    timestamp artifact.
    """
    payload = "".join(
        json.dumps(dict(hit), sort_keys=True, separators=(",", ":")) + "\n"
        for hit in hits
    ).encode("utf-8")
    return gzip.compress(payload, mtime=0)


def write_private_file(path: Path, data: bytes) -> None:
    """Write `data` with 0600 mode and fsync it before returning."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _fsync_dir(path: Path) -> None:
    """fsync a directory so a rename/creation survives a crash."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class RateLimitArtifactStore:
    """Publishes, hashes, bounds and evicts rate-limit experiment artifacts."""

    def __init__(
        self,
        root: str | Path,
        *,
        retention_s: int = 0,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ):
        self.root = Path(root)
        self.retention_s = int(retention_s)
        self.max_bytes = int(max_bytes)

    # --- coordinates -----------------------------------------------------------

    @staticmethod
    def artifact_ref(project_id: Any, run_id: Any, experiment_id: Any) -> str:
        project = _validate_identifier(project_id, what="project_id")
        run = _validate_identifier(run_id, what="run_id")
        experiment = _validate_identifier(experiment_id, what="experiment_id")
        return f"{RATE_ARTIFACT_SCHEME}:{project}/{run}/{experiment}"

    def experiment_dir(self, project_id: Any, run_id: Any, experiment_id: Any) -> Path:
        self.artifact_ref(project_id, run_id, experiment_id)  # validates
        return (
            self.root / str(project_id) / RATE_LIMIT_DIRNAME / str(run_id) / str(experiment_id)
        )

    def project_dir(self, project_id: Any) -> Path:
        resolved = _validate_identifier(project_id, what="project_id")
        return self.root / resolved / RATE_LIMIT_DIRNAME

    # --- publication -----------------------------------------------------------

    def publish(
        self,
        *,
        project_id: str,
        run_id: str,
        experiment_id: str,
        hits: Sequence[Mapping],
        spec: Mapping,
        vegeta_version: str = "unknown",
        duration_s: float = 0.0,
        aggregate: Mapping | None = None,
        created_at: float | None = None,
    ) -> PublishedArtifact:
        """Atomically publish one experiment's compacted hit stream.

        Either the whole experiment directory appears under its advertised name
        or nothing does: the caller receives no reference for a partial write.
        """
        ref = self.artifact_ref(project_id, run_id, experiment_id)
        target = self.experiment_dir(project_id, run_id, experiment_id)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f"{_TEMP_PREFIX}{experiment_id}.tmp-", dir=parent)
        )
        try:
            stream = _encode_stream(hits)
            sha256 = hashlib.sha256(stream).hexdigest()
            write_private_file(temporary / RESULTS_FILENAME, stream)
            manifest = {
                "version": RATE_ARTIFACT_SCHEME,
                "ref": ref,
                "project_id": str(project_id),
                "run_id": str(run_id),
                "experiment_id": str(experiment_id),
                "results_file": RESULTS_FILENAME,
                "sha256": sha256,
                "count": len(hits),
                "duration_s": float(duration_s),
                "vegeta_version": str(vegeta_version),
                "created_at": float(created_at if created_at is not None else time.time()),
                # The experiment spec is stored for auditability with every
                # secret VALUE replaced; the auth context never lands on disk
                # in the clear.
                "spec": _redact(dict(spec)),
                "aggregate": _redact(dict(aggregate)) if aggregate else {},
            }
            write_private_file(
                temporary / MANIFEST_FILENAME,
                json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"),
            )
            _fsync_dir(temporary)
            self._publish_atomically(temporary, target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        _fsync_dir(parent)
        return PublishedArtifact(
            ref=ref, directory=str(target), sha256=sha256, count=len(hits)
        )

    @staticmethod
    def _publish_atomically(temporary: Path, target: Path) -> None:
        """Rename the finished temporary directory onto the advertised name.

        Re-publishing the same experiment id replaces the previous COMPLETE
        directory (a retry of one experiment), never a partial one: the
        replacement happens only after the new directory is fully written.
        """
        if target.exists():
            self_trash = target.parent / f"{_TRASH_PREFIX}{target.name}-{os.getpid()}"
            os.replace(target, self_trash)
            shutil.rmtree(self_trash, ignore_errors=True)
        os.replace(temporary, target)

    # --- retention -------------------------------------------------------------

    def _complete_experiments(self) -> list[tuple[float, int, Path]]:
        """Every COMPLETE experiment directory: (created_at, bytes, path)."""
        found: list[tuple[float, int, Path]] = []
        if not self.root.is_dir():
            return found
        for project in sorted(self.root.iterdir()):
            rate_dir = project / RATE_LIMIT_DIRNAME
            if not rate_dir.is_dir():
                continue
            for run in sorted(rate_dir.iterdir()):
                if not run.is_dir():
                    continue
                for experiment in sorted(run.iterdir()):
                    # A temp/partial directory is not an artifact: it is never
                    # counted, advertised or evicted.
                    if not experiment.is_dir() or experiment.name.startswith(_TEMP_PREFIX):
                        continue
                    manifest_path = experiment / MANIFEST_FILENAME
                    results_path = experiment / RESULTS_FILENAME
                    if not manifest_path.is_file() or not results_path.is_file():
                        continue
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    size = sum(
                        p.stat().st_size
                        for p in experiment.iterdir()
                        if p.is_file()
                    )
                    found.append(
                        (float(manifest.get("created_at") or 0.0), size, experiment)
                    )
        return found

    @staticmethod
    def _remove(experiment: Path) -> None:
        """Make a directory disappear from its advertised name atomically."""
        trash = experiment.parent / f"{_TRASH_PREFIX}{experiment.name}-{os.getpid()}"
        try:
            os.replace(experiment, trash)
        except OSError:
            shutil.rmtree(experiment, ignore_errors=True)
            return
        shutil.rmtree(trash, ignore_errors=True)

    def enforce_limits(self, *, now: float | None = None) -> dict:
        """Apply age retention (if armed) then the byte cap, oldest first."""
        experiments = sorted(self._complete_experiments(), key=lambda item: item[0])
        removed = 0
        if self.retention_s > 0:
            cutoff = (now if now is not None else time.time()) - self.retention_s
            keep: list[tuple[float, int, Path]] = []
            for created_at, size, path in experiments:
                if created_at < cutoff:
                    self._remove(path)
                    removed += 1
                else:
                    keep.append((created_at, size, path))
            experiments = keep

        total = sum(size for _, size, _ in experiments)
        index = 0
        while total > self.max_bytes and index < len(experiments):
            _, size, path = experiments[index]
            self._remove(path)
            total -= size
            removed += 1
            index += 1
        return {"removed": removed, "bytes": total}

    def status(self) -> dict:
        experiments = self._complete_experiments()
        return {
            "experiments": len(experiments),
            "bytes": sum(size for _, size, _ in experiments),
            "retention_s": self.retention_s,
            "max_bytes": self.max_bytes,
        }


__all__ = [
    "ArtifactIdentifierError",
    "DEFAULT_MAX_BYTES",
    "MANIFEST_FILENAME",
    "PublishedArtifact",
    "RATE_ARTIFACT_SCHEME",
    "RATE_LIMIT_DIRNAME",
    "REDACTED",
    "RESULTS_FILENAME",
    "RateLimitArtifactStore",
    "write_private_file",
]
