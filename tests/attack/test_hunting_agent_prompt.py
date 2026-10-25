"""Unit tier: the production hunter prompt contract (T7, #380).

The prompt is the S3 8.5 artifact: one system prompt carrying the role framing,
the loop ontology, the discipline, the decision tree, the eight passes, the four
collection axes, the reduced D4 spec body, and the falsification-only verify
scope. These predicates hold the prompt to the contract's CLAUSES, not to a
wording preference: each required clause is a statement a reader (or the model)
can be held to, and every removed node or retired vocabulary is asserted absent.

The worked examples are part of the SAME system prompt (`examples.md` is
concatenated by `_load_hunting_agent_skill`), so the shape assertions read the
same prompt the model sees.
"""
from __future__ import annotations

import re
from pathlib import Path

from polymerhus.attack.hunting.hunting_agent import _load_hunting_agent_skill

PASSES = (
    "GROUNDING", "SLICE", "COLLECT", "DISCRIMINATE",
    "GENERATE", "WELL-FORMEDNESS", "VERIFY-CLAIMS", "COMPLETE",
)


def _prompt() -> str:
    return _load_hunting_agent_skill()


def _examples() -> str:
    import polymerhus.attack.hunting.hunting_agent as H  # noqa: PLC0415

    return (Path(H.__file__).resolve().parent / "prompts" / "examples.md"
            ).read_text(encoding="utf-8")


# --- the eight passes and the tree --------------------------------------------


def test_the_prompt_names_the_eight_passes_in_chain_order():
    """S3 8.4/8.5: the eight passes, in the order the tracked state walks."""
    prompt = _prompt()
    positions = [prompt.index(name) for name in PASSES]
    assert positions == sorted(positions)
    # each pass is a real section, not only a word in the tree
    for name in PASSES:
        assert f"**{name}**" in prompt, name


def test_the_tree_is_the_contracted_navigation():
    """S3 8.5: GROUND -> [D1] -> SLICE -> COLLECT -> DISCRIMINATE -> GENERATE
    -> WELL-FORMEDNESS --[D2]--> COLLECT or GENERATE -> VERIFY-CLAIMS ->
    COMPLETE; the second DISCRIMINATE is gone."""
    prompt = _prompt()
    start = prompt.index("## The tree")
    fence = prompt.index("```", start)
    tree = prompt[fence:prompt.index("```", fence + 3)]

    assert "GROUND\n" in tree
    assert "[D1]" in tree
    assert "SLICE -> COLLECT -> DISCRIMINATE -> GENERATE" in tree
    assert "WELL-FORMEDNESS --[D2: new instances or specs]--> COLLECT or GENERATE" in tree
    assert "VERIFY-CLAIMS -> COMPLETE" in tree
    assert tree.count("DISCRIMINATE") == 1


def test_the_well_formedness_reentry_never_moves_the_tracked_state():
    """S3 8.5/S4 14: the [D2] re-entry is reasoning; the tracked state stays
    WELL-FORMEDNESS until the exit note."""
    prompt = _prompt()
    assert "the tracked state stays WELL-FORMEDNESS" in prompt
    assert "A [D2] re-entry is reasoning only" in prompt
    assert "on the fly" in prompt  # the likelihood ranking, not a second pass


# --- the four collection axes and the encoding exclusion ----------------------


def test_the_prompt_carries_the_four_collection_axes():
    """S3 8.5 COLLECT: advanced techniques, chaining, technology-specific
    framework or protocol misconfigurations, payload-vector classes."""
    prompt = _prompt()
    collect = prompt[prompt.index("**COLLECT**"):prompt.index("**DISCRIMINATE**")]
    for axis in ("Advanced techniques", "Chaining with other low-hanging vulnerabilities",
                 "Framework or protocol misconfigurations", "Payload-vector classes"):
        assert axis in collect, axis
    assert "effective request item" in collect
    assert "communication protocol" in collect
    assert "redirects or indirect deliveries" in collect


