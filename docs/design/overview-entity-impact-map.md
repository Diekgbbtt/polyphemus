# The structured Overview entity - impact map

Status: W1.2 complete, 2026-10-16; Q4 model refined 2026-10-17 after operator feedback (dedicated Overview message for four agents).
This map covers the W1 change: replace the free-text `## Overview` skeleton attribute with the structured Overview entity.
Decisions come from the operator's answers in `PLAN.md` ("Ontology decisions"); the durable decision record lands in `docs/design/application-overview-entity-adr.md` (W1.5).
The implementation follows TDD in the order of section 7.

## 1. The entity

- `domain` - the target's stable canonical domain (for a benchmark target, its identity, for example `wordpress`).
  Never the per-run synthetic Host; the minting inconsistency is recorded as lack L-1 in `PLAN.md`.
- `description` - the generalised description of the core offered features.
- `journeys` - at least 2 entries, each `{name: str, steps: [str]}` with 3 or more steps.
  Every step names at least one concrete surface part (route, form, menu entry, page navigation) and the activated component(s) by their KB identity.
- Budget - the whole content is at most 250 words, enforced at the creator, the critic, and the validator.
- Storage - `settings.application_overview` as a JSON object; not a graph node; no new label.
- Legacy - an old free-text Overview maps to `{domain: "", description: <prose>, journeys: []}`.

## 2. Artifact and data flow

```
creator (tools/bootstrap/prompts/data-dep-l1.md)
  -> operator_kb.md    ## Overview   (fenced YAML block; the parse source)
  -> l1-surface.yaml   overview:     (top-level mirror of the same fields)

validator (tools/bootstrap/validate_data_dependencies.py)
  -> parses the KB through the platform parse functions (no drift possible)
  -> cross-checks l1-surface.yaml overview == operator_kb.md overview

delivery (existing, unchanged): operator_kb.md -> POST .../data-dependencies/l1
  -> repository.write_project_l1 -> scaffold.scaffold_project
     -> parse_overview (structured) -> settings.application_overview (JSONB)
     -> shells_to_batch -> l1_curate     (units only; the Overview never enters the graph)

consumers (Q4, the four item-consuming agents), each turn heads with a
DEDICATED Overview-only HumanMessage chained to the item message(s) that follow:
  assigner          [Overview msg] -> [inventory + slice + TASK]         (per chunk)
  mechanism typist  [Overview msg] -> [reflection] -> (same thread) extraction + linking
  hunt orchestrator [Overview msg] -> [hypothesise/gate turn]            (once per run thread)
  hunter            [Overview msg] -> [grounding + tool surface + state + protocol] (per hunt)

plumbing: read_l1_inventory -> application_overview (normalized dict)
  read_application_overview (settings-only, cheap; used by the hunting sites)
  overview.overview_message (clean render + shared intro; the entity's single home)
```

## 3. Touchpoint register

### 3.1 tools/bootstrap (contract, prompts, validator)

- `DATA-DEPENDENCIES.md` section 3.1 - replace the prose `## Overview` spec with the fenced-YAML block spec: fields, journeys, budget, example, legacy note. CHANGE.
- `DATA-DEPENDENCIES.md` section 3.2 - add the top-level `overview:` block to the RDF spec plus the cross-file equality rule. CHANGE.
- `prompts/data-dep-l1.md` - authoring instructions for the structured block; self-check duties (budget count, journey grounding, component names resolve to KB units). CHANGE.
- `prompts/data-dep-critic.md` - new Overview criteria: fields present, budget, journey grounding against `surface-map.md`, component references resolve, cross-file equality. CHANGE.
- `prompts/data-dep-authn.md` - unaffected (the auth phase carries no Overview content). VERIFIED, NO CHANGE.
- `validate_data_dependencies.py` - `check_operator_kb` gains the Overview structure and budget checks; `check_l1_surface` gains the cross-file equality check. CHANGE.
- `assessment/` - NEW: the extensive quality-assessment framework (W1.4).
- `README.md` - mention the Overview requirements and the assessment dir. CHANGE (small).

### 3.2 The four item-consuming agents (the refined Q4 model)

