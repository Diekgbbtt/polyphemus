import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from polymerhus.ingestion.audit import (
    AuditIssue,
    AuditReport,
    LightRAGStorageReader,
    LightRAGStorageSnapshot,
    StorageParseError,
)
from polymerhus.ingestion.contracts import SourceRecord, SourceStatus
from polymerhus.ingestion.docprep_adapter import DocprepError, NormalizedDocument
from polymerhus.ingestion.lightrag_adapter import LightRAGAdapterError, LightRAGIngestionResult
from polymerhus.ingestion.service import IngestionService
from polymerhus.ingestion import service as service_module
from polymerhus.ingestion.source_identity import build_url_source_key, canonicalize_url
from polymerhus.ingestion.url_downloader import URLDownloadError, UrlDownloadResult


def test_submit_duplicate_does_not_overwrite_processed_source_record(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    source = inbox / "example.md"
    source.write_text("# Already indexed\n", encoding="utf-8")
    existing = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash=service_module.content_sha256(source),
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-1",
        normalized_markdown_path="normalized/key/document.md",
        normalized_json_path="normalized/key/document.json",
    )
    upserts: list[SourceRecord] = []
    jobs: list[tuple[str, str, SourceStatus]] = []
    statuses: list[tuple[str, SourceStatus]] = []
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: existing)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda record: upserts.append(record))
    monkeypatch.setattr(
        service_module.pg,
        "create_ingestion_job",
        lambda job_id, source_key, status: jobs.append((job_id, source_key, status)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: statuses.append((job_id, status)),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
    )

    result = service.submit(source_kind="file", source_uri=str(source))

    assert result["status"] == SourceStatus.SKIPPED_DUPLICATE
    assert result["run_in_background"] is False
    assert upserts == []
    assert jobs[0][1] == "file:inbox/example.md"
    assert jobs[0][2] == SourceStatus.SKIPPED_DUPLICATE
    assert statuses[0][1] == SourceStatus.SKIPPED_DUPLICATE


def test_submit_same_content_different_path_skips_without_reingestion(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    source = inbox / "copy.md"
    source.write_text("# Already indexed\n", encoding="utf-8")
    content_hash = service_module.content_sha256(source)
    original = SourceRecord(
        source_key="file:inbox/original.md",
        source_kind="file",
        source_uri="inbox/original.md",
        content_hash=content_hash,
        status=SourceStatus.PROCESSED,
        parser="markdown",
        parser_version="docprep-0.3.4",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-1",
        normalized_markdown_path="normalized/original/document.md",
        normalized_json_path="normalized/original/document.json",
    )
    upserts: list[SourceRecord] = []
    jobs: list[tuple[str, str, SourceStatus]] = []
    statuses: list[tuple[str, SourceStatus]] = []
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: None)
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda incoming_hash: original if incoming_hash == content_hash else None,
    )
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda record: upserts.append(record))
    monkeypatch.setattr(
        service_module.pg,
        "create_ingestion_job",
        lambda job_id, source_key, status: jobs.append((job_id, source_key, status)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: statuses.append((job_id, status)),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
    )

    result = service.submit(source_kind="file", source_uri=str(source))

    assert result["status"] == SourceStatus.SKIPPED_DUPLICATE
    assert result["run_in_background"] is False
    assert jobs[0][1] == "file:inbox/copy.md"
    assert jobs[0][2] == SourceStatus.SKIPPED_DUPLICATE
    assert statuses[0][1] == SourceStatus.SKIPPED_DUPLICATE
    assert len(upserts) == 1
    duplicate = upserts[0]
    assert duplicate.source_key == "file:inbox/copy.md"
    assert duplicate.source_uri == "inbox/copy.md"
    assert duplicate.status == SourceStatus.SKIPPED_DUPLICATE
    assert duplicate.content_hash == content_hash
    assert duplicate.lightrag_document_id == "doc-1"
    assert duplicate.normalized_markdown_path == "normalized/original/document.md"


def test_submit_known_source_with_changed_hash_starts_update_without_overwriting_active_record(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    source = inbox / "example.md"
    source.write_text("# Updated content\n", encoding="utf-8")
    existing = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path="normalized/old/document.md",
        normalized_json_path="normalized/old/document.json",
    )
    upserts: list[SourceRecord] = []
    jobs: list[tuple[str, str, SourceStatus]] = []
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: existing)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", lambda content_hash: None)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda record: upserts.append(record))
    monkeypatch.setattr(
        service_module.pg,
        "create_ingestion_job",
        lambda job_id, source_key, status: jobs.append((job_id, source_key, status)),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
    )

    result = service.submit(source_kind="file", source_uri=str(source))

    assert result["status"] == SourceStatus.DISCOVERED
    assert result["run_in_background"] is True
    assert upserts == []
    assert jobs[0][1] == "file:inbox/example.md"
    assert jobs[0][2] == SourceStatus.DISCOVERED


def test_update_parser_failure_keeps_active_processed_record(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    source = root / "inbox" / "example.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Updated content\n", encoding="utf-8")
    active = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path="normalized/old/document.md",
        normalized_json_path="normalized/old/document.json",
    )
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[SourceStatus, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_ingestion_job",
        lambda job_id: {
            "job_id": job_id,
            "source_key": active.source_key,
            "source_uri": active.source_uri,
            "status": SourceStatus.DISCOVERED.value,
            "content_hash": active.content_hash,
            "lightrag_document_id": active.lightrag_document_id,
            "audit": None,
            "error": None,
        },
    )
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda record: upserts.append(record.model_copy(deep=True)))
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((status, kwargs.get("error"))),
    )

    async def fail_normalize(source_path, *, output_root):
        raise service_module.DocprepError("PARSE_FAILED", "parser exploded")

    monkeypatch.setattr(service_module, "normalize_document", fail_normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
    )

    service.process_job("job-1")

    assert upserts == []
    assert active.status == SourceStatus.PROCESSED
    assert active.lightrag_document_id == "doc-old"
    assert job_statuses[-1][0] == SourceStatus.FAILED
    assert job_statuses[-1][1]["code"] == "PARSE_FAILED"


def test_update_success_replaces_active_record_after_lightrag_reingestion(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    source = root / "inbox" / "example.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Updated content\n", encoding="utf-8")
    new_hash = service_module.content_sha256(source)
    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# Updated content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")
    active = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path=str(root / "normalized" / "old" / "document.md"),
        normalized_json_path=str(root / "normalized" / "old" / "document.json"),
    )
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[SourceStatus, dict | None]] = []

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            return {"status": "ok"}

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    monkeypatch.setattr(
        service_module.pg,
        "get_ingestion_job",
        lambda job_id: {
            "job_id": job_id,
            "source_key": active.source_key,
            "source_uri": active.source_uri,
            "status": SourceStatus.DISCOVERED.value,
            "content_hash": active.content_hash,
            "lightrag_document_id": active.lightrag_document_id,
            "audit": None,
            "error": None,
        },
    )
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda record: upserts.append(record.model_copy(deep=True)))
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((status, kwargs.get("audit"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )

    service.process_job("job-1")

    assert adapter.deleted == ["doc-old"]
    assert adapter.ingested == [new_md]
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == new_hash
    assert upserts[-1].lightrag_document_id == "doc-new"
    assert upserts[-1].normalized_markdown_path == str(new_md)
    assert job_statuses[-1][0] == SourceStatus.PROCESSED
    assert audit_calls[0]["lightrag_document_id"] == "doc-new"


def test_update_delete_failure_keeps_active_record_and_fails_job(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    source = root / "inbox" / "example.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Updated content\n", encoding="utf-8")
    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# Updated content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")
    active = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path=str(root / "normalized" / "old" / "document.md"),
        normalized_json_path=str(root / "normalized" / "old" / "document.json"),
    )
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[SourceStatus, dict | None]] = []

    class FailingDeleteAdapter:
        def delete_document(self, document_id):
            raise LightRAGAdapterError("LIGHTRAG_DELETE_FAILED", "delete failed", retryable=True)

        def ingest_markdown(self, markdown_path, *, source_key):
            raise AssertionError("new ingestion must not run after delete failure")

    monkeypatch.setattr(
        service_module.pg,
        "get_ingestion_job",
        lambda job_id: {
            "job_id": job_id,
            "source_key": active.source_key,
            "source_uri": active.source_uri,
            "status": SourceStatus.DISCOVERED.value,
            "content_hash": active.content_hash,
            "lightrag_document_id": active.lightrag_document_id,
            "audit": None,
            "error": None,
        },
    )
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda record: upserts.append(record.model_copy(deep=True)))
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((status, kwargs.get("error"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FailingDeleteAdapter(),
    )

    service.process_job("job-1")

    assert upserts == []
    assert active.status == SourceStatus.PROCESSED
    assert active.lightrag_document_id == "doc-old"
    assert job_statuses[-1][0] == SourceStatus.FAILED
    assert job_statuses[-1][1]["code"] == "LIGHTRAG_DELETE_FAILED"


def test_update_ingestion_failure_restores_previous_normalized_document(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    source = root / "inbox" / "example.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Updated content\n", encoding="utf-8")
    old_md = root / "normalized" / "old" / "document.md"
    old_json = root / "normalized" / "old" / "document.json"
    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    old_md.parent.mkdir(parents=True)
    new_md.parent.mkdir(parents=True)
    old_md.write_text("# Old content\n", encoding="utf-8")
    old_json.write_text("{}", encoding="utf-8")
    new_md.write_text("# Updated content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")
    active = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path=str(old_md),
        normalized_json_path=str(old_json),
    )
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[SourceStatus, dict | None]] = []

    class RestoringAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            return {"status": "ok"}

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                raise LightRAGAdapterError("LIGHTRAG_INGESTION_FAILED", "new ingestion failed", retryable=True)
            return LightRAGIngestionResult(track_id="track-restore", document_id="doc-restored", status="processed")

    adapter = RestoringAdapter()
    monkeypatch.setattr(
        service_module.pg,
        "get_ingestion_job",
        lambda job_id: {
            "job_id": job_id,
            "source_key": active.source_key,
            "source_uri": active.source_uri,
            "status": SourceStatus.DISCOVERED.value,
            "content_hash": active.content_hash,
            "lightrag_document_id": active.lightrag_document_id,
            "audit": None,
            "error": None,
        },
    )
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda record: upserts.append(record.model_copy(deep=True)))
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((status, kwargs.get("error"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
    )

    service.process_job("job-1")

    assert adapter.deleted == ["doc-old"]
    assert adapter.ingested == [new_md, old_md]
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == "old-hash"
    assert upserts[-1].lightrag_document_id == "doc-restored"
    assert job_statuses[-1][0] == SourceStatus.FAILED
    assert job_statuses[-1][1]["code"] == "LIGHTRAG_INGESTION_FAILED"


class _FakeStorageReader:
    def __init__(self):
        self.calls = 0
        self.snapshot_to_return = LightRAGStorageSnapshot()

    def snapshot(self):
        self.calls += 1
        return self.snapshot_to_return


def _make_fake_audit_runner(calls, report):
    def runner(*, job_id, source_key, lightrag_document_id, storage_snapshot, allowed_entity_types):
        calls.append(
            {
                "job_id": job_id,
                "source_key": source_key,
                "lightrag_document_id": lightrag_document_id,
                "storage_snapshot": storage_snapshot,
                "allowed_entity_types": allowed_entity_types,
            }
        )
        return report
    return runner


def _make_update_fixture(tmp_path):
    root = tmp_path / "ingestion"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    source = inbox / "example.md"
    source.write_text("# Updated content\n", encoding="utf-8")
    current_hash = service_module.content_sha256(source)

    old_md = root / "normalized" / "old" / "document.md"
    old_json = root / "normalized" / "old" / "document.json"
    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    old_md.parent.mkdir(parents=True)
    new_md.parent.mkdir(parents=True)
    old_md.write_text("# Old content\n", encoding="utf-8")
    old_json.write_text("{}", encoding="utf-8")
    new_md.write_text("# Updated content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    active = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path=str(old_md),
        normalized_json_path=str(old_json),
    )
    job = {
        "job_id": "job-1",
        "source_key": active.source_key,
        "source_uri": active.source_uri,
        "status": SourceStatus.DISCOVERED.value,
        "content_hash": active.content_hash,
        "lightrag_document_id": active.lightrag_document_id,
        "audit": None,
        "error": None,
    }
    return root, source, old_md, new_md, new_json, active, job, current_hash


def _install_update_mocks(monkeypatch, active, job, upserts, job_statuses):
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((job_id, status, kwargs.get("audit"), kwargs.get("error"))),
    )


def test_update_success_audit_no_critical_activates_new_version_and_processed(tmp_path, monkeypatch):
    root, source, old_md, new_md, new_json, active, job, current_hash = _make_update_fixture(tmp_path)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    _install_update_mocks(monkeypatch, active, job, upserts, job_statuses)

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)

    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )
    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == current_hash
    assert upserts[-1].lightrag_document_id == "doc-new"
    assert job_statuses[-1][1] == SourceStatus.PROCESSED
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert audit_calls[0]["lightrag_document_id"] == "doc-new"
    assert audit_calls[0]["source_key"] == active.source_key
    assert audit_calls[0]["job_id"] == "job-1"
    assert storage_reader.calls == 1
    assert adapter.deleted == ["doc-old"]


