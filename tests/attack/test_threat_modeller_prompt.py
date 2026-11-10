"""Unit tier: the threat modeller prompt material and the role rename (T2, #375).

The prompt contract of S1 8: the system prompt carries the stable role and
method (the seven states and their content requirements, the trust-modelling
ontology and the two-branch method, the confidence degrees and their
falsification lifecycle, the evidence discipline, the live-authority rule, the
retention-first drop rule, the assumption-to-threat closure check, the risk-scoring
ontology, the probe rules with the target-front directive, the tool guidance,
the saturation stop, and the output contract), with the retired notes
documents' material embedded at the point of use - and the gate hints NOT in
the system prompt (they ride the tool responses).

The rename contract of S1 4.1 after T10 closed the alias window: the new role
id, the new session segment, and the new provider environment variable, with no
fallback and no accepted legacy segment or role.
"""
from __future__ import annotations

import re

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
    WELLFORMEDNESS,
    WELLFORMEDNESS_INSTRUCTION,
    ModellerTurnInput,
)


def test_the_spatial_axis_reads_the_data_contract_not_only_the_http_carrier():
    prompt = _modeller_skill()

    assert "data attributes of the data contracts" in prompt
    assert "application contexts" in prompt
    assert "every attribute of every data type as written" in prompt
    assert "HTTP headers, URL schemes, hosts, ports, paths, fragments" not in prompt
    assert "cookies, request-body fields, multipart fields, resource identifiers" not in prompt


