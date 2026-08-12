from pathlib import Path

import httpx
import pytest

from agent.ingestion.lightrag_adapter import (
    LightRAGAdapterError,
    LightRAGIngestionAdapter,
)


class FakeLightRAGClient:
    def __init__(self, *, upload_responses=None, status_responses=None, delete_responses=None):
        self.upload_responses = list(upload_responses or [])
        self.status_responses = list(status_responses or [])
        self.delete_responses = list(delete_responses or [])
        self.uploaded: list[Path] = []
        self.tracked: list[str] = []
        self.deleted: list[tuple[str, bool]] = []

    def upload_file(self, source_path):
        self.uploaded.append(Path(source_path))
        response = self.upload_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def track_status(self, track_id):
        self.tracked.append(track_id)
        return self.status_responses.pop(0)

    def delete_document(self, doc_id, *, delete_llm_cache=False):
        self.deleted.append((doc_id, delete_llm_cache))
        response = self.delete_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://lightrag/documents/upload")
    response = httpx.Response(code, request=request, json={"detail": "boom"})
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_ingest_markdown_uploads_and_polls_until_processed(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(
        upload_responses=[{"track_id": "track-1"}],
        status_responses=[
            {"status": "processing"},
            {"status": "processed", "document_id": "doc-1"},
        ],
    )
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0, max_poll_attempts=3)

    result = adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert client.uploaded[0].name != "document.md"
    assert client.uploaded[0].name.endswith(".md")
    assert client.tracked == ["track-1", "track-1"]
    assert result.track_id == "track-1"
    assert result.document_id == "doc-1"
    assert result.status == "processed"


def test_ingest_markdown_preserves_canonical_artifact_name(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(
        upload_responses=[{"track_id": "track-1"}],
        status_responses=[{"status": "processed", "document_id": "doc-1"}],
    )
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0, max_poll_attempts=1)

    adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert document.exists()
    assert document.name == "document.md"


def test_ingest_markdown_retries_5xx_upload_once(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(
        upload_responses=[status_error(503), {"track_id": "track-1"}],
        status_responses=[{"status": "processed", "document_id": "doc-1"}],
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=0,
        max_upload_attempts=2,
        max_poll_attempts=1,
    )

    result = adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert len(client.uploaded) == 2
    assert result.document_id == "doc-1"


def test_ingest_markdown_does_not_retry_4xx_upload(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(upload_responses=[status_error(400)])
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0, max_upload_attempts=3)

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert len(client.uploaded) == 1
    assert exc.value.code == "LIGHTRAG_INGESTION_FAILED"
    assert exc.value.retryable is False


def test_ingest_markdown_times_out_if_status_never_terminal(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(
        upload_responses=[{"track_id": "track-1"}],
        status_responses=[{"status": "processing"}, {"status": "processing"}],
    )
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0, max_poll_attempts=2)

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_TIMEOUT"
    assert exc.value.retryable is True


def test_ingest_markdown_maps_failed_status_to_error(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(
        upload_responses=[{"track_id": "track-1"}],
        status_responses=[{"status": "failed", "error": "parse failed"}],
    )
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0, max_poll_attempts=1)

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_INGESTION_FAILED"
    assert exc.value.retryable is False


def test_ingest_markdown_maps_track_status_documents_to_terminal_state(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(
        upload_responses=[{"track_id": "track-1"}],
        status_responses=[
            {
                "track_id": "track-1",
                "documents": [
                    {
                        "id": "doc-1",
                        "status": "processed",
                        "error_msg": None,
                    }
                ],
                "status_summary": {"DocStatus.PROCESSED": 1},
            }
        ],
    )
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0, max_poll_attempts=1)

    result = adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert result.document_id == "doc-1"
    assert result.status == "processed"


def test_ingest_markdown_maps_track_status_document_failure_to_error(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    client = FakeLightRAGClient(
        upload_responses=[{"track_id": "track-1"}],
        status_responses=[
            {
                "track_id": "track-1",
                "documents": [
                    {
                        "id": "doc-1",
                        "status": "failed",
                        "error_msg": "embedding failed",
                    }
                ],
                "status_summary": {"DocStatus.FAILED": 1},
            }
        ],
    )
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0, max_poll_attempts=1)

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(document, source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_INGESTION_FAILED"
    assert "embedding failed" in str(exc.value)


def test_delete_document_uses_selective_delete_with_llm_cache_cleanup():
    client = FakeLightRAGClient(delete_responses=[{"status": "ok"}])
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0)

    result = adapter.delete_document("doc-old")

    assert result == {"status": "ok"}
    assert client.deleted == [("doc-old", True)]


def test_delete_document_maps_4xx_to_nonretryable_error():
    client = FakeLightRAGClient(delete_responses=[status_error(404)])
    adapter = LightRAGIngestionAdapter(client=client, poll_interval_seconds=0)

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.delete_document("missing-doc")

    assert exc.value.code == "LIGHTRAG_DELETE_FAILED"
    assert exc.value.retryable is False
