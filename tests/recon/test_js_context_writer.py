"""Deterministic assembly tests for the saved JS context writer."""

from __future__ import annotations

import copy
import hashlib
import time

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.app.js_context.records import document_identity
from polymerhus.app.js_context.store import JsContextStore
from polymerhus.recon.control.js_context_writer import JsContextWriter
from polymerhus.recon.js_intake import (
    issue_js_intake_reference,
    resolve_js_intake_reference,
)
from polymerhus.recon.js_specialist.notes import RunNotes


class FakeNotes:
    def __init__(self, records):
        self.records = copy.deepcopy(records)
        self.requested_event_types = None

    def typed_records(self, *, event_types=None):
        self.requested_event_types = set(event_types or [])
        return copy.deepcopy(
            [
                record
                for record in self.records
                if event_types is None or record.get("event_type") in event_types
            ]
        )


class FakeAccess:
    def __init__(self, receipts=None, *, error_read_ids=()):
        self.receipts = copy.deepcopy(receipts or {})
        self.error_read_ids = set(error_read_ids)
        self.requested = []

    def read_receipt(self, *, reference, read_id):
        self.requested.append(read_id)
        if read_id in self.error_read_ids:
            raise RuntimeError("receipt unavailable")
        return copy.deepcopy(self.receipts.get(read_id) or {})


class FakeRetention:
    def __init__(self, snapshots=None, *, error_behavior_ids=()):
        self.snapshots = copy.deepcopy(snapshots or {})
        self.error_behavior_ids = set(error_behavior_ids)
        self.requested = []
        self.deadlines = []

    def status(
        self,
        *,
        reference,
        behavior_id,
        behavior_revision,
        deadline=None,
    ):
        self.requested.append((behavior_id, behavior_revision))
        self.deadlines.append(deadline)
        if behavior_id in self.error_behavior_ids:
            raise RuntimeError("retention metadata unavailable")
        return copy.deepcopy(
            self.snapshots.get((behavior_id, behavior_revision))
            or {
                "links": [],
                "retained_count": 0,
                "pending_count": 0,
                "gap_count": 0,
            }
        )


def _reference(
    *,
    project_id="project-a",
    run_id="run-1",
    auth_ref="account-a",
):
    return issue_js_intake_reference(
        project_id,
        run_id,
        context_ref=auth_ref,
    )


def _receipt(
    read_id,
    *,
    project_id="project-a",
    run_id="run-1",
    auth_ref="account-a",
    lead_id="lead-a",
    sha_character="b",
):
    return {
        "read_id": read_id,
        "project_id": project_id,
        "run_id": run_id,
        "context_ref": auth_ref,
        "lead_id": lead_id,
        "selector_type": "source",
        "selector_id": "source-" + read_id.removeprefix("read_"),
        "content_sha256": sha_character * 64,
        "start_byte": 10,
        "end_byte": 42,
        "redaction_policy": "js-source-redaction-v1",
        "delivery_status": "delivered",
        "code": "SECRET_SOURCE_MUST_NOT_PUBLISH",
    }


def _event(
    *,
    behavior_id="behavior-a",
    revision=2,
    question="How is the request built?",
    read_ids=("read-a",),
    text="The stored semantic step.",
    gaps=(),
    context_ref="account-a",
):
    return {
        "event_type": "behavior_save",
        "schema_version": 1,
        "behavior_id": behavior_id,
        "revision": revision,
        "reconstruction_level": "reconstructed",
        "question_ref": "span-" + behavior_id,
        "question": question,
        "priority": "high",
        "lead_id": "lead-a",
        "record_sha256": hashlib.sha256(
            (behavior_id + str(revision)).encode()
        ).hexdigest(),
        "redaction_policy": "js-source-redaction-v1",
        "redaction_count": 0,
        "steps": [
            {
                "kind": "request",
                "text": text,
                "read_ids": list(read_ids),
            }
        ],
        "assumptions": [
            {
                "text": "The server accepts the request.",
                "status": "unverified",
                "read_ids": [],
            }
        ],
        "gaps": list(gaps),
        "context_ref": context_ref,
        "code": "SECRET_SOURCE_MUST_NOT_PUBLISH",
    }


