"""The per-project, per-target rate-limit posture bucket (#238 follow-up).

Layout: ``<data_root>/<project_id>/rate-limit/<target_key>.yaml``, one file per
measured target. The file is the project's CURRENT posture, readable by every
phase; ``recon_runs.stats["rate_limit"]`` stays the immutable per-run record.
The envelope is ``advisory: true``: the limit is KNOWN, never ENFORCED.

No import-time I/O (CODING_STANDARD section 6); the root is the app-owned
``DATA_ROOT`` resolved through the one layout owner, with an explicit root for
tests (the AuthStore precedent).
"""
from __future__ import annotations

import fnmatch
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from polymerhus.app.data_root import DATA_ROOT, project_dir, validate_path_component
from polymerhus.recon.domain.rate_limit import RateProfile

logger = logging.getLogger(__name__)

POSTURE_VERSION = "rate-limit-posture/v1"
_BUCKET_NAME = "rate-limit"


class PostureWriteError(ValueError):
    """A write that could not land. The caller fails the run loudly."""


class PostureUnreadableError(ValueError):
    """A stored file that exists but cannot be validated. NEVER 'absent'."""


class PostureEnvelope(BaseModel):
    """The on-disk contract, closed like every contract in the repo."""

    model_config = ConfigDict(extra="forbid")

    version: str = POSTURE_VERSION
    source_run_id: str
    advisory: bool = True
    profile: RateProfile


@dataclass(frozen=True)
class PostureRecord:
    """What a reader gets back: the validated profile plus its provenance."""

    target_key: str
    profile: RateProfile
    source_run_id: str
    fresh: bool


_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def host_matches(host: str | None, patterns) -> bool:
    """Whether a request host is this posture's business.

    MIRRORS `kali.http_history.governor.host_matches` BY VALUE - never imported,
    because `kali` is not on the agent image's import path. An empty pattern
    list means "whatever this project sends" (the posture is already
    per-target); a non-empty list is exact match plus shell-style wildcards,
    case-insensitive, mirroring the governor exactly (no trailing-dot
    normalisation beyond the strip the governor performs).
    """
    wanted = tuple(str(pattern).lower() for pattern in (patterns or ()))
    if not wanted:
        return True
    if not host:
        return False
    value = host.strip().lower()
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in wanted)


def _lock_for(project_id: str) -> threading.Lock:
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


def _atomic_write(path: Path, text: str) -> None:
    """Temp file in the same directory + os.replace (the AuthStore precedent)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class RateLimitPostureStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else DATA_ROOT

    def _dir(self, project_id: str) -> Path:
        return project_dir(project_id, _BUCKET_NAME, root=self._root)

    def _path(self, project_id: str, target_key: str) -> Path:
        name = validate_path_component(target_key, "target_key")
        return self._dir(project_id) / f"{name}.yaml"

    def write(
        self, project_id: str, profile: RateProfile, source_run_id: str
    ) -> Path:
        try:
            path = self._path(project_id, profile.target_key)
        except ValueError as exc:
            raise PostureWriteError(str(exc)) from exc
        envelope = PostureEnvelope(source_run_id=source_run_id, profile=profile)
        text = yaml.safe_dump(envelope.model_dump(mode="json"), sort_keys=False)
        with _lock_for(project_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = self._read_envelope(path)
            if existing is not None and existing.profile.measured_at > profile.measured_at:
                logger.warning(
                    "rate posture for %s/%s on disk is newer (%s > %s); keeping it",
                    project_id, profile.target_key,
                    existing.profile.measured_at, profile.measured_at,
                )
                return path
            try:
                _atomic_write(path, text)
            except OSError as exc:
                raise PostureWriteError(
                    f"could not write the rate posture for "
                    f"{project_id}/{profile.target_key}: {exc}"
                ) from exc
        return path

    def _read_envelope(self, path: Path) -> PostureEnvelope | None:
        if not path.exists():
            return None
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - any parse failure is unreadable
            raise PostureUnreadableError(f"{path} is not readable YAML: {exc}") from exc
        try:
            return PostureEnvelope.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - any schema failure is unreadable
            raise PostureUnreadableError(f"{path} failed validation: {exc}") from exc

    def read(self, project_id: str, target_key: str) -> PostureRecord | None:
        envelope = self._read_envelope(self._path(project_id, target_key))
        if envelope is None:
            return None
        return PostureRecord(
            target_key=envelope.profile.target_key,
            profile=envelope.profile,
            source_run_id=envelope.source_run_id,
            fresh=envelope.profile.is_fresh(datetime.now(timezone.utc)),
        )

    def list_targets(self, project_id: str) -> list[str]:
        directory = self._dir(project_id)
        if not directory.is_dir():
            return []
        return sorted(path.stem for path in directory.glob("*.yaml") if path.is_file())

    def resolve(self, project_id: str, host: str) -> PostureRecord | None:
        for target_key in self.list_targets(project_id):
            record = self.read(project_id, target_key)
            if record is not None and host_matches(host, record.profile.host_patterns):
                return record
        return None
