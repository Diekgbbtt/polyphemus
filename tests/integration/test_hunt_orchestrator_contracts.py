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
    NoteOut,
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
from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
)

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
        supposed_payload_vectors=["fixture vector"],
    )


def _ok_dispatch(calls: list | None = None, *, needs: list[AnalyserReconRequest] | None = None):
    """The fixture hunting agent (IA-2): returns a successful result, optionally
    surfacing an inline back-edge need on the first call (IA-5 -> IA-6)."""
    record = calls if calls is not None else []

    def dispatch(config: HuntConfig, routed=()):
        record.append((config, tuple(routed)))
        if needs and not routed:
            return DispatchResult(back_edge_needs=needs)
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


def _ok_back_edge(seen: list | None = None, *, status: str = "success"):
    record = seen if seen is not None else []

    def back_edge(request: AnalyserReconRequest, run_id: str, project_id: str) -> TargetedReconResult:
        record.append(request)
        return TargetedReconResult(
            correlation_id=request.correlation_id,
            requester_id=request.requester_id,
            origin="hunting",
            status=status,
        )

    return back_edge


def _tools(store: HuntStore, *, back_edge=None, read_fn=None) -> OrchestratorTools:
    return OrchestratorTools(
        back_edge=back_edge,
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=read_fn or (lambda cy, p: [])),
    )


def _run(store: HuntStore, candidates, *, dispatch=None, rematch=None,
         back_edge=None, tools=None, **kwargs) -> OrchestratorReport:
    return run_orchestration(
        project_id="project-1",
        run_id=RUN_ID,
        candidates=candidates,
        tools=tools or _tools(store, back_edge=back_edge),
        dispatch_fn=dispatch or _ok_dispatch(),
        rematch_fn=rematch or _ok_rematch(),
        **kwargs,
    )


# --- C1: empty candidate set is an empty pass (O1) ----------------------------

def test_empty_candidate_set_is_an_empty_pass(tmp_path):
    store = HuntStore(tmp_path)
    report = _run(store, [])
    assert report.hunts_dispatched == 0
    passes = store.list_records(RUN_ID, "run")
    assert len(passes) == 1
    assert passes[0]["candidates_received"] == 0


# --- C2: partial match exhaustion degrades per fault (O2, IA-1) ---------------

def test_partial_match_exhaustion_degrades_per_fault(tmp_path):
    store = HuntStore(tmp_path)
    calls: list = []
    report = _run(store, [_candidate(SERVICE_A, "fault-b")],
                  dispatch=_ok_dispatch(calls), exhausted_faults=["fault-a"])
    assert report.exhausted_faults == ("fault-a",)
    assert report.hunts_dispatched == 1
    assert len(store.list_records(RUN_ID, "hunt")) == 1
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
    assert len(store.list_records(RUN_ID, "hunt")) == 1
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
    # The #137/#140 extended surface is asserted OUTSIDE the raising block (the
    # raise above exits the `with` before it would otherwise run).
    assert TOOL_SURFACE == frozenset(
        {"back_edge", "store_reads", "graph_view", "read_memory_notes"})


# --- C6: dispatch target failure degrades the hunt (O6, IA-2) -----------------

def test_dispatch_target_failure_degrades_the_hunt(tmp_path, caplog):
    store = HuntStore(tmp_path)

    def boom(config: HuntConfig, routed=()):
        raise RuntimeError("agent turn exhausted")

    report = _run(store, [_candidate(SERVICE_A, FAULT_X)], dispatch=boom)
    assert report.hunts_dispatched == 1
    hunts = store.list_records(RUN_ID, "hunt")
    assert len(hunts) == 1
    assert hunts[0]["degraded"] is True
    assert "exhausted" in hunts[0]["error"]


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

def test_park_resume_depth_one_cap(tmp_path):
    store = HuntStore(tmp_path)
    back_edges: list = []
    yellow = _candidate(SERVICE_A, FAULT_X, verdict="insufficient-evidence")
    report = _run(store, [yellow],
                  back_edge=_ok_back_edge(back_edges),
                  rematch=_ok_rematch(verdict="insufficient-evidence"))
    assert report.hunts_dispatched == 0
    assert len(back_edges) == 1
    assert report.unresolved == (revival_key(SERVICE_A, FAULT_X),)
    unresolved = store.list_records(RUN_ID, "unresolved")
    assert len(unresolved) == 1
    assert unresolved[0]["revival_key"] == revival_key(SERVICE_A, FAULT_X)