def _link(
    read_id,
    *,
    status="retained",
    sha_character="b",
    failure_reason=None,
):
    return {
        "read_id": read_id,
        "sha256": sha_character * 64,
        "status": status,
        "archive_ref": (
            "sha256/" + sha_character * 64
            if status == "retained"
            else None
        ),
        "size_bytes": 100,
        "artifact_state": status,
        "failure_reason": failure_reason,
    }


def _snapshot(*links):
    return {
        "links": list(links),
        "retained_count": sum(link["status"] == "retained" for link in links),
        "pending_count": sum(link["status"] == "pending" for link in links),
        "gap_count": sum(link["status"] == "gap" for link in links),
    }


def _writer(
    tmp_path,
    *,
    notes,
    access,
    retention,
):
    return JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes,
        access=access,
        retention=retention,
    )


def _complete_analysis():
    return {"status": "complete", "gaps": []}


def _read_current(
    tmp_path,
    reference,
    section="metadata",
    *,
    origin="https://app.test",
):
    scope = resolve_js_intake_reference(reference)
    from polymerhus.app.js_context.records import context_id_for

    normalized_origin = (
        {"status": "unknown", "value": None}
        if origin is None
        else {"status": "known", "value": origin}
    )
    context_id = context_id_for(
        project_id=scope.project_id,
        origin=normalized_origin,
        auth_ref=scope.context_ref,
    )
    return JsContextStore(root_dir=tmp_path).read(
        project_id=scope.project_id,
        context_id=context_id,
        selector="current",
        section=section,
    )


def test_writer_preserves_latest_semantics_and_indexes_shared_evidence_once(
    tmp_path,
) -> None:
    reference = _reference()
    old = _event(revision=1, text="Old revision that must not publish.")
    latest = _event(
        revision=2,
        read_ids=("read-a", "read-shared"),
        text="First stored step,\nin order.",
    )
    second = _event(
        behavior_id="behavior-b",
        revision=1,
        read_ids=("read-shared",),
        text="Second behavior.",
    )
    notes = FakeNotes([second, old, latest])
    access = FakeAccess(
        {
            "read-a": _receipt("read-a"),
            "read-shared": _receipt(
                "read-shared",
                lead_id="lead-shared",
                sha_character="c",
            ),
        }
    )
    retention = FakeRetention(
        {
            ("behavior-a", 2): _snapshot(
                _link("read-a"),
                _link("read-shared", sha_character="c"),
            ),
            ("behavior-b", 1): _snapshot(
                _link("read-shared", sha_character="c"),
            ),
        }
    )
    writer = _writer(
        tmp_path,
        notes=notes,
        access=access,
        retention=retention,
    )

    result = writer.publish(
        reference=reference,
        origin="https://app.test",
        analysis_coverage=_complete_analysis(),
    )
    publication = _read_current(tmp_path, reference, "behaviors")
    evidence = _read_current(tmp_path, reference, "evidence")

    assert result["status"] == "published"
    assert result["coverage"] == "complete"
    assert notes.requested_event_types == {"behavior_save"}
    assert [item["behavior_id"] for item in publication["items"]] == [
        "behavior-a",
        "behavior-b",
    ]
    behavior = publication["items"][0]
    assert behavior["revision"] == 2
    assert behavior["question"] == "How is the request built?"
    assert [step["text"] for step in behavior["steps"]] == [
        "First stored step,\nin order."
    ]
    assert behavior["assumptions"][0]["text"] == (
        "The server accepts the request."
    )
    assert len(evidence["items"]) == 2
    assert [item["read_id"] for item in evidence["items"]] == [
        "read-a",
        "read-shared",
    ]
    shared = evidence["items"][1]
    assert shared["lead_id"] == "lead-shared"
    assert shared["availability"] == "retained_unverified"
    assert shared["retention_status"] == "retained"
    published_bytes = b"".join(
        path.read_bytes()
        for path in (tmp_path / "project-a" / "js-client-side").rglob("*.yml")
    )
    assert b"SECRET_SOURCE_MUST_NOT_PUBLISH" not in published_bytes


