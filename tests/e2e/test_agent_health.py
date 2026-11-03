import subprocess, httpx, psycopg
from tests.conftest import wait_for

DSN = "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus"

def _health():
    r = httpx.get("http://localhost:8080/health", timeout=3)
    r.raise_for_status()
    return r.json()

def test_agent_health_all_backends_ok():
    subprocess.run(["docker", "compose", "up", "-d", "--build",
                    "postgres", "neo4j", "kali", "agent"], check=True)
    body = wait_for(lambda: _health() if _health()["status"] == "ok" else None, timeout=600)
    assert body["checks"] == {"postgres": True, "neo4j": True, "kali_mcp": True}
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.checkpoints')")
        assert cur.fetchone()[0] == "checkpoints"
