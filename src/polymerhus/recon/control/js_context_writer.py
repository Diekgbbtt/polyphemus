"""Deterministic final publication from already saved JS run records."""

from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict

from pydantic import ValidationError

from polymerhus.app.js_context.records import (
    JsContextInvalidError,
    MAX_COVERAGE_GAPS,
    MAX_GAPS,
    document_identity,
    normalize_origin,
    validate_behavior,
    validate_document,
)
from polymerhus.app.js_context.store import JsContextStore
from polymerhus.recon.js_acquisition.code_access import CodeAccessService
from polymerhus.recon.js_intake import resolve_js_intake_reference
from polymerhus.recon.js_retention.service import JsRetentionService
from polymerhus.recon.js_specialist.behavior import BehaviorSubmission
from polymerhus.recon.js_specialist.notes import RunNotes

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_GAP = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def _safe_gap(value: str) -> str:
    return value if _SAFE_GAP.fullmatch(value) else "retention_gap"


def _artifact_ref(value: object) -> str | None:
    if (
        isinstance(value, str)
        and value
        and len(value) <= 512
        and not any(ord(char) < 32 for char in value)
    ):
        return value
    return None


def _safe_text(value: object, *, max_length: int) -> str | None:
    if (
        isinstance(value, str)
        and value
        and len(value) <= max_length
        and not any(ord(char) < 32 for char in value)
    ):
        return value
    return None


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("js_context_publication_deadline")


def _analysis_coverage(value: object) -> dict:
    if value is None:
        return {
            "status": "partial",
            "gaps": ["analysis_coverage_unknown"],
        }
    if not isinstance(value, dict) or value.get("status") not in {
        "complete",
        "partial",
    }:
        return {
            "status": "partial",
            "gaps": ["analysis_coverage_invalid"],
        }
    raw_gaps = value.get("gaps")
    if not isinstance(raw_gaps, list):
        raw_gaps = []
    gaps = sorted(
        {
            gap
            for gap in raw_gaps
            if isinstance(gap, str) and _SAFE_GAP.fullmatch(gap)
        }
    )
    status = value["status"]
    if status == "complete" and gaps:
        status = "partial"
    if status == "partial" and not gaps:
        gaps = ["analysis_partial"]
    return {"status": status, "gaps": gaps}


