# ADR: the batched L1-unit-first analysis prompt variant

*Status: accepted for implementation 2026-10-12 (branch `feat/analysis-unit-enrichment`).*
*This is the selection seam only (T0). The three prompt files are rewritten from scratch in T1-T3.*

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

## Consequences

- The three new files start as verbatim copies, so the seam is testable before T1-T3 rewrite the content.
  A copy is not a behaviour change; it is the seam's placeholder.
- The default flips behaviour without a settings change.
  The rollback is one env var, `ANALYSIS_PROMPT_VARIANT=legacy`.
- The per-variant memo means a single process can serve both variants in tests without cross-contamination.
- Deleting the `legacy` files would break the rollback; they are retained until a measured comparison retires them.
- The variant selector is separate from `ASSIGNER_PROMPT_CONFIG` and `DATA_MODELLER_PROMPT_CONFIG`, which select the HOW-arm within a file, not the file.

## Superseded

- Nothing. This ADR extends the v2 `service_sourced` decisions; it does not contradict them.
