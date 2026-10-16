# The structured Overview entity - impact map

Status: W1.2 complete, 2026-10-16.
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

consumers: read_l1_inventory -> application_overview (normalized dict)
  -> pod.overview_block -> prepended at every L1-inventory/graph prompt dump
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

### 3.2 src/polymerhus/analysis (parse, persist, surface, render)

- `scaffold.py` - `parse_overview` returns the normalized dict (fenced YAML; legacy prose maps to `description`; malformed stays fail-open like the rest of the scaffold). `scaffold_project` persists the normalized dict with all three keys always present (see JSONB note in section 6). CHANGE.
- `l1_inventory.py` - `application_overview` normalizes to the dict shape (legacy string and absent both map to safe defaults); `_empty()` updated. CHANGE.
- `pod.py` - `overview_block` renders the structured value cleanly (deterministic plain text, no YAML or markdown artifacts); legacy strings keep the current one-line rendering. CHANGE.
- `assigner.py` `_user_prompt` - already prepends `overview_block` + `_inventory_block`; call site unchanged, tests pin it. VERIFIED.
- `mechanism_typist.py` `_reflection_prompt` - already prepends `overview_block`; call site unchanged, tests pin it. VERIFIED.
- `curation.py` `_curation_prompt` - dumps "CURRENT L1 INVENTORY" inline without the Overview; prepend `overview_block(inv)`. CHANGE (Q4).
- `sweep.py` `stale_ownership_prompt` - dumps existing Services/Systems inline without the Overview; prepend `overview_block(inv)`. CHANGE (Q4).
- `bootstrap.py` - the in-system bootstrap message is the creation pass (no Overview exists yet) and the mechanism is on the retirement track. NO CHANGE.
- `l1_curator.py` / `l1_types.py` - the Overview is not a graph unit; no vocabulary or label change. VERIFIED.
- `CONTEXT.md` - the "Application Overview" glossary entry moves to the structured model. CHANGE.

### 3.3 project_management / API / eval harness

- `repository.write_project_l1` - calls `scaffold_project`; persistence rides along. VERIFIED, NO CHANGE.
- `project_management/api.py` - endpoints unchanged. VERIFIED.
- `eval/orchestrator/*` - the harness uploads `operator_kb.md`; no Overview-specific code; `eval/scaffold.py` CLI delegates to the platform parser and calls `scaffold_project` on write. VERIFIED, NO CHANGE.
- `eval/data/webexploitbench/<target>/*` - regenerated from scratch in W2 (Q7); W1 leaves the committed set unchanged.

### 3.4 Other dump sites checked (Q4 completeness)

- `attack/hunting/fault_source.py` - reads the inventory for deterministic kind-qualified unit ids; not a prompt dump. NO CHANGE.
- Frontend / settings API - the JSONB value passes through; nothing renders it. NO CHANGE.
- `bootstrap.py:893` `_inventory_block` use - creation pass, covered above. NO CHANGE.

### 3.5 tests

- `tests/analysis/test_operator_overview.py` - rewrite for the structured model: parse (structured, legacy, absent, malformed), persistence, inventory normalization, render; assigner and typist framing; NEW curation and sweep framing tests. CHANGE.
- `tests/analysis/test_l1_inventory.py` - the default-shape assertion (`application_overview: ""`) updates to the normalized empty shape. CHANGE.
- `tests/tools/test_bootstrap_validator.py` - NEW: the validator's Overview checks (fenced parse, fields, journey and step counts, budget, cross-file equality; legacy prose is rejected by the validator).
  `tests/tools/` is a new directory; the validator is loaded by path (`tools/` is not a package).
- `tests/integration/test_bootstrap_reasoned_contracts.py` - the C22 inventory-block test is unaffected by the render change; re-run to confirm. VERIFY.

### 3.6 docs

- `docs/design/application-overview-entity-adr.md` - NEW (W1.5): the decision record (Q1-Q7, alternatives, consequences).
- `docs/design/overview-entity-impact-map.md` - this file.
- `docs/design/eval-data-dependency-placement-decisions.md` - add a pointer that the validator's canonical home is now `tools/bootstrap/`. CHANGE (small).
- `tools/bootstrap/README.md` - covered in 3.1.

### 3.7 Repo safety (found along the way)

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
- The in-system bootstrap mechanism (creation pass; retirement track).
- `fault_source` unit-id enumeration.

## 6. Notes and risks

- JSONB deep merge: `save_settings` merges nested objects; persist all three keys on every write so an older value can never survive under a missing key.
- Legacy split: the platform parse tolerates legacy prose (fail-open, old projects); the validator requires the new structure (a build gate). The 8 committed KBs fail the new validation until the W2 regeneration; the validator is not wired into CI today (verified), so nothing breaks in between.
- The fenced block must not disturb the KB section regexes (`parse_kb` runs over `## Services` / `## Systems` / `## Roles`; the Overview parser reads its own section). Verify with a full-KB fixture in TDD.
- Words are counted over the rendered plain text (domain + description + journey names + steps), whitespace tokenization; pinned by tests.
- L-1 (minted domain consistency) stays a W2.1 dependency-audit item; it does not block W1.

## 7. TDD order (W1.3)

1. `parse_overview`: structured block -> dict; legacy -> `description`; absent -> empty; malformed -> fail-open. Red first in `tests/analysis/test_operator_overview.py`.
2. `scaffold_project`: persists the normalized dict with all keys; fail-open path unchanged.
3. `read_l1_inventory`: normalization and defaults.
4. `overview_block`: render (structured, legacy, absent).
5. Framing tests: assigner, typist, curation, sweep.
6. Validator: new checks + `tests/tools/test_bootstrap_validator.py`.
7. Contract and prompt text updates (documentation of the already-pinned behavior).
