"""Unit predicates for the ported read-only analysis `graph_view` builder.

The builder is the trunk's adjacent-surface read seam (D-A2): the assigner
enumerates BaseURLs and joins their endpoints through it. Pinned here with an
injected `read_fn` (no live graph): the write-shape guard fails closed to the
model, every other failure degrades fail-open, and the success shape is
`{"rows": [...]}`. The FM-E node projection is pinned here too: a returned
whole node reads back as `{labels, properties}`, never an opaque repr.
"""
import json

from polymerhus.analysis.graph_tools import (
    GRAPH_VIEW_CONTRACT,
    ReadOnlyGraphViewError,
    _WRITE_SHAPED,
    build_analysis_exec_tool,
    build_analysis_graph_view_tool,
    build_surface_tools,
)
from polymerhus.recon.domain.types import ExecResult


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


def test_surface_tools_bind_the_exec_tool_for_the_typist_turn():
    """The mechanism-typist's bounded read phase reaches the live target through
    the SAME `exec` term the hunting agents use (the shared `execute_command`
    seam), bound beside the read-only graph view and the HTTP-history pair."""
    tools = build_surface_tools(
        "mechanism_typist", project_id="p1", with_http=True, with_exec=True)
    assert {t.name for t in tools} == {
        "graph_view", "search_http_history", "get_http_artifact", "exec"}


def test_surface_tools_omit_exec_unless_requested():
    """The assigner's turn is read-only (its adjacent-surface phase is bounded
    reading, never probing), so it binds no exec term."""
    tools = build_surface_tools("assigner", project_id="p1", with_http=True)
    assert "exec" not in {t.name for t in tools}


def test_surface_tools_bind_nothing_without_a_project():
    assert build_surface_tools("assigner", project_id=None, with_http=True) == ()


def test_analysis_exec_tool_reuses_the_injected_exec_seam_and_bounds_calls():
    """The analysis exec tool is a THIN wrapper over the hunting exec contract:
    it delegates to the SAME `exec_fn(command, timeout_s)` seam (`default_exec_fn`
    in production) and only adds the per-turn call budget that makes it bounded.
    Past the budget it degrades to a denoted error, never a raise."""
    seen: list[str] = []

    def exec_fn(command, timeout_s):
        seen.append(command)
        return ExecResult(stdout="ok", stderr="", returncode=0, duration_ms=1)

    tool = build_analysis_exec_tool(exec_fn=exec_fn, budget=2)
    assert tool.name == "exec"
    first = json.loads(tool.invoke({"command": "curl -s http://t/a"}))
    assert first["returncode"] == 0 and first["stdout"] == "ok"
    tool.invoke({"command": "curl -s http://t/b"})
    third = json.loads(tool.invoke({"command": "curl -s http://t/c"}))
    assert third.get("error") == "exec_budget_exhausted"
    assert seen == ["curl -s http://t/a", "curl -s http://t/b"], "the seam is not re-hit past budget"


def test_the_exec_tool_build_degrades_fail_open_keeping_the_read_tools(monkeypatch):
    """An unbuildable exec tool must not take the read tools down with it: the
    typist still gets `graph_view` + the HTTP pair, and the turn still runs."""
    import polymerhus.analysis.graph_tools as G

    def boom(**kwargs):
        raise RuntimeError("exec seam unbuildable")

    monkeypatch.setattr(G, "build_analysis_exec_tool", boom)
    tools = G.build_surface_tools(
        "mechanism_typist", project_id="p1", with_http=True, with_exec=True)
    assert {t.name for t in tools} == {
        "graph_view", "search_http_history", "get_http_artifact"}


class _FakeNode(dict):
    """A driver-Node stand-in: a property mapping carrying `labels`."""

    def __init__(self, labels, props):
        super().__init__(props)
        self._labels = frozenset(labels)

    @property
    def labels(self):
        return self._labels


def test_guard_tokens_match_the_hunting_seam():
    from polymerhus.attack.hunting.graph_view_tool import (
        _WRITE_SHAPED as HUNTING_SHAPED,
    )

    assert _WRITE_SHAPED.pattern == HUNTING_SHAPED.pattern


