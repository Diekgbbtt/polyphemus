"""Unit tier: the hunt-orchestrator graph engine's topology skeleton (#110).

Task 1 pins the StateGraph topology only (no LLM, no Neo4j): the graph builds
and compiles; the supervisor-state schedule loop visits REASON(fault work item)
-> budget -> DISPATCH(direction) in deterministic order and ENDs on an empty
worklist; a routing decision is a SINGLE `Command` (DP-5: both-paths-fire cannot
occur); the two reducer channels append rather than overwrite; an empty schedule
ENDs after budget with nothing dispatched; and a raising reason stretch carries
the fault fail-open while the graph still reaches END.

The O1-O10 canon semantics live in `test_hunt_orchestrator.py` and the C1-C12
catalogue in tests/integration - this tier never repeats them.
"""
import asyncio

from langgraph.graph import END
from langgraph.types import Command

from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    EnvisionedDirection,
    FaultWorkItem,
    Witness,
)
from polymerhus.attack.hunting.orchestrator_graph import (
    _supervisor,
    build_hunting_graph,
)


def _candidate(unit_id: str, fault_class: str) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id,
        fault_class=fault_class,
        applies_witnesses=Witness(deterministic="deterministic", llm="witness"),
        match_verdict="applies",
    )


def _direction(candidate: DeliveredCandidate) -> EnvisionedDirection:
    return EnvisionedDirection(
        unit_id=candidate.unit_id, fault_class=candidate.fault_class, carried=True,
    )


def _fault_grouped(candidates: list[DeliveredCandidate]) -> list[FaultWorkItem]:
    """The candidates-rewrite schedule group (spec 3.1): ONE `FaultWorkItem`
    per distinct fault_class, in deterministic (input) order."""
    grouped: dict[str, list[DeliveredCandidate]] = {}
    for c in candidates:
        grouped.setdefault(c.fault_class, []).append(c)
    return [FaultWorkItem(fault_class=f, candidates=grouped[f])
            for f in grouped]


def _initial(pairs, *, phase: str = "reason") -> dict:
    return {
        "project_id": "project-1",
        "run_id": "run-1",
        "phase": phase,
        "schedule": _fault_grouped(list(pairs)),
        "current": None,
        "worklist": [],
        "current_direction": None,
        "directions": [],
        "trail": [],
        "ledger": None,
        "minted_configs": {},
        "kb_evidences": {},
        "kb_degraded": False,
        "surface": [],
        "exhausted_faults": (),
    }


def _drive(graph, state) -> dict:
    compiled = graph.compile()
    return asyncio.run(compiled.ainvoke(state, {"configurable": {"thread_id": "t"}}))


# --- Topology: build + compile -------------------------------------------------

def test_build_hunting_graph_compiles():
    compiled = build_hunting_graph().compile()
    assert compiled is not None


# --- The loop: REASON -> budget -> DISPATCH -> ... -> END -----------------------

def test_two_pair_schedule_loops_in_deterministic_order_and_ends():
    p1, p2 = _candidate("u-1", "f-1"), _candidate("u-2", "f-2")
    visits: list[tuple] = []

    def reason(state):
        current = state["current"]
        unit = current.candidates[0]
        visits.append(("reason", unit.unit_id))
        return {"directions": [_direction(unit)],
                "trail": [{"kind": "gate", "revival_key": unit.unit_id}]}

    def budget(state):
        visits.append(("budget", None))
        return {"worklist": list(state["directions"]), "phase": "dispatch", "trail": []}

    def dispatch(state):
        direction = state["current_direction"]
        visits.append(("dispatch", direction.unit_id))
        return {"trail": [{"kind": "hunt", "revival_key": direction.unit_id}]}

    final = _drive(build_hunting_graph(
        reason_node=reason, budget_node=budget, dispatch_node=dispatch,
    ), _initial([p1, p2]))

    # REASON phase drains the whole schedule, budget cuts over the accumulated
    # directions, DISPATCH phase drains the worklist - then the graph reaches END.
    assert visits == [
        ("reason", "u-1"), ("reason", "u-2"),
        ("budget", None),
        ("dispatch", "u-1"), ("dispatch", "u-2"),
    ]
    assert final["worklist"] == []  # the worklist drained -> the graph ended
    assert final["current_direction"].unit_id == "u-2"  # last-write retains the last dispatch
    assert [d.unit_id for d in final["directions"]] == ["u-1", "u-2"]


