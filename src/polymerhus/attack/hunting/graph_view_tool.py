"""The single shared read-only L0/L1 graph-view tool (#197).

The hunting module binds a `graph_view` tool at THREE agent seams - the
orchestrator, the hunting agent, and the test-executor pod (runner + triager).
Before #197 the tool existed in two divergent implementations (the
orchestrator's `@tool graph_view(cypher, params)` and the hunter's
`GraphViewTool(BaseTool)`) that disagreed on the argument name (`cypher` vs
`query`), the return shape (dict vs JSON string), and the guard location.
THIS module is the ONE implementation: `cypher` argument, `{"rows": [...]}`
dict return, a single-sourced write-shape guard, and the usage contract
(schema + query-language primitives + read-only guard + return shape + worked
example) rendered verbatim into the tool's description - so no agent receives a
divergent contract.

Design (operator-locked in the #197 grilling, `docs/design/hunting-tools-design.md`):
- one tool, three bindings; `GraphViewTool` is removed;
- `cypher` arg (matches `ReadOnlyGraphView.read`'s `(cypher, params)`);
- `{"rows": [...]}` dict return; a failure degrades to `{"error": ...}`
  (fail-open, O5) - never a raise into the turn, except the read-only guard,
  which is the ONE raise a caller is allowed to surface to the model;
- the `_WRITE_SHAPED` guard is single-sourced here; `ReadOnlyGraphView._guard`
  stays as defense-in-depth underneath;
- no row caps (operator ruling, #197 Q6) - the contract documents the `LIMIT`
  discipline instead.

Import performs no I/O (CODING_STANDARD section 6): the read seam is injected
by the factory call, never resolved at import.
"""
from __future__ import annotations

import re
from typing import Callable

from langchain_core.tools import tool

from polymerhus.analysis.l1_curator import (
    L1_ALLOWED_LABELS,
    L1_RECONCILE_LABELS,
    SYSTEM_EDGE_RELS,
    _DATA_FLOW_RELS,
)
from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphViewError

# The write-shaped tokens the read-only view refuses, single-sourced here (the
# hunter's old local copy and the orchestrator's `ReadOnlyGraphView._WRITE_SHAPED`
# both derive from this; the view's own guard stays as defense-in-depth).
_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")

# The read seam contract: `(cypher, params) -> list[dict]` - the
# `neo4j_client.read` shape that `ReadOnlyGraphView.read` mirrors.
GraphReadFn = Callable[[str, dict], list]


def _schema_surface() -> str:
    """The schema half of the contract, derived from the live enums in
    `analysis/l1_curator.py` so the description cannot drift (#197)."""
    labels_l1 = ", ".join(sorted(L1_ALLOWED_LABELS)) + \
        (" + L1DataItem" if "L1DataItem" in L1_RECONCILE_LABELS else "")
    sys_rels = ", ".join(sorted(SYSTEM_EDGE_RELS))
    return (
        "SCHEMA - node labels:\n"
        f"- L1 (judged): {labels_l1}\n"
        "- L0 (observed): Endpoint, Parameter, BaseURL, Header\n"
        "relationship types:\n"
        "- cross-layer: AGGREGATES ((:L1Service)-[:AGGREGATES]->(:L0)), "
        "SURFACES_AT ((:L1DataItem)-[:SURFACES_AT]->(:L0)), "
        "EVIDENCED_BY ((:L1System)-[:EVIDENCED_BY]->(:L0))\n"
        f"- data flow: {', '.join(sorted(set(_DATA_FLOW_RELS.values())))}\n"
        f"- System-edge taxonomy: {sys_rels}\n"
        "key identity properties: a Service's `business_function_slug`; a "
        "System's `kind` + `discriminator`; an Endpoint's `path` / `method` / "
        "`baseurl` (full URL in `url`); a Parameter's `name` / `position`."
    )