def test_the_encoding_scheme_is_not_a_discrimination_variable():
    """S3 8.5: the encoding scheme is excluded from the discrimination axis."""
    prompt = _prompt()
    assert "The encoding scheme is not a discrimination variable" in prompt
    assert "never split a spec by encoding" in prompt


# --- the spec contract --------------------------------------------------------

def test_the_spec_body_names_every_writable_field_and_nested_contract():
    """The human projection is complete: every writable `SpecWrite` field, every
    `SpecProvenance` field, every `TargetIdentity` field, every `Discriminator`
    field, and every `SkillConcretisedProcedure` field appears. `run_id` is
    bound and `spec_id` is derived, so neither is a model-authored field."""
    from polymerhus.attack.hunting.hunter_tools import SpecWrite  # noqa: PLC0415
    from polymerhus.attack.hunting.spec_contract import (  # noqa: PLC0415
        Discriminator,
        SKILL_CONCRETISED_PROCEDURE_FIELDS,
        SPEC_PROVENANCE_FIELDS,
        SkillConcretisedProcedure,
        TargetIdentity,
    )

    prompt = _prompt()
    start = prompt.index("## The spec body")
    body = prompt[start:prompt.index("\n## ", start)]

    for name in SpecWrite.model_fields:
        assert name in body, name
    for name in TargetIdentity.model_fields:
        assert name in body, name
    for name in Discriminator.model_fields:
        assert name in body, name
    for name in SPEC_PROVENANCE_FIELDS:
        assert name in body, name
    for name in SKILL_CONCRETISED_PROCEDURE_FIELDS:
        assert name in body, name
    for name in SkillConcretisedProcedure.model_fields:
        assert name in body, name
    assert "run_id" in body and "bound" in body.lower()
    assert "spec_id" in body and "derived" in body.lower()
    assert "skills" in body and "pod" in body.lower()


# --- the removals -------------------------------------------------------------


def test_the_prompt_removes_the_retired_nodes_and_vocabulary():
    """S3 8.5/8.8 and the S3 8.5 checklist: EVALUATE, CONCLUDE, [G], the class
    exhaustiveness question, the fault-hypothesis vocabulary, the retired
    statuses, and the retired D4 fields are absent."""
    prompt = _prompt()
    for gone in (
        "EVALUATE", "CONCLUDE", "[G]", "DECOMPOSE", "QUERY", "COMMIT",
        "SPEC-WRITE", "RANK", "D3", "class-exhaustiveness",
        "specific faults of this class", "exhaustive coverage of the specific",
        "fault-class", "fault class", "HuntConfig", "FaultItem",
        "payload_vector_space", "interpretation_guidance", "testing_pattern",
        "`verified`", "`specified`", "fault hypothesis", "candidate hypothesis",
        "candidate set", "supports", "conflicts",
    ):
        assert gone not in prompt, gone
    assert re.search(r"\bverified\b", prompt) is None
    assert re.search(r"\bspecified\b", prompt) is None


# --- the grounding scope ------------------------------------------------------


def test_grounding_starts_on_the_target_then_the_skill_then_the_sources():
    """S3 8.5: target surfaces first, then the class skill, then the other
    sources; the methodology KB grounds technology configurations only."""
    prompt = _prompt()
    grounding = prompt[prompt.index("**GROUNDING**"):prompt.index("**SLICE**")]
    assert "Ground on the target surfaces first" in grounding
    assert "Then load the class skill" in grounding
    assert "methodology KB for the target's technology configurations only" in grounding
    assert "HTTP history" in grounding and "notes" in grounding
    assert "previous spec sets" in grounding and "auth context" in grounding
    assert grounding.index("target surfaces first") < grounding.index(
        "Then load the class skill") < grounding.index("methodology KB")


