import subprocess
from neo4j import GraphDatabase
from tests.conftest import wait_for
from db.neo4j.init_schema import init_schema

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")

def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d

def test_neo4j_constraints_applied():
    subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=True)
    driver = wait_for(_driver, timeout=180)
    with driver.session() as s:
        init_schema(s)
        names = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name")}
    assert "endpoint_unique" in names
    assert "observation_unique" in names
    assert "cve_unique" not in names
    assert "vulnerability_unique" not in names
    driver.close()
