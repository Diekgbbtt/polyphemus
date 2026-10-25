# Unit threat model prompt synergy

## Amendment 2026-10-25: impact-first elicitation

The threat-model impact-elicitation workstream supersedes the likelihood-only risk score and the failure-mode artifact in this document.
The decisions are in `docs/design/threat-model-impact-elicitation-adr.md`; the component map is `docs/design/threat-model-impact-elicitation-impact-map.md`.
Where this document and the amendment disagree, the amendment wins.

- A loop carries `VC`, `VI`, and `VA` plus a literal end impact. The store computes `impact = 1 - (1-VC)(1-VI)(1-VA)`, the ordinal weight, and `loop risk = likelihood_weight * impact_weight`.
- The ranking and the dispatch buckets use the combined risk. The run record carries `impact_weights` and `impact_breakdown`.
- The `failure_modes` artifact, `Loop.failure_mode_refs`, and the pod `failure-mode` variant basis are removed. The modeller no longer judges technical feasibility; the hunter and the pod own the effective attempt.
- The trust procedure uses the four axes `identity`, `spatial`, `temporal`, and `controls_semantics`.
- The well-formedness loop runs between `VULNERABILITIES_WRITTEN` and `COMPLETED`. Its exit is one `wellformedness` note plus the `COMPLETED` write; a lower-gate write is the re-entry signal.
- Every vulnerability binds a suite class parent or leaf. Technique families are not classes. `suite_gap` is removed. Class findings are non-blocking.


## Purpose

This note compares the committed dev hunting prompts with the unit threat model prompts.
It identifies skill-relevant verbatims beyond the cortex.
It judges which dev text is portable, which is obsolete, and where the two systems reinforce each other.
It is a merge note, not a new design.

## Method

I compared the dev prompts at the skills-system merge commit with the unit threat model prompts.
I also read the skill loader contract, the role roster, the artifact-declared skill contract, and the D4 spec contract.
The judgment follows the integration rule: the unit threat model is authoritative for the hunting domain model and the prompt workflow, while dev is authoritative for the skills surface, the bounding mechanism, the prompt specification, the typed hunting-artifact surface, and the cortex.

## Findings

| Dev material | Where it lives | Fit with the new workflow | Decision |
|---|---|---|---|
| Cortex | `cortex.py` and `prompts/COGNITIVE_ARCHITECTURE_MAP.md` | The map names procedural knowledge as a data domain and separates it from testing knowledge; the suite is exactly that procedural layer. | Ported. Appended to the threat modeller, hunter, and pod prompts. |
| `load_skill` and `record_skill_lesson` tool lines | `prompts/pod-runner.md`, `prompts/pod-triager.md` | The pod roles consume the D4 `skills` declaration and write usage lessons; the lines are still accurate. | Ported. The D4 pod field remains. |
| `SKILL_LOAD_CONTRACT` phase-gating rule | `app/llm/skills.py` tool description | Load at phase entry, once per thread, never speculatively mid-reasoning. It fits the new pass sequence and the optional assumption check. | Kept in the tool description; the new prompts do not re-spell it. |
| Artifact-declared skills contract | `CONTEXT.md`, `actors.py`, `hunter_tools.py` | The hunter-to-pod half survives: the hunter writes `skills` on the D4 spec. The orchestrator-to-hunter half dies with `HuntConfig`. | Partially ported. The orchestrator declarer is retired. |
| `HuntConfig` skill declaration | old orchestrator surface | The unit threat model has no config and no loop-payload `skills` field. | Retired. |
| `payload_vector_space`, `testing_pattern`, `interpretation_guidance` | old hunter prompt and D4 | These fields are retired by the reduced D4 and the procedure-diff variant minting. | Not ported. |
| "A variant is a mutation of one flexible attribute" | old hunter prompt | The new variant basis is the first uncovered procedure gap, a failure mode, or a runner recovery. | Not ported. |
| `SkillProcedure` typed excerpt | `spec_contract.py` | It carries the class procedure from the hunter to the pod; the D4 `skills` declaration arms the pod's read surface. The two are complementary. | Kept. |
| Suite listing and load | feature `skill_list` and `skill_load` | The dev suite makes the seam live. The class parent remains the `web_vulnerability_class`; the variant leaves are additional discovery material. | Wired to all suite leaves. |

## Critical reading

The dev hunter prompt is not a source of new skill prose.
Most of its skill behavior lives in the tool binding, the role roster, and the tool contract, not in the prompt body.
Its payload-vector and testing-pattern sections belong to the retired `HuntConfig` testing ontology.
Pasting them into the new hunter would reintroduce retired fields and weaken the procedure-diff workflow.

The dev pod prompts are the most portable prompt material.
Their skill tool lines are short, accurate, and already aligned with the D4 pod field.
The dev cortex is the second high-value item; it gives the suite a named place in the agent's world model.

The suite leaves are a discovery surface, not a classification authority.
The unit threat model's abduction chain runs from a trust assumption to a programming fault to a vulnerability class.
A class-first load can invert that chain and produce a fault that the trust model never supported.
The optional assumption check therefore states the direction explicitly: a leaf may suggest an assumption, but it never supplies the fault by itself.

The dev phase-gating rule is the main unported prompt behavior.
It is present in the `load_skill` tool contract, so every agent reads it at the tool boundary.
Duplicating it in the prompts would add words without adding a new constraint.

## Synergy

The suite gives the threat modeller a concrete assumption-check vocabulary.
The modeller can list all leaves, load a class or variant, and test whether a trust assumption is the root cause of a named class.
The same suite gives the hunter a class procedure and the pod a declared skill set.
The D4 `skills` field and the `SkillProcedure` excerpt cover different needs: selection and procedure.
The pod's `record_skill_lesson` closes the loop into the app-level SkillEvolver.
The cortex names the procedural layer those lessons improve.

The optional actions added in this merge are:

- Threat modeller: list and load suite leaves before the saturation check, only to generate or sharpen a trust assumption, never to reverse the abduction chain.
- Hunter: list and load a sibling leaf when the class skill is silent on a slice assumption; keep the loop's class and slice.
- Pod runner: load a declared suite leaf when the procedure excerpt is silent on a load-bearing assumption; do not re-classify the spec.

All three actions are optional.
None writes a skill or a loop-payload field.
