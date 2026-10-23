# Staged triage decision tree: implementation plan

**Branch:** `feat/staged-triage-decision-tree`.
**Base:** `fix/context-lifecycle-followup` (`8aca8552`), which carries the typed-procedure context dedup and the pod compaction wiring.
**Worktree:** `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/staged-triage`.
**Date:** 2026-10-23.
**Authority:** the measured trial `white-jotter-1-20261022T030303-1618c524` and the staged claim in `docs/experiments/unit-threat-model-eval-2026-10-20/POD-TRIAGER-STAGED-FIRST-CALL-CLAIM.md` on the docs branch.

## Objective

Replace the single full triager turn with a staged decision tree.
The confirmed-symptom path becomes one compact call with no tools.
The full skill, the typed procedure, the variants, and the KB on demand are loaded only for the bounded variant stage.
The terminal verdict remains a triager judgment, but on a compact context.

The change must keep the binary terminal invariant, the six-value terminal vocabulary, the variant record shape, the pod-memory pure-log invariant, and the existing contract tier.

## Seams under test

These are the public seams. Tests are written only against them.

1. `arun_pod(spec, ..., triager_fn=None, triager_stages=None)` - the pod entry. The new `triager_stages` injection is the staged test seam. An injected `triager_fn` keeps the old single-turn seam.
2. `make_staged_triager(stages)` - the pure orchestration of the decision order. Tested through `arun_pod` with four fake stage callables.
3. `compose_triage_delta`, `compose_divergence_delta`, `compose_triager_delta`, `compose_terminal_delta` - the stage-specific context projections, tested as pure functions and through the stage callables.
4. `default_triage_fn`, `default_divergence_fn`, `default_triager_fn`, `default_terminal_fn` - the production stage turns, tested hermetically with a bound `bind_pod_session`, a fake model factory, and a spy `stateful_turn` where the tool surface matters.
5. `build_pod_graph(...)` - the node wiring and the `decide_router`. Tested through `arun_pod`.
6. `_resolve_variant_decision` - the off-spec guard and the variant basis resolution. Tested through `arun_pod` with scripted decisions.

## Design

### The decision order

1. **Stage A: failure and symptom confirmation.**
   `default_triage_fn` reads the spec's verification symptoms, target identity, assumptions, the Runner's verbatim note, and the latest observation.
   It returns `TriageDecision`: `runner_failed`, `symptom_confirmed`, `clean`, `note`.
   No tools. No KB. No skill. No graph view. No variants. No typed procedure.
   - `runner_failed` -> a variant decision with `runner_failed=True`; the graph mints the `runner-failure` basis (current behavior).
   - `symptom_confirmed` -> a terminal decision `successful` / `symptom-confirmed` / `clean=True`; the deterministic `_export` writes the `PodExport`.
   - otherwise -> Stage B.

2. **Stage B: divergence.**
   `default_divergence_fn` reads the note, the spec's typed `SkillProcedure` excerpt, the executed probe trail, and the latest observation.
   It returns `DivergenceDecision`: `runner_diverged`, `note`.
   No tools.
   - `runner_diverged` -> a variant decision with `runner_diverged=True`; the graph mints the `runner-divergence` basis (current behavior).
   - otherwise -> Stage C or Stage D.

3. **Stage C: bounded variant mining.**
   Called only when the current spec carries at least one populated `SkillProcedure` attribute.
   `default_triager_fn` keeps the full triager context: the note, the typed procedure, the variants already tried, the executed probes, the interpretations, the memory guidance, and the bound tools `note`, `query_lightrag`, `graph_view`, `load_skill`, `record_skill_lesson`.
   It returns the existing `TriagerDecision` (variant or terminal).
   The graph's `_resolve_variant_decision` resolves the basis, refuses duplicates, and mints at most one variant per decision.

4. **Stage D: terminal verdict.**
   Called only when the spec has no populated `SkillProcedure` attribute.
   `default_terminal_fn` reads the note, the verification symptoms, the latest observation, the probe trail, the variant bases, and the KB degraded flags.
   It returns `TerminalDecision`: `verdict`, `terminal_reason`, `clean`, `note`.
   No tools. No variant.
   The graph's terminal node writes the `PodExport`.

If the spec has no populated procedure, the pod still reaches a terminal; it just does not pay for the variant miner.
If the spec has a populated procedure and every populated class is covered, Stage C may use the existing `failure-mode` fallback.

### The stage deltas

- `compose_triage_delta`: the Runner's note, the verification symptoms, the target identity, the assumptions, and the latest observation (body capped). No typed procedure, no variants, no probe trail, no memory guidance, no KB.
- `compose_divergence_delta`: the triage delta plus the typed `SkillProcedure` excerpt and the executed probe lines.
- `compose_triager_delta`: unchanged, the full triager delta.
- `compose_terminal_delta`: the Runner's note, the verification symptoms, the latest observation, the executed probe lines, the variant bases, the recent interpretations, and the KB degraded flags. No typed procedure, no skill tools.

