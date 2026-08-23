"""The hunt-orchestration graph engine (#110, reworked by #167): the StateGraph
topology for the node-per-phase REASON stretch.

As amended by the memory + workflow-graph ADR (G1-G14), the REASON body is a
node-per-phase workflow graph: every (unit, fault) pair runs the three phase
nodes `hypothesise -> ratify -> note`, and the phase-transition logic is
EMBEDDED IN THE GRAPH (G2) as static edges, with the harness tracking the
pair's loop state (`HYPOTHESISED / RATIFIED / NOTED`, G5) on the `loop_state`
channel as the graph executes. The supervisor stays the single routing
authority (`Command(goto=...)` only from it - DP-5: the both-paths-fire
pitfall cannot occur): it pops FAULT work items (the fault remains the
schedule unit, spec 3.1 - one work item per fault over all its matched units)
and iterates each fault's candidate queue as the pairs the phase nodes operate
on. The dispatch node and the O9 budget stage are REMOVED (G12/G7): the graph
ENDs after the last pair's note phase - dispatch state and budget belong to the
runtime plane.

The pair-iteration decision (documented, spec 3.2/3.1): the fault work item is
popped by the supervisor and its candidate list becomes the `pairs` queue; the
supervisor pops ONE pair per super-step and routes it into the phase chain, so
the phase nodes operate per (unit, fault) pair while the fault stays the
schedule unit at the routing level.

Topology:
  START -> supervisor
  supervisor --Command(goto="hypothesise")--> hypothesise   (a pair popped)
  hypothesise --edge--> ratify                               (static: the phase machine)
  ratify --edge--> note                                      (static)
  note --edge--> supervisor                                  (static: the pair end)
  supervisor --Command(goto=END)--> END                      (schedule + pairs exhausted)

Determinism: routing ONLY from the supervisor; the phase chain rides static
edges; one logical writer per super-step. Every channel is LAST-WRITE EXCEPT
the two reducer channels `trail` (report bookkeeping) and `loop_states` (the
loop-state machine's observable transitions, append-only).

This module builds (never compiles) the graph; `build_hunting_graph` takes
injectable node closures (hypothesise / ratify / note, mirroring
`analysis.supervisor.build_supervisor_graph`) so a pass compiles IN-MEMORY and
the driver (arun_orchestration) supplies the canon-delegating closures. Each
default node is fail-open - a missing or raising seam body skips that phase's
side effect but keeps the pass serving: the loop state still transitions, the
pair still reaches the note phase, and the graph still reaches END (the O1-O10
degradation canon). No driver and no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import inspect
import logging
import operator
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from polymerhus.attack.hunting.hunt_orchestrator import LoopState

logger = logging.getLogger(__name__)

# The harness loop-state machine (G2/G5): NOTED is a LOOP state, never a config
# status - the config lifecycle `hypothesised -> ratified | dropped` stops at
# ratified (the memory-system spec 5). Single-sourced in hunt_orchestrator.

# Stable node names (routed by the supervisor). The phase chain is the REASON
# stretch; there is NO dispatch node (G12) and NO budget stage (G7).
_HYPOTHESISE = "hypothesise"
_RATIFY = "ratify"
_NOTE = "note"


class HuntOrchestrationState(TypedDict, total=False):
    """The graph's channels. Every field is last-write EXCEPT the two reducer
    channels `trail` (report bookkeeping) and `loop_states` (the loop-state
    machine's append-only transition log). The schedule head is a FAULT work
    item (a `FaultWorkItem`: `fault_class` + the fault's full matched-unit
    list); `current` is that work item, `pairs` is the fault's REMAINING
    candidate queue, and `current_pair` is the (unit, fault) pair the phase
    nodes operate on. `loop_state` tracks the pair's phase-machine position
    (`HYPOTHESISED -> RATIFIED -> NOTED`, G2/G5). The harness-owned `ledger` /
    `minted_configs` channels carry the pair-boundary state; `kb_evidences` /
    `kb_degraded` / `surface` / `tools` / `store_reads` are read-only inputs
    the driver assembles before the graph runs; the seam closures
    (`hypothesise_fn` / `ratify_fn` / `note_fn`) ride the state so the default
    nodes can call the canon delegates without the driver rebuilding the graph."""

    project_id: str
    run_id: str
    schedule: list[Any]                      # last-write: the supervisor rewrites the tail
    current: Any                             # last-write: the fault work item being reasoned
    pairs: list[Any]                         # last-write: the current fault's remaining candidates
    current_pair: Any                        # last-write: the (unit, fault) pair being reasoned
    loop_state: LoopState | None             # last-write: the pair's phase-machine position
    loop_states: Annotated[list[str], operator.add]  # append-only: the transitions the graph took
    trail: Annotated[list[dict], operator.add]       # report bookkeeping
    ledger: Any                              # last-write: the LoopLedger, updated at the pair boundary
    minted_configs: dict                     # last-write: revival_key -> minted HuntConfig list
    kb_evidences: dict                       # read-only, assembled by the driver
    kb_degraded: bool                        # read-only
    surface: list[dict]                      # read-only
    tools: Any                               # read-only (OrchestratorTools)
    store_reads: Any                         # read-only
    hypothesise_fn: Callable | None          # the hypothesise seam (GateInput -> GateDecision)
    ratify_fn: Callable | None               # the ratify seam (PhaseInput -> RatifyDecision)
    note_fn: Callable | None                 # the note seam (PhaseInput -> NoteDecision)
    exhausted_faults: tuple                  # read-only, carried to the report


def _supervisor(state: HuntOrchestrationState) -> Command:
    """The single routing authority. Pops ONE (unit, fault) pair per super-step
    and routes it into the hypothesise phase; when the current fault's pair
    queue is exhausted it pops the next FAULT work item (the fault stays the
    schedule unit, spec 3.1) and seeds its candidate queue; an exhausted
    schedule AND queue -> END. Routing ONLY (a single `Command` - never both
    paths); the payload travels as the typed values on state."""
    pairs = list(state.get("pairs") or [])
    if not pairs:
        schedule = list(state.get("schedule") or [])
        if not schedule:
            return Command(goto=END)
        head, *tail = schedule
        pairs = list(getattr(head, "candidates", None) or [])
        if pairs:
            current_pair, *rest = pairs
        else:
            # a fault with no candidates cannot occur post-intake (O7/O10);
            # fail-open: route a degenerate pair so the phase chain still
            # advances and the supervisor pops the next fault.
            current_pair, rest = None, []
        return Command(goto=_HYPOTHESISE, update={
            "current": head,
            "schedule": tail,
            "pairs": rest,
            "current_pair": current_pair,
            "loop_state": None,
        })
    current_pair, *rest = pairs
    return Command(goto=_HYPOTHESISE, update={
        "pairs": rest,
        "current_pair": current_pair,
        "loop_state": None,
    })


def _call_maybe_await(body: Callable | None, state: HuntOrchestrationState):
    """Invoke an injected node body, awaiting it when it is (or returns) a
    coroutine, so both the sync test fixtures and the async driver closures
    (which must await seam calls) ride the same wrapper."""
    if body is None:
        return None
    out = body(state)
    if inspect.isawaitable(out):
        return out
    return out


def _make_phase_node(loop_state: LoopState, name: str) -> Callable[[Callable | None], Callable]:
    """Factory for the three phase-node wrappers. Each runs the injected seam
    body for the CURRENT pair - sync or async - and ALWAYS advances the
    loop-state machine to its phase (`HYPOTHESISED -> RATIFIED -> NOTED`, G2),
    appending the transition to the `loop_states` reducer. Fail-open: a missing
    or raising seam body skips that phase's side effect (the canon's own
    fail-open produces the degraded trail) but the pass keeps serving and the
    graph still reaches END."""

    def make(body: Callable | None) -> Callable[[HuntOrchestrationState], "Any"]:
        async def phase(state: HuntOrchestrationState) -> dict:
            try:
                out = _call_maybe_await(body, state)
                if inspect.isawaitable(out):
                    out = await out
                if out is not None:
                    return {**out, "loop_state": loop_state,
                            "loop_states": [loop_state]}
            except Exception as exc:  # noqa: BLE001 - fail-open: keep serving
                logger.warning("%s phase failed for %s (%s)", name,
                               _pair_label(state.get("current_pair")), exc)
            return {"loop_state": loop_state, "loop_states": [loop_state]}

        return phase

    return make


def _make_hypothesise(hypothesise_node: Callable | None) -> Callable[[HuntOrchestrationState], "Any"]:
    """Build the `hypothesise` node: run the pair's hypothesis-elicitation
    stretch (Q8; the mint is called at this phase) or skip the phase's side
    effect when the seam is absent or raises (fail-open). The wrapper marks the
    loop state HYPOTHESISED - the hypothesise write's tool-call response
    carries the NEXT_RATIFY_HINT constant (G1/G3)."""
    return _make_phase_node("HYPOTHESISED", "hypothesise")(hypothesise_node)


def _make_ratify(ratify_node: Callable | None) -> Callable[[HuntOrchestrationState], "Any"]:
    """Build the `ratify` node: run the pair's ratification stretch (may
    update/delete/create configs; must END with status="ratified"), or skip the
    phase's side effect when the seam is absent or raises (fail-open). The
    wrapper marks the loop state RATIFIED - the ratified write's tool-call
    response carries ONLY the NEXT_NOTE_HINT constant (G1)."""
    return _make_phase_node("RATIFIED", "ratify")(ratify_node)


def _make_note(note_node: Callable | None) -> Callable[[HuntOrchestrationState], "Any"]:
    """Build the `note` node: run the pair's note-taking stretch (the pair's
    loop ENDS at the note tool's response, which carries the next pair's data
    plus the NEXT_PAIR_HINT constant - G1), or skip the phase's side effect
    when the seam is absent or raises (fail-open). The wrapper marks the loop
    state NOTED - a LOOP state, never a config status (G5)."""
    return _make_phase_node("NOTED", "note")(note_node)


def _pair_label(current: Any) -> str:
    """A stable label for the node that is being reasoned: a FAULT work item
    renders its unit count, a pair renders its revival key. Fail-open."""
    if current is None:
        return "<none>"
    fault_class = getattr(current, "fault_class", "?")
    unit_id = getattr(current, "unit_id", None)
    if unit_id is not None:
        return f"{unit_id}::{fault_class}"
    units = getattr(current, "candidates", None)
    if isinstance(units, (list, tuple)) and units:
        return f"{len(units)} unit(s)::{fault_class}"
    return f"<pair>::{fault_class}"


def build_hunting_graph(
    *,
    hypothesise_node: Callable | None = None,
    ratify_node: Callable | None = None,
    note_node: Callable | None = None,
) -> StateGraph:
    """Build (do NOT compile) the hunt-orchestration graph. Injectable node
    closures mirror `build_supervisor_graph`; each default node degrades
    fail-open when a closure is absent. Routing originates ONLY from the
    supervisor via `Command(goto=...)` (DP-5); the phase chain rides static
    edges hypothesise -> ratify -> note (the phase machine is embedded in the
    graph, G2), and the note node returns to the supervisor so the loop
    restarts naturally. There is no dispatch node (G12) and no budget stage
    (G7)."""
    g = StateGraph(HuntOrchestrationState)
    g.add_node("supervisor", _supervisor)
    g.add_node(_HYPOTHESISE, _make_hypothesise(hypothesise_node))
    g.add_node(_RATIFY, _make_ratify(ratify_node))
    g.add_node(_NOTE, _make_note(note_node))
    g.add_edge(START, "supervisor")
    g.add_edge(_HYPOTHESISE, _RATIFY)   # static: the phase machine's first edge
    g.add_edge(_RATIFY, _NOTE)          # static: the phase machine's second edge
    g.add_edge(_NOTE, "supervisor")     # static: the pair end returns to the supervisor
    return g


__all__ = [
    "HuntOrchestrationState",
    "LoopState",
    "build_hunting_graph",
    "_supervisor",
    "_HYPOTHESISE",
    "_RATIFY",
    "_NOTE",
]