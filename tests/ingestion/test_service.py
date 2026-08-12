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
