# ADR: the converged agent turn - one `system_prompt` seam, reasoning replayed by an agent-layer middleware, and the collapse assessment

**Status:** ACCEPTED and IMPLEMENTED (2026-10-10; branch `refactor/analysis-context-engineering`, off `dev` `fe375d0`).
**Amends:** `assigner-A1-decisions.md` §4 (prompt structure - the delivery, not the content), `dataplane-A1-decisions.md` §7.2 (the same delivery claim), `context-compaction-95-decisions.md` D11 item 4 (the replay rides the session seam), `llm-gateway-100-decisions.md` D8 (fact 1 also binds the client), and it records a SECOND mechanism behind the figure in `compaction-cache-convergence-348-adr.md` whose Decision and root cause stand unchanged.
**Related:** `statefulness-pattern-matrix.md` (the reusable rule, OUTLIER-5), the usage surface in `eval-token-tracking-spec.md` N5.

---

## 1. The decision, in one line

The agent turns converge on ONE native LangGraph seam: the role prompt is bound ONCE through `create_agent(system_prompt=...)` as an ephemeral leading block, the per-call human task is the ONLY volatile trail content, and the reasoning replay that keeps the next turn's prefix byte-identical moves OUT of the session thread control layer and into an agent-layer `after_model` middleware.

Everything else about the analysis proposers - the call counts, the fail-closed reflection, the shaping gates - is unchanged.

## 2. The amended design choice: from system-prompt replay per batch, to one system prompt

**Was.** The three analysis proposers rebuilt the prompt on every call and appended it to their own checkpointed trail:

- `assigner.py:521-524` - one `SystemMessage(_system_prompt(mode))` + `HumanMessage(_user_prompt(...))` per chunk.
- `data_modeller.py:744-748`, `:769-773` - one per call (reflection, extraction).
- `mechanism_typist.py:481-484`, `:499-502`, `:507-511` - one per call (reflection, systems, linking).

So the role prompt was a TRAIL message, and the trail accumulated one verbatim copy per call. The compaction dedup (`_dedup_system_messages`, `compaction.py:541-559`) was the mitigation: it de-duplicated the folded region at fold time, late and partial - it never saw the exempt tail.

**Is.** The role prompt is bound once, ephemerally, through the agent construction seam:

- `stateful_turn(..., system_prompt=<role prompt>)` → `create_agent(system_prompt=...)`.
- `create_agent` prepends it per model invocation (`langchain/agents/factory.py:1416-1417`: `messages = [request.system_message, *messages]`) and NEVER writes it into the checkpoint state.
- The proposer therefore passes `HumanMessage(<the per-call task>)` as the only `new_messages`, and the one-shot legacy seam (`_default_invoke_fn`, used by the unit/contract tiers) keeps working by prepending the prompt into the message list itself.

## 3. Why this is the correct seam (the evidence)

### 3.1 The wire shape

Reconstructed through the production `run_session_turn` path with a recording model:

- **Old shape** - `[System, H, A, System, H, A, System, H, ...]`. The skill is a real trail message and sits at a SHIFTING position (0, 3, 6, 9 ...). The provider's KV-cache anchor is a leading prefix, so every new position is a cold prefix.
- **New shape** - `[System, H, A, H, A, H, ...]`. The skill is prepended ephemerally at position 0, byte-identical on every call. Every call's prefix is a strict extension of the previous call's prefix.

### 3.2 The measured cache data

For trial `comfyui-1-20261009T110342-1fc05262` (run `bf7bed51-de26-41a0-a75b-981f691b5b7f`):

| role | calls | `input_cache_read` null | numeric | cached share | fresh-input shape |
|---|---|---|---|---|---|
| `mechanism_typist` | 46 | 43 | 3 | ~3% | 2,714 → 204,327 monotone, **quadratic** (curvature +3,263/call²) |
| `assigner` | 14 | 0 | 14 | 87.9% | flat at ~4,700 |
| `data_modeller` | 26 | 0 | 26 | 85.3% | flat ~13-15K, cached grows to ~165K |

