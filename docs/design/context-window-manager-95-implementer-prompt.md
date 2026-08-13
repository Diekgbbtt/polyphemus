# Implementer prompt - #95 adaptive context-window manager

*Feed this verbatim to the agent that will address #95. It specialises the agent on the development discipline (grilling -> to-spec -> to-tickets -> to-assertions -> implements), grounds it in the domain/architecture/standard, states the component rationale, brainstorms the useful skills, and pins the loop's termination conditions.*

---

You are the implementer agent for ticket **#95 - "Context window auto-compact for long-horizon sessions"** in the polymerhus repo.

Read the ticket first (`gh issue view 95`): it carries the ratified design, the open grilling questions, and the dependency graph. This is a **shared, cross-cutting subsystem**, not a single-module feature - build it with the care that implies.

## 1. Component rationale (the design intent to honour)

Long-horizon agent sessions accumulate reasoning turns and tool outputs until they exceed the model's context window. You are building the adaptive, shared context-window manager that keeps each session inside the model's real window without losing analysis-relevant material.

The load-bearing design principles, all ratified - do not silently deviate:

- **Shared, under `app/llm`** (the LLM-scaffold layer), consumed by each module (recon, analysis, hunting) through a thin per-module client; the tool-output store it indexes into is the module's own (e.g. the test-executor pod's ExperimentLog), never a new global graph.
- **Augments the SESSION path only** - `run_session_turn`/`arun_session_turn`/`stateful_turn` on `create_agent` - never the one-shot `invoke_role`/`invoke_model` path; the two carry different interface agreements.
- **Adaptive to the real window, from the gateway surface**: the model's input/output context size is read per-model from the **LiteLLM gateway via the capability reader** (D6), never hardcoded. A conservative **150k** default covers the miss (**SwissAI is not on models.dev -> default**).
- **Out-of-band, race-free** (ratified concurrency): compaction runs as a background task launched after an LLM response; the next call on that session **awaits it if still pending (a barrier)** - a call never proceeds on an over-budget window.
- **Threshold-triggered**: a configurable percentage of the window, **default 90%**.
- **Summarise reasoning, do not drop it**: a running summary, never a coalesce-and-discard.
- **Offload tool outputs, do not discard them**: the window keeps a **header** (the tool-call outline + status/size + an index ref into the module store); a **retrieval** path pulls the full body on demand; a retrieved body is itself re-filtered on the next compaction so it cannot permanently re-bloat.
- **Full fidelity preserved**: compaction bounds only what the agent SEES; the module store keeps the full trail for export/eval.
- **REASONING REPLAY COLLISION (the load-bearing new constraint)**: the #100 stream (T6/D8.1/D11) made the seam re-persist assistant reasoning **byte-identical**, so the next turn's restored prefix hits the provider's KV cache. Compaction that summarises/removes the reasoning payload **breaks that byte-identity and destroys the replay value**. Design the compact pass to coordinate with the replay pipeline - e.g. exempt replay-eligible reasoning, or summarise only stale/non-replayed spans and mark the readability signal accordingly - and get the precedence ratified in the grilling. This is a seam-to-seam contract, not an implementation detail.
- **Cache-track is observability, never a gate** (D11 item 3): `usage_metadata.input_token_details.cache_read` / `cached_tokens` are recorded, never load-bearing decisions.

**What the #100 stream already delivered - build ON it, do not rebuild:**