def test_the_grounding_target_is_the_trust_agreements_technical_conditions():
    """S3 8.5: ground on the technical conditions of the trust agreements in
    an interface or a state transition - not on a class fault inventory."""
    prompt = _prompt()
    assert "technical conditions of the trust agreement in an interface or in a state transition" in prompt
    assert "explore/exploit" in prompt
    assert "retrieval-gap rider" in prompt
    assert "not a transition" in prompt


# --- the verify scope ---------------------------------------------------------


def test_verify_claims_probes_only_the_assumptions():
    """S3 8.5: assumption-falsification probes only - effective-technique
    feasibility, chained preliminary-vulnerability feasibility, and
    technology-configuration evidence; never a payload vector."""
    prompt = _prompt()
    verify = prompt[prompt.index("**VERIFY-CLAIMS**"):prompt.index("**COMPLETE**")]
    assert "Probe only the assumptions" in verify
    assert "advanced-technique feasibility" in verify
    assert "chained preliminary-vulnerability feasibility" in verify
    assert "technology-configuration evidence" in verify
    assert "Payload vectors may not yield these probes" in verify
    assert "do not probe whether a payload fires" in verify
    assert "each absorbed or unfeasible spec `status: \"dropped\"`" in verify
    assert "fail-open and loose" in verify
    assert "yields no meaningful insight" in verify
    assert "do not move the tracked state" in verify


# --- the role framing ---------------------------------------------------------


def test_the_role_framing_names_the_hunting_process_only():
    """S3 8.5: "engineering web vulnerability tests"; no wider codebase position
    and no hunter system version."""
    prompt = _prompt()
    assert "You are the hunting agent" in prompt
    assert "engineering web vulnerability tests" in prompt
    for gone in ("codebase", "repository", "polymerhus", "harness", "module",
                 "version", "versions"):
        assert re.search(rf"\b{gone}\b", prompt, re.IGNORECASE) is None, gone


# --- the loop ontology --------------------------------------------------------


def test_the_prompt_carries_the_loop_ontology():
    """S3 8.5: one paragraph with the unit and its technical sharpening, the
    trust model, the abduction chain, the confidence degree, the
    variant and manifestation space, and the reasoning from the loop to attacks."""
    prompt = _prompt()
    start = prompt.index("## The loop ontology")
    ontology = prompt[start:prompt.index("\n## ", start)]
    for clause in (
        "the unit and its technical sharpening",
        "the trust model: the trust agreement",
        "dynamic-state transition",
        "the abduction chain: the programming fault and the vulnerability",
        "the confidence degree",
        "the variant and manifestation space",
        "The reasoning from the loop to engineered attacks",
    ):
        assert clause in ontology, clause


# --- the discipline -----------------------------------------------------------


def test_the_prompt_carries_the_discipline_clauses():
    """S3 8.5: evidence-before-assertion, no-bulldozing, attempt-cap,
    meaningful-insight-guard, fail-open, target-front availability,
    graceful-degradation - plus the single-sourced conciseness directive."""
    from polymerhus.attack.hunting.conciseness import (  # noqa: PLC0415
        HUNTING_CONCISENESS_DIRECTIVE,
    )
    from polymerhus.attack.hunting.hunting_status import (  # noqa: PLC0415
        TARGET_UNAVAILABLE_DIRECTIVE,
    )

    prompt = _prompt()
    discipline = prompt[prompt.index("## Discipline"):prompt.index("## The tree")]
    for clause in ("Evidence before assertion", "No bulldozing", "Attempt cap",
                   "Meaningful-insight guard", "Fail-open",
                   "Graceful degradation"):
        assert clause in discipline, clause
    assert TARGET_UNAVAILABLE_DIRECTIVE in discipline
    assert HUNTING_CONCISENESS_DIRECTIVE in discipline


# --- the store protocol and the reduced surface -------------------------------


