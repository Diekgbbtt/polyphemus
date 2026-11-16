"""Unit tier: T7 (#157) - the rewritten prompt verbatims (D84-10/16).

The Runner's SYSTEM prompt is the P0-P3 stretch plan (feasibility validation ->
concretization -> execute -> confirm exhaustion) with the control-then-intervene
meta-reasoning paradigm and the note-final-step instruction; the Triager's is the
third-party variant miner (classify + terminate or mint a falsifiable variant).
Written under the writing-for-agents + prompt-engineering principles: the stable
SYSTEM layer carries the plan and the tool contract, the per-turn instance data
(the spec, the memory key-list) rides the USER delta.
"""
from __future__ import annotations

import polymerhus.attack.hunting.pod.prompts as prompts_mod
from polymerhus.attack.hunting.pod.prompts import (
    load_pod_decide_verbatim,
    load_pod_runner_skill,
)

KB_TOOL = "query_lightrag"
POD_RUNNER_SYSTEM = load_pod_runner_skill()
DECIDE_VERBATIM = load_pod_decide_verbatim()


# --- the Runner: the P0-P3 plan (D84-16) --------------------------------------

def test_runner_prompt_names_all_four_plan_phases():
    lc = POD_RUNNER_SYSTEM.lower()
    assert "P0" in POD_RUNNER_SYSTEM and "Feasibility" in POD_RUNNER_SYSTEM
    assert "P1" in POD_RUNNER_SYSTEM and "Concretization" in POD_RUNNER_SYSTEM
    assert "P2" in POD_RUNNER_SYSTEM and "Execute" in POD_RUNNER_SYSTEM
    assert "P3" in POD_RUNNER_SYSTEM and "Confirm exhaustion" in POD_RUNNER_SYSTEM
    assert "exhaustion" in lc


def test_runner_prompt_orders_the_phases():
    p0 = POD_RUNNER_SYSTEM.index("P0 Feasibility")
    p1 = POD_RUNNER_SYSTEM.index("P1 Concretization")
    p2 = POD_RUNNER_SYSTEM.index("P2 Execute")
    p3 = POD_RUNNER_SYSTEM.index("P3 Confirm exhaustion")
    assert p0 < p1 < p2 < p3


def test_runner_prompt_carries_the_control_then_intervene_paradigm():
    lc = POD_RUNNER_SYSTEM.lower()
    assert "control" in lc
    assert "single changed variable" in lc           # the minimal payload discipline
    assert "not to noise" in lc                      # attribution, never noise


def test_runner_prompt_guides_confound_anticipation():
    lc = POD_RUNNER_SYSTEM.lower()
    assert "confound" in lc
    assert '"symptom absent" distinct from "could not observe"' in lc or \
           "symptom absent" in lc and "could not observe" in lc


def test_runner_prompt_instructs_the_note_final_step():
    # D84-17/19: the consolidated experiment_summary is the runner's FINAL tool
    # call at P3 exhaustion - the prompt must say so explicitly.
    lc = POD_RUNNER_SYSTEM.lower()
    assert "experiment_summary" in lc
    assert "final" in lc or "final tool call" in lc


def test_runner_prompt_names_every_bound_tool():
    for name in ("exec", "replay", "query_lightrag", "note", "graph_view",
                 "load_skill", "record_skill_lesson", "auth_store"):
        assert name in POD_RUNNER_SYSTEM, name


def test_triager_prompt_variant_table_matches_the_typed_bases():
    from polymerhus.attack.hunting.pod.variant_basis import VARIANT_BASES

    for basis in VARIANT_BASES:
        assert basis in DECIDE_VERBATIM, basis


def test_triager_prompt_names_the_critics_terminal_reasons():
    """`budget-timeout` is a harness terminal, not a critic choice; the DECIDE
    verbatim names the five reasons the triager can actually decide."""
    for reason in ("symptom-confirmed", "technical-infeasibility",
                   "specific-defence-prevention", "space-exhausted",
                   "no-symptom-evidence"):
        assert reason in DECIDE_VERBATIM, reason


def test_triager_prompt_names_the_phase_tools():
    # The DECIDE verbatim's submission contract: the decide gate names itself.
    assert "submit_decision" in DECIDE_VERBATIM
    assert "variant_allowed" in DECIDE_VERBATIM


