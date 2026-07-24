"""Walkthrough predicates (e2e tier) for increment 2a - the async supervisor
scaffold wrapping the legacy passes (#24). Mechanises E1 (output identity) and E2
(the supervised terminal receipt).

Pure fakes for read/analyse/curate; injected MemorySaver + InMemoryStore; no live
Neo4j/Postgres/Langfuse. Expected values from the spec. Verifier-gated.
"""
import asyncio

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from polymerhus.analysis.analyser_types import L1DeltaBatch, ServiceProposal
from polymerhus.analysis.messages import AgentDispatch, Chunk
from polymerhus.analysis.pod import AnalyserExport, build_analyser_graph, run_analyser
from polymerhus.analysis.supervisor import (
    build_supervisor_graph,
    run_analyser_supervised,
    run_supervisor,
)

BATCH = L1DeltaBatch(services=[
    ServiceProposal(business_function_slug="checkout"),
    ServiceProposal(business_function_slug="pay"),
])


def _fakes():
    def read_fn(pid):
        return {"nodes": [{"properties": {"project_id": pid}}], "links": []}

    def analyse_fn(l0_slice, obs):
        return BATCH

    def curate_fn(batch, pid, prov):
        return AnalyserExport(services_written=len(batch.services), systems_written=1, aggregates_written=3)

    return read_fn, analyse_fn, curate_fn


# --- E1: output identity - legacy (flag OFF) == supervised (flag ON) ----------

def test_E1_legacy_and_supervised_outputs_are_identical():
    read_fn, analyse_fn, curate_fn = _fakes()

    legacy_graph = build_analyser_graph(read_fn=read_fn, analyse_fn=analyse_fn, curate_fn=curate_fn)
    exp_legacy = run_analyser("p1", "r1", observations=[], graph=legacy_graph, supervisor_enabled=False)

    exp_supervised = run_analyser_supervised(
        "p1", "r1", observations=[],
        read_fn=read_fn, analyse_fn=analyse_fn, curate_fn=curate_fn,
        checkpointer=MemorySaver(), store=InMemoryStore(), observe=False,
    )

    assert exp_legacy == exp_supervised
    assert exp_supervised.services_written == 2
    assert exp_supervised.systems_written == 1
    assert exp_supervised.aggregates_written == 3


# --- E2: the supervised run's terminal receipt --------------------------------

def test_E2_supervised_run_terminal_written_receipt():
    read_fn, analyse_fn, curate_fn = _fakes()

    def legacy_body(dispatch, state):
        return analyse_fn(state.get("l0_slice") or {}, state.get("observations") or [])

    builder = build_supervisor_graph(
        proposer_bodies={"assigner": legacy_body},
        write_fn=lambda deltas, pid, prov: curate_fn(deltas, pid, prov),
    )
    schedule = [AgentDispatch(dispatch_id="r1", role="assigner", phase="A1", chunk=Chunk(chunk_id="r1"))]
    final = asyncio.run(run_supervisor(
        "p1", "r1", schedule, builder=builder,
        l0_slice=read_fn("p1"), observations=[],
        checkpointer=MemorySaver(), store=InMemoryStore(), observe=False,
    ))

    receipts = final["receipts"]
    assert len(receipts) == 1
    assert receipts[0].dispatch_id == "r1"
    assert receipts[0].status == "written"
    assert receipts[0].written.services == 2
    assert receipts[0].written.systems == 1
    assert receipts[0].written.aggregates == 3