def test_the_prompt_carries_the_required_material():
    """Every clause S1 8 requires, as clauses a reader (or the model) can hold
    the prompt to - the workflow contract's required material, not a wording
    check on any single sentence."""
    prompt = _modeller_skill()
    required = {
        "role": "You are the **threat modeller**",
        "goal": "ranked set of **threats**",
        "state_unit_technical_sharp": "UNIT_TECHNICAL_SHARP",
        "state_trust_modelled": "TRUST_MODELLED",
        "state_assumptions": "TRUST_ASSUMPTIONS_WRITTEN",
        "state_vulnerabilities": "VULNERABILITIES_WRITTEN",
        "state_completed": "COMPLETED",
        "section_technical_sharpening": "technical_sharpening",
        "section_trust_model": "trust_model",
        "section_assumptions": "assumptions",
        "section_vulnerabilities": "vulnerabilities",
        "section_threats": "threats",
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
        "closure_check": "Assumption-to-threat closure",
        "factor_attack_vector": "`attack_vector` (`AV`)",
        "factor_attack_complexity": "`attack_complexity` (`AC`)",
        "factor_attack_requirements": "`attack_requirements` (`AT`)",
        "factor_privileges": "`privileges_required` (`PR`)",
        "factor_user_interaction": "`user_interaction` (`UI`)",
        "factor_confidentiality": "`confidentiality` (`VC`)",
        "factor_integrity": "`integrity` (`VI`)",
        "factor_availability": "`availability` (`VA`)",
        "score_authority": "Never author a score",
        "derived_score": "the persistence computes the score",
        "wellformedness": "Well-formedness: retrospective modelling",
        "class_guard": "Technique families are not vulnerability classes",
        "class_required": "never leave `web_vulnerability_class` empty",
        "worked_example": "## Worked example: the cover fetch",
        "probe_rules": "NEVER destructive",
        "target_front_directive": "502 Bad Gateway",
        "route_absence": "404",
        "tool_store": "`hunts_store`",
        "tool_assess_impact": "`assess_impact`",
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
    for name in ("hunts_store", "assess_impact", "notes", "search_http_history",
                 "get_http_artifact", "js_context", "exec", "skill_list", "skill_load",
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
    """The seven states and their sections are pinned to the typed source, so a
    gate change cannot leave the human projection stale."""
    prompt = _modeller_skill()
    for state in ModelState:
        assert state.value in prompt, state.value
    for state, sections in GATE_SECTIONS.items():
        for section in sections:
            assert section in prompt, f"{state.value}:{section}"


def test_the_prompt_states_the_seven_gates_in_workflow_order():
    """The state table is a reader's map of the workflow: the gates must appear
    in the machine's order, not in an arbitrary mention order."""
    prompt = _modeller_skill()
    table = prompt.split("## The seven states and their gates", 1)[1].split("## ", 1)[0]
    items = {}
    for line in table.splitlines():
        match = re.match(r"\s*(\d+)\.\s+`([A-Z_]+)`", line)
        if match:
            items[int(match.group(1))] = match.group(2)
    assert [items[index] for index in sorted(items)] == [
        state.value for state in ModelState]


def test_the_prompt_states_the_damage_semantic_and_the_precursor_boundary():
    """Ticket 436's prompt contract, on the schema-5 field names: the impact
    description names the victim and the property, the victim/property catalog is
    explicit, a precursor is an abstract capability (never a request or payload),
    one threat references one row, and the two prose blocks precede the factors."""
    prompt = _modeller_skill()
    required = {
        "impact_description": (
            "`impact_description`: the victim and the damaged property"),
        "exploitability_description": "`exploitability_description`: the chain",
        "victim_user": "An end user",
        "victim_application": "The application",
        "victim_infrastructure": "The infrastructure",
        "property_code": "privileged code execution",
        "threat_row": "A `threat` row names a concrete victim and property",
        "precursor_row": "A `precursor` row has no end damage",
        "capability_field": "`capability` (text)",
        "capability_id": "`capability_id` (`P-*`)",
        "capability_path": "capability_path",
        "one_threat_one_damage": "closes to exactly one threat",
        "several_per_vulnerability": "one per exploitation manner",
        "threat_impact_non_none": "at least one impact value above `none`",
        "precursor_impact_none": "`none` in all three",
        "precursor_no_dispatch": "is never dispatched",
    }
    missing = [name for name, clause in required.items() if clause not in prompt]
    assert missing == []


def test_the_prompt_retires_the_likelihood_the_weights_and_the_confidence_rule():
    """Schema 5 retires the whole likelihood vocabulary: no enum, no monotonic
    weights, no impact sub-score arithmetic, and no confidence-as-a-factor rule.
    The retired words must not survive anywhere in the prompt."""
    prompt = _modeller_skill()
    for retired in ("likelihood", "ordinal weight", "impact weight",
                    "0 / 1 / 2 / 3 / 4", "0.22", "0.35", "0.56", "0.6568",
                    "lower the class", "likelihood_rationale"):
        assert retired not in prompt, retired
    # the retired four-value impact set: the impact values are high/low/none
    assert "none / low / medium / high" not in prompt


def test_the_prompt_renders_the_five_exploitability_factors_with_their_domain_semantics():
    """The factors are the domain mapping, not the standard's wording: PR is the
    role and permissions of the chain's primitives, AC is the defence to
    circumnavigate, AT is a further capability that adds a phase, AV is the
    network position, and UI is passive for a routine flow and active for a
    specific victim action."""
    prompt = _modeller_skill()
    required = {
        "pr_role": "the role and the permissions the chain's application "
                   "primitives need",
        "ac_defence": "the defence that must be circumnavigated",
        "ac_sanitizer": "sanitizer",
        "ac_rate_limiter": "rate limiter",
        "ac_csp": "CSP",
        "ac_cors": "CORS",
        "ac_cookie": "cookie attribute",
        "ac_authorization": "authorization control",
        "ac_trust": "trust control",
        "at_phase": "any other attacker capability that adds a phase",
        "at_planted_xss": "planted XSS payload",
        "at_dns": "DNS rebinding for SSRF and TOCTOU",
        "at_jwks": "JWKS access for forged tokens and session fixation",
        "at_not_step_count": "A multi-request chain is not",
        "av_position": "the network position",
        "ui_passive": "passive for a routine",
        "ui_active": "active for a specific non-routine victim action",
        "ui_implicit": "Leave passive interaction implicit",
        "ui_explicit": "state an active interaction",
    }
    missing = [name for name, clause in required.items() if clause not in prompt]
    assert missing == []


def test_the_prompt_states_the_impact_values_with_one_example_each():
    """The impact values are `high`, `low`, and `none` (CVSS 4.0 has no
    `medium`), and every value carries one brief example in the prompt."""
    from polymerhus.attack.hunting.risk_score import FACTOR_DESCRIPTIONS

    prompt = _modeller_skill()
    assert "`high` is a direct, serious loss" in prompt
    assert "`low` is a partial or bounded loss" in prompt
    assert "`none` is no loss" in prompt
    for field in ("confidentiality", "integrity", "availability"):
        assert set(FACTOR_DESCRIPTIONS[field]) == {"none", "low", "high"}


def test_the_prompt_renders_every_factor_value_from_the_single_source():
    """The factor semantics and the examples are defined ONCE, in `risk_score`'s
    FACTOR_DESCRIPTIONS; the prompt renders the same text the tool contract
    renders, so a value cannot drift between them."""
    from polymerhus.attack.hunting.risk_score import FACTOR_DESCRIPTIONS

    prompt = _modeller_skill()
    missing = [
        f"{field}.{value}"
        for field, values in FACTOR_DESCRIPTIONS.items()
        for value, text in values.items()
        if text not in prompt
    ]
    assert missing == []


def test_the_prompt_states_the_no_discount_rule_and_the_derived_score():
    """Two rules the score depends on: the factors describe the attack as it
    would run if the fault is present (an `ASSUMED` premise never lowers one),
    and the model writes the two prose blocks and the eight factors while the
    tool writes the row and the persistence derives the score."""
    prompt = _modeller_skill()
    required = {
        "if_present": "IF THE FAULT IS PRESENT",
        "no_discount": "Never discount a factor for an `ASSUMED` premise",
        "confidence_plans": "verification-planning attribute",
        "confidence_scope": "technical and trust-model claims only",
        "no_score": "Never author a score",
        "model_writes": "you write the two prose blocks and the eight factors",
        "tool_writes": "the tool writes the row",
        "persistence_scores": "the persistence computes the score",
    }
    missing = [name for name, clause in required.items() if clause not in prompt]
    assert missing == []


def test_the_assess_impact_tool_description_renders_the_same_factor_contract():
    """The tool contract and the prompt render ONE source: every factor value and
    its example appears verbatim in both, and the tool states the success
    envelope and the no-score rule."""
    from polymerhus.attack.hunting.risk_score import FACTOR_DESCRIPTIONS
    from polymerhus.attack.hunting.threat_modeller_tools import (
        ASSESS_IMPACT_DESCRIPTION,
    )

    missing = [
        f"{field}.{value}"
        for field, values in FACTOR_DESCRIPTIONS.items()
        for value, text in values.items()
        if text not in ASSESS_IMPACT_DESCRIPTION
    ]
    assert missing == []
    assert "ok: true" in ASSESS_IMPACT_DESCRIPTION
    assert "never send a score" in ASSESS_IMPACT_DESCRIPTION
    assert "ASSUMED" in ASSESS_IMPACT_DESCRIPTION


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
        "threats[].fault_ref",
        "threats[].vulnerability_ref",
    ):
        assert path in prompt, path


def test_the_worked_example_carries_the_factor_compilation():
    """The composite example is the prompt's worked chain: the SSRF/TOCTOU
    factors and the precursor contrast, with no arithmetic for the model to
    author (the persistence derives the score)."""
    prompt = _modeller_skill()
    assert "TOCTOU" in prompt
    assert "AV=network" in prompt
    assert "AT=present" in prompt
    assert "VC=high" in prompt
    assert "soft-404 contract divergence" in prompt
    assert "derived score is `0.0`" in prompt
    assert "ordinal weight" not in prompt
    assert "impact weight" not in prompt


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
    assert len(_modeller_skill().splitlines()) < 500


def test_the_entry_note_belongs_to_the_wellformedness_phase_not_the_assumptions():
    """The phase runs after the vulnerabilities gate, so its entry note does.

    The assumptions phase cannot open a phase that runs two gates later: the
    old placement sent the model from assumptions straight to PRIOR_ART and
    skipped the vulnerabilities gate, which is the C.a skip shape."""
    assumptions = STATE_INSTRUCTIONS[ModelState.TRUST_ASSUMPTIONS_WRITTEN]
    vulnerabilities = STATE_INSTRUCTIONS[ModelState.VULNERABILITIES_WRITTEN]

    assert "trust_assumption" not in assumptions
    assert "trust_assumption" in vulnerabilities
    prompt = _modeller_skill()
    assumptions_section = prompt.split("## Assumptions (TRUST_ASSUMPTIONS_WRITTEN)")[
        1].split("## Vulnerability citation (VULNERABILITIES_WRITTEN)")[0]
    vulnerabilities_section = prompt.split(
        "## Vulnerability citation (VULNERABILITIES_WRITTEN)")[1].split(
            "## Well-formedness")[0]
    assert "trust_assumption" not in assumptions_section
    assert "trust_assumption" in vulnerabilities_section


def test_the_wellformedness_turn_renders_its_phase_not_the_vulnerabilities_state():
    """The well-formedness phase is a workflow phase, not the vulnerabilities
    gate. The turn prompt must say WELLFORMEDNESS, never the stale gate."""
    turn = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.VULNERABILITIES_WRITTEN,
        phase=WELLFORMEDNESS,
        sections=(),
        instruction=WELLFORMEDNESS_INSTRUCTION,
    )

    rendered = _compose_modeller_prompt(turn)

    assert "Current workflow state: WELLFORMEDNESS" in rendered
    assert "Current workflow state: VULNERABILITIES_WRITTEN" not in rendered
    assert "Gate sections to write: (none - workflow phase)" in rendered
    assert "not a gate" in rendered
    assert "Write the gate with" not in rendered


