# Plan - TestImplementationSpecs QA measurement and the Q33-Q36 recording

> **Vocabulary note (2026-10-25).** The artifact called a **loop** in this historical document is now a **threat** in the module and the current documentation.

Status: active, written 2026-10-17 in the unit-threat-model worktree.
Authority: the operator directive of 2026-10-17 (answers to Q33-Q36 plus the measurement order).
Scope: record the new decisions; file the CVSS-adoption ticket; initialise the measurement document with the quality-assessment ground truth; run the mock-hunter measurement over the 22 minted loops; assert the discrepancies; report the qualitative root causes; then open the next grilling round.

## Objective

Measure the quality of the engineered attack artifacts (TestImplementationSpecs sets) that the respecified hunter feed-forward contract yields, before the change is built.
The measurement feeds the next grilling round with evidence on the hunter reasoning architecture.

## Steps and gates

- S1 - Payload build. Extract per-loop payloads from the two trial models (T1: 13 loops, T2: 9 loops) with the respecified rendering: unit context, technical sharpening overview, trust overview (agreements or dynamic-state trust), the loop chain (assumption -> fault -> vulnerability), likelihood, confidence degree, evidences; no failure modes.
  Gate: 22 payload files parse, refs resolve, no `failure_mode` string in any payload.
- S2 - Measurement document. Initialise `docs/experiments/unit-threat-model-testimplspecs-qa.md` following `measure-experiment-results`: hypothesis, method, the quality-assessment ground truth (rubric plus per-loop expectations derived from the models' failure modes), result placeholders.
  Gate: every loop has ground-truth rows; the rubric is explicit.
- S3 - Mock-hunter package. Write the improved hunter prompt (system + task) under `docs/experiments/unit-threat-model-prototype/qa/`: loop ontology in the system prompt; abduction rendering in the human input; the adapted decision tree; output contract (per-loop spec set YAML); tools maximal, no lightrag; skills loaded from `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious`.
  Gate: the package runs standalone on one loop by inspection (no missing inputs).
- S4 - Dispatch. Two background subagents (one per trial model) each iterate their loops, persisting `qa/<t>/output/loop-<n>.yaml` per iteration.
  Gate: all 22 output files exist and parse.
- S5 - Review pass 1. Format and completeness check per output; record defects.
- S6 - Assertion pass. Assert discrepancies against the ground truth; walk backward to qualitative root causes; cluster into actionable items; write into the measurement document (results, learnings, recommendation, next steps).
- S7 - Recording pass (parallel with S4). Record Q33-Q36 in the workbench, the workflow doc and `CONTEXT.md`: confidence-degree rename, its content profile and falsification-nature lifecycle; the CVSS-inspired 5-level scoring with the four attributes and their formal definitions; Design B ratification; the validation seam; the hunter feed-forward contract.
- S8 - Tickets. File the CVSS full-base-metrics adoption enhancement ticket (deferred).
- S9 - Next grilling round. Compose the next questions integrating the QA insights plus the remaining frontier.

## Feedback loops

- After S5 or S6, fix mock-prompt artifacts immediately and re-run only the affected loops (one re-run cycle budget).
- The recording pass (S7) runs while S4 runs; no loop output depends on it.

## Deviation budget

- One mock re-run cycle (S6 trigger only).
- The mock has no pod: EVALUATE closes as not-executed by design; the spec set is the artifact under measure.

## Deliverables

- `docs/experiments/unit-threat-model-testimplspecs-qa.md` (measurement document, ground truth + results).
- `docs/experiments/unit-threat-model-prototype/qa/` (payloads, mock prompt package, outputs).
- Workbench, workflow doc, `CONTEXT.md` updated; CVSS-adoption ticket filed.

## Status log

- 2026-10-17: S1-S8 complete - 22 payloads built and gated; measurement document initialised with the frozen ground truth; mock package written; two mock subagents dispatched (after free-tier rate limits, via the opencode-go provider) and all 22 spec sets returned; mechanical pass clean; assertion pass and report written (primary 22/22; two partials; amendments A1-A4); recording pass done (workbench Round 6, workflow doc section 3.6 and updates, `CONTEXT.md`); ticket `#368` filed.
- QA outcome fed Round 7 (Q37-Q40); answered 2026-10-18: A1 not adopted; A2 documented as a structural limitation; A3 unticketed; `#354` not relabelled; the scoring enum ratified as `none / low / medium / high / critical` with monotonic weights (Q40(b)); R2-16 materialisation retired fully.
- 2026-10-18: Round 8 recorded - the production hunter prompt redesign (R8-1) and the two new grilling frontiers (R8-2 hunter harness FSM refactor; R8-3 test-executor-pod contract); the abduction research (R4-3/Q38) dispatched.
