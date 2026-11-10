"""Selective JS evidence retention over project blobs and PostgreSQL metadata."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from polymerhus.recon.js_acquisition.code_access import CodeAccessService
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_intake import resolve_js_intake_reference
from polymerhus.recon.js_retention.blobs import BlobError, JsBlobStore
from polymerhus.recon.js_specialist.behavior import _sanitize_text
from polymerhus.recon.js_specialist.notes import RunNotes

RETENTION_INTENT_EVENT = "behavior_retention_intent"
JS_RETENTION_MAX_FILE_BYTES = 8 * 1024 * 1024
RETENTION_RECONCILE_PAYLOAD_BYTES = 3000


class RetentionError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PgRetentionMetadata:
    """Lazy adapter over the shared PostgreSQL client."""

    def reserve(self, **kwargs):
        from polymerhus.app.clients import pg
        return pg.reserve_js_artifact(**kwargs)

    def confirm(self, **kwargs):
        from polymerhus.app.clients import pg
        return pg.confirm_js_artifact(**kwargs)

    def fail(self, **kwargs):
        from polymerhus.app.clients import pg
        return pg.fail_js_artifact(**kwargs)

    def unavailable(self, **kwargs):
        from polymerhus.app.clients import pg
        return pg.mark_js_artifact_unavailable(**kwargs)

    def link(self, **kwargs):
        from polymerhus.app.clients import pg
        return pg.upsert_js_evidence_link(**kwargs)

    def snapshot(self, **kwargs):
        from polymerhus.app.clients import pg
        return pg.js_retention_snapshot(**kwargs)


@dataclass(frozen=True)
class RetentionAssociation:
    origin: str
    read_id: str
    selector_type: str
    selector_id: str
    lead_id: str
    start_byte: int | None
    end_byte: int | None
    rationale: str


@dataclass
class RetentionCandidate:
    sha256: str
    size_bytes: int
    source_name: str
    work_file_ref: str
    local_body: bytes | None
    associations: list[RetentionAssociation] = field(default_factory=list)


def _link_id(
    *,
    project_id: str,
    behavior_id: str,
    revision: int,
    sha256: str,
    association: RetentionAssociation,
) -> str:
    return "jslink_" + hashlib.sha256(json.dumps({
        "project_id": project_id,
        "behavior_id": behavior_id,
        "revision": revision,
        "sha256": sha256,
        "origin": association.origin,
        "read_id": association.read_id,
        "selector_type": association.selector_type,
        "selector_id": association.selector_id,
        "start_byte": association.start_byte,
        "end_byte": association.end_byte,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


def _request_id(
    *,
    project_id: str,
    context_ref: str,
    behavior_id: str,
    revision: int,
    sha256: str,
    associations: list[RetentionAssociation],
) -> str:
    association_identity = [
        {
            "origin": item.origin,
            "read_id": item.read_id,
            "selector_type": item.selector_type,
            "selector_id": item.selector_id,
            "lead_id": item.lead_id,
            "start_byte": item.start_byte,
            "end_byte": item.end_byte,
            "rationale": item.rationale,
        }
        for item in associations
    ]
    return "jsret_" + hashlib.sha256(json.dumps({
        "project_id": project_id,
        "context_ref": context_ref,
        "behavior_id": behavior_id,
        "revision": revision,
        "sha256": sha256,
        "associations": association_identity,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


class JsRetentionService:
    def __init__(
        self,
        *,
        root=None,
        blobs: JsBlobStore | None = None,
        metadata=None,
        access: CodeAccessService | None = None,
        quota_bytes: int | None = None,
    ) -> None:
        self._root = root
        self._blobs = blobs or JsBlobStore(root=root)
        self._metadata = metadata or PgRetentionMetadata()
        self._access = access or CodeAccessService(root=root)
        self._quota_bytes = quota_bytes

    def _quota(self) -> int:
        if self._quota_bytes is not None:
            return self._quota_bytes
        from polymerhus.app import config as config_module
        return config_module.config.JS_RETAINED_BLOB_MAX_BYTES

    @staticmethod
    def _timeout_ms(deadline: float | None) -> int | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RetentionError("retention_reconcile_deadline")
        return max(1, int(remaining * 1000))

    @staticmethod
    def _check_deadline(deadline: float | None) -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise RetentionError("retention_reconcile_deadline")

    def _manifest(self, project_id: str, run_id: str) -> dict:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=64 * 1024 * 1024,
        ).get()

    def _local_body(
        self,
        *,
        project_id: str,
        run_id: str,
        sha256: str,
        size_bytes: int,
        manifest: dict,
    ) -> bytes | None:
        run_dir = (
            AcquisitionManifest(
                project_id=project_id,
                run_id=run_id,
                root=self._root,
                max_run_bytes=64 * 1024 * 1024,
            ).path.parent
        )
        for source in (
            (manifest.get("recovery") or {}).get("sources") or {}
        ).values():
            if (
                source.get("content_sha256") != sha256
                or not source.get("available")
                or not source.get("object_ref")
            ):
                continue
            path = run_dir / str(source["object_ref"])
            if path.is_file():
                body = path.read_bytes()
                if len(body) == size_bytes and hashlib.sha256(body).hexdigest() == sha256:
                    return body
        return None

    def _source_record(
        self,
        manifest: dict,
        *,
        lead_id: str,
        context_ref: str,
        sha256: str,
    ) -> dict:
        for source in (
            (manifest.get("recovery") or {}).get("sources") or {}
        ).values():
            if (
                source.get("content_sha256") == sha256
                and source.get("lead_id") == lead_id
                and (source.get("context_ref") or "") == (context_ref or "")
            ):
                return source
        return {}

    def _candidate_associations(
        self,
        *,
        reference: str,
        behavior: dict,
        dependencies: list[dict] | None,
        deadline: float | None = None,
    ) -> tuple[list[RetentionCandidate], list[dict]]:
        scope = resolve_js_intake_reference(reference)
        manifest = self._manifest(scope.project_id, scope.run_id)
        read_ids = {
            read_id
            for step in behavior.get("steps") or []
            for read_id in step.get("read_ids") or []
        }
        read_ids.update(
            read_id
            for assumption in behavior.get("assumptions") or []
            for read_id in assumption.get("read_ids") or []
        )
        candidates = {}
        gaps = []
        for read_id in sorted(read_ids):
            self._check_deadline(deadline)
            receipt = self._access.read_receipt(
                reference=reference,
                read_id=read_id,
            )
            if (
                not receipt
                or receipt.get("delivery_status") != "delivered"
                or (receipt.get("context_ref") or "") != (scope.context_ref or "")
            ):
                gaps.append({
                    "read_id": read_id,
                    "reason": "read_not_delivered_in_context",
                })
                continue
            sha256 = str(receipt["content_sha256"])
            lead_id = str(receipt.get("lead_id") or "")
            source = self._source_record(
                manifest,
                lead_id=lead_id,
                context_ref=scope.context_ref,
                sha256=sha256,
            )
            size = source.get("size")
            work_ref = str(source.get("work_file_ref") or "")
            source_name = str(source.get("redacted_name") or "")
            if size is None:
                lead = (manifest.get("leads") or {}).get(lead_id) or {}
                size = lead.get("size")
                work_ref = work_ref or str(lead.get("work_file_ref") or "")
                source_name = source_name or "acquired/bundle"
            if not isinstance(size, int) or not work_ref:
                gaps.append({
                    "read_id": read_id,
                    "sha256": sha256,
                    "reason": "complete_file_unavailable",
                })
                continue
            if size > JS_RETENTION_MAX_FILE_BYTES:
                gaps.append({
                    "read_id": read_id,
                    "sha256": sha256,
                    "reason": "complete_file_too_large",
                })
                continue
            association = RetentionAssociation(
                origin="cited_read",
                read_id=read_id,
                selector_type=str(receipt.get("selector_type") or ""),
                selector_id=str(receipt.get("selector_id") or ""),
                lead_id=lead_id,
                start_byte=int(receipt.get("start_byte") or 0),
                end_byte=int(receipt.get("end_byte") or 0),
                rationale="delivered read cited by behaviour record",
            )
            existing = candidates.get(sha256)
            if existing is None:
                existing = RetentionCandidate(
                    sha256=sha256,
                    size_bytes=size,
                    source_name=source_name,
                    work_file_ref=work_ref,
                    local_body=self._local_body(
                        project_id=scope.project_id,
                        run_id=scope.run_id,
                        sha256=sha256,
                        size_bytes=size,
                        manifest=manifest,
                    ),
                )
                candidates[sha256] = existing
            existing.associations.append(association)

        for dependency in dependencies or []:
            self._check_deadline(deadline)
            if not isinstance(dependency, dict):
                gaps.append({"reason": "invalid_dependency_nomination"})
                continue
            rationale = _sanitize_text(
                str(dependency.get("rationale") or "").strip()
            )[0]
            selector_type = str(dependency.get("selector_type") or "")
            selector_id = str(dependency.get("target") or "")
            if (
                selector_type not in {"item", "source", "match"}
                or not selector_id
                or not rationale
            ):
                gaps.append({
                    "dependency_id": selector_id,
                    "reason": "dependency_requires_authorized_reference_and_rationale",
                })
                continue
            try:
                target = self._access.read_target(
                    reference=reference,
                    selector={
                        "type": selector_type,
                        "id": selector_id,
                    },
                )
            except Exception:
                gaps.append({
                    "dependency_id": selector_id,
                    "reason": "dependency_reference_not_authorized",
                })
                continue
            sha256 = str(target["content_sha256"])
            size = int(target["size"])
            candidate = candidates.get(sha256)
            if candidate is None:
                candidate = RetentionCandidate(
                    sha256=sha256,
                    size_bytes=size,
                    source_name=str(target.get("kind") or ""),
                    work_file_ref=str(target.get("work_file_ref") or ""),
                    local_body=self._local_body(
                        project_id=scope.project_id,
                        run_id=scope.run_id,
                        sha256=sha256,
                        size_bytes=size,
                        manifest=manifest,
                    ),
                )
                candidates[sha256] = candidate
            candidate.associations.append(RetentionAssociation(
                origin="dependency",
                read_id="",
                selector_type=selector_type,
                selector_id=selector_id,
                lead_id=str(target.get("lead_id") or ""),
                start_byte=int(target.get("range_start") or 0),
                end_byte=int(target.get("range_end") or 0),
                rationale=rationale,
            ))
        return list(candidates.values()), gaps

    def _append_intent(
        self,
        *,
        notes: RunNotes,
        scope,
        behavior: dict,
        candidate: RetentionCandidate,
        request_id: str,
    ) -> dict:
        associations = [
            {
                "origin": item.origin,
                "read_id": item.read_id,
                "selector_type": item.selector_type,
                "selector_id": item.selector_id,
                "lead_id": item.lead_id,
                "start_byte": item.start_byte,
                "end_byte": item.end_byte,
                "rationale": item.rationale,
            }
            for item in candidate.associations
        ]

        def build(records):
            for record in records:
                if (
                    record.get("event_type") == RETENTION_INTENT_EVENT
                    and record.get("request_id") == request_id
                    and (record.get("context_ref") or "") == (scope.context_ref or "")
                ):
                    return {
                        "existing_record": record,
                        "idempotent": True,
                    }
            return {
                "record": {
                    "event_type": RETENTION_INTENT_EVENT,
                    "schema_version": 1,
                    "request_id": request_id,
                    "project_id": scope.project_id,
                    "run_id": scope.run_id,
                    "context_ref": scope.context_ref,
                    "behavior_id": behavior["behavior_id"],
                    "behavior_revision": int(behavior["revision"]),
                    "sha256": candidate.sha256,
                    "size_bytes": candidate.size_bytes,
                    "work_file_ref": candidate.work_file_ref,
                    "source_name": candidate.source_name,
                    "associations": associations,
                }
            }

        result = notes.append_typed_transaction(
            build,
            allow_sanitized_text=True,
        )
        if result.get("error"):
            raise RetentionError(result["error"])
        return result.get("record") or result.get("existing_record")

    def _link_records(
        self,
        *,
        scope,
        behavior: dict,
        candidate: RetentionCandidate,
        status: str,
        failure_reason: str | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        for association in candidate.associations:
            self._metadata.link(link={
                "link_id": _link_id(
                    project_id=scope.project_id,
                    behavior_id=behavior["behavior_id"],
                    revision=int(behavior["revision"]),
                    sha256=candidate.sha256,
                    association=association,
                ),
                "project_id": scope.project_id,
                "sha256": candidate.sha256,
                "run_id": scope.run_id,
                "origin": association.origin,
                "auth_context_ref": scope.context_ref,
                "lead_id": association.lead_id,
                "selector_type": association.selector_type,
                "selector_id": association.selector_id,
                "read_id": association.read_id,
                "start_byte": association.start_byte,
                "end_byte": association.end_byte,
                "behavior_id": behavior["behavior_id"],
                "behavior_revision": int(behavior["revision"]),
                "rationale": association.rationale,
                "status": status,
                "failure_reason": failure_reason,
            }, timeout_ms=timeout_ms)

    def retain_after_save(
        self,
        *,
        reference: str,
        behavior: dict,
        dependencies: list[dict] | None = None,
        deadline: float | None = None,
    ) -> dict:
        timeout_ms = self._timeout_ms(deadline)
        scope = resolve_js_intake_reference(reference)
        candidates, gaps = self._candidate_associations(
            reference=reference,
            behavior=behavior,
            dependencies=dependencies,
            deadline=deadline,
        )
        notes = RunNotes(scope, root=self._root)
        transfer_requests = []
        retained = 0
        pending = 0
        uncertain = 0
        for candidate in candidates:
            timeout_ms = self._timeout_ms(deadline)
            self._check_deadline(deadline)
            request_id = _request_id(
                project_id=scope.project_id,
                context_ref=scope.context_ref,
                behavior_id=behavior["behavior_id"],
                revision=int(behavior["revision"]),
                sha256=candidate.sha256,
                associations=candidate.associations,
            )
            try:
                self._append_intent(
                    notes=notes,
                    scope=scope,
                    behavior=behavior,
                    candidate=candidate,
                    request_id=request_id,
                )
            except Exception as exc:
                gaps.append({
                    "sha256": candidate.sha256,
                    "reason": getattr(exc, "reason", "retention_intent_failed"),
                })
                continue
            archive_ref = self._blobs.archive_ref(candidate.sha256)
            timeout_ms = self._timeout_ms(deadline)
            try:
                reservation = self._metadata.reserve(
                    project_id=scope.project_id,
                    sha256=candidate.sha256,
                    size_bytes=candidate.size_bytes,
                    archive_ref=archive_ref,
                    quota_bytes=self._quota(),
                    timeout_ms=timeout_ms,
                )
            except Exception:
                gaps.append({
                    "sha256": candidate.sha256,
                    "reason": "retention_reservation_uncertain",
                })
                pending += 1
                uncertain += 1
                continue
            if reservation["status"] == "quota_exceeded":
                timeout_ms = self._timeout_ms(deadline)
                self._metadata.fail(
                    project_id=scope.project_id,
                    sha256=candidate.sha256,
                    size_bytes=candidate.size_bytes,
                    archive_ref=archive_ref,
                    reason="retention_quota_exceeded",
                    timeout_ms=timeout_ms,
                )
                self._link_records(
                    scope=scope,
                    behavior=behavior,
                    candidate=candidate,
                    status="gap",
                    failure_reason="retention_quota_exceeded",
                    timeout_ms=timeout_ms,
                )
                gaps.append({
                    "sha256": candidate.sha256,
                    "reason": "retention_quota_exceeded",
                })
                continue
            if reservation["status"] == "version_conflict":
                timeout_ms = self._timeout_ms(deadline)
                self._link_records(
                    scope=scope,
                    behavior=behavior,
                    candidate=candidate,
                    status="gap",
                    failure_reason="retained_version_conflict",
                    timeout_ms=timeout_ms,
                )
                gaps.append({
                    "sha256": candidate.sha256,
                    "reason": "retained_version_conflict",
                })
                continue
            if reservation["status"] == "already_retained":
                timeout_ms = self._timeout_ms(deadline)
                if self._blobs.verify(
                    project_id=scope.project_id,
                    sha256=candidate.sha256,
                    expected_size=candidate.size_bytes,
                ):
                    timeout_ms = self._timeout_ms(deadline)
                    self._link_records(
                        scope=scope,
                        behavior=behavior,
                        candidate=candidate,
                        status="retained",
                        timeout_ms=timeout_ms,
                    )
                    retained += 1
                else:
                    self._metadata.unavailable(
                        project_id=scope.project_id,
                        sha256=candidate.sha256,
                        reason="retained_blob_missing_or_corrupt",
                        timeout_ms=timeout_ms,
                    )
                    self._link_records(
                        scope=scope,
                        behavior=behavior,
                        candidate=candidate,
                        status="gap",
                        failure_reason="retained_blob_missing_or_corrupt",
                        timeout_ms=timeout_ms,
                    )
                    gaps.append({
                        "sha256": candidate.sha256,
                        "reason": "retained_blob_missing_or_corrupt",
                    })
                continue
            if reservation["status"] in {"reserved", "already_reserved"}:
                timeout_ms = self._timeout_ms(deadline)
                if self._blobs.verify(
                    project_id=scope.project_id,
                    sha256=candidate.sha256,
                    expected_size=candidate.size_bytes,
                ):
                    try:
                        timeout_ms = self._timeout_ms(deadline)
                        confirmed = self._metadata.confirm(
                            project_id=scope.project_id,
                            sha256=candidate.sha256,
                            size_bytes=candidate.size_bytes,
                            timeout_ms=timeout_ms,
                        )
                        if confirmed["state"] != "retained":
                            raise RetentionError(
                                "retention_confirmation_failed"
                            )
                        self._link_records(
                            scope=scope,
                            behavior=behavior,
                            candidate=candidate,
                            status="retained",
                            timeout_ms=timeout_ms,
                        )
                        retained += 1
                    except Exception:
                        gaps.append({
                            "sha256": candidate.sha256,
                            "reason": "retention_confirmation_uncertain",
                        })
                        pending += 1
                        uncertain += 1
                    continue
            if candidate.local_body is not None:
                timeout_ms = self._timeout_ms(deadline)
                try:
                    self._blobs.write(
                        project_id=scope.project_id,
                        sha256=candidate.sha256,
                        expected_size=candidate.size_bytes,
                        body=candidate.local_body,
                    )
                    timeout_ms = self._timeout_ms(deadline)
                    confirmed = self._metadata.confirm(
                        project_id=scope.project_id,
                        sha256=candidate.sha256,
                        size_bytes=candidate.size_bytes,
                        timeout_ms=timeout_ms,
                    )
                    if confirmed["state"] != "retained":
                        raise RetentionError("retention_confirmation_failed")
                    self._link_records(
                        scope=scope,
                        behavior=behavior,
                        candidate=candidate,
                        status="retained",
                        timeout_ms=timeout_ms,
                    )
                    retained += 1
                except (BlobError, RetentionError, OSError) as exc:
                    reason = getattr(exc, "reason", "retention_copy_failed")
                    try:
                        timeout_ms = self._timeout_ms(deadline)
                    except RetentionError:
                        gaps.append({
                            "sha256": candidate.sha256,
                            "reason": reason,
                        })
                        pending += 1
                        uncertain += 1
                        continue
                    self._metadata.fail(
                        project_id=scope.project_id,
                        sha256=candidate.sha256,
                        size_bytes=candidate.size_bytes,
                        archive_ref=archive_ref,
                        reason=reason,
                        timeout_ms=timeout_ms,
                    )
                    self._link_records(
                        scope=scope,
                        behavior=behavior,
                        candidate=candidate,
                        status="gap",
                        failure_reason=reason,
                        timeout_ms=timeout_ms,
                    )
                    gaps.append({
                        "sha256": candidate.sha256,
                        "reason": reason,
                    })
                except Exception:
                    gaps.append({
                        "sha256": candidate.sha256,
                        "reason": "retention_confirmation_uncertain",
                    })
                    pending += 1
                    uncertain += 1
                continue
            self._link_records(
                scope=scope,
                behavior=behavior,
                candidate=candidate,
                status="pending",
                timeout_ms=timeout_ms,
            )
            pending += 1
            transfer_requests.append({
                "request_id": request_id,
                "sha256": candidate.sha256,
                "size_bytes": candidate.size_bytes,
                "work_file_ref": candidate.work_file_ref,
            })
        return {
            "status": (
                "complete"
                if candidates and not gaps and not transfer_requests
                else "pending"
                if transfer_requests or uncertain
                else "partial"
                if retained
                else "gap"
            ),
            "retained_count": retained,
            "pending_count": pending,
            "gap_count": len(gaps),
            "gaps": gaps,
            "transfer_requests": transfer_requests,
        }

    def accept_transfer(
        self,
        *,
        reference: str,
        request_id: str,
        body: bytes,
        deadline: float | None = None,
    ) -> dict:
        timeout_ms = self._timeout_ms(deadline)
        scope = resolve_js_intake_reference(reference)
        notes = RunNotes(scope, root=self._root)
        intent = next(
            (
                record
                for record in notes.typed_records(
                    event_types={RETENTION_INTENT_EVENT}
                )
                if record.get("request_id") == request_id
            ),
            None,
        )
        if not intent:
            raise RetentionError("retention_request_not_found")
        sha256 = str(intent["sha256"])
        size = int(intent["size_bytes"])
        if len(body) != size or hashlib.sha256(body).hexdigest() != sha256:
            self._metadata.fail(
                project_id=scope.project_id,
                sha256=sha256,
                size_bytes=size,
                archive_ref=self._blobs.archive_ref(sha256),
                reason="transfer_hash_mismatch",
                timeout_ms=timeout_ms,
            )
            raise RetentionError("transfer_hash_mismatch")
        reservation = self._metadata.reserve(
            project_id=scope.project_id,
            sha256=sha256,
            size_bytes=size,
            archive_ref=self._blobs.archive_ref(sha256),
            quota_bytes=self._quota(),
            timeout_ms=timeout_ms,
        )
        if reservation["status"] not in {
            "reserved",
            "already_reserved",
            "already_retained",
        }:
            raise RetentionError(str(reservation["status"]))
        if not self._blobs.verify(
            project_id=scope.project_id,
            sha256=sha256,
            expected_size=size,
        ):
            try:
                self._blobs.write(
                    project_id=scope.project_id,
                    sha256=sha256,
                    expected_size=size,
                    body=body,
                )
            except BlobError as exc:
                self._metadata.fail(
                    project_id=scope.project_id,
                    sha256=sha256,
                    size_bytes=size,
                    archive_ref=self._blobs.archive_ref(sha256),
                    reason=exc.reason,
                    timeout_ms=timeout_ms,
                )
                raise
        confirmed = self._metadata.confirm(
            project_id=scope.project_id,
            sha256=sha256,
            size_bytes=size,
            timeout_ms=timeout_ms,
        )
        if confirmed["state"] != "retained":
            raise RetentionError("retention_confirmation_failed")
        behavior = {
            "behavior_id": intent["behavior_id"],
            "revision": intent["behavior_revision"],
        }
        associations = intent.get("associations") or []
        for item in associations:
            timeout_ms = self._timeout_ms(deadline)
            association = RetentionAssociation(**item)
            self._metadata.link(link={
                "link_id": _link_id(
                    project_id=scope.project_id,
                    behavior_id=behavior["behavior_id"],
                    revision=int(behavior["revision"]),
                    sha256=sha256,
                    association=association,
                ),
                "project_id": scope.project_id,
                "sha256": sha256,
                "run_id": scope.run_id,
                "origin": association.origin,
                "auth_context_ref": scope.context_ref,
                "lead_id": association.lead_id,
                "selector_type": association.selector_type,
                "selector_id": association.selector_id,
                "read_id": association.read_id,
                "start_byte": association.start_byte,
                "end_byte": association.end_byte,
                "behavior_id": behavior["behavior_id"],
                "behavior_revision": int(behavior["revision"]),
                "rationale": association.rationale,
                "status": "retained",
                "failure_reason": None,
            }, timeout_ms=timeout_ms)
        return self.status(
            reference=reference,
            behavior_id=behavior["behavior_id"],
            behavior_revision=int(behavior["revision"]),
            deadline=deadline,
        )

    def status(
        self,
        *,
        reference: str,
        behavior_id: str,
        behavior_revision: int,
        deadline: float | None = None,
    ) -> dict:
        scope = resolve_js_intake_reference(reference)
        return self._metadata.snapshot(
            project_id=scope.project_id,
            run_id=scope.run_id,
            auth_context_ref=scope.context_ref,
            behavior_id=behavior_id,
            behavior_revision=behavior_revision,
            timeout_ms=self._timeout_ms(deadline),
        )

    @staticmethod
    def _behavior_submission(record: dict) -> dict:
        return {
            "question_ref": record["question_ref"],
            "steps": [
                {
                    "kind": step["kind"],
                    "text": step["text"],
                    "read_ids": list(step.get("read_ids") or []),
                }
                for step in record.get("steps") or []
            ],
            "assumptions": [
                {
                    "text": assumption["text"],
                    "status": assumption["status"],
                    "read_ids": list(
                        assumption.get("read_ids") or []
                    ),
                }
                for assumption in record.get("assumptions") or []
            ],
            "gaps": list(record.get("gaps") or []),
        }

    @staticmethod
    def _behavior_read_ids(record: dict) -> set[str]:
        read_ids = {
            read_id
            for step in record.get("steps") or []
            for read_id in step.get("read_ids") or []
        }
        read_ids.update(
            read_id
            for assumption in record.get("assumptions") or []
            for read_id in assumption.get("read_ids") or []
        )
        return read_ids

    @staticmethod
    def _persisted_dependencies(
        intents: list[dict],
        *,
        behavior_id: str,
        revision: int,
    ) -> list[dict]:
        dependencies = []
        seen = set()
        for intent in intents:
            if (
                intent.get("behavior_id") != behavior_id
                or int(intent.get("behavior_revision") or 0) != revision
            ):
                continue
            for association in intent.get("associations") or []:
                if association.get("origin") != "dependency":
                    continue
                dependency = {
                    "selector_type": str(
                        association.get("selector_type") or ""
                    ),
                    "target": str(
                        association.get("selector_id") or ""
                    ),
                    "rationale": str(
                        association.get("rationale") or ""
                    ),
                }
                identity = json.dumps(
                    dependency,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if identity in seen:
                    continue
                seen.add(identity)
                dependencies.append(dependency)
        return dependencies

    @staticmethod
    def _dependency_batches(
        record: dict,
        dependencies: list[dict],
    ) -> list[list[dict]]:
        if not dependencies:
            return [[]]
        record_size = len(json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"))
        batches = []
        current = []
        current_size = record_size
        for dependency in dependencies:
            size = len(json.dumps(
                dependency,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"))
            if (
                current
                and current_size + size
                > RETENTION_RECONCILE_PAYLOAD_BYTES
            ):
                batches.append(current)
                current = []
                current_size = record_size
            current.append(dependency)
            current_size += size
        if current:
            batches.append(current)
        return batches

    def reconcile_run(
        self,
        *,
        reference: str,
        deadline: float,
        max_items: int,
        retry_fn=None,
    ) -> dict:
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or max_items <= 0
        ):
            raise RetentionError("invalid_reconcile_item_limit")
        scope = resolve_js_intake_reference(reference)
        started = time.monotonic()
        base = {
            "project_id": scope.project_id,
            "run_id": scope.run_id,
            "auth_context_ref": scope.context_ref,
            "behaviors_seen": 0,
            "retry_attempts": 0,
            "maintenance_execs": 0,
            "recovered_behaviors": 0,
            "pending_behaviors": 0,
            "skipped_complete": 0,
            "gaps": [],
        }
        if deadline <= started:
            return {
                **base,
                "status": "partial",
                "gaps": ["retention_reconcile_deadline"],
                "elapsed_ms": 0,
            }
        notes = RunNotes(scope, root=self._root)
        behavior_events = notes.typed_records(
            event_types={"behavior_save"}
        )
        if not behavior_events:
            return {
                **base,
                "status": "no_work",
                "elapsed_ms": int(
                    (time.monotonic() - started) * 1000
                ),
            }
        latest = {}
        for event in behavior_events:
            behavior_id = str(event.get("behavior_id") or "")
            if not behavior_id:
                continue
            prior = latest.get(behavior_id)
            if (
                prior is None
                or int(event.get("revision") or 0)
                > int(prior.get("revision") or 0)
            ):
                latest[behavior_id] = event
        intents = notes.typed_records(
            event_types={RETENTION_INTENT_EVENT}
        )
        base["behaviors_seen"] = len(latest)
        gaps = []
        retries = 0
        recovered = 0
        pending = 0
        skipped = 0

        for behavior_id, event in sorted(latest.items()):
            if time.monotonic() >= deadline:
                gaps.append("retention_reconcile_deadline")
                break
            revision = int(event.get("revision") or 0)
            try:
                status = self.status(
                    reference=reference,
                    behavior_id=behavior_id,
                    behavior_revision=revision,
                    deadline=deadline,
                )
            except Exception:
                gaps.append("retention_database_unavailable")
                break
            dependencies = self._persisted_dependencies(
                intents,
                behavior_id=behavior_id,
                revision=revision,
            )
            corrupt_hashes = []
            for link in status.get("links") or []:
                if link.get("status") != "retained":
                    continue
                if self._blobs.verify(
                    project_id=scope.project_id,
                    sha256=str(link.get("sha256") or ""),
                    expected_size=int(link.get("size_bytes") or 0),
                ):
                    continue
                corrupt_hashes.append(str(link.get("sha256") or ""))
            for sha256 in dict.fromkeys(corrupt_hashes):
                try:
                    self._metadata.unavailable(
                        project_id=scope.project_id,
                        sha256=sha256,
                        reason="retained_blob_missing_or_corrupt",
                    )
                except Exception:
                    gaps.append("retention_database_unavailable")
                    break
                gaps.append("retained_blob_missing_or_corrupt")
            if "retention_database_unavailable" in gaps:
                break
            expected_links = (
                len(self._behavior_read_ids(event))
                + len({
                    (
                        item.get("selector_type"),
                        item.get("target"),
                    )
                    for item in dependencies
                })
            )
            if (
                not corrupt_hashes
                and expected_links
                and int(status.get("retained_count") or 0)
                >= expected_links
                and not status.get("pending_count")
                and not status.get("gap_count")
            ):
                skipped += 1
                continue
            record = self._behavior_submission(event)
            batches = self._dependency_batches(record, dependencies)
            for batch in batches:
                if retries >= max_items:
                    gaps.append("retention_reconcile_item_limit")
                    break
                if time.monotonic() >= deadline:
                    gaps.append("retention_reconcile_deadline")
                    break
                retries += 1
                retry_error = None
                if retry_fn is None:
                    try:
                        self.retain_after_save(
                            reference=reference,
                            behavior=record,
                            dependencies=batch,
                            deadline=deadline,
                        )
                    except Exception:
                        retry_error = "retention_reconcile_retry_uncertain"
                else:
                    try:
                        retry_fn(
                            behavior_id=behavior_id,
                            revision=revision,
                            behavior=record,
                            dependencies=batch,
                            deadline=deadline,
                        )
                    except Exception:
                        retry_error = "retention_reconcile_retry_uncertain"
                if time.monotonic() >= deadline:
                    gaps.append("retention_reconcile_deadline")
                    break
                try:
                    status = self.status(
                        reference=reference,
                        behavior_id=behavior_id,
                        behavior_revision=revision,
                        deadline=deadline,
                    )
                except Exception:
                    gaps.append("retention_database_unavailable")
                    break
                if (
                    int(status.get("retained_count") or 0)
                    >= expected_links
                    and not status.get("pending_count")
                    and not status.get("gap_count")
                ):
                    recovered += 1
                    break
                if retry_error:
                    gaps.append(retry_error)
                if status.get("pending_count"):
                    pending += 1
                    break
                batch_gaps = [
                    str(link.get("failure_reason") or "retention_gap")
                    for link in status.get("links") or []
                    if link.get("status") == "gap"
                ]
                gaps.extend(batch_gaps)
                if retry_error or batch_gaps:
                    break
                continue
            if (
                "retention_reconcile_item_limit" in gaps
                or "retention_reconcile_deadline" in gaps
            ):
                break

        gaps = list(dict.fromkeys(gaps))
        status_name = (
            "complete"
            if not gaps and pending == 0 and recovered + skipped == len(latest)
            else "partial"
            if "retention_reconcile_deadline" in gaps
            or "retention_reconcile_item_limit" in gaps
            else "pending"
            if pending
            else "gap"
        )
        return {
            **base,
            "status": status_name,
            "retry_attempts": retries,
            "maintenance_execs": retries if retry_fn is not None else 0,
            "recovered_behaviors": recovered,
            "pending_behaviors": pending,
            "skipped_complete": skipped,
            "gaps": gaps,
            "elapsed_ms": int(
                (time.monotonic() - started) * 1000
            ),
        }


__all__ = [
    "JsRetentionService",
    "PgRetentionMetadata",
    "RetentionError",
    "RetentionAssociation",
    "RetentionCandidate",
    "JS_RETENTION_MAX_FILE_BYTES",
]
