"""Private source-map parsing and recovery contracts."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote_to_bytes, urljoin, urlsplit, urlunsplit

from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest, _used_bytes
from polymerhus.recon.js_intake import JsIntakeReader
from polymerhus.recon.js_intake.redaction import redact_url


class SourceMapParseError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidMapDataURI(ValueError):
    pass


@dataclass(frozen=True)
class SourceMapLink:
    url: str
    kind: str
    annotation_url: str | None = None
    conflict: bool = False


class RecoveryError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RecoveryLimits:
    max_map_bytes: int = 32 * 1024 * 1024
    max_source_bytes: int = 8 * 1024 * 1024
    max_run_bytes: int = 64 * 1024 * 1024
    max_occurrences: int = 5000
    max_section_depth: int = 8
    deadline_s: float = 35.0
    parser_timeout_s: float = 10.0
    max_parser_output_bytes: int = 96 * 1024 * 1024
    max_parser_memory_bytes: int = 384 * 1024 * 1024


@dataclass(frozen=True)
class SourceMapParseLimits:
    max_map_bytes: int = 32 * 1024 * 1024
    max_source_bytes: int = 8 * 1024 * 1024
    max_occurrences: int = 5000
    max_section_depth: int = 8
    parser_timeout_s: float = 10.0
    max_parser_output_bytes: int = 96 * 1024 * 1024
    max_parser_memory_bytes: int = 384 * 1024 * 1024

    def __post_init__(self):
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("source-map parser limits must be positive")


@dataclass(frozen=True)
class ParsedOccurrence:
    section_path: tuple[int, ...]
    source_ordinal: int
    raw_name: str | None
    resolved_source: str | None
    content_state: str
    content: bytes | None
    content_sha256: str | None
    size: int | None


@dataclass(frozen=True)
class ParsedSourceMap:
    map_url: str
    map_sha256: str
    occurrences: tuple[ParsedOccurrence, ...]
    gaps: tuple[str, ...] = ()
    parser_memory_bytes: int | None = None


def artifact_file_name(content_sha256: str) -> str:
    return f"{content_sha256}.js"


def _atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
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


def _source_kind(name: str | None) -> str:
    suffix = Path((name or "").split("?", 1)[0]).suffix.lower()
    return suffix[1:] if suffix else "unknown"


def _redacted_source_name(raw_name: str | None, resolved: str | None) -> str:
    value = raw_name or resolved or "[unknown]"
    redacted = redact_url(value)
    if "://" in redacted:
        parts = urlsplit(redacted)
        value = f"{parts.hostname or '[host]'}{parts.path}"
    else:
        value = redacted.split("?", 1)[0]
    return value[:512] + ("..." if len(value) > 512 else "")


class SourceMapRecovery:
    def __init__(
        self,
        *,
        root=None,
        acquisition,
        limits: RecoveryLimits | None = None,
        parser_fn=None,
    ) -> None:
        self._root = root
        self._acquisition = acquisition
        self._limits = limits or RecoveryLimits()
        self._reader = JsIntakeReader(root=root)
        self._parser_fn = parser_fn or parse_map_bytes

    def _manifest(self, project_id: str, run_id: str) -> AcquisitionManifest:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=self._limits.max_run_bytes,
        )

    def _run_dir(self, project_id: str, run_id: str) -> Path:
        return (
            Path(
                self._manifest(project_id, run_id).path.parent
            )
        )

    def _source_id(
        self,
        *,
        scope,
        lead_id: str,
        map_id: str,
        occurrence: ParsedOccurrence,
    ) -> str:
        value = (
            f"{scope.project_id}\0{scope.run_id}\0{scope.context_ref}\0"
            f"{lead_id}\0{map_id}\0"
            f"{','.join(str(v) for v in occurrence.section_path)}\0"
            f"{occurrence.source_ordinal}"
        )
        return "src_" + hashlib.sha256(value.encode()).hexdigest()[:24]

    def recover_from_source(
        self,
        *,
        reference: str,
        lead_id: str,
        js_bytes: bytes,
    ) -> dict:
        lead, scope = self._reader.get_private(
            reference=reference, lead_id=lead_id
        )
        manifest = self._manifest(scope.project_id, scope.run_id)
        acquired = manifest.get().get("leads", {}).get(lead_id) or {}
        digest = hashlib.sha256(js_bytes).hexdigest()
        if (
            acquired.get("status") != "acquired"
            or not acquired.get("available")
            or acquired.get("sha256") != digest
            or int(acquired.get("size") or 0) != len(js_bytes)
        ):
            raise RecoveryError("acquired_source_mismatch")
        final_js_url = str(
            acquired.get("final_url")
            or lead.get("final_url")
            or lead.get("exact_url")
            or ""
        )
        link = discover_source_map_link(
            js_bytes,
            final_url=final_js_url,
            sourcemap_header=acquired.get("sourcemap_header"),
            x_sourcemap_header=acquired.get("x_sourcemap_header"),
        )
        gaps = []
        if link.conflict:
            gaps.append("sourcemap_header_annotation_conflict")

        current = manifest.get()
        map_bytes = None
        final_map_url = final_js_url
        cached_map = None
        cached_map_priority = -1
        for record in (current.get("recovery", {}).get("maps") or {}).values():
            if record.get("link_url") != link.url:
                continue
            cache = self._run_dir(scope.project_id, scope.run_id) / str(
                record.get("cache_ref") or ""
            )
            if cache.is_file():
                candidate = cache.read_bytes()
                if hashlib.sha256(candidate).hexdigest() == record.get("map_sha256"):
                    priority = int(
                        record.get("refreshed_at")
                        or int(record.get("created_at") or 0) * 1_000_000_000
                    )
                    if priority >= cached_map_priority:
                        cached_map = (
                            candidate,
                            str(record.get("final_url") or final_js_url),
                        )
                        cached_map_priority = priority
        if link.url.startswith("data:"):
            try:
                map_bytes = decode_map_data_uri(
                    link.url, max_bytes=self._limits.max_map_bytes
                )
            except InvalidMapDataURI as exc:
                return self._failed(
                    manifest,
                    lead_id,
                    scope,
                    gaps + [str(exc)],
                )
        else:
            try:
                fetched = self._acquisition.fetch_map(
                    reference=reference,
                    lead_id=lead_id,
                    map_url=link.url,
                    max_bytes=self._limits.max_map_bytes,
                )
            except Exception as exc:
                reason = getattr(exc, "reason", "map_acquisition_failed")
                if link.kind == "guessed" and reason == "http_status_404":
                    reason = "map_not_found"
                if cached_map is None:
                    return self._failed(
                        manifest,
                        lead_id,
                        scope,
                        gaps + [reason],
                    )
                map_bytes, final_map_url = cached_map
                gaps.append("map_refetch_unavailable_cached_snapshot")
                gaps.append(reason)
            else:
                map_bytes = fetched.body
                final_map_url = fetched.final_url

        parser_limits = SourceMapParseLimits(
            max_map_bytes=self._limits.max_map_bytes,
            max_source_bytes=self._limits.max_source_bytes,
            max_occurrences=self._limits.max_occurrences,
            max_section_depth=self._limits.max_section_depth,
            parser_timeout_s=self._limits.parser_timeout_s,
            max_parser_output_bytes=self._limits.max_parser_output_bytes,
            max_parser_memory_bytes=self._limits.max_parser_memory_bytes,
        )
        try:
            parsed = self._parser_fn(
                map_bytes,
                map_url=final_map_url,
                limits=parser_limits,
            )
        except SourceMapParseError as exc:
            return self._failed(
                manifest,
                lead_id,
                scope,
                gaps + [exc.reason],
            )
        gaps.extend(parsed.gaps)
        map_id = "map_" + hashlib.sha256(
            f"{final_map_url}\0{parsed.map_sha256}".encode()
        ).hexdigest()[:24]
        cache_ref = f"recovery/maps/{parsed.map_sha256}.map"
        cache_path = self._run_dir(scope.project_id, scope.run_id) / cache_ref
        if not cache_path.is_file():
            _atomic_bytes(cache_path, map_bytes)

        materialized = []
        for occurrence in parsed.occurrences:
            content = occurrence.content
            state = occurrence.content_state
            failure = None
            if content is None and occurrence.resolved_source:
                source_url = occurrence.resolved_source
                scheme = urlsplit(source_url).scheme.lower()
                if scheme in {"http", "https"}:
                    try:
                        fetched_source = self._acquisition.fetch_missing_source(
                            reference=reference,
                            lead_id=lead_id,
                            source_url=source_url,
                            max_bytes=self._limits.max_source_bytes,
                        )
                        content = fetched_source.body
                        state = "empty" if content == b"" else "text"
                    except Exception as exc:
                        failure = getattr(
                            exc, "reason", "source_acquisition_failed"
                        )
                elif scheme:
                    failure = "virtual_source_unavailable"
            materialized.append((occurrence, content, state, failure))

        prepared = []

        def mutate(value: dict) -> None:
            recovery = value.setdefault("recovery", {})
            maps = recovery.setdefault("maps", {})
            sources = recovery.setdefault("sources", {})
            used = _used_bytes(value)
            size = len(map_bytes)
            map_unique = map_id not in maps
            if map_unique and used + size > self._limits.max_run_bytes:
                return
            maps[map_id] = {
                "map_id": map_id,
                "lead_id": lead_id,
                "context_ref": scope.context_ref,
                "link_url": link.url,
                "link_kind": link.kind,
                "final_url": final_map_url,
                "map_sha256": parsed.map_sha256,
                "size": size,
                "cache_ref": cache_ref,
                "section_depth_limit": self._limits.max_section_depth,
                "parser_memory_bytes": parsed.parser_memory_bytes,
                "gaps": list(dict.fromkeys(gaps)),
                "created_at": int(time.time()),
                "refreshed_at": time.time_ns(),
            }
            used += size if map_unique else 0
            seen_hashes = {
                row.get("content_sha256")
                for row in sources.values()
                if row.get("status") in {"pending", "available"}
            }
            for occurrence, content, state, failure in materialized:
                source_id = self._source_id(
                    scope=scope,
                    lead_id=lead_id,
                    map_id=map_id,
                    occurrence=occurrence,
                )
                content_sha = (
                    hashlib.sha256(content).hexdigest()
                    if content is not None
                    else None
                )
                prior = sources.get(source_id) or {}
                if (
                    content is None
                    and prior.get("status") == "available"
                    and prior.get("object_ref")
                ):
                    prior_path = (
                        self._run_dir(scope.project_id, scope.run_id)
                        / prior["object_ref"]
                    )
                    if prior_path.is_file():
                        candidate = prior_path.read_bytes()
                        if (
                            hashlib.sha256(candidate).hexdigest()
                            == prior.get("content_sha256")
                        ):
                            content = candidate
                            content_sha = hashlib.sha256(content).hexdigest()
                            state = str(prior.get("content_state") or state)
                fits = (
                    content is not None
                    and (
                        content_sha in seen_hashes
                        or used + len(content) <= self._limits.max_run_bytes
                    )
                )
                if content is not None and fits:
                    used += (
                        0 if content_sha in seen_hashes else len(content)
                    )
                    seen_hashes.add(content_sha)
                    status = (
                        "available"
                        if prior.get("status") == "available"
                        else "pending"
                    )
                    failure_reason = None
                    available = status == "available"
                else:
                    status = "failed"
                    failure_reason = failure or (
                        "run_scratch_limit" if content is not None else "content_unavailable"
                    )
                    available = False
                record = {
                    **prior,
                    "source_id": source_id,
                    "lead_id": lead_id,
                    "context_ref": scope.context_ref,
                    "map_id": map_id,
                    "map_sha256": parsed.map_sha256,
                    "final_map_url": final_map_url,
                    "section_path": list(occurrence.section_path),
                    "source_ordinal": occurrence.source_ordinal,
                    "raw_name": occurrence.raw_name,
                    "resolved_source": occurrence.resolved_source,
                    "redacted_name": _redacted_source_name(
                        occurrence.raw_name, occurrence.resolved_source
                    ),
                    "kind": _source_kind(occurrence.raw_name or occurrence.resolved_source),
                    "content_state": state,
                    "content_sha256": content_sha,
                    "size": len(content) if content is not None else None,
                    "object_ref": (
                        f"recovery/objects/{content_sha}.source"
                        if content is not None and fits
                        else None
                    ),
                    "work_file_ref": (
                        f"/work/js-analysis/{scope.run_id}/recovered/"
                        + artifact_file_name(content_sha)
                        if content is not None and fits
                        else None
                    ),
                    "status": status,
                    "available": available,
                    "failure_reason": failure_reason,
                    "created_at": int(prior.get("created_at") or time.time()),
                    "updated_at": int(time.time()),
                }
                if available and prior.get("available"):
                    record["work_file_ref"] = prior.get("work_file_ref")
                sources[source_id] = record
                prepared.append((record, content))
            recovery.setdefault("leads", {})[lead_id] = {
                "map_id": map_id,
                "status": (
                    "complete"
                    if all(
                        row.get("status") in {"pending", "available"}
                        for row in sources.values()
                        if row.get("lead_id") == lead_id
                    )
                    else "partial"
                ),
                "gaps": list(dict.fromkeys(gaps)),
                "updated_at": int(time.time()),
            }

        manifest.update(mutate)
        if map_id not in (
            manifest.get().get("recovery", {}).get("maps") or {}
        ):
            return self._failed(
                manifest,
                lead_id,
                scope,
                gaps + ["run_scratch_limit"],
            )
        for record, content in prepared:
            if content is not None and record.get("object_ref"):
                _atomic_bytes(
                    self._run_dir(scope.project_id, scope.run_id)
                    / record["object_ref"],
                    content,
                )
        return {
            "lead_id": lead_id,
            "map_id": map_id,
            "deadline_s": self._limits.deadline_s,
            "status": (
                "complete"
                if all(row["status"] in {"pending", "available"} for row in [r for r, _ in prepared])
                else "partial"
            ),
            "gaps": list(dict.fromkeys(gaps)),
            "sources": [
                {
                    **self._source_public(record),
                    "object_ref": record.get("object_ref"),
                }
                for record, _ in prepared
            ],
        }

    def _failed(self, manifest, lead_id, scope, gaps):
        manifest.update(
            lambda value: value.setdefault("recovery", {}).setdefault("leads", {}).__setitem__(
                lead_id,
                {
                    "status": "failed",
                    "gaps": list(dict.fromkeys(gaps)),
                    "updated_at": int(time.time()),
                },
            )
        )
        return {
            "lead_id": lead_id,
            "deadline_s": self._limits.deadline_s,
            "status": "failed",
            "gaps": list(dict.fromkeys(gaps)),
            "sources": [],
        }

    def _source_record(self, reference: str, source_id: str):
        scope = __import__(
            "polymerhus.recon.js_intake.reader",
            fromlist=["resolve_js_intake_reference"],
        ).resolve_js_intake_reference(reference)
        record = (
            self._manifest(scope.project_id, scope.run_id)
            .get()
            .get("recovery", {})
            .get("sources", {})
            .get(source_id)
        )
        if (
            not record
            or record.get("context_ref") != scope.context_ref
        ):
            raise RecoveryError("source_outside_context")
        return record, scope

    def read_source_artifact(self, *, reference: str, source_id: str) -> bytes:
        record, scope = self._source_record(reference, source_id)
        object_ref = str(record.get("object_ref") or "")
        path = self._run_dir(scope.project_id, scope.run_id) / object_ref
        if not object_ref or not path.is_file():
            self._mark_source_failed(
                scope,
                source_id,
                "source_object_missing",
            )
            raise RecoveryError("source_object_missing")
        body = path.read_bytes()
        if (
            hashlib.sha256(body).hexdigest() != record.get("content_sha256")
            or len(body) != record.get("size")
        ):
            self._mark_source_failed(
                scope,
                source_id,
                "source_object_tampered",
            )
            raise RecoveryError("source_object_tampered")
        return body

    def _mark_source_failed(self, scope, source_id: str, reason: str) -> None:
        manifest = self._manifest(scope.project_id, scope.run_id)

        def mutate(value: dict) -> None:
            record = (
                value.setdefault("recovery", {})
                .setdefault("sources", {})
                .get(source_id)
            )
            if not record or record.get("status") == "available":
                return
            record["status"] = "failed"
            record["available"] = False
            record["failure_reason"] = reason
            record["updated_at"] = int(time.time())

        manifest.update(mutate)

    def confirm_source(
        self,
        *,
        reference: str,
        source_id: str,
        size: int,
        sha256: str,
        work_file_ref: str,
    ) -> dict:
        record, scope = self._source_record(reference, source_id)
        manifest = self._manifest(scope.project_id, scope.run_id)
        result = {"status": "failed", "reconcile_required": False}

        def mutate(value: dict) -> None:
            current = (
                value.setdefault("recovery", {})
                .setdefault("sources", {})
                .get(source_id)
                or {}
            )
            matches = (
                current.get("size") == size
                and current.get("content_sha256") == sha256
                and current.get("work_file_ref") == work_file_ref
            )
            if current.get("status") == "available":
                if not matches:
                    raise RecoveryError("confirmation_mismatch")
                result.update(status="available", idempotent=True)
                return
            if current.get("status") != "pending" or not matches:
                raise RecoveryError("confirmation_mismatch")
            current["status"] = "available"
            current["available"] = True
            current["failure_reason"] = None
            current["updated_at"] = int(time.time())
            result.update(status="available", idempotent=False)

        manifest.update(mutate)
        return {"source_id": source_id, **result}

    def fail_source(
        self,
        *,
        reference: str,
        source_id: str,
        failure_reason: str,
    ) -> dict:
        _, scope = self._source_record(reference, source_id)
        manifest = self._manifest(scope.project_id, scope.run_id)
        result = {
            "status": "failed",
            "reconcile_required": False,
            "keep_work_file": False,
        }

        def mutate(value: dict) -> None:
            current = (
                value.setdefault("recovery", {})
                .setdefault("sources", {})
                .get(source_id)
                or {}
            )
            if current.get("status") == "available":
                current["reconcile_required"] = True
                current["reconcile_reason"] = "late_recovery_failure"
                result.update(
                    status="available",
                    reconcile_required=True,
                    keep_work_file=True,
                )
                return
            current["status"] = "failed"
            current["available"] = False
            current["failure_reason"] = failure_reason
            current["updated_at"] = int(time.time())

        manifest.update(mutate)
        return {"source_id": source_id, **result}

    @staticmethod
    def _cursor(scope, lead_id: str, offset: int) -> str:
        body = json.dumps({"offset": offset}, separators=(",", ":")).encode()
        binding = (
            f"{scope.project_id}\0{scope.run_id}\0{scope.context_ref}\0{lead_id}"
        ).encode()
        digest = hashlib.sha256(binding + body).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")

    def _cursor_offset(self, cursor: str | None, scope, lead_id: str) -> int:
        if not cursor:
            return 0
        try:
            payload = base64.urlsafe_b64decode(
                cursor + "=" * (-len(cursor) % 4)
            )
            body, digest = payload[:-8], payload[-8:]
            binding = (
                f"{scope.project_id}\0{scope.run_id}\0{scope.context_ref}\0{lead_id}"
            ).encode()
            if digest != hashlib.sha256(binding + body).digest()[:8]:
                raise ValueError
            offset = json.loads(body).get("offset")
            if not isinstance(offset, int) or offset < 0:
                raise ValueError
            return offset
        except Exception:
            raise RecoveryError("invalid_source_cursor") from None

    def list_sources(
        self,
        *,
        reference: str,
        lead_id: str,
        cursor: str | None = None,
        limit: int = 5,
    ) -> dict:
        from polymerhus.recon.js_intake.reader import (
            resolve_js_intake_reference,
        )

        scope = resolve_js_intake_reference(reference)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise RecoveryError("invalid_source_limit")
        limit = min(limit, 10)
        offset = self._cursor_offset(cursor, scope, lead_id)
        manifest = self._manifest(scope.project_id, scope.run_id).get()
        rows = sorted(
            (
                record
                for record in (
                    manifest.get("recovery", {}).get("sources", {}).values()
                )
                if record.get("lead_id") == lead_id
                and record.get("context_ref") == scope.context_ref
            ),
            key=lambda row: (
                row.get("section_path") or [],
                row.get("source_ordinal") or 0,
                row.get("source_id") or "",
            ),
        )
        window = rows[offset : offset + limit]
        next_offset = offset + len(window)
        return {
            "lead_id": lead_id,
            "sources": [self._source_public(row) for row in window],
            "total": len(rows),
            "next_cursor": (
                self._cursor(scope, lead_id, next_offset)
                if next_offset < len(rows)
                else None
            ),
        }

    def get_source(self, *, reference: str, source_id: str) -> dict:
        record, _ = self._source_record(reference, source_id)
        return self._source_public(record)

    @staticmethod
    def _source_public(record: dict) -> dict:
        return {
            key: record.get(key)
            for key in (
                "source_id",
                "map_id",
                "section_path",
                "source_ordinal",
                "redacted_name",
                "kind",
                "content_state",
                "content_sha256",
                "size",
                "work_file_ref",
                "status",
                "available",
                "failure_reason",
            )
        }


def _source_map_annotations(source: bytes) -> list[str]:
    text = source.decode("utf-8", "replace")
    annotations = []
    state = "normal"
    quote = ""
    buffer = []
    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if state in {"single", "double", "template"}:
            if char == "\\":
                index += 2
                continue
            if (quote == "'" and char == "'") or (
                quote == '"' and char == '"'
            ) or (quote == "`" and char == "`"):
                state = "normal"
                quote = ""
            index += 1
            continue
        if state == "line":
            if char in "\r\n":
                comment = "".join(buffer)
                if comment.startswith(("#", "@")) and "sourceMappingURL=" in comment:
                    annotations.append(
                        comment.split("sourceMappingURL=", 1)[1].strip()
                    )
                state = "normal"
                buffer = []
            else:
                buffer.append(char)
            index += 1
            continue
        if state == "block":
            if char == "*" and nxt == "/":
                comment = "".join(buffer)
                if comment.startswith(("#", "@")) and "sourceMappingURL=" in comment:
                    annotations.append(
                        comment.split("sourceMappingURL=", 1)[1].strip()
                    )
                state = "normal"
                buffer = []
                index += 2
            else:
                buffer.append(char)
                index += 1
            continue
        if char in {"'", '"', "`"}:
            state = {"'": "single", '"': "double", "`": "template"}[char]
            quote = char
            index += 1
            continue
        if char == "/" and nxt == "/":
            state = "line"
            buffer = []
            index += 2
            continue
        if char == "/" and nxt == "*":
            state = "block"
            buffer = []
            index += 2
            continue
        index += 1
    return annotations


def discover_source_map_link(
    source: bytes,
    *,
    final_url: str,
    sourcemap_header: str | None = None,
    x_sourcemap_header: str | None = None,
) -> SourceMapLink:
    annotations = _source_map_annotations(source)
    annotation = annotations[-1] if annotations else None
    annotation_url = urljoin(final_url, annotation) if annotation else None
    header = sourcemap_header or x_sourcemap_header
    if header:
        header_url = urljoin(final_url, header)
        return SourceMapLink(
            url=header_url,
            kind="header",
            annotation_url=annotation_url,
            conflict=bool(annotation_url and annotation_url != header_url),
        )
    if annotation_url:
        return SourceMapLink(
            url=annotation_url,
            kind="annotation",
            annotation_url=annotation_url,
        )
    parts = urlsplit(final_url)
    guessed = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path + ".map",
            parts.query,
            "",
        )
    )
    return SourceMapLink(url=guessed, kind="guessed")


def decode_map_data_uri(value: str, *, max_bytes: int) -> bytes:
    if not value.lower().startswith("data:"):
        raise InvalidMapDataURI("not_data_uri")
    try:
        metadata, payload = value.split(",", 1)
    except ValueError:
        raise InvalidMapDataURI("invalid_data_uri") from None
    if ";base64" in metadata.lower():
        try:
            import base64

            decoded = base64.b64decode(payload, validate=True)
        except Exception:
            raise InvalidMapDataURI("invalid_base64") from None
    else:
        decoded = unquote_to_bytes(payload)
    if len(decoded) > max_bytes:
        raise InvalidMapDataURI("decoded_map_size_limit")
    return decoded


def _parser_path() -> Path:
    return Path(__file__).resolve().with_name("parser") / "sourcemap_parser.mjs"


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (AttributeError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=2)
    except (AttributeError, subprocess.TimeoutExpired, OSError):
        pass


def _run_parser(
    *,
    map_path: Path,
    map_url: str,
    limits: SourceMapParseLimits,
    parser_command: Sequence[str] | None,
):
    node = shutil.which("node") or "node"
    command = list(
        parser_command
        or [node, "--max-old-space-size=256", str(_parser_path())]
    )
    command.extend(
        [
            str(map_path),
            map_url,
            json.dumps(
                {
                    "max_occurrences": limits.max_occurrences,
                    "max_section_depth": limits.max_section_depth,
                    "max_source_bytes": limits.max_source_bytes,
                },
                separators=(",", ":"),
            ),
        ]
    )

    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    assert proc.stderr is not None
    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    chunks: list[bytes] = []
    stderr_bytes = 0
    total = 0
    timed_out = False
    exceeded = False
    memory_exceeded = False
    deadline = started + limits.parser_timeout_s
    try:
        while selector.get_map():
            try:
                rss_kb = int(
                    next(
                        line.split()[1]
                        for line in Path(f"/proc/{proc.pid}/status")
                        .read_text()
                        .splitlines()
                        if line.startswith("VmRSS:")
                    )
                )
            except (OSError, StopIteration, ValueError):
                rss_kb = 0
            if rss_kb * 1024 > limits.max_parser_memory_bytes:
                memory_exceeded = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(0.05, remaining)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > limits.max_parser_output_bytes:
                    exceeded = True
                    break
                if key.data == "stdout":
                    chunks.append(chunk)
                else:
                    stderr_bytes += len(chunk)
            if exceeded:
                break
        if timed_out or exceeded or memory_exceeded:
            _kill(proc)
        else:
            try:
                proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill(proc)
    finally:
        selector.close()
        proc.stdout.close()
        proc.stderr.close()

    if timed_out:
        raise SourceMapParseError("parser_timeout")
    if exceeded:
        raise SourceMapParseError("parser_output_limit")
    if memory_exceeded:
        raise SourceMapParseError("parser_memory_limit")
    if proc.returncode not in (0, 2):
        raise SourceMapParseError("parser_process_failed")
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak = max(usage_before, usage_after) * 1024
    return b"".join(chunks), peak


def parse_map_bytes(
    map_bytes: bytes,
    *,
    map_url: str,
    limits: SourceMapParseLimits | None = None,
    parser_command: Sequence[str] | None = None,
) -> ParsedSourceMap:
    limits = limits or SourceMapParseLimits()
    if len(map_bytes) > limits.max_map_bytes:
        raise SourceMapParseError("map_size_limit")
    try:
        parsed_input = json.loads(map_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SourceMapParseError("invalid_map_json") from None
    if not isinstance(parsed_input, dict):
        raise SourceMapParseError("invalid_map_structure")

    with tempfile.TemporaryDirectory(prefix="sourcemap-parser.") as directory:
        map_path = Path(directory) / "map.json"
        map_path.write_bytes(map_bytes)
        map_path.chmod(0o600)
        stdout, peak_memory = _run_parser(
            map_path=map_path,
            map_url=map_url,
            limits=limits,
            parser_command=parser_command,
        )

    occurrences: list[ParsedOccurrence] = []
    gaps: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get("type") == "error":
            raise SourceMapParseError(str(message.get("reason") or "parser_error"))
        if message.get("type") == "gap":
            gaps.append(str(message.get("gap") or "parser_gap"))
            continue
        if message.get("type") != "occurrence":
            continue
        content = message.get("content")
        content_bytes = (
            content.encode("utf-8") if isinstance(content, str) else None
        )
        digest = (
            hashlib.sha256(content_bytes).hexdigest()
            if content_bytes is not None
            else None
        )
        occurrences.append(
            ParsedOccurrence(
                section_path=tuple(int(item) for item in message.get("section_path") or []),
                source_ordinal=int(message["source_ordinal"]),
                raw_name=message.get("raw_name"),
                resolved_source=message.get("resolved_source"),
                content_state=str(message.get("content_state") or "missing"),
                content=content_bytes,
                content_sha256=digest,
                size=len(content_bytes) if content_bytes is not None else None,
            )
        )

    if len(occurrences) > limits.max_occurrences:
        raise SourceMapParseError("source_count_limit")
    return ParsedSourceMap(
        map_url=map_url,
        map_sha256=hashlib.sha256(map_bytes).hexdigest(),
        occurrences=tuple(occurrences),
        gaps=tuple(dict.fromkeys(gaps)),
        parser_memory_bytes=peak_memory,
    )


__all__ = [
    "InvalidMapDataURI",
    "ParsedOccurrence",
    "ParsedSourceMap",
    "RecoveryError",
    "RecoveryLimits",
    "SourceMapLink",
    "SourceMapParseError",
    "SourceMapParseLimits",
    "SourceMapRecovery",
    "artifact_file_name",
    "decode_map_data_uri",
    "discover_source_map_link",
    "parse_map_bytes",
]