# --- C9: inline back-edge routes on the correlation_id (IA-6, D67-14) ---------

def test_inline_back_edge_routes_on_correlation_id(tmp_path):
    store = HuntStore(tmp_path)
    routed: list = []
    need = AnalyserReconRequest(
        job="graphql-cop",
        requester_id="hunting-agent-1",
        origin="hunting",
        correlation_id="cid-inline-1",
        scope=ReconScope(unit_id=SERVICE_A, targets=["https://a/graphql"]),
    )
    report = _run(store, [_candidate(SERVICE_A, FAULT_X)],
                  dispatch=_ok_dispatch(needs=[need]),
                  back_edge=_ok_back_edge(routed))
    assert report.hunts_dispatched == 1
    assert len(routed) == 1
    assert routed[0].origin == "hunting"
    assert routed[0].correlation_id == "cid-inline-1"


# --- C10: store write failure degrades to a warning (O3, IA-7) ----------------

class _FlakyStore(HuntStore):
    def __init__(self, root, *, fail_first: int):
        super().__init__(root)
        self._failures_left = fail_first

    def append(self, run_id, kind, record):
        if self._failures_left > 0:
            self._failures_left -= 1
            raise OSError("disk full (fixture)")
        return super().append(run_id, kind, record)


def test_store_write_failure_degrades_to_warning(tmp_path, caplog):
    real = HuntStore(tmp_path)
    flaky = _FlakyStore(tmp_path, fail_first=2)
    report = _run(flaky, [_candidate(SERVICE_A, FAULT_X)], tools=_tools(flaky))
    assert report.store_write_failures == 2
    assert report.hunts_dispatched == 1
    assert len(real.list_records(RUN_ID, "hunt")) == 1
    assert "warning" in caplog.text.lower()


# --- C11: record ordering at IA-7 (config -> dispatch -> result) --------------

def test_hunt_record_ordering(tmp_path):
    store = HuntStore(tmp_path)
    report = _run(store, [_candidate(SERVICE_A, FAULT_X)])
    configs = store.list_records(RUN_ID, "config")
    dispatches = store.list_records(RUN_ID, "dispatch")
    results = store.list_records(RUN_ID, "result")
    assert len(configs) == len(dispatches) == len(results) == 1
    assert configs[0]["_seq"] < dispatches[0]["_seq"] < results[0]["_seq"]
    hunts = store.list_records(RUN_ID, "hunt")
    assert len(hunts) == 1
    assert hunts[0]["hunt_id"] == report.hunt_ids[0]
    assert hunts[0]["config_ref"] == configs[0]["_ref"]
    assert hunts[0]["spec_ref"] == "spec-1"
    assert hunts[0]["pod_result_ref"] == "pod-1"
    assert hunts[0]["hypothesis_verdict"] == "successful"
    assert hunts[0]["revival_key"] == revival_key(SERVICE_A, FAULT_X)


# --- C12: budget cut records the un-dispatched direction (O9) -----------------

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
    cuts = store.list_records(RUN_ID, "cut")
    assert len(cuts) == 1
    assert cuts[0]["direction"] == revival_key(SYSTEM_B, FAULT_Y)
    assert len(store.list_records(RUN_ID, "config")) == 1


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
    assert len(store.list_records(RUN_ID, "config")) == 2


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


# --- C8/C9: the deterministic note-taking node (#139) -------------------------

def _note_producer(notes):
    """The fixture note-taking turn: returns the given notes for the current state."""
    def produce(state) -> dict:
        return {"notes": notes}
    return produce


