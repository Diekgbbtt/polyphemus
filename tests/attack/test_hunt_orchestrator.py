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
    Witness,
    hunt_id_for,
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
        # the agent-sole write counters (#294): the harness must add none
        self.write_calls = 0
        self.update_calls = 0
        self.append_calls = 0

    def write_config(self, project_id, config):
        self.write_calls += 1
        data = config.model_dump() if not isinstance(config, dict) else dict(config)
        self._configs.append(data)
        return f"{data.get('unit_id')}::{data.get('fault_class')}::{data.get('vulnerability_class')}"

    def update_config(self, project_id, config):
        self.update_calls += 1
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
        self.append_calls += 1
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

    def read_hunter_specs(self, project_id, key):
        self.read_attempts += 1
        if self.fail_reads:
            raise OSError("store read failed (fixture)")
        return []

    def read_hunter_notes(self, project_id, key):
        self.read_attempts += 1
        if self.fail_reads:
            raise OSError("store read failed (fixture)")
        return []


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
        rationale="r", research_direction="",
    )


def _ratify_drafts(inp) -> RatifyDecision:
    """The default ratify seam: amend every draft to ratified with the filled
    ratification fields (the fixture's ratification contract)."""
    configs = []
    for draft in inp.configs:
        amended = draft.model_copy(deep=True)
        amended.status = "ratified"
        amended.preconditions = ["an authenticated session is obtainable"]
        amended.observed_defences = ["WAF blocks XSS payloads"]
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


# --- #294: agent-owned writes (the agent's tool call is the sole writer) -------

def _safe_store_write(method, *args):
    """The `hunts_store` / `notes` tool's fail-open (O3): a raising store write
    is caught and the tool returns an error object, so the phase turn still
    returns its structured decision - exactly the production behaviour."""
    try:
        return method(*args)
    except Exception:  # noqa: BLE001 - the tool degrades fail-open (O3)
        return None


def _agent_hypothesise(tools, *, classes=None):
    """A hypothesise seam that emulates the AGENT's `hunts_store(write)` tool
    call under the agent-sole model: it mints and writes each carried direction
    through the store seam the pass wraps, exactly as the model's tool call
    does (including the tool's fail-open on a raising write). `classes=None`
    keeps the carried-bare degrade."""
    def hypothesise(inp):
        directions = []
        for candidate in inp.candidates:
            direction = _carry(candidate)
            if classes is not None:
                direction.vulnerability_classes = list(classes)
            directions.append(direction)
            for config in mint_hunt_config(
                    direction,
        surface_context={}, prior_hunt_insights=[]):
                _safe_store_write(tools.store_reads.write_config, "project-1", config)
        return GateDecision(directions=directions)
    return hypothesise


def _agent_ratify(tools):
    """A ratify seam that emulates the agent's `hunts_store(write,
    status='ratified')` tool call: it amends each draft and writes it through
    the store seam the pass wraps (with the tool's fail-open)."""
    def ratify(inp):
        configs = []
        for draft in inp.configs:
            amended = draft.model_copy(deep=True)
            amended.status = "ratified"
            amended.preconditions = ["an authenticated session is obtainable"]
            amended.observed_defences = ["WAF blocks XSS payloads"]
            _safe_store_write(tools.store_reads.update_config, "project-1", amended)
            configs.append(amended)
        return RatifyDecision(configs=configs)
    return ratify


def _agent_note(tools, *, text="fixture note: the reasoning that yielded the rationale"):
    """A note seam that emulates the agent's `notes(write, option='append')`
    tool call (with the tool's fail-open)."""
    def note(inp):
        key = revival_key(inp.pair.unit_id, inp.pair.fault_class)
        _safe_store_write(tools.store_reads.append_note, "project-1", key, text)
        return NoteDecision(notes=[NoteRecord(key=key, note=text)])
    return note


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


def test_applies_without_any_witness_is_malformed():
    intake = normalize_candidates([_candidate(llm_witness=None)])
    assert len(intake.accepted) == 0
    assert intake.malformed_dropped == 1


def test_deterministic_only_witness_is_accepted_not_malformed():
    """#200 (spec 4.1): the llm witness half is OPTIONAL - a candidate carrying
    a deterministic witness alone is accepted, never dropped as malformed (the
    platform's own internal selection emits deterministic-only witnesses)."""
    intake = normalize_candidates([_candidate(
        llm_witness=None,
        deterministic_witness="reachable-via(EXPOSED_VIA, {GraphQLApi})")])
    assert len(intake.accepted) == 1
    assert intake.malformed_dropped == 0
    assert intake.accepted[0].applies_witnesses.llm is None


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
    # the rework (spec 3.5, #202): a direction with no elicited vulnerability
    # classes degrades to ONE carried-bare draft - status="hypothesised",
    # rationale + research_direction filled, the ratification-phase fields
    # (preconditions / observed_defences) empty
    candidate = _candidate(deterministic_witness=None)
    config = mint_hunt_config(
        direction=_carry(candidate),
        surface_context={"card": {"kind": "Service", "spine": {}}},
        prior_hunt_insights=[{"kind": "prior_verdict", "verdict": "unsuccessful"}],
    )[0]
    assert config.hunt_id == hunt_id_for(SERVICE_A, FAULT_X, "")
    assert config.unit_id == SERVICE_A
    assert config.fault_class == FAULT_X
    assert config.status == "hypothesised"
    assert config.vulnerability_class == ""
    template = config.prompt_template
    assert template.rationale == "r"
    assert template.research_direction == ""
    # the ratification-phase fields are empty in the hypothesised draft
    assert config.preconditions == []
    assert config.observed_defences == []
    assert config.surface_context["card"]["kind"] == "Service"
    assert config.prior_hunt_insights == [
        {"kind": "prior_verdict", "verdict": "unsuccessful"}]


