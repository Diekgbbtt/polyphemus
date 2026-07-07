import os
import uuid

import pytest
from fastapi.testclient import TestClient

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set (live PG)")


@pytest.fixture(scope="module")
def client():
    from agent.app.main import app
    return TestClient(app)


def test_get_projects_lists_created_project(client):
    from agent.app.clients import pg
    pid = str(uuid.uuid4())
    pg.create_project(pid, "list-test")
    r = client.get("/projects")
    assert r.status_code == 200
    ids = [p["project_id"] for p in r.json()["projects"]]
    assert pid in ids
