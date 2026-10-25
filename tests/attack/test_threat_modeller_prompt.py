"""Unit tier: the threat modeller prompt material and the role rename (T2, #375).

The prompt contract of S1 8: the system prompt carries the stable role and
method (the five states and their content requirements, the trust-modelling
ontology and the two-branch method, the confidence degrees and their
falsification lifecycle, the evidence discipline, the live-authority rule, the
retention-first drop rule, the assumption-to-loop closure check, the risk-scoring
ontology, the probe rules with the target-front directive, the tool guidance,
the saturation stop, and the output contract), with the retired notes
documents' material embedded at the point of use - and the gate hints NOT in
the system prompt (they ride the tool responses).

The rename contract of S1 4.1 after T10 closed the alias window: the new role
id, the new session segment, and the new provider environment variable, with no
fallback and no accepted legacy segment or role.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.llm import _compose_modeller_prompt, _modeller_skill
from polymerhus.attack.hunting.mover import threat_modeller_session_id
from polymerhus.attack.hunting.surfer import (
    THREAT_MODELLER_ROLE,
    derive_thread_role,
)
from polymerhus.attack.hunting.threat_model import GATE_SECTIONS, ModelState
from polymerhus.attack.hunting.threat_modeller import (
    GATE_HINTS,
    MODELLER_MODEL_KEY,
    MODELLER_ROLE,
    STATE_INSTRUCTIONS,
    ModellerTurnInput,
)


def test_the_prompt_carries_the_required_material():
    """Every clause S1 8 requires, as clauses a reader (or the model) can hold
    the prompt to - the workflow contract's required material, not a wording
    check on any single sentence."""
    prompt = _modeller_skill()
    required = {
        "role": "You are the **threat modeller**",
        "goal": "ranked set of **loops**",
        "state_unit_technical_sharp": "UNIT_TECHNICAL_SHARP",
        "state_trust_modelled": "TRUST_MODELLED",
        "state_assumptions": "TRUST_ASSUMPTIONS_WRITTEN",
        "state_vulnerabilities": "VULNERABILITIES_WRITTEN",
        "state_completed": "COMPLETED",
        "section_technical_sharpening": "technical_sharpening",
        "section_trust_model": "trust_model",
        "section_assumptions": "assumptions",
        "section_vulnerabilities": "vulnerabilities",
        "section_loops": "loops",
        "axis_identity": "### Identity",
        "axis_spatial": "### Spatial",
        "axis_temporal": "### Temporal",
        "axis_controls": "### Controls semantics",
        "dynamic_state_branch": "dynamic-state trust",
        "confidence_observed": "`OBSERVED`",
        "confidence_inferred": "`INFERRED`",
        "confidence_assumed": "`ASSUMED`",
        "falsification_lifecycle": "pure falsification nature",
        "evidence_discipline": "list of evidence entries",
        "evidence_no_probe_plans": "No probe plans",
        "evidence_no_citations_block": "No citations block",
        "evidence_entries_only": "the only place evidence lives",
        "live_authority": "live target responses are the evidence",
        "retention_first": "Retention first",
        "drop_rule": "A drop requires ONE of two findings",
        "unobserved_assumptions": "Unobserved assumptions survive",
        "closure_check": "Assumption-to-loop closure",
        "risk_factor_attack_vector": "**attack vector**",
        "risk_factor_attack_requirements": "**attack requirements**",
        "risk_factor_privileges": "**privileges required**",
        "risk_factor_complexity": "**complexity**",
        "likelihood_enum": "`none / low / medium / high / critical`",
        "monotonic_weights": "`0 / 1 / 2 / 3 / 4`",
        "impact_metrics": "**Impact metrics.**",
        "combined_risk": "**Combined risk.**",
        "wellformedness": "Well-formedness: retrospective modelling",
        "class_guard": "Technique families are not vulnerability classes",
        "class_required": "never leave `web_vulnerability_class` empty",
        "worked_example": "## Worked example: the cover fetch",
        "probe_rules": "NEVER destructive",
        "target_front_directive": "502 Bad Gateway",
        "route_absence": "404",
        "tool_store": "`hunts_store`",
        "tool_notes": "`notes`",
        "tool_http_search": "`search_http_history`",
        "tool_http_get": "`get_http_artifact`",
        "tool_exec": "`exec`",
        "tool_skill_list": "`skill_list`",
        "tool_skill_load": "`skill_load`",
        "tool_auth": "`auth_store`",
        "tool_project_skill": "`load_skill`",
        "no_replay": "You never replay",
        "saturation_stop": "saturation",
        "output_contract": "`{state, sections}`",
    }
    missing = [name for name, clause in required.items() if clause not in prompt]
    assert missing == []


def test_the_prompt_names_every_bound_tool_including_the_lesson_tool():
    """The tool section is the human projection of the bound surface; a bound
    tool the prompt never names is a hidden capability."""
    prompt = _modeller_skill()
    for name in ("hunts_store", "notes", "search_http_history",
                 "get_http_artifact", "exec", "skill_list", "skill_load",
                 "load_skill", "record_skill_lesson", "auth_store"):
        assert name in prompt, name


def test_the_prompt_delegates_the_target_front_rule_to_the_shared_constant():
    """The 5xx paragraph was an exact copy shared with the hunter. The prompt
    now points at the one shared rule instead of paying a second full copy."""
    from polymerhus.attack.hunting.hunting_status import (  # noqa: PLC0415
        TARGET_UNAVAILABLE_DIRECTIVE,
    )

    prompt = _modeller_skill()
    assert TARGET_UNAVAILABLE_DIRECTIVE not in prompt
    assert "shared target-front 5xx rule" in prompt
    assert "502 Bad Gateway" in prompt
    assert "404" in prompt


def test_the_prompt_state_and_section_table_matches_the_typed_contract():
    """The five states and their sections are pinned to the typed source, so a
    gate change cannot leave the human projection stale."""
    prompt = _modeller_skill()
    for state in ModelState:
        assert state.value in prompt, state.value
    for state, sections in GATE_SECTIONS.items():
        for section in sections:
            assert section in prompt, f"{state.value}:{section}"


def test_the_prompt_reference_table_matches_the_typed_paths():
    """The reference-field table is pinned to the canonical field paths."""
    prompt = _modeller_skill()
    for path in (
        "vulnerabilities[].fault_ref",
        "assumptions[].boundary_ref",
        "trust_model.trust_agreements[].interface_agreement_refs[]",
        "trust_model.dynamic_state_trust.transitions[].source",
        "trust_model.dynamic_state_trust.transitions[].target",
        "trust_model.dynamic_state_trust.violations[].maps_to_fault",
        "trust_model.dynamic_state_trust.violations[].transition_ref",
        "loops[].fault_ref",
        "loops[].vulnerability_ref",
    ):
        assert path in prompt, path


def test_the_worked_example_carries_the_impact_arithmetic():
    """The composite example is the prompt's worked chain: the SSRF/TOCTOU
    metrics, the sub-score, the ordinal weight, and the low-yield contrast."""
    prompt = _modeller_skill()
    assert "TOCTOU" in prompt
    assert "0.6568" in prompt
    assert "ordinal weight is `3`" in prompt
    assert "soft-404 contract divergence" in prompt
    assert "impact weight is `0`" in prompt


def test_the_prompt_embeds_the_retired_notes_material():
    """The per-state material comes from the retired notes documents: the
    request-handling stack and the trust-boundary steps for grounding, and the
    dynamic-state trust workflow (until stage 4) for the trust mapping."""
    prompt = _modeller_skill()
    for layer in ("Client and network ingress", "Edge routing and gateway",
                  "Parsing and validation", "Authentication and identity",
                  "Application and business logic", "Internal services and dependencies",
                  "Data access and persistence", "Response construction"):
        assert layer in prompt
    for step in ("Construct the extended finite state machine",
                 "Characterise every transition", "Evaluate each transition"):
        assert step in prompt
    # the trust-boundary reasoning steps
    assert "trace backward through the request-handling workflow" in prompt
    assert "what evidence supports it" in prompt


def test_the_prompt_carries_no_gate_hint():
    """The gate hints are module constants injected in the tool responses - the
    system prompt must not carry them (S1 8, 9.3)."""
    prompt = _modeller_skill()
    for hint in GATE_HINTS.values():
        assert hint not in prompt


def test_the_prompt_stays_within_a_reasonable_size():
    """A gate cadence belongs in the tool responses, not a wall of text."""
    assert len(_modeller_skill().splitlines()) < 400


def test_the_turn_prompt_renders_the_state_the_unit_and_the_fresh_model():
    """The per-turn HumanMessage carries the current unit, the current state, the
    gate sections, the instruction, and the model read at the turn's start."""
    turn = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.TRUST_MODELLED,
        sections=GATE_SECTIONS[ModelState.TRUST_MODELLED],
        instruction=STATE_INSTRUCTIONS[ModelState.TRUST_MODELLED],
        model={"state": "UNIT_TECHNICAL_SHARP",
               "technical_sharpening": {"interface_agreements": []}},
    )

    rendered = _compose_modeller_prompt(turn)

    assert "Service:catalogue-and-discovery" in rendered
    assert "TRUST_MODELLED" in rendered
    assert "trust_model" in rendered
    assert "state: UNIT_TECHNICAL_SHARP" in rendered
    assert "technical_sharpening" in rendered
    assert "hunts_store" in rendered and "notes" in rendered