def test_surface_context_folds_the_candidate_applies_witness():
    """#298: the former `prompt_template.l0_evidence` slot is gone; the
    candidate's applies-witness rides the orchestrator-owned `surface_context`
    as `fault_evidence` (ONE L0-evidence field)."""
    from polymerhus.attack.hunting.hunt_orchestrator import _surface_context_for

    candidate = _candidate(deterministic_witness="clause-x", llm_witness="why")
    ctx = _surface_context_for([], None, applies_witness=candidate.applies_witnesses)
    assert ctx["fault_evidence"] == ["deterministic: clause-x", "llm: why"]
    # an absent witness degrades to no key (fail-open)
    assert "fault_evidence" not in _surface_context_for([], None)
    # the hunter prompt renders the folded evidence, not a template slot
    from polymerhus.attack.hunting.hunting_agent import _compose_grounding
    config = mint_hunt_config(
        direction=_carry(candidate),
        surface_context=_surface_context_for(
            [], None, applies_witness=candidate.applies_witnesses),
        prior_hunt_insights=[],
    )[0]
    text = _compose_grounding(config)
    assert "L0 fault-applicability evidence:" in text
    assert "deterministic: clause-x" in text and "llm: why" in text


def test_surface_context_store_injects_prior_hunt_insights():
    """#201/#298: `prior_hunt_insights` is orchestrator-owned downstream material
    applied on the write seam (like `surface_context`). The seam injects the
    pair's insights - a model-authored value is replaced - and a turn that
    threads none leaves the config's own value untouched."""
    from polymerhus.attack.hunting.hunt_orchestrator import SurfaceContextStore

    seam = SurfaceContextStore(_MemoryStore(), surface=[])
    insights = [{"kind": "prior_verdict", "verdict": "unsuccessful"}]
    seam.set_projection(None, prior_hunt_insights=insights)
    injected = seam._inject({"unit_id": "u",
                             "prior_hunt_insights": [{"model": "authored"}]})
    assert injected["prior_hunt_insights"] == insights
    # a turn with no threaded insights leaves the config's own value alone
    seam.set_projection(None)
    kept = seam._inject({"unit_id": "u", "prior_hunt_insights": [{"keep": True}]})
    assert kept["prior_hunt_insights"] == [{"keep": True}]


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
        direction=direction,
        surface_context={}, prior_hunt_insights=[],
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
    # #298: each config's hunt_id is derived from its own identity, no order element
    assert [c.hunt_id for c in configs] == [
        hunt_id_for(SERVICE_A, FAULT_X, cls) for cls in ("csrf", "idor", "ssti")]


def test_mint_collapses_same_class_duplicates_deterministically():
    # the (LLM-owned, Q16) same-class merge should already have removed
    # duplicates; the mint still collapses same-class emissions into one
    # config, keeping first-emission order
    direction = _carry(_candidate(deterministic_witness=None))
    direction.vulnerability_classes = ["csrf", "csrf", "idor"]
    configs = mint_hunt_config(
        direction=direction,
        surface_context={}, prior_hunt_insights=[],
    )
    assert len(configs) == 2
    assert [c.vulnerability_class for c in configs] == ["csrf", "idor"]


def test_mint_without_classes_is_the_carried_bare_fallback():
    # a direction with no elicited class markers still mints ONE dispatchable
    # hypothesised draft with research_direction (no class-specific identity)
    direction = _carry(_candidate(deterministic_witness=None))
    direction.research_direction = "csrf hygiene across state-changing flows"
    configs = mint_hunt_config(
        direction=direction,
        surface_context={}, prior_hunt_insights=[],
    )
    assert len(configs) == 1
    config = configs[0]
    assert config.hunt_id == hunt_id_for(SERVICE_A, FAULT_X, "")
    assert config.vulnerability_class == ""
    assert config.prompt_template.research_direction == \
        "csrf hygiene across state-changing flows"
    assert config.status == "hypothesised"


def test_mint_with_only_empty_classes_is_the_carried_bare_fallback():
    # class strings carrying no marker degrade the same way (fail-open)
    direction = _carry(_candidate(deterministic_witness=None))
    direction.vulnerability_classes = ["", ""]
    configs = mint_hunt_config(
        direction=direction,
        surface_context={}, prior_hunt_insights=[],
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
        direction=direction,
        surface_context={}, prior_hunt_insights=[],
    )
    assert [c.hunt_id for c in configs] == [
        hunt_id_for(SERVICE_A, FAULT_X, "idor"),
        hunt_id_for(SERVICE_A, FAULT_X, "csrf")]
    assert [c.vulnerability_class for c in configs] == ["idor", "csrf"]
    for config in configs:
        template = config.prompt_template
        assert template.rationale == "r"
        assert template.research_direction == "enumerating the receipts resource"
        assert config.status == "hypothesised"
        assert config.preconditions == []
        assert config.observed_defences == []


