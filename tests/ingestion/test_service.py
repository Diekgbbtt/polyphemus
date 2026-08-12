from pathlib import Path

from agent.ingestion.contracts import SourceRecord, SourceStatus
from agent.ingestion.docprep_adapter import NormalizedDocument
from agent.ingestion.lightrag_adapter import LightRAGAdapterError, LightRAGIngestionResult
from agent.ingestion.service import IngestionService
from agent.ingestion import service as service_module


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
    assert adapter.ingested == [new_md]
    assert upserts[-1].status == SourceStatus.PROCESSED
    assert upserts[-1].content_hash == new_hash
    assert upserts[-1].lightrag_document_id == "doc-new"
    assert upserts[-1].normalized_markdown_path == str(new_md)
    assert job_statuses[-1][0] == SourceStatus.PROCESSED


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
