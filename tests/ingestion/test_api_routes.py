import asyncio

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