def test_the_turn_prompt_degrades_a_missing_model_to_a_denotation():
    turn = ModellerTurnInput(
        unit_id="Service:x", state=ModelState.UNIT_TECHNICAL_SHARP,
        sections=GATE_SECTIONS[ModelState.UNIT_TECHNICAL_SHARP],
        instruction=STATE_INSTRUCTIONS[ModelState.UNIT_TECHNICAL_SHARP],
        model=None,
    )

    assert "(not written yet)" in _compose_modeller_prompt(turn)


def test_the_prompt_renders_the_grounding_inputs_and_their_gaps():
    """S1 4.6 / 5.6: the composed turn carries the unit projection and the L1
    application-surface overview when present, and names each absent source so
    the model grounds on what it has and records the gap."""
    turn = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.UNIT_TECHNICAL_SHARP,
        sections=GATE_SECTIONS[ModelState.UNIT_TECHNICAL_SHARP],
        instruction=STATE_INSTRUCTIONS[ModelState.UNIT_TECHNICAL_SHARP],
        projection={"unit_id": "Service:catalogue-and-discovery",
                    "data_items": {"reads": ["item"]}},
        surface_overview={"core_features": ["catalogue"],
                          "user_journeys": ["browse -> add -> publish"]},
    )

    rendered = _compose_modeller_prompt(turn)

    assert "Unit projection" in rendered
    assert "data_items" in rendered
    assert "Application-surface overview" in rendered
    assert "browse -> add -> publish" in rendered

    absent = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.UNIT_TECHNICAL_SHARP,
        sections=GATE_SECTIONS[ModelState.UNIT_TECHNICAL_SHARP],
        instruction=STATE_INSTRUCTIONS[ModelState.UNIT_TECHNICAL_SHARP],
        context_gaps=("unit projection unavailable",
                      "L1 application-surface overview unavailable"),
    )
    degraded = _compose_modeller_prompt(absent)
    assert "unit projection unavailable" in degraded
    assert "L1 application-surface overview unavailable" in degraded