def test_the_turn_prompt_renders_the_state_the_unit_and_the_fresh_model():
    """The per-turn HumanMessage carries the current unit, the current state, the
    gate sections, the instruction, and the model read at the turn's start."""
    turn = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.TRUST_MODELLED,
        sections=GATE_SECTIONS[ModelState.TRUST_MODELLED],
        instruction=STATE_INSTRUCTIONS[ModelState.TRUST_MODELLED],
        model={"state": "UNIT_TECHNICAL_SHARP",
               "technical_sharpening": {
                   "interface_agreements": [{"id": "ia-1", "statement": "x"}],
               }},
    )

    rendered = _compose_modeller_prompt(turn)

    assert "Service:catalogue-and-discovery" in rendered
    assert "TRUST_MODELLED" in rendered
    assert "trust_model" in rendered
    assert "state: UNIT_TECHNICAL_SHARP" in rendered
    assert "technical_sharpening" in rendered
    assert "hunts_store" in rendered and "notes" in rendered


def test_the_turn_prompt_does_not_report_a_never_written_section():
    """A defaulted section is not "written": the PRIOR_ART turn must not be
    told that prior art is already authored."""
    turn = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.PRIOR_ART,
        sections=GATE_SECTIONS[ModelState.PRIOR_ART],
        instruction=STATE_INSTRUCTIONS[ModelState.PRIOR_ART],
        model={
            "state": "UNIT_TECHNICAL_SHARP",
            "technical_sharpening": {
                "interface_agreements": [{"id": "ia-1", "statement": "x"}],
            },
            "prior_art": {"queries": [], "reused": [], "notes": ""},
        },
    )

    rendered = _compose_modeller_prompt(turn)
    written = next(
        line for line in rendered.splitlines() if "sections written:" in line)

    assert "technical_sharpening" in written
    assert "prior_art" not in written


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


