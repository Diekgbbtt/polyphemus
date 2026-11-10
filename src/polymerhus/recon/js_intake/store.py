"""Atomic per-pod JavaScript intake storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from polymerhus.app.data_root import project_dir, validate_path_component
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_intake.extract import (
    Extraction,
    extract_ffuf,
    extract_katana,
    extract_steel,
)

_SCHEMA_VERSION = 1
_PRODUCERS = {"katana", "ffuf", "steel_crawl"}


def _lead_id(project_id: str, run_id: str, pod_id: str, exact_url: str) -> str:
    digest = hashlib.sha256(
        f"{project_id}\0{run_id}\0{pod_id}\0{exact_url}".encode("utf-8")
    ).hexdigest()
    return f"lead_{digest[:24]}"


def _derived_lead_id(
    project_id: str,
    run_id: str,
    context_ref: str,
    parent_item_id: str,
    exact_url: str,
) -> str:
    digest = hashlib.sha256(
        (
            f"{project_id}\0{run_id}\0{context_ref}\0"
            f"{parent_item_id}\0{exact_url}"
        ).encode("utf-8")
    ).hexdigest()
    return f"lead_{digest[:24]}"


def _path_key(exact_url: str) -> str:
    try:
        parts = urlsplit(exact_url)
    except ValueError:
        return ""
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return f"{parts.scheme}://{host}{parts.path}"


class JsIntakeStore:
    def __init__(self, *, root: str | Path | None = None) -> None:
        self._root = root

    def _run_dir(self, project_id: str, run_id: str) -> Path:
        validate_path_component(run_id, "run_id")
        return project_dir(project_id, "recon/js-intake", root=self._root) / run_id

    def _write(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        producer: str,
        input_context_ref: str,
        terminal_result: str,
        extraction: Extraction,
        auth_context_label: str,
        auth_context_ref: str | None,
    ) -> Path:
        validate_path_component(pod_id, "pod_id")
        if producer not in _PRODUCERS:
            raise ValueError(f"unsupported JS intake producer {producer!r}")

        path_keys = {_path_key(lead.exact_url) for lead in extraction.leads}
        path_keys.discard("")
        envelope = {
            "record_type": "pod",
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id,
            "pod_id": pod_id,
            "producer": producer,
            "input_context_ref": input_context_ref,
            "auth_context_label": auth_context_label,
            "auth_context_ref": auth_context_ref,
            "terminal_result": terminal_result,
            "output_completeness": extraction.completeness,
            "lead_count": len(extraction.leads),
            "path_key_count": len(path_keys),
            "parse_error_count": extraction.parse_errors,
        }
        records = [envelope]
        for lead in extraction.leads:
            discovery_classes = list(lead.discovery_classes) or [
                lead.discovery_class
            ]
            records.append(
                {
                    "record_type": "lead",
                    "schema_version": _SCHEMA_VERSION,
                    "lead_id": _lead_id(project_id, run_id, pod_id, lead.exact_url),
                    "exact_url": lead.exact_url,
                    "path_key": _path_key(lead.exact_url),
                    "source_pod": pod_id,
                    "source_tool": producer,
                    "discovery_class": lead.discovery_class,
                    "discovery_classes": discovery_classes,
                    "script_ids": list(lead.script_ids),
                    "status": lead.status,
                    "content_type": lead.content_type,
                    "input_context_ref": input_context_ref,
                    "auth_context_label": auth_context_label,
                    "auth_context_ref": auth_context_ref,
                }
            )

        run_dir = self._run_dir(project_id, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        destination = run_dir / f"{pod_id}.jsonl"
        body = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        )
        fd, temp_name = tempfile.mkstemp(
            dir=run_dir, prefix=f".{pod_id}.", suffix=".tmp"
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return destination

    def record_code_derived_lead(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        parent_lead_id: str,
        parent_item_id: str,
        parent_index_id: str,
        parent_source_sha256: str,
        exact_url: str,
        input_context_ref: str,
        auth_context_label: str,
    ) -> dict:
        """Register one literal code reference without mutating crawl output."""
        validate_path_component(parent_item_id, "parent_item_id")
        lead_id = _derived_lead_id(
            project_id,
            run_id,
            context_ref,
            parent_item_id,
            exact_url,
        )
        envelope = {
            "record_type": "derived",
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id,
            "batch_id": parent_item_id,
            "producer": "code_derived",
            "input_context_ref": input_context_ref,
            "auth_context_label": auth_context_label,
            "auth_context_ref": context_ref or None,
            "terminal_result": "success",
            "output_completeness": "complete",
            "lead_count": 1,
            "path_key_count": 1,
            "parse_error_count": 0,
        }
        lead = {
            "record_type": "lead",
            "schema_version": _SCHEMA_VERSION,
            "lead_id": lead_id,
            "exact_url": exact_url,
            "path_key": _path_key(exact_url),
            "source_pod": None,
            "source_tool": "code_derived",
            "discovery_class": "code_reference",
            "status": "discovered",
            "content_type": None,
            "input_context_ref": input_context_ref,
            "auth_context_label": auth_context_label,
            "auth_context_ref": context_ref or None,
            "parent_lead_id": parent_lead_id,
            "parent_item_id": parent_item_id,
            "parent_index_id": parent_index_id,
            "parent_source_sha256": parent_source_sha256,
        }
        run_dir = self._run_dir(project_id, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        destination = run_dir / f"derived-{parent_item_id}.jsonl"
        body = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in (envelope, lead)
        )
        fd, temp_name = tempfile.mkstemp(
            dir=run_dir,
            prefix=f".derived-{parent_item_id}.",
            suffix=".tmp",
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return {
            "lead_id": lead_id,
            "parent_item_id": parent_item_id,
            "parent_lead_id": parent_lead_id,
            "discovery_class": "code_reference",
            "source_tool": "code_derived",
        }

    def record_exec_result(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        producer: str,
        input_context_ref: str,
        exec_result: ExecResult,
        auth_context_label: str = "anonymous",
        auth_context_ref: str | None = None,
    ) -> Path:
        if producer == "katana":
            extraction = extract_katana(exec_result.stdout)
        elif producer == "ffuf":
            return self.record_manifest(
                project_id=project_id,
                run_id=run_id,
                pod_id=pod_id,
                producer=producer,
                input_context_ref=input_context_ref,
                manifest=exec_result.stdout,
                auth_context_label=auth_context_label,
                auth_context_ref=auth_context_ref,
                terminal_result=(
                    "success" if exec_result.returncode == 0 else "failed"
                ),
            )
        else:
            raise ValueError(f"{producer!r} does not use an exec result")
        terminal_result = "success" if exec_result.returncode == 0 else "failed"
        if terminal_result == "failed":
            extraction.completeness = "failed"
        return self._write(
            project_id=project_id,
            run_id=run_id,
            pod_id=pod_id,
            producer=producer,
            input_context_ref=input_context_ref,
            terminal_result=terminal_result,
            extraction=extraction,
            auth_context_label=auth_context_label,
            auth_context_ref=auth_context_ref,
        )

    def record_manifest(
        self,
        *,
        project_id: str,
        run_id: str,
        pod_id: str,
        producer: str,
        input_context_ref: str,
        manifest: dict | str | None,
        terminal_result: str,
        output_completeness: str | None = None,
        auth_context_label: str = "anonymous",
        auth_context_ref: str | None = None,
    ) -> Path:
        if producer == "steel_crawl":
            extraction = (
                Extraction(completeness="failed")
                if manifest is None and terminal_result == "failed"
                else extract_steel(manifest if isinstance(manifest, dict) else None)
            )
        elif producer == "ffuf":
            if isinstance(manifest, dict):
                extraction = extract_ffuf(json.dumps(manifest))
            else:
                extraction = extract_ffuf(manifest or "")
        else:
            raise ValueError(f"{producer!r} does not use a manifest")
        if output_completeness is not None:
            extraction.completeness = output_completeness
        if terminal_result == "failed":
            extraction.completeness = "failed"
        return self._write(
            project_id=project_id,
            run_id=run_id,
            pod_id=pod_id,
            producer=producer,
            input_context_ref=input_context_ref,
            terminal_result=terminal_result,
            extraction=extraction,
            auth_context_label=auth_context_label,
            auth_context_ref=auth_context_ref,
        )
