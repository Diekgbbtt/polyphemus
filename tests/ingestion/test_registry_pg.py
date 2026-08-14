import json
import re
from pathlib import Path

from agent.app.clients import pg
from agent.ingestion.contracts import SourceRecord, SourceStatus


class FakeCursor:
    def __init__(self, fetch_result=None):
        self.executed: list[tuple[str, tuple | None]] = []
        self._fetch_result = fetch_result

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetch_result

    def fetchall(self):
        return self._fetch_result if self._fetch_result is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def patch_connect(monkeypatch, cursor):
    monkeypatch.setattr(pg.psycopg, "connect", lambda *a, **kw: FakeConn(cursor))
    return cursor


def test_schema_defines_ingestion_sources_and_jobs_tables():
    schema = Path("db/postgres/init.sql").read_text(encoding="utf-8")

    # Isolate the ingestion_sources CREATE TABLE block so the nullability
    # assertion cannot accidentally pass on a substring from another table.
    start = schema.index("CREATE TABLE IF NOT EXISTS ingestion_sources")
    end = schema.find(");", start)
    ingestion_sources_block = schema[start:end + 2]

    assert "CREATE TABLE IF NOT EXISTS ingestion_sources" in schema
    assert "CREATE TABLE IF NOT EXISTS ingestion_jobs" in schema
    assert "source_key TEXT PRIMARY KEY" in schema
    assert "lightrag_document_id TEXT" in schema
    assert "job_id UUID PRIMARY KEY" in schema

    assert "content_hash TEXT" in ingestion_sources_block
    assert re.search(r"content_hash\s+TEXT\s+NOT\s+NULL", ingestion_sources_block) is None


def test_get_ingestion_source_maps_row_to_source_record(monkeypatch):
    row = (
        "file:inbox/example.md",
        "file",
        "inbox/example.md",
        "abc123",
        "PROCESSED",
        {},
        "markdown",
        "markdown-router",
        "docprep-0.3.4",
        "doc-1",
        "normalized/key/document.md",
        "normalized/key/document.json",
        None,
        None,
    )
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=row))

    record = pg.get_ingestion_source("file:inbox/example.md")

    assert record == SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="abc123",
        status=SourceStatus.PROCESSED,
        source_metadata={},
        parser="markdown",
        parser_version="markdown-router",
        normalization_version="docprep-0.3.4",
        lightrag_document_id="doc-1",
        normalized_markdown_path="normalized/key/document.md",
        normalized_json_path="normalized/key/document.json",
        last_error_code=None,
        last_error_message=None,
    )
    query, params = cur.executed[0]
    assert "FROM ingestion_sources" in query
    assert params == ("file:inbox/example.md",)


def test_get_processed_ingestion_source_by_hash_filters_processed_rows(monkeypatch):
    row = (
        "file:inbox/original.md",
        "file",
        "inbox/original.md",
        "abc123",
        "PROCESSED",
        {},
        "markdown",
        "markdown-router",
        "docprep-0.3.4",
        "doc-1",
        "normalized/key/document.md",
        "normalized/key/document.json",
        None,
        None,
    )
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=row))

    record = pg.get_processed_ingestion_source_by_hash("abc123")

    assert record is not None
    assert record.source_key == "file:inbox/original.md"
    assert record.status == SourceStatus.PROCESSED
    query, params = cur.executed[0]
    assert "FROM ingestion_sources" in query
    assert "content_hash = %s" in query
    assert "status = %s" in query
    assert "content_hash IS NOT NULL" in query
    assert params == ("abc123", "PROCESSED")


def test_get_processed_ingestion_source_by_hash_none_returns_none_without_connect(monkeypatch):
    def fail_connect(*args, **kwargs):
        raise AssertionError("database connection should not be opened for None content_hash")

    monkeypatch.setattr(pg.psycopg, "connect", fail_connect)

    result = pg.get_processed_ingestion_source_by_hash(None)

    assert result is None