def test_note_node_writes_per_pair_notes(tmp_path):
    """C8/C9 - the note node is reached deterministically per pair and writes
    the produced notes to the per-project store, keyed unit_id:fault_class with a
    kind-namespaced name; carried and refused notes both persist."""
    store = HuntStore(tmp_path)
    notes = [
        NoteOut(unit_id=SERVICE_A, fault_class=FAULT_X,
                name="implicit_test_primitive:csrf-probe",
                kind="implicit_test_primitive", body="probe the POST with a bare token"),
        NoteOut(unit_id=SERVICE_A, fault_class=FAULT_X,
                name="hypothesis_refusal:missing-csrf",
                kind="hypothesis_refusal", body="form Z carries no CSRF token",
                evidence="observed on form Z"),
    ]
    _run(store, [_candidate(SERVICE_A, FAULT_X)], note_fn=_note_producer(notes))

    mem = store.project_memory
    got = mem.read_notes("project-1")
    assert len(got) == 2
    kinds = {n["kind"] for n in got}
    assert kinds == {"implicit_test_primitive", "hypothesis_refusal"}
    assert all(n["unit_id"] == SERVICE_A and n["fault_class"] == FAULT_X for n in got)
    keys = {n["key"] for n in got}
    assert any("implicit_test_primitive:csrf-probe" in k for k in keys)
    assert any("hypothesis_refusal:missing-csrf" in k for k in keys)


def test_note_node_absent_fails_open_writes_nothing(tmp_path):
    """C8 - the default (absent) note node writes nothing and never aborts."""
    store = HuntStore(tmp_path)
    report = _run(store, [_candidate(SERVICE_A, FAULT_X)])  # note_fn not passed
    assert report.hunts_dispatched == 1
    assert store.project_memory.read_notes("project-1") == []


# --- C10/C11: the reading tool (#140) ------------------------------------------

def test_reading_tool_grep_match_and_contains_logic(tmp_path):
    """C10 - the reading tool delegates to the per-project store's grep-match read;
    C11 - a parent-index-only query returns the prior notes for that key (the old
    read_memory semantics), so existing call sites degrade compatibly."""
    store = HuntStore(tmp_path)
    memory = store.project_memory
    memory.append_note("project-1", SERVICE_A, FAULT_X, "hypothesis_refusal:no-csrf",
                       "hypothesis_refusal", "form Z carries no CSRF token")
    tools = OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=lambda cy, p: []),
    )
    # parent-index-only (compatible with read_memory semantics).
    hit = tools.read_memory_notes("project-1", parent_key=revival_key(SERVICE_A, FAULT_X))
    assert len(hit) == 1 and hit[0]["kind"] == "hypothesis_refusal"
    # body keyword.
    assert len(tools.read_memory_notes("project-1", body_keyword="csrf")) == 1
    # key keyword.
    assert len(tools.read_memory_notes("project-1", key_keyword="no-csrf")) == 1
    # combinable.
    assert len(tools.read_memory_notes("project-1",
                                       key_keyword="no-csrf", body_keyword="csrf")) == 1
    # empty-but-valid.
    assert tools.read_memory_notes("project-1", body_keyword="nothing") == []
    # no store -> empty, never crash.
    bare = OrchestratorTools(store_reads=None, graph_view=None)
    assert bare.read_memory_notes("project-1", body_keyword="x") == []


def test_config_accumulates_per_project_on_dispatch(tmp_path):
    """#142 - a dispatched pass accumulates a hunt-config direction stamp in the
    per-project config store (the overlap-prevention memory)."""
    store = HuntStore(tmp_path)
    _run(store, [_candidate(SERVICE_A, FAULT_X)])
    cfg = store.project_memory.config_keys("project-1")
    assert cfg == [revival_key(SERVICE_A, FAULT_X)]


# --- C12: gate-prompt key-list embedding (#141) --------------------------------

from polymerhus.attack.hunting.llm import _compose_gate_prompt  # noqa: E402
from polymerhus.attack.hunting.hunt_orchestrator import GateInput  # noqa: E402


def test_gate_prompt_embeds_prior_config_keys():
    """C12 - the gate prompt embeds the previous hunt-config keys as a header
    list (Seam 3); an empty prior set embeds an empty index (valid)."""
    prompt = _compose_gate_prompt(GateInput(
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        prior_config_keys=[revival_key(SERVICE_A, FAULT_X), revival_key(SERVICE_A, FAULT_Y)],
    ))
    assert "Prior hunt-config research-direction keys" in prompt
    assert revival_key(SERVICE_A, FAULT_X) in prompt
    assert revival_key(SERVICE_A, FAULT_Y) in prompt

    empty = _compose_gate_prompt(GateInput(
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        prior_config_keys=[],
    ))
    assert "Prior hunt-config research-direction keys" not in empty