def test_surface_context_replaces_edge_degree_with_connected_data_items():
    """The config surface-context transform (ADR G5): a Service card's
    edge_degree counts are replaced by the detailed connected DataItems
    (name/type/sensitivity/fields/notes) from the unit's rich projection;
    an absent projection, a non-matching card, or a malformed card degrades
    unchanged (fail-open)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        service_card_projection,
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
    cards = service_card_projection([card], proj)
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
    assert service_card_projection([other], proj) == [other]
    # an absent projection degrades to the counts card (fail-open)
    assert service_card_projection([card], None) == [card]
    # a projection whose unit does not match the card degrades to the counts card
    other_proj = UnitProjection(
        unit_id="Service:slug:b", kind="Service", spine={}, edges={},
        data_edges={}, data_rel_kinds=frozenset(),
        data_items={"PRODUCES": (DataItem(item_key="k", name="x"),)},
    )
    assert service_card_projection([card], other_proj) == [card]
    # a malformed card (a non-dict element) degrades unchanged, never a raise
    malformed = ["not-a-dict"]
    assert service_card_projection(malformed, proj) == malformed
    # a Service card whose key is not a dict degrades unchanged, never a raise
    broken_key = {"kind": "Service", "key": "not-a-dict",
                  "edge_degree": {"EXPOSED_VIA": 1}}
    assert service_card_projection([broken_key], proj) == [broken_key]


def test_service_card_projection_surfaces_aggregated_endpoints_under_parent_unit():
    """#201: the renamed service-card projection expands the config's target
    unit card WITH its aggregated L0 Endpoints (method/path/baseurl from the
    projection's AGGREGATES slot) under the parent unit, sorted; a System card
    carries its linked services' endpoints with the owning service slug; the
    expansion fires ONLY for the target unit (a sibling card stays unchanged -
    the DD-4 token-light budget is load-bearing)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        service_card_projection,
    )
    from polymerhus.attack.hunting.unit_projection import (  # noqa: PLC0415
        AggregatedEndpoint,
        UnitProjection,
    )

    card = {
        "kind": "Service",
        "key": {"business_function_slug": "checkout"},
        "edge_degree": {"AGGREGATES": 2},
        "spine": {"exposure": "public"},
    }
    sibling = {
        "kind": "Service",
        "key": {"business_function_slug": "orders"},
        "edge_degree": {"AGGREGATES": 9},
        "spine": {"exposure": "internal"},
    }
    proj = UnitProjection(
        unit_id="Service:checkout", kind="Service", spine={}, edges={},
        data_edges={}, data_rel_kinds=frozenset(),
        aggregated_endpoints=(
            AggregatedEndpoint(method="POST", path="/pay", baseurl="https://a"),
            AggregatedEndpoint(method="GET", path="/cart", baseurl="https://a"),
        ),
    )
    cards = service_card_projection([card, sibling], proj)
    transformed = cards[0]
    assert transformed["aggregated_endpoints"] == [
        {"method": "GET", "path": "/cart", "baseurl": "https://a"},
        {"method": "POST", "path": "/pay", "baseurl": "https://a"},
    ]
    assert "edge_degree" not in transformed
    # the sibling card is never expanded (target-unit-only expansion)
    assert cards[1] == sibling

    # the system contract: a System card surfaces its linked services'
    # endpoints with the owning service slug
    sys_card = {
        "kind": "System",
        "key": {"kind": "auth", "discriminator": "auth-1"},
        "edge_degree": {"DEPENDS_ON": 2},
        "spine": {"exposure": "internal"},
    }
    sys_proj = UnitProjection(
        unit_id="auth:auth-1", kind="auth", spine={}, edges={},
        data_edges={}, data_rel_kinds=frozenset(),
        aggregated_endpoints=(
            AggregatedEndpoint(method="POST", path="/login", baseurl="https://a",
                               service_slug="sign-in"),
        ),
    )
    cards = service_card_projection([sys_card], sys_proj)
    assert cards[0]["aggregated_endpoints"] == [
        {"method": "POST", "path": "/login", "baseurl": "https://a",
         "service_slug": "sign-in"},
    ]

    # an unbound L1 (no AGGREGATES) degrades to the card unchanged - no
    # aggregate slot, never a raise, never a prune signal
    unbound = UnitProjection(
        unit_id="Service:checkout", kind="Service", spine={}, edges={},
        data_edges={}, data_rel_kinds=frozenset(),
    )
    cards = service_card_projection([card], unbound)
    assert "aggregated_endpoints" not in cards[0]
    assert cards[0]["edge_degree"] == {"AGGREGATES": 2}


def test_fanned_out_direction_ratifies_each_config_and_notes_the_pair():
    # the hypothesise fan-out lands one draft per distinct class; the ratify
    # phase amends them to ratified; the note phase writes one note for the pair
    store = _MemoryStore()
    tools = _tools(store)

    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=_agent_hypothesise(tools, classes=["csrf class", "idor class"]),
                  ratify=_agent_ratify(tools),
                  note=_agent_note(tools))
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 2
    assert report.configs_ratified == 2
    assert report.notes_written == 1
    # the memory topology: two ratified configs in produced/ (one per distinct
    # class), one note in memory.yaml (one per pair) - all written by the agent
    configs = store.read_configs("project-1")
    assert len(configs) == 2
    assert all(c["status"] == "ratified" for c in configs)
    assert len(store.read_notes("project-1")) == 1


