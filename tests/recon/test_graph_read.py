import os

import pytest

from agent.recon import graph_read


def test_format_builds_nodes_and_links():
    records = [
        {"n": {"element_id": "a", "labels": ["Domain"], "props": {"name": "acme.com"}},
         "m": {"element_id": "b", "labels": ["Subdomain"], "props": {"name": "api.acme.com"}},
         "rtype": "HAS_SUBDOMAIN", "s": "a", "t": "b"},
    ]
    out = graph_read.format_graph_records(records)
    ids = {n["id"] for n in out["nodes"]}
    assert ids == {"a", "b"}
    assert {"source": "a", "target": "b", "type": "HAS_SUBDOMAIN"} in out["links"]
    dom = next(n for n in out["nodes"] if n["id"] == "a")
    assert dom["type"] == "Domain" and dom["name"] == "acme.com"


def test_isolated_node_has_no_links_but_is_present():
    records = [{"n": {"element_id": "x", "labels": ["Domain"], "props": {"name": "lone.com"}},
               "m": None, "rtype": None, "s": None, "t": None}]
    out = graph_read.format_graph_records(records)
    assert [n["id"] for n in out["nodes"]] == ["x"]
    assert out["links"] == []


def test_observation_node_name_uses_macro_kind():
    assert graph_read.node_name(["Observation"], {"macro_kind": "Exposed Admin"}) == "Exposed Admin"


from tests.conftest import neo4j_live


@pytest.mark.skipif(not neo4j_live(), reason="live neo4j not reachable")
def test_fetch_project_graph_includes_isolated_seed():
    from agent.app.clients import neo4j_client
    from agent.recon.graph_read import fetch_project_graph
    pid = "graphtest-" + os.urandom(4).hex()
    neo4j_client.merge(
        "MERGE (n:Domain {name:$name, project_id:$pid})", {"name": "lone.example", "pid": pid})
    g = fetch_project_graph(pid)
    assert any(n["type"] == "Domain" and n["name"] == "lone.example" for n in g["nodes"])
