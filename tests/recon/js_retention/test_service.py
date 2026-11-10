import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.code_access import CodeAccessService
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
    resolve_js_intake_reference,
)
from polymerhus.recon.js_retention.blobs import JsBlobStore
from polymerhus.recon.js_retention.service import (
    JsRetentionService,
    RetentionError,
)
from polymerhus.recon.js_specialist.notes import RunNotes


class FakeMetadata:
    def __init__(self, *, quota_bytes=32 * 1024 * 1024):
        self.quota_bytes = quota_bytes
        self.artifacts = {}
        self.links = {}
        self.reserve_error = False
        self.snapshot_error = False
        self.confirm_failures = 0
        self.timeouts = []
        self.operation_timeouts = []
        self._lock = threading.RLock()

    def reserve(
        self,
        *,
        project_id,
        sha256,
        size_bytes,
        archive_ref,
        quota_bytes,
        timeout_ms=None,
    ):
        self.operation_timeouts.append(("reserve", timeout_ms))
        if self.reserve_error:
            raise RuntimeError("pg unavailable")
        with self._lock:
            key = (project_id, sha256)
            row = self.artifacts.get(key)
            if row:
                if row["size_bytes"] != size_bytes:
                    return {"status": "version_conflict", "state": row["state"]}
                if row["state"] == "retained":
                    return {
                        "status": "already_retained",
                        "state": "retained",
                        "size_bytes": size_bytes,
                    }
                if row["state"] == "reserved":
                    return {
                        "status": "already_reserved",
                        "state": "reserved",
                        "size_bytes": size_bytes,
                    }
            used = sum(
                item["size_bytes"]
                for (candidate_project, _), item in self.artifacts.items()
                if candidate_project == project_id
                and item["state"] in {"reserved", "retained"}
            )
            if used + size_bytes > quota_bytes:
                return {
                    "status": "quota_exceeded",
                    "state": "gap",
                    "used_bytes": used,
                }
            self.artifacts[key] = {
                "sha256": sha256,
                "size_bytes": size_bytes,
                "archive_ref": archive_ref,
                "state": "reserved",
                "failure_reason": None,
            }
            return {"status": "reserved", "state": "reserved"}

    def confirm(
        self,
        *,
        project_id,
        sha256,
        size_bytes,
        timeout_ms=None,
    ):
        self.operation_timeouts.append(("confirm", timeout_ms))
        with self._lock:
            key = (project_id, sha256)
            row = self.artifacts.get(key)
            if not row or row["size_bytes"] != size_bytes:
                return {"status": "version_conflict", "state": None}
            if self.confirm_failures:
                self.confirm_failures -= 1
                raise RuntimeError("confirmation response lost")
            if row["state"] == "retained":
                return {"status": "already_retained", "state": "retained"}
            if row["state"] != "reserved":
                return {
                    "status": "reservation_not_active",
                    "state": row["state"],
                }
            row["state"] = "retained"
            row["failure_reason"] = None
            return {"status": "retained", "state": "retained"}

    def fail(
        self,
        *,
        project_id,
        sha256,
        size_bytes,
        archive_ref,
        reason,
        timeout_ms=None,
    ):
        self.operation_timeouts.append(("fail", timeout_ms))
        with self._lock:
            key = (project_id, sha256)
            row = self.artifacts.get(key)
            if row and row["state"] == "retained":
                return {"status": "already_retained", "state": "retained"}
            self.artifacts[key] = {
                "sha256": sha256,
                "size_bytes": size_bytes,
                "archive_ref": archive_ref,
                "state": "gap",
                "failure_reason": reason,
            }
            return {"status": "gap", "state": "gap"}

    def unavailable(
        self,
        *,
        project_id,
        sha256,
        reason,
        timeout_ms=None,
    ):
        self.operation_timeouts.append(("unavailable", timeout_ms))
        with self._lock:
            row = self.artifacts[(project_id, sha256)]
            row["state"] = "gap"
            row["failure_reason"] = reason
            return {"status": "gap", "state": "gap"}

    def link(self, *, link, timeout_ms=None):
        self.operation_timeouts.append(("link", timeout_ms))
        with self._lock:
            prior = self.links.get(link["link_id"])
            value = dict(link)
            if prior and prior["status"] == "retained":
                value["status"] = "retained"
                value["failure_reason"] = None
            self.links[link["link_id"]] = value
            return {"status": value["status"]}

    def snapshot(
        self,
        *,
        project_id,
        run_id,
        auth_context_ref,
        behavior_id,
        behavior_revision,
        timeout_ms=None,
    ):
        self.timeouts.append(timeout_ms)
        if self.snapshot_error:
            raise RuntimeError("snapshot unavailable")
        with self._lock:
            links = []
            for link in self.links.values():
                if (
                    link["project_id"] != project_id
                    or link["run_id"] != run_id
                    or link["auth_context_ref"] != auth_context_ref
                    or link["behavior_id"] != behavior_id
                    or int(link["behavior_revision"]) != behavior_revision
                ):
                    continue
                artifact = self.artifacts[
                    (project_id, link["sha256"])
                ]
                status = (
                    link["status"]
                    if artifact["state"] == "retained"
                    else "gap"
                    if artifact["state"] == "gap"
                    else "pending"
                )
                links.append({
                    **link,
                    "status": status,
                    "size_bytes": artifact["size_bytes"],
                    "archive_ref": artifact["archive_ref"],
                    "artifact_state": artifact["state"],
                    "artifact_failure_reason": artifact["failure_reason"],
                })
            return {
                "links": links,
                "retained_count": sum(
                    link["status"] == "retained" for link in links
                ),
                "pending_count": sum(
                    link["status"] == "pending" for link in links
                ),
                "gap_count": sum(link["status"] == "gap" for link in links),
            }