Rule (operator feedback 2026-10-17): each of the four agents sends a dedicated HumanMessage containing ONLY the Overview at the head of its turn, cohesively coupled to the following item-feeding message(s) by specific introductory verbatims and chaining between the messages.
This supersedes the earlier "prepend the Overview at every inventory dump" reading.

- `src/polymerhus/analysis/overview.py` - NEW module, the entity's single home: `empty_overview`, `normalize_overview`, `overview_is_empty`, `OVERVIEW_WORD_BUDGET` + `overview_word_count` (the one budget rule), `overview_message(value)` (clean render + shared intro verbatim; empty when no Overview exists). `pod.py`'s `overview_block` is DELETED (no consumers).
- `l1_inventory.py` - CHANGE: `application_overview` normalizes to the dict shape; NEW `read_application_overview(project_id, settings_fn=None)` - a cheap settings-only read for the hunting sites (no graph read), fail-open.
- `assigner.py` - CHANGE: `_user_prompt` stops embedding the Overview; the assign turn sends `[HumanMessage(overview_message), HumanMessage(items)]` where the item message (inventory + slice + TASK) opens with a chaining verbatim referring to the Overview above. Absent Overview -> today's single-message shape with no chaining verbatim.
- `mechanism_typist.py` - CHANGE: call 1 (reflection) sends `[HumanMessage(overview_message), HumanMessage(reflection)]` with the chaining verbatim; calls 2-3 continue the same per-chunk thread unchanged.
- `hunting_agent.py` - CHANGE: `build_hunting_agent` reads the Overview once per dispatch (`read_application_overview(project_id)`, fail-open) and the first step sends `[HumanMessage(overview_message), HumanMessage(_compose_first_step(..., chained=True))]`; without an Overview, the single first-step message keeps its current shape.
- `hunt_orchestrator.py` + `llm.py` + `actors.py` - CHANGE: `GateInput` gains `overview: str = ""` (the pre-rendered dedicated message content, harness-owned, deterministic); the hypothesise node builds it from `read_application_overview`; `_compose_gate_prompt(inp, chained=...)` opens with the chaining verbatim when the Overview message accompanies it; `HuntOrchestratorActor` emits the Overview message ONCE per run thread (actor flag), immediately before the first gate turn; `build_gate_reason_fn` (the standalone seam) prepends it the same way.
- `curation.py` / `sweep.py` - NO CHANGE: housekeeping passes (dedupe, ownership sweep) do not reason over the application surface; the Overview message would be pure noise there.

### 3.3 Parse, persist, surface

- `scaffold.py` - `parse_overview` returns the normalized dict (fenced YAML; legacy prose maps to `description`; malformed stays fail-open like the rest of the scaffold). `scaffold_project` persists the normalized dict with all three keys always present (see JSONB note in section 6). CHANGE.
- `bootstrap.py` - the in-system bootstrap message is the creation pass (no Overview exists yet) and the mechanism is on the retirement track. NO CHANGE.
- `l1_curator.py` / `l1_types.py` - the Overview is not a graph unit; no vocabulary or label change. VERIFIED.
- `CONTEXT.md` - the "Application Overview" glossary entry moves to the structured model. CHANGE.

### 3.4 project_management / API / eval harness

- `repository.write_project_l1` - calls `scaffold_project`; persistence rides along. VERIFIED, NO CHANGE.
- `project_management/api.py` - endpoints unchanged. VERIFIED.
- `eval/orchestrator/*` - the harness uploads `operator_kb.md`; no Overview-specific code; `eval/scaffold.py` CLI delegates to the platform parser and calls `scaffold_project` on write. VERIFIED, NO CHANGE.
- `eval/data/webexploitbench/<target>/*` - regenerated from scratch in W2 (Q7); W1 leaves the committed set unchanged.

### 3.5 Other sites checked (Q4 completeness)

- `attack/hunting/fault_source.py` - reads the inventory for deterministic kind-qualified unit ids; not a prompt dump. NO CHANGE.
- Frontend / settings API - the JSONB value passes through; nothing renders it. NO CHANGE.
- `bootstrap.py:893` `_inventory_block` use - creation pass, covered above. NO CHANGE.

### 3.6 tests