def test_ratify_upsert_reinjects_the_deterministic_surface_context():
    """#201 (Q3 ruling): the ratify upsert re-injects the minted surface_context
    (the deterministic typed assembly) - a model-authored surface_context is
    replaced, so the ratified config carries the aggregated L0 endpoints under
    the parent unit and the model never re-authors the shape."""
    store = _MemoryStore()

    def read_fn(cypher, params):
        if "AGGREGATES" in cypher:
            return [
                {"props": {"path": "/pay", "method": "POST", "baseurl": "https://a"}},
                {"props": {"path": "/cart", "method": "GET", "baseurl": "https://a"}},
            ]
        if "type(dr) AS family" in cypher:
            return []
        if "AS edges" in cypher:
            return [{"labels": ["L1Service"],
                     "props": {"business_function_slug": "slug:a"},
                     "edges": []}]
        return [{"labels": ["L1Service"],
                 "props": {"business_function_slug": "slug:a", "exposure": "public"},
                 "rels": ["AGGREGATES", "AGGREGATES"]}]

    tools = _tools(store, read_fn=read_fn)

    def ratify_fn(inp):
        configs = []
        for draft in inp.configs:
            amended = draft.model_copy(deep=True)
            amended.status = "ratified"
            amended.surface_context = {"model": "authored", "freeform": True}
            # emulate the agent's hunts_store(write, status='ratified') - the
            # #201 carve-out overwrites the model-authored shape on the seam
            tools.store_reads.update_config("project-1", amended)
            configs.append(amended)
        return RatifyDecision(configs=configs)

    report = _run(store, [_candidate()], tools=tools, ratify=ratify_fn)
    assert report.configs_ratified == 1
    configs = store.read_configs("project-1")
    assert len(configs) == 1
    assert configs[0]["status"] == "ratified"
    # the agent's hunts_store(write) is the ONLY ratify write (#294): the
    # harness no longer upserts a second copy of the decision
    assert store.update_calls == 1
    assert "model" not in configs[0]["surface_context"]
    cards = configs[0]["surface_context"]["cards"]
    transformed = cards[0]
    assert transformed["aggregated_endpoints"] == [
        {"method": "GET", "path": "/cart", "baseurl": "https://a"},
        {"method": "POST", "path": "/pay", "baseurl": "https://a"},
    ]


# --- #294: agent-owned writes (the agent's tool call is the sole writer) -------

def test_agent_note_write_is_the_sole_note_persist():
    """#294: the agent's `notes(write, option='append')` tool call is the SOLE
    note writer. The pre-#294 harness ALSO appended the structured decision's
    note, so whenever the two renderings differed two non-identical notes
    landed at one revival key (observed live). Here the decision's note text
    differs from the agent's tool write: exactly the agent's one survives."""
    store = _MemoryStore()
    tools = _tools(store)
    key = revival_key(SERVICE_A, FAULT_X)

    def agent_note(inp):
        tools.store_reads.append_note("project-1", key, "agent-authored note")
        return NoteDecision(
            notes=[NoteRecord(key=key, note="structured-decision note")])

    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=_agent_hypothesise(tools),
                  ratify=_agent_ratify(tools),
                  note=agent_note)
    notes = store.read_notes("project-1")
    assert [n["note"] for n in notes] == ["agent-authored note"]  # exactly one
    assert store.append_calls == 1  # the harness added no second append
    assert report.notes_written == 1


def test_hypothesise_does_not_backfill_a_config_without_the_agent_write():
    """#294: the harness no longer backfills the in-memory mint - with no
    agent `hunts_store(write, status='hypothesised')`, the phase persists
    nothing. The in-memory mint still drives the phase flow/report."""
    store = _MemoryStore()
    report = _run(store, [_candidate()],
                  hypothesise=lambda inp: GateDecision(
                      directions=[_carry(inp.candidates[0])]))
    assert store.read_configs("project-1") == []      # no backfill
    assert report.configs_hypothesised == 1           # the in-memory flow ran


def test_agent_hypothesise_write_persists_exactly_one_config():
    """#294: with the agent's `hunts_store(write)` the hypothesise phase
    persists exactly one config per elicited class - never a second
    harness-minted copy."""
    store = _MemoryStore()
    tools = _tools(store)
    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=_agent_hypothesise(tools, classes=["csrf"]))
    assert report.configs_hypothesised == 1
    configs = store.read_configs("project-1")
    assert len(configs) == 1
    assert configs[0]["status"] == "hypothesised"
    assert configs[0]["vulnerability_class"] == "csrf"
    assert store.write_calls == 1  # the harness added no second create


def test_agent_write_failure_degrades_without_crashing():
    """#294 fail-open (the TOOL's behaviour, not the phase turn's): the
    `hunts_store` / `notes` tool catches a raising store write and returns an
    error object, so the phase turn still returns its decision and the LATER
    writes succeed - the failed create is warned + counted on the wrapped seam
    and the pass keeps serving."""
    class _RaisingStore(_MemoryStore):
        def write_config(self, project_id, config):
            raise OSError("disk full (fixture)")

    store = _RaisingStore()
    tools = _tools(store)
    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=_agent_hypothesise(tools),
                  ratify=_agent_ratify(tools),
                  note=_agent_note(tools))
    assert report.pairs_processed == 1
    assert report.store_write_failures == 1  # exactly the failed hypothesise create
    assert report.ledger.units_skipped == 0  # the tool degrades, not the turn
    # the later agent writes succeeded: the ratify upsert created the ratified
    # config and the note landed
    configs = store.read_configs("project-1")
    assert len(configs) == 1 and configs[0]["status"] == "ratified"
    assert len(store.read_notes("project-1")) == 1