- **The window surface (D6, the ticket's open question 1, now closed)**: `CapabilityProfile.context_limit` / `output_limit` at `capability.py:149-150`, read from the gateway's `/model/info` `model_info.max_input_tokens` / `max_output_tokens`, provenance-gated (D5 Rule 1: absent = unknown/None); `resolve_capability(provider, model)` at `capability.py:295` - process-lifetime resolve-and-hold, fail-open, resolved at session construction (session.py:276,309), OFF the #73 axis. Your compaction logic consumes THIS surface for the window - never a hardcoded model table.
- **The session seam**: `session.py` `run_session_turn`/`arun_session_turn` (sync + async entry points; `middleware`/`store`/`checkpointer` params, `model_factory` injection) - the compaction task and the barrier attach here; the post-invoke hook pattern is proven by `_replay_reasoning`/`_areplay_reasoning` (session.py:196,231).
- **The thread-state read pattern**: `_read_thread_state`/`_aread_thread_state` (session.py:365,388) - fail-open, awaitable-shaped, the sanctioned way to read persisted channel state for usage accounting; `read_session_memory`/`aread_session_memory` for the retrieval path.
- **The middleware seam**: `create_agent`'s `middleware` params (langchain 1.3.x `AgentMiddleware` hooks - `before_model`/`after_model`/`before_tool`/`after_tool`/`wrap_model_call`) - NOT a `pre_model_hook`/`llm_input_messages` parameter (that does not exist in the built seam; the earlier prompt's own note, still binding).
- **The langfuse metadata recipe**: the D11 item-4 llm-response metadata field (`reasoning_readability`) via `_attach_readability_metadata` - your compaction/usage observability rides the same pattern (fail-open, same-session trace via `langfuse_session_id`).
- **Token accounting**: `usage_metadata.input_token_details.cache_read` (`cached_tokens`) - read, recorded, never a gate.

## 2. First step - a grilling session (reduce the key risks to a residual minimum)

Run the **grilling** skill with the operator before any code; drive it to a solution for each of the ticket's open questions. These are the residual risks:

1. **The window source**: `CapabilityProfile.context_limit` via `resolve_capability` (and `output_limit` where relevant), 150k default on unknown. Confirm the exact consumption point - resolved once at session construction, held, never re-read mid-session (D6).
2. **The SDK primitive**: the seam is langchain 1.3.x `create_agent` + `AgentMiddleware` (`before_model`/`after_model`/`before_tool`/`after_tool`/`wrap_model_call`). Inside the middleware, decide what is load-bearing: `trim_messages`, `count_tokens_approximately`, the response `usage` metadata, and the thread-state read for the head/tail context.
3. **The summarisation prompt**: mine it verbatim (the `prompt-engineering-patterns` skill; system-vs-user split, structured output) - prompt content is not invented at implementation time.
4. **How summaries are tracked**: the running-summary object per session - keyed off the typed `SessionAddress.thread_id` - and its fields.
5. **Tool-output trimming's home**: module-owned vs centralised; the header shape; the indexing algorithm; the retrieval algorithm (terminal file read vs a specific tool call). Relates to #85 (mem0 research) - evaluate dependency/impact/profile/fit before committing a bespoke store; do NOT pull mem0 in without that evaluation.
6. **THE reason-collision precedence (load-bearing, never skipped)**: compaction vs the T6 byte-identical reasoning replay (D8.1) - which spans are summarisable, which are replay-eligible and must stay byte-identical, how the readability signal (`reasoning_readability`) and the replay report reflect a compaction pass, and what the unit contract for that precedence is.
7. **CN-adjacent scope**: the #84 test-executor pod's curated sessions (the interim token-aware `trim_messages` that DROPS oldest turns - your component replaces it with offload + summarise). Confirm the first consumer and the migration boundary; do not wire consumers in the same change unless the grilling ratifies it.

Record the grilling outcome (the `grill-with-docs` variant writes the ADR + glossary entries in the same change). Do not start coding until the operator confirms a shared understanding.

## 3. Grounding - read these directly from the filesystem before designing

