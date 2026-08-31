"""Unit tier: the single shared read-only L0/L1 `graph_view` tool (#197).

Asserts the ONE-tool contract: `cypher` argument, `{"rows": [...]}` dict
return, the single-sourced `_WRITE_SHAPED` guard, and the single-source usage
contract (schema + query-language primitives + read-only guard + return shape +
worked example) rendered into the description - so no binding receives a
divergent contract. No live target, no LLM, no DB.
"""
from polymerhus.attack.hunting.graph_view_tool import (
    GRAPH_VIEW_CONTRACT,
    _WRITE_SHAPED,
    build_graph_view_tool,
)


def _rows(cypher, params):
    return [{"url": "http://soupmarket.shop/", "method": "GET", "path": "/"}]


def test_tool_name_is_graph_view():
    assert build_graph_view_tool(_rows).name == "graph_view"


def test_tool_takes_cypher_argument_and_returns_rows_dict():
    tool = build_graph_view_tool(_rows)
    out = tool.invoke({"cypher": "MATCH (s) RETURN s LIMIT 5", "params": {}})
    assert out == {"rows": [{"url": "http://soupmarket.shop/", "method": "GET",
                             "path": "/"}]}


def test_absent_seam_degrades_to_error_dict():
    out = build_graph_view_tool(None).invoke(
        {"cypher": "MATCH (s) RETURN s", "params": {}})
    assert "error" in out


def test_raising_seam_degrades_fail_open():
    def boom(cypher, params):
        raise RuntimeError("graph down")

    out = build_graph_view_tool(boom).invoke(
        {"cypher": "MATCH (s) RETURN s", "params": {}})
    assert "error" in out and "graph down" in out["error"]


def test_write_shaped_cypher_raises_read_only_error():
    from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphViewError

    tool = build_graph_view_tool(_rows)
    for query in ("MATCH (u) MERGE (u)-[:X]->(m)",
                  "CREATE (x)",
                  "DELETE x",
                  "SET x.y = 1",
                  "REMOVE x.y",
                  "FOREACH (x IN y | SET x.a = 1)",
                  "LOAD CSV FROM 'file:///x.csv' AS row"):
        try:
            tool.invoke({"cypher": query, "params": {}})
            raise AssertionError(f"write-shaped query not rejected: {query}")
        except ReadOnlyGraphViewError:
            pass


def test_write_guard_precedes_the_absent_seam_check():
    # The read-only guard is defense-in-depth: even with NO seam, write-shaped
    # cypher must be rejected before the absent-seam fail-open fires.
    from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphViewError

    tool = build_graph_view_tool(None)
    try:
        tool.invoke({"cypher": "MATCH (u) MERGE (u)-[:X]->(m)", "params": {}})
        raise AssertionError("write-shaped cypher not rejected without a seam")
    except ReadOnlyGraphViewError:
        pass


def test_read_only_guard_is_case_insensitive():
    from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphViewError

    tool = build_graph_view_tool(_rows)
    try:
        tool.invoke({"cypher": "match (u) merge (u)-[:X]->(m)", "params": {}})
        raise AssertionError("lowercase merge not rejected")
    except ReadOnlyGraphViewError:
        pass


def test_contract_covers_schema_query_primitives_guard_shape_and_example():
    for marker in ("SCHEMA", "L1Service", "L1System", "L1DataItem", "Endpoint",
                   "Parameter", "AGGREGATES", "SURFACES_AT", "EVIDENCED_BY",
                   "PRODUCES", "CONSUMES", "QUERY LANGUAGE", "MATCH",
                   "READ-ONLY GUARD", "RETURN SHAPE", "rows", "EXAMPLE"):
        assert marker in GRAPH_VIEW_CONTRACT, f"contract missing {marker!r}"


def test_contract_derived_from_live_l1_curator_enums():
    # The schema half derives from the canonical enums so it cannot drift.
    from polymerhus.analysis.l1_curator import (
        L1_ALLOWED_LABELS,
        SYSTEM_EDGE_RELS,
    )

    for label in L1_ALLOWED_LABELS:
        assert label in GRAPH_VIEW_CONTRACT
    for rel in ("EXPOSED_VIA", "AUTHENTICATED_BY"):
        assert rel in SYSTEM_EDGE_RELS and rel in GRAPH_VIEW_CONTRACT


def test_single_sourced_write_guard():
    # The guard regex is exported single-source; the old hunter local copy is
    # removed, so this module's `_WRITE_SHAPED` is THE guard (the
    # ReadOnlyGraphView._guard stays as defense-in-depth underneath).
    for token in ("MERGE", "CREATE", "DELETE", "SET", "REMOVE", "FOREACH"):
        assert _WRITE_SHAPED.search(f"{token} (x)")
    assert _WRITE_SHAPED.search("LOAD CSV FROM 'f' AS r")
    assert not _WRITE_SHAPED.search("MATCH (x) RETURN x")


def test_description_carries_the_full_contract():
    desc = build_graph_view_tool(_rows).description
    assert desc == GRAPH_VIEW_CONTRACT or GRAPH_VIEW_CONTRACT in desc
    assert "no graph view configured" not in desc  # contract, not the stub