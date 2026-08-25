"""Integration tier: the multi-unit fault contract (spec 3.1 / section 8,
re-scoped by #167).

The pair-iteration decision (documented, spec 3.2): the supervisor pops FAULT
work items (the fault stays the schedule unit) and iterates each fault's
candidate queue as the pairs the phase nodes operate on - so the hypothesise
turn fires ONCE PER PAIR (one candidate per turn), never per fault over the
batched set. Every pair runs hypothesise -> ratify -> note; the ratify phase
amends each draft to ratified; the note phase lands a note per pair; and the
`LoopLedger` accumulates across the pairs. A candidate under a SECOND distinct
fault in the same pass produces a SEPARATE hypothesise call.

The harness is a real `HuntStore` bound onto `OrchestratorTools` (the
integration-style `_tools` seam) and spy phase seams; no live model, no live
database.
"""
import uuid

from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    EnvisionedDirection,
    GateDecision,
    NoteDecision,
    NoteRecord,
    OrchestratorReport,
    OrchestratorTools,
    RatifyDecision,
    ReadOnlyGraphView,
    Witness,
    revival_key,
    run_orchestration,
)
from polymerhus.attack.hunting.hunt_store import HuntStore

SERVICE_A = "Service:slug:a"
SERVICE_B = "Service:slug:b"
FAULT_CSRF = "CWE-352"
FAULT_IDOR = "CWE-639"

RUN_ID = "run-" + uuid.uuid4().hex[:8]


def _candidate(unit_id: str, fault_class: str) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id,
        fault_class=fault_class,
        applies_witnesses=Witness(deterministic="clause-1", llm="clause applies"),
        match_verdict="applies",
    )


def _carry(candidate: DeliveredCandidate) -> EnvisionedDirection:
    return EnvisionedDirection(
        unit_id=candidate.unit_id,
        fault_class=candidate.fault_class,
        carried=True,
        rationale="carried from the fixture gate",
        assumptions=["fixture assumption"],
        envisioned_test_primitives=["fixture probe"],
        vulnerability_classes=["CSRF"],
    )


def _ratify_drafts(inp) -> RatifyDecision:
    configs = []
    for draft in inp.configs:
        amended = draft.model_copy(deep=True)
        amended.status = "ratified"
        configs.append(amended)
    return RatifyDecision(configs=configs)


def _note_pair(inp) -> NoteDecision:
    return NoteDecision(notes=[NoteRecord(
        key=revival_key(inp.pair.unit_id, inp.pair.fault_class),
        note="fixture note",
    )])


def _tools(store: HuntStore) -> OrchestratorTools:
    return OrchestratorTools(
        back_edge=None,
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=lambda cy, p: []),
    )


def _run(store: HuntStore, candidates, *, hypothesise_fn, ratify_fn=None,
         note_fn=None) -> OrchestratorReport:
    return run_orchestration(
        project_id="project-1",
        run_id=RUN_ID,
        candidates=candidates,
        tools=_tools(store),
        hypothesise_fn=hypothesise_fn,
        ratify_fn=ratify_fn or _ratify_drafts,
        note_fn=note_fn or _note_pair,
    )


def test_two_units_one_fault_hypothesise_once_per_pair(tmp_path):
    """The node-per-phase machine (#167): two units under ONE fault run the
    hypothesise phase ONCE PER PAIR (one candidate each), never one turn over
    the batched set; each pair's draft is ratified and noted, the ledger
    accumulates, and the graph ENDs at the note phase."""
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    a = _candidate(SERVICE_A, FAULT_CSRF)
    b = _candidate(SERVICE_B, FAULT_CSRF)

    def hypothesise_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    report = _run(store, [a, b], hypothesise_fn=hypothesise_fn)

    # point 1: ONE hypothesise turn per pair, each carrying exactly its pair
    assert len(gate_inputs) == 2
    assert [{c.unit_id for c in inp.candidates} for inp in gate_inputs] == \
        [{SERVICE_A}, {SERVICE_B}]

    # point 2: every pair's draft is ratified (no dispatch stage - G12)
    assert report.pairs_processed == 2
    assert report.configs_hypothesised == 2
    assert report.configs_ratified == 2
    assert not hasattr(report, "hunts_dispatched")

    # point 3: the harness lands a note per pair in memory.yaml and the ledger accumulates
    notes = store.read_notes("project-1")
    assert {n["revival_key"].split("::")[0] for n in notes} == {SERVICE_A, SERVICE_B}
    ledger = report.ledger
    assert ledger.units_done == 2
    assert set(ledger.minted_config_keys) == {
        f"{SERVICE_A}::{FAULT_CSRF}", f"{SERVICE_B}::{FAULT_CSRF}"}
    assert ledger.notes_recorded == 2


def test_two_distinct_faults_hypothesise_once_each(tmp_path):
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    a = _candidate(SERVICE_A, FAULT_CSRF)
    c = _candidate(SERVICE_A, FAULT_IDOR)

    def hypothesise_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[_carry(x) for x in inp.candidates])

    report = _run(store, [a, c], hypothesise_fn=hypothesise_fn)

    # point 4: two faults -> two SEPARATE hypothesise turns, one per pair.
    # The schedule is risk-descending (fault_risk, f8b5203): CWE-639 (IDOR, the
    # broken-access-control tier) always precedes CWE-352 (CSRF), so assert the
    # SET of faults, never their order.
    assert len(gate_inputs) == 2
    assert {inp.candidates[0].fault_class for inp in gate_inputs} == {FAULT_CSRF, FAULT_IDOR}
    assert all(len(inp.candidates) == 1 for inp in gate_inputs)
    assert report.pairs_processed == 2
    assert report.configs_ratified == 2
    assert report.ledger.units_done == 2
    assert report.ledger.notes_recorded == 2


def test_shared_fault_hypothesises_per_pair_not_per_fault(tmp_path):
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    candidates = [_candidate(f"S{i}", FAULT_CSRF) for i in range(3)]

    def hypothesise_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[
            _carry(x) for x in inp.candidates])

    report = _run(store, candidates, hypothesise_fn=hypothesise_fn)

    # one fault -> one hypothesise turn PER PAIR (the phase nodes operate per
    # (unit, fault) pair, #167); each pair's draft is ratified
    assert len(gate_inputs) == 3
    assert all(len(inp.candidates) == 1 for inp in gate_inputs)
    assert report.pairs_processed == 3
    assert report.configs_ratified == 3
    assert report.ledger.units_done == 3
    assert report.ledger.notes_recorded == 3


def test_hypothesise_called_once_per_pair_and_not_per_fault_batch(tmp_path):
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    a = _candidate(SERVICE_A, FAULT_CSRF)
    b = _candidate(SERVICE_B, FAULT_CSRF)
    c = _candidate(SERVICE_A, FAULT_IDOR)

    def hypothesise_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[_carry(x) for x in inp.candidates])

    report = _run(store, [a, b, c], hypothesise_fn=hypothesise_fn)

    # three units, two distinct faults -> three pair turns
    assert len(gate_inputs) == 3
    by_fault = {inp.candidates[0].fault_class for inp in gate_inputs}
    assert by_fault == {FAULT_CSRF, FAULT_IDOR}
    assert all(len(inp.candidates) == 1 for inp in gate_inputs)
    assert report.pairs_processed == 3
    assert report.configs_ratified == 3