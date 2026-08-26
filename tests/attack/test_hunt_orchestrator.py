"""Unit tier: the hunt-orchestrator's pure mechanics and the fail-open seam
behaviours the catalogue pins only at the integration/e2e tiers.

Pure mechanics: candidate intake (dedup by identity, malformed drop, the
deterministic does-not-apply prune), the revival key, and the D3 HuntConfig
minting. Seam behaviours: the store-read degradation (O4), the graph-view
degradation (O5), the hypothesise fail-open (a raising/empty turn SKIPS the
pair, counted - the #186 anti-fabrication), the ratify fail-open (a raising
turn keeps the drafts hypothesised), the note fail-open (a raising turn skips
the note), and the gate-pruned no-write path. The hunt store and the graph view
are MOCKED (no live Neo4j, no live LLM - testing-strategy.md section 2); the
catalogue predicates live in tests/integration and are never repeated in this
tier's red/green loop.
"""
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
    mint_hunt_config,
    normalize_candidates,
    revival_key,
    run_orchestration,
)

SERVICE_A = "Service:slug:a"
FAULT_X = "fault-x"


class _MemoryStore:
    """The mocked per-project memory store: in-memory configs + notes,
    fail-open reads, mirroring the real store's surface (write_config /
    update_config / append_note / read_configs_by_key / read_notes /
    read_configs)."""

    def __init__(self, *, fail_reads: bool = False):
        self._configs: list[dict] = []
        self._notes: list[dict] = []
        self.fail_reads = fail_reads
        self.read_attempts = 0

    def write_config(self, project_id, config):
        data = config.model_dump() if not isinstance(config, dict) else dict(config)
        self._configs.append(data)
        return f"{data.get('unit_id')}::{data.get('fault_class')}::{data.get('vulnerability_class')}"

    def update_config(self, project_id, config):
        data = config.model_dump() if not isinstance(config, dict) else dict(config)
        identity = (str(data.get("unit_id") or ""), str(data.get("fault_class") or ""),
                    str(data.get("vulnerability_class") or ""))
        for i, existing in enumerate(self._configs):
            if (str(existing.get("unit_id") or ""), str(existing.get("fault_class") or ""),
                    str(existing.get("vulnerability_class") or "")) == identity:
                self._configs[i] = data
                return "::".join(identity)
        self._configs.append(data)
        return "::".join(identity)

    def append_note(self, project_id, key, note):
        self._notes.append({"revival_key": key, "note": note})
        return {"note_id": f"n{len(self._notes)}", "revival_key": key, "note": note}

    def read_configs_by_key(self, project_id, key):
        self.read_attempts += 1
        if self.fail_reads:
            raise OSError("store read failed (fixture)")
        return [c for c in self._configs
                if (str(c.get("unit_id") or "") + "::"
                    + str(c.get("fault_class") or "")) == key
                or (str(c.get("unit_id") or "") + "::"
                    + str(c.get("fault_class") or "") + "::"
                    + str(c.get("vulnerability_class") or "")) == key]

    def read_notes(self, project_id, key=None):
        self.read_attempts += 1
        if self.fail_reads:
            raise OSError("store read failed (fixture)")
        if key is None:
            return list(self._notes)
        return [n for n in self._notes if n.get("revival_key") == key]

    def read_configs(self, project_id):
        return list(self._configs)


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
        envisioned_test_primitives=["p"],
    )


def _ratify_drafts(inp) -> RatifyDecision:
    """The default ratify seam: amend every draft to ratified with the filled
    ratification fields (the fixture's ratification contract)."""
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
    """The default note seam: one fixture note for the pair (the pair end)."""
    return NoteDecision(notes=[NoteRecord(
        key=revival_key(inp.pair.unit_id, inp.pair.fault_class),
        note="fixture note: the reasoning that yielded the rationale",
    )])


def _tools(store, *, read_fn=None) -> OrchestratorTools:
    return OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=read_fn or (lambda cy, p: [])),
    )