def test_mixed_retention_availability_remains_explicit(tmp_path) -> None:
    reference = _reference()
    notes = FakeNotes(
        [_event(read_ids=("read-retained", "read-pending", "read-gap", "read-meta-missing"))]
    )
    access = FakeAccess(
        {
            read_id: _receipt(read_id)
            for read_id in (
                "read-retained",
                "read-pending",
                "read-gap",
                "read-meta-missing",
            )
        }
    )
    retention = FakeRetention(
        {
            ("behavior-a", 2): _snapshot(
                _link("read-retained"),
                _link("read-pending", status="pending"),
                _link(
                    "read-gap",
                    status="gap",
                    failure_reason="retention_quota_exceeded",
                ),
            )
        }
    )

    JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes,
        access=access,
        retention=retention,
    ).publish(reference=reference)
    context = _read_current(tmp_path, reference, "context", origin=None)
    evidence = _read_current(tmp_path, reference, "evidence", origin=None)
    by_read = {item["read_id"]: item for item in evidence["items"]}

    assert context["context"]["coverage"]["status"] == "partial"
    assert "evidence_pending:read-pending" in context["context"]["coverage"]["gaps"]
    assert "evidence_unavailable:read-gap" in context["context"]["coverage"]["gaps"]
    assert (
        "retention_metadata_missing:read-meta-missing"
        in context["context"]["coverage"]["gaps"]
    )
    assert by_read["read-retained"]["availability"] == "retained_unverified"
    assert by_read["read-pending"]["availability"] == "pending"
    assert by_read["read-gap"]["availability"] == "unavailable"
    assert by_read["read-gap"]["limitations"] == ["retention_quota_exceeded"]
    assert by_read["read-meta-missing"]["availability"] == "receipt_only"
    assert by_read["read-meta-missing"]["retention_status"] == "missing"


def test_missing_or_foreign_receipt_is_not_replaced_by_retention_metadata(
    tmp_path,
) -> None:
    reference = _reference()
    notes = FakeNotes([_event(read_ids=("read-foreign",))])
    access = FakeAccess({})
    retention = FakeRetention(
        {
            ("behavior-a", 2): _snapshot(
                _link("read-foreign"),
            )
        }
    )

    JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes,
        access=access,
        retention=retention,
    ).publish(reference=reference)
    evidence = _read_current(tmp_path, reference, "evidence", origin=None)

    item = evidence["items"][0]
    assert item["delivery_status"] == "missing_or_foreign"
    assert item["content_sha256"] is None
    assert item["availability"] == "receipt_missing_or_foreign"
    assert item["retention_status"] == "unknown"
    assert item["limitations"] == ["read_receipt_missing_or_foreign"]


def test_retention_service_failure_does_not_claim_bytes_are_available(
    tmp_path,
) -> None:
    reference = _reference()
    notes = FakeNotes([_event()])
    access = FakeAccess({"read-a": _receipt("read-a")})
    retention = FakeRetention(error_behavior_ids={"behavior-a"})

    JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes,
        access=access,
        retention=retention,
    ).publish(reference=reference)
    context = _read_current(tmp_path, reference, "context", origin=None)
    evidence = _read_current(tmp_path, reference, "evidence", origin=None)

    assert evidence["items"][0]["availability"] == "receipt_only"
    assert evidence["items"][0]["retention_status"] == "missing"
    assert "retention_metadata_unavailable:behavior-a" in (
        context["context"]["coverage"]["gaps"]
    )


