# ADR: the batched L1-unit-first analysis prompt variant

*Status: accepted for implementation 2026-10-12 (branch `feat/analysis-unit-enrichment`).*
*T0 built the selection seam; T1 rewrote the assigner prompt and re-parameterised its code workflow (section "The assigner (T1)"); T2-T3 rewrite the other two roles.*

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