- `tests/analysis/test_operator_overview.py` - rewrite for the structured model: parse (structured, legacy, absent, malformed), persistence, inventory normalization, the `overview_message` render and the word-count rule; NEW assigner and typist two-message framing tests.
- `tests/analysis/test_l1_inventory.py` - the default-shape assertion (`application_overview: ""`) updates to the normalized empty shape. CHANGE.
- `tests/attack/test_hunting_llm.py` - add gate-message framing coverage (Overview message + chained gate prompt; absent Overview -> single message). CHANGE.
- `tests/attack/test_hunting_agent.py` - add first-step framing coverage (Overview message + chained first step). CHANGE.
- Hunting orchestrator actor test (wherever `HuntOrchestratorActor._on_message` is exercised) - the Overview message is emitted once per thread. CHANGE.
- `tests/test_bootstrap_validator.py` - NEW: the validator's Overview checks (fenced parse, fields, journey and step counts, word budget).
  The file sits flat like the other tool-script tests; the validator is loaded by path (`tools/` is not a package).
- `tests/integration/test_bootstrap_reasoned_contracts.py` - the C22 inventory-block test is unaffected; re-run to confirm. VERIFY.

### 3.7 docs

- `docs/design/application-overview-entity-adr.md` - NEW (W1.5): the decision record (Q1-Q7, alternatives, consequences).
- `docs/design/overview-entity-impact-map.md` - this file.
- `docs/design/eval-data-dependency-placement-decisions.md` - add a pointer that the validator's canonical home is now `tools/bootstrap/`. CHANGE (small).
- `tools/bootstrap/README.md` - covered in 3.1.

### 3.8 Repo safety (found along the way)

- `.gitignore` - the W1 branch was missing the staging-root and auth ignore rules the staging layout requires (`eval/data-dependencies/`, `eval/kbs/*/auth/`).
  Both directories hold SECRET-BEARING artifacts; added. DONE (this change).

## 4. Budget enforcement points (Q3)

1. Creator (`data-dep-l1.md`) - write within 250 words and self-count before returning.
2. Critic (`data-dep-critic.md`) - count independently; an over-budget Overview fails review.
3. Validator - deterministic count over the parsed content; above 250 is an error.
   The validator imports the platform parse functions, so it counts exactly what the platform later persists.

## 5. Deliberate non-changes

- No graph label, no `l1_curator` vocabulary change, no RDF insert path (the `l1-surface.yaml` block is forward-carry).
- No frontend or settings-API change.
- Curation and sweep housekeeping passes (the refined Q4 model).
- The in-system bootstrap mechanism (creation pass; retirement track).
- `fault_source` unit-id enumeration.

## 6. Notes and risks

- JSONB deep merge: `save_settings` merges nested objects; persist all three keys on every write so an older value can never survive under a missing key.
- Legacy split: the platform parse tolerates legacy prose (fail-open, old projects); the validator requires the new structure (a build gate). The 8 committed KBs fail the new validation until the W2 regeneration; the validator is not wired into CI today (verified), so nothing breaks in between.
- The fenced block must not disturb the KB section regexes (`parse_kb` runs over `## Services` / `## Systems` / `## Roles`; the Overview parser reads its own section). Verify with a full-KB fixture in TDD.
- Words are counted over the rendered plain text (domain + description + journey names + steps), whitespace tokenization; pinned by tests.
- The orchestrator thread is monotonic across all faults; the Overview message is emitted once (actor flag), never re-stacked per fault (the #187 byte-identical-stacking defect precedent).
- Sessions reset per chunk for the analyser roles and per hunt for the hunter, so their Overview message cannot accumulate; the orchestrator flag is the only dedupe state.
- L-1 (minted domain consistency) stays a W2.1 dependency-audit item; it does not block W1.

## 7. TDD order (W1.3)

1. `parse_overview`: structured block -> dict; legacy -> `description`; absent -> empty; malformed -> fail-open. Red first in `tests/analysis/test_operator_overview.py`.
2. `scaffold_project`: persists the normalized dict with all keys; fail-open path unchanged.
3. `read_l1_inventory` / `read_application_overview`: normalization and defaults.
4. `overview.overview_message`: render and dedicated-message content.
5. Framing tests in order: assigner, mechanism typist, hunter first step, hunt orchestrator gate (composer + actor once-per-thread + standalone seam).
6. Validator: new checks + `tests/test_bootstrap_validator.py`.
7. Contract and prompt text updates (documentation of the already-pinned behavior).