def _context(
    tmp_path,
    *,
    context_ref,
    source_id,
    body,
    run_id="r",
):
    ensure_project("p", root=tmp_path)
    JsIntakeStore(root=tmp_path).record_exec_result(
        project_id="p",
        run_id=run_id,
        pod_id=f"pod-{context_ref}-{source_id}",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps({
                "request": {
                    "endpoint": (
                        f"https://app.test/{context_ref}/{source_id}.js"
                    )
                },
                "response": {"status_code": 200},
            }),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref=context_ref,
    )
    reference = issue_js_intake_reference(
        "p",
        run_id,
        context_ref=context_ref,
    )
    lead_id = JsIntakeReader(root=tmp_path).list(
        reference=reference,
        limit=10,
    )["leads"][-1]["lead_id"]
    parent = f"parent:{context_ref}:{source_id}".encode()
    digest = hashlib.sha256(parent).hexdigest()
    work_ref = f"/work/js-analysis/{run_id}/{digest}.js"
    manifest = AcquisitionManifest(
        project_id="p",
        run_id=run_id,
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    )
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": context_ref},
        work_file_ref=work_ref,
        sha256=digest,
        size=len(parent),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(parent),
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    content_sha = hashlib.sha256(body).hexdigest()
    object_ref = f"recovered/{source_id}-{content_sha}.js"
    local_file = manifest.path.parent / object_ref
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_bytes(body)
    manifest.update(
        lambda value: value.setdefault("recovery", {})
        .setdefault("sources", {})
        .update({
            source_id: {
                "source_id": source_id,
                "lead_id": lead_id,
                "context_ref": context_ref,
                "kind": "typescript",
                "content_state": "text",
                "content_sha256": content_sha,
                "size": len(body),
                "work_file_ref": (
                    f"/work/js-analysis/{run_id}/{object_ref}"
                ),
                "object_ref": object_ref,
                "status": "available",
                "available": True,
            }
        })
    )
    access = CodeAccessService(root=tmp_path)
    target = access.read_target(
        reference=reference,
        selector={"type": "source", "id": source_id},
    )
    read = access.prepare_read(
        reference=reference,
        selector={"type": "source", "id": source_id},
        source_bytes=body,
        window_bytes=128,
    )
    assert read["content_sha256"] == content_sha
    assert access.confirm_read(
        reference=reference,
        read_id=read["read_id"],
    )["delivery_status"] == "delivered"
    return {
        "reference": reference,
        "lead_id": lead_id,
        "source_id": source_id,
        "body": body,
        "sha256": content_sha,
        "read_id": read["read_id"],
        "target": target,
        "local_file": local_file,
        "access": access,
    }