_QUERY_PRIMITIVES = (
    "QUERY LANGUAGE (read-only Cypher) - you may use: MATCH, OPTIONAL MATCH, "
    "WHERE, RETURN, ORDER BY, LIMIT, DISTINCT, labels(), type(), properties(), "
    "relationship patterns (a)-[:REL]->(b), collect(...), and $param parameters. "
    "Write-shaped tokens (MERGE / CREATE / DELETE / SET / REMOVE / FOREACH / "
    "LOAD CSV) are refused. Always LIMIT: the view returns no cap."
)

_READ_ONLY_GUARD = (
    "READ-ONLY GUARD - write-shaped cypher is rejected (ReadOnlyGraphViewError), "
    "never a write."
)

_RETURN_SHAPE = (
    "RETURN SHAPE - on success {\"rows\": [...]} (a list of plain dict rows); on "
    "an absent/misconfigured/failing view {\"error\": ...} (fail-open)."
)

_EXAMPLE = (
    "EXAMPLE - the observed attack surface of a Service (navigate L1 down to L0):\n"
    "MATCH (s:L1Service {business_function_slug: $slug, project_id: $project_id})\n"
    "MATCH (s)-[:AGGREGATES]->(e:Endpoint)\n"
    "OPTIONAL MATCH (e)-[:HAS_PARAMETER]->(p:Parameter)\n"
    "RETURN e.url, e.method, e.path, collect(p.name) AS parameters\n"
    "ORDER BY e.path LIMIT 50"
)

# The single usage contract, rendered verbatim into the tool description at
# every binding so no agent receives a divergent contract (#197).
GRAPH_VIEW_CONTRACT = (
    "Read the live L0/L1 graph through the run's read-only view: navigate from "
    "the L1 units (Service / System / DataItem) down to the observed L0 attack "
    "surface (Endpoints / Parameters / BaseURLs / Headers) to ground your "
    "reasoning in the target's surface.\n\n"
    f"{_schema_surface()}\n\n"
    f"{_QUERY_PRIMITIVES}\n\n"
    f"{_READ_ONLY_GUARD}\n\n"
    f"{_RETURN_SHAPE}\n\n"
    f"{_EXAMPLE}"
)


def build_graph_view_tool(read_fn: GraphReadFn | None):
    """Build the ONE shared `graph_view` tool bound at all three seams.

    `read_fn` is the read-only seam (`ReadOnlyGraphView(project_id).read` or an
    injected equivalent). Absent -> a fail-open `{"error": ...}` result. The
    contract rides the tool's description verbatim.
    """
    @tool
    def graph_view(cypher: str, params: dict | None = None) -> dict:
        """Placeholder - the real contract is assigned below (the `@tool`
        decorator reads the docstring at decoration time, so the interpolated
        `GRAPH_VIEW_CONTRACT` is set on the returned tool explicitly)."""
        if _WRITE_SHAPED.search(cypher.upper()):
            raise ReadOnlyGraphViewError(
                "the graph view is read-only: refusing write-shaped cypher "
                f"{cypher[:120]!r}"
            )
        if read_fn is None:
            return {"error": "no graph view configured; reading degraded"}
        try:
            rows = read_fn(cypher, params or {})
            if not isinstance(rows, list):
                return {"rows": [rows] if rows is not None else []}
            return {"rows": rows}
        except ReadOnlyGraphViewError:
            raise  # surfaced to the model by the tool runtime - never a write
        except Exception as exc:  # noqa: BLE001 - fail-open (O5)
            return {"error": f"graph_view degraded: {exc}"}

    # The `@tool` decorator snapshots the docstring at decoration; assign the
    # interpolated contract as the description so every binding carries it.
    tool_obj = graph_view
    if hasattr(tool_obj, "description"):
        tool_obj.description = GRAPH_VIEW_CONTRACT
    return tool_obj


__all__ = [
    "GRAPH_VIEW_CONTRACT",
    "GraphReadFn",
    "_WRITE_SHAPED",
    "build_graph_view_tool",
]