def test_surface_context_store_injects_the_deterministic_context():
    """#294 #201 carve-out: the store-seam wrapper injects the harness-owned
    deterministic `surface_context` before persisting, so the agent never
    authors the shape - a model-supplied dict is overwritten."""
    from polymerhus.attack.hunting.hunt_orchestrator import SurfaceContextStore

    store = _MemoryStore()
    wrapper = SurfaceContextStore(store, surface=[])
    wrapper.set_projection(None)
    wrapper.write_config("project-1", {
        "hunt_id": "h1", "unit_id": SERVICE_A, "fault_class": FAULT_X,
        "vulnerability_class": "csrf", "surface_context": {"model": "authored"},
    })
    wrapper.update_config("project-1", {
        "hunt_id": "h1", "unit_id": SERVICE_A, "fault_class": FAULT_X,
        "vulnerability_class": "csrf", "surface_context": {"model": "authored"},
    })
    configs = store.read_configs("project-1")
    assert len(configs) == 1
    assert configs[0]["surface_context"] == {"cards": []}


def test_surface_context_store_counts_note_write_failures():
    """#294 #6: the wrapper counts a failed `append_note` too, so
    `store_write_failures` covers every agent store write, not just the config
    writes; a successful write does not count."""
    from polymerhus.attack.hunting.hunt_orchestrator import SurfaceContextStore

    class _RaisingNotes(_MemoryStore):
        def append_note(self, project_id, key, note):
            raise OSError("notes disk full (fixture)")

    store = _RaisingNotes()
    wrapper = SurfaceContextStore(store, surface=[])
    with pytest.raises(OSError):
        wrapper.append_note("project-1", "Service:slug:a::fault-x", "note")
    assert wrapper.write_failures == 1
    wrapper.write_config("project-1", {
        "hunt_id": "h1", "unit_id": SERVICE_A, "fault_class": FAULT_X,
        "vulnerability_class": "csrf",
    })
    assert wrapper.write_failures == 1  # a successful write does not count


def test_hunts_store_tool_over_the_wrapped_seam_injects_surface_context_and_counts():
    """#294 S3: the REAL `hunts_store` tool (built by
    `build_orchestrator_tool_surface`) captures the wrapped store seam and
    passes a Dict (not a HuntConfig); the wrapper injects the deterministic
    `surface_context` into that dict and the tool degrades a raise fail-open
    while the wrapper counts the observed failure. This closes the closure-fake
    fidelity gap (an injected-seam test reads `tools.store_reads` itself and
    would not catch a broken closure capture)."""
    from polymerhus.attack.hunting.actors import build_orchestrator_tool_surface
    from polymerhus.attack.hunting.hunt_orchestrator import SurfaceContextStore

    cards = [{"kind": "Service", "key": {"business_function_slug": "slug:a"},
              "edge_degree": {"EXPOSED_VIA": 1}}]
    store = _MemoryStore()
    wrapper = SurfaceContextStore(store, surface=cards)
    wrapper.set_projection(None)
    tools = OrchestratorTools(
        store_reads=wrapper,
        graph_view=ReadOnlyGraphView("project-1", read_fn=lambda cy, p: []),
    )
    by_name = {t.name: t for t in build_orchestrator_tool_surface(
        tools, run_id="run-tool", project_id="project-1")}
    out = by_name["hunts_store"].invoke({"cmd": "write", "hunt_config": {
        "hunt_id": "h1", "unit_id": SERVICE_A, "fault_class": FAULT_X,
        "vulnerability_class": "csrf", "surface_context": {"model": "authored"},
    }})
    assert out["acknowledged"] is True
    configs = store.read_configs("project-1")
    assert len(configs) == 1
    # the harness-owned deterministic assembly overwrote the model-authored dict
    assert configs[0]["surface_context"] == {"cards": cards}
    assert wrapper.write_failures == 0

    # a raising inner write: the TOOL degrades fail-open (error dict, never a
    # raise into the turn) and the wrapper counts the observed failure
    class _Raising(_MemoryStore):
        def write_config(self, project_id, config):
            raise OSError("disk full (fixture)")

    failing_wrapper = SurfaceContextStore(_Raising(), surface=cards)
    failing_wrapper.set_projection(None)
    failing_tools = OrchestratorTools(
        store_reads=failing_wrapper,
        graph_view=ReadOnlyGraphView("project-1", read_fn=lambda cy, p: []),
    )
    failing_by_name = {t.name: t for t in build_orchestrator_tool_surface(
        failing_tools, run_id="run-tool-2", project_id="project-1")}
    err = failing_by_name["hunts_store"].invoke({"cmd": "write", "hunt_config": {
        "hunt_id": "h2", "unit_id": SERVICE_A, "fault_class": FAULT_X,
        "vulnerability_class": "csrf",
    }})
    assert "error" in err
    assert failing_wrapper.write_failures == 1