def _run(store, candidates, *, hypothesise=None, ratify=None, note=None,
         **kwargs) -> OrchestratorReport:
    tools = kwargs.pop("tools", None) or _tools(store)
    return run_orchestration(
        project_id="project-1",
        run_id="run-1",
        candidates=candidates,
        tools=tools,
        hypothesise_fn=hypothesise or (
            lambda inp: GateDecision(directions=[_carry(c) for c in inp.candidates])),
        ratify_fn=ratify or _ratify_drafts,
        note_fn=note or _note_pair,
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

    def hypothesise_fn(inp):
        gate_inputs.append(inp.candidates)
        return GateDecision(directions=[])

    report = _run(store, [cand], hypothesise=hypothesise_fn)
    assert report.pruned_by_verdict == 1
    assert report.pairs_processed == 0
    assert report.configs_hypothesised == 0
    assert gate_inputs == []  # a pruned-only pass never spends a hypothesise turn


# --- Pure mechanics: the D3 HuntConfig minting --------------------------------

def test_mint_hunt_config_mints_a_hypothesised_draft():
    # the rework (spec 3.5): a direction with no elicited vulnerability classes
    # degrades to ONE carried-bare draft - status="hypothesised", rationale +
    # research_direction filled, the ratification-phase fields empty
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
    assert config.status == "hypothesised"
    assert config.vulnerability_class == ""
    template = config.prompt_template
    assert template.rationale == "r"
    assert template.research_direction == ""
    assert template.l0_evidence == ["llm: witness"]
    # the ratification-phase fields are empty in the hypothesised draft
    assert config.adversarial_capabilities == []
    assert config.assumptions == []
    assert config.technique_primitives == []
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
    fault still reasons about the broken-access-control fault first - the
    supervisor pops its pair before the residual tier's."""
    store = _MemoryStore()
    reason_order: list[str] = []

    def hypothesise_fn(inp):
        reason_order.append(inp.candidates[0].fault_class)
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    report = _run(
        store,
        [_candidate(SERVICE_A, "CWE-601"),   # open redirect, tier 4, FIRST
         _candidate(SERVICE_A, "CWE-639")],  # IDOR, tier 0, SECOND
        hypothesise=hypothesise_fn,
    )
    assert report.pairs_processed == 2
    assert report.configs_ratified == 2
    assert reason_order == ["CWE-639", "CWE-601"]


def test_mint_fans_out_one_config_per_distinct_class():
    # N HuntConfigs per distinct elicited vulnerability class (the emitted
    # set): the class is the config's identity axis (spec 3.5 / ADR G5)
    direction = _carry(_candidate(deterministic_witness=None))
    direction.vulnerability_classes = ["csrf", "idor", "ssti"]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
        sub_fault_ids=["CWE-520", "CWE-9"],
    )
    assert len(configs) == 3
    # each config carries its own class as the identity axis
    assert [c.vulnerability_class for c in configs] == ["csrf", "idor", "ssti"]
    # every fan-out config is a hypothesised draft
    assert all(c.status == "hypothesised" for c in configs)
    assert all(c.prompt_template.rationale == "r" for c in configs)
    # the seeding identity persists on every fan-out config
    assert {c.unit_id for c in configs} == {SERVICE_A}
    assert {c.fault_class for c in configs} == {FAULT_X}
    # sub_fault_ids feeds EACH class-config (the fold family, #66 non-conflation)
    assert all(c.sub_fault_ids == ["CWE-520", "CWE-9"] for c in configs)


def test_mint_collapses_same_class_duplicates_deterministically():
    # the (LLM-owned, Q16) same-class merge should already have removed
    # duplicates; the mint still collapses same-class emissions into one
    # config, keeping first-emission order
    direction = _carry(_candidate(deterministic_witness=None))
    direction.vulnerability_classes = ["csrf", "csrf", "idor"]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert len(configs) == 2
    assert [c.vulnerability_class for c in configs] == ["csrf", "idor"]


def test_mint_without_classes_is_the_carried_bare_fallback():
    # a direction with no elicited class markers still mints ONE dispatchable
    # hypothesised draft with research_direction (no class-specific identity)
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
    assert config.vulnerability_class == ""
    assert config.prompt_template.research_direction == \
        "csrf hygiene across state-changing flows"
    assert config.status == "hypothesised"


def test_mint_with_only_empty_classes_is_the_carried_bare_fallback():
    # class strings carrying no marker degrade the same way (fail-open)
    direction = _carry(_candidate(deterministic_witness=None))
    direction.vulnerability_classes = ["", ""]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert len(configs) == 1
    assert configs[0].vulnerability_class == ""


