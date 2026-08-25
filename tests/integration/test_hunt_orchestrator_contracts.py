"""Integration tier: the hunt-orchestrator assertion catalogue C1-C12
(hunting-67-orchestrator-spec.md section 6.1, re-scoped by #167: the graph ENDs
at the REASON stretch - the dispatch node (G12) and the O9 budget stage (G7)
are removed).

The contract predicates exercise the orchestration run against a REAL
per-project hunt store (the #166 memory topology) with every out-of-tree
collaborator injected: the hypothesise / ratify / note phase turns, the KB
retrieval (IA-1/D67-11), and the store seams all arrive as fixtures. The
tool-surface contract (the three tools `hunts_store` / `notes` / `graph_view`,
G3) is asserted here too. Expected values are taken from the spec, never
recomputed the way the code computes them.
"""
import uuid

import pytest

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
    ReadOnlyGraphViewError,
    TOOL_SURFACE,
    Witness,
    revival_key,
    run_orchestration,
)
from polymerhus.attack.hunting.hunt_store import HuntStore

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


def _carry_hypothesise(calls: list | None = None):
    """The fixture hypothesise turn: carries every candidate as a direction,
    optionally recording the inputs (the per-pair gate-call shape)."""
    record = calls if calls is not None else []

    def hypothesise(inp):
        record.append(inp)
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    return hypothesise


def _ratify_drafts(inp) -> RatifyDecision:
    """The fixture ratify turn: amends every draft to ratified with the filled
    ratification fields."""
    configs = []
    for draft in inp.configs:
        amended = draft.model_copy(deep=True)
        amended.status = "ratified"
        amended.adversarial_capabilities = ["forge a cross-origin request"]
        amended.assumptions = ["the session is cookie-bound"]
        amended.technique_primitives = ["token-missing probe"]
        configs.append(amended)
    return RatifyDecision(configs=configs)


def _note_pair(inp) -> NoteDecision:
    """The fixture note turn: one note for the pair (the pair end)."""
    return NoteDecision(notes=[NoteRecord(
        key=revival_key(inp.pair.unit_id, inp.pair.fault_class),
        note="fixture note walking the reasoning",
    )])


def _tools(store: HuntStore, *, read_fn=None) -> OrchestratorTools:
    return OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=read_fn or (lambda cy, p: [])),
    )


def _run(store: HuntStore, candidates, *, hypothesise=None, ratify=None,
         note=None, tools=None, **kwargs) -> OrchestratorReport:
    return run_orchestration(
        project_id="project-1",
        run_id=RUN_ID,
        candidates=candidates,
        tools=tools or _tools(store),
        hypothesise_fn=hypothesise,
        ratify_fn=ratify or _ratify_drafts,
        note_fn=note or _note_pair,
        **kwargs,
    )


# --- C1: empty candidate set is an empty pass (O1) ----------------------------

def test_empty_candidate_set_is_an_empty_pass(tmp_path):
    store = HuntStore(tmp_path)
    report = _run(store, [])
    assert report.pairs_processed == 0
    assert report.configs_hypothesised == 0
    assert report.configs_ratified == 0
    # the empty pass persists nothing: no configs, no notes (the per-run `run`
    # kind file is removed with the memory topology, #166)
    assert store.read_configs("project-1") == []
    assert store.read_notes("project-1") == []


# --- C2: partial match exhaustion degrades per fault (O2, IA-1) ---------------

def test_partial_match_exhaustion_degrades_per_fault(tmp_path):
    store = HuntStore(tmp_path)
    report = _run(store, [_candidate(SERVICE_A, "fault-b")],
                  exhausted_faults=["fault-a"])
    assert report.exhausted_faults == ("fault-a",)
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert len(store.read_configs("project-1")) == 1


# --- C3: duplicate candidate mints one hunt (O7) ------------------------------

def test_duplicate_candidate_mints_one_hunt(tmp_path):
    store = HuntStore(tmp_path)
    cand = _candidate(SERVICE_A, FAULT_X)
    report = _run(store, [cand, _candidate(SERVICE_A, FAULT_X)])
    assert report.duplicates_dropped == 1
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert len(store.read_configs("project-1")) == 1


