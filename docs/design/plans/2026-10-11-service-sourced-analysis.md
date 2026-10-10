# Plan: the L1-first service-sourced analysis pipeline

Status: ACTIVE PLAN.
Owner: primary agent, operator-directed.
Branch: `feat/service-sourced-analysis` (off `dev` `93d213e`).
Date: 2026-10-11.

This is the umbrella plan for the migration.
It is the source of truth for the phase order and the scope.
The formal specification is produced in phase 2 and supersedes this plan's design summary where they differ.

## 1. Goal

Retire the L0-chunk stream as the analysis driver.
Make the bootstrapped L1 Service the first-class pipeline unit.
Post-recon, analyse ONE Service at a time through a decomposed reasoning workflow, one LLM turn per sub-problem with verbatim-injected inputs.
Give each analysis proposer agent hunting-style episodic memory (the `notes` tool).
Land the new pipeline behind a settings flag; the streamed path stays the default until the new pipeline proves out on a full eval.

## 2. Operator-ratified decisions (this session)

1. Driver: the new pipeline runs as the ANALYSIS module on the module runtime, triggered when recon drains; it reads the settled L0 and the bootstrapped L1 from the graph.
2. Streamed path: the L0-chunk streamed analysis stays behind its existing `streaming_analysis` settings flag and remains the default until the new pipeline proves out. The new pipeline is a new selectable mode.
3. L0 attachment: a global Assigner pass runs FIRST over the settled L0 surface and attaches Endpoints to Services via `AGGREGATES`; each per-Service iteration then reads its aggregated slice.
4. Up/down classing: promote the Service to the first-class pipeline unit; demote the L0 surface to lower-class evidence reachable only through the hinge edges (`AGGREGATES`, `SURFACES_AT`, `EVIDENCED_BY`).

## 3. Definition of done

- The new mode runs end to end: recon drain triggers the analysis module, which runs the global assign pass then the per-Service pipeline, writing L1 through the sole-writer only.
- Each proposer agent runs a decomposed workflow: a small fixed set of distinct sub-problems, data dependencies mapped, one LLM turn per sub-problem with verbatim-injected inputs.
- Each proposer agent has episodic memory via the shared `notes` tool with the identical bounding and usage pattern as hunting.
- The streamed path is unbroken and remains the default; the new mode is selected by a settings flag.
- Green unit + integration tests for the new path.
- Docs pass complete: ADRs, `CONTEXT.md` glossaries, `domain-model.md`, and the spec all updated in the same change.
- Merged into `dev` and pushed.
- A full eval runs on the new stack and the L1 surface well-formedness is assessed.

## 4. Workflow phases (strict order)

### Phase 0 - Grounding (DONE)

Read the docs bank and the code: the analysis module, the recon control planes, the hunting memory system, and the L1 model.
Produced the current-state map and the four operator-ratified decisions above.

### Phase 1 - Grill (grill-with-docs)

Dispatch a Socratic subagent that generates the design questions.
Reply to them and progressively record the design decisions as an ADR plus glossary updates.
Resolve, at minimum: the per-proposer sub-problem decomposition; the data-dependency map between sub-problems; the verbatim-injection contract per turn; the global-assign-pass shape; the per-Service loop and its failure semantics; the episodic-memory scope, paths, keying, bounding, and end-of-workflow usage specification; the settings-flag surface.

### Phase 2 - Spec (to-spec)

Write the formal specification from the resolved decisions.

### Phase 3 - Tickets (to-tickets)

Produce a few coarse tickets, map their blocking edges, and address them sequentially.

### Phase 4 - TDD (subagent-driven-development + tdd)

Implement each ticket test-first in this worktree.
Per task: dispatch an implementer subagent, then a spec reviewer, then a code-quality reviewer.

### Phase 5 - Docs pass, merge, push

Complete the decision-record gate, merge into `dev`, and push.

### Phase 6 - Full eval and L1 assessment

Run a full eval on the new stack and assess the well-formedness of the created L1 surface.

## 5. Scope boundaries

In scope:
The new analysis pipeline mode, the proposer reasoning workflows, the episodic-memory integration, the global assign pass, the per-Service loop, the settings flag, tests, and the docs.

Out of scope unless the grill escalates them:
The A.2 service decomposition (SPLIT op) beyond what the per-Service loop strictly needs; the anti-cluttering A.2 pass; the L0 recon pipeline itself; the hunting and exploit modules.

## 6. Open points to resolve in the grill

- The exact sub-problem decomposition per proposer agent and their dependency order.
- Whether the global assign pass reuses the existing Assigner body over the whole settled L0 or a new whole-graph read.
- The per-Service iteration axis (Service x proposer, or one fused pass per Service).
- The episodic-memory store path, record schema, note kinds, and read-back contract.
- The settings-flag key and its default.