def _behavior(read_id, behavior_id="behavior_a"):
    return {
        "behavior_id": behavior_id,
        "revision": 1,
        "steps": [{"read_ids": [read_id]}],
        "assumptions": [],
    }


def _append_behavior_note(fixture, *, behavior_id="behavior_a"):
    scope = resolve_js_intake_reference(fixture["reference"])
    record = RunNotes(scope, root=fixture["root"]).append_typed(
        {
            "event_type": "behavior_save",
            "schema_version": 1,
            "behavior_id": behavior_id,
            "revision": 1,
            "reconstruction_level": "reconstructed",
            "question_ref": "span_a",
            "question": "Which retained file supports this fixture path?",
            "priority": "normal",
            "lead_id": fixture["lead_id"],
            "record_sha256": "a" * 64,
            "redaction_policy": "js-source-redaction-v1",
            "redaction_count": 0,
            "steps": [{
                "kind": "input",
                "text": "The retained complete file supports this input.",
                "read_ids": [fixture["read_id"]],
            }],
            "assumptions": [],
            "gaps": [],
        },
        allow_sanitized_text=True,
    )
    assert record["behavior_id"] == behavior_id
    return record


def _service(tmp_path, fixture, metadata, *, quota_bytes=1024 * 1024):
    return JsRetentionService(
        root=tmp_path,
        blobs=JsBlobStore(root=tmp_path),
        metadata=metadata,
        access=fixture["access"],
        quota_bytes=quota_bytes,
    )


def _direct_retry(service, reference, attempts):
    def retry(
        *,
        behavior_id,
        revision,
        behavior,
        dependencies,
        deadline,
    ):
        attempts.append({
            "behavior_id": behavior_id,
            "revision": revision,
            "dependencies": dependencies,
        })
        return {
            "returncode": 0,
            "result": service.retain_after_save(
                reference=reference,
                behavior={
                    **behavior,
                    "behavior_id": behavior_id,
                    "revision": revision,
                },
                dependencies=dependencies,
            ),
        }

    return retry


def test_reconcile_run_resumes_saved_behavior_without_sql_metadata(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const resumed = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)
    attempts = []

    def retry(
        *,
        behavior_id,
        revision,
        behavior,
        dependencies,
        deadline,
    ):
        attempts.append((behavior_id, dependencies))
        return {
            "returncode": 0,
            "result": service.retain_after_save(
                reference=fixture["reference"],
                behavior={
                    **behavior,
                    "behavior_id": behavior_id,
                    "revision": revision,
                },
                dependencies=dependencies,
            ),
        }

    result = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=retry,
    )

    assert result["status"] == "complete"
    assert result["retry_attempts"] == 1
    assert attempts == [("behavior_a", [])]
    assert len(metadata.artifacts) == 1
    assert len(metadata.links) == 1
    assert next(iter(metadata.links.values()))["status"] == "retained"


def test_reconcile_run_recovers_persisted_intent_before_sql(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const intent_resume = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    metadata.reserve_error = True
    service = _service(tmp_path, fixture, metadata)
    first = service.retain_after_save(
        reference=fixture["reference"],
        behavior=_behavior(fixture["read_id"]),
    )
    assert first["status"] == "pending"
    assert not metadata.artifacts
    scope = resolve_js_intake_reference(fixture["reference"])
    assert len(RunNotes(scope, root=tmp_path).typed_records(
        event_types={"behavior_retention_intent"}
    )) == 1

    metadata.reserve_error = False
    attempts = []
    result = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            fixture["reference"],
            attempts,
        ),
    )

    assert result["status"] == "complete"
    assert result["retry_attempts"] == 1
    assert result["recovered_behaviors"] == 1
    assert len(attempts) == 1
    assert len(metadata.artifacts) == 1
    assert len(metadata.links) == 1


