"""The hunt-orchestration graph engine (#110): the StateGraph topology.

The O1-O10 orchestration canon's algorithm is a supervisor-state schedule loop
over the candidate pairs. The supervisor is the single routing authority
(`Command(goto=...)` only from it - DP-5: the both-paths-fire pitfall cannot
occur); the deterministic stages ride static edges back to the supervisor, and
the loop restarts naturally when the supervisor pops the next pair.

Topology:
  START -> supervisor
  supervisor --Command(goto="reason")--> reason   (REASON phase: pop schedule head)
  reason    --edge--> supervisor                  (static)
  supervisor --Command(goto="budget")--> budget   (schedule exhausted)
  budget    --edge--> supervisor                  (static; sets phase=dispatch + worklist)
  supervisor --Command(goto="dispatch")--> dispatch (DISPATCH phase: pop worklist head)
  dispatch  --edge--> supervisor                  (static)
  supervisor --Command(goto=END)--> END           (worklist exhausted)

Determinism: routing ONLY from the supervisor; static edges everywhere else;
one logical writer per super-step. Every channel is LAST-WRITE EXCEPT the two
reducer channels `directions` (the per-pair accumulator the budget stage cuts
over) and `trail` (report bookkeeping), both append-only - the supervisor's
`receipts` discipline generalised to the two accumulators this engine needs.

This module builds (never compiles) the graph; `build_hunting_graph` takes
injectable node closures (mirroring `analysis.supervisor.build_supervisor_graph`)
so a pass compiles IN-MEMORY and the driver (arun_orchestration, Task 2)
supplies the canon-delegating closures. Each default node is fail-open - a
collaborator failure carries the pair, never aborts the pass (the O1-O10
degradation canon). No driver and no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import inspect
import logging
import operator
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

logger = logging.getLogger(__name__)

# Stable node names (routed by the supervisor).
_REASON = "reason"
_BUDGET = "budget"
_DISPATCH = "dispatch"


class HuntOrchestrationState(TypedDict, total=False):
    """The graph's channels. Every field is last-write EXCEPT the two reducer
    channels `directions` (the pair accumulator the budget stage cuts over) and
    `trail` (report bookkeeping). `kb_evidences` / `kb_degraded` / `surface` /
    `tools` / `store_reads` are read-only inputs the driver assembles before the
    graph runs; the seam closures (`reason_fn` / `budget_fn` / `dispatch_fn` /
    `rematch_fn`) ride the state so the default nodes can call the canon
    delegates without the driver rebuilding the graph."""

    project_id: str
    run_id: str
    phase: str                               # "reason" | "dispatch"
    schedule: list[Any]                      # last-write: the supervisor rewrites the tail
    current: Any                             # last-write: the pair being reasoned
    worklist: list[Any]                      # last-write: the allowed dispatch queue
    current_direction: Any                   # last-write: the direction being dispatched
    directions: Annotated[list[Any], operator.add]  # the ONLY per-pair accumulator
    trail: Annotated[list[dict], operator.add]      # report bookkeeping
    kb_evidences: dict                       # read-only, assembled by the driver
    kb_degraded: bool                        # read-only
    surface: list[dict]                      # read-only
    tools: Any                               # read-only (OrchestratorTools)
    store_reads: Any                         # read-only
    reason_fn: Callable | None               # the gate turn seam (GateInput -> GateDecision)
    budget_fn: Callable | None               # the budget seam (Sequence -> Sequence)
    dispatch_fn: Callable | None             # the per-config dispatch seam
    rematch_fn: Callable | None              # the re-match judge seam
    exhausted_faults: tuple                  # read-only, carried to the report


def _supervisor(state: HuntOrchestrationState) -> Command:
    """The single routing authority. REASON phase: pop the schedule head, set it
    as the current pair, route to `reason`; an empty schedule -> `budget`.
    DISPATCH phase: pop the worklist head, route to `dispatch`; an empty
    worklist -> END. Routing ONLY (a single `Command` - never both paths); the
    payload travels as the typed values on state."""
    if state.get("phase", "reason") == "reason":
        schedule = list(state.get("schedule") or [])
        if not schedule:
            return Command(goto=_BUDGET)
        head, *tail = schedule
        return Command(goto=_REASON, update={
            "current": head, "schedule": tail, "phase": "reason",
        })
    worklist = list(state.get("worklist") or [])
    if not worklist:
        return Command(goto=END)
    head, *tail = worklist
    return Command(goto=_DISPATCH, update={
        "current_direction": head, "worklist": tail, "phase": "dispatch",
    })


def _carry_current(state: HuntOrchestrationState) -> dict:
    """Fail-open: carry the current pair as a bare carried direction (Task 1;
    Task 2 delegates to the canon's gate-carry so the minted config matches)."""
    current = state.get("current")
    if current is None:
        return {}
    from polymerhus.attack.hunting.hunt_orchestrator import EnvisionedDirection  # noqa: PLC0415
    return {"directions": [
        EnvisionedDirection(unit_id=current.unit_id, fault_class=current.fault_class),
    ]}


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


def _make_reason(reason_node: Callable | None) -> Callable[[HuntOrchestrationState], "Any"]:
    """Build the `reason` node: run the LLM-analysis stretch for the current
    pair (the injected body - sync or async), or carry the pair when the stretch
    is absent or raises (fail-open - the O1-O10 gate-carry). The body (Task 2)
    performs the stateful actor turn and returns the pair's `directions` + trail
    events."""

    async def reason(state: HuntOrchestrationState) -> dict:
        try:
            out = _call_maybe_await(reason_node, state)
            if inspect.isawaitable(out):
                out = await out
            if out is not None:
                return out
        except Exception as exc:  # noqa: BLE001 - fail-open: carry the pair
            logger.warning("reason stretch failed for %s, carrying (%s)",
                           _pair_label(state.get("current")), exc)
        return _carry_current(state)

    return reason


def _make_budget(budget_node: Callable | None) -> Callable[[HuntOrchestrationState], "Any"]:
    """Build the `budget` node: the deterministic batch stage. The injected body
    cuts over the WHOLE accumulated `directions` set and returns the `worklist`
    + any cut trail events; the default (no body) passes every carried direction
    through uncut. Sets `phase="dispatch"` so the supervisor enters the DISPATCH
    phase when it pops next."""

    async def budget(state: HuntOrchestrationState) -> dict:
        out = _call_maybe_await(budget_node, state)
        if inspect.isawaitable(out):
            out = await out
        if out is not None:
            return out
        return {
            "worklist": list(state.get("directions") or []),
            "phase": "dispatch",
            "trail": [],
        }

    return budget


def _make_dispatch(dispatch_node: Callable | None) -> Callable[[HuntOrchestrationState], "Any"]:
    """Build the `dispatch` node: the per-direction dispatch stage. The injected
    body (Task 2) does park/resume + rematch for a yellow candidate, the
    deterministic mint, and the per-config dispatch with inline back-edge
    rounds, returning trail events. The default (no body) degrades to a
    `hunting agent unavailable` trail event - fail-open, exactly the canon's
    no-`dispatch_fn` outcome."""

    async def dispatch(state: HuntOrchestrationState) -> dict:
        out = _call_maybe_await(dispatch_node, state)
        if inspect.isawaitable(out):
            out = await out
        if out is not None:
            return out
        direction = state.get("current_direction")
        if direction is None:
            return {"trail": []}
        key = f"{getattr(direction, 'unit_id', '?')}::{getattr(direction, 'fault_class', '?')}"
        return {"trail": [{"kind": "hunt_degraded", "revival_key": key}]}

    return dispatch


def _pair_label(current: Any) -> str:
    if current is None:
        return "<none>"
    return f"{getattr(current, 'unit_id', '?')}::{getattr(current, 'fault_class', '?')}"


def build_hunting_graph(
    *,
    reason_node: Callable | None = None,
    budget_node: Callable | None = None,
    dispatch_node: Callable | None = None,
) -> StateGraph:
    """Build (do NOT compile) the hunt-orchestration graph. Injectable node
    closures mirror `build_supervisor_graph`; each default node degrades
    fail-open when a closure is absent. Routing originates ONLY from the
    supervisor via `Command(goto=...)` (DP-5); every other edge is static and
    returns to the supervisor, so the loop restarts naturally."""
    g = StateGraph(HuntOrchestrationState)
    g.add_node("supervisor", _supervisor)
    g.add_node(_REASON, _make_reason(reason_node))
    g.add_node(_BUDGET, _make_budget(budget_node))
    g.add_node(_DISPATCH, _make_dispatch(dispatch_node))
    g.add_edge(START, "supervisor")
    g.add_edge(_REASON, "supervisor")      # static: the pair returns to the supervisor
    g.add_edge(_BUDGET, "supervisor")      # static: the worklist returns to the supervisor
    g.add_edge(_DISPATCH, "supervisor")    # static: the dispatch returns to the supervisor
    return g


__all__ = [
    "HuntOrchestrationState",
    "build_hunting_graph",
    "_supervisor",
    "_REASON",
    "_BUDGET",
    "_DISPATCH",
]
