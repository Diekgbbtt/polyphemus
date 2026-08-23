"""Unit tier: the hunt-orchestrator graph engine's topology skeleton (#110,
reworked by #167).

Task 1 pins the StateGraph topology only (no LLM, no Neo4j): the graph builds
and compiles; the supervisor-state schedule loop pops FAULT work items (the
fault stays the schedule unit, spec 3.1) and iterates each fault's candidate
queue as the pairs the phase nodes operate on; every (unit, fault) pair runs
the three phase nodes `hypothesise -> ratify -> note` (the phase machine is
embedded in the graph - G2), the loop states transition
`HYPOTHESISED -> RATIFIED -> NOTED` as the graph executes (G5), the graph ENDs
after the last pair's note phase, and a routing decision is a SINGLE `Command`
(DP-5: both-paths-fire cannot occur); the `trail` and `loop_states` reducers
append rather than overwrite; an empty schedule ENDs with nothing; and a
raising hypothesise seam skips that phase's side effect (fail-open) while the
pass still reaches END.

The dispatch node is REMOVED (G12) and the O9 budget stage is REMOVED (G7) -
the graph ENDs at the REASON stretch. The O1-O10 canon semantics live in
`test_hunt_orchestrator.py` and the integration catalogue - this tier never
repeats them.
"""
import asyncio

from langgraph.graph import END
from langgraph.types import Command