def test_reconcile_run_confirms_verified_blob_after_lost_confirmation(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const confirmation_resume = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    metadata.confirm_failures = 1
    service = _service(tmp_path, fixture, metadata)
    first = service.retain_after_save(
        reference=fixture["reference"],
        behavior=_behavior(fixture["read_id"]),
    )
    assert first["status"] == "pending"
    blob = JsBlobStore(root=tmp_path).path("p", fixture["sha256"])
    assert blob.read_bytes() == fixture["body"]
    assert metadata.artifacts[("p", fixture["sha256"])]["state"] == "reserved"

    fixture["local_file"].unlink()
    attempts = []
    result = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            fixture["reference"],
            attempts,
        ),
    )

    assert result["status"] == "complete"
    assert result["retry_attempts"] == 1
    assert metadata.artifacts[("p", fixture["sha256"])]["state"] == "retained"
    assert next(iter(metadata.links.values()))["status"] == "retained"


def test_reconcile_run_replays_only_persisted_dependency_nominations(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export function persistedDependency() {}\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    metadata.reserve_error = True
    service = _service(tmp_path, fixture, metadata)
    dependency = {
        "selector_type": "source",
        "target": fixture["source_id"],
        "rationale": "Persisted caller required by the saved question.",
    }
    service.retain_after_save(
        reference=fixture["reference"],
        behavior=_behavior(fixture["read_id"]),
        dependencies=[dependency],
    )

    metadata.reserve_error = False
    attempts = []
    result = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            fixture["reference"],
            attempts,
        ),
    )

    assert result["status"] == "complete"
    assert attempts[0]["dependencies"] == [dependency]
    assert len(metadata.links) == 2
    assert {
        link["origin"] for link in metadata.links.values()
    } == {"cited_read", "dependency"}


def test_reconcile_run_continues_across_dependency_batches(tmp_path):
    body = b"export const batchedDependencies = true;\n"
    cited = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_cited",
        body=body,
    )
    cited["root"] = tmp_path
    _append_behavior_note(cited)
    dependencies = []
    for index in range(8):
        dependency_fixture = _context(
            tmp_path,
            context_ref="alice",
            source_id=f"source_dep_{index}",
            body=body,
        )
        dependencies.append({
            "selector_type": "source",
            "target": dependency_fixture["source_id"],
            "rationale": f"dependency-{index}-" + ("x" * 350),
        })
    metadata = FakeMetadata()
    metadata.reserve_error = True
    service = _service(tmp_path, cited, metadata)
    service.retain_after_save(
        reference=cited["reference"],
        behavior=_behavior(cited["read_id"]),
        dependencies=dependencies,
    )

    metadata.reserve_error = False
    attempts = []
    result = service.reconcile_run(
        reference=cited["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            cited["reference"],
            attempts,
        ),
    )

    assert result["status"] == "complete"
    assert result["retry_attempts"] > 1
    assert len(attempts) > 1
    assert len(metadata.links) == 9


def test_reconcile_run_no_work_is_economic_and_repeated_resume_is_noop(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const noWork = true;\n",
    )
    fixture["root"] = tmp_path
    metadata = FakeMetadata()
    metadata.snapshot_error = True
    service = _service(tmp_path, fixture, metadata)

    empty = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
    )
    assert empty["status"] == "no_work"
    assert empty["retry_attempts"] == 0

    metadata.snapshot_error = False
    _append_behavior_note(fixture)
    attempts = []
    first = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            fixture["reference"],
            attempts,
        ),
    )
    second = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            fixture["reference"],
            attempts,
        ),
    )
    assert first["status"] == second["status"] == "complete"
    assert first["retry_attempts"] == 1
    assert second["retry_attempts"] == 0
    assert second["skipped_complete"] == 1
    assert len(attempts) == 1