def test_mint_passes_research_direction_and_preserves_the_identity_slots():
    # the reworked template mapping: research_direction passes through, the
    # class identity rides each fan-out config, and the ratification-phase
    # fields stay empty on the hypothesised draft
    direction = _carry(_candidate(deterministic_witness=None))
    direction.research_direction = "enumerating the receipts resource"
    direction.vulnerability_classes = ["idor", "csrf"]
    configs = mint_hunt_config(
        direction=direction, candidate=_candidate(deterministic_witness=None),
        hunt_id="hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
    )
    assert [c.hunt_id for c in configs] == ["hunt-1", "hunt-1-1"]
    assert [c.vulnerability_class for c in configs] == ["idor", "csrf"]
    for config in configs:
        template = config.prompt_template
        assert template.rationale == "r"
        assert template.l0_evidence == ["llm: witness"]
        assert template.research_direction == "enumerating the receipts resource"
        assert config.status == "hypothesised"
        assert config.adversarial_capabilities == []
        assert config.assumptions == []
        assert config.technique_primitives == []


def test_surface_context_replaces_edge_degree_with_connected_data_items():
    """The config surface-context transform (ADR G5): a Service card's
    edge_degree counts are replaced by the detailed connected DataItems
    (name/type/sensitivity/fields/notes) from the unit's rich projection;
    an absent projection, a non-matching card, or a malformed card degrades
    unchanged (fail-open)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        _surface_cards_with_connected_data_items,
    )
    from polymerhus.attack.hunting.unit_projection import (  # noqa: PLC0415
        DataItem,
        UnitProjection,
    )

    card = {
        "kind": "Service",
        "key": {"business_function_slug": "a"},
        "edge_degree": {"EXPOSED_VIA": 1, "CONSUMES": 1},
        "spine": {"exposure": "public"},
    }
    proj = UnitProjection(
        unit_id="Service:a", kind="Service", spine={}, edges={},
        data_edges={"CONSUMES": 1}, data_rel_kinds=frozenset(),
        data_items={
            "CONSUMES": (
                DataItem(item_key="session_token", name="session token", type="secret",
                         sensitivity="high", fields=("sid",), notes="session-bound"),
            ),
            "PRODUCES": (
                DataItem(item_key="order", name="order", type="record",
                         sensitivity="medium", fields=("id",), notes="order record"),
            ),
        },
    )
    cards = _surface_cards_with_connected_data_items([card], proj)
    transformed = cards[0]
    assert "edge_degree" not in transformed
    # families render sorted (render determinism, M1)
    assert list(transformed["connected_data_items"]) == ["CONSUMES", "PRODUCES"]
    assert transformed["connected_data_items"]["CONSUMES"] == [
        {"name": "session token", "type": "secret", "sensitivity": "high",
         "fields": ["sid"], "notes": "session-bound"},
    ]
    assert transformed["spine"] == {"exposure": "public"}  # rest of the card kept
    # a non-matching card degrades to its counts card
    other = {"kind": "System", "key": {"kind": "cache", "discriminator": "1"},
             "edge_degree": {"DEPENDS_ON": 2}}
    assert _surface_cards_with_connected_data_items([other], proj) == [other]
    # an absent projection degrades to the counts card (fail-open)
    assert _surface_cards_with_connected_data_items([card], None) == [card]
    # a projection whose unit does not match the card degrades to the counts card
    other_proj = UnitProjection(
        unit_id="Service:slug:b", kind="Service", spine={}, edges={},
        data_edges={}, data_rel_kinds=frozenset(),
        data_items={"PRODUCES": (DataItem(item_key="k", name="x"),)},
    )
    assert _surface_cards_with_connected_data_items([card], other_proj) == [card]
    # a malformed card (a non-dict element) degrades unchanged, never a raise
    malformed = ["not-a-dict"]
    assert _surface_cards_with_connected_data_items(malformed, proj) == malformed
    # a Service card whose key is not a dict degrades unchanged, never a raise
    broken_key = {"kind": "Service", "key": "not-a-dict",
                  "edge_degree": {"EXPOSED_VIA": 1}}
    assert _surface_cards_with_connected_data_items([broken_key], proj) == [broken_key]


def test_fanned_out_direction_ratifies_each_config_and_notes_the_pair():
    # the hypothesise fan-out lands one draft per distinct class; the ratify
    # phase amends them to ratified; the note phase writes one note for the pair
    store = _MemoryStore()

    def hypothesise_fn(inp):
        direction = _carry(inp.candidates[0])
        direction.vulnerability_classes = ["csrf class", "idor class"]
        return GateDecision(directions=[direction])

    report = _run(store, [_candidate()], hypothesise=hypothesise_fn)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 2
    assert report.configs_ratified == 2
    assert report.notes_written == 1
    # the memory topology: two ratified configs in produced/ (one per distinct
    # class), one note in memory.yaml (one per pair)
    configs = store.read_configs("project-1")
    assert len(configs) == 2
    assert all(c["status"] == "ratified" for c in configs)
    assert len(store.read_notes("project-1")) == 1


# --- Seam behaviours: fail-open degradations ----------------------------------

def test_store_read_failure_degrades_prior_insights(caplog):
    store = _MemoryStore(fail_reads=True)
    report = _run(store, [_candidate()])
    assert report.pairs_processed == 1
    assert store.read_attempts >= 1
    assert "warning" in caplog.text.lower()


def test_graph_view_query_failure_degrades_the_gate(caplog):
    store = _MemoryStore()

    def broken_read(cypher, params):
        raise RuntimeError("graph read failed (fixture)")

    seen: dict = {}

    def hypothesise_fn(inp):
        seen["surface"] = inp.surface
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate()], tools=_tools(store, read_fn=broken_read),
                  hypothesise=hypothesise_fn)
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert seen["surface"] == []
    assert "warning" in caplog.text.lower()


def test_hypothesise_turn_failure_skips_the_pair_not_fabricates(caplog):
    """#186 - a raising hypothesise turn SKIPS the pair (counted) instead of
    minting a fully-empty draft: the actor-death fabrication (63 empty configs
    in the confirmed eval) is dead - the pair is counted skipped, nothing is
    written, and the pass keeps serving."""
    store = _MemoryStore()

    def boom(inp):
        raise RuntimeError("hypothesise turn exhausted")

    report = _run(store, [_candidate()], hypothesise=boom)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 0     # nothing fabricated on disk
    assert report.configs_ratified == 0
    assert report.ledger.units_skipped == 1
    assert store.read_configs("project-1") == []
    assert "warning" in caplog.text.lower()


def test_ratify_turn_failure_keeps_the_drafts_hypothesised(caplog):
    """The ratify phase degrades fail-open: a raising ratify turn skips the
    phase's side effect - the hypothesised drafts stay on disk, never become
    ratified - but the pair keeps serving (the note phase still runs)."""
    store = _MemoryStore()

    def boom(inp):
        raise RuntimeError("ratify turn exhausted")

    report = _run(store, [_candidate()], ratify=boom)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 1
    assert report.configs_ratified == 0
    assert store.read_configs("project-1")[0]["status"] == "hypothesised"
    assert "warning" in caplog.text.lower()


def test_note_turn_failure_skips_the_note(caplog):
    """The note phase degrades fail-open: a raising note turn skips the note's
    side effect (no note lands) but the pass still completes."""
    store = _MemoryStore()

    def boom(inp):
        raise RuntimeError("note turn exhausted")

    report = _run(store, [_candidate()], note=boom)
    assert report.pairs_processed == 1
    assert report.notes_written == 0
    assert store.read_notes("project-1") == []
    assert "warning" in caplog.text.lower()


def test_gate_pruned_direction_writes_no_config():
    store = _MemoryStore()
    cand = _candidate()

    def pruning_gate(inp):
        direction = _carry(inp.candidates[0])
        return GateDecision(directions=[
            EnvisionedDirection(unit_id=direction.unit_id, fault_class=direction.fault_class,
                                carried=False)])

    report = _run(store, [cand], hypothesise=pruning_gate)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 0
    assert report.notes_written == 0
    assert report.gate_pruned == (revival_key(SERVICE_A, FAULT_X),)
    assert store.read_configs("project-1") == []


def test_ratify_returning_unratified_configs_does_not_count_them_ratified_and_does_not_note(caplog):
    """S2 - the "must END with ratified" contract: a ratify turn that returns
    still-hypothesised configs does NOT count them ratified, does NOT re-persist
    them, and the note phase does NOT note over them (the draft stays
    hypothesised on disk, the pair is still ratifying)."""
    store = _MemoryStore()

    def ratify_return_unratified(inp):
        # return the drafts verbatim (still hypothesised) - the turn did NOT end
        # with ratified
        return RatifyDecision(configs=list(inp.configs))

    report = _run(store, [_candidate()], ratify=ratify_return_unratified)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 1
    assert report.configs_ratified == 0
    assert report.configs_unratified == 1
    assert report.notes_written == 0
    assert store.read_configs("project-1")[0]["status"] == "hypothesised"
    assert store.read_notes("project-1") == []


def test_gate_pruned_pair_does_not_invoke_ratify():
    """S5 - a gate-pruned pair has no drafts and the ratify seam is NOT
    invoked (the pass keeps serving)."""
    store = _MemoryStore()
    cand = _candidate()
    ratify_calls: list = []

    def pruning_gate(inp):
        direction = _carry(inp.candidates[0])
        return GateDecision(directions=[
            EnvisionedDirection(unit_id=direction.unit_id, fault_class=direction.fault_class,
                                carried=False)])

    def spying_ratify(inp):
        ratify_calls.append(inp.pair.unit_id)
        return _ratify_drafts(inp)

    report = _run(store, [cand], hypothesise=pruning_gate, ratify=spying_ratify)
    assert ratify_calls == []
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 0


def test_multi_direction_for_one_pair_accumulates_all_drafts():
    """S8 - a model returning several carried directions for ONE pair (all at
    the same locus) accumulates every draft into the ratify set instead of
    earlier drafts being orphaned forever-hypothesised."""
    store = _MemoryStore()

    def hypothesise_two_dirs(inp):
        c = inp.candidates[0]
        d1 = EnvisionedDirection(unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
                                 rationale="r", vulnerability_classes=["CSRF"])
        d2 = EnvisionedDirection(unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
                                 rationale="r", vulnerability_classes=["IDOR"])
        return GateDecision(directions=[d1, d2])

    report = _run(store, [_candidate()], hypothesise=hypothesise_two_dirs)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 2
    assert report.configs_ratified == 2
    assert len(store.read_configs("project-1")) == 2
    assert {c["vulnerability_class"] for c in store.read_configs("project-1")} == {"CSRF", "IDOR"}
    assert report.ledger.units_done == 1  # one pair, one unit done
    assert len(report.ledger.minted_config_keys) == 1  # one locus key


def test_note_next_pair_at_fault_drain_carries_next_fault_first_candidate():
    """S3 - when the last pair of a fault drains but the schedule holds
    another fault, the note phase's next_pair is the next fault's first
    candidate (not None), so the tool-call response carries the correct frame."""
    store = _MemoryStore()
    c_352 = _candidate(SERVICE_A, "CWE-352")
    c_639 = _candidate(SERVICE_A, "CWE-639")
    captured: list[dict | None] = []
    tools = _tools(store)

    def spying_note(inp):
        # next_pair is set BEFORE this turn is invoked (S3)
        captured.append(dict(tools.phase_context.next_pair)
                        if tools.phase_context.next_pair is not None else None)
        return _note_pair(inp)

    report = _run(store, [c_352, c_639], tools=tools, note=spying_note)
    assert report.pairs_processed == 2
    # first note's next_pair is the next fault's candidate, last is None
    assert len(captured) == 2
    assert captured[0] is not None
    assert captured[1] is None
    # the first next_pair points at whichever fault is second in schedule
    assert captured[0]["unit_id"] == SERVICE_A
    assert captured[0]["fault_class"] in ("CWE-352", "CWE-639")


# --- The async-native parent entry point (#94) --------------------------------

def _arun(store, candidates, **kwargs):
    """`_run`'s async twin: same scenario driven through `arun_orchestration`."""
    import asyncio

    from polymerhus.attack.hunting.hunt_orchestrator import arun_orchestration

    return asyncio.run(arun_orchestration(
        project_id="project-1", run_id="run-1", candidates=candidates,
        tools=_tools(store),
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
        **kwargs,
    ))