def test_hunts_store_write_rejects_a_payload_missing_the_identity():
    """#298: the file name is DERIVED from the identity attributes, so the tool
    must feed back a coded contract error naming the missing attribute and
    persist NOTHING - the surrogate of the live `_CWE-1220_.yaml` regression
    (a silent degenerate-name write the surfer could never ratify)."""
    from polymerhus.attack.hunting.actors import build_orchestrator_tool_surface
    from polymerhus.attack.hunting.hunt_orchestrator import SurfaceContextStore

    cards = [{"kind": "Service", "key": {"business_function_slug": "slug:a"}}]
    store = _MemoryStore()
    wrapper = SurfaceContextStore(store, surface=cards)
    wrapper.set_projection(None)
    tools = OrchestratorTools(
        store_reads=wrapper,
        graph_view=ReadOnlyGraphView("project-1", read_fn=lambda cy, p: []),
    )
    by_name = {t.name: t for t in build_orchestrator_tool_surface(
        tools, run_id="run-reject", project_id="project-1")}

    out = by_name["hunts_store"].invoke({"cmd": "write", "hunt_config": {
        "hunt_id": "h1", "fault_class": FAULT_X, "vulnerability_class": "csrf",
        "status": "ratified",
    }})
    assert out.get("rejected") is True
    assert out["error"] == "hunts_store_write_rejected"
    assert out["fields"] == ["unit_id"]
    assert "unit_id" in out["detail"]
    assert store.write_calls == 0 and store.update_calls == 0
    assert store.read_configs("project-1") == []

    # a valid payload still lands (the class is present here)
    ok = by_name["hunts_store"].invoke({"cmd": "write", "hunt_config": {
        "hunt_id": "h1", "unit_id": SERVICE_A, "fault_class": FAULT_X,
        "vulnerability_class": "csrf", "status": "ratified",
    }})
    assert ok["acknowledged"] is True


def test_surface_store_is_stable_across_passes_on_one_run():
    """#294 requirement 2: the actor's tool surface captures the store seam
    ONCE. A second pass on the SAME run_id with a fresh OrchestratorTools/store
    must retarget that SAME wrapper, so (a) the second pass's agent write lands
    in the second store carrying the SECOND pass's deterministic
    `surface_context` (never the first's), and (b) the second report's counters
    observe the second pass's writes."""
    import asyncio

    from polymerhus.attack.hunting.actors import build_orchestrator_tool_surface
    from polymerhus.attack.hunting.hunt_orchestrator import _reap_orchestrator

    class _FakeView:
        def __init__(self, cards):
            self._cards = cards

        def index_cards(self):
            return list(self._cards)

        def read(self, cypher, params=None):
            return []

    class _FlakyOnce(_MemoryStore):
        def __init__(self):
            super().__init__()
            self._left = 1

        def write_config(self, project_id, config):
            if self._left > 0:
                self._left -= 1
                raise OSError("disk full (fixture)")
            return super().write_config(project_id, config)

    run_id = "run-stable-" + uuid.uuid4().hex[:8]
    store1 = _MemoryStore()
    store2 = _FlakyOnce()
    tools1 = OrchestratorTools(store_reads=store1,
                               graph_view=_FakeView([{"marker": "pass-1"}]))
    tools2 = OrchestratorTools(store_reads=store2,
                               graph_view=_FakeView([{"marker": "pass-2"}]))
    captured: dict = {}

    def agent_hypothesise(inp):
        # emulate the actor's `_ensure_started`: build the tool surface ONCE, so
        # the captured seam is pass 1's wrapper (and must be retargeted later)
        if "surface" not in captured:
            captured["surface"] = {t.name: t for t in build_orchestrator_tool_surface(
                tools1, run_id=run_id, project_id="project-1")}
        directions = [_carry(c) for c in inp.candidates]
        for direction in directions:
            for config in mint_hunt_config(
                    direction,
        surface_context={}, prior_hunt_insights=[]):
                captured["surface"]["hunts_store"].invoke(
                    {"cmd": "write", "hunt_config": config.model_dump()})
        return GateDecision(directions=directions)

    def agent_ratify(inp):
        configs = []
        for draft in inp.configs:
            amended = draft.model_copy(deep=True)
            amended.status = "ratified"
            captured["surface"]["hunts_store"].invoke(
                {"cmd": "write", "hunt_config": amended.model_dump()})
            configs.append(amended)
        return RatifyDecision(configs=configs)

    def _pass(tools):
        return run_orchestration(
            "project-1", run_id, [_candidate()], tools,
            hypothesise_fn=agent_hypothesise, ratify_fn=agent_ratify,
            note_fn=lambda inp: NoteDecision(notes=[]),
        )

    try:
        report1 = _pass(tools1)
        report2 = _pass(tools2)
    finally:
        asyncio.run(_reap_orchestrator(run_id))

    assert report1.store_write_failures == 0
    # (a) the second pass's persisted config carries pass-2's surface_context
    configs2 = store2.read_configs("project-1")
    assert len(configs2) == 1
    assert configs2[0]["status"] == "ratified"
    assert configs2[0]["surface_context"] == {
        "cards": [{"marker": "pass-2"}], "fault_evidence": ["llm: witness"]}
    # the first store was not written by pass 2
    assert len(store1.read_configs("project-1")) == 1
    # (b) the second report observes the second pass's failed write
    assert report2.store_write_failures == 1


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
    tools = _tools(store)

    def boom(inp):
        raise RuntimeError("ratify turn exhausted")

    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=_agent_hypothesise(tools), ratify=boom)
    assert report.pairs_processed == 1
    assert report.configs_hypothesised == 1
    assert report.configs_ratified == 0
    # the agent's hypothesised draft is on disk and the raising ratify turn
    # wrote nothing over it (the harness does not re-persist - #294)
    assert store.read_configs("project-1")[0]["status"] == "hypothesised"
    assert "warning" in caplog.text.lower()


