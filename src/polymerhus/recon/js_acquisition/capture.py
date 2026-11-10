"""Private staging for JavaScript response bytes observed by Steel."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from polymerhus.app.data_root import project_dir, validate_path_component

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class CaptureLimits:
    max_file_bytes: int = 8 * 1024 * 1024
    max_run_bytes: int = 64 * 1024 * 1024


def _lock_for(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[path] = lock
        return lock


def _used_bytes(manifest: dict) -> int:
    blobs: dict[str, int] = {}
    for occurrence in manifest.setdefault("occurrences", {}).values():
        if occurrence.get("status") != "stored":
            continue
        ref = str(occurrence.get("blob_ref") or "")
        if ref:
            blobs[ref] = int(occurrence.get("size") or 0)
    return sum(blobs.values())


class SteelCaptureStore:
    def __init__(
        self,
        *,
        root: str | Path | None = None,
        limits: CaptureLimits | None = None,
    ) -> None:
        self._root = root
        self._limits = limits or CaptureLimits()

    def _base_dir(self, project_id: str, run_id: str) -> Path:
        validate_path_component(run_id, "run_id")
        return (
            project_dir(project_id, "recon/js_analysis", root=self._root)
            / run_id
            / "captures"
        )

    def _manifest_path(self, project_id: str, run_id: str) -> Path:
        return self._base_dir(project_id, run_id) / "manifest.json"

    def _empty(self) -> dict:
        return {
            "schema_version": 1,
            "run": {
                "created_at": 0,
                "last_access_at": 0,
                "status": "active",
            },
            "temporary": {
                "max_bytes": self._limits.max_run_bytes,
                "used_bytes": 0,
            },
            "occurrences": {},
        }

    def _read(self, path: Path) -> dict:
        if not path.is_file():
            return self._empty()
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else self._empty()

    def _write_manifest(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        fd, temp_name = tempfile.mkstemp(
            dir=path.parent, prefix=".captures.", suffix=".tmp"
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @contextmanager
    def _locked(self, manifest_path: Path):
        lock = _lock_for(manifest_path)
        with lock:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with manifest_path.with_suffix(".lock").open(
                "a+", encoding="utf-8"
            ) as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _transaction(
        self,
        project_id: str,
        run_id: str,
        mutate: Callable[[dict], None],
        *,
        touch: bool = True,
    ):
        path = self._manifest_path(project_id, run_id)
        with self._locked(path):
            value = self._read(path)
            mutate(value)
            if touch:
                now = int(time.time())
                run = value.setdefault("run", {})
                run.setdefault("created_at", now)
                run["last_access_at"] = now
                run["status"] = "active"
            value["temporary"]["max_bytes"] = self._limits.max_run_bytes
            value["temporary"]["used_bytes"] = _used_bytes(value)
            self._write_manifest(path, value)
            return value

    @staticmethod
    def _capture_id(
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        crawl_id: str,
        sequence: int,
        exact_url: str,
        status: int,
        digest: str | None,
        reason: str | None,
    ) -> str:
        value = (
            f"{project_id}\0{run_id}\0{pod_id}\0{crawl_id}\0{sequence}\0"
            f"{exact_url}\0{status}\0{digest or ''}\0{reason or ''}"
        )
        return "cap_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    def _record(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        crawl_id: str,
        auth_context_ref: str | None,
        exact_url: str,
        status: int,
        content_type: str | None,
        sequence: int,
        digest: str | None,
        size: int,
        body: bytes | None,
        reason: str | None,
        sourcemap_header: str | None = None,
        x_sourcemap_header: str | None = None,
    ) -> dict:
        blob_ref = f"blobs/{digest}.js" if digest else None
        occurrence = {
            "capture_id": self._capture_id(
                project_id=project_id,
                run_id=run_id,
                pod_id=pod_id,
                crawl_id=crawl_id,
                sequence=sequence,
                exact_url=exact_url,
                status=status,
                digest=digest,
                reason=reason,
            ),
            "pod_id": pod_id,
            "crawl_id": crawl_id,
            "auth_context_ref": auth_context_ref or None,
            "exact_url": exact_url,
            "status_code": status,
            "content_type": content_type,
            "size": size if body is not None else None,
            "sha256": digest,
            "blob_ref": blob_ref,
            "sequence": sequence,
            "captured_at": int(time.time()),
            "status": "stored" if body is not None else "gap",
            "failure_reason": reason,
            "sourcemap_header": sourcemap_header,
            "x_sourcemap_header": x_sourcemap_header,
            "lead_ids": [],
            "active_lead_ids": [],
        }
        result = dict(occurrence)

        def mutate(manifest: dict) -> None:
            nonlocal result
            occurrences = manifest.setdefault("occurrences", {})
            if body is not None and digest:
                existing_blobs = {
                    item.get("blob_ref")
                    for item in occurrences.values()
                    if item.get("status") == "stored"
                }
                if blob_ref not in existing_blobs and (
                    _used_bytes(manifest) + size > self._limits.max_run_bytes
                ):
                    result.update(
                        status="gap",
                        failure_reason="run_capture_limit_exceeded",
                        blob_ref=None,
                        sha256=digest,
                        size=None,
                    )
                else:
                    blob_path = (
                        self._base_dir(project_id, run_id)
                        / "blobs"
                        / f"{digest}.js"
                    )
                    if not blob_path.is_file():
                        self._write_blob(blob_path, body)
            occurrences[result["capture_id"]] = result

        self._transaction(project_id, run_id, mutate)
        return result

    @staticmethod
    def _write_blob(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def record_gap(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        crawl_id: str,
        auth_context_ref: str | None,
        exact_url: str,
        status: int,
        content_type: str | None,
        reason: str,
        sequence: int,
        sourcemap_header: str | None = None,
        x_sourcemap_header: str | None = None,
    ) -> dict:
        return self._record(
            project_id=project_id,
            run_id=run_id,
            pod_id=pod_id,
            crawl_id=crawl_id,
            auth_context_ref=auth_context_ref,
            exact_url=exact_url,
            status=status,
            content_type=content_type,
            sequence=sequence,
            digest=None,
            size=0,
            body=None,
            reason=reason,
            sourcemap_header=sourcemap_header,
            x_sourcemap_header=x_sourcemap_header,
        )

    def record_bytes(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        crawl_id: str,
        auth_context_ref: str | None,
        exact_url: str,
        status: int,
        content_type: str | None,
        body: bytes,
        sequence: int,
        sourcemap_header: str | None = None,
        x_sourcemap_header: str | None = None,
    ) -> dict:
        if len(body) > self._limits.max_file_bytes:
            return self.record_gap(
                project_id=project_id,
                run_id=run_id,
                pod_id=pod_id,
                crawl_id=crawl_id,
                auth_context_ref=auth_context_ref,
                exact_url=exact_url,
                status=status,
                content_type=content_type,
                reason="file_too_large",
                sequence=sequence,
                sourcemap_header=sourcemap_header,
                x_sourcemap_header=x_sourcemap_header,
            )
        digest = hashlib.sha256(body).hexdigest()
        return self._record(
            project_id=project_id,
            run_id=run_id,
            pod_id=pod_id,
            crawl_id=crawl_id,
            auth_context_ref=auth_context_ref,
            exact_url=exact_url,
            status=status,
            content_type=content_type,
            sequence=sequence,
            digest=digest,
            size=len(body),
            body=body,
            reason=None,
            sourcemap_header=sourcemap_header,
            x_sourcemap_header=x_sourcemap_header,
        )

    def find_by_url(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str | None = None,
        auth_context_ref: str | None,
        exact_url: str,
    ) -> list[dict]:
        path = self._manifest_path(project_id, run_id)
        with self._locked(path):
            manifest = self._read(path)
        return sorted(
            (
                dict(occurrence)
                for occurrence in manifest.get("occurrences", {}).values()
                if occurrence.get("exact_url") == exact_url
                and (pod_id is None or occurrence.get("pod_id") == pod_id)
                and (occurrence.get("auth_context_ref") or None)
                == (auth_context_ref or None)
            ),
            key=lambda item: int(item.get("sequence") or 0),
        )

    def link_leads(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        auth_context_ref: str | None,
        exact_url: str,
        lead_ids: list[str],
    ) -> None:
        def mutate(manifest: dict) -> None:
            for occurrence in manifest.get("occurrences", {}).values():
                if (
                    occurrence.get("exact_url") == exact_url
                    and occurrence.get("pod_id") == pod_id
                    and (occurrence.get("auth_context_ref") or None)
                    == (auth_context_ref or None)
                ):
                    occurrence["lead_ids"] = sorted(
                        set(occurrence.get("lead_ids") or []) | set(lead_ids)
                    )
                    occurrence["active_lead_ids"] = sorted(
                        set(occurrence.get("active_lead_ids") or [])
                        | set(lead_ids)
                    )

        self._transaction(project_id, run_id, mutate)

    def find_by_lead(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        auth_context_ref: str | None,
        exact_url: str,
        lead_id: str,
    ) -> list[dict]:
        path = self._manifest_path(project_id, run_id)
        with self._locked(path):
            manifest = self._read(path)
            run = manifest.setdefault("run", {})
            run.setdefault("created_at", int(time.time()))
            run["last_access_at"] = int(time.time())
            run["status"] = "active"
            self._write_manifest(path, manifest)
        return sorted(
            (
                dict(occurrence)
                for occurrence in manifest.get("occurrences", {}).values()
                if occurrence.get("pod_id") == pod_id
                and occurrence.get("exact_url") == exact_url
                and (occurrence.get("auth_context_ref") or None)
                == (auth_context_ref or None)
                and lead_id in (occurrence.get("lead_ids") or [])
            ),
            key=lambda item: int(item.get("sequence") or 0),
        )

    def release_lead(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        lead_id: str,
    ) -> dict:
        released = 0

        def mutate(manifest: dict) -> None:
            nonlocal released
            for occurrence in manifest.get("occurrences", {}).values():
                if occurrence.get("pod_id") != pod_id:
                    continue
                if lead_id not in (occurrence.get("lead_ids") or []):
                    continue
                active = set(occurrence.get("active_lead_ids") or [])
                active.discard(lead_id)
                occurrence["active_lead_ids"] = sorted(active)
                occurrence["released_at"] = int(time.time())
                released += 1

        self._transaction(project_id, run_id, mutate)
        return {"released_occurrences": released}

    def release_consumed(self, *, project_id: str, run_id: str, context_ref=None) -> dict:
        """Release acknowledged transfers only; active/pending/shared bytes survive.

        No expiry or presumed cancellation: an unlinked response may still need
        intake association and is never reclaimed here. Archive bytes are disjoint.
        """
        path=self._manifest_path(project_id,run_id)
        if not path.exists():
            return {'deleted_blobs':0,'released_occurrences':0}
        with self._locked(path):
            manifest=self._read(path)
            occurrences=manifest.get('occurrences') or {}
            candidates=set(); released=0
            for occurrence in occurrences.values():
                if context_ref is not None and (occurrence.get('auth_context_ref') or '') != context_ref:
                    continue
                if occurrence.get('status')!='stored' or not occurrence.get('lead_ids') or occurrence.get('active_lead_ids'):
                    continue
                blob=occurrence.get('blob_ref')
                if blob: candidates.add(blob)
                occurrence.update(status='released',released_blob_ref=blob,blob_ref=None,
                    failure_reason='transferred_to_verified_work',released_at=int(time.time()))
                released+=1
            active={o.get('blob_ref') for o in occurrences.values() if o.get('status')=='stored'}
            deleted=0
            for blob in candidates-active:
                target=self._base_dir(project_id,run_id)/blob
                if target.is_file(): target.unlink(); deleted+=1
            manifest['temporary']['used_bytes']=_used_bytes(manifest)
            self._write_manifest(path,manifest)
            return {'deleted_blobs':deleted,'released_occurrences':released}

    def cleanup_expired(
        self,
        *,
        project_id: str,
        run_id: str,
        ttl_s: int,
        now: int | None = None,
        run_active: bool = True,
    ) -> dict:
        """Release an inactive run's staging area after its TTL.

        The default is deliberately conservative. A caller that has established
        that an inactive run is abandoned must pass ``run_active=False``;
        unconsumed ``active_lead_ids`` cannot then keep that run alive forever.
        """
        path = self._manifest_path(project_id, run_id)
        current_time = int(time.time()) if now is None else int(now)
        with self._locked(path):
            manifest = self._read(path)
            occurrences = manifest.get("occurrences", {})
            last_access = int(
                (manifest.get("run") or {}).get("last_access_at") or 0
            )
            if run_active or current_time - last_access < max(0, int(ttl_s)):
                return {"deleted_blobs": 0, "released_occurrences": 0}

            blobs_to_delete: set[str] = set()
            released = 0
            for occurrence in occurrences.values():
                if occurrence.get("status") != "stored":
                    continue
                blob_ref = str(occurrence.get("blob_ref") or "")
                if blob_ref:
                    blobs_to_delete.add(blob_ref)
                occurrence["released_blob_ref"] = blob_ref or None
                occurrence["blob_ref"] = None
                occurrence["status"] = "released"
                occurrence["failure_reason"] = "released_after_expiry"
                occurrence["released_at"] = current_time
                released += 1

            deleted = 0
            for blob_ref in sorted(blobs_to_delete):
                path_to_delete = self._base_dir(project_id, run_id) / blob_ref
                if path_to_delete.is_file():
                    path_to_delete.unlink()
                    deleted += 1
            manifest.setdefault("run", {})["status"] = "expired"
            manifest["temporary"]["max_bytes"] = self._limits.max_run_bytes
            manifest["temporary"]["used_bytes"] = _used_bytes(manifest)
            self._write_manifest(path, manifest)
            return {
                "deleted_blobs": deleted,
                "released_occurrences": released,
            }

    def read_bytes(
        self,
        *,
        project_id: str,
        run_id: str,
        occurrence: dict,
    ) -> bytes:
        if occurrence.get("status") != "stored":
            raise ValueError(str(occurrence.get("failure_reason") or "capture_unavailable"))
        blob_ref = str(occurrence.get("blob_ref") or "")
        if not blob_ref:
            raise ValueError("capture_blob_missing")
        path = self._base_dir(project_id, run_id) / blob_ref
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != occurrence.get("sha256") or len(body) != occurrence.get("size"):
            raise ValueError("capture_hash_or_size_mismatch")
        return body
