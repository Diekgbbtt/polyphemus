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
    KB_TOOL,
    POD_RUNNER_SYSTEM,
    POD_TRIAGER_SYSTEM,
)


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


def test_triager_prompt_keeps_the_exhaustion_rule():
    lc = POD_TRIAGER_SYSTEM.lower()
    assert "exhaustion" in lc
    assert "no precise new variant" in lc or "yields nothing new" in lc


def test_triager_prompt_names_its_tools():
    assert "note" in POD_TRIAGER_SYSTEM
    assert KB_TOOL in POD_TRIAGER_SYSTEM


# --- the D84-30 guard: no differential anywhere --------------------------------

def test_prompts_carry_no_differential_reference():
    import inspect

    source = inspect.getsource(prompts_mod)
    assert "differential" not in source
    assert "differential" not in POD_RUNNER_SYSTEM
    assert "differential" not in POD_TRIAGER_SYSTEM