def test_note_turn_failure_skips_the_note(caplog):
    """The note phase degrades fail-open: a raising note turn skips the note's
    side effect (no note lands) but the pass still completes."""
    store = _MemoryStore()
    tools = _tools(store)

    def boom(inp):
        raise RuntimeError("note turn exhausted")

    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=_agent_hypothesise(tools),
                  ratify=_agent_ratify(tools), note=boom)
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
    tools = _tools(store)

    def ratify_return_unratified(inp):
        # return the drafts verbatim (still hypothesised) - the turn did NOT end
        # with ratified (so no agent write upserts them)
        return RatifyDecision(configs=list(inp.configs))

    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=_agent_hypothesise(tools),
                  ratify=ratify_return_unratified)
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
    tools = _tools(store)

    def hypothesise_two_dirs(inp):
        c = inp.candidates[0]
        d1 = EnvisionedDirection(unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
                                 rationale="r", vulnerability_classes=["CSRF"])
        d2 = EnvisionedDirection(unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
                                 rationale="r", vulnerability_classes=["IDOR"])
        # emulate the agent's hunts_store(write) tool call per direction
        for direction in (d1, d2):
            for config in mint_hunt_config(
                    direction, surface_context={},
                    prior_hunt_insights=[]):
                tools.store_reads.write_config("project-1", config)
        return GateDecision(directions=[d1, d2])

    report = _run(store, [_candidate()], tools=tools,
                  hypothesise=hypothesise_two_dirs, ratify=_agent_ratify(tools))
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

    report = _run(store, [c_352, c_639], tools=tools,
                  hypothesise=_agent_hypothesise(tools),
                  ratify=_agent_ratify(tools), note=spying_note)
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

