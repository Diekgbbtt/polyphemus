# ADR: the batched L1-unit-first analysis prompt variant

*Status: accepted for implementation 2026-10-12 (branch `feat/analysis-unit-enrichment`).*
*T0 built the selection seam; T1 rewrote the assigner prompt and re-parameterised its code workflow (section "The assigner (T1)"); T2 rewrote the mechanism-typist (section "The mechanism-typist (T2)"); T3 rewrites the data-modeller.*

## Context

The v2 `service_sourced` pipeline (ADR `analysis-unit-enrichment-adr.md`) reasons from a pre-fed asset slice.
Every proposer receives the whole mapped L0 surface in its first user message.
A unit then drops every surface item whose best owner is a different Service, because the write filter admits only the unit's own slug.
One Service proposed 25 aggregates and kept 0, so placement fell below v1.
The root cause is the pre-fed surface plus the per-unit write scope, not the filter alone.

The replacement behaviour reasons L1-unit-first: the unit (a Service or a System) is the only context, and the proposer discovers its own surface through `graph_view` and the HTTP-history tools.
That behaviour needs three NEW prompt files.
The selection must be reversible, because the current prompt files are the only tested arrangement.

## Decision

1. **Keep the `service_sourced` mode value.** No new analysis mode is added; the mode selects the pipeline, not the prompt arrangement.
2. **Add `ANALYSIS_PROMPT_VARIANT`, defaulting to `batched_l1unit_first`.**
   The two values are `batched_l1unit_first` and `legacy`.
   The selector is read on call, never at import (CODING_STANDARD section 6).
   An absent value is the default; an unknown value logs a warning and coerces to the default.
3. **One shared helper owns the role-to-file map.** `analysis/prompt_variant.py` exposes `resolve_prompt_variant()` and `prompt_path(role_id, variant=None)`.
   `batched_l1unit_first` selects `<base>-batched-l1unit-first.md`; `legacy` selects `<base>.md`.
   The module imports none of the three role modules, so it stays a leaf.
4. **The three loaders resolve through the helper and memoize per variant.**
   `assigner._load_assigner_skill`, `mechanism_typist._load_skill`, and `data_modeller._load_skill` keep their FAIL-CLOSED read (a missing file raises) and their per-variant memo, so the system prefix stays byte-identical across a run.
5. **The original files are the rollback.** `legacy` reproduces the current prompts byte-for-byte.

## The assigner (T1)

T1 rewrites the assigner's HOW prompt (`assigner-batched-l1unit-first.md`) and re-parameterises its code workflow.

