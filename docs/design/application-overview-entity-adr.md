# ADR: the Application Overview is a structured entity, delivered to each consuming agent as a dedicated message

Status: accepted (2026-10-17).
Amends: `docs/design/operator-kb-overview-attribute-adr.md` (the Overview stays a skeleton attribute; its value shape and its delivery change).
Related: `docs/design/overview-entity-impact-map.md` (the impact map and the full site inventory), `docs/design/l0-l1-pipeline-split-adr.md` (its item 7, `pod.overview_block` prepending, is superseded by the dedicated message).

## Context

The W-d Overview made the `## Overview` paragraph a skeleton attribute: parsed as prose, persisted to `settings.application_overview`, prepended inline to a Service's reasoning.
Two problems surfaced in use:

1. The framing competed with the item content.
   The paragraph was folded into the head of a larger human message (`APPLICATION OVERVIEW: ...` followed by the inventory, the slice, and the task), so it read as formatting noise and was easy to skim past.
2. Nothing quality-gated it.
   Prose has no stable identity, no canonical structure, and no countable size: a stale or host-named or one-line Overview passed exactly like a good one.

## Decision

1. **Value shape.**
   The Overview is `{"domain": str, "description": str, "journeys": [{"name": str, "steps": [str, ...]}]}`.
   `analysis/overview.py` is its single home (empty shape, `normalize_overview`, `overview_is_empty`, `overview_word_count` + `OVERVIEW_WORD_BUDGET`, `overview_message`); every read path normalizes, so a legacy value never crashes a consumer.
2. **KB form (Q5).**
   A fenced ```yaml block under `## Overview`, read with `yaml.safe_load` - the least complex, most structurally reliable parse.
   Legacy prose stays accepted at runtime (it maps to `description`, fail-open); it fails the validator, which is the strict build gate.
3. **Persistence.**
   `scaffold_project` writes `settings.application_overview` with ALL THREE keys on every write, so the settings store's JSONB deep merge can never let an older value survive under a missing key.
4. **Delivery (Q4).**
   The four item-consuming agents - Assigner, TechnicalSystem mechanism-typist, hunt orchestrator, hunter - each send a DEDICATED HumanMessage that contains ONLY the Overview, at the head of their turn.
   The message is coupled to the item messages that follow by explicit verbatims: one shared intro on the Overview message (`overview_message`), and one chaining opener per site (assigner, mechanism-typist, hunter first step, orchestrator gate).
   Curation and sweep are housekeeping passes and receive no Overview.
   The orchestrator emits it once per run thread (the thread is monotonic across all faults and pairs; a per-turn re-add would restack a byte-identical message - the #187 stacking defect).
5. **Budget (Q3).**
   The whole Overview - domain, description, journey names, steps - stays under 250 words over the rendered plain text (whitespace tokenisation).
   ONE rule serves all three enforcement sites: the creator's self-check, the critic's criteria, and the deterministic validator (`check_overview`).
6. **Gate.**
   `tools/bootstrap/validate_data_dependencies.py::check_overview` is strict: non-empty `domain` (the target's stable identity, never the per-run host), non-empty `description`, at least 2 journeys of at least 3 steps each, and the word budget.
   The runtime parser stays fail-open by design; the validator is the build-time gate.

Journeys name specific surface parts (endpoints, forms, menu entries, page navigations) and, where they exercise an existing L1 component, that component by its KB identity (a Service `business_function_slug`, a System `kind`).

## Consequences

- The framing is machine-legible and stable: `domain` identifies the target across runs.
- The item messages stay clean: the Overview rides its own message and is referenced, not buried.
- The budget is enforceable at all three sites because it counts the SAME rendered text.
- The eight committed `eval/data/webexploitbench/*/operator_kb.md` carry legacy prose Overviews and FAIL the new validator until the W2 bootstrap regeneration replaces them; the validator is not CI-wired, so nothing breaks in between.
- The in-system bootstrap (`analysis/prompts/bootstrapper.md`) authors the structured form; its message shape at creation time is unchanged (no Overview exists when it runs), and its mechanism stays on the retirement track.
- `pod.overview_block` is deleted; all deliveries go through `overview_message`.
- The hunter and orchestrator read the Overview settings-only (`read_application_overview`), so no gate turn pays for a full inventory read.
- Known lack L-1: the eval front mints the Host per run (`t-<short>.target`); host minting must become consistent per target and must never leak into `domain` - handled in the W2 dependency audit.
