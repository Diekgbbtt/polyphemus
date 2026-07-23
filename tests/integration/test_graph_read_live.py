"""The one LIVE graph_read assertion, moved out of the unit tier (2026-07-22).

It lived in `tests/recon/test_graph_read.py` - the unit tree - gated by
`skipif(not neo4j_live())`. That gate was silently ALWAYS false, because
`neo4j_live()` went through the config-backed client while conftest had filled a
dummy password, so this test never ran at all. Fixing the gate made it run and
immediately trip the unit-tier no-live-database guard, which is how it was
found. It belongs here: it MERGEs into a real graph and reads it back.
"""
import os

import pytest

from tests.conftest import neo4j_live


@pytest.mark.skipif(not neo4j_live(), reason="live neo4j not reachable")
def test_fetch_project_graph_includes_isolated_seed():
    """An isolated seed node (no edges) must still surface in the project graph."""
    from polymerhus.app.clients import neo4j_client
    from polymerhus.recon.domain.graph_read import fetch_project_graph
    pid = "graphtest-" + os.urandom(4).hex()
    neo4j_client.merge(
        "MERGE (n:Domain {name:$name, project_id:$pid})", {"name": "lone.example", "pid": pid})
    g = fetch_project_graph(pid)
    assert any(n["type"] == "Domain" and n["name"] == "lone.example" for n in g["nodes"])