def test_update_critical_audit_triggers_rollback_to_previous_version(tmp_path, monkeypatch):
    root, source, old_md, new_md, new_json, active, job, current_hash = _make_update_fixture(tmp_path)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    _install_update_mocks(monkeypatch, active, job, upserts, job_statuses)

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")
            return LightRAGIngestionResult(track_id="track-restore", document_id="doc-restored", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)

    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )
    service.process_job("job-1")

    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md, old_md]
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == "old-hash"
    assert upserts[-1].lightrag_document_id == "doc-restored"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert job_statuses[-1][3] is not None
    assert job_statuses[-1][3]["code"] == "AUDIT_FAILED"
    assert job_statuses[-1][3]["stage"] == "AUDITING"
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert audit_calls[0]["lightrag_document_id"] == "doc-new"


def test_update_warning_audit_activates_new_version_and_processed(tmp_path, monkeypatch):
    root, source, old_md, new_md, new_json, active, job, current_hash = _make_update_fixture(tmp_path)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    _install_update_mocks(monkeypatch, active, job, upserts, job_statuses)

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[AuditIssue(code="WARN", message="warning", severity="warning", evidence={})],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)

    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )
    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].lightrag_document_id == "doc-new"
    assert job_statuses[-1][1] == SourceStatus.PROCESSED
    assert len(job_statuses[-1][2]["warnings"]) == 1
    assert adapter.deleted == ["doc-old"]


def test_update_rollback_failure_follows_existing_recoverable_failure(tmp_path, monkeypatch):
    root, source, old_md, new_md, new_json, active, job, current_hash = _make_update_fixture(tmp_path)
    # Remove the previous markdown artifact so rollback is impossible.
    old_md.unlink()

    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    _install_update_mocks(monkeypatch, active, job, upserts, job_statuses)

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)

    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )
    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md]
    assert audit_calls[0]["lightrag_document_id"] == "doc-new"


def test_update_critical_audit_delete_rejected_document_failure(tmp_path, monkeypatch):
    root, source, old_md, new_md, new_json, active, job, current_hash = _make_update_fixture(tmp_path)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    _install_update_mocks(monkeypatch, active, job, upserts, job_statuses)

    class FailingDeleteOnNewAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            if document_id == "doc-new":
                raise LightRAGAdapterError("LIGHTRAG_DELETE_FAILED", "delete failed", retryable=True)
            return {"status": "ok"}

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")

    adapter = FailingDeleteOnNewAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(output_dir=new_md.parent, markdown_path=new_md, json_path=new_json, parser="markdown", warnings=[])

    monkeypatch.setattr(service_module, "normalize_document", normalize)

    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )
    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md]
    assert audit_calls[0]["lightrag_document_id"] == "doc-new"


def _make_new_document_fixture(tmp_path):
    root = tmp_path / "ingestion"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    source = inbox / "new.md"
    source.write_text("# New content\n", encoding="utf-8")

    normalized_md = root / "normalized" / "new" / "document.md"
    normalized_json = root / "normalized" / "new" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# New content\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    record = SourceRecord(
        source_key="file:inbox/new.md",
        source_kind="file",
        source_uri="inbox/new.md",
        content_hash="hash-irrelevant",
        status=SourceStatus.DISCOVERED,
    )
    job = {
        "job_id": "job-1",
        "source_key": record.source_key,
        "source_uri": record.source_uri,
        "status": SourceStatus.DISCOVERED.value,
        "content_hash": record.content_hash,
        "lightrag_document_id": None,
        "audit": None,
        "error": None,
    }
    return root, source, normalized_md, normalized_json, record, job


def test_new_document_success_audit_results_in_processed(tmp_path, monkeypatch):
    root, source, normalized_md, normalized_json, record, job = _make_new_document_fixture(tmp_path)

    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None]] = []

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(track_id="track", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=record.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((job_id, status, kwargs.get("audit"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="markdown",
            warnings=[],
        )

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )

    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.PROCESSED
    assert job_statuses[-1][1] == SourceStatus.PROCESSED
    assert audit_calls[0]["lightrag_document_id"] == "doc-new"
    assert audit_calls[0]["source_key"] == record.source_key
    assert audit_calls[0]["job_id"] == "job-1"
    assert storage_reader.calls == 1
    assert adapter.deleted == []
    assert job_statuses[-1][2] == report.model_dump(mode="json")


def test_new_document_audit_critical_results_in_failed_audit(tmp_path, monkeypatch):
    root, source, normalized_md, normalized_json, record, job = _make_new_document_fixture(tmp_path)

    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(track_id="track", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=record.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((job_id, status, kwargs.get("audit"), kwargs.get("error"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="markdown",
            warnings=[],
        )

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )

    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert job_statuses[-1][3] is not None
    assert job_statuses[-1][3]["code"] == "AUDIT_FAILED"
    assert job_statuses[-1][3]["stage"] == "AUDITING"
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert not any(rec.status == SourceStatus.PROCESSED for rec in upserts)
    assert adapter.deleted == []


def test_new_document_audit_warnings_do_not_block_processed(tmp_path, monkeypatch):
    root, source, normalized_md, normalized_json, record, job = _make_new_document_fixture(tmp_path)

    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None]] = []

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(track_id="track", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-1",
        source_key=record.source_key,
        critical_issues=[],
        warnings=[AuditIssue(code="WARN", message="warning", severity="warning", evidence={})],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((job_id, status, kwargs.get("audit"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="markdown",
            warnings=[],
        )

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )

    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.PROCESSED
    assert job_statuses[-1][1] == SourceStatus.PROCESSED
    assert len(job_statuses[-1][2]["warnings"]) == 1
    assert adapter.deleted == []


def test_default_storage_reader_uses_configured_storage_dir(tmp_path, monkeypatch):
    storage_dir = tmp_path / "lightrag_storage"
    monkeypatch.setattr(service_module.config, "LIGHTRAG_STORAGE_DIR", str(storage_dir))

    service = IngestionService(
        ingestion_root=tmp_path / "ingestion",
        normalized_root=tmp_path / "normalized",
        lightrag_adapter=None,
    )

    assert isinstance(service.storage_reader, LightRAGStorageReader)
    assert service.storage_reader.storage_root == storage_dir


class _FailingStorageReader:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        raise self.exc


def test_new_document_storage_parse_error_produces_failed_audit(tmp_path, monkeypatch):
    root, source, normalized_md, normalized_json, record, job = _make_new_document_fixture(tmp_path)

    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(track_id="track", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FailingStorageReader(StorageParseError("boom"))
    audit_calls = []

    def audit_runner(**kwargs):
        audit_calls.append(kwargs)
        raise AssertionError("audit runner should not run")

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((job_id, status, kwargs.get("audit"), kwargs.get("error"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="markdown",
            warnings=[],
        )

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )

    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    audit = job_statuses[-1][2]
    assert audit is not None
    assert audit["critical_issues"][0]["code"] == "STORAGE_PARSE_ERROR"
    assert audit["critical_issues"][0]["severity"] == "critical"
    assert audit["checked_at"]
    error = job_statuses[-1][3]
    assert error is not None
    assert error["code"] == "AUDIT_FAILED"
    assert error["stage"] == SourceStatus.AUDITING.value
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert adapter.deleted == []
    assert adapter.ingested == [normalized_md]
    assert storage_reader.calls == 1
    assert audit_calls == []


def test_update_storage_parse_error_deletes_rejected_candidate_and_restores_previous(tmp_path, monkeypatch):
    root, source, old_md, new_md, new_json, active, job, current_hash = _make_update_fixture(tmp_path)

    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")
            return LightRAGIngestionResult(track_id="track-restore", document_id="doc-restored", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FailingStorageReader(StorageParseError("boom"))
    audit_calls = []

    def audit_runner(**kwargs):
        audit_calls.append(kwargs)
        raise AssertionError("audit runner should not run")

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((job_id, status, kwargs.get("audit"), kwargs.get("error"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="markdown",
            warnings=[],
        )

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )

    service.process_job("job-1")

    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md, old_md]
    assert not any(rec.lightrag_document_id == "doc-new" for rec in upserts)
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == "old-hash"
    assert upserts[-1].lightrag_document_id == "doc-restored"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2]["critical_issues"][0]["code"] == "STORAGE_PARSE_ERROR"
    assert job_statuses[-1][3]["code"] == "AUDIT_FAILED"
    assert job_statuses[-1][3]["stage"] == SourceStatus.AUDITING.value
    assert not any(status == SourceStatus.AUDITING for _, status, _, _ in job_statuses[-1:])
    assert storage_reader.calls == 1
    assert audit_calls == []


def test_update_storage_parse_error_rollback_failure_preserves_audit(tmp_path, monkeypatch):
    root, source, old_md, new_md, new_json, active, job, current_hash = _make_update_fixture(tmp_path)
    old_md.unlink()

    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(track_id="track-new", document_id="doc-new", status="processed")

    adapter = FakeAdapter()
    storage_reader = _FailingStorageReader(StorageParseError("boom"))
    audit_calls = []

    def audit_runner(**kwargs):
        audit_calls.append(kwargs)
        raise AssertionError("audit runner should not run")

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((job_id, status, kwargs.get("audit"), kwargs.get("error"))),
    )

    async def normalize(source_path, *, output_root):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="markdown",
            warnings=[],
        )

    monkeypatch.setattr(service_module, "normalize_document", normalize)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
    )

    service.process_job("job-1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2]["critical_issues"][0]["code"] == "STORAGE_PARSE_ERROR"
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][3]["stage"] == SourceStatus.AUDITING.value
    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md]
    assert not any(status == SourceStatus.AUDITING for _, status, _, _ in job_statuses[-1:])
    assert storage_reader.calls == 1
    assert audit_calls == []


# ---------------------------------------------------------------------------
# Milestone 4 Task 3: URL download -> parser handoff -> audit
# ---------------------------------------------------------------------------


def _make_url_fixture(tmp_path):
    root = tmp_path / "ingestion"
    root.mkdir()
    record = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash=None,
        status=SourceStatus.DISCOVERED,
        source_metadata={"active_download": None, "latest_attempt": None},
    )
    job = {
        "job_id": "job-url-1",
        "source_key": record.source_key,
        "source_uri": record.source_uri,
        "status": SourceStatus.DISCOVERED.value,
        "content_hash": None,
        "lightrag_document_id": None,
        "audit": None,
        "error": None,
    }
    return root, record, job


def _make_active_url_fixture(tmp_path):
    root, record, job = _make_url_fixture(tmp_path)
    old_md = root / "normalized" / "old" / "document.md"
    old_json = root / "normalized" / "old" / "document.json"
    old_md.parent.mkdir(parents=True)
    old_md.write_text("# Old content\n", encoding="utf-8")
    old_json.write_text("{}", encoding="utf-8")
    old_raw = root / "url-artifacts" / "old-artifact"
    old_raw.parent.mkdir(parents=True)
    old_raw.write_bytes(b"# Old content\n")
    active_download = {
        "requested_url": "https://Example.COM/Doc?x=1",
        "canonical_url": "https://example.com/doc",
        "final_url": "https://example.com/doc",
        "redirect_chain": ["https://example.com/start"],
        "content_type": "text/html",
        "content_disposition": None,
        "etag": '"old-etag"',
        "last_modified": "Wed, 21 Oct 2026 07:28:00 GMT",
        "downloaded_bytes": 12,
        "sha256": "old-hash",
        "raw_artifact_path": str(old_raw),
        "fetched_at": "2024-01-01T00:00:00Z",
    }
    active = record.model_copy(
        update={
            "content_hash": "old-hash",
            "status": SourceStatus.PROCESSED,
            "parser": "html",
            "normalization_version": "lightrag_docprep",
            "lightrag_document_id": "doc-old",
            "normalized_markdown_path": str(old_md),
            "normalized_json_path": str(old_json),
            "source_metadata": {
                "active_download": active_download,
                "latest_attempt": {
                    **active_download,
                    "job_id": "job-url-0",
                    "terminal_outcome": SourceStatus.PROCESSED.value,
                    "error_code": None,
                },
            },
        }
    )
    active_job = dict(
        job,
        content_hash="old-hash",
        lightrag_document_id="doc-old",
    )
    return root, active, active_job, old_md, old_json


def _make_download_result(
    tmp_path,
    *,
    content_type="text/html",
    final_url="https://example.com/doc",
    requested_url="https://Example.COM/Doc?x=1",
    canonical_url="https://example.com/doc",
    sha256="sha-abc",
    fetched_at="2024-01-01T00:00:00Z",
):
    artifact = tmp_path / "raw-artifact"
    artifact.write_bytes(b"# Title\n\nsome body\n")
    return UrlDownloadResult(
        requested_url=requested_url,
        canonical_url=canonical_url,
        final_url=final_url,
        redirect_chain=["https://example.com/start"],
        content_type=content_type,
        content_disposition=None,
        etag='"abc"',
        last_modified="Wed, 21 Oct 2026 07:28:00 GMT",
        downloaded_bytes=16,
        sha256=sha256,
        raw_artifact_path=str(artifact),
        fetched_at=fetched_at,
    )


class _FakeDownloader:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def download(self, requested_url, *, artifact_dir=None):
        self.calls.append((requested_url, artifact_dir))
        if self.error is not None:
            raise self.error
        return self.result


def _install_url_job_mocks(monkeypatch, job, record, upserts, job_statuses):
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )


def test_url_submit_creates_null_hash_stub_and_background_job(tmp_path, monkeypatch):
    root, _, _ = _make_url_fixture(tmp_path)
    upserts: list[SourceRecord] = []
    jobs: list[tuple[str, str, SourceStatus]] = []
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: None)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda record: upserts.append(record.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "create_ingestion_job",
        lambda job_id, source_key, status: jobs.append((job_id, source_key, status)),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=_FakeDownloader(),
    )

    result = service.submit(
        source_kind="url",
        source_uri="https://Example.COM/Doc?x=1#frag",
    )

    assert result["status"] == SourceStatus.DISCOVERED
    assert result["run_in_background"] is True
    assert result["source_key"] == "url:https://example.com/Doc?x=1"
    assert len(upserts) == 1
    stub = upserts[0]
    assert stub.source_kind == "url"
    assert stub.source_uri == "https://example.com/Doc?x=1"
    assert stub.content_hash is None
    assert stub.status == SourceStatus.DISCOVERED
    assert stub.source_metadata == {"active_download": None, "latest_attempt": None}
    assert jobs[0][1] == "url:https://example.com/Doc?x=1"
    assert jobs[0][2] == SourceStatus.DISCOVERED
    assert service.downloader.calls == []


def test_url_submit_encoded_dot_segments_agree_between_source_uri_and_source_key(
    tmp_path, monkeypatch
):
    root, _, _ = _make_url_fixture(tmp_path)
    upserts: list[SourceRecord] = []
    jobs: list[tuple[str, str, SourceStatus]] = []
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: None)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda record: upserts.append(record.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "create_ingestion_job",
        lambda job_id, source_key, status: jobs.append((job_id, source_key, status)),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=_FakeDownloader(),
    )

    raw = "https://Example.com/a/%2e%2e/document"
    result = service.submit(source_kind="url", source_uri=raw)

    stub = upserts[0]
    assert stub.source_uri == "https://example.com/document"
    assert result["source_key"] == "url:https://example.com/document"
    assert build_url_source_key(stub.source_uri) == stub.source_key
    assert stub.source_key == result["source_key"]
    assert canonicalize_url(stub.source_uri) == stub.source_uri


def test_url_submit_rejects_malformed_url_without_database_writes(tmp_path, monkeypatch):
    root, _, _ = _make_url_fixture(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda *a: calls.append("get"))
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", lambda *a: calls.append("upsert"))
    monkeypatch.setattr(service_module.pg, "create_ingestion_job", lambda *a: calls.append("job"))
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=_FakeDownloader(),
    )

    with pytest.raises(ValueError) as exc:
        service.submit(source_kind="url", source_uri="http://example.com:8080/doc")

    assert "URL_PORT_FORBIDDEN" in str(exc.value)
    assert calls == []


def test_url_job_success_reaches_audit_and_processed(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    handoff_calls: list[dict] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n\nsome body\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        handoff_calls.append(
            {
                "source_path": Path(source_path),
                "source_identity": source_identity,
                "source_type": source_type,
                "native_metadata": native_metadata,
            }
        )
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FakeAdapter(),
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
        now=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert downloader.calls == [
        ("https://Example.COM/Doc?x=1", root / "url-artifacts")
    ]
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == "sha-abc"
    assert all(rec.content_hash is None for rec in upserts[:-1])
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"]["requested_url"] == "https://Example.COM/Doc?x=1"
    assert metadata["active_download"]["canonical_url"] == "https://example.com/doc"
    assert metadata["active_download"]["final_url"] == "https://example.com/doc"
    assert metadata["active_download"]["redirect_chain"] == ["https://example.com/start"]
    assert metadata["active_download"]["content_type"] == "text/html"
    assert metadata["active_download"]["sha256"] == "sha-abc"
    assert metadata["active_download"]["raw_artifact_path"] == download_result.raw_artifact_path
    assert metadata["latest_attempt"]["job_id"] == "job-url-1"
    assert metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.PROCESSED.value
    assert metadata["latest_attempt"]["error_code"] is None
    assert handoff_calls[0]["source_identity"] == "https://example.com/doc"
    assert handoff_calls[0]["source_type"] == "html"
    assert handoff_calls[0]["native_metadata"]["canonical_url"] == "https://example.com/doc"
    assert handoff_calls[0]["native_metadata"]["final_url"] == "https://example.com/doc"
    assert [status for _, status, _, _ in job_statuses] == [
        SourceStatus.PROCESSING,
        SourceStatus.NORMALIZED,
        SourceStatus.INGESTING,
        SourceStatus.AUDITING,
        SourceStatus.PROCESSED,
    ]
    assert audit_calls[0]["lightrag_document_id"] == "doc-url"
    assert audit_calls[0]["source_key"] == record.source_key
    assert job_statuses[-1][2] == report.model_dump(mode="json")


def test_url_job_critical_audit_reaches_failed_audit(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FakeAdapter(),
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert upserts[-1].status == SourceStatus.FAILED_AUDIT
    assert upserts[-1].content_hash is None
    assert all(rec.content_hash is None for rec in upserts)
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"] is None
    attempt = metadata["latest_attempt"]
    assert attempt["sha256"] == "sha-abc"
    assert attempt["final_url"] == "https://example.com/doc"
    assert attempt["terminal_outcome"] == SourceStatus.FAILED_AUDIT.value
    assert attempt["error_code"] == "AUDIT_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][3] is not None
    assert job_statuses[-1][3]["code"] == "AUDIT_FAILED"
    assert job_statuses[-1][3]["stage"] == SourceStatus.AUDITING.value
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert not any(rec.status == SourceStatus.PROCESSED for rec in upserts)


def test_url_job_new_source_reaches_auditing_without_activation_fields(
    tmp_path, monkeypatch
):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    auditing_snapshots: list[SourceRecord] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n\nsome body\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def delete_document(self, document_id):
            raise AssertionError("the clean-audit path must not delete the candidate")

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner([], report)

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )

    def record_job_status(job_id, status, **kwargs):
        if status == SourceStatus.AUDITING:
            auditing_snapshots.append(record.model_copy(deep=True))
        job_statuses.append((job_id, status, kwargs.get("audit"), kwargs.get("error")))

    monkeypatch.setattr(service_module.pg, "set_ingestion_job_status", record_job_status)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FakeAdapter(),
        audit_runner=audit_runner,
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert len(auditing_snapshots) == 1
    snapshot = auditing_snapshots[0]
    assert snapshot.content_hash is None
    assert snapshot.parser is None
    assert snapshot.parser_version is None
    assert snapshot.normalization_version is None
    assert snapshot.lightrag_document_id is None
    assert snapshot.normalized_markdown_path is None
    assert snapshot.normalized_json_path is None
    assert snapshot.source_metadata["active_download"] is None
    # No persisted source write may imply the candidate is active before the
    # final activation write.
    for persisted in upserts[:-1]:
        assert persisted.content_hash is None
        assert persisted.parser is None
        assert persisted.normalization_version is None
        assert persisted.lightrag_document_id is None
        assert persisted.normalized_markdown_path is None
        assert persisted.normalized_json_path is None
        assert (persisted.source_metadata or {}).get("active_download") is None
    # The final write still activates everything at once.
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == "sha-abc"
    assert upserts[-1].lightrag_document_id == "doc-url"


def test_url_job_critical_audit_deletes_rejected_candidate_and_clears_activation_fields(
    tmp_path, monkeypatch
):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    adapter = FakeAdapter()
    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner([], report)

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert adapter.deleted == ["doc-url"]
    final = upserts[-1]
    assert final.status == SourceStatus.FAILED_AUDIT
    assert final.content_hash is None
    assert final.parser is None
    assert final.parser_version is None
    assert final.normalization_version is None
    assert final.lightrag_document_id is None
    assert final.normalized_markdown_path is None
    assert final.normalized_json_path is None
    assert final.source_metadata["active_download"] is None
    assert final.source_metadata["latest_attempt"]["error_code"] == "AUDIT_FAILED"
    assert final.source_metadata["latest_attempt"]["sha256"] == "sha-abc"
    assert all(rec.content_hash is None for rec in upserts)
    assert all(rec.lightrag_document_id is None for rec in upserts)
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][3]["code"] == "AUDIT_FAILED"


