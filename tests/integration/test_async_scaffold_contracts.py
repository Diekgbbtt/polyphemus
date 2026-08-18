"""Contract predicates (integration tier) for increment 2a - the async supervisor
scaffold wrapping the legacy passes (#24). Mechanises C1-C5.

The writing curator, the proposer cargo, and the async driver with an injected
Store + inert observability. No live Neo4j/Postgres/Langfuse. Expected values from
the spec. Verifier-gated; not selected by the tdd unit loop.
"""
import asyncio

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from polymerhus.analysis.analyser_types import L1DeltaBatch, ServiceProposal
from polymerhus.analysis.messages import AgentDispatch, Chunk, ProposalEnvelope
from polymerhus.analysis.pod import AnalyserExport
from polymerhus.analysis.supervisor import (
    _make_curator,
    _make_proposer,
    build_supervisor_graph,
    run_supervisor,
)

BATCH = L1DeltaBatch(services=[ServiceProposal(business_function_slug="checkout")])


# --- C1: writing curator maps an export to a written receipt -------------------

def test_C1_writing_curator_maps_export_to_written_receipt():
    export = AnalyserExport(services_written=1, systems_written=2, aggregates_written=3,
                            enrichment={"data_items": 4})
    curator = _make_curator(write_fn=lambda deltas, pid, prov: export)
    env = ProposalEnvelope(dispatch_id="d1", role="assigner", phase="A1", deltas=BATCH)
    out = curator({"inflight": env, "project_id": "p1", "run_id": "r1"})
    (receipt,) = out["receipts"]
    assert receipt.status == "written"
    assert receipt.written.services == 1
    assert receipt.written.systems == 2
    assert receipt.written.aggregates == 3
    assert receipt.written.enrichment == 4


# --- C2: hollow envelope passes through empty even with a write_fn -------------

def test_C2_empty_envelope_does_not_call_write_fn():
    calls = []
    curator = _make_curator(write_fn=lambda deltas, pid, prov: calls.append(1))
    env = ProposalEnvelope(dispatch_id="d1", role="assigner", phase="A1")  # deltas None
    out = curator({"inflight": env, "project_id": "p1", "run_id": "r1"})
    (receipt,) = out["receipts"]
    assert receipt.status == "empty"
    assert calls == []  # write_fn never invoked
    assert receipt.written.services == 0


# --- C3: a write error degrades, never crashes --------------------------------

def test_C3_write_error_degrades():
    def boom(deltas, pid, prov):
        raise RuntimeError("boom")

    curator = _make_curator(write_fn=boom)
    env = ProposalEnvelope(dispatch_id="d1", role="assigner", phase="A1", deltas=BATCH)
    out = curator({"inflight": env, "project_id": "p1", "run_id": "r1"})
    (receipt,) = out["receipts"]
    assert receipt.status == "degraded"
    assert "boom" in (receipt.error or "")


# --- C4: async driver runs with an injected Store + inert observability --------

def test_C4_run_supervisor_with_injected_store_no_db():
    schedule = [AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", chunk=Chunk(chunk_id="c"))]
    final = asyncio.run(run_supervisor(
        "p1", "r1", schedule,
        checkpointer=MemorySaver(), store=InMemoryStore(), observe=True,
    ))
    # hollow bodies -> one empty receipt; no DB touched, empty callbacks inert
    assert [r.status for r in final["receipts"]] == ["empty"]


# --- C5: a proposer body returning a batch rides the envelope -----------------

def test_C5_proposer_body_batch_rides_envelope():
    node = _make_proposer("assigner", lambda dispatch, state: BATCH)
    d = AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", chunk=Chunk(chunk_id="c"))
    out = node({"dispatch": d})
    assert out["inflight"].deltas is BATCH
