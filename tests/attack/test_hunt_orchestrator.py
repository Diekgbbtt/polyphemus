"""Unit tier: the hunt-orchestrator's pure mechanics and the fail-open seam
behaviours the catalogue pins only at the integration/e2e tiers.

Pure mechanics: candidate intake (dedup by identity, malformed drop, the
deterministic does-not-apply prune), the revival key, and the D3 HuntConfig
minting. Seam behaviours: the park/resume positive path (H3), the store-read
degradation (O4), the graph-view degradation (O5), the back-edge status
vocabulary (IA-6), the gate fail-open (D67-11 spirit), and the rematch
fail-open. The hunt store and the graph view are MOCKED (no live Neo4j, no
live LLM - testing-strategy.md section 2); the catalogue predicates C1-C12 live
in tests/integration/test_hunt_orchestrator_contracts.py and are never
repeated in this tier's red/green loop.
"""
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    DispatchResult,
    EnvisionedDirection,
    GateDecision,
    MatchVerdict,
    OrchestratorReport,
    OrchestratorTools,
    ReadOnlyGraphView,
    Witness,
    build_back_edge_request,
    mint_hunt_config,
    normalize_candidates,
    revival_key,
    run_orchestration,
)
from polymerhus.recon.control.targeted import TargetedReconResult

SERVICE_A = "Service:slug:a"
FAULT_X = "fault-x"


class _MemoryStore:
    """The mocked hunt store: in-memory, append-only, fail-open reads."""

    def __init__(self, *, fail_reads: bool = False):
        self._records: list[tuple[str, str, dict]] = []
        self._seq = 0
        self.fail_reads = fail_reads
        self.read_attempts = 0

    def append(self, run_id, kind, record):
        self._seq += 1
        stored = {"_seq": self._seq, "_ref": f"{run_id}/{kind}-{self._seq:03d}", **record}
        self._records.append((run_id, kind, stored))
        return stored["_ref"]

    def list_records(self, run_id, kind):
        return [r for rid, k, r in self._records if rid == run_id and k == kind]

    def read_memory(self, revival_key_):
        self.read_attempts += 1
        if self.fail_reads:
            raise OSError("store read failed (fixture)")
        return [r for rid, k, r in self._records
                if k == "memory" and r.get("revival_key") == revival_key_]


def _candidate(unit_id: str = SERVICE_A, fault_class: str = FAULT_X, *,
               verdict: str = "applies", llm_witness: str | None = "witness",
               deterministic_witness: str | None = None) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id,
        fault_class=fault_class,
        applies_witnesses=Witness(deterministic=deterministic_witness, llm=llm_witness),
        match_verdict=verdict,
    )


def _carry(candidate: DeliveredCandidate) -> EnvisionedDirection:
    return EnvisionedDirection(
        unit_id=candidate.unit_id, fault_class=candidate.fault_class, carried=True,
        rationale="r", assumptions=["a"],
        envisioned_test_primitives=["p"], supposed_payload_vectors=["v"],
    )


def _tools(store, *, read_fn=None, back_edge=None) -> OrchestratorTools:
    return OrchestratorTools(
        back_edge=back_edge,
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=read_fn or (lambda cy, p: [])),
    )


def _run(store, candidates, *, reason_fn=None, rematch=None, **kwargs) -> OrchestratorReport:
    tools = kwargs.pop("tools", None) or _tools(store)
    return run_orchestration(
        project_id="project-1",
        run_id="run-1",
        candidates=candidates,
        tools=tools,
        dispatch_fn=lambda config, routed=(): DispatchResult(
            spec_ref="spec-1", pod_result_ref="pod-1",
            hypothesis_verdict="successful", feedback="ok",
        ),
        rematch_fn=rematch or (lambda u, f, r: MatchVerdict(unit_id=u, fault_class=f, verdict="applies")),
        reason_fn=reason_fn or (lambda inp: GateDecision(directions=[_carry(c) for c in inp.candidates])),
        **kwargs,
    )


# --- Pure mechanics: the revival key ------------------------------------------

def test_revival_key_is_the_kind_qualified_pair():
    assert revival_key("Service:slug:a", "fault-x") == "Service:slug:a::fault-x"
    assert revival_key("System:WAF/edge", "fault-y") == "System:WAF/edge::fault-y"


# --- Pure mechanics: candidate intake (dedup, malformed drop, the prune) ------

def test_duplicate_candidates_are_deduped_by_identity():
    intake = normalize_candidates([_candidate(), _candidate()])
    assert len(intake.accepted) == 1
    assert intake.duplicates_dropped == 1
    assert intake.malformed_dropped == 0


def test_applies_without_llm_witness_is_malformed():
    intake = normalize_candidates([_candidate(llm_witness=None)])
    assert len(intake.accepted) == 0
    assert intake.malformed_dropped == 1