def test_runner_prompt_names_the_full_three_tool_surface():
    # D84-16/27: exec + query_lightrag + note all bound and all described.
    assert "exec" in POD_RUNNER_SYSTEM
    assert KB_TOOL in POD_RUNNER_SYSTEM and "note" in POD_RUNNER_SYSTEM
    assert "exhausted" in POD_RUNNER_SYSTEM.lower()


def test_runner_prompt_keeps_the_p0_falsification_semantics():
    lc = POD_RUNNER_SYSTEM.lower()
    assert "falsify" in lc
    assert "contradicted" in lc                      # an assumption the evidence contradicts
    assert "default-open" in lc or "default open" in lc  # unconfirmed-but-uncontradicted holds


# --- T8: the reduced spec and the baseline (S5 8.4/8.5) ----------------------

def test_runner_prompt_names_the_baseline_not_the_retired_vector():
    assert "baseline_ref" in POD_RUNNER_SYSTEM
    assert "payload_vector_space" not in POD_RUNNER_SYSTEM
    assert "replay" in POD_RUNNER_SYSTEM.lower()      # the replay tool instruction


def test_runner_prompt_names_the_reduced_spec_surface():
    for token in ("target_identity", "verification_symptoms", "assumptions",
                  "rationale", "provenance", "skill_concretised_procedure", "skills"):
        assert token in POD_RUNNER_SYSTEM, token


def test_runner_prompt_authors_the_first_probe_from_the_spec():
    # S5 8.5: no probe is pre-authored by the hunter; the runner authors at
    # least one from the spec's evidence and the target surface.
    lc = POD_RUNNER_SYSTEM.lower()
    assert "author" in lc
    assert "at least one probe" in lc
    assert "no probe is derivable" in lc or "no probe is derivable" in lc


def test_runner_prompt_treats_an_empty_procedure_section_as_a_recorded_gap():
    # T7's rule (S3 8.6): a section the skill does not carry stays empty and is
    # a recorded gap, never a blocker.
    lc = POD_RUNNER_SYSTEM.lower()
    assert "recorded gap" in lc
    assert "not a blocker" in lc or "never a blocker" in lc


def test_runner_prompt_system_user_split_holds():
    # D84-10: the workflow is the SYSTEM prompt; the memory key-list rides the
    # USER opener, never the system prompt.
    assert "indexable" not in POD_RUNNER_SYSTEM.lower()


# --- the Triager: the third-party variant miner (D84-23) ----------------------

def test_the_contract_prompt_is_a_third_party_critic():
    lc = prompts_mod.load_pod_triager_contract().lower()
    assert "third-party" in lc
    assert "variant" in lc


def test_triager_prompt_requires_a_falsifiable_variant():
    lc = DECIDE_VERBATIM.lower()
    assert "falsifiable" in lc
    assert "changes the spec" in lc                     # the variant changes the spec
    assert "duplicate" in lc                          # never mine a duplicate


def test_triager_prompt_keeps_the_binary_vocabulary():
    for token in ("symptom-confirmed", "space-exhausted", "technical-infeasibility",
                  "specific-defence-prevention", "no-symptom-evidence", "clean"):
        assert token in DECIDE_VERBATIM


def test_triager_prompt_presents_verdict_and_terminal_reason_separately():
    """#209: the decision-vocabulary block presents `verdict` and
    `terminal_reason` as SEPARATE outputs - never slash-joined shorthand. A
    slash-joined string (`successful / symptom-confirmed`) is copied verbatim
    by the model into `verdict`, fails the binary guard, and the degradation
    mis-records a confirmed symptom as unsuccessful."""
    vocab = DECIDE_VERBATIM.split("Terminal vocabulary", 1)[1]
    # the vocabulary names BOTH fields as separate outputs
    assert "verdict" in vocab
    assert "terminal_reason" in vocab
    # no slash-joined "X / Y" shorthand anywhere in the block
    for line in vocab.splitlines():
        assert " / " not in line, line


def test_triager_prompt_keeps_the_exhaustion_rule():
    lc = DECIDE_VERBATIM.lower()
    assert "exhaustion" in lc
    assert "no precise new variant" in lc or "yields nothing new" in lc


