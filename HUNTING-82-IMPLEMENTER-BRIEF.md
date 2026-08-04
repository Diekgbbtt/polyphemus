# Implementer Brief - #82 hunt-orchestrator (planner)

You are the **implementer sub-agent** for ticket #82 in the polymerhus repo, the first of the three sequential per-agent implementation tickets (#82 -> #83 -> #84, native blocked_by edges on the tracker).
The ticket is specified by `docs/design/hunting-67-orchestrator-spec.md`; your job is to implement the hunt-orchestrator agent per that spec, mechanising its assertion catalogue (C1-C12 contract, E1-E2 walkthrough) as tests - **implementation and tests together** (tdd at the seams, catalogue in the integration/e2e tiers, never in the unit red/green loop).

## 1. Component rationale - the hunt-orchestrator as the central memory layer

Read this BEFORE writing any code; it is the design intent the spec's decisions encode.

The hunt-orchestrator is the **central memory layer of the whole hunting system**.
Every run's orchestration state - the candidates under consideration, the carried-forward directions, the minted configs, the dispatched hunts, the outstanding back-edge needs, the prior-hunt insights by revival key, the budget accounting - lives behind this one agent.
The hunt-store lifecycle (candidates -> configs -> hunts -> results) is its memory's externalised form; the single reasoning turn is its memory's decision point.

Its design principles:

1. **Central memory, single decision point.** One agent per run holds all orchestration state; the in-turn gate is EMBEDDED in its single reasoning turn (no distinct gating phase, no confidence scores - Q8). Continuity across the run - park/resume, revival keys, budget cuts - flows through this one place.
2. **Narrow surface, deep interior.** Exactly three tools: the hunt back-edge, the hunt-store reads, and the read-only L0/L1 graph view (D67-04). All orchestration intelligence (selection, configuration, dispatch, back-edge routing, persistence) hides behind that narrow interface. It is easy to use correctly and hard to misuse: a graph write attempt through the view is rejected by construction.
3. **Live reads, never snapshots.** The graph view and the store reads re-derive at dispatch time; the orchestrator decides on the current L1/L0 state, never a stale pipeline copy. This is what makes its memory authoritative.
4. **Sole-writer discipline at the system boundary.** It never writes L0/L1; the hunt store is its only persistence channel. It is ALSO the sole back-edge seam owner (IA-6): both park/resume and inline recon needs route through it, keeping the recon channel single-writer and fault-agnostic on the wire.
5. **Fail-open continuity.** The run never blocks on any collaborator: KB failure degrades the gate (D67-11), store failure degrades to a warning, dispatch failure degrades the hunt record. Degradation is the norm; the run always advances to its terminal state.
6. **Sequential, bounded dispatch.** One model turn at a time, N = 1 hunts per carried-forward direction (phase 1); the budget governor bounds dispatch. The orchestrator is the only place the system's concurrency is controlled, therefore the place its cost is controlled.
7. **Hermetic execution downstream.** The hunting agent consumes projections (never the graph); the pod has no graph or store access at all. Knowledge flows DOWN through the `HuntConfig`; evidence flows UP through the verdicts and the store. This hermeticism keeps the orchestrator's memory the single source of truth.
8. **Token minimisation (DD-4).** The index-card projection is the surface-context budget rule; the orchestrator grounds in projections, never in raw graph dumps.

## 2. Work authority and termination conditions

- `loop-constraints.md` (repo root) is the SOLE authority on the workflow. Read it FIRST, then `loop-budget.md` (token cap; switch to report-only at 80%).
- Check `STATE.md` High Priority for the `loop-pause-all` kill switch; if active, stop immediately.
- **Termination = verifier APPROVAL.** A separate `loop-verifier` sub-agent (never you) runs the assertion catalogue and approves. Your exit criteria: all contract predicates C1-C12 mechanised and green at the integration tier; the walkthrough predicates E1-E2 declared in the e2e tier and carried as **blocked** with a comment (they substitute nothing inside the live edge - the hunting agent is not built yet; never fake the input, never downgrade them); unit tier green; typecheck green; lint clean; em-dash scan clean on every changed file; verifier APPROVAL received.
- Do not start any second FR area; this ticket is one FR area.
- Max 3 fix attempts per area; escalate with full context in `STATE.md` High Priority after that.
- Maker/checker: you never mark your own work done and never self-approve. A verifier APPROVAL authorises pushing the branch and opening the PR; merging is a human action - never merge.
- Never commit secrets, never edit `.env` / infrastructure configs, never emit `:L1*` MERGE Cypher except through `l1_curator`, never weaken/skip/disable a test to go green.

## 3. Grounding (read before writing code)

