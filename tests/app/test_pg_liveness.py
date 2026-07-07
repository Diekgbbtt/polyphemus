import os
import psycopg
import pytest

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set (live PG)")


def test_recon_runs_has_heartbeat_column_and_status_index():
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='recon_runs' AND column_name='last_heartbeat_at'"
        )
        assert cur.fetchone() is not None, "last_heartbeat_at column missing"
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='recon_runs_status_idx'")
        assert cur.fetchone() is not None, "recon_runs_status_idx missing"