def test_url_job_critical_audit_candidate_delete_failure_is_terminalized_sanitized(
    tmp_path, monkeypatch
):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FailingDeleteAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            raise LightRAGAdapterError(
                "LIGHTRAG_DELETE_FAILED",
                "delete exploded at /secret/socket",
                retryable=True,
            )

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    adapter = FailingDeleteAdapter()
    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner([], report)

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert adapter.deleted == ["doc-url"]
    final = upserts[-1]
    assert final.status == SourceStatus.FAILED_AUDIT
    assert final.content_hash is None
    assert final.parser is None
    assert final.normalization_version is None
    assert final.lightrag_document_id is None
    assert final.normalized_markdown_path is None
    assert final.normalized_json_path is None
    assert final.source_metadata["active_download"] is None
    assert final.source_metadata["latest_attempt"]["error_code"] == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][3]["message"] == "Candidate cleanup failed"
    assert "/secret" not in job_statuses[-1][3]["message"]
    assert "socket" not in job_statuses[-1][3]["message"]


@pytest.mark.parametrize(
    "error_code",
    ["URL_CONTENT_TYPE_UNSUPPORTED", "URL_CONTENT_TYPE_AMBIGUOUS"],
)
def test_url_download_failure_reaches_failed_with_sanitized_error(
    tmp_path,
    monkeypatch,
    error_code,
):
    root, record, job = _make_url_fixture(tmp_path)
    downloader = _FakeDownloader(error=URLDownloadError(error_code))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=downloader,
        now=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == error_code
    assert upserts[-1].last_error_message == "URL download failed"
    assert upserts[-1].content_hash is None
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"] is None
    attempt = metadata["latest_attempt"]
    assert attempt["requested_url"] == "https://Example.COM/Doc?x=1"
    assert attempt["canonical_url"] == "https://example.com/doc"
    assert attempt["final_url"] is None
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == error_code
    assert attempt["fetched_at"] == "2024-01-01T00:00:00Z"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == error_code
    assert job_statuses[-1][3]["message"] == "URL download failed"
    assert job_statuses[-1][3]["stage"] == SourceStatus.PROCESSING.value


