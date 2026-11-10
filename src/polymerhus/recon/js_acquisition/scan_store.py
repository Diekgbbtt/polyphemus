"""Private, atomic persistence for redacted jsluice scan candidates."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from polymerhus.app.data_root import project_dir, validate_path_component
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.scan_worker import (
    CANDIDATE_SCHEMA_VERSION,
    candidate_id_for,
    scan_key_for,
)

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_MAX_ENVELOPE_BYTES = 15000
_MAX_CANDIDATE_BYTES = 4096
_MODES = ("urls", "secrets")


class ScanStoreError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _lock_for(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[path] = lock
        return lock


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate_candidate(candidate: dict, *, mode: str, source_sha256: str) -> None:
    if not isinstance(candidate, dict):
        raise ScanStoreError("invalid_scan_candidate")
    if candidate.get("mode") != mode:
        raise ScanStoreError("scan_mode_mismatch")
    if candidate.get("source_sha256") != source_sha256:
        raise ScanStoreError("scan_candidate_source_mismatch")
    if candidate.get("candidate_id") != candidate_id_for(candidate):
        raise ScanStoreError("invalid_candidate_id")
    if len(
        json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
    ) > _MAX_CANDIDATE_BYTES:
        raise ScanStoreError("scan_candidate_too_large")
    if mode == "urls":
        allowed = {
            "candidate_id",
            "mode",
            "source_sha256",
            "record_locator",
            "redacted_url",
            "url_truncated",
            "candidate_schema_version",
            "safe_metadata",
        }
        if set(candidate) - allowed:
            raise ScanStoreError("unexpected_candidate_field")
        metadata = candidate.get("safe_metadata")
        if not isinstance(metadata, dict):
            raise ScanStoreError("invalid_candidate_metadata")
        if set(metadata) - {
            "kind",
            "method",
            "query_param_names",
            "body_param_names",
            "method_truncated",
            "parameter_names_limited",
        }:
            raise ScanStoreError("unexpected_candidate_metadata")
    else:
        allowed = {
            "candidate_id",
            "mode",
            "source_sha256",
            "record_locator",
            "secret_kind",
            "severity",
            "secret_fingerprint",
            "secret_hash_algorithm",
            "candidate_schema_version",
        }
        if set(candidate) - allowed:
            raise ScanStoreError("unexpected_candidate_field")


def _overall_status(modes: dict) -> str:
    statuses = [
        modes.get(mode, {}).get("status")
        for mode in _MODES
    ]
    if statuses == ["complete", "complete"]:
        return "complete"
    if all(status == "failed" for status in statuses):
        return "failed"
    return "partial"


def _load_candidate_file(path: Path, source_sha256: str) -> list[dict]:
    if not path.is_file():
        raise ScanStoreError("scan_candidate_file_missing")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ScanStoreError("scan_candidate_file_limit")
    records = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            raise ScanStoreError("scan_candidate_file_invalid") from None
        if not isinstance(item, dict):
            raise ScanStoreError("scan_candidate_file_invalid")
        item_mode = str(item.get("mode") or "")
        _validate_candidate(
            item,
            mode=item_mode,
            source_sha256=source_sha256,
        )
        records.append(item)
    return records


class ScanStore:
    def __init__(self, *, root=None) -> None:
        self._root = root

    def _run_dir(self, project_id: str, run_id: str) -> Path:
        validate_path_component(run_id, "run_id")
        return project_dir(
            project_id,
            "recon/js_analysis",
            root=self._root,
        ) / run_id

    def _manifest(self, project_id: str, run_id: str) -> AcquisitionManifest:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=64 * 1024 * 1024,
        )

    def _lock_path(self, project_id: str, run_id: str) -> Path:
        return self._run_dir(project_id, run_id) / "scans" / ".scan.lock"

    @contextmanager
    def _locked(self, project_id: str, run_id: str):
        path = self._lock_path(project_id, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock_for(path):
            with path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _acquired_record(manifest: dict, lead_id: str, context_ref: str) -> dict:
        record = (manifest.get("leads") or {}).get(lead_id)
        if not record or record.get("status") != "acquired" or not record.get(
            "available"
        ):
            raise ScanStoreError("lead_not_acquired")
        if (record.get("context_ref") or "") != (context_ref or ""):
            raise ScanStoreError("scan_context_mismatch")
        if not record.get("work_file_ref") or not record.get("sha256"):
            raise ScanStoreError("scan_input_unavailable")
        return record

    def work_input(
        self,
        *,
        project_id: str,
        run_id: str,
        lead_id: str,
        context_ref: str,
    ) -> dict:
        record = self._acquired_record(
            self._manifest(project_id, run_id).get(),
            lead_id,
            context_ref,
        )
        return {
            "lead_id": lead_id,
            "context_ref": context_ref,
            "run_id": run_id,
            "work_file_ref": record["work_file_ref"],
            "sha256": record["sha256"],
            "size": int(record["size"]),
        }

    def submit_mode(
        self,
        *,
        project_id: str,
        run_id: str,
        lead_id: str,
        context_ref: str,
        result: dict,
        mode: str,
    ) -> dict:
        if mode not in _MODES:
            raise ScanStoreError("unsupported_scan_mode")
        if not isinstance(result, dict):
            raise ScanStoreError("invalid_scan_result")
        if result.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
            raise ScanStoreError("incompatible_candidate_projection")
        source = result.get("source") or {}
        source_sha = str(source.get("sha256") or "")
        source_size = int(source.get("size") or 0)
        binary = result.get("binary") or {}
        options = result.get("options") or {}
        pattern = str(result.get("pattern_fingerprint") or "")
        expected_key = scan_key_for(
            source_sha256=source_sha,
            binary=binary,
            options=options,
            pattern_fingerprint=pattern,
        )
        if result.get("scan_key") != expected_key:
            raise ScanStoreError("scan_key_mismatch")
        mode_state = (result.get("modes") or {}).get(mode)
        if not isinstance(mode_state, dict):
            raise ScanStoreError("scan_mode_missing")

        incoming = [
            candidate
            for candidate in result.get("candidates") or []
            if isinstance(candidate, dict) and candidate.get("mode") == mode
        ]
        for candidate in incoming:
            _validate_candidate(
                candidate,
                mode=mode,
                source_sha256=source_sha,
            )
        submission_id = hashlib.sha256(
            json.dumps(
                {
                    "scan_key": expected_key,
                    "mode": mode,
                    "state": mode_state,
                    "candidates": incoming,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        manifest = self._manifest(project_id, run_id)
        with self._locked(project_id, run_id):
            current_manifest = manifest.get()
            acquired = self._acquired_record(
                current_manifest,
                lead_id,
                context_ref,
            )
            if (
                acquired.get("sha256") != source_sha
                or int(acquired.get("size") or 0) != source_size
            ):
                raise ScanStoreError("scan_source_mismatch")

            scans = current_manifest.setdefault("scans", {})
            existing = dict(scans.get(expected_key) or {})
            existing_modes = dict(existing.get("modes") or {})
            existing_submissions = dict(existing.get("submissions") or {})
            candidate_file = Path("scans") / f"{expected_key}.jsonl"
            path = self._run_dir(project_id, run_id) / candidate_file
            if (
                {"lead_id": lead_id, "context_ref": context_ref or ""} in (existing.get("context_links") or [])
                and existing_submissions.get(mode, {}).get("submission_id")
                == submission_id
            ):
                try:
                    _load_candidate_file(path, source_sha)
                except ScanStoreError:
                    pass
                else:
                    return {
                        "scan_key": expected_key,
                        "submission_id": submission_id,
                        "overall_status": existing.get("status", "partial"),
                        "idempotent": True,
                    }

            retained: list[dict] = []
            if path.is_file():
                try:
                    retained = [
                        item
                        for item in _load_candidate_file(path, source_sha)
                        if item.get("mode") != mode
                    ]
                except ScanStoreError:
                    retained = []

            previous_mode = existing_modes.get(mode) or {}
            should_replace = not (
                previous_mode.get("status") == "complete"
                and mode_state.get("status") != "complete"
            )
            if should_replace:
                existing_modes[mode] = dict(mode_state)
                existing_submissions[mode] = {
                    "submission_id": submission_id,
                    "candidate_count": len(incoming),
                }
                retained.extend(incoming)
                retained.sort(
                    key=lambda item: (
                        item.get("mode", ""),
                        item.get("record_locator", ""),
                    )
                )
                body = "".join(
                    json.dumps(item, sort_keys=True, separators=(",", ":"))
                    + "\n"
                    for item in retained
                )
                _atomic_text(path, body)

            now = int(__import__("time").time())
            overall = _overall_status(existing_modes)
            scan_record = {
                **existing,
                "schema_version": 1,
                "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                "scan_key": expected_key,
                "source_sha256": source_sha,
                "size": source_size,
                "binary": binary,
                "options": options,
                "pattern_fingerprint": pattern,
                "limits": result.get("limits") or {},
                "modes": existing_modes,
                "submissions": existing_submissions,
                "status": overall,
                "candidate_file": str(candidate_file),
                "candidate_count": len(retained),
                "created_at": int(existing.get("created_at") or now),
                "updated_at": now,
            }
            context_links = {
                (str(item.get("lead_id")), str(item.get("context_ref") or ""))
                for item in scan_record.get("context_links") or []
            }
            context_links.add((lead_id, context_ref or ""))
            scan_record["context_links"] = [
                {"lead_id": item[0], "context_ref": item[1]}
                for item in sorted(
                    context_links,
                    key=lambda pair: (pair[1], pair[0]),
                )
            ]

            def mutate(value: dict) -> None:
                current_lead = self._acquired_record(
                    value,
                    lead_id,
                    context_ref,
                )
                if (
                    current_lead.get("sha256") != source_sha
                    or int(current_lead.get("size") or 0) != source_size
                ):
                    raise ScanStoreError("scan_source_mismatch")
                value.setdefault("scans", {})[expected_key] = scan_record
                current_lead["scan"] = {
                    "scan_key": expected_key,
                    "status": overall,
                    "modes": existing_modes,
                    "candidate_file": str(candidate_file),
                }

            manifest.update(mutate)
            return {
                "scan_key": expected_key,
                "submission_id": submission_id,
                "overall_status": overall,
                "idempotent": not should_replace,
            }

    def find_reusable(
        self,
        *,
        project_id: str,
        run_id: str,
        source_sha256: str,
        binary: dict,
        options: dict,
        pattern_fingerprint: str,
    ) -> dict | None:
        scan_key = scan_key_for(
            source_sha256=source_sha256,
            binary=binary,
            options=options,
            pattern_fingerprint=pattern_fingerprint,
        )
        record = (self._manifest(project_id, run_id).get().get("scans") or {}).get(
            scan_key
        )
        if not record or record.get("status") != "complete" or record.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
            return None
        candidate_file = str(record.get("candidate_file") or "")
        if candidate_file != f"scans/{scan_key}.jsonl" or not re.fullmatch("[0-9a-f]{64}", scan_key):
            return None
        try:
            _load_candidate_file(
                self._run_dir(project_id, run_id) / candidate_file,
                str(record.get("source_sha256") or ""),
            )
        except ScanStoreError:
            return None
        return dict(record)

    def get_scan(
        self,
        *,
        project_id: str,
        run_id: str,
        scan_key: str,
    ) -> dict | None:
        record = (self._manifest(project_id, run_id).get().get("scans") or {}).get(
            scan_key
        )
        return dict(record) if record else None

    def link_lead(
        self,
        *,
        project_id: str,
        run_id: str,
        lead_id: str,
        context_ref: str,
        scan_key: str,
    ) -> dict:
        manifest = self._manifest(project_id, run_id)
        with self._locked(project_id, run_id):
            current = manifest.get()
            acquired = self._acquired_record(current, lead_id, context_ref)
            scan = (current.get("scans") or {}).get(scan_key)
            if not scan:
                raise ScanStoreError("scan_missing")
            if scan.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
                raise ScanStoreError("incompatible_candidate_projection")
            if scan.get("source_sha256") != acquired.get("sha256"):
                raise ScanStoreError("scan_source_mismatch")
            candidate_file = str(scan.get("candidate_file") or "")
            if candidate_file != f"scans/{scan_key}.jsonl" or not re.fullmatch("[0-9a-f]{64}", scan_key):
                raise ScanStoreError("scan_candidate_file_invalid")
            _load_candidate_file(
                self._run_dir(project_id, run_id) / candidate_file,
                str(scan.get("source_sha256") or ""),
            )

            links = {
                (str(item.get("lead_id")), str(item.get("context_ref") or ""))
                for item in scan.get("context_links") or []
            }
            links.add((lead_id, context_ref or ""))
            updated = {
                **scan,
                "context_links": [
                    {"lead_id": item[0], "context_ref": item[1]}
                    for item in sorted(
                        links,
                        key=lambda pair: (pair[1], pair[0]),
                    )
                ],
            }

            def mutate(value: dict) -> None:
                lead = self._acquired_record(value, lead_id, context_ref)
                value.setdefault("scans", {})[scan_key] = updated
                lead["scan"] = {
                    "scan_key": scan_key,
                    "status": scan["status"],
                    "modes": scan["modes"],
                    "candidate_file": scan["candidate_file"],
                }

            manifest.update(mutate)
            return {
                "scan_key": scan_key,
                "status": scan["status"],
                "reused": True,
            }

    def snapshot(self, *, project_id: str, run_id: str, context_ref: str,
                 max_scans: int = 64, max_candidates: int = 4096,
                 max_bytes: int = 8 * 1024 * 1024) -> dict:
        """Read all eligible saved occurrences, independently of narrated behaviours.

        Sharing scan bytes does not authorize another occurrence. No work-file
        availability is required: only the matching saved acquisition identity.
        Old projections stay private evidence; publication requires a normal
        verified-file rescan, never SHA-256-to-SHA-1 relabelling.
        """
        if min(max_scans, max_candidates, max_bytes) <= 0:
            raise ValueError("snapshot limits must be positive")
        result = {'occurrences': [], 'gaps': []}
        with self._locked(project_id, run_id):
            manifest_store = self._manifest(project_id, run_id)
            if manifest_store.path.is_file() and manifest_store.path.stat().st_size > max_bytes:
                return {**result, 'gaps': ['manifest_limit']}
            try:
                manifest = manifest_store.get()
            except (OSError, ValueError):
                return {**result, 'gaps': ['manifest_invalid']}
            total = 0
            byte_count = 0
            scan_count = 0
            for key, scan in sorted((manifest.get('scans') or {}).items()):
                links = [link for link in scan.get('context_links') or []
                         if (link.get('context_ref') or '') == context_ref]
                if not links:
                    continue
                if scan_count >= max_scans:
                    result['gaps'].append('scan_limit')
                    break
                scan_count += 1
                if scan.get('candidate_schema_version') != CANDIDATE_SCHEMA_VERSION:
                    result['gaps'].append('incompatible_candidate_projection')
                    continue
                if not re.fullmatch('[0-9a-f]{64}', key) or scan.get('candidate_file') != f'scans/{key}.jsonl':
                    result['gaps'].append('scan_candidate_file_invalid')
                    continue
                path = self._run_dir(project_id, run_id) / scan['candidate_file']
                try:
                    if path.is_file():
                        byte_count += path.stat().st_size
                    if byte_count > max_bytes:
                        result['gaps'].append('scan_bytes_limit')
                        break
                    candidates = _load_candidate_file(path, scan.get('source_sha256') or '')
                    if len(candidates) != scan.get('candidate_count'):
                        raise ScanStoreError('scan_candidate_count_mismatch')
                except (OSError, ValueError) as exc:
                    result['gaps'].append(getattr(exc, 'reason', 'scan_candidate_file_invalid'))
                    continue
                if scan.get('status') != 'complete':
                    result['gaps'].append('partial_scan')
                for link in sorted(links, key=lambda x: x['lead_id']):
                    acquired = (manifest.get('leads') or {}).get(link['lead_id']) or {}
                    if (acquired.get('context_ref') or '') != context_ref or acquired.get('sha256') != scan.get('source_sha256'):
                        result['gaps'].append('scan_occurrence_source_mismatch')
                        continue
                    remaining = max_candidates - total
                    selected = candidates[:remaining]
                    if len(selected) < len(candidates):
                        result['gaps'].append('candidate_limit')
                    result['occurrences'].append({
                        'lead_id': link['lead_id'], 'context_ref': context_ref,
                        'scan_key': key, 'source_sha256': scan['source_sha256'],
                        'candidate_schema_version': scan['candidate_schema_version'],
                        'submissions': scan.get('submissions') or {},
                        'status': scan.get('status'), 'modes': scan.get('modes') or {},
                        'final_url': acquired.get('final_url') or '',
                        'candidates': selected,
                    })
                    total += len(selected)
                    if total >= max_candidates:
                        result['gaps'].append('candidate_limit')
                        break
                if total >= max_candidates:
                    break
            if not result['occurrences']:
                result['gaps'].append('no_eligible_scans')
        result['gaps'] = sorted(set(result['gaps']))
        return result

    @staticmethod
    def _cursor(scan_key: str, lead_id: str, mode: str, offset: int) -> str:
        body = json.dumps(
            {"offset": offset},
            separators=(",", ":"),
        ).encode()
        binding = f"{scan_key}\0{lead_id}\0{mode}".encode()
        digest = hashlib.sha256(binding + body).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")

    @staticmethod
    def _cursor_offset(
        cursor: str | None,
        *,
        scan_key: str,
        lead_id: str,
        mode: str,
    ) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = base64.urlsafe_b64decode(padded.encode())
            body, digest = payload[:-8], payload[-8:]
            binding = f"{scan_key}\0{lead_id}\0{mode}".encode()
            expected = hashlib.sha256(binding + body).digest()[:8]
            if digest != expected:
                raise ValueError
            value = json.loads(body)
            offset = value.get("offset")
            if not isinstance(offset, int) or offset < 0:
                raise ValueError
            return offset
        except (ValueError, TypeError, json.JSONDecodeError):
            raise ScanStoreError("invalid_scan_cursor") from None

    def read(
        self,
        *,
        project_id: str,
        run_id: str,
        lead_id: str,
        mode: str | None = None,
        cursor: str | None = None,
        limit: int = 5,
    ) -> dict:
        if mode is not None and mode not in _MODES:
            raise ScanStoreError("unsupported_scan_mode")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ScanStoreError("invalid_scan_limit")
        limit = min(limit, 10)
        manifest = self._manifest(project_id, run_id).get()
        lead = (manifest.get("leads") or {}).get(lead_id) or {}
        link = lead.get("scan")
        if not link:
            return {
                "lead_id": lead_id,
                "status": "missing",
                "modes": {},
                "candidates": [],
                "next_cursor": None,
                "coverage_gap": "scan_missing",
            }
        scan_key = str(link["scan_key"])
        scan = (manifest.get("scans") or {}).get(scan_key) or {}
        candidate_file = str(scan.get("candidate_file") or "")
        if candidate_file != f"scans/{scan_key}.jsonl" or not re.fullmatch("[0-9a-f]{64}", scan_key):
            raise ScanStoreError("scan_candidate_file_invalid")
        offset = self._cursor_offset(
            cursor,
            scan_key=scan_key,
            lead_id=lead_id,
            mode=mode or "",
        )
        path = self._run_dir(project_id, run_id) / candidate_file
        candidates = [
            {**item, "lead_id": lead_id}
            for item in _load_candidate_file(
                path,
                str(scan.get("source_sha256") or ""),
            )
            if mode is None or item.get("mode") == mode
        ]
        window = candidates[offset : offset + limit]
        next_offset = offset + len(window)
        response = {
            "lead_id": lead_id,
            "scan_key": scan_key,
            "source_sha256": scan.get("source_sha256"),
            "status": scan.get("status", "partial"),
            "modes": scan.get("modes") or {},
            "candidate_count": len(candidates),
            "candidates": window,
            "next_cursor": (
                self._cursor(scan_key, lead_id, mode or "", next_offset)
                if next_offset < len(candidates)
                else None
            ),
            "coverage_gap": (
                None
                if scan.get("status") == "complete"
                else "scan_partial_or_failed"
            ),
        }
        while len(json.dumps(response, separators=(",", ":")).encode()) > _MAX_ENVELOPE_BYTES:
            if not response["candidates"]:
                raise ScanStoreError("scan_result_envelope_too_large")
            response["candidates"].pop()
            returned = offset + len(response["candidates"])
            response["next_cursor"] = (
                self._cursor(scan_key, lead_id, mode or "", returned)
                if returned < len(candidates)
                else None
            )
        return response


__all__ = [
    "ScanStore",
    "ScanStoreError",
]
