"""The residual hunt-config vocabulary (retired incrementally since T2b, #386).

The hunt-orchestrator as an AGENT is retired: the threat modeller
(`threat_modeller.py`) is the hunt's reasoning pass and the run bootstrap
(`runtime.start_hunting`) drives it unit by unit. What remains in this module is
only the config and dispatch vocabulary with live consumers:

- `HuntConfig` / `ConfigStatus` - the config the surfer, the mover, the hunter
  harness and the API hand-off still carry (one config per dispatched hunter);
- `DispatchResult` - one hunt session's dispatch outcome;
- `ReadOnlyGraphView` / `ReadOnlyGraphViewError` - the read-only L0/L1 graph
  seam the hunter, the pod and the modeller's grounding provider share;
- `hunt_id_for` - the derived config identity the hunting API uses.

designed-for-removal: the module name and every type above retire with the
consumer tickets - the config family with T4 (#377) and T6 (#379), the module
name with the component-name hygiene sweep (T10, #379). Nothing here may grow a
new consumer.

Retired in T3 (#376): the FaultSource selection output (`DeliveredCandidate` /
`Witness`) - the run's unit set is its INTAKE now (`unit_intake`), so nothing
consumes a delivered candidate any more.

This module imports no driver and performs no I/O at import (CODING_STANDARD 6).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from polymerhus.attack.hunting.hunt_store import semantic_key

# The config status lifecycle (ADR G5/G6): hypothesised -> ratified | dropped.
# `noted` is a LOOP state, never a config status; `consumed` is tautological in
# the produced/consumed topology, never a status enum member.
ConfigStatus = Literal["hypothesised", "ratified", "dropped"]


class HuntConfig(BaseModel):
    """The declarative config a dispatched hunt session consumes (D3): the
    parameter set - the `rationale` + `research_direction` seeds, wide surface
    context (the adapted index-card, a Service's edge_degree transformed to its
    connected DataItems), the `preconditions` + `observed_defences`, and the
    downstream prior-hunt insights (the hunter memory's TestImplementationSpecs
    + Q16 pod exports by config_key, shallow-projected, #202) - plus `status`
    (the config lifecycle `hypothesised -> ratified | dropped`) and
    `vulnerability_class` (the config's identity axis, one config per class).

    The config is oriented by the three goals (#202): (G1) feasibility of that
    fault at that unit - `rationale`, `research_direction`, `vulnerability_class`,
    `surface_context`; (G2) the initial concretisation - the
    `vulnerability_class` naming itself; (G3) further-concretisation material -
    `prior_hunt_insights`. `tool_registry` / `adversarial_capabilities` /
    `assumptions` / `technique_primitives` / `target_caveats` are removed (#202),
    and `sub_fault_ids` is removed (#298).

    The former `HuntPromptTemplate` wrapper is FLATTENED (2026-10-04): it carried
    exactly two plain strings, so `rationale` and `research_direction` are
    top-level config fields."""

    hunt_id: str
    unit_id: str
    fault_class: str
    status: ConfigStatus = "hypothesised"
    vulnerability_class: str = ""
    rationale: str = ""
    research_direction: str = ""
    surface_context: dict = Field(default_factory=dict)
    observed_defences: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    prior_hunt_insights: list[dict] = Field(default_factory=list)


class DispatchResult(BaseModel):
    """One hunting-agent dispatch outcome (IA-2): the delivered refs plus the
    hypothesis verdict and NL feedback (D11)."""

    spec_ref: str | None = None
    pod_result_ref: str | None = None
    hypothesis_verdict: str | None = None
    feedback: str | None = None


class ReadOnlyGraphViewError(RuntimeError):
    """A write was attempted through the read-only graph view (D67-04)."""


# Write-shaped tokens the read-only view refuses to pass through, whatever the
# calling convention (defense in depth - the API itself exposes no write seam).
_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")


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


def hunt_id_for(unit_id: str, fault_class: str, vulnerability_class: str) -> str:
    """The DETERMINISTIC config hunt id (#298): a pure function of the identity
    triple `(unit_id, fault_class, vulnerability_class)` - the same identity the
    file name and the semantic key derive from. The former `uuid4` base plus the
    `-i` fan-out order element is REMOVED: it added a cross-run collision surface
    while carrying no information beyond the identity."""
    return semantic_key(unit_id, fault_class, vulnerability_class)
