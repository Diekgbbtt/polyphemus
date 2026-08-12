import json
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

    assert "CREATE TABLE IF NOT EXISTS ingestion_sources" in schema
    assert "CREATE TABLE IF NOT EXISTS ingestion_jobs" in schema
    assert "source_key TEXT PRIMARY KEY" in schema
    assert "content_hash TEXT NOT NULL" in schema
    assert "lightrag_document_id TEXT" in schema
    assert "job_id UUID PRIMARY KEY" in schema


def test_get_ingestion_source_maps_row_to_source_record(monkeypatch):
    row = (
        "file:inbox/example.md",
        "file",
        "inbox/example.md",
        "abc123",
        "PROCESSED",
        "markdown",
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
        parser="markdown",
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
