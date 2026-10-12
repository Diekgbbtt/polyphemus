# Plan: batched L1-unit-first analysis pipeline

_Status: accepted for implementation 2026-10-12, branch `feat/analysis-unit-enrichment`._
_Scope: replace the `service_sourced` behaviour. Keep the mode value `service_sourced`; the new prompt files are its prompts._

## 1. Objective

Rebuild the three analysis proposers so each reasons L1-unit-first, discovers its own evidence, and is never write-restricted to its own unit.
Keep the load-bearing analysis principles in the system prompts, re-parametrised for L1 units.
Run the comfyui trial again with a 4,000,000 capped-token budget.

## 2. The diagnosis (why the per-Service assign filter is a symptom)

The per-Service assign filter (`assigner.py:1070`, `existing_slugs=frozenset({slug})`) is one visible face of a lower-layer design smell.
Every proposer was fed the WHOLE mapped L0 surface in its first HumanMessage (`assigner.py:1062` builds one `Chunk` with ALL `assets`; `_slice_repr(l0_slice)` renders it).
The unit then had to drop every surface item whose best owner was a different Service, because the write filter admitted only the unit's own slug.
One Service proposed 25 aggregates and kept 0, so placement fell below v1.
The root cause is the pre-fed surface plus the per-unit write scope, not the filter alone.

## 3. The design change

The unit (a Service or a System, with its identifier and description) is the reasoning anchor, and the ONLY thing fed as the unit context.
The proposer discovers its own relevant surface by querying `graph_view` and the HTTP-history tools, driven by the unit identifier and description.
No proposer is write-restricted to its own unit slug.
The only surviving gate is the GLOBAL inventory validation: a proposed `service_slug` must name a live Service (a hallucinated owner is still dropped).
Every proposer gets a new harvesting phase, and the phase differs per agent (section 5).
Each unit's prompt is rewritten from scratch as `*-batched-l1unit-first.md`.

### 3.1 The two unit kinds for the mechanism-typist

The mechanism-typist consumes both Services and Systems (already appended by `service_slice.build_service_slices` via `systems_fn`).
For a Service unit it puts the forward central question: given the catalog, which technical Systems could this Service rely on to offer the application service in its contract, and how is that contract implemented.
For a System unit it puts the SAME question in reverse: which Services rely on this technical overlay, and how.
Both directions are optimised for hypothesis reasoning.

### 3.2 Evidence the mechanism-typist is fed

The RDF catalog: every System `kind` (`l1_curator.SYSTEM_KINDS`) and every System-edge `rel` (`l1_curator.SYSTEM_EDGE_RELS`), already rendered by `l1_curator.vocabulary_prompt()`.
The currently bootstrapped Systems with their descriptions (`mechanism_typist._defined_systems_block`, from the live inventory).
The unit subject (identifier + kind + description), and, for a Service unit, its aggregated L0 endpoints where they exist.
These ride the HumanMessage, not the stable system prompt.

## 4. Wiring

Keep the mode value `service_sourced` and its `pass_fn`.
Add ONE variant selector, read on call, defaulting to the new behaviour: `ANALYSIS_PROMPT_VARIANT` with values `batched_l1unit_first` (default) and `legacy`.
Each role's prompt loader (`assigner._load_assigner_skill`, `mechanism_typist._load_skill`, `data_modeller._system_prompt`) resolves its file through ONE shared helper that maps `(role, variant)` to a file name.
`batched_l1unit_first` loads `prompts/<role>-batched-l1unit-first.md`; `legacy` loads the current `prompts/<role>.md` (rollback).
`proposer_turn._role_prompt` is unchanged: it calls the role loader, so the variant is selected once.
Each loader stays FAIL-CLOSED on a missing file and memoized per variant, so the system prefix is byte-stable across a run.
The current prompt files are retained for rollback.

## 5. Per-proposer churn

Each proposer has two halves: the PROMPT file (rewritten from scratch) and the CODE workflow (re-parametrised). Both change.

### 5.1 Assigner (unit = Service)

Prompt file `assigner-batched-l1unit-first.md`, rewritten from scratch.
Section-by-section treatment of the current `assigner.md`:

- Opening two lines ("Your base prompt fixes WHAT you emit...") - rewrite for the unit-first harvest.
- "## The null hypothesis is that nothing owns it" - KEEP the verbatim principle, re-parametrised: the burden of proof stays on assignment, and the harvest is discovery, not a pre-fed inventory.
- "## Work each Endpoint in four moves" - REPLACE with the L1-unit-first critical paradigm: harvest aggressively, then falsify the harvest, then assign the survivors.
- "## What the confidence numbers mean" - KEEP, re-parametrised (the calibration anchors are unchanged; the evidence now comes from the discovered harvest).
- "## Judge the surface in front of you, freshly" - REWRITE (there is no repeated streamed chunk; the unit is re-run over a discovered surface).
- "## Worked examples" - REWRITE from scratch (the current examples are spurious L0chunk-first material).
- "## The workflow you run, in order" - REWRITE for the new sub-problem chain.

Code rewiring (`assigner.py`):

