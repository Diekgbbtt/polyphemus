"""Contract predicates (integration tier) for increment 0 - the analyser control
plane (#22). Mechanises C1-C7 of the assertion catalogue attached to #22.

These range over the typed VO boundary, the `merge_receipts` reducer, the curator
and proposer nodes, and the `run_analyser` flag branch. They touch NO Neo4j (the
control plane is hollow and writes nothing); the path-based `live_neo4j` mark this
tree carries is a no-op here. Expected values come from the spec, not recomputed.

These gate the verifier and are NOT selected by the tdd unit red/green loop.
"""
import asyncio

import pytest

from polymerhus.analysis.messages import (
    AgentDispatch,
    Chunk,
    ProposalEnvelope,
    StepReceipt,
    SweepCursor,
    WriteCounts,
)
from polymerhus.analysis.supervisor import (
    SupervisorState,
    _make_curator,
    _make_proposer,
    merge_receipts,
)
from polymerhus.analysis.pod import AnalyserExport, run_analyser


# --- C1: ProposalEnvelope total defaults + immutability (empty-valid) ---------

def test_C1_proposal_envelope_bare_construct_defaults_and_is_frozen():
    e = ProposalEnvelope(dispatch_id="d1", role="assigner", phase="A1")
    assert e.deltas is None
    assert e.anatomy is None
    assert e.curation is None
    assert e.verdicts == []
    assert e.status == "empty"
    assert e.error is None
    with pytest.raises(Exception):  # frozen: a mutation attempt raises
        e.status = "written"


# --- C2: AgentDispatch exactly-one-of-chunk/sweep_cursor (malformed) ----------

def test_C2a_dispatch_with_both_chunk_and_cursor_is_rejected():
    with pytest.raises(ValueError):
        AgentDispatch(
            dispatch_id="d1", role="assigner", phase="A1",
            chunk=Chunk(chunk_id="c"), sweep_cursor=SweepCursor(),
        )


def test_C2b_dispatch_with_chunk_only_is_accepted():
    d = AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", chunk=Chunk(chunk_id="c"))
    assert d.chunk is not None and d.sweep_cursor is None


def test_C2c_sliceless_bootstrapper_with_neither_is_accepted():
    d = AgentDispatch(dispatch_id="d1", role="bootstrapper", phase="bootstrap")
    assert d.chunk is None and d.sweep_cursor is None


def test_C2d_non_sliceless_role_with_neither_is_rejected():
    with pytest.raises(ValueError):
        AgentDispatch(dispatch_id="d1", role="assigner", phase="A1")


# --- C3: merge_receipts dedup-by-dispatch_id (duplicate-idempotent) -----------

def test_C3_merge_receipts_dedups_by_dispatch_id_replaying_replaces_in_place():
    r1 = StepReceipt(dispatch_id="d1", role="assigner", phase="A1", status="empty")
    r2 = StepReceipt(dispatch_id="d2", role="assigner", phase="A1", status="empty")
    trail = merge_receipts([], [r1])
    trail = merge_receipts(trail, [r2])
    assert len(trail) == 2  # two distinct ids
    r1b = StepReceipt(dispatch_id="d1", role="assigner", phase="A1", status="written")
    trail = merge_receipts(trail, [r1b])
    assert len(trail) == 2  # replay of d1 does NOT append -> twice yields one
    survivor = next(r for r in trail if r.dispatch_id == "d1")
    assert survivor.status == "written"  # the replacement, not the original


# --- C4: curator on an empty baton -> StepReceipt(empty) with zero counts ------

def test_C4_curator_maps_empty_envelope_to_empty_receipt_zero_counts():
    env = ProposalEnvelope(dispatch_id="d1", role="assigner", phase="A1", status="empty")
    out = _make_curator(None)({"inflight": env})  # hollow curator (increment 0)
    (receipt,) = out["receipts"]
    assert isinstance(receipt, StepReceipt)
    assert receipt.status == "empty"
    assert receipt.written == WriteCounts()  # all-zero
    assert receipt.error is None
    assert receipt.status in {"written", "empty", "degraded"}


# --- C5: a raising proposer degrades, never crashes (degradation) -------------

def test_C5_raising_proposer_degrades_to_degraded_envelope():
    def boom(dispatch, state):
        raise RuntimeError("boom")

    node = _make_proposer("assigner", boom)
    d = AgentDispatch(dispatch_id="d1", role="assigner", phase="A1", chunk=Chunk(chunk_id="c"))
    out = node({"dispatch": d})  # no exception propagates
    env = out["inflight"]
    assert env.status == "degraded"
    assert "boom" in (env.error or "")


# --- C6: state channels - receipts is the sole accumulator (reducer contract) --

def test_C6_receipts_is_the_only_reducer_channel_no_proposals_accumulator():
    # the receipts reducer ACCUMULATES distinct ids...
    a = StepReceipt(dispatch_id="d1", role="assigner", phase="A1")
    b = StepReceipt(dispatch_id="d2", role="assigner", phase="A1")
    assert len(merge_receipts([a], [b])) == 2
    # ...while the state carries NO proposals-accumulator channel (live graph is
    # the accumulator, #17): only `receipts` is annotated with a reducer.
    ann = SupervisorState.__annotations__
    assert "receipts" in ann
    assert not any("proposal" in k.lower() for k in ann)
    assert "dispatch" in ann and "inflight" in ann  # last-write baton channels


# --- C7: run_analyser flag branch - exactly one path per flag value ------------

class _FakeGraph:
    def __init__(self, export):
        self.calls = 0
        self._export = export

    def invoke(self, state):
        self.calls += 1
        return {"export": self._export}


def test_C7_flag_off_runs_legacy_and_not_supervisor():
    known = AnalyserExport(services_written=2, systems_written=1, aggregates_written=5)
    legacy = _FakeGraph(known)
    sup_calls = []

    # #34: the supervisor seam is CHUNK-FED and takes (project_id, run_id) alone.
    # Observations are not passed: the Assigner does not render them (D5), and
    # everything else is re-derived live at dispatch time.
    def spy_supervisor(pid, rid):
        sup_calls.append((pid, rid))
        return AnalyserExport()

    out = run_analyser(
        "p1", "r1", observations=[], graph=legacy,
        supervisor_enabled=False, run_supervisor_fn=spy_supervisor,
    )
    assert out.services_written == 2 and out.systems_written == 1 and out.aggregates_written == 5
    assert legacy.calls == 1 and sup_calls == []  # legacy fired, supervisor did not


def test_C7_flag_on_runs_supervisor_and_not_legacy():
    legacy = _FakeGraph(AnalyserExport(services_written=99))
    sup_calls = []

    # #34: the supervisor seam is CHUNK-FED and takes (project_id, run_id) alone.
    # Observations are not passed: the Assigner does not render them (D5), and
    # everything else is re-derived live at dispatch time.
    def spy_supervisor(pid, rid):
        sup_calls.append((pid, rid))
        return AnalyserExport()

    run_analyser(
        "p1", "r1", observations=[], graph=legacy,
        supervisor_enabled=True, run_supervisor_fn=spy_supervisor,
    )
    assert sup_calls == [("p1", "r1")] and legacy.calls == 0  # supervisor fired, legacy did not