def test_does_not_apply_with_llm_witness_is_pruned_not_malformed():
    intake = normalize_candidates([_candidate(verdict="does-not-apply")])
    assert len(intake.accepted) == 0
    assert intake.pruned_by_verdict == 1
    assert intake.malformed_dropped == 0


def test_does_not_apply_without_any_witness_is_malformed():
    intake = normalize_candidates([_candidate(verdict="does-not-apply", llm_witness=None)])
    assert len(intake.accepted) == 0
    assert intake.pruned_by_verdict == 0
    assert intake.malformed_dropped == 1


def test_unknown_fault_class_is_dropped_when_registry_given():
    intake = normalize_candidates([_candidate()], known_faults=["other-fault"])
    assert len(intake.accepted) == 0
    assert intake.malformed_dropped == 1


def test_does_not_apply_is_pruned_and_never_reaches_the_gate():
    store = _MemoryStore()
    gate_inputs: list = []
    cand = _candidate(verdict="does-not-apply", deterministic_witness="clause 3 FALSE")

    def reason_fn(inp):
        gate_inputs.append(inp.candidates)
        return GateDecision(directions=[])

    report = _run(store, [cand], reason_fn=reason_fn)
    assert report.pruned_by_verdict == 1
    assert report.hunts_dispatched == 0
    assert gate_inputs == []  # a pruned-only pass never spends a gate turn


# --- Pure mechanics: the D3 HuntConfig minting --------------------------------

def test_mint_hunt_config_carries_the_five_part_parameter_set():
    candidate = _candidate(deterministic_witness=None)
    config = mint_hunt_config(
        direction=_carry(candidate), candidate=candidate, hunt_id="hunt-1",
        surface_context={"card": {"kind": "Service", "spine": {}}},
        prior_hunt_insights=[{"insight": "form Z carries no CSRF token"}],
        tool_registry=[{"tool": "csrf-probe"}],
    )
    assert config.hunt_id == "hunt-1"
    assert config.unit_id == SERVICE_A
    assert config.fault_class == FAULT_X
    template = config.prompt_template
    assert template.rationale == "r"
    assert template.extension_points == ["p"]
    assert template.assumptions == ["a"]
    assert template.supposed_payload_vectors == ["v"]
    assert template.l0_evidence == ["llm: witness"]
    assert config.surface_context["card"]["kind"] == "Service"
    assert config.target_caveats == []
    assert config.prior_hunt_insights == [{"insight": "form Z carries no CSRF token"}]
    assert config.tool_registry == [{"tool": "csrf-probe"}]


# --- Seam behaviours: park/resume (H3) ----------------------------------------

def test_park_resume_positive_path_dispatches_after_rematch():
    store = _MemoryStore()
    seen: list = []
    yellow = _candidate(verdict="insufficient-evidence")

    def back_edge(request, run_id, project_id):
        seen.append(request)
        return TargetedReconResult(
            correlation_id=request.correlation_id, requester_id=request.requester_id,
            origin="hunting", status="success",
        )

    report = _run(store, [yellow], tools=_tools(store, back_edge=back_edge))
    assert report.hunts_dispatched == 1
    assert len(seen) == 1
    assert len(store.list_records("run-1", "back_edge")) == 1
    assert report.unresolved == ()


# --- Seam behaviours: fail-open degradations ----------------------------------

def test_store_read_failure_degrades_prior_insights(caplog):
    store = _MemoryStore(fail_reads=True)
    report = _run(store, [_candidate()])
    assert report.hunts_dispatched == 1
    assert store.read_attempts >= 1
    assert "warning" in caplog.text.lower()


def test_graph_view_query_failure_degrades_the_gate(caplog):
    store = _MemoryStore()

    def broken_read(cypher, params):
        raise RuntimeError("graph read failed (fixture)")

    seen: dict = {}

    def reason_fn(inp):
        seen["surface"] = inp.surface
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate()], tools=_tools(store, read_fn=broken_read),
                  reason_fn=reason_fn)
    assert report.hunts_dispatched == 1
    assert seen["surface"] == []
    assert "warning" in caplog.text.lower()


def test_errored_back_edge_is_folded_into_the_evidence_trail():
    store = _MemoryStore()
    yellow = _candidate(verdict="insufficient-evidence")

    def failing_back_edge(request, run_id, project_id):
        return TargetedReconResult(
            correlation_id=request.correlation_id, requester_id=request.requester_id,
            origin="hunting", status="error", error="probe blew up",
        )

    report = _run(store, [yellow], tools=_tools(store, back_edge=failing_back_edge))
    records = store.list_records("run-1", "back_edge")
    assert len(records) == 1
    assert records[0]["status"] == "error"
    assert records[0]["error"] == "probe blew up"
    assert report.unresolved == ()


def test_reason_turn_failure_carries_all_directions(caplog):
    store = _MemoryStore()

    def boom(inp):
        raise RuntimeError("reasoning turn exhausted")

    report = _run(store, [_candidate()], reason_fn=boom)
    assert report.hunts_dispatched == 1
    assert "warning" in caplog.text.lower()


