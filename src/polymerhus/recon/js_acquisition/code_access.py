"""Authorized verified-artifact selectors and bounded redacted code windows."""

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from polymerhus.recon.js_acquisition.code_redaction import (
    REDACTION_POLICY_ID,
    CodeRedactionError,
    redact_window,
)
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.structure_store import (
    StructureStore,
    StructureStoreError,
)
from polymerhus.recon.js_intake import resolve_js_intake_reference

DEFAULT_WINDOW_BYTES = 4096
MAX_WINDOW_BYTES = 8192


class CodeAccessError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CodeTarget:
    project_id: str
    run_id: str
    context_ref: str
    lead_id: str
    selector_type: str
    selector_id: str
    work_file_ref: str
    content_sha256: str
    size: int
    range_start: int
    range_end: int
    kind: str
    focus_around: int | None = None

    def public(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "selector": {
                "type": self.selector_type,
                "id": self.selector_id,
            },
            "work_file_ref": self.work_file_ref,
            "content_sha256": self.content_sha256,
            "size": self.size,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "kind": self.kind,
            "focus_around": self.focus_around,
        }


def _selector(selector: dict | None) -> tuple[str, str]:
    if not isinstance(selector, dict):
        raise CodeAccessError("exactly_one_selector_required")
    if set(selector) != {"type", "id"}:
        raise CodeAccessError("exactly_one_selector_required")
    selector_type = selector.get("type")
    selector_id = selector.get("id")
    if selector_type not in {"item", "source", "match"}:
        raise CodeAccessError("unsupported_code_selector")
    if not isinstance(selector_id, str) or not selector_id:
        raise CodeAccessError("invalid_code_selector")
    return str(selector_type), selector_id


