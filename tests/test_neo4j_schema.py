import subprocess
from neo4j import GraphDatabase
from tests.conftest import wait_for
from db.neo4j.init_schema import init_schema

from tests.conftest import neo4j_target

import pytest as _pytest_live

# Applies + asserts the real schema against live Neo4j.
pytestmark = _pytest_live.mark.live_neo4j

# Single source of truth (tests/conftest.py::neo4j_target): env-driven so this
# file works BOTH in-network (bolt://neo4j:7687) and from the host against the
# published port. Was a hardcoded localhost constant, which cannot resolve
# inside the Docker network.
URI, AUTH = neo4j_target()

def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d

def test_neo4j_constraints_applied():
    subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=True)
    driver = wait_for(_driver, timeout=180)
    with driver.session() as s:
        init_schema(s)
        keys = {
            r["name"]: set(r["properties"] or [])
            for r in s.run("SHOW CONSTRAINTS YIELD name, properties")
        }
    names = set(keys)
    assert "endpoint_unique" in names
    assert "observation_unique" in names
    assert "cve_unique" not in names
    assert "vulnerability_unique" not in names
    # The identity reconcile (2026-10-16) must leave the Header key set on the
    # endpoint-scoped identity, never a stale (name, value, baseurl) one.
    assert keys["header_unique"] == {"name", "endpoint", "baseurl", "project_id"}
    driver.close()
