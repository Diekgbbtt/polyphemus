"""Deep e2e — the app schema round-trips (FK + jsonb) and pgvector actually
does cosine nearest-neighbour over vector(1024). Critical component: postgres only."""
import subprocess, psycopg
from tests.conftest import wait_for

DSN = "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus"

def _vec(values):
    return "[" + ",".join(str(v) for v in values) + "]"

def test_app_schema_and_pgvector_cosine_roundtrip():
    subprocess.run(["docker", "compose", "up", "-d", "postgres"], check=True)
    wait_for(lambda: psycopg.connect(DSN, connect_timeout=3).close() or True, timeout=120)
    # Non-parallel vectors so cosine distance can distinguish them.
    even = _vec([1.0 if i % 2 == 0 else 0.0 for i in range(1024)])   # query + "near"
    odd = _vec([0.0 if i % 2 == 0 else 1.0 for i in range(1024)])    # orthogonal "far"
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        # app schema round-trip: project -> settings(jsonb) with FK
        cur.execute("INSERT INTO projects(project_id, name) VALUES('e2e','E2E') "
                    "ON CONFLICT (project_id) DO NOTHING")
        cur.execute("INSERT INTO settings(project_id, recon) "
                    "VALUES('e2e', '{\"auth_context\": {\"cookies\": []}}'::jsonb) "
                    "ON CONFLICT (project_id) DO UPDATE SET recon = EXCLUDED.recon")
        cur.execute("SELECT recon->'auth_context' FROM settings WHERE project_id='e2e'")
        assert cur.fetchone()[0] is not None
        # doc_chunks vector insert + cosine (<=>) nearest-neighbour
        cur.execute("DELETE FROM doc_chunks WHERE project_id='e2e'")
        cur.execute(
            "INSERT INTO doc_chunks(doc_ref, source_type, anchor, chunk_text, ordinal, "
            "embedding, provenance, project_id) VALUES "
            "('doc:openapi:e2e:1','openapi','{}'::jsonb,'near',0,%s,'{}'::jsonb,'e2e'),"
            "('doc:openapi:e2e:1','openapi','{}'::jsonb,'far',1,%s,'{}'::jsonb,'e2e')",
            (even, odd))
        cur.execute("SELECT chunk_text FROM doc_chunks WHERE project_id='e2e' "
                    "ORDER BY embedding <=> %s LIMIT 1", (even,))
        assert cur.fetchone()[0] == "near"  # cosine-nearest is the matching direction
        cur.execute("DELETE FROM doc_chunks WHERE project_id='e2e'")
        conn.commit()
