"""The analysis-proposer tool surface (the adjacent-surface read seam, D-A2).

The streamed Assigner judges a recently-collected chunk slice, and may widen
its view to the slice's neighbourhood to gain a topological understanding of
the services around it. It therefore needs to query the mapped L0 surface
broadly, without assuming asset names, and to confirm an ambiguous ownership
against the recorded request shapes.

Two tools are bound on the Assigner turn (the constant request shape, the
cache rule):

  * `graph_view` - the read-only L0/L1 Cypher view (broad L0 query);
  * `search_http_history` / `get_http_artifact` - the recorded transaction
    search + fetch (request shapes), for disambiguation and confirmation only.

`graph_view` is a light analysis-side binding: the write-shape guard and the
read seam live here so the analysis module does not import `attack.hunting` for
it. The HTTP-history tools are the SAME classes the hunting module binds; they
are resolved lazily and reused verbatim so the contracts cannot drift.

Import performs no I/O (CODING_STANDARD section 6); the read seam resolves on call.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from langchain_core.tools import tool

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
    "discriminator), L1DataItem (item_key)\n"
    "- L0 (observed): Endpoint (path/method/baseurl/url), Parameter "
    "(name/position/endpoint_path/baseurl), BaseURL (url), Header "
    "(name/value/baseurl), Secret (value_hash), Observation (triager)\n"
    "relationship types:\n"
    "- cross-layer: AGGREGATES ((:L1Service)-[:AGGREGATES]->(:L0)), SURFACES_AT "
    "((:L1DataItem)-[:SURFACES_AT]->(:L0)), EVIDENCED_BY "
    "((:L1System)-[:EVIDENCED_BY]->(:L0))\n"
    "- intra-L1: EXPOSED_VIA, ROUTED_BY, FRONTED_BY, AUTHENTICATED_BY, "
    "AUTHORIZED_BY, CONSUMES, PRODUCES\n"
    "- L0-internal: HAS_ENDPOINT ((:BaseURL)-[:HAS_ENDPOINT]->(:Endpoint)), "
    "HAS_PARAMETER, HAS_HEADER, HAS_SECRET, HAS_OBSERVATION"
)

_QUERY_PRIMITIVES = (
    "QUERY LANGUAGE (read-only Cypher) - use MATCH, OPTIONAL MATCH, WHERE, "
    "RETURN, ORDER BY, LIMIT, DISTINCT, count(), collect(), labels(), type(). "
    "Scope every query with {project_id: $project_id}. Write-shaped tokens "
    "(MERGE / CREATE / DELETE / SET / REMOVE / FOREACH / LOAD CSV) are refused. "
    "Always LIMIT: the view returns no cap. Query BROADLY first (enumerate the "
    "surface) and only then narrow - never assume an asset name."
)

_RETURN_SHAPE = (
    "RETURN SHAPE - on success {\"rows\": [...]} (a list of dict rows); on a "
    "failure {\"error\": ...} (fail-open, never a raise)."
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
        if _WRITE_SHAPED.search(cypher.upper()):
            raise ReadOnlyGraphViewError(
                "the graph view is read-only: refusing write-shaped cypher "
                f"{cypher[:120]!r}"
            )
        merged = {"project_id": project_id, **(params or {})}
        try:
            rows = read(cypher, merged)
            if not isinstance(rows, list):
                return {"rows": [rows] if rows is not None else []}
            return {"rows": rows}
        except ReadOnlyGraphViewError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail-open
            return {"error": f"graph_view degraded: {exc}"}

    graph_view.description = GRAPH_VIEW_CONTRACT
    return graph_view


def build_http_history_tools(project_id: str):
    """The `search_http_history` / `get_http_artifact` read pair, bound for every
    proposer that harvests a surface so it can read the recorded request shapes.

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


def build_surface_tools(role_id: str, *, project_id: str | None = None,
                        with_http: bool = False) -> tuple:
    """The L0-grounding tools bound on a proposer turn: `graph_view` always, and
    the HTTP-history pair when `with_http` (every harvesting proposer)."""
    if not project_id:
        return ()
    tools: list[Any] = []
    try:
        tools.append(build_analysis_graph_view_tool(project_id))
    except Exception:  # noqa: BLE001 - fail-open
        return ()
    if with_http:
        tools.extend(build_http_history_tools(project_id))
    return tuple(tools)


__all__ = [
    "GRAPH_VIEW_CONTRACT",
    "ReadOnlyGraphViewError",
    "build_analysis_graph_view_tool",
    "build_http_history_tools",
    "build_surface_tools",
]