def test_prior_hunt_insights_never_embed_nested_records(tmp_path):
    """I3 + #202 - the downstream prior_hunt_insights are shallow-projected: a
    minted config's prior_hunt_insights carry identity/status/summary only,
    never the full downstream record (the evidence trail is never embedded), so
    the nesting never snowballs across passes."""
    from polymerhus.attack.hunting.hunt_store import (  # noqa: PLC0415
        HuntStore,
        semantic_key,
    )
    from polymerhus.attack.hunting.hunter_memory import (  # noqa: PLC0415
        HunterMemoryStore,
    )

    store = HuntStore(tmp_path)
    hunter = HunterMemoryStore(tmp_path)
    config_key = semantic_key(SERVICE_A, FAULT_X, "csrf")
    # a downstream spec whose record carries a sizeable evidence trail
    hunter.write_spec(
        "project-1", config_key, fault_keyword="f1", strategy_keyword="probe",
        spec={
            "fault_id": "F1", "spec_id": "S1", "status": "specified",
            "strategy": "probe", "fault_key": config_key, "spec_ref": "r",
            "mechanism": "m",
            "supports": ["evidence-1", "evidence-2", "evidence-3"],
            "conflicts": [], "test": "t",
        },
    )
    tools = _tools(store)
    key = revival_key(SERVICE_A, FAULT_X)

    def hypothesise_fn(inp):
        # emulate the agent reading the sibling hunter records through the
        # store tool and authoring them into its config (the prior insights)
        c = inp.candidates[0]
        direction = _carry(c)
        insights = (
            list(tools.store_reads.read_hunter_specs("project-1", key))
            + list(tools.store_reads.read_hunter_notes("project-1", key))
        )
        for config in mint_hunt_config(
                direction, surface_context={},
                prior_hunt_insights=insights):
            tools.store_reads.write_config("project-1", config)
        return GateDecision(directions=[direction])

    report = _run(store, [_candidate()], tools=tools, hypothesise=hypothesise_fn)
    assert report.pairs_processed == 1
    minted = store.read_configs("project-1")
    insights = minted[0]["prior_hunt_insights"]
    assert insights, "the second pass should have read the downstream spec as an insight"
    # never a nested full record (the snowball is cut): the evidence trail and
    # the full spec body are not embedded
    for insight in insights:
        assert "supports" not in insight
        assert "conflicts" not in insight
        assert "mechanism" not in insight
        assert "prior_hunt_insights" not in insight
    # the projection keeps the identity + status for the G3 read
    assert any(i.get("spec_id") == "S1" and i.get("status") == "specified"
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
    tools = _tools(store)

    def hypothesise_fn(inp):
        c = inp.candidates[0]
        direction = EnvisionedDirection(
            unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
            rationale="plausible at this locus", research_direction="probe the flow")
        # the agent's hunts_store(write) of its carried-bare draft
        for config in mint_hunt_config(
                direction, surface_context={},
                prior_hunt_insights=[]):
            tools.store_reads.write_config("project-1", config)
        return GateDecision(directions=[direction])

    report = _run(store, [_candidate()], tools=tools, hypothesise=hypothesise_fn)
    assert report.pairs_processed == 1
    assert report.ledger.units_done == 1
    assert report.ledger.units_skipped == 0
    assert report.configs_hypothesised == 1
    configs = store.read_configs("project-1")
    assert len(configs) == 1
    assert configs[0]["vulnerability_class"] == ""
    assert configs[0]["prompt_template"]["rationale"] == "plausible at this locus"


# --- #202: the lean HuntConfig (three-goal, no redundant slots) --------------

def test_hunt_config_shape_is_the_lean_three_goal_config():
    """#202 - the HuntConfig type reflects the grilling rulings: the merged
    `preconditions` list and the renamed `observed_defences` survive, and the
    redundant slots (`tool_registry`, `adversarial_capabilities`, `assumptions`,
    `technique_primitives`, `target_caveats`) are gone."""
    config = mint_hunt_config(
        direction=_carry(_candidate(deterministic_witness=None)),
        surface_context={},
        prior_hunt_insights=[],
        observed_defences=["WAF on /api/* blocks XSS payloads"],
        preconditions=["an authenticated session is obtainable"],
    )[0]
    # the merged G1 preconditions list (capabilities + assumptions unified)
    assert config.preconditions == ["an authenticated session is obtainable"]
    # the renamed, re-oriented target_caveats slot
    assert config.observed_defences == ["WAF on /api/* blocks XSS payloads"]
    # the redundant slots are REMOVED from the type
    for gone in ("tool_registry", "adversarial_capabilities", "assumptions",
                 "technique_primitives", "target_caveats"):
        assert not hasattr(config, gone)


def test_mint_never_assembles_a_tool_registry():
    """#202 - the mint's tool_registry assembly is retired: the source
    (`_registry_from_kb`) no longer exists and a minted config carries no
    tool_registry slot."""
    import polymerhus.attack.hunting.hunt_orchestrator as ho  # noqa: PLC0415
    assert not hasattr(ho, "_registry_from_kb")
    config = mint_hunt_config(
        direction=_carry(_candidate(deterministic_witness=None)),
        surface_context={},
        prior_hunt_insights=[],
    )[0]
    assert not hasattr(config, "tool_registry")


def test_direction_carrier_no_longer_carries_the_old_ratification_fields():
    """#202 - the EnvisionedDirection carrier drops the dead
    `assumptions` / `envisioned_test_primitives` fields (traced-only, never
    minted; their config-level mirrors are cut/merged)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        EnvisionedDirection,
    )
    direction = EnvisionedDirection(
        unit_id=SERVICE_A, fault_class=FAULT_X, carried=True,
        rationale="r", research_direction="rd", vulnerability_classes=["csrf"],
    )
    assert direction.vulnerability_classes == ["csrf"]
    assert not hasattr(direction, "assumptions")
    assert not hasattr(direction, "envisioned_test_primitives")


def test_prior_hunt_insights_read_the_downstream_hunter_records(tmp_path):
    """#202 - `_read_prior_insights` reads the DOWNSTREAM hunter memory (the
    TestImplementationSpecs + the Q16 durable PodExport verdicts, keyed by the
    config_key) instead of the orchestrator's own prior configs+notes, and
    projects each shallowly (I3 - never a full config/spec embedded)."""
    import json  # noqa: PLC0415

    from polymerhus.attack.hunting.hunt_store import (  # noqa: PLC0415
        HuntStore,
        semantic_key,
    )
    from polymerhus.attack.hunting.hunter_memory import (  # noqa: PLC0415
        HunterMemoryStore,
    )

    store = HuntStore(tmp_path)
    hunter = HunterMemoryStore(tmp_path)
    config_key = semantic_key(SERVICE_A, FAULT_X, "csrf")
    # a downstream produced TestImplementationSpec
    hunter.write_spec(
        "project-1", config_key, fault_keyword="f1", strategy_keyword="probe",
        spec={
            "fault_id": "F1", "spec_id": "S1", "status": "specified",
            "strategy": "probe", "fault_key": config_key,
            "spec_ref": f"data/project-1/hunting/hunter/test-specs/{config_key}/produced/f1_probe.yaml",
            "mechanism": "m", "supports": ["e1"], "conflicts": [],
            "test": "submit a tokenless foreign-origin request and observe the response",
        },
    )
    # the Q16 durable pod-export record (verdict-stub note)
    hunter.write_note(
        "project-1", action="append", fault_key=config_key,
        note_name="pod-1", kind="freeform",
        body=json.dumps({"verdict": "unsuccessful",
                         "terminal_reason": "no-symptom-evidence", "clean": True}),
        provenance={"run_id": "prior-run", "source": "pod-src", "verdict_stub": True},
    )
    tools = _tools(store)
    key = revival_key(SERVICE_A, FAULT_X)

    def hypothesise_fn(inp):
        # emulate the agent reading the sibling hunter records and authoring
        # them into its config (the prior-hunt insights)
        c = inp.candidates[0]
        direction = _carry(c)
        insights = (
            list(tools.store_reads.read_hunter_specs("project-1", key))
            + list(tools.store_reads.read_hunter_notes("project-1", key))
        )
        for config in mint_hunt_config(
                direction, surface_context={},
                prior_hunt_insights=insights):
            tools.store_reads.write_config("project-1", config)
        return GateDecision(directions=[direction])

    report = run_orchestration(
        "project-1", "run-1", [_candidate()], tools,
        hypothesise_fn=hypothesise_fn,
        ratify_fn=_agent_ratify(tools),
        note_fn=_agent_note(tools),
    )
    assert report.configs_ratified == 1
    minted = store.read_configs("project-1")
    insights = minted[0]["prior_hunt_insights"]
    kinds = {i.get("kind") for i in insights}
    assert "prior_spec" in kinds and "prior_verdict" in kinds
    # shallow projection: identity/status/summary only, never the full records
    spec_insight = next(i for i in insights if i.get("kind") == "prior_spec")
    assert spec_insight["spec_id"] == "S1" and spec_insight["status"] == "specified"
    assert "supports" not in spec_insight  # the evidence trail is not embedded
    verdict_insight = next(i for i in insights if i.get("kind") == "prior_verdict")
    assert verdict_insight["verdict"] == "unsuccessful"
    assert verdict_insight["terminal_reason"] == "no-symptom-evidence"