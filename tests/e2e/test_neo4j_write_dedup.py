"""Deep e2e — the graph write path is idempotent on identity (the load-bearing
'identity before dedup, idempotent MERGE' principle). Critical component: neo4j only."""
import subprocess
from neo4j import GraphDatabase
from tests.conftest import wait_for
from db.neo4j.init_schema import init_schema

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")
MERGE = ("MERGE (d:Domain {name:$name, project_id:$pid}) "
         "ON CREATE SET d.first_seen = datetime() "
         "SET d.last_seen = datetime()")

def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d

def test_merge_is_idempotent_on_identity():
    subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=True)
    driver = wait_for(_driver, timeout=180)
    with driver.session() as s:
        init_schema(s)  # constraint must exist for identity-based dedup
        s.run("MATCH (d:Domain {name:$n, project_id:$p}) DETACH DELETE d",
              n="e2e.example.com", p="e2e")
        for _ in range(2):  # two writes of the same identity
            s.run(MERGE, name="e2e.example.com", pid="e2e")
        c = s.run("MATCH (d:Domain {name:$n, project_id:$p}) RETURN count(d) AS c",
                  n="e2e.example.com", p="e2e").single()["c"]
        assert c == 1, f"idempotent MERGE must yield one node, got {c}"
        rec = s.run("MATCH (d:Domain {name:$n, project_id:$p}) "
                    "RETURN d.first_seen AS f, d.last_seen AS l",
                    n="e2e.example.com", p="e2e").single()
        assert rec["f"] is not None and rec["l"] is not None  # provenance stamped
        s.run("MATCH (d:Domain {name:$n, project_id:$p}) DETACH DELETE d",
              n="e2e.example.com", p="e2e")
    driver.close()