def test_the_contract_prompt_names_the_read_surface():
    text = prompts_mod.load_pod_triager_contract()
    assert "note" in text
    assert KB_TOOL in text


# --- T9: the variant-basis minting algorithm (S5 8.6) -------------------------

VARIANT_BASES = (
    "recon-action",
    "bypass-technique",
    "technology-grounding",
    "pro-tips",
    "advanced-technique",
    "preliminary-chaining",
    "payload-vector",
    "technology-misconfiguration",
    "interpretation-pitfall",
    "runner-failure",
    "runner-divergence",
)


def test_triager_prompt_names_all_eleven_variant_bases():
    for basis in VARIANT_BASES:
        assert basis in DECIDE_VERBATIM, basis


def test_triager_prompt_carries_the_first_uncovered_order():
    lc = DECIDE_VERBATIM.lower()
    assert "first uncovered" in lc
    assert "table order" in lc
    positions = [DECIDE_VERBATIM.index(b) for b in VARIANT_BASES[:9]]
    assert positions == sorted(positions)


def test_triager_prompt_reads_the_typed_concretisation_from_the_spec():
    assert "skill_concretised_procedure" in DECIDE_VERBATIM
    assert "SkillConcretisedProcedure" in DECIDE_VERBATIM


def test_triager_prompt_states_the_skipped_section_and_absent_excerpt_rules():
    lc = DECIDE_VERBATIM.lower()
    assert "empty" in lc
    assert "skipped" in lc
    assert "recorded gap" in lc


def test_triager_prompt_has_no_failure_mode_fallback():
    lc = DECIDE_VERBATIM.lower()
    assert "failure-mode" not in lc
    assert "no variant basis is derivable" in lc
    packet = prompts_mod.load_pod_assess_verbatim() + prompts_mod.load_pod_triager_contract()
    assert "verification symptoms" in packet.lower()
    assert "assumptions" in packet.lower()


def test_triager_prompt_states_the_execution_triggers():
    lc = DECIDE_VERBATIM.lower()
    assert "runner-failure" in lc and "failed" in lc
    assert "runner-divergence" in lc and "diverged" in lc


def test_triager_prompt_states_the_duplicate_guard():
    lc = DECIDE_VERBATIM.lower()
    assert "duplicate" in lc
    assert "basis" in lc and "detail" in lc


def test_the_decide_verbatim_names_the_coverage_field():
    # The decision gate schema carries the material the graph's deterministic
    # diff needs; the DECIDE verbatim names the field the model fills.
    for field in ("covered_gap_classes", "declined_attribute"):
        assert field in DECIDE_VERBATIM, field
    # runner_failed/diverged are the ASSESS phase's harness fact and judgment,
    # not decision fields.
    from polymerhus.attack.hunting.pod.prompts import load_pod_assess_verbatim

    assess = load_pod_assess_verbatim()
    assert "runner_failed" in assess
    assert "runner_diverged" in assess


# --- the STAGED triage prompts (the compact stages) ---------------------------

def test_runner_prompt_names_the_variant_basis():
    assert "declined an attribute into" not in POD_RUNNER_SYSTEM
    assert "basis" in POD_RUNNER_SYSTEM.lower()


# --- #207: the KB framing (positive methodology, never a "fault KB") -----------

def test_kb_bullet_is_the_neutral_methodology_signature():
    """#207 defect 2: both KB-tool bullets use the neutral pointer + trigger
    signature - the KB is a methodology KB (retrieve missing ontology concepts),
    never a "fault knowledge base" used to verify or adjudicate a bug."""
    for prompt in (POD_RUNNER_SYSTEM, prompts_mod.load_pod_triager_contract()):
        assert KB_TOOL in prompt
        # the neutral signature: a methodology KB, never a fault oracle
        lc = prompt.lower()
        assert "fault knowledge base" not in lc
        assert "verification-symptom knowledge is missing" in lc
        for stale in ("fault, symptom, assumption", "defence, payload, vector"):
            assert stale not in prompt


# --- #236: the skills surface in the pod prompts ------------------------------

