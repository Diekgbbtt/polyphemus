import asyncio, subprocess, httpx, psycopg
from neo4j import GraphDatabase
from fastmcp import Client
import pytest
from tests.conftest import neo4j_target, wait_for

# Talks to the real stack it just brought up.
pytestmark = pytest.mark.live_neo4j

def test_full_stack_comes_up_and_connects():
    subprocess.run(["docker", "compose", "up", "-d", "--build"], check=True)
    body = wait_for(lambda: httpx.get("http://localhost:8080/health", timeout=3).json(), timeout=600)
    assert body["status"] == "ok"

    async def _roundtrip():
        async with Client("http://localhost:8000/mcp") as c:
            await c.call_tool("execute_command",
                              {"command": "echo persisted > note.txt", "session_id": "smoke-e2e"})
            r = await c.call_tool("execute_command",
                                  {"command": "cat note.txt", "session_id": "smoke-e2e"})
            return r.data
    assert asyncio.run(_roundtrip())["stdout"].strip() == "persisted"

    uri, auth = neo4j_target()
    d = GraphDatabase.driver(uri, auth=auth)
    with d.session() as s:
        names = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name")}
    assert "endpoint_unique" in names
    d.close()

    with psycopg.connect("postgresql://polymerhus:polymerhus@localhost:5432/polymerhus") as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.doc_chunks')")
        assert cur.fetchone()[0] == "doc_chunks"
