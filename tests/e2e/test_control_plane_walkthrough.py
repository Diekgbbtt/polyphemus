"""Walkthrough predicates (e2e tier) for increment 0 - the analyser control plane
(#22). Mechanises E1-E6 of the assertion catalogue attached to #22.

Each traces one full schedule through the COMPILED async supervisor via `ainvoke`
with an injected `MemorySaver` (no live Postgres, no Neo4j - the control plane is
hollow and writes nothing). `asyncio.run` drives the async graph from a sync test
body (this repo has no pytest-asyncio). Expected quantities are taken from the spec.

These gate the verifier and are NOT selected by the tdd unit red/green loop.
"""
import asyncio

from langgraph.checkpoint.memory import MemorySaver

from polymerhus.analysis.messages import AgentDispatch, Chunk, PROPOSER_ROLES
from polymerhus.analysis.supervisor import build_supervisor_graph, run_supervisor


def _drive(schedule, *, builder=None, run_id="r"):
    return asyncio.run(
        run_supervisor("p1", run_id, schedule, checkpointer=MemorySaver(), builder=builder)
    )


# --- E1: happy N-dispatch sequence --------------------------------------------

def test_E1_three_dispatch_schedule_yields_three_empty_receipts_in_order():
    schedule = [
        AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", mode="create", chunk=Chunk(chunk_id="c1")),
        AgentDispatch(dispatch_id="d2", role="mechanism_typist", phase="A1", mode="create", chunk=Chunk(chunk_id="c2")),
        AgentDispatch(dispatch_id="d3", role="data_modeller", phase="A2", mode="create", chunk=Chunk(chunk_id="c3")),
    ]
    # instrument every proposer to count invocations
    calls = {r: 0 for r in PROPOSER_ROLES}
    bodies = {r: (lambda d, s, _r=r: calls.__setitem__(_r, calls[_r] + 1)) for r in PROPOSER_ROLES}
    builder = build_supervisor_graph(proposer_bodies=bodies)

    final = _drive(schedule, builder=builder, run_id="r1")
    receipts = final["receipts"]

    assert [r.dispatch_id for r in receipts] == ["d1", "d2", "d3"]  # schedule order
    assert all(r.status == "empty" for r in receipts)
    assert all(r.written.services == 0 and r.written.aggregates == 0 for r in receipts)  # 0 writes
    assert calls == {"assigner": 1, "mechanism_typist": 1, "data_modeller": 1,
                     "bootstrapper": 0, "anti_cluttering": 0}  # each routed proposer once


# --- E2: empty schedule is a valid zero-work run ------------------------------

def test_E2_empty_schedule_terminates_with_zero_receipts_no_error():
    final = _drive([], run_id="r2")
    assert final["receipts"] == []  # 0 entries, clean termination


# --- E3: replayed dispatch_id yields exactly one receipt ----------------------

def test_E3_replayed_dispatch_id_leaves_one_receipt():
    schedule = [
        AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", mode="create", chunk=Chunk(chunk_id="c1")),
        AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", mode="reflect", chunk=Chunk(chunk_id="c2")),
    ]
    final = _drive(schedule, run_id="r3")
    receipts = final["receipts"]
    assert len(receipts) == 1
    assert receipts[0].dispatch_id == "d1"


# --- E4: a degrading step does not abort the run ------------------------------

def test_E4_middle_raising_stub_degrades_run_still_terminates():
    def boom(dispatch, state):
        raise RuntimeError("boom")

    builder = build_supervisor_graph(proposer_bodies={"mechanism_typist": boom})
    schedule = [
        AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", chunk=Chunk(chunk_id="c1")),
        AgentDispatch(dispatch_id="d2", role="mechanism_typist", phase="A1", chunk=Chunk(chunk_id="c2")),
        AgentDispatch(dispatch_id="d3", role="data_modeller", phase="A2", chunk=Chunk(chunk_id="c3")),
    ]
    final = _drive(schedule, builder=builder, run_id="r4")
    receipts = final["receipts"]
    assert [r.status for r in receipts] == ["empty", "degraded", "empty"]  # schedule order
    assert "boom" in (receipts[1].error or "")


# --- E5: coexistence two-way door - flag OFF returns identical legacy export ---

def test_E5_flag_off_run_analyser_returns_identical_legacy_export():
    from polymerhus.analysis.pod import AnalyserExport, run_analyser

    known = AnalyserExport(services_written=2, systems_written=1, aggregates_written=5)

    class _Legacy:
        def __init__(self):
            self.calls = 0

        def invoke(self, state):
            self.calls += 1
            return {"export": known}

    legacy = _Legacy()
    sup_calls = []

    def spy_supervisor(pid, rid, obs):
        sup_calls.append((pid, rid))
        return AnalyserExport()

    out = run_analyser(
        "p1", "r5", observations=[], graph=legacy,
        supervisor_enabled=False, run_supervisor_fn=spy_supervisor,
    )
    assert out == known  # field-for-field identical to the injected legacy export
    assert legacy.calls == 1
    assert sup_calls == []  # the supervisor was never compiled/driven


# --- E6: single-path routing (the both-paths-fire pitfall is absent) ----------

def test_E6_single_dispatch_runs_only_the_routed_proposer():
    calls = {r: 0 for r in PROPOSER_ROLES}
    bodies = {r: (lambda d, s, _r=r: calls.__setitem__(_r, calls[_r] + 1)) for r in PROPOSER_ROLES}
    builder = build_supervisor_graph(proposer_bodies=bodies)
    schedule = [AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", chunk=Chunk(chunk_id="c"))]

    final = _drive(schedule, builder=builder, run_id="r6")
    assert calls["assigner"] == 1
    assert sum(calls.values()) == 1  # exactly one of the five proposers ran
    assert len(final["receipts"]) == 1
