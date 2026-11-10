"""Authorized orchestration for generated-JS structure indexing and reads."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.structure import (
    ParsedStructure,
    StructureLimits,
    StructureParseError,
    parse_structure_bytes,
)
from polymerhus.recon.js_acquisition.structure_store import (
    StructureStore,
    StructureStoreError,
)
from polymerhus.recon.js_intake import (
    InvalidJsIntakeReference,
    JsIntakeLeadNotFound,
    JsIntakeReader,
    JsIntakeStore,
    resolve_js_intake_reference,
)

_CURRENT_PARSER = {
    "name": "@babel/parser",
    "version": "8.0.8",
    "traverse_version": "8.0.7",
}


class StructureError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StructureService:
    def __init__(
        self,
        *,
        root: str | Path | None = None,
        parser: Callable[[bytes], ParsedStructure] | None = None,
        store: StructureStore | None = None,
    ) -> None:
        self._root = root
        self._parser = parser
        self._uses_default_parser = parser is None
        self._store = store or StructureStore(root=root)
        self._intake = JsIntakeReader(root=root)

    def _manifest(self, project_id: str, run_id: str) -> AcquisitionManifest:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=64 * 1024 * 1024,
        )

    def _lead_scope(self, reference: str, lead_id: str):
        try:
            self._intake.get_private(reference=reference, lead_id=lead_id)
            return resolve_js_intake_reference(reference)
        except InvalidJsIntakeReference:
            raise StructureError("structure_reference_invalid") from None
        except JsIntakeLeadNotFound:
            raise StructureError("structure_lead_not_found") from None

    def _acquired_record(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
    ) -> dict:
        record = (
            self._manifest(project_id, run_id)
            .get()
            .get("leads", {})
            .get(lead_id)
            or {}
        )
        if (
            record.get("status") != "acquired"
            or not record.get("available")
            or not record.get("work_file_ref")
            or (record.get("context_ref") or "") != (context_ref or "")
        ):
            raise StructureError("structure_input_unavailable")
        return record

    def structure_from_source(
        self,
        *,
        reference: str,
        lead_id: str,
        source_bytes: bytes,
        deadline_s: float | None = None,
    ) -> dict:
        if not isinstance(source_bytes, bytes):
            raise StructureError("structure_source_must_be_bytes")
        scope = self._lead_scope(reference, lead_id)
        record = self._acquired_record(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            lead_id=lead_id,
        )
        digest = hashlib.sha256(source_bytes).hexdigest()
        if (
            digest != record.get("sha256")
            or len(source_bytes) != int(record.get("size") or 0)
        ):
            raise StructureError("structure_source_mismatch")

        reusable = self._store.find_index(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            lead_id=lead_id,
            source_sha256=digest,
            parser_identity=_CURRENT_PARSER,
            config_identity=self._store.config_identity(),
        )
        if reusable is not None:
            return {
                **reusable,
                "source_availability": "verified_current",
                "reused": True,
            }

        try:
            if self._uses_default_parser:
                remaining = min(
                    20.0,
                    max(0.001, deadline_s if deadline_s is not None else 20.0),
                )
                parsed = parse_structure_bytes(
                    source_bytes,
                    limits=StructureLimits(
                        deadline_s=remaining,
                        parser_timeout_s=remaining,
                    ),
                )
            else:
                assert self._parser is not None
                parsed = self._parser(source_bytes)
            stored = self._store.store_index(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                lead_id=lead_id,
                source_bytes=source_bytes,
                parsed=parsed,
                parent_final_url=str(record.get("final_url") or ""),
            )
        except StructureParseError as exc:
            raise StructureError(f"structure_parse_{exc.reason}") from None
        except StructureStoreError as exc:
            raise StructureError(exc.reason) from None
        return {
            **stored,
            "source_availability": "verified_current",
            "reused": False,
            "parser_memory_bytes": parsed.parser_memory_bytes,
            "index_bytes": parsed.index_bytes,
        }

    def list_items(
        self,
        *,
        reference: str,
        lead_id: str,
        kind: str | None = None,
        cursor: str | None = None,
        limit: int = 5,
    ) -> dict:
        scope = self._lead_scope(reference, lead_id)
        try:
            result = self._store.list_items(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                lead_id=lead_id,
                kind=kind,
                cursor=cursor,
                limit=limit,
            )
        except StructureStoreError as exc:
            raise StructureError(exc.reason) from None
        return {**result, "source_availability": "historical_index"}

    def get_item(self, *, reference: str, item_id: str) -> dict:
        try:
            scope = resolve_js_intake_reference(reference)
        except InvalidJsIntakeReference:
            raise StructureError("structure_reference_invalid") from None
        try:
            result = self._store.get_item(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                item_id=item_id,
            )
        except StructureStoreError as exc:
            raise StructureError(exc.reason) from None
        return {**result, "source_availability": "historical_index"}

    @staticmethod
    def _same_origin(left: str, right: str) -> bool:
        left_parts = urlsplit(left)
        right_parts = urlsplit(right)
        return (
            left_parts.scheme.lower(),
            (left_parts.hostname or "").lower(),
            left_parts.port,
        ) == (
            right_parts.scheme.lower(),
            (right_parts.hostname or "").lower(),
            right_parts.port,
        )

    def register_reference(self, *, reference: str, item_id: str) -> dict:
        try:
            scope = resolve_js_intake_reference(reference)
        except InvalidJsIntakeReference:
            raise StructureError("structure_reference_invalid") from None
        try:
            private = self._store.private_item(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                item_id=item_id,
            )
        except StructureStoreError as exc:
            raise StructureError(exc.reason) from None
        parent_lead_id = str(private.get("lead_id") or "")
        try:
            parent_lead, _ = self._intake.get_private(
                reference=reference,
                lead_id=parent_lead_id,
            )
        except JsIntakeLeadNotFound:
            raise StructureError("structure_lead_not_found") from None
        acquired = self._acquired_record(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            lead_id=parent_lead_id,
        )
        current = self._store.find_index(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            lead_id=parent_lead_id,
            source_sha256=str(acquired.get("sha256") or ""),
            parser_identity=_CURRENT_PARSER,
            config_identity=self._store.config_identity(),
        )
        if (
            current is None
            or current.get("index_id") != private.get("index_id")
        ):
            raise StructureError("structure_item_stale")
        if (
            private.get("kind") != "import"
            or not private.get("resolved")
            or private.get("subtype") not in {"static", "dynamic"}
        ):
            raise StructureError("unsupported_reference_kind")
        specifier = private.get("specifier")
        if not isinstance(specifier, str) or not specifier:
            raise StructureError("unresolved_reference")
        parent_url = str(private.get("parent_final_url") or "")
        if not parent_url:
            raise StructureError("parent_final_url_unavailable")

        parts = urlsplit(specifier)
        if parts.scheme and parts.scheme.lower() not in {"http", "https"}:
            raise StructureError("unsupported_reference_scheme")
        if not parts.scheme and not specifier.startswith(("/", "./", "../")):
            raise StructureError("import_map_context_missing")
        exact_url = (
            specifier
            if parts.scheme
            else urljoin(parent_url, specifier)
        )
        resolved = urlsplit(exact_url)
        if (
            resolved.scheme.lower() not in {"http", "https"}
            or not resolved.hostname
        ):
            raise StructureError("invalid_reference_url")
        if resolved.username or resolved.password:
            raise StructureError("reference_credentials_forbidden")
        host = resolved.hostname.lower().rstrip(".")
        domains = tuple(domain.lower().rstrip(".") for domain in scope.scope_domains)
        host_allowed = any(
            host == domain or host.endswith(f".{domain}")
            for domain in domains
        )
        if not (
            self._same_origin(parent_url, exact_url)
            or (domains and host_allowed)
        ):
            raise StructureError("reference_out_of_scope")

        registered = JsIntakeStore(root=self._root).record_code_derived_lead(
            project_id=scope.project_id,
            run_id=scope.run_id,
            context_ref=scope.context_ref,
            parent_lead_id=parent_lead_id,
            parent_item_id=item_id,
            parent_index_id=str(private.get("index_id") or ""),
            parent_source_sha256=str(private.get("source_sha256") or ""),
            exact_url=exact_url,
            input_context_ref=str(parent_lead.get("input_context_ref") or ""),
            auth_context_label=str(
                parent_lead.get("auth_context_label") or "anonymous"
            ),
        )
        return {"status": "registered", **registered}


__all__ = ["StructureError", "StructureService"]