def test_the_prompt_names_the_read_command():
    """The store's read needs `cmd='read'` (the schema's discriminator); a
    prompt that says "no arguments" sends an invalid call."""
    assert "cmd='read'" in _modeller_skill()


def test_the_session_segment_and_the_role_are_the_new_names():
    """T10 removed the planner-era alias: `threat-modeller` is the only
    segment that classifies as the modeller role."""
    assert threat_modeller_session_id("r-1") == "hunting:r-1:threat-modeller"
    assert derive_thread_role("hunting:r-1:threat-modeller") == THREAT_MODELLER_ROLE
    assert derive_thread_role("hunting:r-1:orchestrator") == "infra"
    assert MODELLER_ROLE == "hunting_threat_modeller"
    assert THREAT_MODELLER_ROLE == "threat_modeller"


def test_the_role_binds_the_project_skill_and_the_auth_store_by_site_arming():
    """S1 5.5: the auth store and the project skill arrive through the role
    binding (the recon-orchestrator coupling) - the roster declares the role
    exempt, the site arms the read-only surface."""
    from polymerhus.app.auth.seams import auth_capable_binding
    from polymerhus.app.llm.skills import ROLE_SKILLS

    assert ROLE_SKILLS[MODELLER_ROLE] == ()
    binding = auth_capable_binding(MODELLER_ROLE, project_id="proj-1",
                                   arm_exempt_surface=True)
    names = {tool.name for tool in binding.tools}

    assert {"load_skill", "auth_store"} <= names
    assert "write_skill" not in names
    assert binding.middleware
    assert binding.context["project_id"] == "proj-1"
    # the read-only arming still names a loadable skill, so the prompt's "load
    # the skill named in your context" is actionable
    assert binding.context["skills"] == ["authn"]