# --- C4: malformed candidate is dropped counted (O10) -------------------------

def test_malformed_candidate_is_dropped_counted(tmp_path, caplog):
    store = HuntStore(tmp_path)
    valid = _candidate(SERVICE_A, FAULT_X)
    missing_witness = _candidate("Service:pay", FAULT_X, llm_witness=None)
    unknown_fault = _candidate("Service:inv", "fault-unknown")
    report = _run(store, [valid, missing_witness, unknown_fault],
                  known_faults=[FAULT_X])
    assert report.malformed_dropped == 2
    assert report.pairs_processed == 1
    assert "malformed" in caplog.text.lower()


# --- C5: the graph view rejects writes (D67-04) + the three-tool surface ------

def test_graph_view_rejects_writes():
    def spy_read(cypher, params):
        raise AssertionError("no read should happen on a rejected write")

    view = ReadOnlyGraphView("project-1", read_fn=spy_read)
    with pytest.raises(ReadOnlyGraphViewError):
        view.merge("MATCH (n) MERGE (m) ...")  # write-shaped call through the view
    assert TOOL_SURFACE == frozenset({"hunts_store", "notes", "graph_view"})


# --- C6: a raising phase turn degrades fail-open, the pass completes ----------

def test_ratify_turn_failure_degrades_the_pass(tmp_path, caplog):
    """The ratify phase degrades fail-open: a raising ratify turn keeps the
    hypothesised drafts on disk (never ratified) but the pass completes - the
    graph still ENDs at the note phase (no dispatch node to fail on)."""
    store = HuntStore(tmp_path)

    def boom(inp):
        raise RuntimeError("agent turn exhausted")

    report = _run(store, [_candidate(SERVICE_A, FAULT_X)], ratify=boom)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 1
    assert report.configs_ratified == 0
    assert store.read_configs("project-1")[0]["status"] == "hypothesised"
    assert "warning" in caplog.text.lower()


# --- C7: KB retrieval seam retired (D67-11) -----------------------------------

def test_kb_seam_retired_gate_grounds_on_materialisation(tmp_path):
    """The duplicate symptom-technique retrieval seam (surface B) is RETIRED:
    the gate no longer calls a `kb_retrieve_fn`; `kb_evidences` stays empty and
    `kb_degraded` stays False (available) - the gate grounds via the direct
    fault-KB materialisation read (the CWE catalogue), and never prunes on
    degraded grounds."""
    store = HuntStore(tmp_path)
    seen = {}

    def hypothesise_fn(inp):
        seen["kb_degraded"] = inp.kb_degraded
        seen["kb_evidences"] = inp.kb_evidences
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, FAULT_X)],
                  hypothesise=hypothesise_fn)
    assert seen["kb_degraded"] is False
    assert seen["kb_evidences"] == {}
    assert report.pairs_processed == 1


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

    def update_config(self, project_id, config, *, directory="produced"):
        self._write_guard()
        return super().update_config(project_id, config, directory=directory)

    def append_note(self, project_id, key, note):
        self._write_guard()
        return super().append_note(project_id, key, note)


def test_store_write_failure_degrades_to_warning(tmp_path, caplog):
    real = HuntStore(tmp_path)
    flaky = _FlakyStore(tmp_path, fail_first=2)
    report = _run(flaky, [_candidate(SERVICE_A, FAULT_X)], tools=_tools(flaky))
    # a 1-candidate pass makes exactly three store writes - the hypothesise
    # create, the ratify upsert, and the note append - so the first two fail
    # (O3: warned + counted); the pass keeps serving (fail-open)
    assert report.store_write_failures == 2
    assert report.pairs_processed == 1
    assert real.read_configs("project-1") == []  # neither config write landed
    assert "warning" in caplog.text.lower()


# --- C11: the pass persists config + note in the memory topology ---------------

