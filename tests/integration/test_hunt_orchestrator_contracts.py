"""Integration tier: the hunt-orchestrator assertion catalogue C1-C12
(hunting-67-orchestrator-spec.md section 6.1).

The contract predicates exercise the orchestration run against a REAL
append-only markdown hunt-store stub (the #68 persistence seam) with every
out-of-tree collaborator injected: the reasoning turn (the gate), the hunting
agent dispatch (IA-2), the re-match (the #71/#64 LLM match), the KB retrieval
(IA-1/D67-11), and the back-edge (IA-6) all arrive as fixtures - the real
hunting agent is #83's and the real chain is walked in the e2e tier (E1/E2,
blocked). Expected values are taken from the spec, never recomputed the way the
code computes them.
"""
import uuid

import pytest

from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    DispatchResult,
    EnvisionedDirection,
    GateDecision,
    HuntConfig,
    MatchVerdict,
    OrchestratorReport,
    OrchestratorTools,
    ReadOnlyGraphView,
    ReadOnlyGraphViewError,
    TOOL_SURFACE,
    Witness,
    revival_key,
    run_orchestration,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.recon.control.targeted import TargetedReconResult

SERVICE_A = "Service:slug:a"
SYSTEM_B = "System:key:b"
FAULT_X = "fault-x"
FAULT_Y = "fault-y"

RUN_ID = "run-" + uuid.uuid4().hex[:8]


def _candidate(unit_id: str, fault_class: str, *, verdict: str = "applies",
               llm_witness: str | None = "clause x holds",
               deterministic_witness: str | None = None) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id,
        fault_class=fault_class,
        applies_witnesses=Witness(deterministic=deterministic_witness, llm=llm_witness),
        match_verdict=verdict,
    )


def _carry(candidate: DeliveredCandidate, *, carried: bool = True) -> EnvisionedDirection:
    return EnvisionedDirection(
        unit_id=candidate.unit_id,
        fault_class=candidate.fault_class,
        carried=carried,
        rationale="fixture rationale from the spec's H1 gate",
        assumptions=["fixture assumption"],
        envisioned_test_primitives=["fixture probe"],
    )


def _ok_dispatch(calls: list | None = None):
    """The fixture hunting agent (IA-2): returns a successful result on every
    dispatch (the inline back-edge need path is out of scope - the back_edge
    request to recon is not an agent tool, operator ruling 2026-08-22)."""
    record = calls if calls is not None else []

    def dispatch(config: HuntConfig, routed=()):
        record.append((config, tuple(routed)))
        return DispatchResult(
            spec_ref=f"spec-{len(record)}",
            pod_result_ref=f"pod-{len(record)}",
            hypothesis_verdict="successful",
            feedback="fixture feedback",
        )

    return dispatch


def _ok_rematch(verdict: str = "applies"):
    def rematch(unit_id: str, fault_class: str, result: TargetedReconResult) -> MatchVerdict:
        return MatchVerdict(unit_id=unit_id, fault_class=fault_class, verdict=verdict)

    return rematch


def _tools(store: HuntStore, *, read_fn=None) -> OrchestratorTools:
    return OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=read_fn or (lambda cy, p: [])),
    )


def _run(store: HuntStore, candidates, *, dispatch=None, rematch=None,
         tools=None, **kwargs) -> OrchestratorReport:
    return run_orchestration(
        project_id="project-1",
        run_id=RUN_ID,
        candidates=candidates,
        tools=tools or _tools(store),
        dispatch_fn=dispatch or _ok_dispatch(),
        rematch_fn=rematch or _ok_rematch(),
        **kwargs,
    )


# --- C1: empty candidate set is an empty pass (O1) ----------------------------

def test_empty_candidate_set_is_an_empty_pass(tmp_path):
    store = HuntStore(tmp_path)
    report = _run(store, [])
    assert report.hunts_dispatched == 0
    # the empty pass persists nothing: no configs, no notes (the per-run `run`
    # kind file is removed with the memory topology, #166)
    assert store.read_configs("project-1") == []
    assert store.read_notes("project-1") == []


# --- C2: partial match exhaustion degrades per fault (O2, IA-1) ---------------

def test_partial_match_exhaustion_degrades_per_fault(tmp_path):
    store = HuntStore(tmp_path)
    calls: list = []
    report = _run(store, [_candidate(SERVICE_A, "fault-b")],
                  dispatch=_ok_dispatch(calls), exhausted_faults=["fault-a"])
    assert report.exhausted_faults == ("fault-a",)
    assert report.hunts_dispatched == 1
    assert len(store.read_configs("project-1")) == 1
    assert len(calls) == 1


