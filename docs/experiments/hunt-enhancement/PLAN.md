# Hunt enhancement trunk plan

## Goal

Reduce semantic duplication and attention tax across the hunting agents without weakening their data contracts.
Keep the canonical typed models, the request tool schemas, and the target context.
Implement the safe cuts in this branch, measure the result, and stop before any trial.

## Decisions

- The experimentation trunk is `hunt-enhancement-trunk`.
- The trunk was created from `fix/context-lifecycle-followup` and merged with `docs/comfyui-hunting-retest`.
- The trunk is pushed to origin.
- This branch is `fix/hunt-context-dedup`, branched from the trunk.
- The system-prompt decision is the minimal cut.
- The loop tool surface is removed.
- The old full skill index is already gone and stays gone.
- The hand-written `## The tools` section and the 248-char direct-reference line stay.
- `skills` stays writable and is documented.
- All writable spec fields get an explicit human projection.
- The first human message is pinned for all four hunting roles.
- No new trial runs in this branch.
- A later trial runs only after this branch is merged into the trunk, the trunk is merged into `dev`, CD reaches the eval server, and the operator authorizes the run.
- The experiment score is `capped_tokens / confirmed_symptoms`, lower is better.
- The score is reported separately for ground-truth and non-ground-truth confirmations.
- A confirmed symptom is a pod export with `terminal_reason=symptom-confirmed`.
- A distinct non-ground-truth vulnerability groups confirmed symptoms by spec identity.

## Non-goals

- No system-prompt cut beyond the minimal cut.
- No removal of `## The tools` or the direct-reference line.
- No new live trial.
- No change to the model, compaction thresholds, token caps, or USD guards.
- No change to the hunting reasoning beyond the explicit contract fixes.
- No broad rewrite of the analysis agents.

## Seams under test

- Hunter first-human composition: `hunting_agent._compose_first_step`.
- Hunter prompt loading: `hunting_agent._load_hunting_agent_skill`.
- Hunter spec contract: `hunter_tools.SpecWrite`, `spec_contract.SpecProvenance`, `pod.types.TestImplementationSpec`.
- Hunter tool descriptions: `build_hunter_tools`, `auth_capable_binding`, `build_skill_tools`.
- Phase hint wording: `hunting_agent._STEP_PROTOCOL` and `prompts/hunting-agent.md`.
- Compaction: `app.llm.compaction.compact_pass`, `create_compaction_middleware`, `build_role_compaction_middleware`.
- Modeller prompt: `prompts/threat-modeller.md`, `threat_modeller_tools`, `threat_model`.
- Pod prompts: `prompts/pod-runner.md`, `prompts/pod-triager.md`, `pod/agents.py`, `pod/context.py`.
- Pod variant and terminal contracts: `pod/variant_basis.py`, `pod/verification.py`, `pod/agents.TriagerDecision`.

## Acceptance criteria

- The hunter first human message contains no `Tool surface` block.
- The hunter first call removes the 22,470-char loop tool surface.
- The hunter request tool descriptions are at most 8,500 chars in total.
- The hunter request tool schemas are unchanged in meaning and still expose every field.
- The hunter spec prompt names every writable `SpecWrite` field and every nested `SpecProvenance` field.
- `skills` is documented as a writable list of pod runner skill names.
- `run_id` is documented as bound and non-writable.
- `spec_id` is documented as derived.
- The phase-hint text says that a transition tool response carries the hint.
- The hint remains guidance, never a gate.
- The technical sharpening projection is at most 4,000 chars and keeps every agreement id and statement.
- Compaction preserves the first human message for the hunter, modeller, pod runner, and pod triager.
- Compaction without the pin keeps its current behavior.
- The modeller prompt tables are generated from `ModelState`, `GATE_SECTIONS`, and `ModelSections`.
- The modeller tool list names every bound tool.
- The pod prompt tool lists name every bound tool.
- The triager binds the read-only auth store.
- The pod variant table matches `VARIANT_BASES`.
- The pod terminal vocabulary matches the validator.
- The conciseness directive is single-sourced.
- The reports quantify the current occupancy, the removed duplication, and the cache-miss effect.
- The focused suites pass.
- The combined suite passes with no new failures.
- The branch is merged back into `hunt-enhancement-trunk`.
- No trial is run.

## Status at handoff

The plan is the execution contract; this section records the actual state.