def test_returned_node_projects_to_labels_and_properties():
    node = _FakeNode(["Endpoint"], {"path": "/queue", "method": "GET"})
    tool = build_analysis_graph_view_tool(
        "p", read_fn=lambda cypher, params: [{"s": node}])
    out = tool.invoke({"cypher": "MATCH (s) RETURN s", "params": {}})
    assert out == {"rows": [{"s": {
        "labels": ["Endpoint"],
        "properties": {"path": "/queue", "method": "GET"},
    }}]}


def test_collected_nodes_project_element_wise():
    nodes = [_FakeNode(["Endpoint"], {"path": f"/{i}"}) for i in range(2)]
    tool = build_analysis_graph_view_tool(
        "p", read_fn=lambda cypher, params: [{"items": nodes}])
    out = tool.invoke({"cypher": "MATCH (s) RETURN collect(s) AS items", "params": {}})
    assert [row["items"][0]["labels"] for row in out["rows"]] == [["Endpoint"]]
    assert out["rows"][0]["items"][1]["properties"] == {"path": "/1"}


def test_scalars_and_plain_rows_pass_through():
    rows = [{"method": "GET", "path": "/", "n": 3, "flag": True, "x": None}]
    tool = build_analysis_graph_view_tool(
        "p", read_fn=lambda cypher, params: rows)
    assert tool.invoke({"cypher": "MATCH (s) RETURN s.method", "params": {}}) == {
        "rows": rows}


def test_contract_teaches_return_scalars_not_nodes():
    assert "never a whole node" in GRAPH_VIEW_CONTRACT
    assert "properties(e) AS props" in GRAPH_VIEW_CONTRACT


def test_schema_states_the_endpoint_scoped_header_identity():
    """Operator ruling 2026-10-16: the graph_view schema must state the Header
    identity as {name, endpoint, baseurl} with value/direction as PROPS - the same
    keys `l0_stream.L0_IDENTITY_KEYS` declares, never in drift."""
    from polymerhus.analysis.l0_stream import L0_IDENTITY_KEYS

    assert "Header (name/endpoint/baseurl" in GRAPH_VIEW_CONTRACT
    assert "value/direction" in GRAPH_VIEW_CONTRACT
    # the retired value-in-identity form must be gone
    assert "name/value/baseurl" not in GRAPH_VIEW_CONTRACT
    assert L0_IDENTITY_KEYS["Header"] == ("name", "endpoint", "baseurl")


def test_write_word_inside_a_string_literal_is_allowed():
    """FM-A: the analysis seam reuses the single-sourced strip - `CONTAINS
    'create'` is a legal path filter, not a write."""
    tool = build_analysis_graph_view_tool(
        "p", read_fn=lambda cypher, params: [{"path": "/create"}])
    out = tool.invoke({"cypher": "MATCH (e:Endpoint) WHERE e.path CONTAINS 'create' "
                                 "RETURN e.path LIMIT 50", "params": {}})
    assert out == {"rows": [{"path": "/create"}]}


def test_strip_behavior_matches_the_hunting_seam():
    """FM-A parity: both seams take the same verdict on literal-bearing and
    genuinely write-shaped queries."""
    from polymerhus.attack.hunting.graph_view_tool import build_graph_view_tool

    rows = lambda cypher, params: [{"ok": True}]
    analysis = build_analysis_graph_view_tool("p", read_fn=rows)
    hunting = build_graph_view_tool(rows)
    for query in ("MATCH (e:Endpoint) WHERE e.path CONTAINS 'create' RETURN e.path",
                  "MATCH (n) /* delete me */ RETURN n",
                  "MATCH (n) SET n.x = 1 RETURN n"):
        try:
            analysis.invoke({"cypher": query, "params": {}})
            analysis_verdict = "rows"
        except Exception as exc:  # noqa: BLE001 - verdict comparison only
            analysis_verdict = type(exc).__name__
        try:
            hunting.invoke({"cypher": query, "params": {}})
            hunting_verdict = "rows"
        except Exception as exc:  # noqa: BLE001 - verdict comparison only
            hunting_verdict = type(exc).__name__
        assert analysis_verdict == hunting_verdict == (
            "rows" if "SET n.x" not in query else "ReadOnlyGraphViewError")