# --- C3: duplicate candidate mints one hunt (O7) ------------------------------

def test_duplicate_candidate_mints_one_hunt(tmp_path):
    store = HuntStore(tmp_path)
    calls: list = []
    cand = _candidate(SERVICE_A, FAULT_X)
    report = _run(store, [cand, _candidate(SERVICE_A, FAULT_X)],
                  dispatch=_ok_dispatch(calls))
    assert report.duplicates_dropped == 1
    assert report.hunts_dispatched == 1
    assert len(store.read_configs("project-1")) == 1
    assert len(calls) == 1


# --- C4: malformed candidate is dropped counted (O10) -------------------------

def test_malformed_candidate_is_dropped_counted(tmp_path, caplog):
    store = HuntStore(tmp_path)
    valid = _candidate(SERVICE_A, FAULT_X)
    missing_witness = _candidate("Service:pay", FAULT_X, llm_witness=None)
    unknown_fault = _candidate("Service:inv", "fault-unknown")
    report = _run(store, [valid, missing_witness, unknown_fault],
                  known_faults=[FAULT_X])
    assert report.malformed_dropped == 2
    assert report.hunts_dispatched == 1
    assert "malformed" in caplog.text.lower()


# --- C5: the graph view rejects writes (D67-04) -------------------------------

def test_graph_view_rejects_writes():
    def spy_read(cypher, params):
        raise AssertionError("no read should happen on a rejected write")

    view = ReadOnlyGraphView("project-1", read_fn=spy_read)
    with pytest.raises(ReadOnlyGraphViewError):
        view.merge("MATCH (n) MERGE (m) ...")  # write-shaped call through the view
    assert TOOL_SURFACE == frozenset({
        "read_memory_hunts", "read_memory_notes", "graph_view",
        "mint_hunt_config", "record_note",
    })


# --- C6: dispatch target failure degrades the hunt (O6, IA-2) -----------------

def test_dispatch_target_failure_degrades_the_hunt(tmp_path, caplog):
    store = HuntStore(tmp_path)

    def boom(config: HuntConfig, routed=()):
        raise RuntimeError("agent turn exhausted")

    report = _run(store, [_candidate(SERVICE_A, FAULT_X)], dispatch=boom)
    assert report.hunts_dispatched == 1
    assert report.hunt_ids[0]  # the degraded hunt still counts as dispatched
    assert len(store.read_configs("project-1")) == 1  # the config persisted at the mint


# --- C7: KB failure degrades the gate, never prunes (D67-11) ------------------

def test_kb_failure_degrades_the_gate(tmp_path, caplog):
    store = HuntStore(tmp_path)
    seen = {}

    def reason_fn(inp):
        seen["kb_degraded"] = inp.kb_degraded
        seen["kb_evidences"] = inp.kb_evidences
        return GateDecision(directions=[_carry(inp.candidates[0])])

    def kb_retrieve(fault_class):
        raise RuntimeError("KB unavailable")

    report = _run(store, [_candidate(SERVICE_A, FAULT_X)],
                  reason_fn=reason_fn, kb_retrieve_fn=kb_retrieve)
    assert seen["kb_degraded"] is True
    assert seen["kb_evidences"] == {}
    assert report.hunts_dispatched == 1
    assert "warning" in caplog.text.lower()


# --- C8: park/resume depth-1 cap (O8, IA-6) -----------------------------------

# --- C8/C9: park/resume + inline back-edge → recon are OUT OF SCOPE ----------
# The back_edge request to recon is wrongly designed and is NOT an agent tool in
# this tree (operator ruling 2026-08-22); the target-knowledge loop rides
# graph_view, never a recon request. The park/resume and inline back-edge
# predicates are removed from the integration tier, not substituted.


# --- C10: store write failure degrades to a warning (O3, IA-7) ----------------

class _FlakyStore(HuntStore):
    def __init__(self, root, *, fail_first: int):
        super().__init__(root)
        self._failures_left = fail_first

    def _write_guard(self):
        if self._failures_left > 0:
            self._failures_left -= 1
            raise OSError("disk full (fixture)")

    def write_config(self, project_id, config, *, directory="produced"):
        self._write_guard()
        return super().write_config(project_id, config, directory=directory)

    def append_note(self, project_id, key, note):
        self._write_guard()
        return super().append_note(project_id, key, note)