- Rework `WORKFLOW` sub-problems to: `harvest_surface` (aggressive multi-string harvest over `graph_view` and `search_http_history`), `falsify_harvest` (a critical pass that tries to falsify the correctness of each harvested endpoint and drops the survivors' rejected ones), `prior_insights`, `candidate_owners`, `assign`, `closure`.
- Add `search_http_history` / `get_http_artifact` to the assigner tool set (`assigner` currently binds `graph_view` only).
- Replace the pre-fed surface: `assign_services` passes the SERVICE unit context, not the whole `assets` surface; the harvest starts from the contract-derived candidate strings.
- Replace `existing_slugs=frozenset({slug})` with the FULL live inventory set, so no per-Service write filter remains while global validation stays.

### 5.2 Mechanism-typist (unit = Service OR System)

Prompt file `technical-system-batched-l1unit-first.md`, rewritten from scratch.
Section-by-section treatment of the current `technical-system.md`:

- The opening paragraph ("Your job is to read a streamed slice of a target's observable surface...") - OBSOLETE, replaced by the unit-first framing (its analysis object changed).
- "A `System` is a **mechanism**..." - KEEP, re-parametrised.
- "## Reason by hypothesis, and verify" - KEEP the verbatim principle, re-parametrised to L1 units and to the direction-dependent central question.
- "## Judge each proposal critically" - KEEP, re-parametrised (new-vs-extend now reads the fed catalog).
- "## Output contract" - KEEP, re-parametrised for the two unit kinds.
- "## Worked examples" - REWRITE from scratch (keep the hypothesise -> verify -> type shape, drop the L0-stream framing).
- "## The workflow you run, in order" - REWRITE for the new sub-problem chain.

Code rewiring (`mechanism_typist.py`):

- Rework `WORKFLOW` sub-problems to: `orient_from_catalog` (read the RDF catalog, the bootstrapped Systems, and the unit), `harvest_surface` (discover the unit's surface via `graph_view`), `prior_insights`, `mechanism_hypotheses` (the central question, direction chosen by unit kind), `page_clusters`, `systems_extract`, `link`, `closure`.
- Feed the RDF catalog + bootstrapped Systems + the unit subject in the HumanMessage base artifacts.
- REVERT the "Read what EXISTS; never filter on a path or parameter you guessed from the contract" rule in the current `unit_surface_read` prompt: for the Service direction the typist now starts from the contract and hypothesises, then verifies.
- Bring the aggregated L0 endpoints into the Service unit's context (already available as `aggregations`).
- REMOVE the per-unit `service_slug` write scope on `link`; keep global validation.

### 5.3 Data-modeller (unit = Service)

Prompt file `data-plane-batched-l1unit-first.md`, rewritten from scratch.
Section-by-section treatment of the current `data-plane.md`:

- The opening paragraph ("Your job is to read a streamed slice of Parameter/Header/Secret surface...") - rewrite (the analysis object is now the L1 unit).
- "## Reason by hypothesis, and verify" - KEEP the verbatim principle, re-parametrised: L0 assets are no longer streamed; the survey works downward from the unit.
- "## Judge each proposal critically" - KEEP, re-parametrised.
- "## Output contract" - KEEP, re-parametrised.
- "## Worked examples" - REMOVE / REWRITE from scratch (spurious L0chunk-first material).
- "## The workflow you run, in order" - REWRITE: replace the streamed L0 asset survey with the L1-unit-first survey, and re-parametrise the downstream decision nodes and branches accordingly.

Code rewiring (`data_modeller.py`):

- Rework `WORKFLOW` sub-problems and their `inject` sources for the L1-unit-first survey.
- Re-parametrise the decision nodes and branches of the reasoning algorithm that assumed streamed L0 assets.
- REMOVE the per-unit `service_slug` write scope on `data_flows`; keep global validation.

## 6. Tools surface

The three tools (`graph_view`, `search_http_history`, `get_http_artifact`) already exist in `analysis/graph_tools.py` and are bound by `proposer_turn._turn_tools`.
`search_http_history` / `get_http_artifact` are currently bound to the data-modeller only; the assigner and the mechanism-typist need them for their harvest phases.
The review pass audits that each proposer's bound tool set matches the tools its rewritten workflow tells the model to call.

## 7. Ticket (local file)

File a local ticket for the low hunting-orchestrator cache-hit ratio.
Reference the numbers and evidence introspectable on the recent v2 eval trial (project `6c357d47-2b7e-401e-9521-d268f2902365`).
Write it under `docs/` (no tracker write, per the answer).

## 8. Task breakdown

- T0 - wiring: the variant selector + shared prompt-file helper + wire the three loaders; create the three mirror files as initial copies; ADR stub; tests.
- T1 - assigner: rewrite the prompt file; rework the workflow; remove the write filter; add the HTTP tools; tests.
- T2 - mechanism-typist: rewrite the prompt file; rework the workflow; two unit kinds; remove the write scope; tests.
- T3 - data-modeller: rewrite the prompt file; rework the workflow; remove the write scope; tests.
- T4 - adversarial review: one reviewer per proposer, checking for surviving spurious verbatims, expression quality, the workflows, and the tool surface; the implementer fixes; re-review.
- T5 - ticket: the local cache-hit ticket.
- T6 - docs pass: the ADR and the CONTEXT updates, before the commit.

Each task is dispatched to a fresh implementer subagent, followed by its adversarial review.
The tasks run sequentially, because they share the wiring, the docs, and the test files.

## 9. After the tasks

Commit the change set; merge into `dev`; jump the dev version; push; confirm the remote eval server stack is aligned as CD works; run the comfyui trial again with `analysis_mode=service_sourced` and a 4,000,000 capped-token budget.

## 10. Assumptions (call out if wrong)

1. The workflow sub-problem chains change in code, not only in prompt text.
2. The RDF catalog is `SYSTEM_KINDS` plus `SYSTEM_EDGE_RELS`; nothing new is authored.
3. "No service write filters" keeps the global inventory validation and removes only the per-unit restriction.
4. The rerun target is comfyui, the same target as the v2 trial, with the 4,000,000 cap.
5. The ticket is a local file only.