- Phase 0 is complete.
- Phase 1 is complete and the hunter harness suite is green.
- Phase 2 is complete and the hunter prompt and tool suites are green.
- Phase 3 is complete: the 12 hunter descriptions total 8,478 chars, under the 8,500 ceiling.
- Phase 4 is complete for all four roles and the compaction suite is green.
- Phase 5.1 is complete: the modeller report is written.
- Phase 5.2 is partial: the tool list, the shared 5xx pointer, and the contract coverage tests are done; the state, gate, and reference table generation is deferred.
- Phase 6.1 is complete: the pod report is written.
- Phase 6.2 is partial: the tool lists, the read-only auth store, and the contract coverage tests are done; spec, variant, terminal, and memory generation is deferred.
- Phase 7 is partial: the reports and focused suites are done; the full suite is blocked by the missing Docker, Steel, database, and sibling-agent tiers; no trial ran.

The system-prompt decision is the user's minimal cut.
The body, examples, and cortex-only option was not taken.
The hand-written `## The tools` section and the direct-reference line stay.

## Phase 0: Trunk and plan

- [x] Create `hunt-enhancement-trunk` from `fix/context-lifecycle-followup`.
- [x] Merge `docs/comfyui-hunting-retest` into the trunk.
- [x] Resolve the `FAILURES.md` union.
- [x] Push the trunk.
- [x] Create `fix/hunt-context-dedup` from the trunk.
- [x] Write this plan.
- [ ] Commit this plan.

## Phase 1: Hunter loop surface and first-human composition

### Task 1.1: Remove the loop tool surface

**Files:**
- Modify: `src/polymerhus/attack/hunting/hunting_agent.py`
- Test: `tests/attack/test_hunting_agent.py`

- [ ] Write a failing test that the first human message has no `Tool surface` block.
- [ ] Write a failing test that the first human message still carries grounding, state, and step protocol in order.
- [ ] Remove `_tool_surface` from `_compose_first_step`.
- [ ] Remove the tool-surface call site from `build_hunting_agent`.
- [ ] Update `_HUNTER_CHAIN` to remove the tool-surface wording.
- [ ] Update the existing first-human order test.
- [ ] Run the hunter harness suite.
- [ ] Record the first-human char delta.

### Task 1.2: Bound the technical sharpening projection

**Files:**
- Modify: `src/polymerhus/attack/hunting/hunting_agent.py`
- Test: `tests/attack/test_hunting_agent.py`

- [ ] Write a failing test with oversized sharpening evidence entries.
- [ ] Assert the rendered sharpening is at most 4,000 chars.
- [ ] Assert every interface, control-flow, and data-flow id and statement survives.
- [ ] Project each agreement to `id`, `statement`, and `confidence`.
- [ ] Drop only the repeated evidence entries from the rendered projection.
- [ ] Run the hunter harness suite.
- [ ] Record the sharpening char delta.

## Phase 2: Hunter spec contract and phase hint

### Task 2.1: Generate the spec body from the typed models

**Files:**
- Modify: `src/polymerhus/attack/hunting/hunter_tools.py`
- Modify: `src/polymerhus/attack/hunting/prompts/hunting-agent.md`
- Modify: `src/polymerhus/attack/hunting/hunting_agent.py`
- Test: `tests/attack/test_hunting_agent_prompt.py`
- Test: `tests/attack/test_hunter_tools.py`

- [ ] Write a failing test that every writable `SpecWrite` field appears in the prompt.
- [ ] Write a failing test that every `SpecProvenance` field appears in the prompt.
- [ ] Write a failing test that `skills` is documented as a list of pod runner skill names.
- [ ] Write a failing test that `run_id` is marked bound and non-writable.
- [ ] Write a failing test that `spec_id` is marked derived.
- [ ] Add a generated spec-body renderer sourced from the typed models.
- [ ] Replace the hand-written `## The spec body` block with the generated projection.
- [ ] Keep the `skill_procedure` seven-field excerpt guidance.
- [ ] Run the hunter prompt and tool suites.

### Task 2.2: Correct the phase-hint wording

**Files:**
- Modify: `src/polymerhus/attack/hunting/prompts/hunting-agent.md`
- Modify: `src/polymerhus/attack/hunting/hunting_agent.py`
- Test: `tests/attack/test_hunting_agent_prompt.py`
- Test: `tests/attack/test_hunting_agent.py`

- [ ] Write a failing test that the old `Each tool result may carry` wording is absent.
- [ ] Write a failing test that the transition-only wording is present.
- [ ] Replace the prompt wording.
- [ ] Replace the step-protocol wording.
- [ ] Keep the guidance-not-a-gate sentence.
- [ ] Run the hunter suites.

## Phase 3: Hunter tool descriptions

### Task 3.1: Establish the description budget

**Files:**
- Test: `tests/attack/test_hunter_tools.py`
- Test: `tests/attack/test_auth_seams.py`

