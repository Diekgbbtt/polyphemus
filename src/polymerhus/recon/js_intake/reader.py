"""Bounded, redacted reader for the JavaScript intake inventory."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from polymerhus.app.data_root import project_dir, validate_path_component
from polymerhus.recon.js_intake.redaction import redact_url

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100
_DEFAULT_TTL_S = 300


class InvalidJsIntakeReference(ValueError):
    pass


class JsIntakeLeadNotFound(LookupError):
    pass


@dataclass(frozen=True)
class JsIntakeScope:
    project_id: str
    run_id: str
    context_ref: str
    scope_domains: tuple[str, ...]
    expires_at: float
    allow_http_replay: bool = True


_REFERENCES: dict[str, JsIntakeScope] = {}


def issue_js_intake_reference(
    project_id: str,
    run_id: str,
    *,
    context_ref: str = "",
    scope_domains: Sequence[str] = (),
    ttl_s: int = _DEFAULT_TTL_S,
    allow_http_replay: bool = True,
) -> str:
    validate_path_component(project_id, "project_id")
    validate_path_component(run_id, "run_id")
    if ttl_s <= 0:
        raise ValueError("ttl_s must be positive")
    normalized_domains = tuple(
        dict.fromkeys(
            domain.strip().lower().rstrip(".")
            for domain in scope_domains
            if isinstance(domain, str) and domain.strip()
        )
    )
    token = secrets.token_urlsafe(24)
    _REFERENCES[token] = JsIntakeScope(
        project_id=project_id,
        run_id=run_id,
        context_ref=context_ref,
        scope_domains=normalized_domains,
        expires_at=time.monotonic() + ttl_s,
        allow_http_replay=allow_http_replay,
    )
    return token


def resolve_js_intake_reference(reference: str) -> JsIntakeScope:
    scope = _REFERENCES.get(reference)
    if scope is None or scope.expires_at <= time.monotonic():
        _REFERENCES.pop(reference, None)
        raise InvalidJsIntakeReference("unknown or expired JavaScript intake reference")
    return scope


def _binding(scope: JsIntakeScope) -> bytes:
    return f"{scope.project_id}\0{scope.run_id}\0{scope.context_ref}".encode()


def _encode_cursor(scope: JsIntakeScope, offset: int) -> str:
    body = json.dumps({"offset": offset}, separators=(",", ":")).encode()
    digest = hashlib.sha256(_binding(scope) + body).digest()[:8]
    return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")


def _decode_cursor(scope: JsIntakeScope, cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = base64.urlsafe_b64decode(padded.encode())
        body, digest = payload[:-8], payload[-8:]
        expected = hashlib.sha256(_binding(scope) + body).digest()[:8]
        if not secrets.compare_digest(digest, expected):
            raise ValueError
        offset = json.loads(body).get("offset")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (ValueError, TypeError, json.JSONDecodeError):
        raise InvalidJsIntakeReference("invalid or out-of-scope cursor") from None


def _public_lead(lead: dict) -> dict:
    discovery_class = lead.get("discovery_class")
    discovery_classes = lead.get("discovery_classes")
    if not isinstance(discovery_classes, list):
        discovery_classes = [discovery_class] if discovery_class else []
    script_ids = lead.get("script_ids")
    if not isinstance(script_ids, list):
        script_ids = []
    return {
        "lead_id": lead.get("lead_id"),
        "redacted_url": redact_url(str(lead.get("exact_url") or "")),
        "source_pod": lead.get("source_pod"),
        "source_tool": lead.get("source_tool"),
        "discovery_class": discovery_class,
        "discovery_classes": [
            value for value in discovery_classes if isinstance(value, str)
        ],
        "script_ids": [value for value in script_ids if isinstance(value, str)],
        "status": lead.get("status"),
        "content_type": lead.get("content_type"),
        "auth_context_label": lead.get("auth_context_label"),
        "input_context_ref": lead.get("input_context_ref"),
    }


class JsIntakeReader:
    def __init__(self, *, root: str | Path | None = None) -> None:
        self._root = root

    def _load(self, scope: JsIntakeScope) -> tuple[list[dict], list[dict], bool]:
        run_dir = (
            project_dir(scope.project_id, "recon/js-intake", root=self._root)
            / scope.run_id
        )
        if not run_dir.is_dir():
            return [], [], False
        pods: list[dict] = []
        leads: list[dict] = []
        context_inventory_present = False
        for path in sorted(run_dir.glob("*.jsonl")):
            records: list[dict] = []
            try:
                for raw_line in path.read_text(encoding="utf-8").split("\n"):
                    if raw_line.strip():
                        value = json.loads(raw_line)
                        if isinstance(value, dict):
                            records.append(value)
            except (OSError, UnicodeError, json.JSONDecodeError):
                records = []
            if (
                not records
                or records[0].get("record_type") not in {"pod", "derived"}
            ):
                continue
            envelope = records[0]
            if (envelope.get("auth_context_ref") or "") != scope.context_ref:
                continue
            context_inventory_present = True
            if envelope.get("record_type") == "derived":
                leads.extend(
                    record
                    for record in records[1:]
                    if record.get("record_type") == "lead"
                    and (record.get("auth_context_ref") or "")
                    == scope.context_ref
                )
                continue
            pods.append(
                {
                    "pod_id": envelope.get("pod_id") or path.stem,
                    "producer": envelope.get("producer") or "unknown",
                    "terminal_result": envelope.get("terminal_result") or "unknown",
                    "output_completeness": (
                        envelope.get("output_completeness") or "unknown"
                    ),
                    "lead_count": envelope.get("lead_count", 0),
                    "path_key_count": envelope.get("path_key_count", 0),
                    "parse_error_count": envelope.get("parse_error_count", 0),
                }
            )
            leads.extend(
                r
                for r in records[1:]
                if r.get("record_type") == "lead"
                and (r.get("auth_context_ref") or "") == scope.context_ref
            )
        leads.sort(
            key=lambda row: (
                row.get("source_pod") or "",
                row.get("lead_id") or "",
            )
        )
        return pods, leads, context_inventory_present

    def list(
        self,
        *,
        reference: str,
        cursor: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> dict:
        scope = resolve_js_intake_reference(reference)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        limit = min(limit, _MAX_LIMIT)
        offset = _decode_cursor(scope, cursor)
        pods, leads, inventory_present = self._load(scope)
        window = leads[offset : offset + limit]
        public_leads = [_public_lead(lead) for lead in window]
        next_offset = offset + len(window)
        complete_zero_result = bool(pods) and all(
            pod.get("output_completeness") == "complete"
            and pod.get("lead_count") == 0
            for pod in pods
        )
        if not inventory_present:
            coverage_gap = "missing_inventory"
        elif any(
            pod.get("output_completeness") in {"failed", "partial", "unknown"}
            for pod in pods
        ):
            coverage_gap = "incomplete_or_unknown"
        else:
            coverage_gap = None
        return {
            "leads": public_leads,
            "pods": pods,
            "next_cursor": (
                _encode_cursor(scope, next_offset)
                if next_offset < len(leads)
                else None
            ),
            "coverage": {
                "inventory_present": inventory_present,
                "inventory_state": "present" if inventory_present else "missing",
                "complete_zero_result": complete_zero_result,
                "lead_count": len(leads),
                "coverage_gap": coverage_gap,
            },
        }

    def get(self, *, reference: str, lead_id: str) -> dict:
        scope = resolve_js_intake_reference(reference)
        _, leads, _ = self._load(scope)
        for lead in leads:
            if lead.get("lead_id") == lead_id:
                return _public_lead(lead)
        raise JsIntakeLeadNotFound(
            "lead is not present in the referenced JavaScript intake run"
        )

    def get_private(
        self, *, reference: str, lead_id: str
    ) -> tuple[dict, JsIntakeScope]:
        """Resolve exact lead data for trusted in-process services only."""
        scope = resolve_js_intake_reference(reference)
        _, leads, _ = self._load(scope)
        for lead in leads:
            if lead.get("lead_id") == lead_id:
                return dict(lead), scope
        raise JsIntakeLeadNotFound(
            "lead is not present in the referenced JavaScript intake run"
        )



def renew_js_intake_reference(reference: str, *, ttl_s: int) -> str:
    """Trusted renewal of the same scope AND acquisition restrictions."""
    scope = resolve_js_intake_reference(reference)
    return issue_js_intake_reference(scope.project_id, scope.run_id, context_ref=scope.context_ref,
        scope_domains=scope.scope_domains, allow_http_replay=scope.allow_http_replay, ttl_s=ttl_s)