def test_reconcile_run_database_unavailable_and_deadline_are_explicit(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const unavailable = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    metadata.snapshot_error = True
    service = _service(tmp_path, fixture, metadata)

    database = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
    )
    deadline = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() - 1,
        max_items=4,
    )

    assert database["status"] == "gap"
    assert database["gaps"] == ["retention_database_unavailable"]
    assert deadline["status"] == "partial"
    assert deadline["gaps"] == ["retention_reconcile_deadline"]


def test_reconcile_run_passes_remaining_timeout_to_postgres(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const timed = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)
    started = time.monotonic()

    service.reconcile_run(
        reference=fixture["reference"],
        deadline=started + 5,
        max_items=4,
    )

    assert metadata.timeouts
    assert 0 < metadata.timeouts[0] <= 5000


def test_retention_save_passes_remaining_timeout_to_all_metadata_ops(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const timedSave = true;\n",
    )
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)

    result = service.retain_after_save(
        reference=fixture["reference"],
        behavior=_behavior(fixture["read_id"]),
        deadline=time.monotonic() + 5,
    )

    assert result["status"] == "complete"
    assert metadata.operation_timeouts
    assert all(
        0 < timeout_ms <= 5000
        for _, timeout_ms in metadata.operation_timeouts
    )
    assert {
        operation for operation, _ in metadata.operation_timeouts
    } >= {"reserve", "confirm", "link"}


def test_reconcile_run_item_limit_preserves_pending_work(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const bounded = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture, behavior_id="behavior_a")
    _append_behavior_note(fixture, behavior_id="behavior_b")
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)
    attempts = []

    result = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=1,
        retry_fn=_direct_retry(
            service,
            fixture["reference"],
            attempts,
        ),
    )

    assert result["status"] == "partial"
    assert result["retry_attempts"] == 1
    assert result["gaps"] == ["retention_reconcile_item_limit"]
    assert len(attempts) == 1


def test_reconcile_run_concurrent_attempts_do_not_duplicate_evidence(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const concurrent = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)

    def resume():
        return service.reconcile_run(
            reference=fixture["reference"],
            deadline=time.monotonic() + 10,
            max_items=4,
            retry_fn=_direct_retry(
                service,
                fixture["reference"],
                [],
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: resume(), range(2)))

    assert all(result["status"] == "complete" for result in results)
    assert len(metadata.artifacts) == 1
    assert len(metadata.links) == 1
    assert sum(result["retry_attempts"] for result in results) >= 1


def test_reconcile_run_duplicate_hashes_share_blob_not_links(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const duplicateHash = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture, behavior_id="behavior_a")
    _append_behavior_note(fixture, behavior_id="behavior_b")
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)

    result = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            fixture["reference"],
            [],
        ),
    )

    assert result["status"] == "complete"
    assert result["retry_attempts"] == 2
    assert len(metadata.artifacts) == 1
    assert len(metadata.links) == 2
    assert {
        link["behavior_id"] for link in metadata.links.values()
    } == {"behavior_a", "behavior_b"}