### The schemas and prompts

- `TriageDecision` in `agents.py`: `runner_failed`, `symptom_confirmed`, `clean`, `note`.
- `DivergenceDecision` in `agents.py`: `runner_diverged`, `note`.
- `TerminalDecision` in `agents.py`: `verdict`, `terminal_reason`, `clean`, `note`, `classification`.
- New prompts: `prompts/pod-triage.md`, `prompts/pod-divergence.md`, `prompts/pod-terminal.md`, loaded through `prompts.py` with the shared cortex.
- `prompts/pod-triager.md` stays the Stage C system prompt.

### The graph wiring

- `build_pod_graph(..., triager_stages=None)`.
- `triager_fn is None` -> `make_staged_triager(triager_stages or default stages)`; `staged_triager=True`.
- `triager_fn` injected -> the old single-turn seam; `staged_triager=False`.
- The `triager` node composes `compose_triage_delta` for the staged lane and keeps `log.triager_context` for the injected lane.
- `decide_router` is unchanged: the staged orchestrator returns `terminate` or `variant`.

### The off-spec guard

`_resolve_variant_decision` appends an `[off-spec: ...]` note when the derived variant's `verification_symptoms` differ from the base spec's.
The derived spec is recorded as its own variant, so its confirmation is not the base spec's confirmation.
The variant record shape stays four fields.

### The provider-failure and degrade contract

A stage provider failure propagates as the typed `ProviderUnavailableError`, exactly like the current triager.
Any other stage exception returns a safe `no-symptom-evidence` terminal with the degradation note, exactly like the current triager.
The stage C `default_triager_fn` keeps its current fail-open behavior.

## TDD slices

Each slice is red -> green, one seam at a time. No bulk test writing.

### Slice 0: baseline

- Run the existing pod suite. Record the one stale failure `test_tool_contract_rejects_foreign_params` (the shared store base now returns an `extra_forbidden` coded rejection instead of raising).
- Fix that test to assert the coded rejection and `calls == []`.

### Slice 1: the staged order

- Red: `test_staged_confirmed_short_circuits` through `arun_pod` with fake stages: only `assess` is called; envelope `successful` / `symptom-confirmed` / `iterations == 1`.
- Green: `triage.py` (`TriageStages`, `make_staged_triager`), `build_pod_graph`/`arun_pod` plumbing, the compact delta branch.
- Red: `test_staged_runner_failure_mints_the_recovery_basis`: only `assess`; variant basis `runner-failure`.
- Red: `test_staged_divergence_mints_the_recovery_basis`: `assess`, `diverge`; basis `runner-divergence`.
- Red: `test_staged_populated_procedure_calls_the_miner`: `assess`, `diverge`, `mine`; the variant is recorded.
- Red: `test_staged_no_populated_procedure_calls_the_terminal_not_the_miner`: `assess`, `diverge`, `terminal`; terminal envelope.
- Red: `test_staged_duplicate_basis_still_degrades`: the graph's duplicate guard still applies after the miner.
- Green: the orchestrator branches.

### Slice 2: the stage contexts

- Red: `test_triage_delta_is_compact`: it carries the note, symptoms, identity, assumptions, and observation; it excludes `## Skill procedure`, `## Variants already tried`, `## Probes executed`, and the memory guidance.
- Red: `test_divergence_delta_adds_the_typed_procedure_and_the_probes`.
- Red: `test_terminal_delta_carries_the_probe_trail_and_the_kb_flags`.
- Red: `test_triager_delta_stays_full`.
- Green: the three new context functions in `context.py`.

### Slice 3: the production stages

- Red: `test_triage_turn_binds_no_tools_and_the_compact_schema`: a spy `stateful_turn` sees `tools == ()`, `schema is TriageDecision`, `system_prompt == load_pod_triage_skill()`.
- Red: `test_divergence_turn_binds_no_tools_and_the_compact_schema`.
- Red: `test_terminal_turn_binds_no_tools_and_the_compact_schema`.
- Red: `test_stage_c_turn_keeps_the_full_tool_surface` (the existing production triager test).
- Red: `test_triage_prompt_is_shorter_and_has_no_variant_mining`.
- Red: `test_divergence_prompt_names_the_typed_procedure_and_divergence`.
- Red: `test_terminal_prompt_keeps_the_binary_vocabulary_and_the_kb_rule`.
- Red: `test_stage_prompts_carry_the_cortex`.
- Green: the schemas, the prompts, the stage functions, and the prompt loaders.
- Red: `test_staged_default_path_lands_confirmed_with_fake_models`: the production staged path end-to-end with a stage-aware fake model.
- Green: update the e2e fake model to reply per schema (`TriageDecision`, `DivergenceDecision`, `TerminalDecision`, `TriagerDecision`).

### Slice 4: the off-spec guard