- [ ] Write a failing test that the bound hunter descriptions total at most 8,500 chars.
- [ ] Write a failing test that the read-only auth store is bound for the hunter.
- [ ] Write a failing test that every bound hunter tool has a non-empty description.
- [ ] Write a failing test that the critical clauses are present.
- [ ] Critical clauses: one spec per write, derived identity, finalize gate, phase-note exit, read-only graph view, KB query contract, target-front 5xx rule, HTTP history search/get, skill list/load, project skill load, auth read-only.

### Task 3.2: Slim the shared descriptions

**Files:**
- Modify: `src/polymerhus/attack/hunting/hunter_tools.py`
- Modify: `src/polymerhus/attack/hunting/threat_modeller_tools.py`
- Modify: `src/polymerhus/attack/hunting/graph_view_tool.py`
- Modify: `src/polymerhus/app/auth/tool.py`
- Modify: `src/polymerhus/app/llm/skills.py`
- Test: `tests/attack/test_hunter_tools.py`
- Test: `tests/attack/test_threat_modeller_prompt.py`
- Test: `tests/attack/pod/test_prompts.py`

- [ ] Rewrite each top-level description to purpose, operation, constraints, and error envelope.
- [ ] Keep field-level detail in the pydantic schema descriptions.
- [ ] Keep the auth read-only contract at or below 3,100 chars.
- [ ] Keep the shared HTTP search and get contracts at or below 1,600 chars combined.
- [ ] Keep the graph-view contract usable without its long example.
- [ ] Keep the skill load and lesson contracts at or below 1,100 chars combined.
- [ ] Run the focused tool and prompt suites.
- [ ] Record the description char delta per tool and per role.

## Phase 4: Compaction pin

### Task 4.1: Add a pinned leading human message

**Files:**
- Modify: `src/polymerhus/app/llm/compaction.py`
- Test: `tests/test_llm_compaction.py`

- [ ] Write a failing test that `compact_pass` preserves the first human message when the pin is enabled.
- [ ] Write a failing test that the pinned message stays at the head of the staged trail.
- [ ] Write a failing test that the summary follows the pinned message.
- [ ] Write a failing test that the default path is unchanged.
- [ ] Add a `pin_first_human` parameter to the compact pass and the manager.
- [ ] Preserve the leading prefix through the first human message.
- [ ] Compact only the region after that prefix.
- [ ] Keep the existing tail exemption.
- [ ] Run the compaction suite.

### Task 4.2: Wire the pin for all four hunting roles

**Files:**
- Modify: `src/polymerhus/app/llm/compaction.py`
- Modify: `src/polymerhus/attack/hunting/llm.py`
- Modify: `src/polymerhus/attack/hunting/pod/agents.py`
- Test: `tests/attack/test_hunting_compaction.py`
- Test: `tests/attack/pod/test_compaction_seam.py`

- [ ] Write a failing test that the hunter middleware enables the pin.
- [ ] Write a failing test that the modeller middleware enables the pin.
- [ ] Write a failing test that the pod runner and triager middleware enable the pin.
- [ ] Add the role set that enables the pin.
- [ ] Wire the flag through the role middleware builder.
- [ ] Run the hunting and pod compaction suites.

### Task 4.3: Merge the hunter overview and loop into one pinned message

**Files:**
- Modify: `src/polymerhus/attack/hunting/hunting_agent.py`
- Test: `tests/attack/test_hunting_agent.py`

- [ ] Write a failing test that the hunter sends one first human message.
- [ ] Assert the message carries the application overview and the loop grounding.
- [ ] Merge the overview and first-step content.
- [ ] Remove the coupling lead.
- [ ] Run the hunter harness suite.

## Phase 5: Threat modeller analysis and fixes

### Task 5.1: Write the modeller context analysis

**Files:**
- Create: `docs/experiments/hunt-enhancement/THREAT-MODELLER-CONTEXT-ANALYSIS.md`
- Reuse: `CONTEXT-OCCUPANCY-ANALYSIS.md`
- Reuse: `CONTEXT-DUPLICATION-FORMAL-ANALYSIS.md`

- [ ] Record the first-call components: 23,297 system chars, 36,820 tool chars, 5,015 human chars, 17,076 input tokens, 14,336 cache read, 2,740 uncached.
- [ ] Record the lifecycle: 163 calls, 215,777 mean input, 96.1% cache share, 35.17M total input.
- [ ] List the five-state and gate duplications across the prompt, tool description, `GATE_SECTIONS`, `ModelSections`, and the store validator.
- [ ] List the reference-field and completion-rule duplications.
- [ ] List the exact 5xx paragraph shared with the hunter.
- [ ] List the missing bound tools in the prompt.
- [ ] Quantify the first-call and lifecycle effect of each proposed cut.
- [ ] Separate cached-text removal from uncached-text removal.
- [ ] State that removing cached fixed text can raise the miss share while lowering occupancy.
- [ ] State the estimated absolute uncached reduction and the miss-share range.

