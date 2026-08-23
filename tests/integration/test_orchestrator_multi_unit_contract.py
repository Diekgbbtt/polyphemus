"""Integration tier: the multi-unit fault contract (spec 3.1 / section 8).

A pass whose candidate set carries TWO matched units under ONE `fault_class`
must budget exactly ONE `reason_fn` gate turn for that fault (never one per
unit), hand that turn a `GateInput` whose `candidates` holds BOTH units, fan
each carried direction out into one `HuntConfig` per distinct class, dispatch
every minted config, land a `notes` record per unit, and accumulate the
`LoopLedger`. A candidate under a SECOND distinct fault in the same pass must
produce a SEPARATE `reason_fn` call.

The harness is a real `HuntStore` bound onto `OrchestratorTools` (the
integration-style `_tools` seam) and a spy `reason_fn`; no live model, no live
database.
"""
import uuid

from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    DispatchResult,
    EnvisionedDirection,
    GateDecision,
    OrchestratorReport,
    OrchestratorTools,
    ReadOnlyGraphView,
    Witness,
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


def _ok_dispatch(calls: list | None = None):
    record = calls if calls is not None else []

    def dispatch(config, routed=()):
        record.append((config, tuple(routed)))
        return DispatchResult(
            spec_ref=f"spec-{len(record)}",
            pod_result_ref=f"pod-{len(record)}",
            hypothesis_verdict="successful",
            feedback="fixture feedback",
        )

    return dispatch


def _tools(store: HuntStore) -> OrchestratorTools:
    return OrchestratorTools(
        back_edge=None,
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=lambda cy, p: []),
    )


def _run(store: HuntStore, candidates, *, reason_fn, dispatch=None) -> OrchestratorReport:
    return run_orchestration(
        project_id="project-1",
        run_id=RUN_ID,
        candidates=candidates,
        tools=_tools(store),
        reason_fn=reason_fn,
        dispatch_fn=dispatch or _ok_dispatch(),
    )


def test_two_units_one_fault_reason_once_with_both_candidates(tmp_path):
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    dispatched: list = []
    a = _candidate(SERVICE_A, FAULT_CSRF)
    b = _candidate(SERVICE_B, FAULT_CSRF)

    def reason_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    report = _run(store, [a, b], reason_fn=reason_fn, dispatch=_ok_dispatch(dispatched))

    # point 1: ONE gate turn for the fault, carrying BOTH units
    assert len(gate_inputs) == 1
    assert {c.unit_id for c in gate_inputs[0].candidates} == {SERVICE_A, SERVICE_B}

    # point 2: every config minted at the unit boundary is dispatched
    assert report.hunts_dispatched == 2
    assert len(report.hunt_ids) == 2
    assert len(set(report.hunt_ids)) == 2
    assert {c.unit_id for c, _ in dispatched} == {SERVICE_A, SERVICE_B}

    # point 3: the harness lands a note per unit in memory.yaml and the ledger accumulates
    notes = store.read_notes("project-1")
    assert {n["revival_key"].split("::")[0] for n in notes} == {SERVICE_A, SERVICE_B}
    ledger = report.ledger
    assert ledger.units_done == 2
    assert set(ledger.minted_config_keys) == {
        f"{SERVICE_A}::{FAULT_CSRF}", f"{SERVICE_B}::{FAULT_CSRF}"}
    assert ledger.notes_recorded == 2


def test_two_distinct_faults_reason_once_each(tmp_path):
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    a = _candidate(SERVICE_A, FAULT_CSRF)
    c = _candidate(SERVICE_A, FAULT_IDOR)

    def reason_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[_carry(x) for x in inp.candidates])

    report = _run(store, [a, c], reason_fn=reason_fn)

    # point 4: two faults -> two SEPARATE gate turns, one per distinct fault.
    # The schedule is risk-descending (fault_risk, f8b5203): CWE-639 (IDOR, the
    # broken-access-control tier) always precedes CWE-352 (CSRF), so assert the
    # SET of faults, never their order.
    assert len(gate_inputs) == 2
    assert {inp.candidates[0].fault_class for inp in gate_inputs} == {FAULT_CSRF, FAULT_IDOR}
    assert all(len(inp.candidates) == 1 for inp in gate_inputs)
    assert report.hunts_dispatched == 2
    assert report.ledger.units_done == 2
    assert report.ledger.notes_recorded == 2


def test_shared_fault_does_not_refire_reason_per_unit(tmp_path):
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    candidates = [_candidate(f"S{i}", FAULT_CSRF) for i in range(3)]

    def reason_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[
            _carry(x) for x in inp.candidates])

    report = _run(store, candidates, reason_fn=reason_fn)

    # one fault -> exactly one gate turn however many units share it
    assert len(gate_inputs) == 1
    assert len(gate_inputs[0].candidates) == 3
    assert report.hunts_dispatched == 3
    assert report.ledger.units_done == 3
    assert report.ledger.notes_recorded == 3


def test_reason_fn_called_once_per_distinct_fault_and_not_per_candidate(tmp_path):
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    a = _candidate(SERVICE_A, FAULT_CSRF)
    b = _candidate(SERVICE_B, FAULT_CSRF)
    c = _candidate(SERVICE_A, FAULT_IDOR)

    def reason_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[_carry(x) for x in inp.candidates])

    report = _run(store, [a, b, c], reason_fn=reason_fn)

    # three units, two distinct faults -> two gate turns
    assert len(gate_inputs) == 2
    by_fault = {inp.candidates[0].fault_class: inp for inp in gate_inputs}
    assert set(by_fault) == {FAULT_CSRF, FAULT_IDOR}
    assert len(by_fault[FAULT_CSRF].candidates) == 2
    assert len(by_fault[FAULT_IDOR].candidates) == 1
    assert report.hunts_dispatched == 3