def test_reconcile_run_verifies_success_after_lost_retry_ack(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const lostAck = true;\n",
    )
    fixture["root"] = tmp_path
    _append_behavior_note(fixture)
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)

    def lost_ack(
        *,
        behavior_id,
        revision,
        behavior,
        dependencies,
        deadline,
    ):
        service.retain_after_save(
            reference=fixture["reference"],
            behavior={
                **behavior,
                "behavior_id": behavior_id,
                "revision": revision,
            },
            dependencies=dependencies,
        )
        raise TimeoutError("response lost")

    result = service.reconcile_run(
        reference=fixture["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=lost_ack,
    )

    assert result["status"] == "complete"
    assert result["recovered_behaviors"] == 1
    assert result["gaps"] == []


def test_reconcile_run_missing_or_corrupt_bytes_remain_explicit(tmp_path):
    missing = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_missing",
        body=b"export const missing = true;\n",
    )
    missing["root"] = tmp_path
    _append_behavior_note(missing, behavior_id="behavior_missing")
    missing["local_file"].unlink()
    metadata = FakeMetadata()
    service = _service(tmp_path, missing, metadata)
    result = service.reconcile_run(
        reference=missing["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service,
            missing["reference"],
            [],
        ),
    )
    assert result["status"] == "pending"
    assert result["pending_behaviors"] == 1

    corrupt = _context(
        tmp_path,
        context_ref="bob",
        source_id="source_corrupt",
        body=b"export const corrupt = true;\n",
    )
    corrupt["root"] = tmp_path
    _append_behavior_note(corrupt, behavior_id="behavior_corrupt")
    service_corrupt = JsRetentionService(
        root=tmp_path,
        blobs=JsBlobStore(root=tmp_path),
        metadata=metadata,
        access=corrupt["access"],
        quota_bytes=1024 * 1024,
    )
    assert service_corrupt.retain_after_save(
        reference=corrupt["reference"],
        behavior=_behavior(corrupt["read_id"], "behavior_corrupt"),
    )["status"] == "complete"
    JsBlobStore(root=tmp_path).path("p", corrupt["sha256"]).write_bytes(
        b"corrupt"
    )
    corrupt["local_file"].unlink()
    attempts = []
    corrupted = service_corrupt.reconcile_run(
        reference=corrupt["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
        retry_fn=_direct_retry(
            service_corrupt,
            corrupt["reference"],
            attempts,
        ),
    )
    assert corrupted["status"] == "pending"
    assert corrupted["pending_behaviors"] == 1
    assert attempts
    assert "retained_blob_missing_or_corrupt" in corrupted["gaps"]


def test_reconcile_run_is_isolated_by_run_and_auth_context(tmp_path):
    alice = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_alice",
        body=b"export const alice = true;\n",
    )
    alice["root"] = tmp_path
    _append_behavior_note(alice)
    bob = _context(
        tmp_path,
        context_ref="bob",
        source_id="source_bob",
        body=b"export const bob = true;\n",
    )
    other_run = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_other_run",
        body=b"export const otherRun = true;\n",
        run_id="other-run",
    )
    other_run["root"] = tmp_path
    _append_behavior_note(other_run, behavior_id="behavior_other_run")
    plain_run = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_plain_run",
        body=b"export const plainRun = true;\n",
        run_id="plain-run",
    )
    metadata = FakeMetadata()
    metadata.snapshot_error = True
    bob_service = JsRetentionService(
        root=tmp_path,
        blobs=JsBlobStore(root=tmp_path),
        metadata=metadata,
        access=bob["access"],
        quota_bytes=1024 * 1024,
    )
    plain_service = JsRetentionService(
        root=tmp_path,
        blobs=JsBlobStore(root=tmp_path),
        metadata=metadata,
        access=plain_run["access"],
        quota_bytes=1024 * 1024,
    )

    auth_isolated = bob_service.reconcile_run(
        reference=bob["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
    )
    run_isolated = plain_service.reconcile_run(
        reference=plain_run["reference"],
        deadline=time.monotonic() + 10,
        max_items=4,
    )

    assert auth_isolated["status"] == "no_work"
    assert run_isolated["status"] == "no_work"
    assert other_run["reference"] != plain_run["reference"]


def test_cited_complete_file_is_archived_and_idempotent_after_scratch_loss(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const retained = true;\n",
    )
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)
    behavior = _behavior(fixture["read_id"])

    first = service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
    )
    assert first["status"] == "complete"
    assert first["retained_count"] == 1
    assert first["pending_count"] == 0

    fixture["local_file"].unlink()
    fixture["local_file"].parent.rmdir()
    second = service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
    )
    assert second["status"] == "complete"
    assert second["retained_count"] == 1
    assert not second["transfer_requests"]

    blob = JsBlobStore(root=tmp_path).path("p", fixture["sha256"])
    assert blob.read_bytes() == fixture["body"]
    assert hashlib.sha256(blob.read_bytes()).hexdigest() == fixture["sha256"]
    scope = __import__(
        "polymerhus.recon.js_intake.reader",
        fromlist=["resolve_js_intake_reference"],
    ).resolve_js_intake_reference(fixture["reference"])
    intents = RunNotes(scope, root=tmp_path).typed_records(
        event_types={"behavior_retention_intent"}
    )
    assert len(intents) == 1
    assert intents[0]["sha256"] == fixture["sha256"]


