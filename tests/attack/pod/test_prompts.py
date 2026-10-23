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
    load_pod_runner_skill,
    load_pod_triager_skill,
)

KB_TOOL = "query_lightrag"
POD_RUNNER_SYSTEM = load_pod_runner_skill()
POD_TRIAGER_SYSTEM = load_pod_triager_skill()


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


def test_triager_prompt_names_every_bound_tool():
    for name in ("note", "query_lightrag", "graph_view", "load_skill",
                 "record_skill_lesson", "auth_store"):
        assert name in POD_TRIAGER_SYSTEM, name


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
    assert "provenance.baseline_ref" in POD_RUNNER_SYSTEM
    assert "payload_vector_space" not in POD_RUNNER_SYSTEM
    assert "replay" in POD_RUNNER_SYSTEM.lower()      # the replay tool instruction


def test_runner_prompt_names_the_reduced_spec_surface():
    for token in ("target_identity", "verification_symptoms", "assumptions",
                  "rationale", "provenance", "skill_procedure"):
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

def test_triager_prompt_is_a_third_party_miner():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "third-party" in lc or "third party" in lc
    assert "variant" in lc
    assert "never re-derive" in lc or "never re-run" in lc


def test_triager_prompt_requires_a_falsifiable_variant():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "falsifiable" in lc
    assert "fundamental parameter" in lc             # D84-16: change a fundamental parameter
    assert "duplicate" in lc                          # never mine a duplicate


def test_triager_prompt_keeps_the_binary_vocabulary():
    for token in ("symptom-confirmed", "space-exhausted", "technical-infeasibility",
                  "specific-defence-prevention", "no-symptom-evidence", "clean"):
        assert token in POD_TRIAGER_SYSTEM


def test_triager_prompt_presents_verdict_and_terminal_reason_separately():
    """#209: the decision-vocabulary block presents `verdict` and
    `terminal_reason` as SEPARATE outputs - never slash-joined shorthand. A
    slash-joined string (`successful / symptom-confirmed`) is copied verbatim
    by the model into `verdict`, fails the binary guard, and the degradation
    mis-records a confirmed symptom as unsuccessful."""
    vocab = POD_TRIAGER_SYSTEM.split("Decision vocabulary", 1)[1]
    # the vocabulary names BOTH fields as separate outputs
    assert "verdict" in vocab
    assert "terminal_reason" in vocab
    # no slash-joined "X / Y" shorthand anywhere in the block
    for line in vocab.splitlines():
        assert " / " not in line, line


def test_triager_prompt_keeps_the_exhaustion_rule():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "exhaustion" in lc
    assert "no precise new variant" in lc or "yields nothing new" in lc


def test_triager_prompt_names_its_tools():
    assert "note" in POD_TRIAGER_SYSTEM
    assert KB_TOOL in POD_TRIAGER_SYSTEM


# --- T9: the variant-basis minting algorithm (S5 8.6) -------------------------

VARIANT_BASES = (
    "recon-action",
    "bypass-technique",
    "technology-grounding",
    "pro-tips",
    "advanced-technique",
    "preliminary-chaining",
    "interpretation-pitfall",
    "failure-mode",
    "runner-failure",
    "runner-divergence",
)


def test_triager_prompt_names_all_ten_variant_bases():
    for basis in VARIANT_BASES:
        assert basis in POD_TRIAGER_SYSTEM, basis


def test_triager_prompt_carries_the_first_uncovered_order():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "first uncovered" in lc
    assert "table order" in lc
    positions = [POD_TRIAGER_SYSTEM.index(b) for b in VARIANT_BASES[:7]]
    assert positions == sorted(positions)


def test_triager_prompt_reads_the_typed_procedure_from_the_provenance():
    assert "provenance" in POD_TRIAGER_SYSTEM
    assert "skill_procedure" in POD_TRIAGER_SYSTEM
    assert "SkillProcedure" in POD_TRIAGER_SYSTEM


def test_triager_prompt_states_the_skipped_section_and_absent_excerpt_rules():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "empty" in lc
    assert "skipped" in lc
    assert "recorded gap" in lc


def test_triager_prompt_states_the_failure_mode_fallback():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "failure-mode" in lc
    assert "verification_symptoms" in POD_TRIAGER_SYSTEM
    assert "assumptions" in POD_TRIAGER_SYSTEM
    assert "fallback" in lc


def test_triager_prompt_states_the_execution_triggers():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "runner-failure" in lc and "failed" in lc
    assert "runner-divergence" in lc and "diverged" in lc


def test_triager_prompt_states_the_duplicate_guard():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "duplicate" in lc
    assert "basis" in lc and "detail" in lc


def test_triager_prompt_names_the_coverage_assessment_fields():
    # The production tool schema carries the material the graph's deterministic
    # diff needs, so the prompt must name every field.
    for field in ("covered_gap_classes", "failure_mode_plausible",
                  "runner_failed", "runner_diverged", "declined_attribute"):
        assert field in POD_TRIAGER_SYSTEM, field


# --- T9: the runner honours the basis, not the retired attribute decline ------

def test_runner_prompt_names_the_variant_basis():
    assert "declined an attribute into" not in POD_RUNNER_SYSTEM
    assert "basis" in POD_RUNNER_SYSTEM.lower()


# --- #207: the KB framing (positive methodology, never a "fault KB") -----------

def test_kb_bullet_is_the_neutral_methodology_signature():
    """#207 defect 2: both KB-tool bullets use the neutral pointer + trigger
    signature - the KB is a methodology KB (retrieve missing ontology concepts),
    never a "fault knowledge base" used to verify or adjudicate a bug."""
    sig = (
        "the knowledge base from which you retrieve the testing ontology's "
        "concepts when missing from your reasoning; query it when stack-shape, "
        "payload/vector, technique, or verification-symptom knowledge is missing."
    )
    for prompt in (POD_RUNNER_SYSTEM, POD_TRIAGER_SYSTEM):
        assert KB_TOOL in prompt
        # the neutral signature is present verbatim (after the tool name)
        idx = prompt.index(KB_TOOL)
        assert sig in prompt[idx:].split("\n")[0] or sig in prompt[idx:]
        # the stale "fault knowledge base" + binary ontology list is gone
        assert "fault knowledge base" not in prompt
        for stale in ("fault, symptom, assumption", "defence, payload, vector"):
            assert stale not in prompt


# --- #236: the skills surface in the pod prompts ------------------------------

def test_both_prompts_name_the_two_skill_tools():
    """The pod roles' tool sections name the two bound skill tools. The read and
    usage discipline itself arrives through the `meta-usage-skill` protocol
    appended on every load, so the prompt never duplicates it."""
    for prompt in (POD_RUNNER_SYSTEM, POD_TRIAGER_SYSTEM):
        assert "- load_skill -" in prompt
        assert "- record_skill_lesson -" in prompt
        assert "# Lesson sub-phase" not in prompt


def test_both_prompts_carry_the_shared_cortex():
    """The served prompt is the base markdown plus the shared cortex, through
    the ONE composition helper every hunting agent uses."""
    from polymerhus.attack.hunting.cortex import cognitive_architecture_map

    cortex = cognitive_architecture_map()
    for prompt in (POD_RUNNER_SYSTEM, POD_TRIAGER_SYSTEM):
        assert prompt.endswith(cortex)


# --- the D84-30 guard: no differential anywhere --------------------------------

def test_prompts_carry_no_differential_reference():
    import inspect

    source = inspect.getsource(prompts_mod)
    assert "differential" not in source
    assert "differential" not in POD_RUNNER_SYSTEM
    assert "differential" not in POD_TRIAGER_SYSTEM