def test_url_parser_failure_reaches_failed_with_sanitized_error(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise DocprepError("PARSE_FAILED", f"parser exploded at /secret/{source_path}")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "PARSE_FAILED"
    assert upserts[-1].last_error_message == "Document preprocessing failed"
    assert "/secret" not in upserts[-1].last_error_message
    assert upserts[-1].content_hash is None
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"] is None
    attempt = metadata["latest_attempt"]
    assert attempt["job_id"] == "job-url-1"
    assert attempt["requested_url"] == "https://Example.COM/Doc?x=1"
    assert attempt["canonical_url"] == "https://example.com/doc"
    assert attempt["final_url"] == "https://example.com/doc"
    assert attempt["sha256"] == "sha-abc"
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == "PARSE_FAILED"
    assert job_statuses[-1][3]["code"] == "PARSE_FAILED"
    assert job_statuses[-1][3]["message"] == "Document preprocessing failed"


def test_url_normalization_failure_reaches_failed_with_sanitized_error(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise DocprepError("NORMALIZATION_FAILED", "normalizer exploded at /secret/output")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "NORMALIZATION_FAILED"
    assert upserts[-1].content_hash is None
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"] is None
    assert metadata["latest_attempt"]["sha256"] == "sha-abc"
    assert metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.FAILED.value
    assert metadata["latest_attempt"]["error_code"] == "NORMALIZATION_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "NORMALIZATION_FAILED"
    assert job_statuses[-1][3]["message"] == "Document preprocessing failed"


def test_url_lightrag_failure_reaches_failed_with_sanitized_error(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FailingAdapter:
        def ingest_markdown(self, markdown_path, *, source_key):
            raise LightRAGAdapterError(
                "LIGHTRAG_INGESTION_FAILED",
                "C[3/3]: doc-1-chunk-001: extract LLM func: "
                "Worker execution timeout after 360s /secret/socket",
                retryable=True,
            )

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FailingAdapter(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "LIGHTRAG_INGESTION_FAILED"
    assert upserts[-1].last_error_message == "LightRAG ingestion failed"
    assert upserts[-1].content_hash is None
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"] is None
    assert metadata["latest_attempt"]["sha256"] == "sha-abc"
    assert metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.FAILED.value
    assert metadata["latest_attempt"]["error_code"] == "LIGHTRAG_INGESTION_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3] == {
        "code": "LIGHTRAG_INGESTION_FAILED",
        "message": "LightRAG ingestion failed",
        "stage": "INGESTING",
    }


def test_url_storage_parse_failure_reaches_failed_with_sanitized_error(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    class ExplodingStorageReader:
        def snapshot(self):
            raise StorageParseError("storage exploded with /secret/socket details")

    audit_calls = []
    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FakeAdapter(),
        audit_runner=audit_runner,
        storage_reader=ExplodingStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert audit_calls == []
    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "AUDIT_PARSE_FAILED"
    assert upserts[-1].content_hash is None
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"] is None
    assert metadata["latest_attempt"]["sha256"] == "sha-abc"
    assert metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.FAILED.value
    assert metadata["latest_attempt"]["error_code"] == "AUDIT_PARSE_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "AUDIT_PARSE_FAILED"
    assert "/secret" not in job_statuses[-1][3]["message"]
    assert "/secret" not in upserts[-1].last_error_message


def test_url_retry_after_parser_failure_downloads_and_completes(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n\nsome body\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    attempts = {"count": 0}

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise DocprepError("PARSE_FAILED", "transient parser failure")
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    job2 = dict(job, job_id="job-url-2")
    jobs_by_id = {"job-url-1": job, "job-url-2": job2}

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: jobs_by_id[job_id])
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FakeAdapter(),
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].content_hash is None
    assert upserts[-1].source_metadata["active_download"] is None
    assert upserts[-1].source_metadata["latest_attempt"]["error_code"] == "PARSE_FAILED"

    service.process_job("job-url-2", requested_url="https://Example.COM/Doc?x=1")

    assert downloader.calls == [
        ("https://Example.COM/Doc?x=1", root / "url-artifacts"),
        ("https://Example.COM/Doc?x=1", root / "url-artifacts"),
    ]
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == "sha-abc"
    assert upserts[-1].source_metadata["active_download"]["sha256"] == "sha-abc"
    assert upserts[-1].source_metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.PROCESSED.value
    job2_statuses = [status for jid, status, _, _ in job_statuses if jid == "job-url-2"]
    assert job2_statuses[-1] == SourceStatus.PROCESSED
    assert not any(status == SourceStatus.DISCOVERED for status in job2_statuses)


def test_url_same_url_unchanged_content_skips_and_refreshes_metadata(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(
        tmp_path,
        sha256="old-hash",
        fetched_at="2024-02-02T00:00:00Z",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    class NoWorkAdapter:
        def delete_document(self, document_id):
            raise AssertionError("delete must not run for unchanged content")

        def ingest_markdown(self, markdown_path, *, source_key):
            raise AssertionError("ingest must not run for unchanged content")

    class NoSnapshotReader:
        def snapshot(self):
            raise AssertionError("storage snapshot must not run for unchanged content")

    def exploding_audit_runner(**kwargs):
        raise AssertionError("audit must not run for unchanged content")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise AssertionError("normalization must not run for unchanged content")

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=NoWorkAdapter(),
        audit_runner=exploding_audit_runner,
        storage_reader=NoSnapshotReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert downloader.calls == [
        ("https://Example.COM/Doc?x=1", root / "url-artifacts")
    ]
    assert len(upserts) == 1
    refreshed = upserts[0]
    assert refreshed.status == SourceStatus.PROCESSED
    assert refreshed.content_hash == "old-hash"
    assert refreshed.lightrag_document_id == "doc-old"
    assert refreshed.normalized_markdown_path == str(old_md)
    assert refreshed.normalized_json_path == str(old_json)
    metadata = refreshed.source_metadata
    assert metadata["active_download"]["sha256"] == "old-hash"
    assert metadata["active_download"]["etag"] == '"abc"'
    assert metadata["active_download"]["fetched_at"] == "2024-02-02T00:00:00Z"
    attempt = metadata["latest_attempt"]
    assert attempt["job_id"] == "job-url-1"
    assert attempt["terminal_outcome"] == SourceStatus.SKIPPED_DUPLICATE.value
    assert attempt["error_code"] is None
    assert [status for _, status, _, _ in job_statuses] == [
        SourceStatus.PROCESSING,
        SourceStatus.SKIPPED_DUPLICATE,
    ]


def test_url_same_url_changed_content_clean_audit_activates_candidate(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(
        tmp_path,
        final_url="https://example.com/redirected",
        sha256="sha-new",
        fetched_at="2024-02-02T00:00:00Z",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    handoff_calls: list[dict] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        handoff_calls.append(
            {
                "source_path": Path(source_path),
                "source_identity": source_identity,
                "source_type": source_type,
                "native_metadata": native_metadata,
            }
        )
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    events: list[tuple] = []

    class StagedAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            events.append(("delete", document_id))

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            events.append(("ingest", str(path), source_key))
            document_id = "doc-candidate-" + source_key.rsplit("#candidate-", 1)[-1][:8]
            return LightRAGIngestionResult(
                track_id=f"track-{document_id}",
                document_id=document_id,
                status="processed",
            )

    adapter = StagedAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    def audit_runner(**kwargs):
        audit_calls.append(kwargs)
        events.append(("audit", kwargs["lightrag_document_id"]))
        return report

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert downloader.calls == [
        ("https://Example.COM/Doc?x=1", root / "url-artifacts")
    ]
    # The candidate is ingested under a distinct staging identity while the
    # old document still exists; the old document is deleted only after the
    # candidate audit completes cleanly.
    staging_source_key = events[0][2]
    candidate_document_id = "doc-candidate-" + staging_source_key.rsplit("#candidate-", 1)[-1][:8]
    assert events[0][0] == "ingest"
    assert staging_source_key.startswith(active.source_key + "#candidate-")
    assert events[1] == ("audit", candidate_document_id)
    assert events[2] == ("delete", "doc-old")
    assert candidate_document_id != "doc-old"
    assert adapter.deleted == ["doc-old"]
    assert adapter.ingested == [new_md]
    assert len(upserts) == 1
    candidate = upserts[0]
    assert candidate.status == SourceStatus.PROCESSED
    assert candidate.content_hash == "sha-new"
    assert candidate.source_uri == "https://example.com/doc"
    assert candidate.lightrag_document_id == candidate_document_id
    assert candidate.normalized_markdown_path == str(new_md)
    metadata = candidate.source_metadata
    assert metadata["active_download"]["sha256"] == "sha-new"
    assert metadata["active_download"]["canonical_url"] == "https://example.com/doc"
    assert metadata["active_download"]["final_url"] == "https://example.com/redirected"
    assert metadata["active_download"]["fetched_at"] == "2024-02-02T00:00:00Z"
    assert metadata["latest_attempt"]["job_id"] == "job-url-1"
    assert metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.PROCESSED.value
    assert metadata["latest_attempt"]["error_code"] is None
    assert [status for _, status, _, _ in job_statuses] == [
        SourceStatus.PROCESSING,
        SourceStatus.NORMALIZED,
        SourceStatus.INGESTING,
        SourceStatus.AUDITING,
        SourceStatus.PROCESSED,
    ]
    assert job_statuses[-1][1] == SourceStatus.PROCESSED
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert audit_calls[0]["lightrag_document_id"] == candidate_document_id
    assert audit_calls[0]["source_key"] == active.source_key
    assert audit_calls[0]["job_id"] == "job-url-1"
    assert storage_reader.calls == 1
    assert handoff_calls[0]["source_identity"] == "https://example.com/doc"
    assert handoff_calls[0]["source_type"] == "html"


def test_url_same_url_changed_content_ingest_failure_keeps_old_active_without_delete(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(
        tmp_path,
        sha256="sha-new",
        fetched_at="2024-02-02T00:00:00Z",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class FailingIngestAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                raise LightRAGAdapterError(
                    "LIGHTRAG_INGESTION_FAILED",
                    "new ingestion failed",
                    retryable=True,
                )
            raise AssertionError("old artifact must not be re-ingested when candidate ingestion fails")

    adapter = FailingIngestAdapter()

    class NoSnapshotReader:
        def snapshot(self):
            raise AssertionError("storage snapshot must not run when ingestion fails")

    def exploding_audit_runner(**kwargs):
        raise AssertionError("audit must not run when ingestion fails")

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=exploding_audit_runner,
        storage_reader=NoSnapshotReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # The old document is never deleted before a successful candidate ingest;
    # a pre-ingestion failure leaves it completely untouched.
    assert adapter.deleted == []
    assert adapter.ingested == [new_md]
    assert len(upserts) == 1
    kept = upserts[0]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.normalized_markdown_path == str(old_md)
    assert kept.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = kept.source_metadata["latest_attempt"]
    assert attempt["job_id"] == "job-url-1"
    assert attempt["sha256"] == "sha-new"
    assert attempt["fetched_at"] == "2024-02-02T00:00:00Z"
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == "LIGHTRAG_INGESTION_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "LIGHTRAG_INGESTION_FAILED"
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert not any(rec.content_hash == "sha-new" for rec in upserts)


def test_url_same_url_changed_content_failed_audit_keeps_old_active_and_cleans_candidate(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(
        tmp_path,
        sha256="sha-new",
        fetched_at="2024-02-02T00:00:00Z",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class StagedAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(
                    track_id="track-new",
                    document_id="doc-new",
                    status="processed",
                )
            raise AssertionError("old artifact must not be re-ingested on failed candidate audit")

    adapter = StagedAdapter()
    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # Critical audit: the rejected candidate is deleted, the old document and
    # its activation are untouched, and no old-artifact restore runs.
    assert adapter.deleted == ["doc-new"]
    assert "doc-old" not in adapter.deleted
    assert adapter.ingested == [new_md]
    assert len(upserts) == 1
    kept = upserts[0]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.parser == "html"
    assert kept.normalized_markdown_path == str(old_md)
    assert kept.normalized_json_path == str(old_json)
    assert kept.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = kept.source_metadata["latest_attempt"]
    assert attempt["job_id"] == "job-url-1"
    assert attempt["sha256"] == "sha-new"
    assert attempt["terminal_outcome"] == SourceStatus.FAILED_AUDIT.value
    assert attempt["error_code"] == "AUDIT_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert job_statuses[-1][3]["code"] == "AUDIT_FAILED"
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert not any(rec.content_hash == "sha-new" for rec in upserts)
    assert audit_calls[0]["lightrag_document_id"] == "doc-new"


@pytest.mark.parametrize("candidate_id", [None, "", "   "])
def test_url_update_candidate_missing_document_id_fails_sanitized_and_preserves_active(
    tmp_path, monkeypatch, candidate_id
):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(
        tmp_path,
        sha256="sha-new",
        fetched_at="2024-02-02T00:00:00Z",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class NoIdAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(
                track_id="track-new",
                document_id=candidate_id,
                status="processed",
            )

    adapter = NoIdAdapter()

    class NoSnapshotReader:
        def snapshot(self):
            raise AssertionError("storage snapshot must not run without a candidate ID")

    def exploding_audit_runner(**kwargs):
        raise AssertionError("audit must not run without a candidate ID")

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=exploding_audit_runner,
        storage_reader=NoSnapshotReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # The old document is never deleted and the active activation stays valid.
    assert adapter.deleted == []
    assert adapter.ingested == [new_md]
    kept = upserts[-1]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.normalized_markdown_path == str(old_md)
    assert kept.normalized_json_path == str(old_json)
    assert kept.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = kept.source_metadata["latest_attempt"]
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == "LIGHTRAG_DOCUMENT_ID_MISSING"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "LIGHTRAG_DOCUMENT_ID_MISSING"
    assert job_statuses[-1][3]["message"] == "LightRAG did not return a valid document ID"
    assert job_statuses[-1][3]["stage"] == SourceStatus.INGESTING.value
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert not any(rec.content_hash == "sha-new" for rec in upserts)


def test_url_update_candidate_same_document_id_fails_without_deleting_active(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(
        tmp_path,
        sha256="sha-new",
        fetched_at="2024-02-02T00:00:00Z",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class SameIdAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            return LightRAGIngestionResult(
                track_id="track-restore" if path == old_md else "track-new",
                document_id="doc-old",
                status="processed",
            )

    adapter = SameIdAdapter()

    class NoSnapshotReader:
        def snapshot(self):
            raise AssertionError("storage snapshot must not run with a conflicting candidate ID")

    def exploding_audit_runner(**kwargs):
        raise AssertionError("audit must not run with a conflicting candidate ID")

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=exploding_audit_runner,
        storage_reader=NoSnapshotReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # The candidate returned the active document ID: never delete that ID.
    # Re-ingest the preserved old artifact instead, because the candidate may
    # already have replaced the active remote content under the shared ID.
    assert adapter.deleted == []
    assert adapter.ingested == [new_md, old_md]
    kept = upserts[-1]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.normalized_markdown_path == str(old_md)
    assert kept.normalized_json_path == str(old_json)
    assert kept.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = kept.source_metadata["latest_attempt"]
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == "LIGHTRAG_DOCUMENT_ID_CONFLICT"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "LIGHTRAG_DOCUMENT_ID_CONFLICT"
    assert job_statuses[-1][3]["message"] == "LightRAG returned a document ID that is already active"
    assert job_statuses[-1][3]["stage"] == SourceStatus.INGESTING.value
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert not any(rec.content_hash == "sha-new" for rec in upserts)


def test_url_same_url_changed_content_candidate_cleanup_failure_is_stable(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path, sha256="sha-new")
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class CleanupFailingAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            if document_id == "doc-new":
                raise LightRAGAdapterError(
                    "LIGHTRAG_DELETE_FAILED",
                    "cleanup exploded at /secret/socket",
                    retryable=True,
                )

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-new",
                document_id="doc-new",
                status="processed",
            )

    storage_reader = _FakeStorageReader()
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_calls = []
    audit_runner = _make_fake_audit_runner(audit_calls, report)
    adapter = CleanupFailingAdapter()

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # Cleanup was attempted on the candidate only; the old document stays
    # active and the job reaches a stable terminal state.
    assert adapter.deleted == ["doc-new"]
    assert "doc-old" not in adapter.deleted
    kept = upserts[-1]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = kept.source_metadata["latest_attempt"]
    assert attempt["terminal_outcome"] == SourceStatus.FAILED_AUDIT.value
    assert attempt["error_code"] == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][2] == report.model_dump(mode="json")
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert "/secret" not in job_statuses[-1][3]["message"]
    assert "socket" not in job_statuses[-1][3]["message"]
    assert kept.last_error_message != "cleanup exploded at /secret/socket"


def test_url_same_url_changed_content_final_source_persistence_failure_compensates(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path, sha256="sha-new")
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class RestoringAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(
                    track_id="track-new",
                    document_id="doc-new",
                    status="processed",
                )
            return LightRAGIngestionResult(
                track_id="track-restore",
                document_id="doc-restored",
                status="processed",
            )

    adapter = RestoringAdapter()
    storage_reader = _FakeStorageReader()
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_calls = []
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    def failing_upsert(rec):
        if rec.status == SourceStatus.PROCESSED and rec.content_hash == "sha-new":
            raise RuntimeError("secret /tmp/leak during final persistence")
        upserts.append(rec.model_copy(deep=True))

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", failing_upsert)
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # The candidate was deleted and the preserved old normalized artifact was
    # re-ingested to compensate for the failed final source persistence.
    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md, old_md]
    restored = upserts[-1]
    assert restored.status == SourceStatus.PROCESSED
    assert restored.content_hash == "old-hash"
    assert restored.lightrag_document_id == "doc-restored"
    assert restored.normalized_markdown_path == str(old_md)
    assert restored.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = restored.source_metadata["latest_attempt"]
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == "INTERNAL_PROCESSING_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "INTERNAL_PROCESSING_FAILED"
    assert job_statuses[-1][3]["message"] == "Internal processing failed"
    assert "/tmp" not in job_statuses[-1][3]["message"]
    assert "secret" not in job_statuses[-1][3]["message"]
    assert not any(rec.content_hash == "sha-new" for rec in upserts)


def test_url_same_url_changed_content_final_job_persistence_failure_compensates(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path, sha256="sha-new")
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class RestoringAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(
                    track_id="track-new",
                    document_id="doc-new",
                    status="processed",
                )
            return LightRAGIngestionResult(
                track_id="track-restore",
                document_id="doc-restored",
                status="processed",
            )

    adapter = RestoringAdapter()
    storage_reader = _FakeStorageReader()
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_calls = []
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    def failing_status(job_id, status, **kwargs):
        if status == SourceStatus.PROCESSED:
            raise RuntimeError("secret /tmp/status-leak during final persistence")
        job_statuses.append((job_id, status, kwargs.get("audit"), kwargs.get("error")))

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(service_module.pg, "set_ingestion_job_status", failing_status)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md, old_md]
    restored = upserts[-1]
    assert restored.status == SourceStatus.PROCESSED
    assert restored.content_hash == "old-hash"
    assert restored.lightrag_document_id == "doc-restored"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "INTERNAL_PROCESSING_FAILED"
    assert job_statuses[-1][3]["message"] == "Internal processing failed"
    assert "/tmp" not in job_statuses[-1][3]["message"]
    assert not any(status == SourceStatus.AUDITING for _, status, _, _ in job_statuses[-1:])


def test_url_same_url_changed_content_compensation_rollback_failure(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    old_md.unlink()
    download_result = _make_download_result(tmp_path, sha256="sha-new")
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class Adapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(
                track_id="track-new",
                document_id="doc-new",
                status="processed",
            )

    adapter = Adapter()
    storage_reader = _FakeStorageReader()
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_calls = []
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    def failing_upsert(rec):
        if rec.status == SourceStatus.PROCESSED and rec.content_hash == "sha-new":
            raise RuntimeError("secret /tmp/leak during final persistence")
        upserts.append(rec.model_copy(deep=True))

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(service_module.pg, "upsert_ingestion_source", failing_upsert)
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md]
    failed_record = upserts[-1]
    assert failed_record.status == SourceStatus.FAILED
    assert failed_record.last_error_code == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert "/tmp" not in job_statuses[-1][3]["message"]


def test_url_different_url_same_hash_skips_without_implying_activation(tmp_path, monkeypatch):
    root, _, _ = _make_url_fixture(tmp_path)
    new_record = SourceRecord(
        source_key="url:https://example.org/mirror",
        source_kind="url",
        source_uri="https://example.org/mirror",
        content_hash=None,
        status=SourceStatus.DISCOVERED,
        source_metadata={"active_download": None, "latest_attempt": None},
    )
    new_job = {
        "job_id": "job-url-mirror",
        "source_key": new_record.source_key,
        "source_uri": new_record.source_uri,
        "status": SourceStatus.DISCOVERED.value,
        "content_hash": None,
        "lightrag_document_id": None,
        "audit": None,
        "error": None,
    }
    owner = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash="sha-abc",
        status=SourceStatus.PROCESSED,
        parser="html",
        parser_version="docprep-0.3.4",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-owner",
        normalized_markdown_path="normalized/owner/document.md",
        normalized_json_path="normalized/owner/document.json",
    )
    download_result = _make_download_result(
        tmp_path,
        requested_url="https://Example.ORG/Mirror?x=1",
        canonical_url="https://example.org/mirror",
        final_url="https://example.org/mirror",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    lookup_calls: list[str] = []

    def lookup(content_hash):
        lookup_calls.append(content_hash)
        return owner if content_hash == "sha-abc" else None

    class NoWorkAdapter:
        def delete_document(self, document_id):
            raise AssertionError("delete must not run for a content duplicate")

        def ingest_markdown(self, markdown_path, *, source_key):
            raise AssertionError("upload must not run for a content duplicate")

    class NoSnapshotReader:
        def snapshot(self):
            raise AssertionError("storage snapshot must not run for a content duplicate")

    def exploding_audit_runner(**kwargs):
        raise AssertionError("audit must not run for a content duplicate")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise AssertionError("normalization must not run for a content duplicate")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: new_job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: new_record)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=NoWorkAdapter(),
        audit_runner=exploding_audit_runner,
        storage_reader=NoSnapshotReader(),
        downloader=downloader,
    )

    service.process_job("job-url-mirror", requested_url="https://Example.ORG/Mirror?x=1")

    assert downloader.calls == [
        ("https://Example.ORG/Mirror?x=1", root / "url-artifacts")
    ]
    assert lookup_calls == ["sha-abc"]
    duplicate = upserts[-1]
    assert duplicate.source_key == "url:https://example.org/mirror"
    assert duplicate.source_uri == "https://example.org/mirror"
    assert duplicate.content_hash is None
    assert duplicate.status == SourceStatus.SKIPPED_DUPLICATE
    # A cross-URL duplicate never copies parser, normalized-artifact, or
    # LightRAG activation fields: those would imply activation.
    assert duplicate.parser is None
    assert duplicate.parser_version is None
    assert duplicate.normalization_version is None
    assert duplicate.lightrag_document_id is None
    assert duplicate.normalized_markdown_path is None
    assert duplicate.normalized_json_path is None
    metadata = duplicate.source_metadata
    assert metadata["active_download"] is None
    attempt = metadata["latest_attempt"]
    assert attempt["requested_url"] == "https://Example.ORG/Mirror?x=1"
    assert attempt["canonical_url"] == "https://example.org/mirror"
    assert attempt["final_url"] == "https://example.org/mirror"
    assert attempt["sha256"] == "sha-abc"
    assert attempt["raw_artifact_path"] == download_result.raw_artifact_path
    assert attempt["terminal_outcome"] == SourceStatus.SKIPPED_DUPLICATE.value
    assert attempt["error_code"] is None
    assert attempt["job_id"] == "job-url-mirror"
    assert job_statuses[-1][1] == SourceStatus.SKIPPED_DUPLICATE
    # The existing processed owner is untouched.
    assert owner.status == SourceStatus.PROCESSED
    assert owner.content_hash == "sha-abc"
    assert owner.lightrag_document_id == "doc-owner"
    # The owner row is never upserted: only the mirror's own record is written.
    assert all(rec.source_key == "url:https://example.org/mirror" for rec in upserts)


def test_url_cross_url_duplicate_retry_clears_stale_activation_fields(tmp_path, monkeypatch):
    root, _, _ = _make_url_fixture(tmp_path)
    stale_record = SourceRecord(
        source_key="url:https://example.org/mirror",
        source_kind="url",
        source_uri="https://example.org/mirror",
        content_hash=None,
        status=SourceStatus.FAILED_AUDIT,
        parser="html",
        parser_version="docprep-0.3.4",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-stale",
        normalized_markdown_path="normalized/stale/document.md",
        normalized_json_path="normalized/stale/document.json",
        last_error_code="AUDIT_FAILED",
        last_error_message="Post-ingestion audit found critical issues",
        source_metadata={
            "active_download": None,
            "latest_attempt": {
                "requested_url": "https://Example.ORG/Mirror?x=1",
                "canonical_url": "https://example.org/mirror",
                "final_url": "https://example.org/mirror",
                "redirect_chain": [],
                "content_type": "text/html",
                "content_disposition": None,
                "etag": None,
                "last_modified": None,
                "downloaded_bytes": 16,
                "sha256": "sha-owner",
                "raw_artifact_path": "url-artifacts/stale",
                "fetched_at": "2024-01-01T00:00:00Z",
                "job_id": "job-stale",
                "terminal_outcome": SourceStatus.FAILED_AUDIT.value,
                "error_code": "AUDIT_FAILED",
            },
        },
    )
    stale_job = {
        "job_id": "job-url-mirror",
        "source_key": stale_record.source_key,
        "source_uri": stale_record.source_uri,
        "status": SourceStatus.FAILED_AUDIT.value,
        "content_hash": None,
        "lightrag_document_id": "doc-stale",
        "audit": None,
        "error": None,
    }
    owner = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash="sha-owner",
        status=SourceStatus.PROCESSED,
        parser="html",
        parser_version="docprep-0.3.4",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-owner",
        normalized_markdown_path="normalized/owner/document.md",
        normalized_json_path="normalized/owner/document.json",
    )
    download_result = _make_download_result(
        tmp_path,
        requested_url="https://Example.ORG/Mirror?x=1",
        canonical_url="https://example.org/mirror",
        final_url="https://example.org/mirror",
        sha256="sha-owner",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    def lookup(content_hash):
        return owner if content_hash == "sha-owner" else None

    class NoWorkAdapter:
        def delete_document(self, document_id):
            raise AssertionError("delete must not run for a content duplicate")

        def ingest_markdown(self, markdown_path, *, source_key):
            raise AssertionError("upload must not run for a content duplicate")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise AssertionError("normalization must not run for a content duplicate")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: stale_job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: stale_record)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=NoWorkAdapter(),
        audit_runner=None,
        storage_reader=None,
        downloader=downloader,
    )

    service.process_job("job-url-mirror", requested_url="https://Example.ORG/Mirror?x=1")

    duplicate = upserts[-1]
    assert duplicate.status == SourceStatus.SKIPPED_DUPLICATE
    # No activation-derived field may survive the duplicate conversion.
    assert duplicate.content_hash is None
    assert duplicate.parser is None
    assert duplicate.parser_version is None
    assert duplicate.normalization_version is None
    assert duplicate.lightrag_document_id is None
    assert duplicate.normalized_markdown_path is None
    assert duplicate.normalized_json_path is None
    assert duplicate.last_error_code is None
    assert duplicate.last_error_message is None
    # Legitimate duplicate provenance remains: the candidate SHA is recorded
    # only in latest_attempt, and the owner linkage is untouched.
    metadata = duplicate.source_metadata
    assert metadata["active_download"] is None
    attempt = metadata["latest_attempt"]
    assert attempt["sha256"] == "sha-owner"
    assert attempt["terminal_outcome"] == SourceStatus.SKIPPED_DUPLICATE.value
    assert attempt["error_code"] is None
    assert attempt["job_id"] == "job-url-mirror"
    assert job_statuses[-1][1] == SourceStatus.SKIPPED_DUPLICATE
    # The active owner record is never modified.
    assert owner.status == SourceStatus.PROCESSED
    assert owner.content_hash == "sha-owner"
    assert owner.lightrag_document_id == "doc-owner"


def test_url_null_hash_stub_never_collides_as_duplicate(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []
    lookup_calls: list[str] = []

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    storage_reader = _FakeStorageReader()
    audit_calls = []
    report = AuditReport(
        job_id="job-url-1",
        source_key=record.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    audit_runner = _make_fake_audit_runner(audit_calls, report)

    def lookup(content_hash):
        lookup_calls.append(content_hash)
        return None  # a NULL-hash stub can never be a duplicate owner

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: record)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FakeAdapter(),
        audit_runner=audit_runner,
        storage_reader=storage_reader,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert lookup_calls == ["sha-abc"]
    assert all(hash_value is not None for hash_value in lookup_calls)
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == "sha-abc"


def test_url_recrawl_download_failure_keeps_active_and_records_attempt(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    downloader = _FakeDownloader(error=URLDownloadError("URL_TIMEOUT"))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise AssertionError("normalization must not run when the download fails")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=downloader,
        now=lambda: datetime(2024, 2, 2, tzinfo=timezone.utc),
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert downloader.calls == [
        ("https://Example.COM/Doc?x=1", root / "url-artifacts")
    ]
    assert len(upserts) == 1
    kept = upserts[0]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = kept.source_metadata["latest_attempt"]
    assert attempt["job_id"] == "job-url-1"
    assert attempt["requested_url"] == "https://Example.COM/Doc?x=1"
    assert attempt["canonical_url"] == "https://example.com/doc"
    assert attempt["final_url"] is None
    assert attempt["sha256"] is None
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == "URL_TIMEOUT"
    assert attempt["fetched_at"] == "2024-02-02T00:00:00Z"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "URL_TIMEOUT"


@pytest.mark.parametrize(
    "content_type, expected_source_type",
    [
        ("text/html", "html"),
        ("application/xhtml+xml", "html"),
        ("text/html; charset=utf-8", "html"),
        ("text/markdown", "markdown"),
        ("text/x-markdown", "markdown"),
        ("text/plain", "markdown"),
    ],
)
def test_url_source_type_maps_declared_mime_to_parser_type(content_type, expected_source_type):
    result = UrlDownloadResult(
        requested_url="https://example.com/doc",
        canonical_url="https://example.com/doc",
        final_url="https://example.com/doc",
        redirect_chain=[],
        content_type=content_type,
        content_disposition=None,
        etag=None,
        last_modified=None,
        downloaded_bytes=1,
        sha256="sha",
        raw_artifact_path=None,
        fetched_at="2024-01-01T00:00:00Z",
    )

    assert service_module._url_source_type(result) == expected_source_type


def test_url_source_type_rejects_unsupported_mime_even_with_safe_suffix():
    result = UrlDownloadResult(
        requested_url="https://example.com/doc.md",
        canonical_url="https://example.com/doc.md",
        final_url="https://example.com/doc.md",
        redirect_chain=[],
        content_type="image/png",
        content_disposition='attachment; filename="doc.md"',
        etag=None,
        last_modified=None,
        downloaded_bytes=1,
        sha256="sha",
        raw_artifact_path=None,
        fetched_at="2024-01-01T00:00:00Z",
    )

    with pytest.raises(URLDownloadError) as exc:
        service_module._url_source_type(result)

    assert exc.value.code == "URL_CONTENT_TYPE_UNSUPPORTED"


# ---------------------------------------------------------------------------
# Milestone 4 remediation: final background failure boundaries (H2)
# ---------------------------------------------------------------------------


def _assert_generic_failed_job(upserts, job_statuses, stage):
    assert upserts[-1].status == SourceStatus.FAILED
    assert upserts[-1].last_error_code == "INTERNAL_PROCESSING_FAILED"
    assert upserts[-1].last_error_message == "Internal processing failed"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "INTERNAL_PROCESSING_FAILED"
    assert job_statuses[-1][3]["message"] == "Internal processing failed"
    assert job_statuses[-1][3]["stage"] == stage.value
    assert not any(
        status in (SourceStatus.DISCOVERED, SourceStatus.PROCESSING, SourceStatus.AUDITING)
        for _, status, _, _ in job_statuses[-1:]
    )


def test_url_unexpected_normalization_json_loading_failure_is_terminal_and_sanitized(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise RuntimeError("secret /secret/normalized.json parse failed")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    _install_url_job_mocks(monkeypatch, job, record, upserts, job_statuses)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    _assert_generic_failed_job(upserts, job_statuses, SourceStatus.PROCESSING)
    assert "/secret" not in job_statuses[-1][3]["message"]
    assert "RuntimeError" not in job_statuses[-1][3]["message"]
    assert upserts[-1].content_hash is None


def test_url_unexpected_normalization_output_access_failure_is_terminal_and_sanitized(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    class ExplodingNormalized:
        parser = "html"
        warnings: list[str] = []

        @property
        def markdown_path(self):
            raise RuntimeError("secret /secret/markdown-output access failed")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return ExplodingNormalized()

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    _install_url_job_mocks(monkeypatch, job, record, upserts, job_statuses)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    _assert_generic_failed_job(upserts, job_statuses, SourceStatus.PROCESSING)
    assert "/secret" not in job_statuses[-1][3]["message"]


def test_url_unexpected_lightrag_ingestion_failure_is_terminal_and_sanitized(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class ExplodingAdapter:
        def ingest_markdown(self, markdown_path, *, source_key):
            raise RuntimeError("secret /secret/socket lightrag exploded")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    _install_url_job_mocks(monkeypatch, job, record, upserts, job_statuses)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=ExplodingAdapter(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    _assert_generic_failed_job(upserts, job_statuses, SourceStatus.INGESTING)
    assert "/secret" not in job_statuses[-1][3]["message"]
    assert "socket" not in job_statuses[-1][3]["message"]


def test_url_unexpected_storage_snapshot_failure_is_terminal_and_sanitized(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    class ExplodingStorageReader:
        def snapshot(self):
            raise OSError("secret /secret/storage snapshot read failed")

    adapter = FakeAdapter()
    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    _install_url_job_mocks(monkeypatch, job, record, upserts, job_statuses)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        storage_reader=ExplodingStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    _assert_generic_failed_job(upserts, job_statuses, SourceStatus.AUDITING)
    assert "/secret" not in job_statuses[-1][3]["message"]
    assert "storage" not in job_statuses[-1][3]["message"]
    assert adapter.deleted == []


def test_url_unexpected_audit_execution_failure_is_terminal_and_sanitized(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    normalized_md = root / "normalized" / "out" / "document.md"
    normalized_json = root / "normalized" / "out" / "document.json"
    normalized_md.parent.mkdir(parents=True)
    normalized_md.write_text("# Title\n", encoding="utf-8")
    normalized_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=normalized_md.parent,
            markdown_path=normalized_md,
            json_path=normalized_json,
            parser="html",
            warnings=[],
        )

    class FakeAdapter:
        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-url",
                document_id="doc-url",
                status="processed",
            )

    def exploding_audit_runner(**kwargs):
        raise RuntimeError("secret /tmp/audit internals leaked")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    _install_url_job_mocks(monkeypatch, job, record, upserts, job_statuses)
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=FakeAdapter(),
        audit_runner=exploding_audit_runner,
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    _assert_generic_failed_job(upserts, job_statuses, SourceStatus.AUDITING)
    assert "/tmp" not in job_statuses[-1][3]["message"]
    assert "audit" not in job_statuses[-1][3]["message"].lower()


def test_url_update_candidate_cleanup_unexpected_failure_is_stable(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path, sha256="sha-new"))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class CleanupAdapter:
        def __init__(self):
            self.deleted: list[str] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            if document_id == "doc-new":
                raise RuntimeError("secret /secret/cleanup socket exploded")

        def ingest_markdown(self, markdown_path, *, source_key):
            return LightRAGIngestionResult(
                track_id="track-new",
                document_id="doc-new",
                status="processed",
            )

    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    adapter = CleanupAdapter()

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=_make_fake_audit_runner([], report),
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert adapter.deleted == ["doc-new"]
    kept = upserts[-1]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.source_metadata["latest_attempt"]["error_code"] == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert "/secret" not in job_statuses[-1][3]["message"]
    assert "socket" not in job_statuses[-1][3]["message"]


def test_url_update_old_document_deletion_unexpected_failure_compensates(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path, sha256="sha-new"))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class DeleteExplodingAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            if document_id == "doc-old":
                raise RuntimeError("secret /secret/old-delete exploded")

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(
                    track_id="track-new",
                    document_id="doc-new",
                    status="processed",
                )
            return LightRAGIngestionResult(
                track_id="track-restore",
                document_id="doc-restored",
                status="processed",
            )

    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )
    adapter = DeleteExplodingAdapter()

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=_make_fake_audit_runner([], report),
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md, old_md]
    restored = upserts[-1]
    assert restored.status == SourceStatus.PROCESSED
    assert restored.content_hash == "old-hash"
    assert restored.lightrag_document_id == "doc-restored"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "INTERNAL_PROCESSING_FAILED"
    assert job_statuses[-1][3]["message"] == "Internal processing failed"
    assert "/secret" not in job_statuses[-1][3]["message"]


def test_url_update_old_delete_completes_then_raises_triggers_update_compensation(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path, sha256="sha-new"))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class DeleteThenExplodeAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []
            self.remote_documents = {"doc-old"}

        def delete_document(self, document_id):
            # The remote deletion completes and then the call fails: the
            # remote outcome is ambiguous from the caller's perspective.
            self.deleted.append(document_id)
            self.remote_documents.discard(document_id)
            if document_id == "doc-old":
                raise LightRAGAdapterError(
                    "LIGHTRAG_UNAVAILABLE",
                    "LightRAG is unavailable",
                    retryable=True,
                )

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(
                    track_id="track-new",
                    document_id="doc-new",
                    status="processed",
                )
            return LightRAGIngestionResult(
                track_id="track-restore",
                document_id="doc-restored",
                status="processed",
            )

    adapter = DeleteThenExplodeAdapter()
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=_make_fake_audit_runner([], report),
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # The ambiguous delete triggers update-aware compensation: the candidate
    # is cleaned up and the old artifact is re-ingested to restore the old
    # version. The registry is restored to the old activation.
    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md, old_md]
    restored = upserts[-1]
    assert restored.status == SourceStatus.PROCESSED
    assert restored.content_hash == "old-hash"
    assert restored.lightrag_document_id == "doc-restored"
    assert restored.normalized_markdown_path == str(old_md)
    assert restored.normalized_json_path == str(old_json)
    assert restored.source_metadata["active_download"] == active.source_metadata["active_download"]
    attempt = restored.source_metadata["latest_attempt"]
    assert attempt["terminal_outcome"] == SourceStatus.FAILED.value
    assert attempt["error_code"] == "LIGHTRAG_UNAVAILABLE"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "LIGHTRAG_UNAVAILABLE"
    assert job_statuses[-1][3]["message"] == "LightRAG update failed; previous version restored"
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)
    assert not any(rec.content_hash == "sha-new" for rec in upserts)


def test_url_update_old_delete_completes_then_raises_and_restore_failure_rolls_back(tmp_path, monkeypatch):
    root, active, job, old_md, old_json = _make_active_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path, sha256="sha-new"))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    new_md = root / "normalized" / "new" / "document.md"
    new_json = root / "normalized" / "new" / "document.json"
    new_md.parent.mkdir(parents=True)
    new_md.write_text("# New content\n", encoding="utf-8")
    new_json.write_text("{}", encoding="utf-8")

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        return NormalizedDocument(
            output_dir=new_md.parent,
            markdown_path=new_md,
            json_path=new_json,
            parser="html",
            warnings=[],
        )

    class DeleteThenExplodeRestoreFailsAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)
            if document_id == "doc-old":
                raise LightRAGAdapterError(
                    "LIGHTRAG_UNAVAILABLE",
                    "LightRAG is unavailable",
                    retryable=True,
                )

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == new_md:
                return LightRAGIngestionResult(
                    track_id="track-new",
                    document_id="doc-new",
                    status="processed",
                )
            raise LightRAGAdapterError(
                "LIGHTRAG_INGESTION_FAILED",
                "restore ingestion failed",
                retryable=True,
            )

    adapter = DeleteThenExplodeRestoreFailsAdapter()
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "get_processed_ingestion_source_by_hash",
        lambda content_hash: None,
    )
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=adapter,
        audit_runner=_make_fake_audit_runner([], report),
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # Restoration failed: the existing rollback-failure semantics apply and
    # the job never reaches a false PROCESSED state.
    assert adapter.deleted == ["doc-old", "doc-new"]
    assert adapter.ingested == [new_md, old_md]
    failed_record = upserts[-1]
    assert failed_record.status == SourceStatus.FAILED
    assert failed_record.last_error_code == "UPDATE_ROLLBACK_FAILED"
    assert failed_record.last_error_message == "Previous version restore failed"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "UPDATE_ROLLBACK_FAILED"
    assert job_statuses[-1][3]["message"] == "Previous version restore failed"
    assert not any(status == SourceStatus.PROCESSED for _, status, _, _ in job_statuses)


def test_url_persistence_outage_is_logged_and_never_falsely_terminalized(tmp_path, monkeypatch, caplog):
    root, record, job = _make_url_fixture(tmp_path)
    downloader = _FakeDownloader(result=_make_download_result(tmp_path))
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    async def normalize(source_path, *, output_root, source_identity, source_type, native_metadata):
        raise RuntimeError("secret /secret/outage")

    monkeypatch.setattr(service_module, "normalize_downloaded_artifact", normalize)
    _install_url_job_mocks(monkeypatch, job, record, upserts, job_statuses)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: (_ for _ in ()).throw(RuntimeError("database unavailable"))
        if rec.status == SourceStatus.FAILED
        else upserts.append(rec.model_copy(deep=True)),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=root / "normalized",
        lightrag_adapter=None,
        downloader=downloader,
    )

    with caplog.at_level(logging.ERROR, logger="polymerhus.ingestion.service"):
        with pytest.raises(RuntimeError):
            service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # No false terminal: the job was never marked FAILED because persistence
    # was unavailable, and the residual boundary was logged server-side.
    assert not any(status == SourceStatus.FAILED for _, status, _, _ in job_statuses)
    assert any("Could not persist terminal state" in message for message in caplog.messages)
    assert any("Unexpected error processing URL job" in message for message in caplog.messages)