def test_arun_orchestration_matches_the_sync_pass():
    """The async-native parent entry point produces the IDENTICAL report to the sync
    pass for the same scenario - it single-sources the O1-O10 fail-open canon by
    running `run_orchestration` off the event loop, never re-implementing it."""
    sync_report = _run(_MemoryStore(), [_candidate()])
    async_report = _arun(_MemoryStore(), [_candidate()])
    assert async_report.model_dump() == sync_report.model_dump()
    assert async_report.pairs_processed == 1
    assert async_report.configs_ratified == 1


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
            hypothesise_fn=lambda inp: GateDecision(
                directions=[_carry(c) for c in inp.candidates]),
            ratify_fn=_ratify_drafts,
            note_fn=_note_pair,
        )
        await beat
        return report, ticks

    report, ticks = asyncio.run(_drive())
    assert report.pairs_processed == 1
    assert ticks == 50  # the loop kept ticking while the pass ran off-loop


# --- I3: prior_hunt_insights never embed nested configs (no snowball) ---------

def test_prior_hunt_insights_never_embed_nested_configs():
    """I3 - the recursive prior_hunt_insights snowball is broken: a minted
    config's prior_hunt_insights carries a shallow PROJECTION of each prior
    config (identity + hypothesise seeds), never the full dump - so a persisted
    config never embeds another config's prior_hunt_insights (the nesting
    would grow unbounded across passes)."""
    store = _MemoryStore()
    # pass N-1's persisted config carried ITS prior-hunt insights (the old
    # full-dump merge); the projection must strip that baggage
    store.write_config("project-1", {
        "unit_id": SERVICE_A, "fault_class": FAULT_X,
        "vulnerability_class": "CSRF", "status": "hypothesised",
        "hunt_id": "prior",
        "prompt_template": {"rationale": "r", "research_direction": "rd"},
        "prior_hunt_insights": [{"unit_id": "ancient"}],
    })
    report = _run(store, [_candidate()])
    assert report.pairs_processed == 1
    minted = [c for c in store.read_configs("project-1")
              if c.get("hunt_id") != "prior"]
    assert len(minted) == 1
    insights = minted[0]["prior_hunt_insights"]
    assert insights, "the second pass should have read the prior config as an insight"
    # never a nested prior_hunt_insights key (the snowball is cut)
    for insight in insights:
        assert "prior_hunt_insights" not in insight
    # the projection keeps the identity + hypothesise seeds for the Q11 read
    assert any(i.get("unit_id") == SERVICE_A and i.get("fault_class") == FAULT_X
               for i in insights)


