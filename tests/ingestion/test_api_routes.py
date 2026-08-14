import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException

from agent.ingestion.contracts import SourceStatus
from agent.ingestion import routes as ingestion_routes


class FakeService:
    def __init__(self):
        self.submitted = []
        self.jobs = {
            "job-1": {
                "job_id": "job-1",
                "source_key": "file:inbox/example.md",
                "source_uri": "inbox/example.md",
                "status": "PROCESSED",
                "content_hash": "abc123",
                "lightrag_document_id": "doc-1",
                "audit": {"critical_issues": 0, "warnings": 0},
                "error": None,
            }
        }

    def submit(self, *, source_kind, source_uri):
        self.submitted.append((source_kind, source_uri))
        return {
            "job_id": "job-1",
            "source_key": "file:inbox/example.md",
            "status": SourceStatus.DISCOVERED,
            "run_in_background": False,
        }

    def process_job(self, job_id):
        raise AssertionError(f"process_job should not run for fake job {job_id}")

    def get_job(self, job_id):
        return self.jobs.get(job_id)


def test_post_ingestion_returns_job_and_delegates_to_service(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(ingestion_routes, "get_ingestion_service", lambda: service)

    response = asyncio.run(
        ingestion_routes.create_ingestion(
            ingestion_routes.IngestionRequest(
                source_kind="file",
                source_uri="/data/ingestion/inbox/example.md",
            ),
            BackgroundTasks(),
        )
    )

    assert response == {
        "job_id": "job-1",
        "source_key": "file:inbox/example.md",
        "status": "DISCOVERED",
    }
    assert service.submitted == [("file", "/data/ingestion/inbox/example.md")]


def test_get_ingestion_returns_observable_job_status(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(ingestion_routes, "get_ingestion_service", lambda: service)

    response = asyncio.run(ingestion_routes.get_ingestion("job-1"))

    assert response["status"] == "PROCESSED"
    assert response["audit"] == {"critical_issues": 0, "warnings": 0}


def test_get_ingestion_unknown_job_404(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(ingestion_routes, "get_ingestion_service", lambda: service)

    try:
        asyncio.run(ingestion_routes.get_ingestion("missing"))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected HTTPException")


class UrlFakeService:
    def __init__(self):
        self.submitted = []
        self.processed = []

    def submit(self, *, source_kind, source_uri):
        self.submitted.append((source_kind, source_uri))
        return {
            "job_id": "job-url-1",
            "source_key": "url:https://example.com/doc",
            "status": SourceStatus.DISCOVERED,
            "run_in_background": True,
        }

    def process_job(self, job_id, *, requested_url=None):
        self.processed.append((job_id, requested_url))

    def get_job(self, job_id):
        return {}


def test_post_url_ingestion_schedules_background_processing_with_raw_url(monkeypatch):
    service = UrlFakeService()
    monkeypatch.setattr(ingestion_routes, "get_ingestion_service", lambda: service)
    background = BackgroundTasks()

    response = asyncio.run(
        ingestion_routes.create_ingestion(
            ingestion_routes.IngestionRequest(
                source_kind="url",
                source_uri="https://Example.COM/Doc?x=1",
            ),
            background,
        )
    )

    assert response == {
        "job_id": "job-url-1",
        "source_key": "url:https://example.com/doc",
        "status": "DISCOVERED",
    }
    assert service.submitted == [("url", "https://Example.COM/Doc?x=1")]
    assert len(background.tasks) == 1
    task = background.tasks[0]
    assert task.args == ()
    assert task.kwargs == {
        "job_id": "job-url-1",
        "requested_url": "https://Example.COM/Doc?x=1",
    }


def test_post_url_ingestion_rejects_malformed_url_with_400(monkeypatch):
    class RejectingService:
        def submit(self, *, source_kind, source_uri):
            raise ValueError("URL_PORT_FORBIDDEN: Non-default port not allowed for http")

    monkeypatch.setattr(ingestion_routes, "get_ingestion_service", lambda: RejectingService())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingestion_routes.create_ingestion(
                ingestion_routes.IngestionRequest(
                    source_kind="url",
                    source_uri="http://example.com:8080/doc",
                ),
                BackgroundTasks(),
            )
        )

    assert exc.value.status_code == 400
    assert "URL_PORT_FORBIDDEN" in exc.value.detail