def test_upsert_ingestion_source_uses_source_key_conflict(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    record = SourceRecord(
        source_key="file:inbox/example.md",
        source_kind="file",
        source_uri="inbox/example.md",
        content_hash="abc123",
        status=SourceStatus.PROCESSED,
    )

    pg.upsert_ingestion_source(record)

    query, params = cur.executed[0]
    assert "INSERT INTO ingestion_sources" in query
    assert "ON CONFLICT (source_key) DO UPDATE" in query
    assert params[:5] == (
        "file:inbox/example.md",
        "file",
        "inbox/example.md",
        "abc123",
        "PROCESSED",
    )


def test_create_ingestion_job_is_idempotent(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())

    pg.create_ingestion_job(
        job_id="11111111-1111-1111-1111-111111111111",
        source_key="file:inbox/example.md",
        status=SourceStatus.DISCOVERED,
    )

    query, params = cur.executed[0]
    assert "INSERT INTO ingestion_jobs" in query
    assert "ON CONFLICT (job_id) DO NOTHING" in query
    assert params == (
        "11111111-1111-1111-1111-111111111111",
        "file:inbox/example.md",
        "DISCOVERED",
    )


def test_get_ingestion_job_returns_observable_status(monkeypatch):
    row = (
        "11111111-1111-1111-1111-111111111111",
        "file:inbox/example.md",
        "inbox/example.md",
        "PROCESSED",
        "abc123",
        "doc-1",
        {"critical_issues": 0, "warnings": 0},
        None,
        None,
    )
    patch_connect(monkeypatch, FakeCursor(fetch_result=row))

    result = pg.get_ingestion_job("11111111-1111-1111-1111-111111111111")

    assert result == {
        "job_id": "11111111-1111-1111-1111-111111111111",
        "source_key": "file:inbox/example.md",
        "source_uri": "inbox/example.md",
        "status": "PROCESSED",
        "content_hash": "abc123",
        "lightrag_document_id": "doc-1",
        "audit": {"critical_issues": 0, "warnings": 0},
        "error": None,
    }


def test_set_ingestion_job_status_serializes_error_and_audit(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())

    pg.set_ingestion_job_status(
        "11111111-1111-1111-1111-111111111111",
        SourceStatus.FAILED,
        error={"code": "PARSE_FAILED", "message": "Could not parse", "stage": "PROCESSING"},
        audit={"critical_issues": 1, "warnings": 0},
    )

    query, params = cur.executed[0]
    assert "UPDATE ingestion_jobs" in query
    assert "finished_at = now()" in query
    assert params[0] == "FAILED"
    assert json.loads(params[1]) == {"critical_issues": 1, "warnings": 0}
    assert json.loads(params[2])["code"] == "PARSE_FAILED"


def test_set_ingestion_job_status_with_failed_audit_is_terminal_and_serializes_audit(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())

    pg.set_ingestion_job_status(
        "11111111-1111-1111-1111-111111111111",
        SourceStatus.FAILED_AUDIT,
        error={"code": "FAILED_AUDIT", "message": "Audit failed", "stage": "AUDITING"},
        audit={"critical_issues": 2, "warnings": 1},
    )

    query, params = cur.executed[0]
    assert "UPDATE ingestion_jobs" in query
    assert "finished_at = now()" in query
    assert params[0] == "FAILED_AUDIT"
    assert json.loads(params[1]) == {"critical_issues": 2, "warnings": 1}
    assert json.loads(params[2])["code"] == "FAILED_AUDIT"


def test_url_stub_source_metadata_round_trip(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    record = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash=None,
        status=SourceStatus.DISCOVERED,
        source_metadata={"active_download": None, "latest_attempt": None},
    )

    pg.upsert_ingestion_source(record)

    query, params = cur.executed[0]
    assert params[4] == "DISCOVERED"  # status still before source_metadata in the tuple
    assert json.loads(params[5]) == {"active_download": None, "latest_attempt": None}


def test_null_content_hash_is_allowed_and_never_picked_by_duplicate_lookup(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    record = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash=None,
        status=SourceStatus.DISCOVERED,
    )

    pg.upsert_ingestion_source(record)

    query, params = cur.executed[0]
    assert params[3] is None


def test_url_migration_executes_same_idempotent_statements_on_repeated_calls(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.apply_url_ingestion_migrations()

    queries = [q for q, _ in cur.executed]
    assert any("ADD COLUMN IF NOT EXISTS source_metadata" in q for q in queries)
    assert any("ALTER COLUMN content_hash DROP NOT NULL" in q for q in queries)

    cur.executed.clear()
    pg.apply_url_ingestion_migrations()
    repeated_queries = [q for q, _ in cur.executed]
    assert repeated_queries == queries


def _record_row(record, source_metadata):
    return (
        record.source_key,
        record.source_kind,
        record.source_uri,
        record.content_hash,
        record.status.value,
        source_metadata,
        record.parser,
        record.parser_version,
        record.normalization_version,
        record.lightrag_document_id,
        record.normalized_markdown_path,
        record.normalized_json_path,
        record.last_error_code,
        record.last_error_message,
    )


def test_url_successful_metadata_round_trips_through_registry(monkeypatch):
    download = {
        "requested_url": "https://Example.COM/Doc?x=1",
        "canonical_url": "https://example.com/doc",
        "final_url": "https://example.com/doc",
        "redirect_chain": ["https://example.com/start"],
        "content_type": "text/html",
        "content_disposition": None,
        "etag": '"abc"',
        "last_modified": "Wed, 21 Oct 2026 07:28:00 GMT",
        "downloaded_bytes": 16,
        "sha256": "sha-abc",
        "raw_artifact_path": "/tmp/raw-artifact",
        "fetched_at": "2024-01-01T00:00:00Z",
    }
    record = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash="sha-abc",
        status=SourceStatus.PROCESSED,
        source_metadata={
            "active_download": download,
            "latest_attempt": {
                **download,
                "job_id": "job-url-1",
                "terminal_outcome": SourceStatus.PROCESSED.value,
                "error_code": None,
            },
        },
    )

    write_cursor = patch_connect(monkeypatch, FakeCursor())
    pg.upsert_ingestion_source(record)

    query, params = write_cursor.executed[0]
    assert "ON CONFLICT (source_key) DO UPDATE" in query
    persisted = json.loads(params[5])
    assert persisted == record.source_metadata

    read_cursor = patch_connect(
        monkeypatch,
        FakeCursor(fetch_result=_record_row(record, persisted)),
    )
    read_back = pg.get_ingestion_source(record.source_key)

    assert read_back.source_metadata == record.source_metadata
    assert read_back.content_hash == "sha-abc"
    assert read_back.status == SourceStatus.PROCESSED
    assert read_back.source_metadata["active_download"]["sha256"] == "sha-abc"
    assert read_back.source_metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.PROCESSED.value
    assert read_back.source_metadata["latest_attempt"]["error_code"] is None


def test_url_rejected_metadata_round_trips_through_registry(monkeypatch):
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
        "raw_artifact_path": "/tmp/old-artifact",
        "fetched_at": "2024-01-01T00:00:00Z",
    }
    rejected_download = {
        "requested_url": "https://Example.COM/Doc?x=1",
        "canonical_url": "https://example.com/doc",
        "final_url": "https://example.com/redirected",
        "redirect_chain": ["https://example.com/start"],
        "content_type": "text/html",
        "content_disposition": None,
        "etag": '"new-etag"',
        "last_modified": "Wed, 21 Oct 2026 07:28:00 GMT",
        "downloaded_bytes": 20,
        "sha256": "sha-new",
        "raw_artifact_path": "/tmp/new-artifact",
        "fetched_at": "2024-02-02T00:00:00Z",
    }
    record = SourceRecord(
        source_key="url:https://example.com/doc",
        source_kind="url",
        source_uri="https://example.com/doc",
        content_hash="old-hash",
        status=SourceStatus.PROCESSED,
        source_metadata={
            "active_download": active_download,
            "latest_attempt": {
                **rejected_download,
                "job_id": "job-url-2",
                "terminal_outcome": SourceStatus.FAILED_AUDIT.value,
                "error_code": "AUDIT_FAILED",
            },
        },
    )

    write_cursor = patch_connect(monkeypatch, FakeCursor())
    pg.upsert_ingestion_source(record)

    _, params = write_cursor.executed[0]
    persisted = json.loads(params[5])
    assert persisted == record.source_metadata

    read_cursor = patch_connect(
        monkeypatch,
        FakeCursor(fetch_result=_record_row(record, persisted)),
    )
    read_back = pg.get_ingestion_source(record.source_key)

    assert read_back.source_metadata == record.source_metadata
    assert read_back.status == SourceStatus.PROCESSED
    assert read_back.content_hash == "old-hash"
    assert read_back.source_metadata["active_download"]["sha256"] == "old-hash"
    assert read_back.source_metadata["latest_attempt"]["sha256"] == "sha-new"
    assert read_back.source_metadata["latest_attempt"]["terminal_outcome"] == SourceStatus.FAILED_AUDIT.value
    assert read_back.source_metadata["latest_attempt"]["error_code"] == "AUDIT_FAILED"