`assigner` and `data_modeller` re-add their own (smaller) prompt per call and still cache well - their prompt is small enough that the re-add cost stays bounded. `mechanism_typist` re-bills an ever-growing prefix, because its skill is the largest of the three, so the compounded copy is what shows the quadratic. The cost therefore scales with PROMPT SIZE, which is why the flat roles gave no warning before this was measured.

### 3.3 The verdict on the collapse

The operator asked whether the technical sequence structurally forces one bounded call. It does NOT.

- The 3-call chain is NOT the sufficient cause: `data_modeller` alternates a no-tools reflection with a tools-bound extraction and still caches at 85.3%. `assigner` re-adds its prompt per chunk and still caches at 87.9%.
- The chain IS the growth multiplier: 3 calls/chunk moves the shifting `SystemMessage` 9 positions per chunk instead of 3, which is why the quadratic term is visible only on `mechanism_typist`.
- With the `system_prompt` fix alone, `mechanism_typist` produces the SAME clean append-only stack `data_modeller` already has. The chain becomes cache-correct once the prefix is stable.

**Decision: the chain stays.** Collapsing reflection → extraction → linking into one high-reasoning pass would trade a ratified design property (the fail-closed reflection gate, the separate structured shapes, the inspectable WHY trace) for no cache gain, and would risk extraction quality. The chain is only revisited if a post-fix live run still reports a low cached share, which would point at the provider-side `prompt_tokens_details` omission (hypothesis H1 of the diagnosis) rather than at the app request.

### 3.4 The prose triplication

`mechanism_typist.py:336`, `:371` and `data_modeller.py:568-569` embed the reflection prose into later prompts while the prose ALSO rides the trail as an assistant message. With a stable prefix that is pure fresh-input inflation on every structured call, so it goes.

## 4. The amended design choice: the reasoning replay moves to the agent layer

**Was.** `run_session_turn` / `arun_session_turn` re-persisted the turn's reasoning AFTER the stream, from the session thread control layer: resolve the T3 profile at turn construction (`_resolve_reasoning_profile`), then on return `_replay_reasoning` parsed the trail and called `agent.update_state(config, {"messages": replacement})` (`session.py:427-483`, `reasoning.py:255-304`).

**Is.** A dedicated `ReasoningReplayMiddleware` (an `AgentMiddleware` whose `after_model` hook re-attaches the reasoning the model just emitted) rides in `_build_agent` exactly like `usage_middleware()` and `parsing_recovery_middleware()` do. The session seam stops reaching for `agent.update_state`; the agent owns its own state.

**Why.** The replay is a state-shape concern - the assistant message in the thread must carry its reasoning for the next turn's prefix to be byte-identical - so it belongs beside the other model-shape concerns in the agent layer, not in the turn control layer. This is also what makes it uniform across every agent: pod, hunting, recon and analysis all get it from the one `_build_agent` seam, instead of the session seam owning it for everyone.

**What does NOT change.** The reasoning still lands on the ratified surfaces (`reasoning_content` on `additional_kwargs`, `reasoning_details` under `provider_specific_fields`); the replay is still best-effort and fail-open (a replay failure never breaks a turn); the capability profile still resolves at turn construction and fail-opens to None (D5 Rule 1); encrypted reasoning is still replayed verbatim and never decoded; the CACHE-TRACK and Langfuse readability observability still fire.

**The honest weak link.** The reasoning is only parsed when a profile says `reasoning_in_response`. The `after_model` hook reads the thread state, so it sees every assistant message the turn produced; a turn that emits reasoning the profile does not name is a logged gap exactly as today. The seam change is a refactor, not a semantic one, and the existing `test_llm_reasoning` tier pins `replay_assistant_reasoning` as the unchanged pure core.

## 5. The N5 measurement fix