def test_empty_schedule_ends_after_budget_with_nothing_dispatched():
    visits: list[str] = []

    def budget(state):
        visits.append("budget")
        return {"worklist": list(state["directions"]), "phase": "dispatch", "trail": []}

    def dispatch(state):
        visits.append("dispatch")  # pragma: no cover - must never be reached
        return {"trail": []}

    final = _drive(build_hunting_graph(
        budget_node=budget, dispatch_node=dispatch,
    ), _initial([]))

    assert visits == ["budget"]
    assert final["worklist"] == []


# --- Routing: one authority, one Command (DP-5) ---------------------------------

def test_supervisor_routes_with_a_single_command_never_both_paths():
    head = _candidate("u-1", "f-1")
    tail = _candidate("u-2", "f-2")
    schedule = _fault_grouped([head, tail])

    cmd = _supervisor({"phase": "reason", "schedule": schedule})
    assert isinstance(cmd, Command)
    assert cmd.goto == "reason"
    assert cmd.update["current"].fault_class == "f-1"
    assert cmd.update["schedule"] == schedule[1:]

    cmd = _supervisor({"phase": "reason", "schedule": []})
    assert isinstance(cmd, Command)
    assert cmd.goto == "budget"

    direction = _direction(_candidate("u-1", "f-1"))
    cmd = _supervisor({"phase": "dispatch", "worklist": [direction]})
    assert isinstance(cmd, Command)
    assert cmd.goto == "dispatch"
    assert cmd.update["current_direction"].unit_id == "u-1"
    assert cmd.update["worklist"] == []

    cmd = _supervisor({"phase": "dispatch", "worklist": []})
    assert isinstance(cmd, Command)
    assert cmd.goto == END


# --- Reducers: accumulate, never overwrite --------------------------------------

def test_directions_and_trail_reduce_append_not_overwrite():
    p1, p2 = _candidate("u-1", "f-1"), _candidate("u-2", "f-2")

    def reason(state):
        current = state["current"]
        unit = current.candidates[0]
        return {"directions": [_direction(unit)],
                "trail": [{"kind": "gate", "revival_key": unit.unit_id}]}

    def budget(state):
        return {"worklist": list(state["directions"]), "phase": "dispatch",
                "trail": [{"kind": "budget"}]}

    def dispatch(state):
        direction = state["current_direction"]
        return {"trail": [{"kind": "hunt", "revival_key": direction.unit_id}]}

    final = _drive(build_hunting_graph(
        reason_node=reason, budget_node=budget, dispatch_node=dispatch,
    ), _initial([p1, p2]))

    assert [d.unit_id for d in final["directions"]] == ["u-1", "u-2"]
    assert [t["kind"] for t in final["trail"]] == ["gate", "gate", "budget", "hunt", "hunt"]


# --- Fail-open: a raising stretch carries the fault, the pass still ENDs -------

def test_raising_reason_stretch_carries_the_pair_and_reaches_end():
    p1 = _candidate("u-1", "f-1")
    visits: list[tuple] = []

    def reason(state):
        raise RuntimeError("gate reasoning failed (fixture)")

    def dispatch(state):
        direction = state["current_direction"]
        visits.append(("dispatch", direction.unit_id))
        return {"trail": []}

    final = _drive(build_hunting_graph(
        reason_node=reason, dispatch_node=dispatch,
    ), _initial([p1]))

    assert [d.unit_id for d in final["directions"]] == ["u-1"]
    assert visits == [("dispatch", "u-1")]
    assert final["worklist"] == []