def test_rematch_failure_degrades_to_unresolved(caplog):
    store = _MemoryStore()
    yellow = _candidate(verdict="insufficient-evidence")

    def boom(unit_id, fault_class, result):
        raise RuntimeError("re-match exhausted")

    report = _run(store, [yellow], rematch=boom,
                  tools=_tools(store, back_edge=lambda req, r, p: TargetedReconResult(
                      correlation_id=req.correlation_id, requester_id=req.requester_id,
                      origin="hunting", status="success")))
    assert report.hunts_dispatched == 0
    assert report.unresolved == (revival_key(SERVICE_A, FAULT_X),)
    assert "warning" in caplog.text.lower()


def test_gate_pruned_direction_is_not_dispatched():
    store = _MemoryStore()
    cand = _candidate()

    def pruning_gate(inp):
        direction = _carry(inp.candidates[0])
        return GateDecision(directions=[
            EnvisionedDirection(unit_id=direction.unit_id, fault_class=direction.fault_class,
                                carried=False)])

    report = _run(store, [cand], reason_fn=pruning_gate)
    assert report.hunts_dispatched == 0
    assert report.gate_pruned == (revival_key(SERVICE_A, FAULT_X),)


# --- Seam behaviours: the back-edge request shape (IA-6) ----------------------

def test_back_edge_request_builds_origin_hunting():
    request = build_back_edge_request(
        SERVICE_A, FAULT_X, requester_id="hunt-orchestrator-1",
        note="yellow match: insufficient evidence of exposure",
    )
    assert request.origin == "hunting"
    assert request.requester_id == "hunt-orchestrator-1"
    assert request.scope.unit_id == SERVICE_A
    assert request.correlation_id
    assert "insufficient evidence" in request.scope.note


# --- The async-native parent entry point (#94) --------------------------------

def _arun(store, candidates, **kwargs):
    """`_run`'s async twin: same scenario driven through `arun_orchestration`."""
    import asyncio

    from polymerhus.attack.hunting.hunt_orchestrator import arun_orchestration

    return asyncio.run(arun_orchestration(
        project_id="project-1", run_id="run-1", candidates=candidates,
        tools=_tools(store),
        dispatch_fn=lambda config, routed=(): DispatchResult(
            spec_ref="spec-1", pod_result_ref="pod-1",
            hypothesis_verdict="successful", feedback="ok"),
        rematch_fn=lambda u, f, r: MatchVerdict(unit_id=u, fault_class=f, verdict="applies"),
        reason_fn=lambda inp: GateDecision(directions=[_carry(c) for c in inp.candidates]),
        **kwargs,
    ))


def test_arun_orchestration_matches_the_sync_pass():
    """The async-native parent entry point produces the IDENTICAL report to the sync
    pass for the same scenario - it single-sources the O1-O10 fail-open canon by
    running `run_orchestration` off the event loop, never re-implementing it."""
    sync_report = _run(_MemoryStore(), [_candidate()])
    async_report = _arun(_MemoryStore(), [_candidate()])
    # `hunt_ids` are random uuids (one per dispatch), so compare everything else
    # verbatim and the hunt_ids by COUNT - the pass shape must be identical.
    drop = {"hunt_ids"}
    assert ({k: v for k, v in async_report.model_dump().items() if k not in drop}
            == {k: v for k, v in sync_report.model_dump().items() if k not in drop})
    assert len(async_report.hunt_ids) == len(sync_report.hunt_ids) == 1
    assert async_report.hunts_dispatched == 1


def test_arun_orchestration_does_not_block_the_event_loop():
    """The parent value: an async caller can `await` a hunt pass while OTHER
    coordination runs concurrently on the same loop. A ticking heartbeat coroutine
    makes progress while the (thread-offloaded) pass runs - proving the pass is not
    monopolising the loop."""
    import asyncio

    from polymerhus.attack.hunting.hunt_orchestrator import arun_orchestration

    async def _drive():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(50):
                await asyncio.sleep(0.001)
                ticks += 1

        beat = asyncio.ensure_future(heartbeat())
        report = await arun_orchestration(
            project_id="project-1", run_id="run-1", candidates=[_candidate()],
            tools=_tools(_MemoryStore()),
            dispatch_fn=lambda config, routed=(): DispatchResult(
                spec_ref="s", pod_result_ref="p",
                hypothesis_verdict="successful", feedback="ok"),
            rematch_fn=lambda u, f, r: MatchVerdict(unit_id=u, fault_class=f, verdict="applies"),
            reason_fn=lambda inp: GateDecision(directions=[_carry(c) for c in inp.candidates]),
        )
        await beat
        return report, ticks

    report, ticks = asyncio.run(_drive())
    assert report.hunts_dispatched == 1
    assert ticks == 50  # the loop kept ticking while the pass ran off-loop