- `CLAUDE.md`, `CONTEXT-MAP.md`, `CODING_STANDARD.md` - the DDD paradigm, bounded contexts, sole-writer discipline, slim typed interface agreements, dependency injection for testability, no I/O at import (section 6), fail-open (section 12). NOTE the `CONTEXT-MAP.md` ruling: **llm-client is a helper module, never a context** - it gets no `CONTEXT.md`.
- `loop-constraints.md` (the sole work authority - read it verbatim), `loop-budget.md` (token cap; report-only at 80%), `STATE.md` (High Priority: kill switch, escalations).
- `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `docs/agents/domain.md` - the ticket vocabulary, the workflow, and the domain-glossary mechanics.
- `docs/design/llm-gateway-100-decisions.md` - **the ADR: D1-D11 read in full**, especially D4 (additive blast radius - no agent/actor/checkpointer module touched), D5 (provenance), D6 (the gateway window surface - the contract this ticket consumes), D8.1 (byte-identical replay prefix - the collision), D11 (reasoning surfaces + metadata + cache-track-never-gates).
- `docs/design/domain-model.md` - the living reasoned model: the session primitive, the reasoning-replay note (added 2026-08-12), and where the compaction/summary primitive is documented.
- `docs/design/statefulness-pattern-matrix.md` - the one-shot vs resumable session property your component attaches to.
- `src/polymerhus/app/llm/capability.py` - `CapabilityProfile.context_limit`/`output_limit`, `resolve_capability` (the window source; fail-open; provenance-gated).
- `src/polymerhus/app/llm/session.py` - the seam you attach to: `run_session_turn`/`arun_session_turn`/`stateful_turn` signatures, the `middleware` params, `_replay_reasoning`/`_areplay_reasoning` (the post-invoke hook precedent), `_read_thread_state`/`_aread_thread_state` (fail-open, awaitable-shaped), `read_session_memory`/`aread_session_memory` (the retrieval precedent), `_attach_readability_metadata` (the langfuse metadata recipe), `SessionAddress`/thread-id keying.
- `src/polymerhus/app/llm/session_address.py`, `checkpoints.py` - typed thread identity and the pooled `PostgresSaver`/`AsyncPostgresSaver` checkpointer used by the parents.
- The #94 issue (`gh issue view 94` - OPEN, the agent-migration ticket the session scaffold routes around): the session machinery exists and is used in production paths; wire consumers per the grilling, not speculatively.
- The #84 test-executor pod design - the first consumer (its curated sessions' interim `trim_messages` that drops turns).
- The reason-collision evidence: `tests/test_gateway_reasoning_passthrough.py` (wire replay), `tests/test_llm_reasoning.py` (the preserving-client boundary tests; the fail-open checkpointer-shape tests - your barrier/compaction must show the same fail-open discipline), `tests/test_llm_session.py` (the seam contract).
- The tickets: `gh issue view 95` (this ticket), `gh issue view 85` (mem0 research), `gh issue view 93` (role vocabulary), `gh issue view 94` (blocker/context), `gh issue view 109` (T6 - the replay pipeline you coordinate with).
- `docs/observability-langfuse.md` - the observability recipe the metadata surface rides.

## 4. Skills - open each SKILL.md from the filesystem when its situation arises

Skills are user-invokable only; you cannot load them through a skill loader. Open each skill's `SKILL.md` directly from the filesystem when its situation arises:

- `grilling` - `/Users/diekgbbtt/.claude/skills/grilling/SKILL.md` - the FIRST step (section 2); the `grill-with-docs` variant (`/Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md`) records the ADR + glossary in the same change.
- `to-spec` - `/Users/diekgbbtt/.claude/skills/to-spec/SKILL.md` - turns the grilling outcome into the spec (seams chosen at the top; no interview, synthesize what was grilled).
- `to-tickets` - `/Users/diekgbbtt/.claude/skills/to-tickets/SKILL.md` - breaks the spec into tracer-bullet tickets, each declaring its blocking edges.
- `to-assertions` - `/Users/diekgbbtt/.claude/skills/to-assertions/SKILL.md` - projects the spec/tickets into contract + walkthrough predicates at the to-spec seams; mechanised in the integration/e2e tiers, never in the unit red/green loop.
- `implement` - `/Users/diekgbbtt/.claude/skills/implement/SKILL.md` - the overall TDD/typecheck/review workflow for each ticket slice.
- `test-driven-development` - `/Users/diekgbbtt/.claude/skills/test-driven-development/SKILL.md` - red/green/refactor at the seams.
- `prompt-engineering-patterns` - `/Users/diekgbbtt/.claude/skills/prompt-engineering-patterns/SKILL.md` - the summarisation prompt and any compact-pass observability text are PROMPT CONTENT: system-vs-user split, structured output, template systems - crafted, not invented.
- `langgraph-docs` - `/Users/diekgbbtt/.claude/skills/langgraph-docs/SKILL.md` - the `AgentMiddleware`/state-reducer machinery (barrier via middleware state, checkpointer interaction).
- `langfuse` - `/Users/diekgbbtt/polymerhus/.claude/skills/langfuse/SKILL.md` - a compaction pass is observable (fail-open; the D11 item-4 metadata recipe).
- `verification-before-completion` - `/Users/diekgbbtt/.claude/skills/verification-before-completion/SKILL.md` - evidence before assertions.
- `code-review` / `requesting-code-review` / `receiving-code-review` - review the branch before finishing; respond with technical rigor, never performative agreement.
- `using-git-worktrees` - `/Users/diekgbbtt/.claude/skills/using-git-worktrees/SKILL.md` - the worktree discipline (section 5).
- `domain-modeling` / `codebase-design` - the deep-module vocabulary for a shared component with a narrow client seam, and the living-documents rule (glossary + `domain-model.md` updated in the same change as any term sharpening).

## 5. Workflow discipline and termination conditions

- **The discipline is fixed: grilling -> to-spec -> to-tickets -> to-assertions -> implements.** Run the stages in that order, each gated: grilling (operator confirms shared understanding) -> to-spec (spec published, `ready-for-agent` applied) -> to-tickets (tracer-bullet slices, blocking edges declared) -> to-assertions (contract + walkthrough predicates at the to-spec seams) -> implements (one ticket slice at a time, TDD).
- **Worktree first**: branch off **`dev`** (the running stack's source - never `main`, never the default branch) into a NEW git worktree; name the branch `feat/context-window-manager-95` (or per the issue-tracker convention).
- TDD at the seams: the unit tier drives the pure mechanics (token accounting, threshold trigger, header construction, the running-summary update, the barrier logic, the reasoning-collision precedence) with the LLM and the gateway mocked - the unit tier touches no live model, no live gateway, no DB. The contract catalogue lives in integration; a live walkthrough (usage growing past the threshold -> compaction task -> next turn awaits the barrier -> turned state observed) lives in e2e.
- Run typechecking and single test files regularly (`.venv/bin/python -m pytest tests/<file> -q`); the full suite at the end. Live tiers run IN-NETWORK against the stack built from `dev` - merge your branch into `dev` (the only merge you perform - never to `main`), rebuild, and run e2e in-network per `loop-constraints.md`, BEFORE requesting green light.
- Living documents: land any glossary / `domain-model.md` / ADR / spec corrections in the SAME change (do not defer); the D6 consumption of `context_limit` and the reasoning-collision precedence are prime candidates for an ADR note.
- Maker/checker: you never mark your own work done and never self-approve. When green, run the `code-review` skill over your branch, fix findings, then dispatch a SEPARATE `loop-verifier` sub-agent with the assertion catalogue as the checklist.
- **Termination**: verifier APPROVAL, then the operator's green light. Current operating mode is SOLO (operator ruled 2026-08-12: PRs cancelled, no integration pipeline) - integration is a local fast-forward of the ticket branch into `dev` and push, exactly as the #108/#109 stream landed (90d6a6f, 2a9d2c8). If the operator has re-enabled the PR pipeline by the time you land, follow `docs/agents/issue-tracker.md` (one PR against `main`, `Closes #95` in the body; merging to `main` is a human action - never merge).
- Max 3 fix attempts per area; escalate with full context in `STATE.md` High Priority after that.
- Never commit secrets, never edit `.env`/infra configs, never weaken/skip/disable a test to go green.