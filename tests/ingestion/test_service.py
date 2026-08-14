from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.ingestion.audit import (
    AuditIssue,
    AuditReport,
    LightRAGStorageReader,
    LightRAGStorageSnapshot,
    StorageParseError,
)
from agent.ingestion.contracts import SourceRecord, SourceStatus
from agent.ingestion.docprep_adapter import DocprepError, NormalizedDocument
from agent.ingestion.lightrag_adapter import LightRAGAdapterError, LightRAGIngestionResult
from agent.ingestion.service import IngestionService
from agent.ingestion import service as service_module
from agent.ingestion.url_downloader import URLDownloadError, UrlDownloadResult


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


def _make_download_result(
    tmp_path,
    *,
    content_type="text/html",
    final_url="https://example.com/doc",
    requested_url="https://Example.COM/Doc?x=1",
):
    artifact = tmp_path / "raw-artifact"
    artifact.write_bytes(b"# Title\n\nsome body\n")
    return UrlDownloadResult(
        requested_url=requested_url,
        canonical_url="https://example.com/doc",
        final_url=final_url,
        redirect_chain=["https://example.com/start"],
        content_type=content_type,
        content_disposition=None,
        etag='"abc"',
        last_modified="Wed, 21 Oct 2026 07:28:00 GMT",
        downloaded_bytes=16,
        sha256="sha-abc",
        raw_artifact_path=str(artifact),
        fetched_at="2024-01-01T00:00:00Z",
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
                "lightrag exploded at /secret/socket",
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
    assert upserts[-1].content_hash is None
    metadata = upserts[-1].source_metadata
    assert metadata["active_download"] is None
    assert metadata["latest_attempt"]["sha256"] == "sha-abc"
    assert metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.FAILED.value
    assert metadata["latest_attempt"]["error_code"] == "LIGHTRAG_INGESTION_FAILED"
    assert job_statuses[-1][1] == SourceStatus.FAILED
    assert job_statuses[-1][3]["code"] == "LIGHTRAG_INGESTION_FAILED"
    assert job_statuses[-1][3]["message"] == "LightRAG ingestion failed"
    assert "/secret" not in job_statuses[-1][3]["message"]


def test_url_storage_parse_failure_reaches_failed_with_sanitized_error(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    download_result = _make_download_result(tmp_path)
    downloader = _FakeDownloader(result=download_result)
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


def test_url_guard_terminalizes_job_when_source_already_has_content(tmp_path, monkeypatch):
    root, record, job = _make_url_fixture(tmp_path)
    record = record.model_copy(
        update={"content_hash": "existing-hash", "status": SourceStatus.PROCESSED}
    )
    downloader = _FakeDownloader()
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
    )

    service.process_job("job-url-1", requested_url="https://Example.COM/Doc?x=1")

    assert downloader.calls == []
    assert upserts == []
    assert len(job_statuses) == 1
    assert job_statuses[0][1] == SourceStatus.FAILED
    assert job_statuses[0][3]["code"] == "URL_SOURCE_ALREADY_ACTIVE"
    assert job_statuses[0][3]["message"] == "URL source already has active content"
    assert job_statuses[0][3]["stage"] == SourceStatus.PROCESSING.value


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