from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    FaultWorkItem,
    Witness,
)
from polymerhus.attack.hunting.orchestrator_graph import (
    _HYPOTHESISE,
    _NOTE,
    _RATIFY,
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


def _fault_grouped(candidates: list[DeliveredCandidate]) -> list[FaultWorkItem]:
    """The schedule group (spec 3.1): ONE `FaultWorkItem` per distinct
    fault_class, in deterministic (input) order."""
    grouped: dict[str, list[DeliveredCandidate]] = {}
    for c in candidates:
        grouped.setdefault(c.fault_class, []).append(c)
    return [FaultWorkItem(fault_class=f, candidates=grouped[f])
            for f in grouped]


def _initial(pairs) -> dict:
    return {
        "project_id": "project-1",
        "run_id": "run-1",
        "schedule": _fault_grouped(list(pairs)),
        "current": None,
        "pairs": [],
        "current_pair": None,
        "loop_state": None,
        "loop_states": [],
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


# --- The phase machine: hypothesise -> ratify -> note per pair, then END ------

def test_reason_stretch_runs_three_phase_nodes_per_pair_and_ends():
    p1, p2 = _candidate("u-1", "f-1"), _candidate("u-2", "f-2")
    visits: list[tuple] = []

    def hypothesise(state):
        pair = state["current_pair"]
        visits.append(("hypothesise", pair.unit_id))
        return {"trail": [{"kind": "hypothesised", "revival_key": pair.unit_id}]}

    def ratify(state):
        pair = state["current_pair"]
        visits.append(("ratify", pair.unit_id))
        return {"trail": [{"kind": "ratified", "revival_key": pair.unit_id}]}

    def note(state):
        pair = state["current_pair"]
        visits.append(("note", pair.unit_id))
        return {"trail": [{"kind": "note", "revival_key": pair.unit_id}]}

    final = _drive(build_hunting_graph(
        hypothesise_node=hypothesise, ratify_node=ratify, note_node=note,
    ), _initial([p1, p2]))

    # each pair runs hypothesise -> ratify -> note in order; the graph ENDs
    # after the last pair's note phase (no dispatch node, no budget stage).
    assert visits == [
        ("hypothesise", "u-1"), ("ratify", "u-1"), ("note", "u-1"),
        ("hypothesise", "u-2"), ("ratify", "u-2"), ("note", "u-2"),
    ]
    assert final["current_pair"].unit_id == "u-2"  # last-write keeps the last pair
    assert final["loop_state"] == "NOTED"          # the pair loop ended at the note phase


def test_no_dispatch_or_budget_nodes():
    """The dispatch node is REMOVED (G12) and the budget stage is REMOVED (G7):
    the graph has EXACTLY the supervisor + the three phase nodes."""
    g = build_hunting_graph(
        hypothesise_node=lambda state: {}, ratify_node=lambda state: {},
        note_node=lambda state: {},
    )
    assert set(g.nodes) == {"supervisor", "hypothesise", "ratify", "note"}


# --- Loop states: the phase machine transitions as the graph executes (G2/G5) --

def test_loop_states_transition_hypothesised_ratified_noted():
    """The harness loop states are tracked on the graph state as it executes:
    the hypothesise node records HYPOTHESISED, the ratify node RATIFIED, the
    note node NOTED - and each phase node observes the PREVIOUS phase's state
    (the transition logic is embedded in the graph, never a harness variable)."""
    p1 = _candidate("u-1", "f-1")
    seen: list[tuple] = []

    def hypothesise(state):
        seen.append(("hypothesise", state["loop_state"]))
        return {}

    def ratify(state):
        seen.append(("ratify", state["loop_state"]))
        return {}

    def note(state):
        seen.append(("note", state["loop_state"]))
        return {}

    final = _drive(build_hunting_graph(
        hypothesise_node=hypothesise, ratify_node=ratify, note_node=note,
    ), _initial([p1]))

    assert seen == [
        ("hypothesise", None),      # a fresh pair starts outside the machine
        ("ratify", "HYPOTHESISED"), # the hypothesise node just ran
        ("note", "RATIFIED"),       # the ratify node just ran
    ]
    assert final["loop_states"] == ["HYPOTHESISED", "RATIFIED", "NOTED"]
    assert final["loop_state"] == "NOTED"


# --- Routing: one authority, one Command (DP-5) ---------------------------------

def test_supervisor_routes_a_pair_per_command_and_ends():
    head = _candidate("u-1", "f-1")
    tail = _candidate("u-2", "f-2")
    schedule = _fault_grouped([head, tail])

    # the first pop seeds the fault's pair queue and routes to hypothesise
    cmd = _supervisor({"schedule": schedule, "pairs": []})
    assert isinstance(cmd, Command)
    assert cmd.goto == _HYPOTHESISE
    assert cmd.update["current"].fault_class == "f-1"
    assert cmd.update["current_pair"].unit_id == "u-1"
    assert cmd.update["pairs"] == []          # one pair popped, queue drained
    assert cmd.update["schedule"] == schedule[1:]

    # the next super-step pops the second fault's pair
    cmd = _supervisor({"schedule": schedule[1:], "pairs": []})
    assert isinstance(cmd, Command)
    assert cmd.goto == _HYPOTHESISE
    assert cmd.update["current"].fault_class == "f-2"
    assert cmd.update["current_pair"].unit_id == "u-2"

    # a fault with two candidates: the supervisor pops the queue one pair at a
    # time, and only pops the next fault once the queue is drained
    pair_fault = FaultWorkItem(fault_class="f-3", candidates=[
        _candidate("u-3", "f-3"), _candidate("u-4", "f-3")])
    cmd = _supervisor({"schedule": [pair_fault], "pairs": []})
    assert cmd.goto == _HYPOTHESISE
    assert cmd.update["current_pair"].unit_id == "u-3"
    assert [c.unit_id for c in cmd.update["pairs"]] == ["u-4"]
    assert cmd.update["schedule"] == []

    cmd = _supervisor({"schedule": [], "pairs": [pair_fault.candidates[1]]})
    assert cmd.goto == _HYPOTHESISE
    assert cmd.update["current_pair"].unit_id == "u-4"

    # schedule AND queue exhausted -> END
    cmd = _supervisor({"schedule": [], "pairs": []})
    assert isinstance(cmd, Command)
    assert cmd.goto == END


def test_empty_schedule_ends_with_nothing():
    visits: list[str] = []

    def hypothesise(state):
        visits.append("hypothesise")  # pragma: no cover - must never be reached
        return {}

    final = _drive(build_hunting_graph(hypothesise_node=hypothesise), _initial([]))

    assert visits == []
    assert final["loop_state"] is None
    assert final["loop_states"] == []


# --- Reducers: accumulate, never overwrite --------------------------------------

def test_trail_and_loop_states_reduce_append_not_overwrite():
    p1, p2 = _candidate("u-1", "f-1"), _candidate("u-2", "f-2")

    def hypothesise(state):
        pair = state["current_pair"]
        return {"trail": [{"kind": "hypothesised", "revival_key": pair.unit_id}]}

    def ratify(state):
        pair = state["current_pair"]
        return {"trail": [{"kind": "ratified", "revival_key": pair.unit_id}]}

    def note(state):
        pair = state["current_pair"]
        return {"trail": [{"kind": "note", "revival_key": pair.unit_id}]}

    final = _drive(build_hunting_graph(
        hypothesise_node=hypothesise, ratify_node=ratify, note_node=note,
    ), _initial([p1, p2]))

    assert [t["kind"] for t in final["trail"]] == [
        "hypothesised", "ratified", "note",
        "hypothesised", "ratified", "note",
    ]
    assert final["loop_states"] == [
        "HYPOTHESISED", "RATIFIED", "NOTED",
        "HYPOTHESISED", "RATIFIED", "NOTED",
    ]


# --- Fail-open: a raising seam skips the phase's side effect, the pass ENDs ----

def test_raising_hypothesise_skips_side_effect_and_keeps_the_pass_serving():
    p1 = _candidate("u-1", "f-1")
    visits: list[tuple] = []

    def hypothesise(state):
        raise RuntimeError("hypothesise turn failed (fixture)")

    def ratify(state):
        visits.append(("ratify", state["current_pair"].unit_id))
        return {}

    def note(state):
        visits.append(("note", state["current_pair"].unit_id))
        return {}

    final = _drive(build_hunting_graph(
        hypothesise_node=hypothesise, ratify_node=ratify, note_node=note,
    ), _initial([p1]))

    # the failing hypothesise skipped its side effect, but the phase machine
    # still advanced: ratify and note ran, the loop states transitioned, END.
    assert visits == [("ratify", "u-1"), ("note", "u-1")]
    assert final["loop_states"] == ["HYPOTHESISED", "RATIFIED", "NOTED"]
    assert final["loop_state"] == "NOTED"
    assert final["current_pair"].unit_id == "u-1"


def test_missing_seams_skip_side_effects_but_keep_the_pass_serving():
    """Every default node degrades fail-open (the canon's no-seam outcome): a
    graph with NO injected closures still runs the phase machine (the loop
    states transition) and reaches END without a dispatch node or budget stage."""
    p1 = _candidate("u-1", "f-1")
    final = _drive(build_hunting_graph(), _initial([p1]))
    assert final["loop_states"] == ["HYPOTHESISED", "RATIFIED", "NOTED"]
    assert final["loop_state"] == "NOTED"