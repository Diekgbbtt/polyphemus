"""#230 (T4) integration tier - the operator seed face against real HTTP and
on-disk state, with a live Postgres for the project-existence gate (the auth
bucket itself is YAML on disk; only project existence needs pg). Live-postgres
posture mirrors `test_auth_roles_merge.py`: probe candidate DSNs, skip cleanly
when none is reachable, override the config DSN, and clean up the rows."""
import os
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polymerhus.app.auth.store import AuthStore
from polymerhus.app.main import app
from polymerhus.project_management import repository

client = TestClient(app)

OVERVIEW = {
    "login_endpoint": "https://app.example.com/login",
    "mechanism": "password",
    "notes": "operator ground truth",
}

ACCOUNT = {
    "credentials": {
        "username": "op@example.com",
        "password": "pw",
        "login_url": "https://app.example.com/login",
    }
}

AGENT_ACCOUNT = {
    "credentials": {
        "username": "agent-minted",
        "password": "pw",
        "login_url": "https://app.example.com/login",
    }
}


def _candidate_dsns() -> list[str]:
    out: list[str] = []
    env_dsn = os.environ.get("POSTGRES_DSN")
    _DUMMY = "postgresql://postgres:postgres@localhost:5432/postgres"  # conftest placeholder
    if env_dsn and env_dsn != _DUMMY:
        out.append(env_dsn)
    env_file = Path(__file__).resolve().parents[2] / ".env"
    try:
        for line in env_file.read_text().splitlines():
            m = re.match(r"\s*POSTGRES_DSN\s*=\s*(.+?)\s*$", line)
            if m:
                out.append(re.sub(r"@postgres:", "@localhost:", m.group(1)))
    except OSError:
        pass
    return out


def _working_dsn() -> str | None:
    import psycopg
    for dsn in _candidate_dsns():
        try:
            psycopg.connect(dsn, connect_timeout=3).close()
            return dsn
        except Exception:  # noqa: BLE001
            continue
    return None


@pytest.fixture(scope="module")
def pg_mod():
    dsn = _working_dsn()
    if not dsn:
        pytest.skip("no reachable Postgres for the auth-seed round-trip integration test")
    from polymerhus.app.config import config
    config.POSTGRES_DSN = dsn
    from polymerhus.app.clients import pg
    return pg


@pytest.fixture
def project(pg_mod):
    from polymerhus.app.config import config
    import psycopg
    pid = str(uuid.uuid4())
    pg_mod.create_project(pid, "auth-seed-roundtrip")
    yield pid
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM settings WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM projects WHERE project_id = %s", (pid,))


@pytest.fixture
def tmp_store(project, tmp_path, monkeypatch):
    """Root the repository's production store at a temp dir: the HTTP face
    below exercises the real YAML bucket on disk."""
    store = AuthStore(root_dir=tmp_path / project)
    monkeypatch.setattr(repository, "_default_auth_store", lambda: store)
    return store


def test_seed_then_read_round_trip_over_http(pg_mod, project, tmp_store):
    put = client.put(f"/projects/{project}/auth",
                     json={"overview": OVERVIEW, "accounts": {"op": ACCOUNT}})
    assert put.status_code == 200
    assert put.json() == {"ok": True}

    got = client.get(f"/projects/{project}/auth")
    assert got.status_code == 200
    body = got.json()
    assert body["overview"] == OVERVIEW
    assert body["accounts"]["op"]["origin"] == "operator"


def test_reseed_replaces_operators_but_preserves_agents(pg_mod, project, tmp_store):
    client.put(f"/projects/{project}/auth",
               json={"overview": OVERVIEW, "accounts": {"op": ACCOUNT}})
    tmp_store.write(project, "accounts.agentbot", AGENT_ACCOUNT, origin="agent")

    reseed = client.put(f"/projects/{project}/auth", json={
        "overview": {**OVERVIEW, "notes": "v2"},
        "accounts": {"op2": ACCOUNT},
    })
    assert reseed.status_code == 200

    body = client.get(f"/projects/{project}/auth").json()
    assert body["overview"]["notes"] == "v2"
    assert set(body["accounts"]) == {"op2", "agentbot"}
    assert body["accounts"]["agentbot"]["origin"] == "agent"
    assert body["accounts"]["agentbot"]["credentials"]["username"] == "agent-minted"

    # a shape violation reseeds nothing: the landed state survives intact
    bad = client.put(f"/projects/{project}/auth",
                     json={"overview": {"bogus": 1}, "accounts": {"op3": ACCOUNT}})
    assert bad.status_code == 400
    assert bad.json() == {
        "ok": False,
        "error": "auth_invalid",
        "detail": "auth_invalid: overview.bogus is not a known overview field",
    }
    assert client.get(f"/projects/{project}/auth").json() == body