def test_the_prompt_states_the_prior_art_phase_and_the_query_contract():
    """Ticket 437: the phase runs after the technical sharpening and before the
    trust model; it carries the query contract (the kind, the filters, the
    AND/regex semantics, the `*` traversal, the limit, the bound-unit
    exclusion) and the three required query kinds plus the prior-art note."""
    prompt = _modeller_skill()
    required = {
        "phase_heading": "## Prior art (PRIOR_ART)",
        "phase_order": "AFTER the vulnerability-local impact note and BEFORE the impact rows",
        "query_command": "cmd='query'",
        "kind_field": "`kind`",
        "kinds": (
            "`threat`, `vulnerability`, `precursor`, `assumption`, or `impact`"
        ),
        "filters_field": "`filters`",
        "filter_path": "`path`",
        "filter_regex": "`regex`",
        "filter_flags": "`flags`",
        "and_semantics": "non-empty AND list",
        "search_semantics": "`re.search(regex, value, flags)`",
        "star_traversal": "`*` iterates a list",
        "missing_path": "a missing path is no match",
        "limit": "`limit` is 1..50",
        "bound_unit_exclusion": "unless a filter path is `unit_id`",
        "produced_and_consumed": "produced and the consumed",
        "matched_pairs": "`matched` path/value pairs",
        "three_kinds": "at least ONE query for threats, one for vulnerabilities, "
                       "and one for precursors",
        "note": "`prior_art` note",
    }
    missing = [name for name, clause in required.items() if clause not in prompt]
    assert missing == []


