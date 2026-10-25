# Modeller impact-quality workstream plan

## Goal

Shift the threat modeller's loop mass from low-yield contract findings to high-yield, technically sharp vulnerabilities.
Make end impact a first-class, numerically scored property of every loop.
Remove the failure-mode artifact and move technical feasibility to the hunter and the pod.
Turn the trust-model stretch into a well-formedness loop that reads the class skills.
Keep the run deterministic, auditable, and within the token budget.

## Experiment score

The success gate is the green-loop share over all stored loops.

- A loop is green when its `web_vulnerability_class` is in the ratified high-yield set plus CSRF and clickjacking.
- A variant leaf rolls up to its class parent before the check.
- The target is more than 90% green loops.
- Secondary metrics: severe share, sharp-boundary share, class-binding rate, severe loops below the medium risk bucket, capped tokens per green loop.
- The A/B uses a 7M capped budget per the operator's protocol.

## Decisions

- The impact metrics are `VC`, `VI`, `VA` only.
- The metric weights are `N = 0.00`, `L = 0.22`, `M = 0.35`, `H = 0.56`.
- `impact = 1 - (1 - VC)(1 - VI)(1 - VA)`.
- The ordinal impact weight is `0`, `1`, `2`, `3`, `4` with the thresholds in the impact map.
- `loop_risk = likelihood_weight * impact_weight`.
- The ranking is risk, then impact, then likelihood, then write order.
- The dispatch buckets are critical `>= 12`, high `8..11`, medium `4..7`, low `1..3`, none `0`.
- The provisional threshold is `360`.
- The trust axes are `identity`, `spatial`, `temporal`, `controls_semantics`.
- The well-formedness phase is a pass-level pseudo-phase, not a new `ModelState`.
- The exit is one `wellformedness` note plus the `COMPLETED` write.
- A lower-gate write after vulnerabilities is the re-entry signal.
- The loop has no iteration bound.
- The drop rule has two clauses: the data is not attacker-influenced, or the trust agreement is misspecified.
- Unobserved assumptions survive. A missing observation or a failed probe is not a drop reason.
- The modeller judges exploitability through the likelihood score. The hunter and the pod own technical feasibility and effective attempt.
- The failure-mode artifact, the pod `failure-mode` variant basis, and the hunter failure-mode references are removed.
- The hunter keeps its existing reasoning axes: vulnerability variants, manifestation, testing technique, framework or protocol misconfiguration, payload vector class.
- The class binding requires a suite class parent or leaf. `suite_gap` is removed.
- Technique families are never the class. They stay in the characterisation prose.
- The non-blocking finding covers an empty class, a technique family, and a name outside the suite.
- The low-yield loops stay stored. Their risk is low or zero, so they do not enter the priority dispatch.

## Non-goals

- No new hunting role.
- No change to the L1 intake or the unit projection.
- No change to the pod execution contract beyond the variant-basis removal.
- No change to the eval orchestrator vocabulary.
- No rewrite of historical experiment reports.
- No new `ModelState` enum value.
- No new hunter reasoning vocabulary.

## Seams under test

- `threat_model.Impact`, `compute_impact`, `impact_weight`, `loop_risk`, `compute_risk_profile`, `normalise_loops`, `check_completion`.
- `threat_model_store.write_sections`, `ThreatModelStore._merged_document`, `_commit`.
- `threat_modeller_tools.ModellerHuntsStoreArgs`, `ModellerNotesHandle`, `build_modeller_notes_tool`, `build_vulnerability_suite_tools`.
- `threat_modeller.arun_modeller_pass`, `ModellerTurnInput`, `STATE_INSTRUCTIONS`, `PassiveGateTracker`.
- `run_lifecycle.model_sum`, `RiskAccumulator`, `risk_weights`, the resume recompute.
- `runtime` threshold and run-record writes.
- `pipeline_sync._loop_weight`, `_risk`, `hunt_rank`.
- `mover.ThreatLoopItem`, `sequence_dispatch`, `threat_loop_item`.
- `surfer` live-loop priority map.
- `hunter_payload.materialise_hunter_payload`.
- `hunting_agent._compose_first_step`, `prompts/hunting-agent.md`.
- `hunter_state.phase_note_name`, the grounding note.
- `pod.variant_basis.mint_variant_basis`, `first_uncovered_gap`, `VARIANT_BASES`.
- `pod.agents.TriagerDecision`, `pod.graph`, `pod.context`, `prompts/pod-triager.md`.

## Acceptance criteria

- `impact` exists on the vulnerability and the loop, with `VC`, `VI`, `VA`, the end-impact statement, and the ordinal weight.
- `compute_impact` returns the formula value and the ordinal weight for every metric combination in the table test.
- `compute_risk_profile` sums `likelihood_weight * impact_weight`.
- `normalise_loops` ranks by risk, then impact, then likelihood, then write order.
- The loop file and the hunter payload carry the impact and the risk.
- The run record carries the likelihood weights, the impact weights, the impact breakdown, and the risk breakdown.
- The resume recomputes the combined total from the model sums and the models.
- The mover gates low-bucket loops behind higher buckets.
- The modeller prompt carries the four trust axes, the field and state elicitation, the impact elicitation, the well-formedness loop, the class guard, and the composite example.
- The modeller prompt carries no failure-mode phase and no encoding floor.
- The pass asks the well-formedness turn after vulnerabilities and after a lower-gate write.
- The `wellformedness` note is written once at the exit.
- The `notes` tool accepts the `wellformedness` kind.
- The completion checker records a non-blocking finding for an empty class, a technique family, or a non-suite name.
- `suite_gap` is removed.
- The `failure_modes` section, the `failure_mode_refs` link, the pod `failure-mode` basis, and the hunter failure-mode references are removed.
- The hunter prompt uses only the existing reasoning axes.
- Every updated design spec and `CONTEXT.md` matches the code.
- The focused suites pass, then `tests/attack`, then the pod integration and e2e suites.
- `compileall` is clean and `git diff --check` is clean.
- The A/B runs on a fresh instance with the same threshold per arm.
- The green-loop share is measured over all stored loops.

