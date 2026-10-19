"""The residual read-only L0/L1 graph view (the hunt-orchestrator module home).

The hunt-orchestrator as an AGENT is retired: the threat modeller
(`threat_modeller.py`) is the hunt's reasoning pass and the run bootstrap
(`runtime.start_hunting`) drives it unit by unit. The config family
(`HuntConfig` / `ConfigStatus`) and the dispatch outcome (`DispatchResult`)
retired in T6 (#379) with the hunter's loop-payload rework; the derived config
identity (`hunt_id_for`) retired with them. What remains in this module is the
read-only graph seam the hunter, the pod and the modeller's grounding provider
share:

- `ReadOnlyGraphView` / `ReadOnlyGraphViewError` - the read-only L0/L1 graph
  seam.

designed-for-removal: the module name retires with the component-name hygiene
sweep (T10, #383). Nothing here may grow a new consumer.

This module imports no driver and performs no I/O at import (CODING_STANDARD 6).
"""
from __future__ import annotations

import re
from typing import Any, Callable

# Write-shaped tokens the read-only view refuses to pass through, whatever the
# calling convention (defense in depth - the API itself exposes no write seam).
_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")


class ReadOnlyGraphViewError(RuntimeError):
    """A write was attempted through the read-only graph view (D67-04)."""


class ReadOnlyGraphView:
    """The read-only view over the live L0/L1 graph (D67-04): it grounds the
    hunter, the pod and the modeller's grounding provider in the live graph and
    can never write it. Any write-shaped call - including `merge` itself -
    raises."""

    def __init__(self, project_id: str, *, read_fn: Callable[[str, dict], list] | None = None):
        self.project_id = project_id
        self._read_fn = read_fn

    def _guard(self, cypher: str) -> None:
        if _WRITE_SHAPED.search(cypher.upper()):
            raise ReadOnlyGraphViewError(
                "the graph view is read-only: refusing write-shaped cypher "
                f"{cypher[:120]!r}"
            )

    def read(self, cypher: str, params: dict | None = None) -> list[dict]:
        self._guard(cypher)
        if self._read_fn is not None:
            return self._read_fn(cypher, params or {})
        from polymerhus.app.clients import neo4j_client

        return neo4j_client.read(cypher, params or {})

    def merge(self, *args: Any, **kwargs: Any) -> Any:
        raise ReadOnlyGraphViewError(
            "the graph view is read-only: the orchestrator never writes L0/L1"
        )

    def index_cards(self) -> list[dict]:
        from polymerhus.analysis.index_card import index_cards as _index_cards

        return _index_cards(self.project_id, read_fn=self.read)


__all__ = [
    "ReadOnlyGraphView",
    "ReadOnlyGraphViewError",
]