def test_both_prompts_name_the_two_skill_tools():
    """The pod roles' tool sections name the two bound skill tools. The read and
    usage discipline itself arrives through the `meta-usage-skill` protocol
    appended on every load, so the prompt never duplicates it."""
    for prompt in (POD_RUNNER_SYSTEM, prompts_mod.load_pod_triager_contract()):
        assert "- load_skill" in prompt
        assert "- record_skill_lesson -" in prompt
        assert "# Lesson sub-phase" not in prompt


def test_both_prompts_carry_the_shared_cortex():
    """The served prompt is the base markdown plus the shared cortex, through
    the ONE composition helper every hunting agent uses."""
    from polymerhus.attack.hunting.cortex import cognitive_architecture_map

    cortex = cognitive_architecture_map()
    for prompt in (POD_RUNNER_SYSTEM, DECIDE_VERBATIM):
        assert prompt.endswith(cortex)


# --- the D84-30 guard: no differential anywhere --------------------------------

def test_prompts_carry_no_differential_reference():
    import inspect

    source = inspect.getsource(prompts_mod)
    assert "differential" not in source
    for prompt in (POD_RUNNER_SYSTEM, DECIDE_VERBATIM,
                   prompts_mod.load_pod_triager_contract(),
                   prompts_mod.load_pod_assess_verbatim()):
        assert "differential" not in prompt

def test_triager_prompt_does_not_offer_harness_terminal_reasons():
    for reason in ("node-timeout", "context-window-exceeded", "tool-timeout",
                   "graph-limit", "pod-watchdog-timeout"):
        assert reason not in DECIDE_VERBATIM, reason


# --- the lifecycle v2 contract prompt (slice 3) --------------------------------
#
# One immutable system prompt per pod_triager thread: the static contract only.
# The phase verbatims are separate files, and the phase identity never enters
# the system prompt, because the provider caches a token prefix from position 0
# and a stage label there resets it (the 25.56% cache-hit defect).

TRIAGER_CONTRACT = None


def _contract() -> str:
    global TRIAGER_CONTRACT
    if TRIAGER_CONTRACT is None:
        TRIAGER_CONTRACT = prompts_mod.load_pod_triager_contract()
    return TRIAGER_CONTRACT


def test_triager_contract_prompt_carries_the_static_sections():
    lc = _contract().lower()
    for section in ("# role", "what you read", "surgical conciseness",
                    "observation integrity", "evidence sufficiency",
                    "output discipline"):
        assert section in lc, section
    assert "third-party" in lc


def test_triager_contract_prompt_carries_no_per_pod_or_phase_material():
    text = _contract()
    lc = text.lower()
    # Phase identity and stage labels never enter the system prompt.
    for marker in ("stage a", "stage b", "stage c", "stage d",
                   "## assess", "## decide", "p0", "p1", "p2", "p3"):
        assert marker not in lc, marker
    # No per-pod spec content and no skill listing ride position 0.
    for material in ("verification_symptoms", "skill_concretised_procedure",
                     "- name:"):
        assert material not in text, material


def test_triager_contract_prompt_names_the_gate_tools_and_the_integrity_fields():
    text = _contract()
    for name in ("submit_assessment", "submit_decision"):
        assert name in text, name
    # The observation-integrity judgement is defined over the raw fields, not
    # over a summary.
    for field in ("returncode", "stderr", "error_code", "warning"):
        assert field in text, field


def test_the_assess_verbatim_is_a_separate_phase_file():
    text = prompts_mod.load_pod_assess_verbatim()
    for name in ("symptom_confirmed", "runner_diverged", "clean", "note"):
        assert name in text, name
    # The confirmation and divergence rules are the phase's own text.
    lc = text.lower()
    assert "confirm" in lc and "diverg" in lc


def test_the_decide_verbatim_is_a_separate_phase_file():
    text = prompts_mod.load_pod_decide_verbatim()
    from polymerhus.attack.hunting.pod.variant_basis import VARIANT_BASES
    for basis in VARIANT_BASES:
        assert basis in text, basis
    # The terminal vocabulary and the coherence rule ride the DECIDE packet.
    for reason in ("space-exhausted", "no-symptom-evidence",
                   "technical-infeasibility", "specific-defence-prevention"):
        assert reason in text, reason
    assert "submit_decision" in text