# --- #186: anti-fabrication in the canon (skip on an empty decision) -----------

def test_empty_hypothesise_decision_skips_the_pair_instead_of_fabricating():
    """#186 - the anti-fabrication canon: a None/empty hypothesise decision
    SKIPS the pair (counted on the ledger) instead of minting a fully-empty
    draft - the exact defect that minted 63 empty configs after the actor died
    in the confirmed hunt-orchestrator eval. The genuine carried-bare (a model
    direction with a rationale but no class) is preserved elsewhere (below)."""
    store = _MemoryStore()
    report = _run(store, [_candidate()],
                  hypothesise=lambda inp: GateDecision(directions=[]))
    assert report.pairs_processed == 1
    assert report.ledger.units_skipped == 1
    assert report.ledger.units_done == 0
    assert report.configs_hypothesised == 0
    assert report.configs_ratified == 0
    assert store.read_configs("project-1") == []     # nothing fabricated on disk


def test_carried_bare_direction_with_rationale_is_still_minted():
    """#186 - the genuine carried-bare survives the anti-fabrication canon: a
    direction the model EMITTED with a rationale but no elicited vulnerability
    class still fans out to the single carried-bare hypothesised draft (the
    mint's class-less degrade, spec 3.5)."""
    store = _MemoryStore()

    def hypothesise_fn(inp):
        c = inp.candidates[0]
        return GateDecision(directions=[EnvisionedDirection(
            unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
            rationale="plausible at this locus", research_direction="probe the flow")])

    report = _run(store, [_candidate()], hypothesise=hypothesise_fn)
    assert report.pairs_processed == 1
    assert report.ledger.units_done == 1
    assert report.ledger.units_skipped == 0
    assert report.configs_hypothesised == 1
    configs = store.read_configs("project-1")
    assert len(configs) == 1
    assert configs[0]["vulnerability_class"] == ""
    assert configs[0]["prompt_template"]["rationale"] == "plausible at this locus"