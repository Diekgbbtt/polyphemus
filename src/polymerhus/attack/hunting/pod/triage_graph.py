"""The triage phase graph - the compiled `StateGraph` mirror of the hunter's
(lifecycle v2, slice 7).

`hunter_graph.py` is the source of truth for the shape: one passive
supervisor routing only, one deterministic detect handing the outcome to the
advance, and one advance that pushes the phase. The triage machine selects a
DECISION, never a pod terminal: the pod graph's terminal node renders the
`PodExport` from it, and the finalizer applies the monotonicity rule.

There is NO `messages` channel: the ReAct turns own their message history in
the per-pod session checkpointer. Every `ainvoke` carries the TRANSIENT
per-drive inputs (`observed_signal` / `observed_args`) the harness hands it.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.constants import END
from langgraph.graph import START, StateGraph
from langgraph.types import Command

from polymerhus.attack.hunting.pod.triage_state import (
    ASSESS_SIGNAL,
    TriageDecision,
    TriageFacts,
    TriageOutcome,
    TriagePhase,
    advance_triage_state,
    detect_triage_outcome,
)

_SUPERVISE = "supervise"
_DETECT = "detect"
_ADVANCE = "advance"

DECIDE_PACKET_SENTINEL = "__DECIDE_PACKET__"
"""The `injected_constant` the advance node sets on an advance. The harness
replaces it with the composed DECIDE packet before the packet rides the gate
response, so the material is composed only when the route continues."""


class TriageGraphState(TypedDict, total=False):
    """The compiled graph's channels. Every field is last-write EXCEPT `trail`
    (the `operator.add` trajectory record). `observed_signal` / `observed_args`
    are the TRANSIENT observation the harness hands each `ainvoke`; the advance
    consumes them."""

    phase: TriagePhase
    observed_signal: str | None
    observed_args: dict | None
    observed_outcome: TriageOutcome | None
    facts: TriageFacts
    assessment: dict | None
    injected_constant: str | None
    trail: Annotated[list[dict], operator.add]
    decision: TriageDecision | None


def route_supervise(state: TriageGraphState) -> str | None:
    """The sole-entry state tracker's route, as a pure function.

    - `done` -> END: the decision landed.
    - a signal is pending -> `detect`.
    - otherwise -> None: the drive carries no signal; nothing moves and the
      harness returns with the channels untouched."""
    if (state.get("phase") or "assess") == "done":
        return END
    if state.get("observed_signal") is not None:
        return _DETECT
    return None


def _supervise(state: TriageGraphState) -> Command:
    """The state tracker: routing ONLY (a single `Command`, mirroring the
    hunter's DP-5). The stay carries no destination, so the drive returns."""
    return Command(goto=route_supervise(state) or [])


def _detect(state: TriageGraphState) -> Command:
    """The deterministic dispatcher over the pure outcome rule.

    The gate accepted the signal (the harness checked), so the outcome is
    computed here and handed to `advance`. The ASSESS submission is stored as
    the running assessment - the DECIDE gate reads its `clean`. The machine
    never rejects a signal and never raises."""
    signal = state.get("observed_signal")
    args = state.get("observed_args") or {}
    outcome = detect_triage_outcome(state.get("facts") or {}, state.get("assessment"),
                                    signal, args)
    update: dict[str, Any] = {"observed_outcome": outcome}
    if signal == ASSESS_SIGNAL:
        update["assessment"] = args
    return Command(goto=_ADVANCE, update=update)


def _advance(state: TriageGraphState) -> dict:
    """The push: `advance_triage_state` moves the phase, the node records the
    trail entry (an advance, or the decision kind - the ratified phase-path
    vocabulary), then consumes the observation. The DECIDE packet is a
    SENTINEL: the harness composes the material only when an advance actually
    happened, and replaces the sentinel before the packet rides the gate
    response."""
    outcome = state.get("observed_outcome") or {"kind": "advance", "decision": None}
    phase = advance_triage_state(state.get("phase") or "assess", outcome)
    decision = outcome.get("decision")
    kind = "advance" if decision is None else (
        "variant" if decision.get("action") == "variant" else "terminal")
    entry = {"phase": phase, "kind": kind,
             "lap": (state.get("facts") or {}).get("lap", 0)}
    return {
        "phase": phase,
        "decision": decision,
        "injected_constant": (DECIDE_PACKET_SENTINEL
                              if decision is None else None),
        "trail": [entry],
        "observed_signal": None,
        "observed_args": None,
        "observed_outcome": None,
    }


def build_triage_graph(
    *,
    supervise_node: Any = None,
    detect_node: Any = None,
    advance_node: Any = None,
) -> StateGraph:
    """Build (do NOT compile) the triage phase graph, mirroring
    `build_hunter_graph`: routing originates ONLY from `supervise` and `detect`
    via `Command(goto=...)`; `advance` returns to `supervise` on a static
    edge, so the loop restarts naturally per drive."""
    g = StateGraph(TriageGraphState)
    g.add_node(_SUPERVISE, supervise_node or _supervise)
    g.add_node(_DETECT, detect_node or _detect)
    g.add_node(_ADVANCE, advance_node or _advance)
    g.add_edge(START, _SUPERVISE)
    g.add_edge(_ADVANCE, _SUPERVISE)   # static: the next drive is ready
    return g


__all__ = [
    "TriageGraphState",
    "build_triage_graph",
    "route_supervise",
]
