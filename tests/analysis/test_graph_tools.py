"""Unit predicates for the ported read-only analysis `graph_view` builder.

The builder is the trunk's adjacent-surface read seam (D-A2): the assigner
enumerates BaseURLs and joins their endpoints through it. Pinned here with an
injected `read_fn` (no live graph): the write-shape guard fails closed to the
model, every other failure degrades fail-open, and the success shape is
`{"rows": [...]}`.
"""
from polymerhus.analysis.graph_tools import (
    ReadOnlyGraphViewError,
    build_analysis_graph_view_tool,
    build_surface_tools,
)


def test_write_shaped_cypher_raises_fail_closed():
    tool = build_analysis_graph_view_tool("p1", read_fn=lambda c, p: [])
    try:
        tool.invoke({"cypher": "MATCH (n) MERGE (m) RETURN m", "params": {}})
    except ReadOnlyGraphViewError:
        return
    raise AssertionError("write-shaped cypher must raise, never execute")


def test_read_path_returns_rows_through_the_injected_seam():
    seen = {}

    def read_fn(cypher, params):
        seen.update(params)
        assert "project_id" in params
        return [{"path": "/x"}]

    tool = build_analysis_graph_view_tool("p1", read_fn=read_fn)
    assert tool.invoke({"cypher": "MATCH (e:Endpoint) RETURN e.path LIMIT 1"}) == {
        "rows": [{"path": "/x"}]}
    assert seen["project_id"] == "p1"


def test_read_failure_degrades_fail_open_to_an_error_dict():
    def read_fn(cypher, params):
        raise RuntimeError("store down")

    tool = build_analysis_graph_view_tool("p1", read_fn=read_fn)
    out = tool.invoke({"cypher": "MATCH (e:Endpoint) RETURN e LIMIT 1"})
    assert "error" in out


def test_surface_tools_bind_graph_view_and_the_http_pair_for_the_assigner():
    tools = build_surface_tools("assigner", project_id="p1", with_http=True)
    assert {t.name for t in tools} == {"graph_view", "search_http_history", "get_http_artifact"}


def test_surface_tools_without_a_project_bind_nothing():
    assert build_surface_tools("assigner", project_id=None, with_http=True) == ()