## Tickets

The ticket order is the dependency order.
Each ticket lands green on its own.
The failure-mode removal is expand-contract: the impact lands first, the readers migrate, then the failure-mode artifact is removed.

### Phase 0: Decisions and records

| # | Ticket | Blocked by | Delivers |
|---|---|---|---|
| 402 | Record the impact-elicitation ADR and the impact map | none | The ADR and the impact map in the docs bank |
| 403 | Record the baseline measurement | none | The baseline report and the survey script (done in `9eb66a0a`) |

### Phase 1: Impact schema and scoring

| # | Ticket | Blocked by | Delivers |
|---|---|---|---|
| 404 | Add the impact model to the threat-model schema | 402 | `Impact`, `compute_impact`, `impact_weight`, `loop_risk`, the combined profile, the ranking, and the table tests |
| 405 | Persist the impact through the store and the model sections | 404 | The write/read round-trip, the old-model tolerance, and the loop-file impact |
| 406 | Carry the impact and risk in the hunter payload | 405 | The payload fields and the tests |
| 407 | Move the run risk accumulator to the combined score | 406 | `model_sum`, `RiskAccumulator`, `risk_weights`, the resume recompute, and the run-record fields |
| 408 | Move the dispatch priority to the combined score | 407 | `pipeline_sync`, `mover`, `surfer`, the low-bucket gating, and the tests |
| 409 | Render the combined risk on the status surfaces | 408 | The status and run-record rendering, with tests |

### Phase 2: Prompt and well-formedness

| # | Ticket | Blocked by | Delivers |
|---|---|---|---|
| 410 | Rewrite the trust-modelling procedure with the four axes | 409 | The axis framework, the field and state elicitation, the Branch A/B balance, and the prompt tests |
| 411 | Rewrite the impact elicitation and remove the failure-mode phase | 410 | The impact reasoning, the metric elicitation, the loose drop rule, the encoding-floor removal, and the prompt tests |
| 412 | Add the well-formedness pseudo-phase to the pass | 411 | The pass turn, the re-entry detection, the `wellformedness` note kind, and the pass tests |
| 413 | Add the class binding guard and the non-blocking finding | 412 | The verbatim guard, the suite index lookup, the `suite_gap` removal, and the validator tests |
| 414 | Add the composite SSRF/TOCTOU example | 413 | The example, the low-yield contrast, and the prompt tests |
| 415 | Adversarial prompt review and fixes | 414 | The concision, completeness, and cohesion report, and the fixes |

### Phase 3: Failure-mode contraction

| # | Ticket | Blocked by | Delivers |
|---|---|---|---|
| 416 | Remove the failure-mode section from the schema and the store | 415 | The schema, store, validator, and fixture removal |
| 417 | Remove the failure-mode references from the hunter | 416 | The prompt and module cleanup, with the existing axes |
| 418 | Remove the pod failure-mode variant basis | 417 | The basis, field, prompt row, and tests |
| 419 | Sweep the remaining failure-mode references | 418 | The payload, docs, and module sweep, with a grep gate |

### Phase 4: Docs, verification, and the A/B

| # | Ticket | Blocked by | Delivers |
|---|---|---|---|
| 420 | Update the design specs, CONTEXT, and the ADR | 419 | The full docs pass |
| 421 | Run the full verification suite | 420 | The focused suites, `tests/attack`, the pod integration and e2e, `compileall`, and `git diff --check` |
| 422 | Run the A/B and measure the green-loop share | 421 | The A/B report and the ship/iterate decision |

## Status

- Phase 0 is complete. The baseline report is committed at `9eb66a0a`; the impact map, plan, and tickets are at `e7fc64b1`.
- Phase 1 is complete. The impact model and combined risk are at `9b5f97c6` and `6f4b5385`.
- Phase 2 is complete. The prompt, well-formedness pass, class guard, and example are at `8a5bf072`.
- Phase 3 is complete. The failure-mode contraction and the hunter/pod cleanup are at `de9cb2c5` and `2e2037a5`.
- Phase 4 is complete for the docs. The implementation result is `docs/experiments/modeller-impact-quality/IMPLEMENTATION.md`.
- The procedural verification is complete: `tests/attack` 1094 passed, pod contracts and e2e 27 passed, project management plus settings 8 passed and 2 skipped, eval trial 68 passed, `compileall` clean, `git diff --check` clean.
- The A/B is pending the operator's protocol. It is an experimentation item, not a tracked ticket.

## Tight feedback loops

- Every ticket starts with a failing test.
- Every ticket ends with the focused suite and a commit.
- The prompt tickets are implemented with subagents and an adversarial review after each.
- The review checks concision, presence of the specified content, and cohesion with the surrounding prompt.
- The full suite runs after the contraction phase, not only at the end.
- The A/B runs only after the branch is merged into the trunk and the eval server has the new code.