def test_malformed_retention_snapshot_remains_an_explicit_gap(tmp_path) -> None:
    reference = _reference()

    class MalformedRetention:
        def status(self, **kwargs):
            return ["not", "a", "snapshot"]

    JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: FakeNotes([_event()]),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=MalformedRetention(),
    ).publish(reference=reference)
    context = _read_current(tmp_path, reference, "context", origin=None)
    evidence = _read_current(tmp_path, reference, "evidence", origin=None)

    assert evidence["items"][0]["availability"] == "receipt_only"
    assert "retention_metadata_unavailable:behavior-a" in (
        context["context"]["coverage"]["gaps"]
    )


def test_retained_metadata_without_artifact_reference_is_not_available(
    tmp_path,
) -> None:
    reference = _reference()
    notes = FakeNotes([_event()])
    access = FakeAccess({"read-a": _receipt("read-a")})
    retained_without_ref = _link("read-a")
    retained_without_ref["archive_ref"] = None
    retention = FakeRetention(
        {("behavior-a", 2): _snapshot(retained_without_ref)}
    )

    JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes,
        access=access,
        retention=retention,
    ).publish(reference=reference)
    context = _read_current(tmp_path, reference, "context", origin=None)
    evidence = _read_current(tmp_path, reference, "evidence", origin=None)

    item = evidence["items"][0]
    assert item["availability"] == "receipt_only"
    assert item["retention_status"] == "missing"
    assert item["artifact_ref"] is None
    assert "retained_artifact_ref_missing" in item["limitations"]
    assert "retained_artifact_ref_missing:read-a" in (
        context["context"]["coverage"]["gaps"]
    )


def test_evidence_limitations_are_bounded_and_mark_truncation(
    tmp_path,
) -> None:
    reference = _reference()
    notes = FakeNotes([_event()])
    access = FakeAccess({"read-a": _receipt("read-a")})
    links = [
        _link("read-a", status="gap", failure_reason=f"gap-{index}")
        for index in range(20)
    ]
    retention = FakeRetention(
        {("behavior-a", 2): _snapshot(*links)}
    )

    JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes,
        access=access,
        retention=retention,
    ).publish(reference=reference)
    evidence = _read_current(
        tmp_path,
        reference,
        "evidence",
        origin=None,
    )

    limitations = evidence["items"][0]["limitations"]
    assert len(limitations) == 16
    assert limitations[-1].startswith("limitations_truncated:")


def test_empty_run_and_unknown_origin_publish_explicit_context(tmp_path) -> None:
    reference = _reference()
    writer = _writer(
        tmp_path,
        notes=FakeNotes([]),
        access=FakeAccess(),
        retention=FakeRetention(),
    )

    result = writer.publish(
        reference=reference,
        origin=None,
        analysis_coverage=_complete_analysis(),
    )
    context = _read_current(tmp_path, reference, "context", origin=None)

    assert result["status"] == "published"
    assert result["coverage"] == "empty"
    assert result["behavior_count"] == 0
    assert context["context"]["origin"] == {"status": "unknown", "value": None}
    assert context["context"]["coverage"] == {
        "status": "empty",
        "gaps": ["no_saved_behaviors"],
    }


