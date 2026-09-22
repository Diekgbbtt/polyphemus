"""Settings deep-merge integration tier - a partial PUT that sets one nested
block must MERGE into the stored settings via jsonb_deep_merge, never wiping
a previously-stored sibling block. This is a live-Postgres behaviour (the
merge is a SQL function), so it needs the docker-compose postgres up.

(#243: rewritten neutral - the role/realm-tagged auth_context example the
blob retirement removed; the merge contract itself is generic and stays.)
"""
import os
import re
import uuid
from pathlib import Path

import pytest


def _candidate_dsns() -> list[str]:
    """Candidate Postgres DSNs to try, in order: the env POSTGRES_DSN (skipping
    conftest's known dummy), then the repo .env value with the docker service host
    swapped for localhost (the compose port is published on :5432)."""
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
        pytest.skip("no reachable Postgres for the settings deep-merge integration test")
    # override the config instance's cached (dummy) DSN so pg uses the live one
    from polymerhus.app.config import config
    config.POSTGRES_DSN = dsn
    from polymerhus.app.clients import pg
    return pg


@pytest.fixture
def project(pg_mod):
    from polymerhus.app.config import config
    import psycopg
    pid = str(uuid.uuid4())
    pg_mod.create_project(pid, "settings-merge")
    yield pid
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM settings WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM projects WHERE project_id = %s", (pid,))


def test_partial_nested_put_preserves_sibling_blocks(pg_mod, project):
    # PUT 1: configure the scope block
    pg_mod.save_settings(project, {"target_domain": "shop.example",
        "scope": {"mode": "wildcard", "exclusions": ["static.example"]}})
    # PUT 2: a partial PUT adding ONLY a notes block
    pg_mod.save_settings(project, {"notes": {"owner": "ops"}})

    settings = pg_mod.load_settings(project)
    # both blocks coexist - the partial notes PUT did NOT wipe the scope sibling
    assert settings["scope"] == {"mode": "wildcard", "exclusions": ["static.example"]}
    assert settings["notes"] == {"owner": "ops"}
    # and the unrelated top-level sibling (target_domain) survived too
    assert settings["target_domain"] == "shop.example"

    # PUT 3: updating one field of scope must not wipe its exclusions sibling
    pg_mod.save_settings(project, {"scope": {"mode": "exact"}})
    scope = pg_mod.load_settings(project)["scope"]
    assert scope["mode"] == "exact"
    assert scope["exclusions"] == ["static.example"]  # sibling field preserved
    assert pg_mod.load_settings(project)["notes"] == {"owner": "ops"}  # untouched