def test_hunt_record_ordering(tmp_path):
    """C11 - re-scoped to the memory topology (#166 + #167): the config lands
    in produced/ hypothesised and is amended to ratified by the ratify phase;
    the pair's note lands in memory.yaml; there is no dispatch/result/hunt
    ordering anymore (_seq/_ref removed, G11; dispatch removed, G12)."""
    store = HuntStore(tmp_path)
    report = _run(store, [_candidate(SERVICE_A, FAULT_X)])
    configs = store.read_configs("project-1")
    notes = store.read_notes("project-1")
    assert len(configs) == 1
    assert configs[0]["status"] == "ratified"
    assert configs[0]["unit_id"] == SERVICE_A
    assert configs[0]["fault_class"] == FAULT_X
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert len(notes) == 1
    assert notes[0]["revival_key"] == revival_key(SERVICE_A, FAULT_X)
    assert notes[0]["note"]
    produced = (tmp_path / "project-1" / "orchestration" / "hunt_configs"
                / "produced")
    assert produced.exists()
    # the per-run kinds are gone: no dispatch/result/hunt files anywhere
    assert list((tmp_path / "project-1" / "orchestration").glob("*.md")) == []


# --- C12: the O9 budget stage is REMOVED (G7) ---------------------------------

def test_budget_stage_is_removed_and_no_direction_is_cut(tmp_path):
    """C12 - re-scoped by #167/G7: the deterministic O9 BUDGET stage is gone -
    spending is the runtime plane's and the pod's ownership. A pass over two
    candidates ratifies BOTH configs (nothing is ever cut), and the report has
    no budget-cut field at all."""
    store = HuntStore(tmp_path)
    report = _run(
        store,
        [_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
    )
    assert report.pairs_processed == 2
    assert report.configs_ratified == 2
    assert not hasattr(report, "budget_cut")      # the stage's field is gone
    assert not hasattr(report, "hunts_dispatched")  # the dispatch node is gone (G12)
    configs = store.read_configs("project-1")
    assert len(configs) == 2
    assert all(c["status"] == "ratified" for c in configs)


# --- #110/#167: the hypothesise turn runs per pair, one candidate at a time ----

def test_hypothesise_turn_is_invoked_per_pair_with_one_candidate(tmp_path):
    """The phase-machine rework (#167): the hypothesise turn is invoked ONCE
    per accepted pair, each turn receiving exactly that pair (never the batched
    candidate set), in schedule order - so the actor's checkpointed memory
    carries the pass's reasoning across pairs."""
    store = HuntStore(tmp_path)
    seen: list[list[tuple[str, str]]] = []

    def hypothesise_fn(inp):
        seen.append([(c.unit_id, c.fault_class) for c in inp.candidates])
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    report = _run(
        store,
        [_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        hypothesise=hypothesise_fn,
    )
    assert seen == [[(SERVICE_A, FAULT_X)], [(SYSTEM_B, FAULT_Y)]]
    assert report.pairs_processed == 2
    assert report.configs_ratified == 2
    assert len(store.read_configs("project-1")) == 2


# --- #110: the orchestration actor lives per run, never reaped in-pass ---

def test_orchestration_actor_survives_the_pass_and_is_reused(tmp_path):
    """#110 actor-lives-per-run: the registry-held `HuntOrchestratorActor` is NOT
    reaped when the graph completes - a second pass on the same run_id reuses
    the SAME actor, so the same `hunting_orchestrator` thread serves every pair
    AND every pass of the run (monotonic statefulness). The default phase seams
    (None -> the actor) drive both passes."""
    import asyncio

    from polymerhus.attack.hunting.hunt_orchestrator import (
        _ORCHESTRATOR_ACTORS,
        _reap_orchestrator,
    )

    store = HuntStore(tmp_path)
    _run(store, [_candidate(SERVICE_A, FAULT_X)],
         hypothesise=_carry_hypothesise(), ratify=_ratify_drafts, note=_note_pair)
    first = _ORCHESTRATOR_ACTORS.get(RUN_ID)
    assert first is not None  # the pass registered the actor and did NOT reap it

    _run(store, [_candidate(SERVICE_A, FAULT_X)],
         hypothesise=_carry_hypothesise(), ratify=_ratify_drafts, note=_note_pair)
    second = _ORCHESTRATOR_ACTORS.get(RUN_ID)
    assert second is first  # a later pass on the same run reuses the SAME actor

    asyncio.run(_reap_orchestrator(RUN_ID))  # teardown: the stop path reaps it
    assert _ORCHESTRATOR_ACTORS.get(RUN_ID) is None