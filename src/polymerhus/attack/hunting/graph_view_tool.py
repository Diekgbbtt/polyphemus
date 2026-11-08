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
from polymerhus.attack.hunting.read_only_graph import ReadOnlyGraphViewError

# The write-shaped tokens the read-only view refuses, single-sourced here (the
# hunter's old local copy and the orchestrator's `ReadOnlyGraphView._WRITE_SHAPED`
# both derive from this; the view's own guard stays as defense-in-depth).
_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")

# String literals (and comments) blanked before the guard search (FM-A): text
# inside a literal is DATA, not Cypher, so `WHERE e.path CONTAINS 'create'`
# must not trip on the write word. Single quotes allow the `''` and `\`
# escapes, backticks quote identifiers, `//` and `/* */` are comments.
_CYPHER_LITERAL_OR_COMMENT = re.compile(
    r"'(?:[^'\\]|\\.|'')*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|`(?:[^`\\]|\\.)*`"
    r"|//[^\n]*"
    r"|/\*.*?\*/",
    re.DOTALL,
)


def _strip_cypher_for_guard(cypher: str) -> str:
    """Blank literals and comments so the write-shape guard sees code only.

    Single-sourced here; the analysis seam reuses it through a lazy import
    (the parity test pins both). An unbalanced quote is left in place, so a
    malformed query fails closed (refused) rather than slipping through."""
    return _CYPHER_LITERAL_OR_COMMENT.sub(" ", cypher or "")

# The read seam contract: `(cypher, params) -> list[dict]` - the
# `neo4j_client.read` shape that `ReadOnlyGraphView.read` mirrors.
GraphReadFn = Callable[[str, dict], list]


def _schema_surface() -> str:
    """The schema half of the contract, derived from the live enums in
    `analysis/l1_curator.py` so the description cannot drift (#197)."""
    # RETAINED (dormant legacy: nothing writes L1DataItem/data edges after the
    # data-plane removal) -> docs/design/drop-data-modeller.md
    labels_l1 = ", ".join(sorted(L1_ALLOWED_LABELS)) + \
        (" + L1DataItem" if "L1DataItem" in L1_RECONCILE_LABELS else "")
    sys_rels = ", ".join(sorted(SYSTEM_EDGE_RELS))
    return (
        f"SCHEMA: L1 {labels_l1}; L0 Endpoint, Parameter, BaseURL, Header, "
        "Technology, Certificate.\n"
        "Edges: AGGREGATES (L1 service -> L0), SURFACES_AT (L1 data item -> "
        "L0), EVIDENCED_BY (L1 system -> L0), CONSUMES, PRODUCES; system edges "
        f"{sys_rels}.\n"
        "Identity: Service business_function_slug; System kind+discriminator; "
        "Endpoint path/method/baseurl (full URL in url); Parameter "
        "name/position."
    )


_QUERY_PRIMITIVES = (
    "QUERY LANGUAGE (read-only Cypher): MATCH, OPTIONAL MATCH, WHERE, RETURN, "
    "ORDER BY, LIMIT, DISTINCT, labels(), type(), properties(), relationship "
    "patterns, collect(), and $params. Write-shaped tokens (MERGE / CREATE / "
    "DELETE / SET / REMOVE / FOREACH / LOAD CSV) are refused. Text inside a "
    "string is data: always quote your literals, because a write word inside a "
    "literal is legal. Always LIMIT; the view returns no cap."
)

_READ_ONLY_GUARD = "READ-ONLY GUARD: write-shaped cypher is refused."

_RETURN_SHAPE = (
    "RETURN SHAPE: {\"rows\": [...]} on success; {\"error\": ...} on a "
    "fail-open read."
)

_EXAMPLE = (
    "EXAMPLE: MATCH (s:L1Service {business_function_slug:$slug, "
    "project_id:$project_id})-[:AGGREGATES]->(e:Endpoint) RETURN e.url, "
    "e.method, e.path ORDER BY e.path LIMIT 50"
)

# The single usage contract, rendered verbatim into the tool description at
# every binding so no agent receives a divergent contract (#197).
GRAPH_VIEW_CONTRACT = (
    "Read the live L0/L1 graph through the run's read-only view.\n\n"
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
        if _WRITE_SHAPED.search(_strip_cypher_for_guard(cypher).upper()):
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
    "_strip_cypher_for_guard",
    "build_graph_view_tool",
]