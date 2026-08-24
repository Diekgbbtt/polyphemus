"""The state-graph hunter's StateGraph topology (#164, W5): the state tracker.

The graph does NOT navigate the decision tree (spec 2.1): the ReAct engine does.
This graph is the state-tracking and trajectory-boundary layer over it - a PASSIVE
detection-and-push machine (ADR R4, GP8c): it observes the status verbatim the
harness extracts from a tool call, detects the transition, and pushes the
corresponding list move plus the injected phase-transition constant. It NEVER
gates a tool call on the current state and never rejects an illegal transition -
the no-block invariant. The harness is the sole writer: it drives one compiled
graph per hunt (OUTLIER-1, no graph-level checkpointer) with each observation
and reads back the moved state.

Topology:
  START -> supervise                      (the state tracker: the sole entry)
  supervise --Command(goto="detect")--> detect      (an observation is pending)
  supervise --Command(goto=END)----> END            (idle: hypothesis list exhausted)
  detect   --Command(goto="push_*")--> push_*       (dispatch by the observed status verbatim)
  detect   --Command(goto="supervise")-> supervise  (no transition: appends/reads/other calls)
  push_*   --edge----------------------> supervise  (static: the next push is ready)

DP-5 style: routing via `Command(goto=...)` ONLY where a node must choose - the
`supervise` state tracker (observation pending vs idle) and the deterministic
`detect` dispatcher (which push node, or none). Every other edge is static and
returns to `supervise`, so the loop restarts naturally per observation. There is
NO model-gated router: `detect` is a pure function of the observed status
verbatim (`hunter_state.detect_transition`), never of the state or of a model.

The channels are `hunter_state.HuntState` (every field last-write EXCEPT `trail`,
the `operator.add` trajectory record, replay only, never authoritative) plus the
read-only `config` / `tools` driver assemblies and the TRANSIENT per-drive
observation inputs (`observed_status` / `observed_fault`) the harness hands to
each `ainvoke`. There is NO `messages` channel: the ReAct turns own their message
history in the per-hunt session checkpointer.

Ratifications honoured here:
- R4 (turn-by-turn driver): the graph holds state + transition logic; the
  harness drives it once per observed tool-call status. Detection + push only.
- GP8c (passive lifecycle): no illegal-transition rejection, no steering back.
- GP1 (router discipline): no query_gate / coverage_gate pass routers; the D1/D2/D3
  boundaries are tracked as the `phase` flag, driven by tool-call responses.
- Outer-container correction (ADR, 2026-08-23): the supervisor has NO dispatch
  node - the hunter is fed `HuntConfig`s from its inbox by the surfer, never by
  a graph dispatch node. The verdict-consumption workflow graph is OUT OF SCOPE:
  there is no `waiting-for-verdict` node; END is the idle state the harness
  returns from, and the verdict graph is a separate workstream.

The `phase` flag advances on a push (spec 2.3): a `hypothesised` write advances
`grounding -> hypothesised`, a `verified` / `dropped` write moves to `evaluating`,
and a `specified` write starts the next loop iteration (`hypothesised`). The
terminal `concluded` phase is the harness's idle landing, not a graph node.

This module builds (never compiles) the graph; `build_hunter_graph` takes
injectable node closures (mirroring `orchestrator_graph.build_hunting_graph`) so
a pass compiles IN-MEMORY and the harness supplies the default passive nodes.
No driver and no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .hunter_state import (
    FaultItem,
    HuntState,
    TransitionName,
    TRANSITION_HINTS,
    detect_transition,
    push_transition,
)

logger = logging.getLogger(__name__)

# Stable node names (routed by the state tracker / the deterministic dispatcher).
_SUPERVISE = "supervise"
_DETECT = "detect"
_PUSH_HYPOTHESISED = "push_hypothesised"
_PUSH_VERIFIED = "push_verified"
_PUSH_DROPPED = "push_dropped"
_PUSH_SPECIFIED = "push_specified"

# The phase advance per transition (spec 2.3): the outer loop flag, last-write on
# `HuntState.phase`. `hypothesise` advances `grounding -> hypothesised` (and stays
# `hypothesised` on further appends); `verify` / `drop` move to `evaluating`;
# `specify` starts the next loop iteration back at `hypothesised`. The terminal
# `concluded` phase is the harness's idle landing, never a graph write.
_TRANSITION_PHASE: dict[TransitionName, str] = {
    "hypothesise": "hypothesised",
    "verify": "evaluating",
    "drop": "evaluating",
    "specify": "hypothesised",
}

# The four push nodes by transition (the `detect` dispatcher's destinations).
_PUSH_BY_TRANSITION: dict[TransitionName, str] = {
    "hypothesise": _PUSH_HYPOTHESISED,
    "verify": _PUSH_VERIFIED,
    "drop": _PUSH_DROPPED,
    "specify": _PUSH_SPECIFIED,
}


class HunterGraphState(HuntState, total=False):
    """The compiled graph's channels: `HuntState` plus the per-drive observation
    and the read-only driver assemblies.

    Every `HuntState` field is last-write EXCEPT `trail` (the `operator.add`
    trajectory record). `observed_status` / `observed_fault` are TRANSIENT inputs
    the harness hands each `ainvoke` (one observation per drive); `config` /
    `tools` are the read-only HuntConfig + tool surface assemblies the driver
    rides (spec 3). None of these extra channels belong to the pure `HuntState`
    vocabulary (`hunter_state.py`): they exist only on the compiled graph."""

    observed_status: str | None
    observed_fault: FaultItem | None
    config: Any
    tools: Any


def _supervise(state: HunterGraphState) -> Command:
    """The sole-entry state tracker. An observation is pending -> `detect`;
    otherwise the harness has stopped driving (the hypothesis list is exhausted)
    and the graph lands END - the idle state (verdict consumption is the
    OUT-OF-SCOPE separate graph). Routing ONLY (a single `Command`, DP-5)."""
    if state.get("observed_status") is not None:
        return Command(goto=_DETECT)
    return Command(goto=END)


def _detect(state: HunterGraphState) -> Command:
    """The deterministic dispatcher: map the observed status verbatim to its
    push node (DP-5 Command only - never both paths). "none" (an append, a read,
    another tool call, an absent status) consumes the observation and returns to
    the state tracker with NO state move - the passive machine records only what
    the model signalled on a lifecycle write."""
    transition = detect_transition(state, state.get("observed_status"))
    if transition == "none":
        return Command(goto=_SUPERVISE, update={"observed_status": None})
    return Command(goto=_PUSH_BY_TRANSITION[transition])


def _make_push(transition: TransitionName) -> Callable[[HunterGraphState], dict]:
    """Build a push node: `hunter_state.push_transition` moves the observed fault
    between the semantic lists (the no-block invariant - a transition is NEVER
    gated on the current state), the node injects the phase-transition constant
    (`TRANSITION_HINTS[transition]`, G9 - a constant, never the system prompt),
    advances the `phase` flag, records the fault as `current_fault`, consumes the
    observation, and appends one trail entry. The trail is `operator.add`: only
    the fresh entry returns, so the accumulated trajectory is never re-appended."""

    def push(state: HunterGraphState) -> dict:
        fault: FaultItem = state.get("observed_fault") or {}
        new_state = push_transition(state, transition, fault)
        new_state["injected_constant"] = TRANSITION_HINTS.get(transition)
        new_state["phase"] = _TRANSITION_PHASE.get(
            transition, state.get("phase", "grounding"),
        )
        if fault.get("fault_id"):
            new_state["current_fault"] = fault
        new_state["observed_status"] = None
        new_state["trail"] = [{
            "kind": "transition",
            "transition": transition,
            "fault_id": fault.get("fault_id"),
            "phase": new_state["phase"],
        }]
        return new_state

    return push


def build_hunter_graph(
    *,
    supervise_node: Callable[[HunterGraphState], Any] | None = None,
    detect_node: Callable[[HunterGraphState], Any] | None = None,
    push_nodes: dict[TransitionName, Callable[[HunterGraphState], Any]] | None = None,
) -> StateGraph:
    """Build (do NOT compile) the state-graph hunter's graph. Injectable node
    closures mirror `build_hunting_graph`; each default node is the PASSIVE
    detect/push machine above (a raising injected body degrades the drive, never
    aborts the hunt - the harness's fail-open canon). Routing originates ONLY
    from `supervise` (observation pending vs END) and `detect` (which push, or
    none) via `Command(goto=...)`; every push returns to `supervise` on a static
    edge, so the loop restarts naturally per observation."""
    push_nodes = push_nodes or {}
    g = StateGraph(HunterGraphState)
    g.add_node(_SUPERVISE, supervise_node or _supervise)
    g.add_node(_DETECT, detect_node or _detect)
    g.add_node(_PUSH_HYPOTHESISED,
               push_nodes.get("hypothesise") or _make_push("hypothesise"))
    g.add_node(_PUSH_VERIFIED, push_nodes.get("verify") or _make_push("verify"))
    g.add_node(_PUSH_DROPPED, push_nodes.get("drop") or _make_push("drop"))
    g.add_node(_PUSH_SPECIFIED, push_nodes.get("specify") or _make_push("specify"))
    g.add_edge(START, _SUPERVISE)
    g.add_edge(_PUSH_HYPOTHESISED, _SUPERVISE)  # static: the next push is ready
    g.add_edge(_PUSH_VERIFIED, _SUPERVISE)
    g.add_edge(_PUSH_DROPPED, _SUPERVISE)
    g.add_edge(_PUSH_SPECIFIED, _SUPERVISE)
    return g


__all__ = [
    "HunterGraphState",
    "_SUPERVISE",
    "_DETECT",
    "_PUSH_HYPOTHESISED",
    "_PUSH_VERIFIED",
    "_PUSH_DROPPED",
    "_PUSH_SPECIFIED",
    "build_hunter_graph",
    "_supervise",
    "_detect",
    "_make_push",
]