`usage.py:_axis_totals` maps an ABSENT `input_token_details` to `cache_read = 0`. That conflates "the provider omitted `prompt_tokens_details`" with "the provider reported a genuine cache miss", which is how the false 0% perception survived. The ledger gains an explicit `cache_detail_omitted` count, so a null detail is recorded as omitted rather than as a zero.

## 6. The priority ruling (operator, 2026-10-10)

When the two goals conflict, INPUT-TOKEN CACHING wins over analysis quality. The operator's reasoning: the model now gives the system prompt less attention because it is a single leading block rather than a fresh copy per batch; but the prompt is the initial prefix and survives compaction, so it retains enough attention across the run. The cost of a slightly weaker fundamental instruction is measured, bounded and paid deliberately; the cost of a quadratic input bill is unbounded and grows with the run.

This is recorded because it is a REVERSAL of the implicit prior: the two-layer prompt split (`assigner-A1-decisions.md` §7.2, "the stable half is byte-stable so the provider prompt-cache survives a run") was believed to be achieving cache stability. It was not - the stable half was being re-send as trail content. The split was right about WHICH half was stable and wrong about HOW stability is delivered.

## 7. Consequences for the docs that specified the old design

- `assigner-A1-decisions.md` §4 - the "system half byte-stable so the cache survives" claim is amended: byte-stability must be delivered by the ephemeral leading block, not by trail re-append.
- `dataplane-A1-decisions.md` §7.2 - the same claim (its in-process prompt-file cache holds the STRING byte-identical, which is necessary but not sufficient), plus the prose re-embed is removed.
- `analysis/CONTEXT.md` "Proposer decomposition" - the proposers still run on their own per-run session thread (unchanged), but the thread content changes shape: no role prompt in the trail, no repeated prose, and one shared construction seam (`analysis/proposer_turn.py`).
- `statefulness-pattern-matrix.md` - the Analysis rows gain the `system_prompt=` construction and OUTLIER-5 gains the reusable rule and the rejected alternative.
- `session.py` - the module docstring's reasoning-replay section is replaced by a pointer to the middleware.
- `llm-gateway-100-decisions.md` D8 / `context-compaction-95-decisions.md` D11 item 4 - the replay rides the agent layer; the pure core (`reasoning.replay_assistant_reasoning`) and the D11 surfaces are unchanged.
- `compaction-cache-convergence-348-adr.md` - records the second, independent mechanism behind the same 30.6% figure; its Decision and root cause stand.
- `eval-token-tracking-spec.md` - gains N5, the `cache_detail_omitted` count that makes a reported 0% cached share readable as "not measured" rather than "measured a miss".

Done as a single change: `assigner-A1-decisions.md`, `dataplane-A1-decisions.md`, `analysis/CONTEXT.md`, `statefulness-pattern-matrix.md`, `llm-gateway-100-decisions.md`, `context-compaction-95-decisions.md`, `compaction-cache-convergence-348-adr.md`, `eval-token-tracking-spec.md`, `docs/design/domain-model.md`, and `session.py`.

## 8. Acceptance criteria

1. Every analysis proposer's per-call request carries ONE role-prompt copy, at position 0, on every call - no role prompt in the checkpointed trail.
2. The `mechanism_typist` context growth stops fitting a quadratic (the measured before: curvature +3,263 per call², SSE 3.7e7 against 9.3e10 linear) and the reported cached share (read through the N5-fixed ledger) is at least the `assigner`'s 87.9% reference.
3. Extraction quality (systems + system_edges counts, and the data_modeller's items/surfaces/flows/rels) does not regress against the baseline run.
4. `replay_assistant_reasoning` keeps its existing unit contract unchanged; the reasoning lands on the same ratified surfaces; a replay failure never breaks a turn.
5. The one-shot legacy seam (`_default_invoke_fn`) still returns the same shapes, so the contract tier is untouched.
6. No agent implementation keeps its own bespoke prompt-replay or reasoning-replay logic: pod, hunting, recon and analysis all route through the one `_build_agent` seam.