def test_lost_confirmation_retry_uses_verified_orphan_blob(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"const recovery = 'same bytes';\n",
    )
    metadata = FakeMetadata()
    metadata.confirm_failures = 1
    service = _service(tmp_path, fixture, metadata)
    behavior = _behavior(fixture["read_id"])

    first = service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
    )
    assert first["status"] == "pending"
    assert first["gaps"][0]["reason"] == "retention_confirmation_uncertain"
    blob = JsBlobStore(root=tmp_path).path("p", fixture["sha256"])
    assert blob.read_bytes() == fixture["body"]

    fixture["local_file"].unlink()
    second = service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
    )
    assert second["status"] == "complete"
    assert second["retained_count"] == 1
    assert metadata.artifacts[("p", fixture["sha256"])]["state"] == "retained"


def test_kali_only_transfer_verifies_ack_and_rejects_changed_bytes(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"console.log('kali only');\n",
    )
    fixture["local_file"].unlink()
    fixture["local_file"].parent.rmdir()
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)
    behavior = _behavior(fixture["read_id"])

    pending = service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
    )
    assert pending["status"] == "pending"
    request = pending["transfer_requests"][0]
    completed = service.accept_transfer(
        reference=fixture["reference"],
        request_id=request["request_id"],
        body=fixture["body"],
    )
    assert completed["retained_count"] == 1
    assert completed["pending_count"] == 0

    other = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_b",
        body=b"console.log('changed');\n",
    )
    other["local_file"].unlink()
    request = service.retain_after_save(
        reference=other["reference"],
        behavior=_behavior(other["read_id"], "behavior_b"),
    )["transfer_requests"][0]
    with pytest.raises(RetentionError, match="transfer_hash_mismatch"):
        service.accept_transfer(
            reference=other["reference"],
            request_id=request["request_id"],
            body=b"changed bytes",
        )
    assert metadata.artifacts[("p", other["sha256"])]["state"] == "gap"
    assert metadata.artifacts[
        ("p", other["sha256"])
    ]["failure_reason"] == "transfer_hash_mismatch"


def test_same_hash_deduplicates_bytes_but_not_auth_context(tmp_path):
    body = b"export const shared = 42;\n"
    alice = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=body,
    )
    bob = _context(
        tmp_path,
        context_ref="bob",
        source_id="source_b",
        body=body,
    )
    metadata = FakeMetadata()
    service_alice = _service(
        tmp_path,
        alice,
        metadata,
        quota_bytes=len(body),
    )
    first = service_alice.retain_after_save(
        reference=alice["reference"],
        behavior=_behavior(alice["read_id"], "behavior_alice"),
    )
    service_bob = JsRetentionService(
        root=tmp_path,
        blobs=JsBlobStore(root=tmp_path),
        metadata=metadata,
        access=bob["access"],
        quota_bytes=len(body),
    )
    second = service_bob.retain_after_save(
        reference=bob["reference"],
        behavior=_behavior(bob["read_id"], "behavior_bob"),
    )

    assert first["status"] == second["status"] == "complete"
    assert len(metadata.artifacts) == 1
    assert len(list(
        JsBlobStore(root=tmp_path).path(
            "p",
            bob["sha256"],
        ).parent.glob("*.blob")
    )) == 1
    assert len(metadata.links) == 2
    assert {
        link["auth_context_ref"] for link in metadata.links.values()
    } == {"alice", "bob"}

    alice_status = service_alice.status(
        reference=alice["reference"],
        behavior_id="behavior_alice",
        behavior_revision=1,
    )
    cross_context = service_alice.status(
        reference=alice["reference"],
        behavior_id="behavior_bob",
        behavior_revision=1,
    )
    assert alice_status["retained_count"] == 1
    assert cross_context["links"] == []


