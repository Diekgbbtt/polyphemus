"""Unit tier: the read-only usage endpoint (`GET /projects/{id}/usage`).

The endpoint is a thin, DATABASE-FREE read of the process-wide usage ledger: an
unknown/empty project returns zeros, never a 404. The app's lifespan reaches
Postgres/Neo4j, which this unit test does not have, so `TestClient(app)` is used
WITHOUT entering it as a context manager (the lifespan never runs)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from polymerhus.app.llm.usage import usage_ledger
from polymerhus.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_ledger():
    usage_ledger().reset()
    yield
    usage_ledger().reset()


def test_usage_returns_totals_and_per_agent_breakdown():
    usage_ledger().record("proj-1", "analyser",
                          {"input_tokens": 10, "output_tokens": 5,
                           "total_tokens": 15})
    usage_ledger().record("proj-1", "triager",
                          {"input_tokens": 1, "output_tokens": 4,
                           "total_tokens": 5})

    resp = client.get("/projects/proj-1/usage")

    assert resp.status_code == 200
    assert resp.json() == {
        "project_id": "proj-1",
        "total_tokens": 20,
        "calls": 2,
        "by_agent": {
            "analyser": {"input_tokens": 10, "output_tokens": 5,
                         "total_tokens": 15, "calls": 1},
            "triager": {"input_tokens": 1, "output_tokens": 4,
                        "total_tokens": 5, "calls": 1},
        },
    }


def test_usage_for_an_empty_project_returns_zeros_and_never_404s():
    resp = client.get("/projects/never-seen/usage")

    assert resp.status_code == 200
    assert resp.json() == {
        "project_id": "never-seen", "total_tokens": 0, "calls": 0,
        "by_agent": {},
    }


def test_usage_endpoint_excludes_the_unscoped_bucket():
    usage_ledger().record(None, "assigner",
                          {"input_tokens": 7, "output_tokens": 1,
                           "total_tokens": 8})
    usage_ledger().record("proj-1", "assigner",
                          {"input_tokens": 2, "output_tokens": 2,
                           "total_tokens": 4})

    body = client.get("/projects/proj-1/usage").json()

    assert body["total_tokens"] == 4
    assert set(body["by_agent"]) == {"assigner"}