def test_the_modeller_actor_speaks_on_the_renamed_role_and_thread():
    """The actor's session role and its checkpoint thread are the renamed ones;
    its bound tool surface is exactly the modeller's."""
    from polymerhus.attack.hunting.actors import ThreatModellerActor

    actor = ThreatModellerActor("r-9")
    assert actor.role_id == "hunting_threat_modeller"
    assert actor.thread_id == "r-9:hunting_threat_modeller"


def test_the_provider_environment_variable_does_not_read_the_legacy_key(monkeypatch):
    """T10 closed the one-window alias: `LLM_HUNTING_THREAT_MODELLER` is the
    only accepted key. The planner-era key no longer resolves the role."""
    from polymerhus.app.llm.providers import LLMConfigError, resolve_role

    monkeypatch.delenv(MODELLER_MODEL_KEY, raising=False)
    monkeypatch.setenv("LLM_HUNTING_ORCHESTRATOR", "opencode:legacy-model")
    with pytest.raises(LLMConfigError):
        resolve_role(MODELLER_ROLE)

    monkeypatch.setenv(MODELLER_MODEL_KEY, "opencode:new-model")
    assert resolve_role(MODELLER_ROLE) == ("opencode", "new-model")


# --- F-027: the reference-ID contract -----------------------------------------

def test_the_modeller_prompt_teaches_the_reference_id_contract():
    """The completion check resolves every reference field to an id the model
    itself authored. The white-jotter run put control/data-flow ids in
    `interface_agreement_refs` and prose in `maps_to_fault`, so every completed
    unit was archived; the prompt must teach the namespace table."""
    prompt = _modeller_skill()

    assert "Reference fields" in prompt
    assert "interface_agreement_refs" in prompt
    assert "maps_to_fault" in prompt
    assert "never control flows (`CF-*`) or data flows (`DF-*`)" in prompt
    assert "never prose" in prompt
    for token in ("`F-*`", "`V-*`", "`IA-*`", "`TA-*`", "`TR-*`"):
        assert token in prompt


def test_the_hunts_store_description_names_the_reference_fields():
    from polymerhus.attack.hunting.threat_modeller_tools import (
        _HUNTS_STORE_DESCRIPTION,
    )

    assert "interface_agreement_refs" in _HUNTS_STORE_DESCRIPTION
    assert "maps_to_fault" in _HUNTS_STORE_DESCRIPTION
    assert "ID" in _HUNTS_STORE_DESCRIPTION


def test_the_completed_gate_teaches_class_copying_and_the_validation_rewrite():
    """The final gate must copy the loop classes from the vulnerability and
    treat an invalid COMPLETED write as feedback, not a terminal outcome. The
    white-jotter model renamed the loop classes and left V-4 unclosed; the pass
    archived the unit before the model could fix it."""
    prompt = _modeller_skill()
    assert "Class identity is copied, never re-derived" in prompt
    assert "validation.valid" in prompt
    assert "write COMPLETED again" in prompt

    instruction = STATE_INSTRUCTIONS[ModelState.COMPLETED]
    assert "verbatim" in instruction
    assert "write COMPLETED again" in instruction