# ---------------------------------------------------------------------------
# Milestone 4 remediation: candidate normalization staging (H1)
# ---------------------------------------------------------------------------


def test_url_update_candidate_normalization_never_overwrites_active_artifact(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    root.mkdir()
    normalized_root = root / "normalized"
    old_raw = b"# Title\n\nBody"
    new_raw = b"# Title\n\nBody\n\n\n"
    assert old_raw != new_raw

    old_artifact = root / "url-artifacts" / "old-artifact"
    old_artifact.parent.mkdir(parents=True)
    old_artifact.write_bytes(old_raw)
    old_normalized = asyncio.run(
        service_module.normalize_downloaded_artifact(
            old_artifact,
            output_root=normalized_root,
            source_identity="https://example.com/doc",
            source_type="markdown",
            native_metadata={
                "canonical_url": "https://example.com/doc",
                "final_url": "https://example.com/doc",
                "http_content_type": "text/plain",
                "sha256": "old-hash",
            },
        )
    )
    old_md = old_normalized.markdown_path
    old_json = old_normalized.json_path
    old_md_bytes = old_md.read_bytes()
    old_json_bytes = old_json.read_bytes()

    active_download = {
        "requested_url": "https://Example.COM/Doc?x=1",
        "canonical_url": "https://example.com/doc",
        "final_url": "https://example.com/doc",
        "redirect_chain": [],
        "content_type": "text/plain",
        "content_disposition": None,
        "etag": '"old-etag"',
        "last_modified": None,
        "downloaded_bytes": len(old_raw),
        "sha256": "old-hash",
        "raw_artifact_path": str(old_artifact),
        "fetched_at": "2024-01-01T00:00:00Z",
    }
    active = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path=str(old_md),
        normalized_json_path=str(old_json),
        source_metadata={
            "active_download": active_download,
            "latest_attempt": {
                **active_download,
                "job_id": "job-url-0",
                "terminal_outcome": SourceStatus.PROCESSED.value,
                "error_code": None,
            },
        },
    )
    job = {
        "job_id": "job-url-1",
        "source_key": active.source_key,
        "source_uri": active.source_uri,
        "status": SourceStatus.PROCESSED.value,
        "content_hash": "old-hash",
        "lightrag_document_id": "doc-old",
        "audit": None,
        "error": None,
    }

    new_artifact = root / "url-artifacts" / "new-artifact"
    new_artifact.write_bytes(new_raw)
    download_result = UrlDownloadResult(
        requested_url="https://Example.COM/Doc?x=1",
        canonical_url="https://example.com/doc",
        final_url="https://example.com/doc",
        redirect_chain=[],
        content_type="text/plain",
        content_disposition=None,
        etag='"new-etag"',
        last_modified=None,
        downloaded_bytes=len(new_raw),
        sha256="new-hash",
        raw_artifact_path=str(new_artifact),
        fetched_at="2024-02-02T00:00:00Z",
    )
    downloader = _FakeDownloader(result=download_result)
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[str, SourceStatus, dict | None, dict | None]] = []

    class StagedAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            self.ingested.append(Path(markdown_path))
            return LightRAGIngestionResult(
                track_id="track-new",
                document_id="doc-new",
                status="processed",
            )

    adapter = StagedAdapter()
    report = AuditReport(
        job_id="job-url-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )

    def no_cross_url_lookup(content_hash):
        raise AssertionError("active URL recrawl must not consult the cross-URL duplicate registry")

    monkeypatch.setattr(service_module.pg, "get_ingestion_job", lambda job_id: job)
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(service_module.pg, "get_processed_ingestion_source_by_hash", no_cross_url_lookup)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append(
            (job_id, status, kwargs.get("audit"), kwargs.get("error"))
        ),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=normalized_root,
        lightrag_adapter=adapter,
        audit_runner=_make_fake_audit_runner([], report),
        storage_reader=_FakeStorageReader(),
        downloader=downloader,
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    # The active artifact and provenance stay byte-for-byte unchanged, and the
    # registry keeps the old paths, metadata, hash, and LightRAG identity.
    assert old_md.read_bytes() == old_md_bytes
    assert old_json.read_bytes() == old_json_bytes
    kept = upserts[-1]
    assert kept.status == SourceStatus.PROCESSED
    assert kept.content_hash == "old-hash"
    assert kept.lightrag_document_id == "doc-old"
    assert kept.normalized_markdown_path == str(old_md)
    assert kept.normalized_json_path == str(old_json)
    assert kept.source_metadata["active_download"] == active.source_metadata["active_download"]
    assert job_statuses[-1][1] == SourceStatus.FAILED_AUDIT
    # The candidate was normalized into a distinct staging directory that was
    # cleaned up after the failed audit; it never overwrote the active dir.
    assert len(adapter.ingested) == 1
    candidate_md = adapter.ingested[0]
    assert candidate_md != old_md
    assert candidate_md.parent.parent.name.startswith("candidate-")
    assert not candidate_md.exists()
    assert not candidate_md.parent.exists()
    assert [p.name for p in normalized_root.iterdir() if p.name.startswith("candidate-")] == []
    assert adapter.deleted == ["doc-new"]
    assert "doc-old" not in adapter.deleted


def test_file_update_candidate_normalization_never_overwrites_active_artifact(tmp_path, monkeypatch):
    root = tmp_path / "ingestion"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    source = inbox / "example.md"
    source.write_text("# Title\n\nBody", encoding="utf-8")
    normalized_root = root / "normalized"

    old_normalized = asyncio.run(
        service_module.normalize_document(source, output_root=normalized_root)
    )
    old_md = old_normalized.markdown_path
    old_json = old_normalized.json_path
    old_md_bytes = old_md.read_bytes()
    old_json_bytes = old_json.read_bytes()

    # Different raw bytes that normalize to the identical Markdown document.
    source.write_text("# Title\n\nBody\n\n\n", encoding="utf-8")

    active = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        parser="markdown",
        normalization_version="lightrag_docprep",
        lightrag_document_id="doc-old",
        normalized_markdown_path=str(old_md),
        normalized_json_path=str(old_json),
    )
    upserts: list[SourceRecord] = []
    job_statuses: list[tuple[SourceStatus, dict | None]] = []

    class UpdateAdapter:
        def __init__(self):
            self.deleted: list[str] = []
            self.ingested: list[Path] = []

        def delete_document(self, document_id):
            self.deleted.append(document_id)

        def ingest_markdown(self, markdown_path, *, source_key):
            path = Path(markdown_path)
            self.ingested.append(path)
            if path == old_md:
                return LightRAGIngestionResult(
                    track_id="track-restore",
                    document_id="doc-restored",
                    status="processed",
                )
            return LightRAGIngestionResult(
                track_id="track-new",
                document_id="doc-new",
                status="processed",
            )

    adapter = UpdateAdapter()
    report = AuditReport(
        job_id="job-1",
        source_key=active.source_key,
        critical_issues=[
            AuditIssue(code="CRIT", message="critical problem", severity="critical", evidence={})
        ],
        warnings=[],
        merge_candidates=[],
        checked_at="2024-01-01T00:00:00Z",
    )

    monkeypatch.setattr(
        service_module.pg,
        "get_ingestion_job",
        lambda job_id: {
            "job_id": job_id,
            "source_key": active.source_key,
            "source_uri": active.source_uri,
            "status": SourceStatus.DISCOVERED.value,
            "content_hash": active.content_hash,
            "lightrag_document_id": active.lightrag_document_id,
            "audit": None,
            "error": None,
        },
    )
    monkeypatch.setattr(service_module.pg, "get_ingestion_source", lambda source_key: active)
    monkeypatch.setattr(
        service_module.pg,
        "upsert_ingestion_source",
        lambda rec: upserts.append(rec.model_copy(deep=True)),
    )
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, **kwargs: job_statuses.append((status, kwargs.get("error"))),
    )
    service = IngestionService(
        ingestion_root=root,
        normalized_root=normalized_root,
        lightrag_adapter=adapter,
        audit_runner=_make_fake_audit_runner([], report),
        storage_reader=_FakeStorageReader(),
    )

    service.process_job("job-1")

    # The active artifact is untouched; the failed audit restores the old
    # activation from the untouched old Markdown.
    assert old_md.read_bytes() == old_md_bytes
    assert old_json.read_bytes() == old_json_bytes
    assert adapter.deleted == ["doc-old", "doc-new"]
    assert len(adapter.ingested) == 2
    candidate_md, restored_md = adapter.ingested
    assert candidate_md != old_md
    assert restored_md == old_md
    assert candidate_md.parent.parent.name.startswith("candidate-")
    assert not candidate_md.exists()
    assert not candidate_md.parent.exists()
    assert [p.name for p in normalized_root.iterdir() if p.name.startswith("candidate-")] == []
    restored = upserts[-1]
    assert restored.status == SourceStatus.PROCESSED
    assert restored.content_hash == "old-hash"
    assert restored.normalized_markdown_path == str(old_md)
    assert restored.normalized_json_path == str(old_json)
    assert job_statuses[-1][0] == SourceStatus.FAILED_AUDIT
    assert job_statuses[-1][1]["code"] == "AUDIT_FAILED"