def test_the_prompt_carries_the_one_spec_write_and_the_three_statuses():
    """F-025: one `spec` object per write; the derived identity; the three
    statuses; the finalize call that closes the set."""
    prompt = _prompt()
    assert "Write the set one spec per `hunts_store` call" in prompt
    assert "exactly one `spec` object" in prompt
    assert "command" in prompt and "`spec`" in prompt
    assert "`specs`" not in prompt
    assert "`discriminators`" in prompt
    assert "Never author `spec_id`" in prompt
    assert "<class>__<value>__<value>" in prompt
    for status in ("hypothesised", "ratified", "dropped"):
        assert status in prompt
    assert 'command: "finalize"' in prompt
    assert "A finalize while any draft is still `hypothesised` is rejected" in prompt


def test_the_prompt_carries_the_reduced_d4_spec_body():
    """S3 8.6: target_identity, discriminators, verification_symptoms,
    assumptions, rationale, parent_spec_ref, provenance, and the typed
    nine-field skill_concretised_procedure."""
    prompt = _prompt()
    for field in ("`target_identity`", "`discriminators`",
                  "`verification_symptoms`", "`assumptions`",
                  "`rationale`", "`parent_spec_ref`", "`provenance`",
                  "`skill_concretised_procedure`"):
        assert field in prompt, field
    for field in ("`recon_action`", "`bypass_technique`", "`technology_grounding`",
                  "`pro_tips`", "`advanced_technique`", "`preliminary_chaining`",
                  "`payload_vector`", "`technology_misconfiguration`",
                  "`interpretation_pitfalls`"):
        assert field in prompt, field
    assert "non-empty list" in prompt
    assert "symptom-absent" in prompt
    assert "It carries no variant detail and no narrowed vector" in prompt


def test_the_baseline_example_is_an_artifact_pointer_not_a_request_line():
    """S5 8.5: `provenance.baseline_ref` is ONE optional artifact id, never a
    request line. The worked example must teach the replay-compatible shape."""
    prompt = _prompt()
    assert '"baseline_ref": "http_' in prompt
    assert '"baseline_ref": "GET ' not in prompt
    assert "the payload's baseline evidence" in prompt


def test_the_prompt_carries_the_phase_summary_note_exits():
    """S3 8.4/S4 14.8: five note exits named `phase:<state>` with kind
    `phase_summary`; a re-iteration updates the same note; the two store exits
    and the terminal pass carry no note."""
    prompt = _prompt()
    assert "`kind=phase_summary`" in prompt
    for phase in ("grounding", "slice", "collect", "discriminate",
                  "well_formedness"):
        assert f"`phase:{phase}`" in prompt, phase
    assert "`action=update`" in prompt
    assert "phase:generate" not in prompt
    assert "phase:verify_claims" not in prompt


def test_well_formedness_records_drops_and_never_writes_dropped_statuses():
    """S3 8.5: merge/drop decisions ride the phase note; the terminal write
    applies the drops; no mechanical exhaustiveness claim."""
    prompt = _prompt()
    well = prompt[prompt.index("**WELL-FORMEDNESS**"):prompt.index("**VERIFY-CLAIMS**")]
    assert "no two specs own the same sub-slice" in well
    assert "Exhaustive coverage of the slice" in well
    assert "record every merge and drop" in well
    assert "A merge keeps one identity" in well
    assert "the absorbed identity as `dropped`" in well
    assert "Write the exit note once, when the check is final" in well
    assert "Do not write a `dropped` status here" in well
    assert "one-spec status writes at VERIFY-CLAIMS apply the drops" in well
    assert "no mechanical check" in well
    assert "never claim a proof of exhaustiveness" in well


# --- the examples -------------------------------------------------------------