- Red: `test_an_off_spec_variant_is_recorded_as_a_derived_spec`: the note contains `off-spec`; the derived variant keeps the changed symptoms; the base spec is unchanged.
- Red: `test_a_same_symptom_variant_has_no_off_spec_note`.
- Green: the `_resolve_variant_decision` note.

### Slice 5: the first-call occupancy proof

- Red: `test_stage_a_first_call_has_no_tool_descriptions`: the stage A turn binds no tools, so the first-call fixed tax loses the tool-description block.
- Red: `test_stage_a_compact_context_is_smaller_than_the_full_triager_context`: a spec with a populated procedure and two variants; the compact delta is strictly shorter.
- Red: `test_the_triage_prompt_is_shorter_than_the_triager_prompt`.
- Green: already covered by Slices 2 and 3; add the assertions.

### Slice 6: the design spec docs

- `docs/design/hunting-67-test-executor-pod-spec.md`: add the staged triage section, the stage order, the stage contexts, the schemas, the prompts, the off-spec guard, the token intent, and the test decisions.
- `docs/design/hunting-84-pod-memory-system-spec.md`: state that the stage reads use the same store and the pure-log invariant is unchanged; the interpretation record still lands once per triager node.
- `src/polymerhus/attack/hunting/CONTEXT.md`: add the staged triager terms (Stage A/B/C/D, compact triage delta, bounded variant miner, off-spec guard).
- Update the experiment report `POD-TRIAGER-STAGED-FIRST-CALL-CLAIM.md` with the implemented design and the test evidence if the file is present on this branch.

## Test matrix

| Layer | Files | What it proves |
|---|---|---|
| Unit | `tests/attack/pod/test_staged_triage.py` (new) | the decision order, the stage contexts, the stage seams, the off-spec guard |
| Unit | `tests/attack/pod/test_context.py` | the new delta projections |
| Unit | `tests/attack/pod/test_prompts.py` | the new prompts, the compact triage prompt, the retained Stage C prompt |
| Unit | `tests/attack/pod/test_react_seams.py` | the stage tool surfaces, the production stage functions |
| Unit | `tests/attack/pod/test_variant_mint.py` | the off-spec guard and the existing basis resolution |
| Integration | `tests/integration/test_test_executor_pod_contracts.py` | the external `arun_pod` contract, the staged production lane, the fixed stale foreign-param test |
| E2E | `tests/e2e/test_test_executor_pod_walkthrough.py` | the production staged walkthrough with fake models |

## Verification commands

```bash
PYTHONPATH=src /Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/fix-395-steel-timeout/.venv/bin/python -m pytest \
  tests/attack/pod tests/integration/test_test_executor_pod_contracts.py \
  tests/e2e/test_test_executor_pod_walkthrough.py -q
```

Then the broader hunting module suite:

```bash
PYTHONPATH=src .../python -m pytest tests/attack -q
```

Then a compile check:

```bash
PYTHONPATH=src .../python -m compileall -q src/polymerhus/attack/hunting/pod
```

## Non-goals

- No change to the terminal vocabulary, the variant record shape, the pod-memory store layout, or the IA-4 envelope.
- No change to the runner.
- No change to the symbolic fast path.
- No live-model measurement in this branch; the token estimate stays an estimate until the next trial.
- No merge into `dev`; the target branch is the operator's call after review.

## Known baseline failure

`tests/integration/test_test_executor_pod_contracts.py::test_tool_contract_rejects_foreign_params` fails before this work because the shared `StoreToolBase` translates `extra_forbidden` into a coded rejection instead of raising. Slice 0 updates the test to the current contract.

## Result

All slices landed on `feat/staged-triage-decision-tree`.

- The staged order and the compact short-circuits: `tests/attack/pod/test_staged_triage.py`.
- The stage context projections: `tests/attack/pod/test_context.py`.
- The stage tool surfaces: `tests/attack/pod/test_react_seams.py`.
- The stage prompts: `tests/attack/pod/test_prompts.py`.
- The off-spec guard: `tests/attack/pod/test_variant_mint.py`.
- The production staged lane: the integration pod contracts and the e2e walkthrough, with the stage-aware fake model in `tests/support/staged_triager_fake.py`.

Verification:

- `tests/attack/pod` + the pod integration contracts + the e2e walkthrough: **340 passed**.
- `tests/attack`: **959 passed**.
- `tests/integration`: 287 passed, 79 skipped, 3 failed / 3 errors in the live assigner eval (`tests/integration/test_assigner_eval_live.py`) - unrelated to the pod and pre-existing/environmental.
- `compileall` on `src/polymerhus/attack/hunting/pod`: clean.

The design spec update is in `docs/design/hunting-67-test-executor-pod-spec.md` section 8.11, `docs/design/hunting-84-pod-memory-system-spec.md` section 7, and `src/polymerhus/attack/hunting/CONTEXT.md`.

The token estimate is not re-measured on a live trial in this branch; the structural tests pin the compact first call (no tools, compact delta, shorter prompt) and the full miner call.