def test_store_write_failure_degrades_to_warning(tmp_path, caplog):
    real = HuntStore(tmp_path)
    flaky = _FlakyStore(tmp_path, fail_first=2)
    report = _run(flaky, [_candidate(SERVICE_A, FAULT_X)], tools=_tools(flaky))
    # a 1-candidate pass makes exactly two store writes - the config at the
    # mint and the unit-boundary note - so both fail (O3: warned + counted)
    assert report.store_write_failures == 2
    assert report.hunts_dispatched == 1  # the pass keeps serving (fail-open)
    assert real.read_configs("project-1") == []  # neither write landed
    assert "warning" in caplog.text.lower()


# --- C11: the pass persists config + note in the memory topology ---------------

def test_hunt_record_ordering(tmp_path):
    """C11 - re-scoped to the memory topology (#166): the hypothesised config
    lands in produced/ and the unit-boundary note in memory.yaml; there is no
    dispatch/result/hunt ordering anymore (_seq/_ref removed, G11)."""
    store = HuntStore(tmp_path)
    report = _run(store, [_candidate(SERVICE_A, FAULT_X)])
    configs = store.read_configs("project-1")
    notes = store.read_notes("project-1")
    assert len(configs) == 1
    assert configs[0]["status"] == "hypothesised"
    assert configs[0]["unit_id"] == SERVICE_A
    assert configs[0]["fault_class"] == FAULT_X
    assert report.hunt_ids[0]
    assert len(notes) == 1
    assert notes[0]["revival_key"] == revival_key(SERVICE_A, FAULT_X)
    assert notes[0]["note"]
    produced = (tmp_path / "project-1" / "orchestration" / "hunt_configs"
                / "produced")
    assert produced.exists()
    # the per-run kinds are gone: no dispatch/result/hunt files anywhere
    assert list((tmp_path / "project-1" / "orchestration").glob("*.md")) == []


# --- C12: budget cut rides the report trail (O9) ------------------------------

def test_budget_cut_records_undispatched_direction(tmp_path):
    store = HuntStore(tmp_path)

    def budget_fn(directions):
        return directions[:1]

    report = _run(
        store,
        [_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        budget_fn=budget_fn,
    )
    assert report.hunts_dispatched == 1
    assert report.budget_cut == (revival_key(SYSTEM_B, FAULT_Y),)
    # the cut rides the report trail; the per-run `cut` kind file is removed.
    # Both configs were minted (and persisted to produced/) at the unit
    # boundary BEFORE the budget stage, so the cut direction's hypothesised
    # config stays on disk - a budget cut is a dispatch-stage decision, not a
    # config deletion (G10: the configs express the fault-processing state).
    assert len(store.read_configs("project-1")) == 2


# --- NEW (#110): the gate turn runs per pair, one candidate at a time ----------

def test_gate_turn_is_invoked_per_pair_with_one_candidate(tmp_path):
    """#110 stateful per-fault-unit loop: the reasoning stretch is invoked ONCE
    per accepted pair, each turn receiving exactly that pair (never the batched
    candidate set), in schedule order - so the actor's checkpointed memory
    carries the pass's reasoning across pairs."""
    store = HuntStore(tmp_path)
    seen: list[list[tuple[str, str]]] = []

    def reason_fn(inp):
        seen.append([(c.unit_id, c.fault_class) for c in inp.candidates])
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    report = _run(
        store,
        [_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        reason_fn=reason_fn,
    )
    assert seen == [[(SERVICE_A, FAULT_X)], [(SYSTEM_B, FAULT_Y)]]
    assert report.hunts_dispatched == 2
    assert len(store.read_configs("project-1")) == 2


# --- NEW (#110): the orchestration actor lives per run, never reaped in-pass ---

def test_orchestration_actor_survives_the_pass_and_is_reused(tmp_path):
    """#110 actor-lives-per-run: the registry-held `HuntOrchestratorActor` is NOT
    reaped when the graph completes - a second pass on the same run_id reuses
    the SAME actor, so the same `hunting_orchestrator` thread serves every pair
    AND every pass of the run (monotonic statefulness)."""
    import asyncio

    from polymerhus.attack.hunting.hunt_orchestrator import (
        _ORCHESTRATOR_ACTORS,
        _reap_orchestrator,
    )

    store = HuntStore(tmp_path)
    _run(store, [_candidate(SERVICE_A, FAULT_X)])
    first = _ORCHESTRATOR_ACTORS.get(RUN_ID)
    assert first is not None  # the pass registered the actor and did NOT reap it

    _run(store, [_candidate(SERVICE_A, FAULT_X)])
    second = _ORCHESTRATOR_ACTORS.get(RUN_ID)
    assert second is first  # a later pass on the same run reuses the SAME actor

    asyncio.run(_reap_orchestrator(RUN_ID))  # teardown: the stop path reaps it
    assert _ORCHESTRATOR_ACTORS.get(RUN_ID) is None