def test_the_prompt_keeps_prior_art_after_the_vulnerability_phase():
    prompt = _modeller_skill()
    assert prompt.index("## Vulnerability citation (VULNERABILITIES_WRITTEN)") < prompt.index(
        "## Prior art (PRIOR_ART)")
    assert prompt.index("## Prior art (PRIOR_ART)") < prompt.index(
        "## Impact assessment and the capability chain (IMPACT_ASSESSED)")


# --- #438: the project scope ------------------------------------------------

SCOPE = ("The target is assumed to have a request-rate limiter and a WAF in "
         "blocking mode. The internal build network is out of scope; a threat "
         "that needs access to the build network is not modelled.")


def _assumptions_section(prompt: str) -> str:
    return prompt.split(
        "## Assumptions (TRUST_ASSUMPTIONS_WRITTEN)", 1)[1].split("\n## ", 1)[0]


def test_the_turn_prompt_appends_the_project_scope_verbatim():
    """#438: the run's scope string rides the turn under `## Project scope
    (verbatim)`, exactly as the operator wrote it - the prompt never paraphrases
    or reformats it."""
    turn = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.TRUST_ASSUMPTIONS_WRITTEN,
        sections=GATE_SECTIONS[ModelState.TRUST_ASSUMPTIONS_WRITTEN],
        instruction=STATE_INSTRUCTIONS[ModelState.TRUST_ASSUMPTIONS_WRITTEN],
        threat_model_scope=SCOPE,
    )

    rendered = _compose_modeller_prompt(turn)

    heading = "## Project scope (verbatim)"
    assert heading in rendered
    appended = rendered.split(heading, 1)[1]
    # verbatim: the operator's string is one contiguous block, unedited
    assert SCOPE in appended
    assert appended.count(SCOPE) == 1


def test_an_empty_project_scope_appends_no_scope_section():
    """#438: an unset project appends nothing - no empty heading, no empty
    claim for the model to fill in."""
    turn = ModellerTurnInput(
        unit_id="Service:catalogue-and-discovery",
        state=ModelState.TRUST_ASSUMPTIONS_WRITTEN,
        sections=GATE_SECTIONS[ModelState.TRUST_ASSUMPTIONS_WRITTEN],
        instruction=STATE_INSTRUCTIONS[ModelState.TRUST_ASSUMPTIONS_WRITTEN],
        threat_model_scope="",
    )

    rendered = _compose_modeller_prompt(turn)

    assert "## Project scope (verbatim)" not in rendered
    assert SCOPE not in rendered