def test_prepare_is_pure_and_publish_prepared_uses_the_frozen_document(
    tmp_path,
) -> None:
    reference = _reference()
    writer = _writer(
        tmp_path,
        notes=FakeNotes([_event()]),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    prepared = writer.prepare(
        reference=reference,
        origin="https://app.test",
        analysis_coverage=_complete_analysis(),
        deadline=time.monotonic() + 10,
    )

    assert prepared["status"] == "prepared"
    assert prepared["document_id"] == document_identity(
        prepared["document"]
    )
    assert not (
        tmp_path / "project-a" / "js-client-side"
    ).exists()

    result = writer.publish_prepared(prepared)
    stored = _read_current(tmp_path, reference)

    assert result["status"] == "published"
    assert result["document_id"] == prepared["document_id"]
    assert stored["status"] == "ok"
    assert stored["publication"]["document_sha256"] == (
        result["document_sha256"]
    )


def test_pipeline_envelope_and_string_origin_have_one_document_identity(
    tmp_path,
) -> None:
    reference = _reference()
    writer = _writer(
        tmp_path,
        notes=FakeNotes([_event()]),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    envelope = writer.prepare(
        reference=reference,
        origin={"status": "known", "value": "https://APP.test:443/"},
        analysis_coverage=_complete_analysis(),
    )
    string = writer.prepare(
        reference=reference,
        origin="https://app.test",
        analysis_coverage=_complete_analysis(),
    )

    assert envelope["document_id"] == string["document_id"]
    assert envelope["document"] == string["document"]


def test_partial_analysis_with_retained_evidence_remains_partial(
    tmp_path,
) -> None:
    reference = _reference()
    writer = _writer(
        tmp_path,
        notes=FakeNotes([_event()]),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    prepared = writer.prepare(
        reference=reference,
        origin="https://app.test",
        analysis_coverage={
            "status": "partial",
            "gaps": ["producer_incomplete", "bounded_selection"],
        },
    )

    assert prepared["document"]["context"]["coverage"] == {
        "status": "partial",
        "gaps": ["bounded_selection", "producer_incomplete"],
    }
    assert prepared["document"]["evidence"][0]["availability"] == (
        "retained_unverified"
    )


def test_missing_analysis_coverage_is_conservatively_partial(tmp_path) -> None:
    reference = _reference()
    writer = _writer(
        tmp_path,
        notes=FakeNotes([_event()]),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    prepared = writer.prepare(reference=reference)

    assert prepared["document"]["context"]["coverage"] == {
        "status": "partial",
        "gaps": ["analysis_coverage_unknown"],
    }


def test_empty_behaviours_with_analysis_gaps_are_partial_not_empty(
    tmp_path,
) -> None:
    reference = _reference()
    writer = _writer(
        tmp_path,
        notes=FakeNotes([]),
        access=FakeAccess(),
        retention=FakeRetention(),
    )

    prepared = writer.prepare(
        reference=reference,
        analysis_coverage={
            "status": "partial",
            "gaps": ["producer_inventory_missing"],
        },
    )

    assert prepared["document"]["context"]["coverage"] == {
        "status": "partial",
        "gaps": ["no_saved_behaviors", "producer_inventory_missing"],
    }


def test_prepare_forwards_the_remaining_deadline_to_retention(tmp_path) -> None:
    reference = _reference()
    retention = FakeRetention(
        {("behavior-a", 2): _snapshot(_link("read-a"))}
    )
    writer = _writer(
        tmp_path,
        notes=FakeNotes([_event()]),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=retention,
    )
    deadline = time.monotonic() + 5

    writer.prepare(
        reference=reference,
        analysis_coverage=_complete_analysis(),
        deadline=deadline,
    )

    assert retention.deadlines == [deadline]


def test_expired_prepare_deadline_fails_before_metadata_reads(
    tmp_path,
) -> None:
    reference = _reference()
    access = FakeAccess({"read-a": _receipt("read-a")})
    retention = FakeRetention()
    writer = _writer(
        tmp_path,
        notes=FakeNotes([_event()]),
        access=access,
        retention=retention,
    )

    with pytest.raises(TimeoutError):
        writer.prepare(
            reference=reference,
            analysis_coverage=_complete_analysis(),
            deadline=time.monotonic() - 1,
        )

    assert access.requested == []
    assert retention.requested == []


def test_foreign_note_context_is_not_inherited(tmp_path) -> None:
    reference = _reference(auth_ref="account-a")
    writer = _writer(
        tmp_path,
        notes=FakeNotes([_event(context_ref="account-b")]),
        access=FakeAccess(),
        retention=FakeRetention(),
    )

    result = writer.publish(
        reference=reference,
        origin=None,
        analysis_coverage=_complete_analysis(),
    )
    context = _read_current(tmp_path, reference, "context", origin=None)

    assert result["coverage"] == "empty"
    assert result["behavior_count"] == 0
    assert context["context"]["coverage"] == {
        "status": "empty",
        "gaps": ["no_saved_behaviors"],
    }


def test_runs_and_auth_contexts_do_not_inherit_behaviors(tmp_path) -> None:
    notes_by_scope = {}
    run_1 = _reference(run_id="run-1", auth_ref="account-a")
    run_2 = _reference(run_id="run-2", auth_ref="account-a")
    other_auth = _reference(run_id="run-1", auth_ref="account-b")
    notes_by_scope[("project-a", "run-1", "account-a")] = FakeNotes(
        [_event(behavior_id="behavior-run-1", context_ref="account-a")]
    )
    notes_by_scope[("project-a", "run-2", "account-a")] = FakeNotes(
        [
            _event(
                behavior_id="behavior-run-2",
                context_ref="account-a",
                read_ids=("read-run-2",),
            )
        ]
    )
    notes_by_scope[("project-a", "run-1", "account-b")] = FakeNotes(
        [
            _event(
                behavior_id="behavior-auth-b",
                context_ref="account-b",
                read_ids=("read-a-auth-b",),
            )
        ]
    )
    access = FakeAccess(
        {
            "read-a": _receipt("read-a"),
            "read-run-2": _receipt("read-run-2", run_id="run-2"),
            "read-a-auth-b": _receipt("read-a-auth-b", auth_ref="account-b"),
        }
    )
    retention = FakeRetention(
        {
            ("behavior-run-1", 2): _snapshot(_link("read-a")),
            ("behavior-run-2", 2): _snapshot(_link("read-run-2")),
            ("behavior-auth-b", 2): _snapshot(_link("read-a-auth-b")),
        }
    )
    writer = JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes_by_scope[
            (scope.project_id, scope.run_id, scope.context_ref)
        ],
        access=access,
        retention=retention,
    )

    writer.publish(reference=run_1, origin="https://app.test")
    writer.publish(reference=run_2, origin="https://app.test")
    writer.publish(reference=other_auth, origin="https://app.test")

    run_2_publication = _read_current(tmp_path, run_2, "behaviors")
    auth_b_publication = _read_current(tmp_path, other_auth, "behaviors")
    assert [item["behavior_id"] for item in run_2_publication["items"]] == [
        "behavior-run-2"
    ]
    assert [item["behavior_id"] for item in auth_b_publication["items"]] == [
        "behavior-auth-b"
    ]


def test_writer_retry_is_idempotent_and_output_survives_recreation(
    tmp_path,
) -> None:
    reference = _reference()
    notes = FakeNotes([_event()])
    access = FakeAccess({"read-a": _receipt("read-a")})
    retention = FakeRetention(
        {("behavior-a", 2): _snapshot(_link("read-a"))}
    )
    writer = _writer(
        tmp_path,
        notes=notes,
        access=access,
        retention=retention,
    )

    first = writer.publish(reference=reference, origin="https://app.test")
    second = writer.publish(reference=reference, origin="https://app.test")
    del writer
    read = JsContextStore(root_dir=tmp_path).read(
        project_id="project-a",
        context_id=first["context_id"],
        selector="current",
    )

    assert first["status"] == "published"
    assert second["status"] == "identical"
    assert read["status"] == "ok"
    assert read["publication"]["run_id"] == "run-1"
    assert read["publication"]["behavior_count"] == 1


def test_malformed_saved_record_is_a_visible_partial_gap(tmp_path) -> None:
    reference = _reference()
    malformed = _event()
    malformed["steps"][0]["kind"] = "invented-kind"
    writer = _writer(
        tmp_path,
        notes=FakeNotes([malformed]),
        access=FakeAccess(),
        retention=FakeRetention(),
    )

    result = writer.publish(
        reference=reference,
        analysis_coverage=_complete_analysis(),
    )
    context = _read_current(tmp_path, reference, "context", origin=None)

    assert result["status"] == "published"
    assert result["coverage"] == "partial"
    assert result["behavior_count"] == 0
    assert context["context"]["coverage"]["gaps"] == [
        "invalid_behavior_record:behavior-a"
    ]


def test_one_oversized_saved_record_does_not_block_valid_records(
    tmp_path,
) -> None:
    reference = _reference()
    valid = _event(behavior_id="behavior-a")
    oversized = _event(behavior_id="behavior-b", question="x" * 513)
    writer = _writer(
        tmp_path,
        notes=FakeNotes([valid, oversized]),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=FakeRetention(
            {
                ("behavior-a", 2): _snapshot(_link("read-a")),
                ("behavior-b", 2): _snapshot(_link("read-a")),
            }
        ),
    )

    result = writer.publish(
        reference=reference,
        analysis_coverage=_complete_analysis(),
    )
    publication = _read_current(
        tmp_path,
        reference,
        "behaviors",
        origin=None,
    )

    assert result["coverage"] == "partial"
    assert result["behavior_count"] == 1
    assert result["run_gaps"] == ["invalid_behavior_record:behavior-b"]
    assert [item["behavior_id"] for item in publication["items"]] == [
        "behavior-a"
    ]


def test_malformed_identifier_does_not_abort_other_or_empty_publication(
    tmp_path,
) -> None:
    reference = _reference()
    malformed = _event(behavior_id="bad\nidentifier")
    writer = _writer(
        tmp_path,
        notes=FakeNotes([malformed]),
        access=FakeAccess(),
        retention=FakeRetention(),
    )

    result = writer.publish(
        reference=reference,
        analysis_coverage=_complete_analysis(),
    )

    assert result["coverage"] == "partial"
    assert result["behavior_count"] == 0
    assert result["run_gaps"] == ["invalid_behavior_record:index-0"]


def test_many_malformed_records_remain_a_bounded_partial_publication(
    tmp_path,
) -> None:
    reference = _reference()
    records = []
    for index in range(20):
        malformed = _event(behavior_id=f"behavior-{index}")
        malformed["steps"][0]["kind"] = "invented-kind"
        records.append(malformed)
    writer = _writer(
        tmp_path,
        notes=FakeNotes(records),
        access=FakeAccess(),
        retention=FakeRetention(),
    )

    result = writer.publish(
        reference=reference,
        analysis_coverage=_complete_analysis(),
    )
    context = _read_current(tmp_path, reference, "context", origin=None)

    assert result["coverage"] == "partial"
    assert result["behavior_count"] == 0
    assert len(context["context"]["coverage"]["gaps"]) == 20


def test_real_run_notes_publish_after_writer_recreation(tmp_path) -> None:
    ensure_project("project-a", root=tmp_path)
    reference = _reference()
    scope = resolve_js_intake_reference(reference)
    stored = RunNotes(scope, root=tmp_path).append_typed(
        _event(),
        allow_sanitized_text=True,
    )
    assert stored["behavior_id"] == "behavior-a"
    writer = _writer(
        tmp_path,
        notes=RunNotes(scope, root=tmp_path),
        access=FakeAccess({"read-a": _receipt("read-a")}),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    result = writer.publish(reference=reference, origin="https://app.test")
    del writer
    read = JsContextStore(root_dir=tmp_path).read(
        project_id="project-a",
        context_id=_read_current(tmp_path, reference)["context_id"],
        selector="run-1",
        section="behaviors",
    )

    assert result["status"] == "published"
    assert read["items"][0]["question"] == "How is the request built?"
