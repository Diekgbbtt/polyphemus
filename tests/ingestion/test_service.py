from pathlib import Path

from agent.ingestion.contracts import SourceRecord, SourceStatus
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