class CodeAccessService:
    def __init__(
        self,
        *,
        root: str | Path | None = None,
        structures: StructureStore | None = None,
    ) -> None:
        self._root = root
        self._structures = structures or StructureStore(root=root)

    def _manifest(self, project_id: str, run_id: str) -> AcquisitionManifest:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=64 * 1024 * 1024,
        )

    @staticmethod
    def _acquired(
        manifest: dict,
        *,
        lead_id: str,
        context_ref: str,
    ) -> dict:
        record = (manifest.get("leads") or {}).get(lead_id) or {}
        if (
            record.get("status") != "acquired"
            or not record.get("available")
            or (record.get("context_ref") or "") != (context_ref or "")
        ):
            raise CodeAccessError("lead_not_acquired")
        return record

    def read_target(self, *, reference: str, selector: dict) -> dict:
        selector_type, selector_id = _selector(selector)
        scope = resolve_js_intake_reference(reference)
        manifest = self._manifest(scope.project_id, scope.run_id).get()
        if selector_type == "item":
            try:
                item = self._structures.private_item(
                    project_id=scope.project_id,
                    run_id=scope.run_id,
                    context_ref=scope.context_ref,
                    item_id=selector_id,
                )
            except StructureStoreError as exc:
                reason = (
                    "item_outside_context"
                    if exc.reason == "structure_item_missing"
                    else exc.reason
                )
                raise CodeAccessError(reason) from None
            lead_id = str(item.get("lead_id") or "")
            acquired = self._acquired(
                manifest,
                lead_id=lead_id,
                context_ref=scope.context_ref,
            )
            try:
                current_index = self._structures.current_index_id(
                    project_id=scope.project_id,
                    run_id=scope.run_id,
                    context_ref=scope.context_ref,
                    lead_id=lead_id,
                )
            except StructureStoreError:
                raise CodeAccessError("item_stale") from None
            if (
                current_index != item.get("index_id")
                or acquired.get("sha256") != item.get("source_sha256")
                or int(acquired.get("size") or -1)
                != int(item.get("source_size") or -2)
            ):
                raise CodeAccessError("item_stale")
            start = int(item.get("start_byte") or 0)
            end = int(item.get("end_byte") or 0)
            target = CodeTarget(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                lead_id=lead_id,
                selector_type=selector_type,
                selector_id=selector_id,
                work_file_ref=str(acquired["work_file_ref"]),
                content_sha256=str(acquired["sha256"]),
                size=int(acquired["size"]),
                range_start=start,
                range_end=end,
                kind=f"item:{item.get('kind') or 'unknown'}",
            )
            return target.public()
        if selector_type == "source":
            source = (
                (manifest.get("recovery") or {})
                .get("sources", {})
                .get(selector_id)
                or {}
            )
            if (
                not source
                or (source.get("context_ref") or "") != (scope.context_ref or "")
            ):
                raise CodeAccessError("source_outside_context")
            if source.get("status") != "available" or not source.get("available"):
                raise CodeAccessError("source_unavailable")
            lead_id = str(source.get("lead_id") or "")
            self._acquired(
                manifest,
                lead_id=lead_id,
                context_ref=scope.context_ref,
            )
            size = int(source.get("size") or 0)
            target = CodeTarget(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                lead_id=lead_id,
                selector_type=selector_type,
                selector_id=selector_id,
                work_file_ref=str(source.get("work_file_ref") or ""),
                content_sha256=str(source.get("content_sha256") or ""),
                size=size,
                range_start=0,
                range_end=size,
                kind=str(source.get("kind") or "unknown"),
            )
            return target.public()

        from polymerhus.recon.js_acquisition.code_search import (
            CodeSearchError,
            CodeSearchService,
        )

        try:
            match = CodeSearchService(root=self._root).read_match(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                match_id=selector_id,
            )
        except CodeSearchError as exc:
            raise CodeAccessError(exc.reason) from None
        source = match.get("source") or {}
        lead_id = str(source.get("lead_id") or "")
        self._acquired(
            manifest,
            lead_id=lead_id,
            context_ref=scope.context_ref,
        )
        size = int(source.get("size") or 0)
        start = int(match.get("start_byte") or 0)
        end = int(match.get("end_byte") or 0)
        target = CodeTarget(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            lead_id=lead_id,
            selector_type=selector_type,
            selector_id=selector_id,
            work_file_ref=str(source.get("work_file_ref") or ""),
            content_sha256=str(source.get("content_sha256") or ""),
            size=size,
            range_start=max(0, start - DEFAULT_WINDOW_BYTES // 2),
            range_end=min(size, start + DEFAULT_WINDOW_BYTES // 2),
            kind=str(source.get("kind") or "unknown"),
            focus_around=start,
        )
        return target.public()

    @staticmethod
    def _binding(target: CodeTarget) -> bytes:
        return "\0".join(
            (
                target.project_id,
                target.run_id,
                target.context_ref,
                target.selector_type,
                target.selector_id,
                target.content_sha256,
                REDACTION_POLICY_ID,
            )
        ).encode("utf-8")

    def _target_private(
        self,
        *,
        reference: str,
        selector: dict,
    ) -> tuple[CodeTarget, object]:
        scope = resolve_js_intake_reference(reference)
        public = self.read_target(reference=reference, selector=selector)
        return (
            CodeTarget(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                lead_id=public["lead_id"],
                selector_type=public["selector"]["type"],
                selector_id=public["selector"]["id"],
                work_file_ref=public["work_file_ref"],
                content_sha256=public["content_sha256"],
                size=public["size"],
                range_start=public["range_start"],
                range_end=public["range_end"],
                kind=public["kind"],
                focus_around=public.get("focus_around"),
            ),
            scope,
        )

    def _encode_cursor(self, target: CodeTarget, offset: int) -> str:
        body = json.dumps({"offset": offset}, separators=(",", ":")).encode()
        digest = hashlib.sha256(self._binding(target) + body).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")

    def _decode_cursor(self, target: CodeTarget, cursor: str | None) -> int:
        if not cursor:
            return target.range_start
        try:
            payload = base64.urlsafe_b64decode(
                cursor + "=" * (-len(cursor) % 4)
            )
            body, observed = payload[:-8], payload[-8:]
            expected = hashlib.sha256(
                self._binding(target) + body
            ).digest()[:8]
            value = json.loads(body)
            offset = value.get("offset")
            if (
                observed != expected
                or not isinstance(offset, int)
                or offset < target.range_start
                or offset > target.range_end
            ):
                raise ValueError
            return offset
        except Exception:
            raise CodeAccessError("invalid_code_cursor") from None

    @staticmethod
    def _boundaries(source: bytes) -> tuple[list[int], dict[int, int]]:
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError:
            raise CodeAccessError("unsupported_encoding") from None
        byte_offsets = [0]
        reverse = {0: 0}
        position = 0
        for index, char in enumerate(text, start=1):
            position += len(char.encode("utf-8"))
            byte_offsets.append(position)
            reverse[position] = index
        return byte_offsets, reverse

    def prepare_read(
        self,
        *,
        reference: str,
        selector: dict,
        source_bytes: bytes,
        cursor: str | None = None,
        window_bytes: int = DEFAULT_WINDOW_BYTES,
    ) -> dict:
        if not isinstance(source_bytes, bytes):
            raise CodeAccessError("source_must_be_bytes")
        if (
            not isinstance(window_bytes, int)
            or isinstance(window_bytes, bool)
            or window_bytes <= 0
            or window_bytes > MAX_WINDOW_BYTES
        ):
            raise CodeAccessError("invalid_window_bytes")
        target, scope = self._target_private(
            reference=reference,
            selector=selector,
        )
        digest = hashlib.sha256(source_bytes).hexdigest()
        if digest != target.content_sha256 or len(source_bytes) != target.size:
            raise CodeAccessError("content_mismatch")
        boundaries, _ = self._boundaries(source_bytes)
        if cursor:
            start = self._decode_cursor(target, cursor)
            if start not in set(boundaries):
                raise CodeAccessError("invalid_utf8_window_boundary")
        else:
            boundary_index = bisect.bisect_right(
                boundaries,
                target.range_start,
            ) - 1
            start = boundaries[max(0, boundary_index)]
        proposed_end = min(target.range_end, start + window_bytes)
        while proposed_end > start and proposed_end not in set(boundaries):
            proposed_end -= 1
        if proposed_end == start and start < target.range_end:
            proposed_end = next(
                (value for value in boundaries if value > start),
                start,
            )
        end = proposed_end
        try:
            redacted = redact_window(source_bytes, start, end)
        except CodeRedactionError as exc:
            raise CodeAccessError(exc.reason) from None
        read_id = "read_" + hashlib.sha256(
            self._binding(target)
            + json.dumps(
                [start, end, redacted.policy_id],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:32]
        response = {
            "read_id": read_id,
            "lead_id": target.lead_id,
            "selector": {
                "type": target.selector_type,
                "id": target.selector_id,
            },
            "content_sha256": target.content_sha256,
            "source_size": target.size,
            "kind": target.kind,
            "content_state": "empty" if target.size == 0 else "text",
            "original_start": start,
            "original_end": end,
            "display_sha256": hashlib.sha256(
                redacted.display.encode("utf-8")
            ).hexdigest(),
            "code": redacted.display,
            "redacted": True,
            "redaction_policy": redacted.policy_id,
            "redaction_count": redacted.redaction_count,
            "redaction_kinds": list(redacted.redaction_kinds),
            "next_cursor": (
                self._encode_cursor(target, end)
                if end < target.range_end
                else None
            ),
            "delivery_status": "prepared",
        }
        record = {
            "read_id": read_id,
            "project_id": scope.project_id,
            "run_id": scope.run_id,
            "context_ref": scope.context_ref,
            "lead_id": target.lead_id,
            "selector_type": target.selector_type,
            "selector_id": target.selector_id,
            "content_sha256": target.content_sha256,
            "start_byte": start,
            "end_byte": end,
            "display_sha256": response["display_sha256"],
            "redaction_policy": redacted.policy_id,
            "redaction_count": redacted.redaction_count,
            "delivery_status": "prepared",
            "created_at": int(time.time()),
        }

        def mutate(value: dict) -> None:
            reads = value.setdefault("code_access", {}).setdefault("reads", {})
            prior = reads.get(read_id) or {}
            if prior.get("delivery_status") == "delivered":
                record["delivery_status"] = "delivered"
                record["created_at"] = prior.get("created_at") or record["created_at"]
            reads[read_id] = record

        self._manifest(scope.project_id, scope.run_id).update(mutate)
        return response

    def confirm_read(self, *, reference: str, read_id: str) -> dict:
        scope = resolve_js_intake_reference(reference)
        manifest = self._manifest(scope.project_id, scope.run_id)
        result = {"read_id": read_id, "delivery_status": "missing"}

        def mutate(value: dict) -> None:
            record = (
                value.setdefault("code_access", {})
                .setdefault("reads", {})
                .get(read_id)
            )
            if (
                not record
                or record.get("context_ref") != (scope.context_ref or "")
            ):
                return
            if record.get("delivery_status") == "delivered":
                result["delivery_status"] = "delivered"
                result["idempotent"] = True
                return
            record["delivery_status"] = "delivered"
            record["delivered_at"] = int(time.time())
            result["delivery_status"] = "delivered"
            result["idempotent"] = False

        manifest.update(mutate)
        if result["delivery_status"] == "missing":
            raise CodeAccessError("read_receipt_missing")
        return result

    def validate_read_for_focus(
        self,
        *,
        reference: str,
        read_id: str,
        focus: dict,
    ) -> bool:
        scope = resolve_js_intake_reference(reference)
        record = (
            self._manifest(scope.project_id, scope.run_id)
            .get()
            .get("code_access", {})
            .get("reads", {})
            .get(read_id)
            or {}
        )
        return bool(
            record
            and record.get("context_ref") == (scope.context_ref or "")
            and record.get("delivery_status") == "delivered"
            and record.get("content_sha256") == focus.get("content_sha256")
            and int(record.get("start_byte") or 0)
            <= int(focus.get("start_byte") or 0)
            and int(record.get("end_byte") or -1)
            >= int(focus.get("end_byte") or -1)
        )

    def read_receipt(self, *, reference: str, read_id: str) -> dict:
        scope = resolve_js_intake_reference(reference)
        record = (
            self._manifest(scope.project_id, scope.run_id)
            .get()
            .get("code_access", {})
            .get("reads", {})
            .get(read_id)
            or {}
        )
        if not record or record.get("context_ref") != (scope.context_ref or ""):
            return {}
        return dict(record)


__all__ = [
    "CodeAccessError",
    "CodeAccessService",
    "CodeTarget",
    "DEFAULT_WINDOW_BYTES",
    "MAX_WINDOW_BYTES",
]