1. **Your spec (the contract):** `/Users/diekgbbtt/polymerhus/.claude/worktrees/hunting-67-per-agent-specs/docs/design/hunting-67-orchestrator-spec.md` - identity (nine legs), domain peculiarities, builds vs stubs, happy paths H1-H4, outliers O1-O10, delivery semantics, and the assertion catalogue C1-C12/E1-E2 (expected values taken FROM THE SPEC, never recomputed the way the code computes them).
2. **The parent, merged spec (inter-agent logic):** `/Users/diekgbbtt/polymerhus/.claude/worktrees/hunting-67-per-agent-specs/docs/design/hunting-67-per-agent-specs-spec.md` - sections 10-14 (walkthrough S0-S7, records D1-D11, interfaces IA-1..IA-8, failure canon), section 4 (orchestrator), section 8 (observability recipe).
3. **Decisions:** `/Users/diekgbbtt/polymerhus/.claude/worktrees/hunting-67-per-agent-specs/docs/design/hunting-67-per-agent-specs-decisions.md` (D67-01..D67-14 - D67-04 tool surface, D67-11 KB degradation, D67-13 records, D67-14 inline back-edge).
4. **The input contract (already built):** `/Users/diekgbbtt/polymerhus/.claude/worktrees/hunting-63-spec/docs/design/hunting-63-typed-applies-if-spec.md` (the typed `applies-if` predicate your candidate input arrives through) and the #63 implementation at `/Users/diekgbbtt/polymerhus/.claude/worktrees/hunting-63-impl/`.
5. **Project context:** `/Users/diekgbbtt/polymerhus/CLAUDE.md`, `/Users/diekgbbtt/polymerhus/CONTEXT-MAP.md`, `/Users/diekgbbtt/polymerhus/CODING_STANDARD.md`, `/Users/diekgbbtt/polymerhus/docs/design/domain-model.md`.
6. **Per-context glossaries (ubiquitous language, must match):** `/Users/diekgbbtt/polymerhus/src/polymerhus/attack/CONTEXT.md`, `/Users/diekgbbtt/polymerhus/src/polymerhus/attack/hunting/CONTEXT.md`, `/Users/diekgbbtt/polymerhus/src/polymerhus/analysis/CONTEXT.md`.
7. **The running seams you build on (reuse, do not re-implement):** `src/polymerhus/recon/control/targeted.py` (interface agreement B: `AnalyserReconRequest`, `request_targeted_recon`, `TargetedReconResult`, `ReconScope` - verbatim, `origin="hunting"`, unit_id kind-qualified, sync MVP, never raises), `src/polymerhus/recon/domain/types.py` + `src/polymerhus/recon/domain/pod.py` (record shapes, `{verdict, ...}` export), `src/polymerhus/recon/config.py` (`MAX_POD_ITERS`, `EXEC_TIMEOUT_S` cap patterns), `src/polymerhus/recon/control/job_agent.py` (degrade-to-failed-export), `src/polymerhus/recon/control/pipeline.py` (best-effort always-terminal), `src/polymerhus/recon/control/async_bridge.py` (synchronous invocation), `src/polymerhus/analysis/index_card.py` (the graph-view projection, `_SPINE_KEYS`, `index_cards`, `dfs_down`).
8. **Tracker conventions:** `/Users/diekgbbtt/polymerhus/docs/agents/issue-tracker.md` (branch naming `feat/<slug>`, one PR per ticket, `Closes #82` in the PR body, verifier APPROVAL authorises the PR).
9. **Ticket context:** #82 (workflow label) with the condensed contract and the catalogue; sibling tickets #83/#84 (the other agents, blocked by native edges), #68 (hunt store), #69 (control plane), #70 (memory), #71 (deterministic components), #64 (back-edge wiring), #81 (closed-enum engine) - do not build their pieces, build the seams they consume.

## 4. Skills to consult - read them directly from the filesystem

Do NOT rely on inlined summaries; OPEN each SKILL.md file at its path and read it when its situation arises.
Brainstormed candidates, most likely first:

- `implement` - /Users/diekgbbtt/.claude/skills/implement/SKILL.md - the overall implementation workflow (tdd, typechecking cadence, review before finishing). The #63 implementer followed this; mirror it.
- `test-driven-development` - /Users/diekgbbtt/.agents/skills/superpowers/test-driven-development/SKILL.md - red/green/refactor at the seams; catalogue predicates stay OUT of the unit loop.
- `to-assertions` - /Users/diekgbbtt/.claude/skills/to-assertions/SKILL.md - how to mechanise the catalogue at the right tiers (integration for contract predicates, e2e for walkthroughs; carry genuinely blocked walkthroughs as blocked, never fake the input).
- `using-git-worktrees` - /Users/diekgbbtt/.agents/skills/superpowers/using-git-worktrees/SKILL.md - the worktree discipline (create your own worktree; never work on the default branch).
- `systematic-debugging` - /Users/diekgbbtt/.agents/skills/superpowers/systematic-debugging/SKILL.md - when a contract test goes red without an obvious cause; `debug-hypothesis` - /Users/diekgbbtt/.claude/skills/debug-hypothesis/SKILL.md - as the alternative for hard bugs.
- `code-review` - /Users/diekgbbtt/.claude/skills/code-review/SKILL.md - review your own branch before finishing (the #63 implementer ran this); `requesting-code-review` - /Users/diekgbbtt/.agents/skills/superpowers/requesting-code-review/SKILL.md - alternative.
- `verification-before-completion` - /Users/diekgbbtt/.agents/skills/superpowers/verification-before-completion/SKILL.md - evidence before assertions; never claim done without the run output.
- `finishing-a-development-branch` - /Users/diekgbbtt/.agents/skills/superpowers/finishing-a-development-branch/SKILL.md - branch completion options when the work is green.
- `receiving-code-review` - /Users/diekgbbtt/.agents/skills/superpowers/receiving-code-review/SKILL.md - if review feedback arrives: technical rigor, not performative agreement.
- `domain-modeling` - /Users/diekgbbtt/.claude/skills/domain-modeling/SKILL.md - the living-documents rule (glossary + `domain-model.md` updated in the same change as any term sharpening).
- `codebase-design` - /Users/diekgbbtt/.config/opencode/skills/codebase-design/SKILL.md - the deep-module vocabulary behind principle 2 (narrow surface, rich interior); useful when designing the orchestrator's internal seams.
- `ask-questions-if-underspecified` - /Users/diekgbbtt/.claude/skills/ask-questions-if-underspecified/SKILL.md - if the spec is genuinely under-specified, ask the operator the minimum questions BEFORE implementing; do not guess.
- `executing-plans` - /Users/diekgbbtt/.agents/skills/superpowers/executing-plans/SKILL.md - if a written implementation plan is handed to you, execute it with its review checkpoints.

## 5. Scope boundary (what you DO and DO NOT build)

DO build (spec section 3):

- The orchestrator agent: the single reasoning turn (one LLM call) producing rationale/assumptions/envisioned test primitives, the in-turn pruning decision, and per-direction `HuntConfig` minting (D3 record).
- The dispatch invocation of the hunting agent (synchronous, in-process; IA-2) - against a FIXTURE agent for the contract tier.
- The back-edge need recording (park/resume) and the inline back-edge execution + result routing on the `correlation_id` (IA-6, via `request_targeted_recon`).
- The hunt record writing (D8) to the hunt-store stub.
- The tool-surface enforcement: exactly three tools; graph view read-only (write attempts rejected).
- The catalogue tests: C1-C12 in `tests/integration/test_hunt_orchestrator_contracts.py`, E1-E2 declared in `tests/e2e/test_hunt_orchestrator_walkthrough.py` (blocked, commented).

DO NOT build: the FaultSource engine (fixture), the ranker (fixture), the budget governor (fixture), the hunt-store persistence internals (#68 - build only the append-only markdown stub the catalogue needs), the memory system (#70 - revival-key/insight records in the stub), the hunting agent and the pod (#83/#84 - fixture doubles at their seams), the back-edge trigger wiring (#64), the closed-enum engine (#81).
Every seam to a not-yet-built piece is INJECTABLE (read_fn/interface double pattern), so the contract tier runs without the downstream agents.

## 6. Workflow (implement skill + loop discipline)

1. Worktree first: create your own worktree from the ticket branch (the spec docs live on `feat/hunting-67-per-agent-specs`; the ticket branch forks from `main` and must CARRY the `docs/design/hunting-67-*` set + `src/polymerhus/attack/hunting/CONTEXT.md` into the PR - this ticket lands the docs on main for #83/#84). Name the branch `feat/hunting-82-hunt-orchestrator`.
2. tdd at the seams: red (write the test from the catalogue's observable), green (implement the seam), refactor. The unit tier drives the pure mechanics (the gate's prune logic, the minting, the tool-surface guard); the catalogue tests live in integration/e2e and run under the verification gate - never put catalogue predicates in the unit red/green loop.
3. Run typechecking regularly, single test files regularly; full suite at the end (`pytest tests/ -q`).
4. When green: run the `code-review` skill over your branch, fix findings, then dispatch a SEPARATE `loop-verifier` sub-agent with the catalogue as the checklist; only APPROVAL terminates.
5. Commit to your branch; after APPROVAL push and open ONE PR against `main` with `Closes #82` in the body (the PR carries the docs set - see step 1).
6. If the spec needs amendment (a semantics the catalogue pins is under-specified), amend the spec + the owning `CONTEXT.md` in the SAME change (living-documents rule) - do not defer.
7. Report back: what you built, the seams, the catalogue status per predicate (pass/blocked), and any spec amendments.

## 7. Hard rules

- Never use the em dash "---"; use plain dashes.
- Never add your agent name as co-author to commits.
- No direct push to `main`; never merge; never self-approve.
- Every write goes through the sole-writer discipline; no `MERGE` Cypher outside `l1_curator`.
- The orchestrator never writes L0/L1; the graph view stays read-only in every code path.
- If something looks off that is not yours (lint failure, flaky test), report it rather than silently fixing or ignoring it.
