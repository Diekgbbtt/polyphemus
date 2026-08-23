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
    ConcreteFaultCandidate,
    DeliveredCandidate,
    DispatchResult,
    EnvisionedDirection,
    GateDecision,
    MatchVerdict,
    OrchestratorReport,
    OrchestratorTools,
    ReadOnlyGraphView,
    Witness,
    mint_hunt_config,
    normalize_candidates,
    revival_key,
    run_orchestration,
)

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


def _tools(store, *, read_fn=None) -> OrchestratorTools:
    return OrchestratorTools(
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

def _ccf(*, hypothesis: str, capabilities=(), blockers=()) -> ConcreteFaultCandidate:
    """A concrete fault candidate: a web-vulnerability CLASS (hypothesis text)
    with the Q9-refined capability / blocker analysis."""
    return ConcreteFaultCandidate(
        fault_hypothesis=hypothesis,
        adversarial_capabilities=list(capabilities),
        blocking_constraints=list(blockers),
    )


def test_mint_hunt_config_carries_the_five_part_parameter_set():
    # the candidates-rewrite fan-out: a direction with no concrete fault
    # candidates degrades to ONE carried-bare config (the legacy seeded slots)
    candidate = _candidate(deterministic_witness=None)
    config = mint_hunt_config(
        direction=_carry(candidate), candidate=candidate, hunt_id="hunt-1",
        surface_context={"card": {"kind": "Service", "spine": {}}},
        prior_hunt_insights=[{"insight": "form Z carries no CSRF token"}],
        tool_registry=[{"tool": "csrf-probe"}],
    )[0]
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
    assert config.sub_fault_ids == []  # folded recipes, filled by the graph logic


def test_hunt_config_carries_the_sub_fault_ids_slot():
    # the folded fault_ids (reflection material) captured under the parent
    # fault-class: a typed slot the graph logic fills from the fold-family map
    config = mint_hunt_config(
        direction=_carry(_candidate(deterministic_witness=None)),
        candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={},
        prior_hunt_insights=[],
        tool_registry=[],
    )[0]
    config.sub_fault_ids = ["CWE-24", "CWE-35"]
    assert config.sub_fault_ids == ["CWE-24", "CWE-35"]


# --- The risk-descending schedule (the fault_risk policy) -----------------------

def test_schedule_processes_the_riskiest_fault_first():
    """The per-fault schedule is re-sorted RISK-DESCENDING (operator tiers,
    `fault_risk.risk_tier`): an intake that first emitted a residual-tier
    fault still reasons about the broken-access-control fault first - a
    budget-capped pass spends on the riskiest."""
    store = _MemoryStore()
    reason_order: list[str] = []

    def reason_fn(inp):
        reason_order.append(inp.candidates[0].fault_class)
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    report = _run(
        store,
        [_candidate(SERVICE_A, "CWE-601"),   # open redirect, tier 4, FIRST
         _candidate(SERVICE_A, "CWE-639")],  # IDOR, tier 0, SECOND
        reason_fn=reason_fn,
    )
    assert report.hunts_dispatched == 2
    assert reason_order == ["CWE-639", "CWE-601"]


def test_mint_fans_out_one_config_per_distinct_class():
    # N HuntConfigs per distinct web-vulnerability class (the emitted set):
    # the grouping discriminator is the candidate's `fault_hypothesis` text
    direction = _carry(_candidate(deterministic_witness=None))
    direction.concrete_fault_candidates = [
        _ccf(hypothesis="csrf"),
        _ccf(hypothesis="idor"),
        _ccf(hypothesis="ssti"),
    ]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert len(configs) == 3
    # each config carries its own class's candidate as the class marker
    assert [c.prompt_template.concrete_fault_candidates[0].fault_hypothesis
            for c in configs] == ["csrf", "idor", "ssti"]
    # the seeding identity persists on every fan-out config
    assert {c.unit_id for c in configs} == {SERVICE_A}
    assert {c.fault_class for c in configs} == {FAULT_X}


def test_mint_collapses_same_class_duplicates_deterministically():
    # the (LLM-owned, Q16) same-class merge should already have removed
    # duplicates; the mint still collapses candidates sharing the same
    # hypothesis text into one config, keeping the class's full subset
    direction = _carry(_candidate(deterministic_witness=None))
    direction.concrete_fault_candidates = [
        _ccf(hypothesis="csrf", capabilities=["token bypass"], blockers=["WAF guards"]),
        _ccf(hypothesis="csrf", capabilities=["same-origin policy"], blockers=[]),
        _ccf(hypothesis="idor"),
    ]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert len(configs) == 2
    csrf, idor = configs
    assert csrf.prompt_template.concrete_fault_candidates == [
        _ccf(hypothesis="csrf", capabilities=["token bypass"], blockers=["WAF guards"]),
        _ccf(hypothesis="csrf", capabilities=["same-origin policy"], blockers=[]),
    ]
    assert idor.prompt_template.concrete_fault_candidates == [
        _ccf(hypothesis="idor"),
    ]


def test_mint_without_candidates_is_the_carried_bare_fallback():
    # a direction with no emitted class markers still mints ONE dispatchable
    # config from the legacy seeds + research direction (no class-specific slot)
    direction = _carry(_candidate(deterministic_witness=None))
    direction.research_direction = "csrf hygiene across state-changing flows"
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert len(configs) == 1
    config = configs[0]
    assert config.hunt_id == "hunt-1"
    assert config.prompt_template.concrete_fault_candidates == []
    assert config.prompt_template.research_direction == \
        "csrf hygiene across state-changing flows"


def test_mint_with_only_empty_hypotheses_is_the_carried_bare_fallback():
    # candidates whose hypothesis carries no class marker degrade the same way
    direction = _carry(_candidate(deterministic_witness=None))
    direction.concrete_fault_candidates = [_ccf(hypothesis=""), _ccf(hypothesis="")]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert len(configs) == 1
    assert configs[0].prompt_template.concrete_fault_candidates == []


def test_mint_passes_research_direction_and_preserves_the_seed_slots():
    # the extended template mapping: research_direction passes through, the
    # legacy seeds keep their old direction-to-template slots, and the fan-out
    # hides nothing
    direction = _carry(_candidate(deterministic_witness=None))
    direction.research_direction = "enumerating the receipts resource"
    direction.concrete_fault_candidates = [
        _ccf(hypothesis="idor", capabilities=["direct object ref"], blockers=["authz check"]),
        _ccf(hypothesis="csrf", capabilities=["token bypass"], blockers=["same-site cookies"]),
    ]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert [c.hunt_id for c in configs] == ["hunt-1", "hunt-1-1"]
    for config in configs:
        template = config.prompt_template
        assert template.rationale == "r"
        assert template.extension_points == ["p"]
        assert template.assumptions == ["a"]
        assert template.supposed_payload_vectors == ["v"]
        assert template.l0_evidence == ["llm: witness"]
        assert template.research_direction == "enumerating the receipts resource"
    assert configs[0].prompt_template.concrete_fault_candidates == [
        _ccf(hypothesis="idor", capabilities=["direct object ref"], blockers=["authz check"])]
    assert configs[1].prompt_template.concrete_fault_candidates == [
        _ccf(hypothesis="csrf", capabilities=["token bypass"], blockers=["same-site cookies"])]


def test_fanned_out_direction_dispatches_each_config():
    # the dispatch stretch consumes the entire fan-out set: one hunt per
    # distinct class, each with its own config record and hunt_id
    store = _MemoryStore()

    def reason_fn(inp):
        direction = _carry(inp.candidates[0])
        direction.concrete_fault_candidates = [
            _ccf(hypothesis="csrf class"),
            _ccf(hypothesis="idor class"),
        ]
        return GateDecision(directions=[direction])

    report = _run(store, [_candidate()], reason_fn=reason_fn)
    assert report.hunts_dispatched == 2
    assert len(report.hunt_ids) == 2
    assert len(set(report.hunt_ids)) == 2
    assert len(store.list_records("run-1", "config")) == 2
    assert len(store.list_records("run-1", "hunt")) == 2
    assert len(store.list_records("run-1", "memory")) == 2


# --- Seam behaviours: park/resume (H3) ----------------------------------------

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

    report = _run(store, [yellow], rematch=boom)
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
