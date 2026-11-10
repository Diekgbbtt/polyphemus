"""Private bounded literal-search snapshots and scoped match navigation."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from polymerhus.app.data_root import project_dir
from polymerhus.recon.js_acquisition.code_redaction import (
    CodeRedactionError,
    PreparedRedaction,
    prepare_redaction,
    redact_window,
)
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_intake import resolve_js_intake_reference

DEFAULT_PAGE = 5
MAX_PAGE = 10
MAX_EXAMINED_BYTES = 64 * 1024 * 1024
MAX_MATCHES = 10_000
SEARCH_DEADLINE_S = 5.0


class CodeSearchError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _record_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {key: item for key, item in value.items() if key != "integrity"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class CodeSearchService:
    def __init__(
        self,
        *,
        root: str | Path | None = None,
        clock=time.monotonic,
    ) -> None:
        self._root = root
        self._clock = clock

    def _manifest(self, project_id: str, run_id: str) -> AcquisitionManifest:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=64 * 1024 * 1024,
        )

    def _run_dir(self, project_id: str, run_id: str) -> Path:
        return project_dir(
            project_id,
            "recon/js_analysis",
            root=self._root,
        ) / run_id

    def _search_path(self, project_id: str, run_id: str, search_id: str) -> Path:
        return self._run_dir(project_id, run_id) / "code_searches" / f"{search_id}.json"

    @staticmethod
    def _search_key(
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        query_sha256: str,
        snapshot: list[dict],
    ) -> str:
        return "search_" + hashlib.sha256(
            json.dumps(
                {
                    "project_id": project_id,
                    "run_id": run_id,
                    "context_ref": context_ref,
                    "lead_id": lead_id,
                    "query_sha256": query_sha256,
                    "snapshot": sorted(
                        (
                            row["source_id"],
                            row["content_sha256"],
                            row["kind"],
                        )
                        for row in snapshot
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:32]

    @staticmethod
    def _cursor(
        search_id: str,
        context_ref: str,
        *,
        mode: str,
        offset: int = 0,
        source_index: int = 0,
        page_offset: int = 0,
        match_offset: int = 0,
    ) -> str:
        body = json.dumps(
            {
                "search_id": search_id,
                "mode": mode,
                "offset": offset,
                "source_index": source_index,
                "page_offset": page_offset,
                "match_offset": match_offset,
            },
            separators=(",", ":"),
        ).encode()
        binding = f"{search_id}\0{context_ref or ''}".encode()
        digest = hashlib.sha256(binding + body).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None, context_ref: str) -> dict:
        if not cursor:
            raise CodeSearchError("invalid_search_cursor")
        try:
            payload = base64.urlsafe_b64decode(
                cursor + "=" * (-len(cursor) % 4)
            )
            body, observed = payload[:-8], payload[-8:]
            value = json.loads(body)
            search_id = str(value["search_id"])
            mode = str(value["mode"])
            offset = int(value["offset"])
            source_index = int(value["source_index"])
            page_offset = int(value.get("page_offset", 0))
            match_offset = int(value.get("match_offset", 0))
            expected = hashlib.sha256(
                f"{search_id}\0{context_ref or ''}".encode() + body
            ).digest()[:8]
            if (
                observed != expected
                or mode not in {"page", "scan"}
                or offset < 0
                or source_index < 0
                or page_offset < 0
                or match_offset < 0
            ):
                raise ValueError
            return {
                "search_id": search_id,
                "mode": mode,
                "offset": offset,
                "source_index": source_index,
                "page_offset": page_offset,
                "match_offset": match_offset,
            }
        except Exception:
            raise CodeSearchError("invalid_search_cursor") from None

    def _inventory(
        self,
        *,
        manifest: dict,
        lead_id: str,
        context_ref: str,
    ) -> tuple[list[dict], list[str]]:
        generated = (manifest.get("leads") or {}).get(lead_id) or {}
        if (
            generated.get("status") != "acquired"
            or not generated.get("available")
            or (generated.get("context_ref") or "") != (context_ref or "")
        ):
            raise CodeSearchError("lead_not_acquired")
        rows = [
            {
                "source_id": lead_id,
                "lead_id": lead_id,
                "kind": "generated",
                "source_tool": "acquired",
                "content_sha256": generated["sha256"],
                "size": int(generated["size"]),
                "work_file_ref": generated["work_file_ref"],
                "available": True,
            }
        ]
        gaps: list[str] = []
        for source in (
            manifest.get("recovery", {}).get("sources", {}).values()
        ):
            if (
                source.get("lead_id") != lead_id
                or (source.get("context_ref") or "") != (context_ref or "")
            ):
                continue
            available = (
                source.get("status") == "available"
                and bool(source.get("available"))
                and source.get("content_state") in {"text", "empty"}
            )
            if not available:
                gaps.append("unavailable_recovered_source")
                continue
            rows.append(
                {
                    "source_id": str(source["source_id"]),
                    "lead_id": lead_id,
                    "kind": str(source.get("kind") or "unknown"),
                    "source_tool": "source_map",
                    "content_sha256": str(source["content_sha256"]),
                    "size": int(source["size"]),
                    "work_file_ref": str(source["work_file_ref"]),
                    "available": True,
                }
            )
        return rows, list(dict.fromkeys(gaps))

    @staticmethod
    def _inventory_cursor(
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        offset: int,
    ) -> str:
        body = json.dumps({"offset": offset}, separators=(",", ":")).encode()
        binding = (
            f"{project_id}\0{run_id}\0{context_ref or ''}\0{lead_id}"
        ).encode()
        digest = hashlib.sha256(binding + body).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")

    @staticmethod
    def _decode_inventory_cursor(
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        cursor: str | None,
    ) -> int:
        if not cursor:
            return 0
        try:
            payload = base64.urlsafe_b64decode(
                cursor + "=" * (-len(cursor) % 4)
            )
            body, observed = payload[:-8], payload[-8:]
            binding = (
                f"{project_id}\0{run_id}\0{context_ref or ''}\0{lead_id}"
            ).encode()
            expected = hashlib.sha256(binding + body).digest()[:8]
            offset = int(json.loads(body)["offset"])
            if observed != expected or offset < 0:
                raise ValueError
            return offset
        except Exception:
            raise CodeSearchError("invalid_search_cursor") from None

    def source_inventory(
        self,
        *,
        reference: str,
        lead_id: str,
        cursor: str | None = None,
        limit: int = MAX_PAGE,
    ) -> dict:
        scope = resolve_js_intake_reference(reference)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise CodeSearchError("invalid_search_limit")
        limit = min(limit, MAX_PAGE)
        offset = self._decode_inventory_cursor(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            lead_id=lead_id,
            cursor=cursor,
        )
        manifest = self._manifest(scope.project_id, scope.run_id).get()
        sources, gaps = self._inventory(
            manifest=manifest,
            lead_id=lead_id,
            context_ref=scope.context_ref,
        )
        window = sources[offset : offset + limit]
        next_offset = offset + len(window)
        return {
            "lead_id": lead_id,
            "sources": window,
            "total_sources": len(sources),
            "coverage_gaps": gaps,
            "next_cursor": (
                self._inventory_cursor(
                    project_id=scope.project_id,
                    run_id=scope.run_id,
                    context_ref=scope.context_ref,
                    lead_id=lead_id,
                    offset=next_offset,
                )
                if next_offset < len(sources)
                else None
            ),
        }

    def _verify_snapshot_current(
        self,
        *,
        scope,
        lead_id: str,
        snapshot: list[dict],
    ) -> bool:
        current, _ = self._inventory(
            manifest=self._manifest(scope.project_id, scope.run_id).get(),
            lead_id=lead_id,
            context_ref=scope.context_ref,
        )
        current_map = {
            row["source_id"]: (row["content_sha256"], row["size"], row["kind"])
            for row in current
        }
        return all(
            current_map.get(row["source_id"])
            == (row["content_sha256"], row["size"], row["kind"])
            for row in snapshot
        )

    @staticmethod
    def _preview_bounds(
        content: bytes,
        start: int,
        end: int,
    ) -> tuple[int, int]:
        window_start = max(0, start - 96)
        window_end = min(len(content), end + 96)
        while window_start > 0 and content[window_start] & 0xC0 == 0x80:
            window_start -= 1
        while (
            window_end < len(content)
            and content[window_end] & 0xC0 == 0x80
        ):
            window_end += 1
        return window_start, window_end

    @staticmethod
    def _match_preview(
        content: bytes,
        start: int,
        end: int,
        prepared: PreparedRedaction | None = None,
    ) -> str:
        window_start, window_end = CodeSearchService._preview_bounds(
            content,
            start,
            end,
        )
        redacted = (
            prepared.window(window_start, window_end)
            if prepared is not None
            else redact_window(content, window_start, window_end)
        )
        return redacted.display

    def search_from_contents(
        self,
        *,
        reference: str,
        lead_id: str,
        text: str,
        contents: dict[str, bytes],
        limit: int = DEFAULT_PAGE,
        max_examined_bytes: int = MAX_EXAMINED_BYTES,
        deadline_s: float = SEARCH_DEADLINE_S,
        resume_cursor: str | None = None,
    ) -> dict:
        if not isinstance(text, str):
            raise CodeSearchError("invalid_search_literal")
        query_bytes = text.encode("utf-8")
        if len(query_bytes) < 2 or len(query_bytes) > 128:
            raise CodeSearchError("invalid_search_literal")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise CodeSearchError("invalid_search_limit")
        limit = min(limit, MAX_PAGE)
        if (
            not isinstance(max_examined_bytes, int)
            or max_examined_bytes <= 0
            or max_examined_bytes > MAX_EXAMINED_BYTES
        ):
            raise CodeSearchError("invalid_search_byte_limit")
        started = self._clock()
        scope = resolve_js_intake_reference(reference)
        if resume_cursor:
            return self._resume_search(
                scope=scope,
                lead_id=lead_id,
                query_bytes=query_bytes,
                contents=contents,
                cursor=resume_cursor,
                limit=limit,
                max_examined_bytes=max_examined_bytes,
                deadline_s=deadline_s,
                started=started,
            )
        manifest = self._manifest(scope.project_id, scope.run_id).get()
        available, gaps = self._inventory(
            manifest=manifest,
            lead_id=lead_id,
            context_ref=scope.context_ref,
        )
        available_by_id = {row["source_id"]: row for row in available}
        if any(source_id not in available_by_id for source_id in contents):
            raise CodeSearchError("search_content_not_in_snapshot")

        matches: list[dict] = []
        progress: dict = {}
        examined_sources, examined, search_gaps = self._scan_sources(
            sources=available,
            contents=contents,
            query_bytes=query_bytes,
            matches=matches,
            max_examined_bytes=max_examined_bytes,
            deadline_s=deadline_s,
            started=started,
            progress=progress,
        )
        gaps.extend(search_gaps)
        query_sha256 = hashlib.sha256(query_bytes).hexdigest()
        snapshot = [
            {
                key: source[key]
                for key in (
                    "source_id",
                    "lead_id",
                    "kind",
                    "source_tool",
                    "content_sha256",
                    "size",
                    "work_file_ref",
                )
            }
            for source in available
        ]
        search_id = self._search_key(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            lead_id=lead_id,
            query_sha256=query_sha256,
            snapshot=snapshot,
        )
        status = "partial" if gaps else "complete"
        document = {
            "schema_version": 1,
            "search_id": search_id,
            "project_id": scope.project_id,
            "run_id": scope.run_id,
            "context_ref": scope.context_ref,
            "lead_id": lead_id,
            "query_sha256": query_sha256,
            "snapshot": snapshot,
            "matches": matches,
            "examined_source_ids": examined_sources,
            "examined_bytes": examined,
            "status": status,
            "coverage_gaps": list(dict.fromkeys(gaps)),
            "resume_source_index": (
                progress.get("source_index")
                if not progress.get("source_complete")
                else None
            ),
            "resume_match_offset": (
                progress.get("match_offset", 0)
                if not progress.get("source_complete")
                else 0
            ),
            "created_at": int(time.time()),
        }
        document["integrity"] = _record_digest(document)
        _atomic_json(
            self._search_path(scope.project_id, scope.run_id, search_id),
            document,
        )
        self._manifest(scope.project_id, scope.run_id).update(
            lambda value: value.setdefault("code_access", {})
            .setdefault("searches", {})
            .__setitem__(
                search_id,
                {
                    "search_id": search_id,
                    "lead_id": lead_id,
                    "context_ref": scope.context_ref,
                    "status": status,
                },
            )
        )
        return self._page(document, offset=0, limit=limit)

    def _scan_sources(
        self,
        *,
        sources: list[dict],
        contents: dict[str, bytes],
        query_bytes: bytes,
        matches: list[dict],
        max_examined_bytes: int,
        deadline_s: float,
        started: float,
        source_index_offset: int = 0,
        start_offset: int = 0,
        progress: dict | None = None,
    ) -> tuple[list[str], int, list[str]]:
        examined_sources: list[str] = []
        examined_bytes = 0
        gaps: list[str] = []
        existing_ids = {match["match_id"] for match in matches}
        prepared_by_content: dict[str, PreparedRedaction] = {}
        progress = progress if progress is not None else {}
        progress.update(
            {
                "source_index": None,
                "match_offset": 0,
                "source_complete": False,
            }
        )
        for local_index, source in enumerate(sources):
            source_index = source_index_offset + local_index
            if self._clock() - started >= deadline_s:
                gaps.append("search_deadline")
                progress.update(
                    {
                        "source_index": source_index,
                        "match_offset": 0,
                        "examined_sources": list(examined_sources),
                        "examined_bytes": examined_bytes,
                        "gaps": list(gaps),
                        "source_complete": False,
                    }
                )
                break
            if source["source_id"] not in contents:
                gaps.append("content_not_transferred")
                progress.update(
                    {
                        "source_index": source_index,
                        "match_offset": 0,
                        "examined_sources": list(examined_sources),
                        "examined_bytes": examined_bytes,
                        "gaps": list(gaps),
                        "source_complete": False,
                    }
                )
                break
            content = contents[source["source_id"]]
            if not isinstance(content, bytes):
                raise CodeSearchError("search_content_mismatch")
            source_start_offset = start_offset if local_index == 0 else 0
            if source_start_offset < 0 or source_start_offset > len(content):
                raise CodeSearchError("invalid_search_cursor")
            if (
                len(content) != source["size"]
                or hashlib.sha256(content).hexdigest()
                != source["content_sha256"]
            ):
                raise CodeSearchError("search_content_mismatch")
            remaining_source_bytes = len(content) - source_start_offset
            if examined_bytes + remaining_source_bytes > max_examined_bytes:
                gaps.append("examined_byte_limit")
                progress.update(
                    {
                        "source_index": source_index,
                        "match_offset": 0,
                        "examined_sources": list(examined_sources),
                        "examined_bytes": examined_bytes,
                        "gaps": list(gaps),
                        "source_complete": False,
                    }
                )
                break
            content_sha256 = str(source["content_sha256"])
            prepared = prepared_by_content.get(content_sha256)
            if prepared is None:
                try:
                    prepared = prepare_redaction(content)
                except CodeRedactionError:
                    gaps.append("unsupported_encoding")
                    continue
                prepared_by_content[content_sha256] = prepared
            if self._clock() - started >= deadline_s:
                gaps.append("search_deadline")
                progress.update(
                    {
                        "source_index": source_index,
                        "match_offset": 0,
                        "examined_sources": list(examined_sources),
                        "examined_bytes": examined_bytes,
                        "gaps": list(gaps),
                        "source_complete": False,
                    }
                )
                break
            cursor = source_start_offset
            ordinal = 0
            interrupted = False
            while True:
                start = content.find(query_bytes, cursor)
                if start < 0:
                    break
                if len(matches) >= MAX_MATCHES:
                    gaps.append("match_count_limit")
                    interrupted = True
                    break
                if self._clock() - started >= deadline_s:
                    gaps.append("search_deadline")
                    interrupted = True
                    progress.update(
                        {
                            "source_index": source_index,
                            "match_offset": start,
                            "examined_sources": list(examined_sources),
                            "examined_bytes": (
                                examined_bytes
                                + max(0, start - source_start_offset)
                            ),
                            "gaps": list(gaps),
                            "source_complete": False,
                        }
                    )
                    break
                end = start + len(query_bytes)
                match_id = "match_" + hashlib.sha256(
                    (
                        f"{source['source_id']}\0{source['content_sha256']}\0"
                        f"{start}\0{end}\0{ordinal}"
                    ).encode()
                ).hexdigest()[:32]
                if match_id not in existing_ids:
                    matches.append(
                        {
                            "match_id": match_id,
                            "source": {
                                key: source[key]
                                for key in (
                                    "source_id",
                                    "lead_id",
                                    "kind",
                                    "source_tool",
                                    "content_sha256",
                                    "size",
                                    "work_file_ref",
                                )
                            },
                            "start_byte": start,
                            "end_byte": end,
                            "redacted_preview": self._match_preview(
                                content,
                                start,
                                end,
                                prepared,
                            ),
                        }
                    )
                    existing_ids.add(match_id)
                ordinal += 1
                cursor = end
                if self._clock() - started >= deadline_s:
                    gaps.append("search_deadline")
                    interrupted = True
                    progress.update(
                        {
                            "source_index": source_index,
                            "match_offset": cursor,
                            "examined_sources": list(examined_sources),
                            "examined_bytes": (
                                examined_bytes
                                + max(0, cursor - source_start_offset)
                            ),
                            "gaps": list(gaps),
                            "source_complete": False,
                        }
                    )
                    break
            if interrupted:
                break
            if "match_count_limit" in gaps:
                break
            examined_bytes += remaining_source_bytes
            examined_sources.append(source["source_id"])
            progress.update(
                {
                    "source_index": source_index,
                    "match_offset": 0,
                    "examined_sources": list(examined_sources),
                    "examined_bytes": examined_bytes,
                    "gaps": list(gaps),
                    "source_complete": True,
                }
            )
        return examined_sources, examined_bytes, gaps

    def _resume_search(
        self,
        *,
        scope,
        lead_id: str,
        query_bytes: bytes,
        contents: dict[str, bytes],
        cursor: str,
        limit: int,
        max_examined_bytes: int,
        deadline_s: float,
        started: float,
    ) -> dict:
        decoded = self._decode_cursor(cursor, scope.context_ref)
        if decoded["mode"] != "scan":
            raise CodeSearchError("invalid_search_cursor")
        document = self._load(scope, decoded["search_id"])
        if (
            document.get("lead_id") != lead_id
            or document.get("query_sha256")
            != hashlib.sha256(query_bytes).hexdigest()
        ):
            raise CodeSearchError("invalid_search_cursor")
        snapshot = document.get("snapshot") or []
        if not self._verify_snapshot_current(
            scope=scope,
            lead_id=lead_id,
            snapshot=snapshot,
        ):
            raise CodeSearchError("stale_search_snapshot")
        examined_before = set(document.get("examined_source_ids") or [])
        remaining = [
            row
            for row in snapshot[decoded["source_index"] :]
            if row["source_id"] not in examined_before
        ]
        remaining_ids = {row["source_id"] for row in remaining}
        if any(source_id not in remaining_ids for source_id in contents):
            raise CodeSearchError("search_content_not_in_snapshot")
        progress: dict = {}
        newly_examined, newly_examined_bytes, new_gaps = self._scan_sources(
            sources=remaining,
            contents=contents,
            query_bytes=query_bytes,
            matches=document.setdefault("matches", []),
            max_examined_bytes=max_examined_bytes,
            deadline_s=deadline_s,
            started=started,
            source_index_offset=decoded["source_index"],
            start_offset=decoded["match_offset"],
            progress=progress,
        )
        examined_sources = list(
            dict.fromkeys(
                list(document.get("examined_source_ids") or []) + newly_examined
            )
        )
        document["examined_source_ids"] = examined_sources
        document["examined_bytes"] = (
            int(document.get("examined_bytes") or 0) + newly_examined_bytes
        )
        persistent_gaps = [
            gap
            for gap in document.get("coverage_gaps") or []
            if gap
            not in {
                "content_not_transferred",
                "examined_byte_limit",
                "search_deadline",
            }
        ]
        all_examined = {
            row["source_id"] for row in snapshot
        }.issubset(set(examined_sources))
        gaps = list(dict.fromkeys(persistent_gaps + new_gaps))
        if not all_examined and not any(
            gap in gaps
            for gap in {
                "content_not_transferred",
                "examined_byte_limit",
            }
        ):
            gaps.append("content_not_transferred")
        document["coverage_gaps"] = gaps
        document["resume_source_index"] = (
            progress.get("source_index")
            if not progress.get("source_complete")
            else None
        )
        document["resume_match_offset"] = (
            progress.get("match_offset", 0)
            if not progress.get("source_complete")
            else 0
        )
        document["status"] = "complete" if not gaps else "partial"
        document["updated_at"] = int(time.time())
        document["integrity"] = _record_digest(document)
        _atomic_json(
            self._search_path(scope.project_id, scope.run_id, document["search_id"]),
            document,
        )
        return self._page(document, offset=0, limit=limit)

    def _page(self, document: dict, *, offset: int, limit: int) -> dict:
        matches = document.get("matches") or []
        window = matches[offset : offset + limit]
        next_offset = offset + len(window)
        public_matches = []
        for match in window:
            source = match["source"]
            public_matches.append(
                {
                    "match_id": match["match_id"],
                    "source": {
                        key: source.get(key)
                        for key in (
                            "source_id",
                            "lead_id",
                            "kind",
                            "source_tool",
                            "content_sha256",
                            "size",
                        )
                    },
                    "start_byte": match["start_byte"],
                    "end_byte": match["end_byte"],
                    "redacted_preview": match["redacted_preview"],
                }
            )
        response = {
            "search_id": document["search_id"],
            "lead_id": document["lead_id"],
            "query_sha256": document["query_sha256"],
            "status": document["status"],
            "matches": public_matches,
            "total_matches": len(matches),
            "examined_sources": len(document.get("examined_source_ids") or []),
            "examined_bytes": document.get("examined_bytes", 0),
            "coverage_gap": (
                (document.get("coverage_gaps") or [None])[0]
                if document.get("status") != "complete"
                else None
            ),
            "coverage_gaps": document.get("coverage_gaps") or [],
            "next_cursor": (
                self._cursor(
                    document["search_id"],
                    document["context_ref"],
                    mode="page",
                    offset=next_offset,
                )
                if next_offset < len(matches)
                else None
            ),
            "scan_resume_cursor": self._scan_resume_cursor(document),
        }
        while len(json.dumps(response, separators=(",", ":")).encode()) > 15000:
            if not response["matches"]:
                raise CodeSearchError("search_response_too_large")
            response["matches"].pop()
            returned = offset + len(response["matches"])
            response["next_cursor"] = (
                self._cursor(
                    document["search_id"],
                    document["context_ref"],
                    mode="page",
                    offset=returned,
                )
                if returned < len(matches)
                else None
            )
        return response

    def _scan_resume_cursor(self, document: dict) -> str | None:
        if "match_count_limit" in (document.get("coverage_gaps") or []):
            return None
        resume_source_index = document.get("resume_source_index")
        if isinstance(resume_source_index, int):
            return self._cursor(
                document["search_id"],
                document["context_ref"],
                mode="scan",
                source_index=resume_source_index,
                match_offset=int(document.get("resume_match_offset") or 0),
            )
        snapshot = document.get("snapshot") or []
        examined = set(document.get("examined_source_ids") or [])
        for index, row in enumerate(snapshot):
            if row["source_id"] not in examined:
                return self._cursor(
                    document["search_id"],
                    document["context_ref"],
                    mode="scan",
                    source_index=index,
                )
        return None

    def _load(self, scope, search_id: str) -> dict:
        path = self._search_path(scope.project_id, scope.run_id, search_id)
        try:
            value = json.loads(path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise CodeSearchError("search_record_missing") from None
        if (
            not isinstance(value, dict)
            or value.get("search_id") != search_id
            or value.get("project_id") != scope.project_id
            or value.get("run_id") != scope.run_id
            or (value.get("context_ref") or "") != (scope.context_ref or "")
        ):
            raise CodeSearchError("search_outside_context")
        if value.get("integrity") != _record_digest(value):
            raise CodeSearchError("search_record_corrupt")
        return value

    def results(
        self,
        *,
        reference: str,
        lead_id: str,
        text: str,
        cursor: str | None,
        limit: int = DEFAULT_PAGE,
    ) -> dict:
        scope = resolve_js_intake_reference(reference)
        decoded = self._decode_cursor(cursor, scope.context_ref)
        if decoded["mode"] != "page":
            raise CodeSearchError("invalid_search_cursor")
        search_id = decoded["search_id"]
        offset = decoded["offset"]
        document = self._load(scope, search_id)
        if (
            document.get("lead_id") != lead_id
            or document.get("query_sha256")
            != hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            raise CodeSearchError("invalid_search_cursor")
        if not self._verify_snapshot_current(
            scope=scope,
            lead_id=lead_id,
            snapshot=document.get("snapshot") or [],
        ):
            raise CodeSearchError("stale_search_snapshot")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise CodeSearchError("invalid_search_limit")
        return self._page(document, offset=offset, limit=min(limit, MAX_PAGE))

    def resume_source_inventory(
        self,
        *,
        reference: str,
        lead_id: str,
        text: str,
        cursor: str,
    ) -> dict:
        scope = resolve_js_intake_reference(reference)
        decoded = self._decode_cursor(cursor, scope.context_ref)
        if decoded["mode"] != "scan":
            raise CodeSearchError("invalid_search_cursor")
        document = self._load(scope, decoded["search_id"])
        if (
            document.get("lead_id") != lead_id
            or document.get("query_sha256")
            != hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            raise CodeSearchError("invalid_search_cursor")
        snapshot = document.get("snapshot") or []
        if not self._verify_snapshot_current(
            scope=scope,
            lead_id=lead_id,
            snapshot=snapshot,
        ):
            raise CodeSearchError("stale_search_snapshot")
        examined = set(document.get("examined_source_ids") or [])
        all_sources = [
            row
            for row in snapshot[decoded["source_index"] :]
            if row["source_id"] not in examined
        ]
        page_offset = decoded.get("page_offset", 0)
        sources = all_sources[page_offset : page_offset + MAX_PAGE]
        next_offset = page_offset + len(sources)
        return {
            "mode": "scan",
            "search_id": document["search_id"],
            "lead_id": lead_id,
            "sources": sources,
            "scan_resume_cursor": cursor,
            "sources_next_cursor": (
                self._cursor(
                    document["search_id"],
                    document["context_ref"],
                    mode="scan",
                    source_index=decoded["source_index"],
                    page_offset=next_offset,
                )
                if next_offset < len(all_sources)
                else None
            ),
        }

    def resume_cursor(
        self,
        *,
        reference: str,
        lead_id: str,
        text: str,
        cursor: str,
        limit: int = DEFAULT_PAGE,
    ) -> dict:
        scope = resolve_js_intake_reference(reference)
        decoded = self._decode_cursor(cursor, scope.context_ref)
        if decoded["mode"] == "page":
            return self.results(
                reference=reference,
                lead_id=lead_id,
                text=text,
                cursor=cursor,
                limit=limit,
            )
        return self.resume_source_inventory(
            reference=reference,
            lead_id=lead_id,
            text=text,
            cursor=cursor,
        )

    def read_match(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        match_id: str,
    ) -> dict:
        root = self._run_dir(project_id, run_id) / "code_searches"
        for path in sorted(root.glob("*.json")):
            try:
                document = json.loads(path.read_text())
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                document.get("project_id") != project_id
                or document.get("run_id") != run_id
                or (document.get("context_ref") or "") != (context_ref or "")
                or document.get("integrity") != _record_digest(document)
            ):
                continue
            for match in document.get("matches") or []:
                if match.get("match_id") == match_id:
                    return {
                        **match,
                        "search_id": document["search_id"],
                    }
        raise CodeSearchError("match_not_found")


__all__ = [
    "CodeSearchError",
    "CodeSearchService",
    "DEFAULT_PAGE",
    "MAX_EXAMINED_BYTES",
    "MAX_MATCHES",
    "MAX_PAGE",
    "SEARCH_DEADLINE_S",
]