def test_the_worked_rationale_does_not_restate_the_symptom():
    """S3 8.6: the rationale is vulnerability-level. The worked example is a
    literal contract sample, so its rationale must not restate the symptom or
    carry a variant detail (the defect this predicate pins: a rationale
    that duplicated the `verification_symptoms` phrase verbatim)."""
    prompt = _prompt()
    worked = prompt[prompt.index("## Worked example 1"):]
    symptom = re.search(r'"verification_symptoms": \[(.*?)\]', worked, re.S)
    rationale = re.search(r'"rationale": "(.*?)"', worked, re.S)
    assert symptom is not None and rationale is not None

    symptom_text = " ".join(symptom.group(1).split()).strip().strip('"').strip()
    rationale_text = " ".join(rationale.group(1).split())

    def words(text):
        return re.findall(r"[a-z0-9]+", text.lower())

    symptom_words = words(symptom_text)
    rationale_words = words(rationale_text)
    # no four-word run of the symptom may reappear in the rationale: a
    # restated manifestation is exactly such a run ("another tenant's report
    # body" was the regression), while a vulnerability-level rationale may
    # still share a noun or two.
    symptom_runs = {tuple(symptom_words[index:index + 4])
                    for index in range(len(symptom_words) - 3)}
    rationale_runs = {tuple(rationale_words[index:index + 4])
                      for index in range(len(rationale_words) - 3)}
    assert symptom_runs & rationale_runs == set()
    assert symptom_text.lower() not in rationale_text.lower()


def test_the_examples_are_rewritten_for_the_new_passes_and_surface():
    """S3 8.5: imitate the reasoning shape, not the old domain; the off-path
    examples cover a [D2] re-entry, a probe, and a degraded run."""
    examples = _examples()
    assert "Hunting-agent worked examples" in examples
    assert "Example 2 - well-formedness re-entry" in examples
    assert "Example 3 - a falsifying probe" in examples
    assert "Example 4 - worst case, graceful degradation" in examples
    for gone in ("HuntConfig", "DECOMPOSE", "EVALUATE", "CONCLUDE", "[G]",
                 "payload_vector_space", "interpretation_guidance",
                 "testing_pattern", "COMMIT", "QUERY", "SPEC-WRITE"):
        assert gone not in examples, gone
    for present in ("phase:grounding", "phase:slice", "phase:collect",
                    "phase:discriminate", "phase:well_formedness",
                    "hypothesised", "ratified", "dropped", "specs"):
        assert present in examples, present
    # the structural support stays in the threat model, never the rationale;
    # an absent class skill is a grounding gap, not rationale material
    assert "structural reasoning carried in the rationale" not in examples
    assert "class skill absent" in examples
    # the [D2] example's terminal set follows its probes: the share-route mint
    # is the spec the 403 falsifies, while the signed-URL delivery survives
    normalized = " ".join(examples.split())
    assert "The share-route spec is unfeasible" in normalized
    assert "the widened direct-route and signed-URL specs ratified" in normalized
    assert "the signed-URL spec is unfeasible" not in examples


def test_the_tools_section_names_every_bound_tool():
    """The hand-written summary is a human projection; it must not omit a
    bound capability."""
    prompt = _prompt()
    section = prompt[prompt.index("## The tools"):prompt.index("\n## ", prompt.index("## The tools"))]
    for name in ("hunts_store", "notes", "graph_view", "kb_query", "exec",
                 "skill_list", "skill_load", "search_http_history",
                 "get_http_artifact", "load_skill", "record_skill_lesson",
                 "auth_store"):
        assert name in section, name


def test_the_phase_hint_wording_is_transition_only():
    """The hint is injected only when a pass exits and the response drives the
    next pass; the prompt must not claim that every tool result carries one."""
    prompt = _prompt()
    assert "Each tool result may carry" not in prompt
    assert "A result may carry" not in prompt
    assert "When the workflow transitions to a new pass" in prompt
    assert "ending tool response" in prompt
    assert "guidance, never a gate" in prompt


def test_the_prompt_stays_within_a_reasonable_size():
    """A stable system prompt, not a wall of text (the modeller prompt's bar).

    The bound grew from 420 to 460 with the realigned spec contract: the
    generated table now expands the discriminator and the nine-field
    concretisation so the hunter never has to infer either shape."""
    assert len(_prompt().splitlines()) < 460
