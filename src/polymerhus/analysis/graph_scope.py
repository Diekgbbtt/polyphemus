"""The symbolic project scope every `graph_view` read binds.

The tool layer owns the run's project scope. The model never supplies it:
the Cypher uses the bound `$project_id` symbol, and the wrapper injects the
value. A caller-supplied `project_id` is dropped so a domain slug can never
silently scope the read to an empty graph.

This is intentionally a tiny module: both the analysis `graph_view` and the
hunting `ReadOnlyGraphView` import it, so the two seams cannot drift on the
one invariant that matters.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["bind_project_scope"]


def bind_project_scope(
    project_id: str,
    params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the Cypher params with the run's project scope bound.

    Every other caller parameter survives unchanged. A caller-supplied
    `project_id` is removed, never merged: the bound scope is the only
    value the read can see.
    """
    scoped = {
        key: value
        for key, value in (params or {}).items()
        if key != "project_id"
    }
    scoped["project_id"] = project_id
    return scoped