class JsContextWriter:
    """Assemble and publish one run's already saved behavioural context."""

    def __init__(
        self,
        *,
        root=None,
        store: JsContextStore | None = None,
        notes_factory=None,
        access=None,
        retention=None,
    ) -> None:
        self._root = root
        self._store = store or JsContextStore(root_dir=root)
        self._notes_factory = notes_factory or (
            lambda scope: RunNotes(scope, root=root)
        )
        self._access = access or CodeAccessService(root=root)
        self._retention = retention or JsRetentionService(
            root=root,
            access=self._access,
        )

    @staticmethod
    def _valid_receipt(receipt: dict, *, scope) -> bool:
        if not isinstance(receipt, dict):
            return False
        lead_id = _safe_text(receipt.get("lead_id"), max_length=200)
        selector_id = _safe_text(receipt.get("selector_id"), max_length=200)
        policy = _safe_text(receipt.get("redaction_policy"), max_length=100)
        return bool(
            receipt.get("delivery_status") == "delivered"
            and receipt.get("project_id") == scope.project_id
            and receipt.get("run_id") == scope.run_id
            and (receipt.get("context_ref") or "") == (scope.context_ref or "")
            and lead_id is not None
            and receipt.get("selector_type") in {"item", "source", "match"}
            and selector_id is not None
            and isinstance(receipt.get("content_sha256"), str)
            and _SHA256.fullmatch(receipt["content_sha256"])
            and policy is not None
            and isinstance(receipt.get("start_byte"), int)
            and not isinstance(receipt.get("start_byte"), bool)
            and isinstance(receipt.get("end_byte"), int)
            and not isinstance(receipt.get("end_byte"), bool)
            and receipt["start_byte"] >= 0
            and receipt["end_byte"] >= receipt["start_byte"]
        )

    @staticmethod
    def _behavior(event: dict) -> dict:
        submission = BehaviorSubmission.model_validate(
            {
                "question_ref": event.get("question_ref"),
                "steps": event.get("steps"),
                "assumptions": event.get("assumptions"),
                "gaps": event.get("gaps"),
            }
        )
        behavior_id = event.get("behavior_id")
        revision = event.get("revision")
        question = event.get("question")
        priority = event.get("priority")
        lead_id = event.get("lead_id")
        reconstruction = event.get("reconstruction_level")
        record_sha = event.get("record_sha256")
        policy = event.get("redaction_policy")
        redactions = event.get("redaction_count")
        if (
            not isinstance(behavior_id, str)
            or not behavior_id
            or not _SAFE_GAP.fullmatch(behavior_id)
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
            or not isinstance(question, str)
            or not question.strip()
            or not isinstance(priority, str)
            or not priority.strip()
            or not isinstance(lead_id, str)
            or not lead_id
            or not isinstance(reconstruction, str)
            or not reconstruction
            or not isinstance(record_sha, str)
            or not _SHA256.fullmatch(record_sha)
            or not isinstance(policy, str)
            or not policy
            or not isinstance(redactions, int)
            or isinstance(redactions, bool)
            or redactions < 0
            or not isinstance(record_sha, str)
        ):
            raise ValueError("invalid_behavior_record")
        read_ids = [
            read_id
            for step in submission.steps
            for read_id in step.read_ids
        ]
        read_ids.extend(
            read_id
            for assumption in submission.assumptions
            for read_id in assumption.read_ids
        )
        if any(not _SAFE_GAP.fullmatch(read_id) for read_id in read_ids):
            raise ValueError("invalid_behavior_record")
        return validate_behavior({
            "behavior_id": behavior_id,
            "revision": revision,
            "reconstruction_level": reconstruction,
            "question_ref": submission.question_ref,
            "question": question,
            "priority": priority,
            "lead_id": lead_id,
            "record_sha256": record_sha,
            "redaction_policy": policy,
            "redaction_count": redactions,
            "steps": [
                {
                    "kind": step.kind,
                    "text": step.text,
                    "read_ids": list(step.read_ids),
                }
                for step in submission.steps
            ],
            "assumptions": [
                {
                    "text": assumption.text,
                    "status": assumption.status,
                    "read_ids": list(assumption.read_ids),
                }
                for assumption in submission.assumptions
            ],
            "gaps": list(submission.gaps),
        })

    @staticmethod
    def _read_ids(behavior: dict) -> list[str]:
        values = []
        for step in behavior["steps"]:
            values.extend(step["read_ids"])
        for assumption in behavior["assumptions"]:
            values.extend(assumption["read_ids"])
        return list(dict.fromkeys(values))

    @staticmethod
    def _read_lead_map(behaviors: list[dict]) -> dict[str, str]:
        result = {}
        for behavior in behaviors:
            for read_id in JsContextWriter._read_ids(behavior):
                result.setdefault(read_id, behavior["lead_id"])
        return result

    def _latest_behaviors(
        self,
        events: list[dict],
        *,
        scope,
    ) -> tuple[list[dict], list[str]]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        gaps = []
        for index, event in enumerate(events):
            if (event.get("context_ref") or "") != (scope.context_ref or ""):
                continue
            behavior_id = event.get("behavior_id")
            revision = event.get("revision")
            if (
                not isinstance(behavior_id, str)
                or not behavior_id
                or not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 1
            ):
                gaps.append(f"invalid_behavior_record:index-{index}")
                continue
            grouped[behavior_id].append(event)

        behaviors = []

        def gap_reference(value: object, index: int) -> str:
            return (
                value
                if isinstance(value, str) and _SAFE_GAP.fullmatch(value)
                else f"index-{index}"
            )

        for behavior_id in sorted(grouped):
            candidates = grouped[behavior_id]
            latest_revision = max(int(item["revision"]) for item in candidates)
            latest = [
                item
                for item in candidates
                if int(item["revision"]) == latest_revision
            ]
            if len(latest) != 1:
                gaps.append(
                    "duplicate_behavior_revision:"
                    + gap_reference(behavior_id, events.index(candidates[0]))
                )
                continue
            try:
                behaviors.append(self._behavior(latest[0]))
            except (ValidationError, ValueError, TypeError):
                gaps.append(
                    "invalid_behavior_record:"
                    + gap_reference(behavior_id, events.index(candidates[0]))
                )
        return behaviors, gaps

    def _receipts(
        self,
        *,
        reference: str,
        scope,
        read_lead_map: dict[str, str],
        deadline: float | None = None,
    ) -> tuple[dict[str, dict], list[str]]:
        receipts = {}
        gaps = []
        for read_id in sorted(read_lead_map):
            _check_deadline(deadline)
            try:
                receipt = self._access.read_receipt(
                    reference=reference,
                    read_id=read_id,
                )
            except Exception:
                receipts[read_id] = {
                    "valid": False,
                    "error": "read_receipt_unavailable",
                    "lead_id": read_lead_map[read_id],
                }
                gaps.append(f"read_receipt_unavailable:{read_id}")
                continue
            if not self._valid_receipt(receipt, scope=scope):
                receipts[read_id] = {
                    "valid": False,
                    "error": "read_receipt_missing_or_foreign",
                    "lead_id": read_lead_map[read_id],
                }
                gaps.append(f"read_receipt_missing_or_foreign:{read_id}")
                continue
            receipts[read_id] = {
                "valid": True,
                "receipt": receipt,
                "lead_id": receipt["lead_id"],
            }
        return receipts, gaps

    def _retention_links(
        self,
        *,
        reference: str,
        behaviors: list[dict],
        deadline: float | None = None,
    ) -> tuple[dict[str, list[dict]], set[str], list[str]]:
        links: dict[str, list[dict]] = defaultdict(list)
        unavailable_behaviors = set()
        gaps = []
        for behavior in behaviors:
            _check_deadline(deadline)
            behavior_id = behavior["behavior_id"]
            try:
                snapshot = self._retention.status(
                    reference=reference,
                    behavior_id=behavior_id,
                    behavior_revision=behavior["revision"],
                    deadline=deadline,
                )
            except Exception:
                unavailable_behaviors.add(behavior_id)
                gaps.append(f"retention_metadata_unavailable:{behavior_id}")
                continue
            if (
                not isinstance(snapshot, dict)
                or not isinstance(snapshot.get("links", []), list)
            ):
                unavailable_behaviors.add(behavior_id)
                gaps.append(f"retention_metadata_unavailable:{behavior_id}")
                continue
            cited = set(self._read_ids(behavior))
            for link in snapshot.get("links") or []:
                if not isinstance(link, dict):
                    unavailable_behaviors.add(behavior_id)
                    gaps.append(
                        f"retention_metadata_unavailable:{behavior_id}"
                    )
                    continue
                read_id = link.get("read_id")
                if not isinstance(read_id, str) or read_id not in cited:
                    continue
                status = link.get("status")
                if status not in {"retained", "pending", "gap"}:
                    status = "gap"
                links[read_id].append({**link, "status": status})
        return links, unavailable_behaviors, gaps

    @staticmethod
    def _evidence_entry(
        *,
        read_id: str,
        receipt_state: dict,
        links: list[dict],
        retention_unavailable: bool,
    ) -> tuple[dict, list[str], list[str]]:
        receipt = receipt_state.get("receipt")
        limitations = []
        gaps = []
        if not receipt_state["valid"]:
            reason = receipt_state["error"]
            return (
                {
                    "read_id": read_id,
                    "lead_id": receipt_state["lead_id"],
                    "selector": {"type": "unknown", "id": read_id},
                    "content_sha256": None,
                    "range": {"start": 0, "end": 0},
                    "redaction_policy": None,
                    "delivery_status": "missing_or_foreign",
                    "availability": "receipt_missing_or_foreign",
                    "retention_status": "unknown",
                    "artifact_ref": None,
                    "limitations": [reason],
                },
                [reason],
                [f"{reason}:{read_id}"],
            )

        matching_links = []
        for link in links:
            if link.get("sha256") != receipt["content_sha256"]:
                limitations.append("retention_hash_mismatch")
                continue
            matching_links.append(link)
        statuses = [link["status"] for link in matching_links]
        retained_refs = []
        for link in matching_links:
            if link["status"] != "retained":
                continue
            artifact = _artifact_ref(link.get("archive_ref"))
            if artifact is not None:
                retained_refs.append(artifact)
        if len(set(statuses)) > 1:
            limitations.append("retention_status_disagreement")
        if "gap" in statuses:
            availability = "unavailable"
            retention_status = "gap"
        elif "pending" in statuses:
            availability = "pending"
            retention_status = "pending"
        elif "retained" in statuses:
            if retained_refs:
                availability = "retained_unverified"
                retention_status = "retained"
            else:
                availability = "receipt_only"
                retention_status = "missing"
                limitations.append("retained_artifact_ref_missing")
        else:
            availability = "receipt_only"
            retention_status = "missing"
            limitations.append(
                "retention_metadata_unavailable"
                if retention_unavailable
                else "retention_metadata_missing"
            )

        failure_reasons = [
            _safe_gap(str(link.get("failure_reason") or "retention_gap"))
            for link in matching_links
            if link["status"] == "gap"
        ]
        limitations.extend(failure_reasons)
        if availability == "pending":
            limitations.append("retention_pending")
        artifact_ref = retained_refs[0] if retained_refs else None
        if availability == "unavailable":
            gaps.append(f"evidence_unavailable:{read_id}")
        elif availability == "pending":
            gaps.append(f"evidence_pending:{read_id}")
        elif availability == "receipt_only":
            if "retained_artifact_ref_missing" in limitations:
                gaps.append(f"retained_artifact_ref_missing:{read_id}")
            else:
                gaps.append(
                    (
                        "retention_metadata_unavailable"
                        if retention_unavailable
                        else "retention_metadata_missing"
                    )
                    + f":{read_id}"
                )
        if "retention_hash_mismatch" in limitations:
            gaps.append(f"retention_hash_mismatch:{read_id}")
        unique_limitations = list(dict.fromkeys(limitations))
        if len(unique_limitations) > MAX_GAPS:
            omitted = len(unique_limitations) - (MAX_GAPS - 1)
            unique_limitations = unique_limitations[: MAX_GAPS - 1] + [
                f"limitations_truncated:{omitted}"
            ]
        return (
            {
                "read_id": read_id,
                "lead_id": receipt["lead_id"],
                "selector": {
                    "type": receipt["selector_type"],
                    "id": receipt["selector_id"],
                },
                "content_sha256": receipt["content_sha256"],
                "range": {
                    "start": receipt["start_byte"],
                    "end": receipt["end_byte"],
                },
                "redaction_policy": receipt["redaction_policy"],
                "delivery_status": "delivered",
                "availability": availability,
                "retention_status": retention_status,
                "artifact_ref": artifact_ref,
                "limitations": unique_limitations,
            },
            unique_limitations,
            gaps,
        )

    def prepare(
        self,
        *,
        reference: str,
        origin: str | dict[str, object] | None = None,
        analysis_coverage: dict | None = None,
        deadline: float | None = None,
    ) -> dict:
        """Build one validated document without writing the public store."""
        _check_deadline(deadline)
        scope = resolve_js_intake_reference(reference)
        notes = self._notes_factory(scope)
        events = [
            event
            for event in notes.typed_records(event_types={"behavior_save"})
            if (event.get("context_ref") or "") == (scope.context_ref or "")
        ]
        _check_deadline(deadline)
        behaviors, run_gaps = self._latest_behaviors(events, scope=scope)
        read_lead_map = self._read_lead_map(behaviors)
        receipts, receipt_gaps = self._receipts(
            reference=reference,
            scope=scope,
            read_lead_map=read_lead_map,
            deadline=deadline,
        )
        _check_deadline(deadline)
        links, unavailable_behaviors, retention_gaps = self._retention_links(
            reference=reference,
            behaviors=behaviors,
            deadline=deadline,
        )
        analysis = _analysis_coverage(analysis_coverage)
        run_gaps.extend(receipt_gaps)
        run_gaps.extend(retention_gaps)
        run_gaps.extend(analysis["gaps"])

        cited_behaviors: dict[str, set[str]] = defaultdict(set)
        for behavior in behaviors:
            for read_id in self._read_ids(behavior):
                cited_behaviors[read_id].add(behavior["behavior_id"])
        evidence = []
        for read_id in sorted(read_lead_map):
            retention_unavailable = any(
                behavior_id in unavailable_behaviors
                for behavior_id in cited_behaviors[read_id]
            )
            entry, _, evidence_gaps = self._evidence_entry(
                read_id=read_id,
                receipt_state=receipts[read_id],
                links=links.get(read_id) or [],
                retention_unavailable=retention_unavailable,
            )
            evidence.append(entry)
            run_gaps.extend(evidence_gaps)

        if not events:
            run_gaps.append("no_saved_behaviors")
            coverage_status = (
                "empty"
                if analysis["status"] == "complete"
                else "partial"
            )
        elif run_gaps or len(behaviors) != len(
            {
                event.get("behavior_id")
                for event in events
                if isinstance(event.get("behavior_id"), str)
            }
        ):
            coverage_status = "partial"
        else:
            coverage_status = "complete"

        coverage_gaps = sorted(set(run_gaps))
        if len(coverage_gaps) > MAX_COVERAGE_GAPS:
            omitted = len(coverage_gaps) - (MAX_COVERAGE_GAPS - 1)
            coverage_gaps = coverage_gaps[: MAX_COVERAGE_GAPS - 1] + [
                f"coverage_gaps_truncated:{omitted}"
            ]
        document = {
            "schema_version": 1,
            "context": {
                "project_id": scope.project_id,
                "run_id": scope.run_id,
                "origin": normalize_origin(origin),
                "auth_ref": scope.context_ref,
                "coverage": {
                    "status": coverage_status,
                    "gaps": coverage_gaps,
                },
            },
            "behaviors": behaviors,
            "evidence": evidence,
        }
        validated = validate_document(document)
        return {
            "status": "prepared",
            "document": validated,
            "document_id": document_identity(validated),
            "coverage": validated["context"]["coverage"]["status"],
            "behavior_count": len(validated["behaviors"]),
            "evidence_count": len(validated["evidence"]),
            "run_gaps": list(validated["context"]["coverage"]["gaps"]),
        }

    def publish_prepared(self, prepared: dict) -> dict:
        """Validate and publish one already prepared document."""
        if not isinstance(prepared, dict) or prepared.get("status") != "prepared":
            raise JsContextInvalidError("prepared", "must be a prepared document")
        document = validate_document(prepared.get("document"))
        document_id = document_identity(document)
        if prepared.get("document_id") != document_id:
            raise JsContextInvalidError(
                "prepared.document_id",
                "does not match the prepared document",
            )
        result = self._store.publish(document)
        return {
            **result,
            "document_id": document_id,
            "coverage": document["context"]["coverage"]["status"],
            "behavior_count": len(document["behaviors"]),
            "evidence_count": len(document["evidence"]),
            "run_gaps": list(document["context"]["coverage"]["gaps"]),
        }

    def publish(
        self,
        *,
        reference: str,
        origin: str | dict[str, object] | None = None,
        analysis_coverage: dict | None = None,
        deadline: float | None = None,
    ) -> dict:
        """Compatibility composition of ``prepare`` and ``publish_prepared``."""
        return self.publish_prepared(
            self.prepare(
                reference=reference,
                origin=origin,
                analysis_coverage=analysis_coverage,
                deadline=deadline,
            )
        )


__all__ = ["JsContextWriter"]