6. **The workflow is harvest, falsify, assign.** The assigner's sub-problem chain is `harvest_surface` (aggressively query `graph_view` and `search_http_history` from contract-derived candidate strings), `falsify_harvest` (try to throw each harvested Endpoint out against the contract), `prior_insights`, `candidate_owners` (the differential over the SURVIVORS), `assign`, `closure`.
7. **The settled surface is no longer pre-fed.** `assign` seeds the Service UNIT context (the slug, its `contract`, and the Service's OWN already-aggregated endpoints) plus the inventory; it no longer renders the whole admitted surface into a prompt. The full admitted set is still built from the chunk for the deterministic gates (`shape_proposal`): only the PROMPT feed is removed, never the validation set.
8. **No per-Service write filter.** `assign_services` judges each Service with the FULL live inventory (`existing_slugs=all_slugs`), so a Service may name ANY live Service as owner. The GLOBAL validation gate (`drop_out_of_inventory`) is unchanged: a slug that is not a live Service is still dropped.
9. **The HTTP-history pair is bound for every harvesting proposer.** `search_http_history` / `get_http_artifact` join `graph_view` on every assigner (and, for T2, mechanism-typist) turn, so the bound tool set matches the tools the rewritten workflow tells the model to call and stays constant across a run (the cache rule).

## The mechanism-typist (T2)

T2 rewrites the mechanism-typist's HOW prompt (`technical-system-batched-l1unit-first.md`) and re-parameterises its code workflow.

10. **The analysis object is the L1 UNIT, and the question has two directions.** The typist no longer reads "a streamed slice of a target's observable surface". Its unit is a Service OR a System (`service_slice.build_service_slices` appends both). A Service unit asks the CENTRAL question FORWARD: given the catalog, which technical Systems could this Service rely on to offer the service in its contract, and how is that contract implemented; which relied-upon Systems are not yet mapped. A System unit asks the SAME question in REVERSE: which Services rely on this overlay, and how. The unit kind selects the direction; the unit block states it.
11. **The workflow is the unit-first chain.** `orient_from_catalog` (read the RDF catalog, the bootstrapped Systems, and the unit; state the mechanism landscape) -> `harvest_surface` (discover the unit's surface through `graph_view` and the bound HTTP-history pair) -> `prior_insights` -> `mechanism_hypotheses` (the direction-dependent central question, with the fail-closed halt preserved) -> `page_clusters` -> `systems_extract` -> `link` -> `closure`. Every turn speaks the ONE `AnalysisTurn` envelope.
12. **The catalog, the bootstrapped Systems, and the unit ride the HumanMessage.** The base artifacts are the `unit` block (identifier, kind, description - the `service_contract` for a Service, the System `description` for a System - plus the Service's aggregated L0 endpoints), the `inventory` (the bootstrapped Systems with their descriptions, plus the live Service list), the `vocabulary` (every System `kind` and System-edge `rel`, via `l1_curator.vocabulary_prompt()`), the `observations`, and the linking `candidates`. None moves into the stable system prompt.
13. **The "read what exists; never filter on a path you guessed" rule is REVERTED for this role.** The typist now starts FROM the contract and hypothesises, then VERIFIES against the graph and the HTTP history. The old `unit_surface_read` turn is gone, replaced by `harvest_surface`.
14. **No per-unit `service_slug` write scope on `link`.** A Service unit may link a System to ANY live Service it genuinely overlays; a System unit may link to any rider. The `link` context names the full live Service inventory and marks PRIMARY a PRIORITY, never a restriction. The only surviving gate is the curator's global validation (a `rel` or `kind` outside the catalog is dropped) - a slug that is not a live Service is rejected by the write layer, never scoped by this role.

## Consequences

- The three new files start as verbatim copies, so the seam is testable before T1-T3 rewrite the content.
  A copy is not a behaviour change; it is the seam's placeholder.
- The default flips behaviour without a settings change.
  The rollback is one env var, `ANALYSIS_PROMPT_VARIANT=legacy`.
- The per-variant memo means a single process can serve both variants in tests without cross-contamination.
- Deleting the `legacy` files would break the rollback; they are retained until a measured comparison retires them.
- The variant selector is separate from `ASSIGNER_PROMPT_CONFIG` and `DATA_MODELLER_PROMPT_CONFIG`, which select the HOW-arm within a file, not the file.
- T1 removes the measured keep-0 defect: a Service no longer drops every proposal whose owner is another Service, because the write filter is gone while the global validation gate stays.

## Superseded

- `analysis-unit-enrichment-adr.md` item 4 (`existing_slugs={slug}`, the per-Service write scope) is superseded by decision 8: the write filter is removed; only global inventory validation remains.
- The assigner's v2 `surface_scan -> prior_insights -> candidate_owners -> assign -> closure` chain (and its pre-fed surface source) is superseded by decision 6/7.
- The mechanism-typist's v2 `unit_surface_read -> prior_insights -> mechanism_hypotheses -> page_clusters -> systems_extract -> link -> closure` chain (ADR D46) and its `unit_surface_read` "no asset-name assumption" rule are superseded by decisions 10-14: `unit_surface_read` is replaced by `orient_from_catalog` + `harvest_surface`, and the "read what exists" discipline is reverted to hypothesis-then-verify for this role.
- The pre-fed surface / per-unit write-scope framing of the v2 service-sourced pipeline (ADR `analysis-unit-enrichment-adr.md`) is superseded for this role by the unit-first feed and the removed `link` scope.
