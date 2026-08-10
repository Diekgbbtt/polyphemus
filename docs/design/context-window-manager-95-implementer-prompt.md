# Implementer prompt - #95 adaptive context-window manager

*Feed this verbatim to the agent that will address #95. It specialises the agent on the workflow, grounds it in the domain/architecture/standard, states the component rationale, brainstorms the useful skills, and pins the loop's termination conditions.*

---

You are the implementer agent for ticket **#95 - "Context window auto-compact for long-horizon sessions"** in the polymerhus repo.
Read the ticket first (`gh issue view 95`): it carries the ratified design, the open grilling questions, and the dependency graph.
This is a **shared, cross-cutting subsystem**, not a single-module feature - build it with the care that implies.

## 1. Component rationale (the design intent to honour)

Long-horizon agent sessions (the #94 semi-stateful scaffold) accumulate reasoning turns and tool outputs until they exceed the model's context window.
You are building the adaptive, shared context-window manager that keeps each session inside the model's real window without losing analysis-relevant material.
The load-bearing design principles, all ratified - do not silently deviate:

- **Shared, under `app/llm`** (the LLM-scaffold layer), consumed by each module (recon, analysis, hunting) through a thin per-module client; the tool-output store it indexes into is the module's own (e.g. the test-executor pod's ExperimentLog), never a new global graph.
- **Augments the SESSION path** (`chat_model_for`), not the one-shot `invoke_role`/`invoke_model` path - the two carry different interface agreements and a partial migration is ongoing. This work is **blocked by #94**; confirm #94's interface agreement is landed (or coordinate) before wiring consumers.
- **Adaptive to the real window**: the model's input/output context size is read per-model from the **LiteLLM gateway (fed by models.dev)**, never hardcoded. A conservative **150k** default covers the rare miss; **SwissAI is not on models.dev, so it takes the default**.
- **Out-of-band, race-free** (ratified concurrency): compaction runs as a background task launched after an LLM response is received; the next call on that session **awaits it if still pending (a barrier)**, so a call never proceeds on an over-budget window.
- **Threshold-triggered**: a configurable percentage of the window, **default 90%**.
- **Summarise reasoning, do not drop it**: a running summary, never a coalesce-and-discard.
- **Offload tool outputs, do not discard them**: the window keeps a **header** (the tool-call outline + status/size + an index ref into the module store); a **retrieval** path pulls the full body on demand; a retrieved body is itself re-filtered on the next compaction so it cannot permanently re-bloat.
- **Full fidelity preserved**: compaction bounds only what the agent SEES; the module store keeps the full trail for export/eval.

## 2. First step - a grilling session (reduce the key risks to a residual minimum)

Before any code, run a grilling session with the operator (the `grilling` skill).
Drive it to a solution for each of the ticket's open questions; these are the residual risks:

1. **What retrieves context-window lengths dynamically?** (models.dev via the LiteLLM gateway field; SwissAI -> 150k default. Confirm the exact gateway field and access path.)
2. **Which langchain-ai or openai SDK primitive is the most proper?** (the seam is langchain 1.3.x `create_agent` + its `AgentMiddleware` hooks - `before_model`/`after_model`/`before_tool`/`after_tool`, `wrap_model_call` - NOT a `pre_model_hook`/`llm_input_messages` parameter, which does not exist in the built seam. Inside the middleware body, `trim_messages`, `count_tokens_approximately`, and the openai response `usage` metadata are usable; decide which are load-bearing.)
3. **The summarisation prompt?** (mine it verbatim; it is LLM-call content, not invented at implementation time.)
4. **How are summaries tracked, and what exactly is tracked?** (the running-summary object per session - keyed off the typed `SessionAddress.thread_id` - and its fields.)
5. **Does tool-output trimming belong to specific modules, or is a centralised memory needed?** What is in the header? The indexing algorithm? The retrieval algorithm - a terminal file read vs a specific tool call? (Relates to #85 mem0 research: evaluate dependency/impact/profile/fit before committing a bespoke store; do NOT pull mem0 in without that evaluation.)

Record the grilling outcome (the `grill-with-docs` variant writes the ADR + glossary entries in the same change).
Do not start coding until the operator confirms a shared understanding.

## 3. Grounding - read these directly from the filesystem before designing

- `CLAUDE.md`, `CONTEXT-MAP.md`, `CODING_STANDARD.md` - the DDD paradigm, bounded contexts, sole-writer discipline, slim typed interface agreements, dependency injection for testability, no I/O at import (section 6), fail-open (section 12).
- `src/polymerhus/app/llm/providers.py`, `roles.py`, `session.py`, `session_address.py`, `checkpoints.py` - the LLM-scaffold layer you extend: `ChatOpenAI` per role over `PROVIDERS`, `resolve_role`, `chat_model_for` (session path) vs `invoke_role` (one-shot path), the single escalating-retry wrapper `invoke_with_escalating_timeout`, and the SESSION SEAM you plug into: `run_session_turn`/`arun_session_turn`/`stateful_turn` on `create_agent` with `middleware`/`store`/`checkpointer` parameters, typed `SessionAddress` thread identity, pooled `PostgresSaver` checkpointer. This is where the shared component lives.
- The #94 issue and its branch/worktree - the semi-stateful scaffold and its interface agreement you build on. Read the seam comment on the #95 ticket (adjusted 2026-08-07) before designing; the seam is `create_agent` middleware, not a `pre_model_hook`/`llm_input_messages` parameter.
- The #84 test-executor pod design - the first consumer: a token-aware `trim_messages` that currently **drops** oldest turns is planned for its curated sessions (not yet built); your component replaces it with offload + summarise. `pod/config.py` carries `HUNT_POD_SESSION_TOKENS` (to be built with #84).
- The ticket's relations: **#94** (blocker), **#85** (mem0 research), **#93** (unified analyser role key + one-shot vs resumable property), and the LiteLLM gateway + models.dev work (tracked separately - the per-model window field is its dependency).
- `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md` - branch naming, one PR per workflow ticket, verifier APPROVAL + operator green light authorise the PR.
- `loop-constraints.md` (the sole work authority) and `loop-budget.md` (token cap; report-only at 80%); check `STATE.md` High Priority for the `loop-pause-all` kill switch.

## 4. Skills - open each SKILL.md from the filesystem when its situation arises

Beyond `ask-questions-if-underspecified` (this prompt cannot be exhaustive - ask the operator the minimum questions before implementing a gap, never guess), `langgraph` (the `create_agent`/`AgentMiddleware`/state-reducer machinery) and `langfuse` (the fail-open observability recipe; a compaction pass should be observable), brainstormed candidates most-likely-first:

- `grilling` / `grill-with-docs` - the first step (section 2), the latter records the ADR + glossary in the same change.
- `implement` - the overall TDD/typecheck/review-before-finishing workflow.
- `test-driven-development` - red/green/refactor at the seams; keep the assertion catalogue out of the unit red/green loop.
- `prompt-engineering-patterns` - crafting the summarisation prompt verbatim (system-vs-user split, structured output, template systems).
- `codebase-design` / `domain-modeling` - the deep-module vocabulary for a shared component with a narrow client seam, and the living-documents rule (glossary + `domain-model.md` updated in the same change as any term sharpening).
- `verification-before-completion` - evidence before assertions; never claim done without the run output.
- `code-review` / `requesting-code-review` / `receiving-code-review` - review the branch before finishing; respond with technical rigor.
- `using-git-worktrees` - the worktree discipline (section 5).

## 5. Workflow discipline and termination conditions

- **Worktree first**: branch off **`dev`** (the running stack's source, never `main`, never the default branch) into a NEW git worktree; name the branch `feat/context-window-manager-95` (or per the issue-tracker convention).
- TDD at the seams: unit tier drives the pure mechanics (token accounting, threshold trigger, header construction, the running-summary update, the barrier logic) with the LLM and the gateway mocked - the unit tier touches no live model, no live gateway, no DB. The contract catalogue lives in integration; any live-model walkthrough lives in e2e.
- Run typechecking and single test files regularly; the full suite at the end.
- **E2E + the running stack**: the running stack is built from `dev`, and the e2e tier runs in-network against it. When your e2e needs the stack, **merge your branch into `dev`** (the only merge you perform - never to `main`), rebuild, and run the e2e tier in-network per `loop-constraints.md` - do this **before** requesting the operator's green light.
- Living documents: land any glossary/`domain-model.md`/CONTEXT.md term sharpening in the SAME change (do not defer).
- Maker/checker: you never mark your own work done and never self-approve. When green, run the `code-review` skill over your branch, fix findings, then dispatch a SEPARATE `loop-verifier` sub-agent with the catalogue as the checklist.
- **Termination**: verifier APPROVAL, then the operator's green light. Only then push the branch and open ONE PR against `main` with `Closes #95` in the body. Merging to `main` is a human action - never merge to `main`. Max 3 fix attempts per area; escalate with full context in `STATE.md` High Priority after that.
- Never commit secrets, never edit `.env`/infra configs, never weaken/skip/disable a test to go green.