def test_the_prompt_binds_the_assumptions_phase_to_the_project_scope():
    """#438: the scope is a project assumption, not a prompt rule bolted onto
    the impact rows. The assumptions phase states the binding: an excluded trust
    boundary is never modelled, so the excluded assumption and fault are never
    made."""
    assumptions = _assumptions_section(_modeller_skill())

    assert "## Project scope (verbatim)" in assumptions
    assert "do not model a trust boundary the project scope excludes" in assumptions
    assert "do not make the excluded assumption or fault" in assumptions
    assert "at the assumptions layer, never as an impact-row exclusion" in assumptions


def test_the_hunting_config_scope_is_not_a_prompt_constant():
    """#438: the scope is the PROJECT's string, read per run - the static
    prompt names the section and the binding but never hardcodes a posture."""
    assert SCOPE not in _modeller_skill()


def test_the_hunts_store_description_states_the_query_contract():
    from polymerhus.attack.hunting.threat_modeller_tools import (
        _HUNTS_STORE_DESCRIPTION,
    )

    assert "cmd='query'" in _HUNTS_STORE_DESCRIPTION
    assert "`kind`" in _HUNTS_STORE_DESCRIPTION
    assert "`filters`" in _HUNTS_STORE_DESCRIPTION
    assert "`limit`" in _HUNTS_STORE_DESCRIPTION


def test_the_session_segment_and_the_role_are_the_new_names():
    """T10 removed the planner-era alias: `threat-modeller` is the only
    segment that classifies as the modeller role."""
    assert threat_modeller_session_id("r-1") == "hunting:r-1:threat-modeller"
    assert derive_thread_role("hunting:r-1:threat-modeller") == THREAT_MODELLER_ROLE
    assert derive_thread_role("hunting:r-1:orchestrator") == "infra"
    assert MODELLER_ROLE == "hunting_threat_modeller"
    assert THREAT_MODELLER_ROLE == "threat_modeller"


def test_the_role_binds_the_project_skill_and_the_auth_store_by_site_arming():
    """The auth store and the project skill arrive through the role binding;
    the browser mechanics skill is the role's optional live-probe surface."""
    from polymerhus.app.auth.seams import auth_capable_binding
    from polymerhus.app.llm.skills import ROLE_SKILLS

    assert ROLE_SKILLS[MODELLER_ROLE] == ("steel-browser",)
    binding = auth_capable_binding(MODELLER_ROLE, project_id="proj-1",
                                   arm_exempt_surface=True)
    names = {tool.name for tool in binding.tools}

    assert {"load_skill", "auth_store"} <= names
    assert "write_skill" not in names
    assert binding.middleware
    assert binding.context["project_id"] == "proj-1"
    # the read-only arming still names a loadable skill, so the prompt's "load
    # the skill named in your context" is actionable
    assert binding.context["skills"] == ["steel-browser", "authn"]


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
    """The final gate must copy the threat classes from the vulnerability and
    treat an invalid COMPLETED write as feedback, not a terminal outcome. The
    white-jotter model renamed the threat classes and left V-4 unclosed; the pass
    archived the unit before the model could fix it."""
    prompt = _modeller_skill()
    assert "Class identity is copied, never re-derived" in prompt
    assert "validation.valid" in prompt
    assert "write COMPLETED again" in prompt

    instruction = STATE_INSTRUCTIONS[ModelState.COMPLETED]
    assert "verbatim" in instruction
    assert "write COMPLETED again" in instruction


def test_the_assessment_and_completion_turns_name_the_tool_and_the_derived_risk():
    """Schema 5 moves the write to the tool: the IMPACT_ASSESSED turn calls
    `assess_impact` once per row, and the COMPLETED turn derives the risk and
    verifies the coverage and the chains instead of scoring anything."""
    instruction = STATE_INSTRUCTIONS[ModelState.IMPACT_ASSESSED]
    assert "`assess_impact`" in instruction
    assert "once per assessment row" in instruction
    assert "derived" in instruction

    completion = STATE_INSTRUCTIONS[ModelState.COMPLETED]
    assert "do not author a score" in completion
    assert "assessment row" in completion
    assert "enabling chain" in completion
    assert "likelihood" not in completion