### Task 5.2: Fix the modeller contract

**Files:**
- Modify: `src/polymerhus/attack/hunting/prompts/threat-modeller.md`
- Modify: `src/polymerhus/attack/hunting/threat_modeller.py`
- Modify: `src/polymerhus/attack/hunting/threat_modeller_tools.py`
- Test: `tests/attack/test_threat_modeller_prompt.py`
- Test: `tests/attack/test_threat_modeller.py`

- [ ] Write a failing test that the prompt state table matches `ModelState` and `GATE_SECTIONS`.
- [ ] Write a failing test that the prompt reference fields match `ModelSections`.
- [ ] Write a failing test that the prompt tool list matches the bound surface.
- [ ] Write a failing test that the 5xx paragraph is the shared directive.
- [ ] Generate the state and gate table from the typed model.
- [ ] Generate the reference-field table from the typed model.
- [ ] Generate the tool list from the bound surface.
- [ ] Replace the 5xx paragraph with the shared directive.
- [ ] Keep the gate reasoning method and the drop policy.
- [ ] Run the modeller suites.

## Phase 6: Pod runner and triager analysis and fixes

### Task 6.1: Write the pod context analysis

**Files:**
- Create: `docs/experiments/hunt-enhancement/POD-CONTEXT-ANALYSIS.md`
- Reuse: `CONTEXT-OCCUPANCY-ANALYSIS.md`
- Reuse: `CONTEXT-DUPLICATION-FORMAL-ANALYSIS.md`

- [ ] Record the runner first call: 9,446 system chars, 20,770 tool chars, 6,574 human chars, 8,810 input tokens, 0 cache read.
- [ ] Record the triager first call: 11,724 system chars, 19,580 tool chars, 14,318 human chars, 11,712 input tokens, 0 cache read.
- [ ] Record the lifecycle cache shares: 93.3% runner, 66.3% triager.
- [ ] List the spec-paragraph, tool-list, conciseness, memory, variant-table, and terminal-vocabulary duplications.
- [ ] Quantify the cold first-call uncached reduction for each cut.
- [ ] Quantify the post-warm occupancy reduction.
- [ ] State the miss-share caveat for cached text.

### Task 6.2: Fix the pod contracts

**Files:**
- Modify: `src/polymerhus/attack/hunting/prompts/pod-runner.md`
- Modify: `src/polymerhus/attack/hunting/prompts/pod-triager.md`
- Modify: `src/polymerhus/attack/hunting/pod/agents.py`
- Modify: `src/polymerhus/attack/hunting/pod/tools.py`
- Modify: `src/polymerhus/attack/hunting/pod/context.py`
- Test: `tests/attack/pod/test_prompts.py`
- Test: `tests/attack/pod/test_tools.py`
- Test: `tests/attack/pod/test_variant_mint.py`

- [ ] Write a failing test that each pod prompt names every bound tool.
- [ ] Write a failing test that the triager binds the read-only auth store.
- [ ] Write a failing test that the variant table matches `VARIANT_BASES`.
- [ ] Write a failing test that the terminal vocabulary matches the validator.
- [ ] Write a failing test that the conciseness directive appears once.
- [ ] Generate the tool lists from the bound surface.
- [ ] Generate the variant table from `VARIANT_BASES` and `PROCEDURE_GAP_FIELD`.
- [ ] Generate the terminal vocabulary from the typed decision model.
- [ ] Remove the duplicated conciseness text from the prompts.
- [ ] Replace the partial spec paragraph with a compact projection of the typed spec.
- [ ] Bind the read-only auth store for the triager.
- [ ] Run the pod suites.

## Phase 7: Verification and reports

### Task 7.1: Write the change report

**Files:**
- Create: `docs/experiments/hunt-enhancement/CHANGES.md`

- [ ] Record every removed or rewritten component with its before and after chars.
- [ ] Record the first-call token estimate for the hunter.
- [ ] Record the modeller and pod estimates.
- [ ] Record the cache-share interpretation and the caveat.
- [ ] Record the test results.
- [ ] Record that no trial ran.

### Task 7.2: Run the suites

- [ ] Run the focused hunter suites.
- [ ] Run the focused modeller suites.
- [ ] Run the focused pod suites.
- [ ] Run the compaction suites.
- [ ] Run the combined suite.
- [ ] Confirm zero failures.
- [ ] Confirm no new skips caused by this change.
- [ ] Run `git diff --check`.

### Task 7.3: Merge back

- [ ] Commit each phase.
- [ ] Merge `fix/hunt-context-dedup` into `hunt-enhancement-trunk`.
- [ ] Push the trunk.
- [ ] Leave the trial authorization to the operator.
