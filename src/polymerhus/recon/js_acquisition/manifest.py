"""Private, atomic acquisition manifest under recon/js_analysis."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import fcntl

from polymerhus.app.data_root import project_dir, validate_path_component

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[path] = lock
        return lock


def _used_bytes(manifest: dict) -> int:
    files: dict[str, int] = {}
    for record in manifest.setdefault("leads", {}).values():
        if record.get("status") not in {"fetched_pending_work_file", "acquired"}:
            continue
        key = str(
            record.get("work_file_ref")
            or record.get("sha256")
            or record.get("lead_id")
        )
        files[key] = int(record.get("size") or 0)
    recovery = manifest.get("recovery") or {}
    for map_record in (recovery.get("maps") or {}).values():
        digest = str(map_record.get("map_sha256") or "")
        if digest:
            files[f"recovery-map:{digest}"] = int(map_record.get("size") or 0)
    for source in (recovery.get("sources") or {}).values():
        if source.get("status") not in {"pending", "available"}:
            continue
        digest = str(source.get("content_sha256") or "")
        if digest:
            files[f"recovery-source:{digest}"] = int(source.get("size") or 0)
    return sum(files.values())


class AcquisitionManifest:
    def __init__(
        self,
        *,
        project_id: str,
        run_id: str,
        root: str | Path | None,
        max_run_bytes: int,
    ) -> None:
        validate_path_component(run_id, "run_id")
        self._path = (
            project_dir(project_id, "recon/js_analysis", root=root)
            / run_id
            / "manifest.json"
        )
        self._max_run_bytes = max_run_bytes
        self._lock = _lock_for(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def _empty(self) -> dict:
        return {
            "schema_version": 1,
            "temporary": {
                "max_bytes": self._max_run_bytes,
                "used_bytes": 0,
            },
            "leads": {},
        }

    def _read(self) -> dict:
        if not self._path.is_file():
            return self._empty()
        value = json.loads(self._path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else self._empty()

    def _write(self, value: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        fd, temp_name = tempfile.mkstemp(
            dir=self._path.parent, prefix=".manifest.", suffix=".tmp"
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @contextmanager
    def _locked(self):
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.with_suffix(".lock").open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _transaction(self, mutator: Callable[[dict], None]) -> dict:
        with self._locked():
            value = self._read()
            mutator(value)
            value["temporary"]["max_bytes"] = self._max_run_bytes
            value["temporary"]["used_bytes"] = _used_bytes(value)
            self._write(value)
            return value

    def update(self, mutator: Callable[[dict], None]) -> dict:
        return self._transaction(mutator)

    def get(self) -> dict:
        with self._locked():
            return self._read()

    def reserve(
        self,
        *,
        lead_id: str,
        record: dict,
        work_file_ref: str,
        sha256: str,
        size: int,
    ) -> bool:
        reserved = False

        def mutate(value: dict) -> None:
            nonlocal reserved
            leads = value.setdefault("leads", {})
            active_refs = {
                str(item.get("work_file_ref") or item.get("sha256"))
                for item in leads.values()
                if item.get("status")
                in {"fetched_pending_work_file", "acquired"}
                and item.get("lead_id") != lead_id
            }
            already_shared = work_file_ref in active_refs or sha256 in active_refs
            if not already_shared and _used_bytes(value) + size > self._max_run_bytes:
                leads[lead_id] = {
                    **record,
                    "lead_id": lead_id,
                    "status": "failed",
                    "available": False,
                    "failure_reason": "quota_exhausted",
                }
                return
            leads[lead_id] = {
                **record,
                "lead_id": lead_id,
                "status": "fetched_pending_work_file",
                "available": False,
                "failure_reason": None,
                "work_file_ref": work_file_ref,
                "sha256": sha256,
                "size": size,
            }
            reserved = True

        self._transaction(mutate)
        return reserved

    def confirm(
        self,
        *,
        lead_id: str,
        size: int,
        sha256: str,
        work_file_ref: str,
    ) -> str:
        outcome = "confirmation_mismatch"

        def mutate(value: dict) -> None:
            nonlocal outcome
            leads = value.setdefault("leads", {})
            record = leads.get(lead_id) or {}
            matches = (
                record.get("size") == size
                and record.get("sha256") == sha256
                and record.get("work_file_ref") == work_file_ref
            )
            if record.get("status") == "acquired":
                outcome = (
                    "already_acquired" if matches else "confirmation_mismatch"
                )
                return
            if record.get("status") == "fetched_pending_work_file" and matches:
                leads[lead_id] = {
                    **record,
                    "status": "acquired",
                    "available": True,
                    "failure_reason": None,
                }
                outcome = "acquired"
                return
            if record.get("status") == "fetched_pending_work_file":
                leads[lead_id] = {
                    **record,
                    "status": "failed",
                    "available": False,
                    "failure_reason": "confirmation_mismatch",
                }

        self._transaction(mutate)
        return outcome

    def fail(
        self,
        *,
        lead_id: str,
        failure_reason: str,
    ) -> dict:
        result = {
            "status": "failed",
            "keep_work_file": False,
            "reconcile_required": False,
        }

        def mutate(value: dict) -> None:
            leads = value.setdefault("leads", {})
            record = leads.get(lead_id) or {}
            work_ref = str(record.get("work_file_ref") or "")
            if record.get("status") == "acquired":
                leads[lead_id] = {
                    **record,
                    "reconcile_required": True,
                    "reconcile_reason": "late_failure_after_acquired",
                }
                result.update(
                    status="acquired",
                    keep_work_file=True,
                    reconcile_required=True,
                )
                return
            leads[lead_id] = {
                **record,
                "status": "failed",
                "available": False,
                "failure_reason": failure_reason,
            }
            result["keep_work_file"] = bool(
                work_ref
                and any(
                    other.get("status")
                    in {"fetched_pending_work_file", "acquired"}
                    and other.get("work_file_ref") == work_ref
                    and other_lead_id != lead_id
                    for other_lead_id, other in leads.items()
                )
            )

        self._transaction(mutate)
        return result