def test_retention_status_isolated_to_current_run(tmp_path):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export const run_scoped = true;\n",
    )
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)
    behavior = _behavior(fixture["read_id"], "behavior_shared")
    assert service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
    )["status"] == "complete"

    current = next(iter(metadata.links.values()))
    metadata.links["foreign-run-link"] = {
        **current,
        "link_id": "foreign-run-link",
        "run_id": "other-run",
    }
    status = service.status(
        reference=fixture["reference"],
        behavior_id="behavior_shared",
        behavior_revision=1,
    )

    assert len(status["links"]) == 1
    assert status["links"][0]["run_id"] == "r"


def test_quota_exhaustion_keeps_prior_blob_and_reports_explicit_gap(
    tmp_path,
):
    first_body = b"export const first = true;\n"
    second_body = b"export const second = true;\n"
    first = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_first",
        body=first_body,
    )
    metadata = FakeMetadata()
    service = _service(
        tmp_path,
        first,
        metadata,
        quota_bytes=len(first_body),
    )
    assert service.retain_after_save(
        reference=first["reference"],
        behavior=_behavior(first["read_id"], "behavior_first"),
    )["status"] == "complete"

    second = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_second",
        body=second_body,
    )
    result = service.retain_after_save(
        reference=second["reference"],
        behavior=_behavior(second["read_id"], "behavior_second"),
    )

    assert result["status"] == "gap"
    assert result["gaps"] == [{
        "sha256": second["sha256"],
        "reason": "retention_quota_exceeded",
    }]
    first_blob = JsBlobStore(root=tmp_path).path("p", first["sha256"])
    assert first_blob.read_bytes() == first_body
    assert not JsBlobStore(root=tmp_path).path(
        "p",
        second["sha256"],
    ).exists()
    assert metadata.artifacts[
        ("p", second["sha256"])
    ]["state"] == "gap"


def test_dependency_nomination_adds_link_and_exact_retry_is_idempotent(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"export function indispensable() {}\n",
    )
    metadata = FakeMetadata()
    service = _service(tmp_path, fixture, metadata)
    behavior = _behavior(fixture["read_id"])
    dependency = {
        "selector_type": "source",
        "target": fixture["source_id"],
        "rationale": "Imported function needed to explain the cited call.",
    }

    result = service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
        dependencies=[dependency],
    )
    assert result["status"] == "complete"
    assert len(metadata.links) == 2
    before = len(metadata.links)
    repeated = service.retain_after_save(
        reference=fixture["reference"],
        behavior=behavior,
        dependencies=[dependency],
    )
    assert repeated["status"] == "complete"
    assert len(metadata.links) == before


def test_intent_survives_metadata_failure_and_bad_dependency_is_explicit(
    tmp_path,
):
    fixture = _context(
        tmp_path,
        context_ref="alice",
        source_id="source_a",
        body=b"const x = 1;\n",
    )
    metadata = FakeMetadata()
    metadata.reserve_error = True
    service = _service(tmp_path, fixture, metadata)
    result = service.retain_after_save(
        reference=fixture["reference"],
        behavior=_behavior(fixture["read_id"]),
    )
    assert result["status"] == "pending"
    assert result["gaps"] == [{
        "sha256": fixture["sha256"],
        "reason": "retention_reservation_uncertain",
    }]

    scope = __import__(
        "polymerhus.recon.js_intake.reader",
        fromlist=["resolve_js_intake_reference"],
    ).resolve_js_intake_reference(fixture["reference"])
    intents = RunNotes(scope, root=tmp_path).typed_records(
        event_types={"behavior_retention_intent"}
    )
    assert len(intents) == 1

    metadata.reserve_error = False
    invalid = service.retain_after_save(
        reference=fixture["reference"],
        behavior=_behavior(fixture["read_id"]),
        dependencies=[{
            "selector_type": "source",
            "target": fixture["source_id"],
            "rationale": "",
        }],
    )
    assert invalid["status"] == "partial"
    assert any(
        gap["reason"] == "dependency_requires_authorized_reference_and_rationale"
        for gap in invalid["gaps"]
    )
