import subprocess, psycopg
from tests.conftest import wait_for

DSN = "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus"

def test_postgres_schema():
    subprocess.run(["docker", "compose", "up", "-d", "postgres"], check=True)
    wait_for(lambda: psycopg.connect(DSN, connect_timeout=3).close() or True, timeout=120)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
        assert cur.fetchone() is not None
        for t in ("projects", "settings", "recon_runs", "recon_jobs", "ingest_runs", "doc_chunks"):
            cur.execute("SELECT to_regclass(%s)", (f"public.{t}",))
            assert cur.fetchone()[0] == t, f"missing {t}"
        cur.execute("SELECT indexname FROM pg_indexes WHERE indexname='doc_chunks_hnsw'")
        assert cur.fetchone() is not None
