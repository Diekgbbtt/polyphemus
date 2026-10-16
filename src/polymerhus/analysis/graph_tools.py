"""The analysis-proposer tool surface (the read/probe seam).

The mechanism-typist judges a recently-collected chunk slice, and may widen
its view to the slice's neighbourhood to gain a topological understanding of
the services around it. It therefore needs to query the mapped L0 surface
broadly, without assuming asset names, and to confirm an ambiguous ownership
against the recorded request shapes.

Three tools are bound on the typist turn (the constant request shape, the
cache rule):

  * `graph_view` - the read-only L0/L1 Cypher view (broad L0 query);
  * `search_http_history` / `get_http_artifact` - the recorded transaction
    search + fetch (request shapes), for disambiguation, confirmation, and an
    adjacently promising endpoint's fuller response.

The Assigner turn binds ONLY the HTTP-history pair: its `graph_view`
binding is rolled back (the concentration failure it licensed), and the
recorded-transaction read is its whole widening seam, kept central.

The mechanism-typist turn binds the same three plus a bounded `exec`
(`build_analysis_exec_tool`), so its ORIENT / VERIFY phases can witness a
mechanism in the target's real response. The exec tool wraps the hunting `exec`
tool (the SAME `execute_command` execution seam, args schema and tool name);
only its model-facing description and its per-call budget are analysis-local,
so no second tooling stack is built.

`graph_view` is a light analysis-side binding: the write-shape guard and the
read seam live here so the analysis module does not import `attack.hunting` for
it. The HTTP-history tools are the SAME classes the hunting module binds; they
are resolved lazily and reused verbatim so the contracts cannot drift.

Import performs no I/O (CODING_STANDARD section 6); the read seam resolves on call.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from typing import Any, Callable

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

# The write-shaped tokens the read-only view refuses. The same set the hunting
# `graph_view` guards (`attack/hunting/graph_view_tool.py`); kept in step by the
# shared test `tests/analysis/test_graph_tools.py::test_guard_tokens_match`.
_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")

GraphReadFn = Callable[[str, dict], list]


class ReadOnlyGraphViewError(RuntimeError):
    """Raised when write-shaped Cypher reaches the read-only analysis view."""


def _default_read(cypher: str, params: dict) -> list:
    from polymerhus.app.clients import neo4j_client

    return neo4j_client.read(cypher, params)


_SCHEMA = (
    "SCHEMA - node labels:\n"
    "- L1 (judged): L1Service (business_function_slug), L1System (kind + "
    "discriminator)\n"
    "- L0 (observed): Endpoint (path/method/baseurl/url), Parameter "
    "(name/position/endpoint_path/baseurl), BaseURL (url), Header "
    "(name/endpoint/baseurl; value/direction are props), Secret (value_hash), "
    "Observation (triager)\n"
    "relationship types:\n"
    "- cross-layer: AGGREGATES ((:L1Service)-[:AGGREGATES]->(:L0)), EVIDENCED_BY "
    "((:L1System)-[:EVIDENCED_BY]->(:L0))\n"
    "- intra-L1: EXPOSED_VIA, ROUTED_BY, FRONTED_BY, AUTHENTICATED_BY, "
    "AUTHORIZED_BY\n"
    "- L0-internal: HAS_ENDPOINT ((:BaseURL)-[:HAS_ENDPOINT]->(:Endpoint)), "
    "HAS_PARAMETER, HAS_HEADER, HAS_SECRET, HAS_OBSERVATION"
)

_QUERY_PRIMITIVES = (
    "QUERY LANGUAGE (read-only Cypher) - use MATCH, OPTIONAL MATCH, WHERE, "
    "RETURN, ORDER BY, LIMIT, DISTINCT, count(), collect(), labels(), type(). "
    "Scope every query with {project_id: $project_id}. Write-shaped tokens "
    "(MERGE / CREATE / DELETE / SET / REMOVE / FOREACH / LOAD CSV) are refused. "
    "Text inside a string literal is DATA, not Cypher: a path filter that "
    "happens to contain a write word is legal and always allowed "
    "(`WHERE e.path CONTAINS 'create'`) - the guard refuses a write word only "
    "where it stands as a Cypher keyword, so always quote your literals. "
    "Always LIMIT: the view returns no cap. Query BROADLY first (enumerate the "
    "surface) and only then narrow - never assume an asset name."
)

_RETURN_SHAPE = (
    "RETURN SHAPE - on success {\"rows\": [...]} (a list of dict rows); on a "
    "failure {\"error\": ...} (fail-open, never a raise). RETURN scalars or "
    "maps, never a whole node: `RETURN properties(e) AS props, labels(e) AS "
    "labels` reads back as a real row, while `RETURN e` comes back as an "
    "opaque node repr you cannot index. Prefer `RETURN e.method, e.path, "
    "properties(e) AS props`."
)

_EXAMPLE = (
    "EXAMPLE - enumerate the endpoints a BaseURL exposes (broad, no name "
    "assumption):\n"
    "MATCH (b:BaseURL {project_id: $project_id})-[:HAS_ENDPOINT]->(e:Endpoint)\n"
    "OPTIONAL MATCH (e)-[:HAS_PARAMETER]->(p:Parameter)\n"
    "RETURN e.method, e.path, e.url, collect(p.name) AS parameters\n"
    "ORDER BY e.path LIMIT 200"
)

GRAPH_VIEW_CONTRACT = (
    "Read the live L0/L1 graph through the run's read-only view: navigate from "
    "the L1 units down to the observed L0 attack surface to ground your "
    "reasoning in the target's surface.\n\n"
    f"{_SCHEMA}\n\n{_QUERY_PRIMITIVES}\n\n{f'{_RETURN_SHAPE}'}\n\n{_EXAMPLE}"
)


def _project_value(value: Any) -> Any:
    """Project a graph element to a model-readable map (FM-E).

    A returned whole node serializes to an opaque repr
    (`<Node element_id=...>`) the model must scrape, although `_RETURN_SHAPE`
    promises dict rows. Node-likes (a property mapping carrying `labels`,
    which is what the driver returns for `RETURN e`) project to
    `{"labels": [...], "properties": {...}}`; every other mapping projects to
    a plain dict, and lists/tuples project element-wise, so a `collect()`
    of nodes reads back too. Scalars pass through untouched."""
    labels = getattr(value, "labels", None)
    if labels is not None and isinstance(value, Mapping):
        return {
            "labels": sorted(labels),
            "properties": {k: _project_value(v) for k, v in value.items()},
        }
    if isinstance(value, Mapping):
        return {k: _project_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_project_value(v) for v in value]
    return value


def build_analysis_graph_view_tool(project_id: str, *, read_fn: GraphReadFn | None = None):
    """Build the read-only `graph_view` tool for an analysis proposer turn.

    `read_fn(cypher, params) -> list[dict]` is the read seam (defaults to
    `neo4j_client.read`). The write-shape guard is the ONLY raise surfaced to the
    model; every other failure degrades fail-open to `{"error": ...}`.
    """
    read = read_fn or _default_read

    @tool
    def graph_view(cypher: str, params: dict | None = None) -> dict:
        """Placeholder - the contract is assigned below."""
        # The literal/comment stripper is single-sourced on the hunting seam
        # and reused here through a lazy import (this module never imports
        # `attack.hunting` at import time). If the import ever fails the
        # check falls back to the unstripped text: fail-closed, as before.
        try:
            from polymerhus.attack.hunting.graph_view_tool import (
                _strip_cypher_for_guard,
            )
        except Exception:  # noqa: BLE001 - fail-closed on the raw text
            _strip_cypher_for_guard = None
        scanned = _strip_cypher_for_guard(cypher) \
            if _strip_cypher_for_guard is not None else cypher
        if _WRITE_SHAPED.search(scanned.upper()):
            raise ReadOnlyGraphViewError(
                "the graph view is read-only: refusing write-shaped cypher "
                f"{cypher[:120]!r}"
            )
        merged = {"project_id": project_id, **(params or {})}
        try:
            rows = read(cypher, merged)
            if not isinstance(rows, list):
                rows = [rows] if rows is not None else []
            return {"rows": [_project_value(row) for row in rows]}
        except ReadOnlyGraphViewError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail-open
            return {"error": f"graph_view degraded: {exc}"}

    graph_view.description = GRAPH_VIEW_CONTRACT
    return graph_view


def build_http_history_tools(project_id: str):
    """The `search_http_history` / `get_http_artifact` read pair: the
    assigner's whole widening seam and the typist's transaction read.

    The classes and contracts are single-sourced in the hunting module and
    reused verbatim; the default read seams are the app client. Resolved lazily
    so this module imports nothing from `attack.hunting` at import time. Any
    failure to build degrades to `()` (the turn still carries `graph_view`)."""
    try:
        from polymerhus.app.clients.kali_http_history import (
            default_http_get_fn,
            default_http_search_fn,
        )
        from polymerhus.attack.hunting.hunter_tools import (
            HttpHistoryGetTool,
            HttpHistorySearchTool,
        )

        return (
            HttpHistorySearchTool(http_search_fn=default_http_search_fn, project_id=project_id),
            HttpHistoryGetTool(http_get_fn=default_http_get_fn, project_id=project_id),
        )
    except Exception:  # noqa: BLE001 - fail-open: the http pair binds nothing
        return ()


# The mechanism-typist's `exec` contract. It is deliberately NOT the hunter's
# `exec` description: that one is written for a hunting probe agent (the
# partition guard, the spec's replay lineage), and the typist never holds a
# spec. What is shared is the EXECUTION seam - the SAME `exec_fn` the hunter
# binds (in production the pod's `default_exec_fn`, which runs `execute_command`
# through the kali MCP). Only the model-facing contract and the call budget are
# analysis-local; the tooling stack is not rebuilt.
ANALYSIS_EXEC_CONTRACT = (
    "Run a bounded, READ-ONLY command against the target through the SAME kali "
    "`execute_command` surface the hunting agents use. Reach for it when a "
    "mechanism hypothesis hinges on what a page RESPONSE actually contains and "
    "the mapped surface does not carry it: fetch one known endpoint's rendered "
    "body to see its embedded features (iframes, menu entries, tabs), or read a "
    "response header the recon pass did not record. One endpoint often embeds "
    "several features, and a rendered body is a witness a path noun cannot give. "
    "READ-ONLY means read-only: a `curl` of a known endpoint, never a scan, a "
    "mutation, or an exploitation step. A handful of probes per call is the "
    "budget (the tool refuses past it); the mapped graph is the substrate you "
    "reason over and the probe is the exception."
)

# The per-call probe budget (env-overridable, fail-open). A typist turn that
# burns its budget degrades to a denoted error, never a raise and never a hang
# on the analysis critical path.
_DEFAULT_EXEC_BUDGET = 6


class _BoundedAnalysisExec(BaseTool):
    """The bounded, typist-scoped `exec` term (module level, defined once).

    A THIN composition over the hunting `exec` tool: it holds an
    `hunter_tools.ExecTool` and delegates each call to it, so the execution
    seam, the `ExecArgs` schema and the fail-open result shaping are the hunting
    tool's, unchanged. It adds exactly two analysis-side things:

    * the typist-scoped when+how description (`ANALYSIS_EXEC_CONTRACT`) - the
      hunter's description is written for a spec-holding probe agent;
    * a per-call call budget - the typist is a bounded read phase, not a hunting
      agent, so an unbounded exec loop must not sit on the analysis path.

    The hunting base is resolved lazily (the analysis module never imports
    `attack.hunting` at import time). Past the budget the tool returns a denoted
    error, never a raise."""

    name: str = "exec"
    description: str = ANALYSIS_EXEC_CONTRACT

    def __init__(self, *, exec_fn=None, budget: int = _DEFAULT_EXEC_BUDGET, **kwargs):
        from polymerhus.attack.hunting.hunter_tools import ExecArgs, ExecTool

        if exec_fn is None:
            from polymerhus.attack.hunting.pod.tools import default_exec_fn

            exec_fn = default_exec_fn
        super().__init__(args_schema=ExecArgs, **kwargs)
        self._inner = ExecTool(exec_fn=exec_fn)
        self._remaining = budget

    def _run(self, **kwargs):
        if self._remaining <= 0:
            return json.dumps({
                "ok": False, "error": "exec_budget_exhausted", "degraded": True,
                "detail": "this call's probe budget is spent; continue with "
                          "graph_view and the mapped surface",
            })
        self._remaining -= 1
        return self._inner._run(**kwargs)


def build_analysis_exec_tool(*, exec_fn=None, budget: int | None = None):
    """Build the mechanism-typist's bounded `exec` tool.

    `exec_fn` defaults to the pod's `default_exec_fn` (`execute_command` through
    the kali MCP); `budget` defaults to `ANALYSIS_TYPIST_EXEC_BUDGET` (fail-open
    to `_DEFAULT_EXEC_BUDGET`). Fail-open: an unbuildable tool is the caller's
    `build_surface_tools` to drop, never a raise into the turn."""
    cap = budget if budget is not None else int(
        os.environ.get("ANALYSIS_TYPIST_EXEC_BUDGET", _DEFAULT_EXEC_BUDGET)
    )
    return _BoundedAnalysisExec(exec_fn=exec_fn, budget=cap)


def build_surface_tools(role_id: str, *, project_id: str | None = None,
                        with_http: bool = False, with_exec: bool = False) -> tuple:
    """The L0-grounding tools bound on a mechanism-typist turn: `graph_view`
    always, the HTTP-history pair when `with_http`, and the bounded `exec`
    term when `with_exec`. (The assigner no longer builds through this seam -
    its turn binds the HTTP-history pair alone, direct from
    `build_http_history_tools`.) Fail-open at every seam: an unbuildable
    `graph_view` binds nothing, an unbuildable `exec` is simply omitted (the
    read tools remain)."""
    if not project_id:
        return ()
    tools: list[Any] = []
    try:
        tools.append(build_analysis_graph_view_tool(project_id))
    except Exception:  # noqa: BLE001 - fail-open
        return ()
    if with_http:
        tools.extend(build_http_history_tools(project_id))
    if with_exec:
        try:
            tools.append(build_analysis_exec_tool())
        except Exception:  # noqa: BLE001 - fail-open: no exec, read tools remain
            logger.warning(
                "graph_tools: exec tool unbuildable; binding the read tools only",
                exc_info=True,
            )
    return tuple(tools)


__all__ = [
    "ANALYSIS_EXEC_CONTRACT",
    "GRAPH_VIEW_CONTRACT",
    "ReadOnlyGraphViewError",
    "build_analysis_exec_tool",
    "build_analysis_graph_view_tool",
    "build_http_history_tools",
    "build_surface_tools",
]
