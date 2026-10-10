# Diagnosis: context engineering in the analysis module (cache hostility, growth, and design smells)

**Status:** Diagnosis (not an implementation).
**Date:** 2026-10-10.
**Branch:** `diag/context-engineering-analysis` (off `dev` at `fe375d0`).
**Scope:** the three chunk-fed analysis proposers (`assigner`, `mechanism_typist`, `data_modeller`), the reason the `mechanism_typist` provider cache is reported as zero while the other two cache well, every context-engineering design smell and narrow bug in the analysis module, and the LangGraph primitive question.
**Method:** the `debug-hypothesis` loop (Observe -> Hypothesise -> Experiment -> Conclude), with the `define-hypothesis` template for the testable claim. Evidence: live Langfuse observations for trial `comfyui-1-20261009T110342-1fc05262` (run `bf7bed51-de26-41a0-a75b-981f691b5b7f`), the LiteLLM spend logs, and the source. Every secret is redacted.

This supersedes the cache section of `348-failure-diagnosis.md` and extends it with the direct per-call cache diff, the reasoning-replay branch, and the framework-primitive answer.

---

## 1. Verdict

The three analysis proposers share one implementation pattern (a per-run `stateful_turn` thread, a fresh `SystemMessage(prompt)` re-added on every call, a `HumanMessage` task, outputs stacked as assistant messages). The cache outcomes are NOT shared:

- `assigner` and `data_modeller` report `input_cache_read` numeric on EVERY call, from call 1 or 2.
- `mechanism_typist` reports `input_cache_read` null on 43 of 46 calls, and its fresh `input` grows monotonically to ~204K.

So the cause is NOT the shared pattern (the per-call `SystemMessage`, the tool alternation, or the session thread). It is role-specific to `mechanism_typist`. The evidence is consistent with two compounding causes: (a) the provider intermittently omits `prompt_tokens_details` for this role's request stream, and (b) the `mechanism_typist` chain is the one that keeps its whole trail in one thread with a large, tool-call-dense, re-embedded-system-message prefix that the provider does not re-anchor on. The app-side context restructuring is the no-regret lever regardless of which dominates.

The operator's two named bugs are both confirmed as real design smells: the skill must be bound once via the native `system_prompt`, and the 3-call chain over one thread is the growth multiplier. The operator's reasoning hypothesis is REFUTED at the config level (all three are `medium`) but the replay path is shared, so it is not the role-specific trigger.

---

## 2. The hypothesis (define-hypothesis)

**Belief.** We believe that binding each analysis proposer's role prompt once through the LangGraph-native `system_prompt` and sending only the per-call `HumanMessage` (outputs stacked as assistant messages), and collapsing the `mechanism_typist` 3-call chain onto that single stable prefix, will for the `mechanism_typist` role raise the reported cached share to at least the `assigner`'s level and lower its per-call fresh input, without changing any proposer's output contract.

**Target user segment.** The three chunk-fed analysis proposers in one analysis run (20-27 chunks each).

**Expected outcome.** The `mechanism_typist` per-call fresh `input` stops growing linearly with the run; the reported cached share over 20 calls is at least the `assigner`'s; the per-call prompt carries one skill copy and no duplicated reflection prose.

**Success metrics (primary + guardrails).**
- Primary: `mechanism_typist` cached share over >= 20 calls >= 60% (the `assigner` reference), read from the durable usage ledger (#349).
- Guardrail 1: the `mechanism_typist` extraction output (systems + system_edges counts) does not regress against a baseline run.
- Guardrail 2: the per-call context-growth slope falls materially below the observed ~8,260 tokens per call.

**Validation approach.** One live eval run at the eval budget (200K), the same comfyui-1 target, the `mechanism_typist` per-call cache read from the ledger and Langfuse, compared against the recorded baseline.

**Risks and assumptions.** Assumes the provider's null is at least partly a reporting omission (so a smaller prefix lowers the uncached bill even if the reported share stays noisy); assumes the extraction quality is not sensitive to the skill being a system message rather than a re-appended one; assumes the prose re-injection removal (a separate, quality-affecting step) is validated on its own.

---

## 3. OBSERVE

### 3.1 The shared pattern (the premise under test)

All three proposers build `[SystemMessage(prompt), HumanMessage(task)]` per call and append it to their own per-run `stateful_turn` thread (`AnalysisSession(run_id, role)`), over the process-wide pooled checkpointer:

- `assigner`: ONE call per chunk (`assigner.py:521-524`), `schema=L1DeltaBatch`.
- `data_modeller`: TWO calls per chunk (`data_modeller.py:744-748` reflection `schema=None`; `data_modeller.py:770-771` extraction `schema=L1DeltaBatch`).
- `mechanism_typist`: THREE calls per chunk (`mechanism_typist.py:481-484` reflection `schema=None`; `:499-502` systems `schema=L1DeltaBatch`; `:507-511` linking `schema=L1DeltaBatch`).

The `SystemMessage` is re-added to `new_messages` on every call, so the checkpointed trail accumulates one identical copy of the role prompt per call. `run_session_turn` streams `{"messages": list(new_messages)}` into the agent (`session.py:563-565`), so the checkpointer appends them; the provider sees the whole growing thread each call.

### 3.2 The system prompts are static

All three prompts are read from a file once and memoized in-process, FAIL-CLOSED on a missing file: `technical-system.md` (46 lines, 8,056 chars), `assigner.md` (72 lines), `data-plane.md` (51 lines). None contains a timestamp or any per-call dynamic content. So the system prompt does NOT evolve. The operator's "system prompt evolving" hypothesis is refuted at the source.

### 3.3 The role configs are identical

`providers.py:486-488`: `assigner`, `mechanism_typist`, `data_modeller` are all `Role(..., "session", "medium")` on the same model key `LLM_ANALYSER`. So the reasoning level does NOT differ. The operator's "configured without reasoning or low" hypothesis is refuted at the config.

### 3.4 The reasoning-replay path is shared

`stateful_turn` -> `run_session_turn` resolves the capability profile at turn construction (`session.py:542`, `_resolve_reasoning_profile`) and, on the return path, `_replay_reasoning` re-persists every assistant message that carried parseable reasoning via `agent.update_state` (`session.py:427-459`, `reasoning.py:255-304`). The path is role-agnostic; nothing branches on `mechanism_typist`. So a reasoning-replay bug cannot be role-specific by construction. The operator's "reasoning chunks wrongly parsed for mechanism_typist" hypothesis is refuted at the seam.

### 3.5 The cache data (the decisive observation)

Live Langfuse generations for the run, grouped by role tag, `usageDetails.input` (fresh) and `usageDetails.input_cache_read` (cached):

| role | calls with input | `input_cache_read` null | numeric | sum fresh | sum cached | cached share |
|---|---|---|---|---|---|---|
| `mechanism_typist` | 46 | 43 | 3 | 5,005,953 | 168,832 | ~3% |
| `assigner` | 14 | 0 | 14 | 59,283 | 429,056 | 87.9% |
| `data_modeller` | 26 | 0 | 26 | 348,846 | 2,026,368 | 85.3% |

Per-call shape:

- `assigner` call 1: `in=32 cache=4736`; then `in~4700 cache` grows 4736, 9472, 14336, ... The whole prior thread is cached; only the new chunk is fresh.
- `data_modeller` call 1: `in=4103 cache=0`; call 2: `in=12144 cache=2048`; then fresh stays ~13-15K while cached grows to ~165K.
- `mechanism_typist`: `in` grows 2714 -> 8377 -> 16306 -> ... -> 204327 with `cache` NULL throughout; the only numeric reads are `cache=0` at 11:05:04, `cache=167040` at 11:06:45, `cache=1792` at 11:09:03.

So the `mechanism_typist` fresh input grows with the WHOLE thread, i.e. the provider does not re-anchor its prefix cache, while the other two re-anchor every call. The distinction is role-specific and present from call 1.

### 3.6 The message structures differ

From the Langfuse `input` (truncated at ~259K chars) for the last call of each role:

- `mechanism_typist` role sequence: `[system, assistant, tool, assistant, tool, ... (8 tool pairs) ..., system([running summary]), user, assistant, system(skill), user, assistant]`. System-content lengths seen: `[8161, 10265, 8156]` - the skill (8056) re-appears, plus a running-summary system message.
- `data_modeller` role sequence: `[system, assistant, tool, ..., system([running summary]), assistant, system, user, assistant, tool, system, user, assistant, ...]`. System-content lengths: `[10747, 5947, 10742, 10742, ...]`.

Both interleave system messages and tool pairs; the `mechanism_typist`'s early region is dominated by `assistant, tool` pairs with the reflection prose embedded in the later user prompts, and its skill re-appears mid-trail.

---

## 4. HYPOTHESIZE

### H1 - the provider intermittently omits `prompt_tokens_details` for the `mechanism_typist` stream (ROOT HYPOTHESIS, with H2)
- Supports: 43 of 46 calls are null while the other two roles are numeric in the same run/lane/model/seconds; the prior request-capture showed the exact live bodies cache near-completely when replayed, and the wire serialization is deterministic.
- Conflicts: a reporting omission alone does not explain the monotonic fresh-input growth (if the provider cached, `input` would not equal the whole prompt).
- Test: a controlled live probe repeating the exact `mechanism_typist` bodies over a representative workload; count null vs numeric.

### H2 - the `mechanism_typist` prefix is not re-anchored because its thread is the tool-call-dense, re-embedded-system-message, running-summary one
- Supports: the only role with 3 calls/chunk and the deepest tool-pair density; its skill re-appears mid-trail and a running-summary system message sits in the middle; its fresh input tracks the whole thread.
- Conflicts: `data_modeller` also alternates no-tools/tools and interleaves system messages, yet re-anchors; so density alone is not proven sufficient.
- Test: bind the skill once, collapse the chain, and re-measure the reported share on a live run.

### H3 - the per-call `SystemMessage(prompt)` is the cause
- Supports: the skill accumulates O(calls) copies; the compaction dedup only runs at a fold, region-only.
- Conflicts: REFUTED. `data_modeller` re-adds its prompt per call (`data_modeller.py:745,770`) and caches at 85%.
- Test: n/a (refuted by the data).

### H4 - the 3-call chain / tool alternation is the cause
- Supports: `mechanism_typist` is the only 3-call role.
- Conflicts: REFUTED as a sufficient cause. `data_modeller` alternates no-tools/tools within a chunk and caches at 85%.
- Test: n/a (refuted as sufficient; still a growth multiplier).

### H5 - the reasoning is off or mis-parsed for `mechanism_typist`
- Supports: none.
- Conflicts: REFUTED. All three roles are `medium` (`providers.py:486-488`); the replay path (`session.py:427-459`) is role-agnostic.
- Test: n/a (refuted).

### H6 - the system prompt evolves
- Supports: none.
- Conflicts: REFUTED. All three prompts are static, memoized, file-backed (`assigner.py:421-436`, `data_modeller.py:640-652`, `mechanism_typist.py:437-449`).
- Test: n/a (refuted).

### H7 - the system prompt is not bound through the native `system_prompt`, so the provider's cache breakpoint is not a clean leading block
- Supports: the analysis proposers embed a `SystemMessage` in the messages, while the pod/hunting agents pass `system_prompt=` to `create_agent` (`session.py:216-217`; `pod/agents.py:138,181`; `hunting_agent.py:545`); the `mechanism_typist` thread interleaves system messages (3/chunk), so its "system prompt" is not a single stable leading block.
- Conflicts: `data_modeller` also embeds per call and caches; so the native binding is a design smell, not proven to be the role-specific trigger.
- Test: bind the skill via `system_prompt=` for the proposers and re-measure.

---

## 5. EXPERIMENT

### 5.1 The per-call cache diff (executed, decisive)
Queried Langfuse generations for the run and grouped by role tag (section 3.5). Result: `assigner`/`data_modeller` numeric every call; `mechanism_typist` null 43/46. This CONFIRMS H1's reporting shape and REFUTES H3/H4/H5/H6 as the role-specific trigger.

### 5.2 The source read (executed)
Read the three proposers' prompt builders and `stateful_invoke_fn`; read `_build_agent` and `run_session_turn`; read `reasoning.replay_assistant_reasoning`. Result: identical pattern, static prompts, identical configs, shared replay path. Confirms H3-H6 refutations.

### 5.3 The message-structure read (executed, truncated)
Read the Langfuse `input` for the last call of each role (section 3.6). Result: both interleave system messages; the `mechanism_typist` is the tool-dense one with a mid-trail skill and running summary. Supports H2 (as a contributing, not sole, cause).

### 5.4 The live replay probe (not re-run here; recorded in `348-failure-diagnosis.md` section 17)
The prior probe replayed the exact live bodies through the production `build_chat_model` and read `usage_metadata.input_token_details`: the exact bodies cache near-completely (call 1: 2816/2830; call 2: 8448/8456), the wire serialization is deterministic (same SHA1 three times), and the provider intermittently returns null. This is the strongest available support for H1 and the reason the app request is NOT the trigger.

---

## 6. CONCLUDE

### 6.1 Rooted cause (the cache)
The `mechanism_typist` cache hostility is role-specific and present from call 1. The evidence supports two compounding causes and excludes the shared pattern:
- (provider) the provider intermittently omits `prompt_tokens_details` for this role's stream (H1), so the app records 0; and
- (app) the `mechanism_typist` thread is the one whose prefix is not re-anchored (H2), so on a genuine miss the whole trail is re-billed.

The app-side lever (H2) is real and no-regret: it shrinks every call at any cache behaviour. The provider-side lever (H1) needs the measurement fix (distinguish "provider omitted the field" from "cache read zero") and a provider bug report.

### 6.2 The design smells (all analysis proposers)

1. **The role prompt is re-added per call instead of bound once (Lane A violation).** `mechanism_typist.py:482,500,508`; `data_modeller.py:745,770`; `assigner.py:522`. The correct native pattern exists and is used by the pod/hunting agents (`system_prompt=` at `session.py:216-217`). The skill is checkpointed O(calls) times (at call 8, 25.1% of the window for `mechanism_typist`).
2. **Per-turn content is duplicated within a turn.** The `mechanism_typist` reflection prose is embedded in the systems prompt (`:336`) AND the linking prompt (`:371`) AND kept as the assistant message - 3 copies/chunk. The `data_modeller` extraction prompt re-embeds the reflection prose (`:568-569`). The defined-systems block and vocabulary are rendered into two prompts.
3. **The 3-call chain over one thread is the growth multiplier.** Every chunk appends 3 prompts + 3 outputs to one run-long thread, so call cost is O(run length) with a 3x per-chunk constant.
4. **One unbounded per-run session thread.** No per-chunk or per-pass reset (#94); every call re-sends the whole run.
5. **The fold is a head rewrite.** Compaction removes old messages from the front and inserts the summary, so the cache prefix breaks from the first removed message (`compaction-cache-convergence-348-adr.md:55`).
6. **The running summary is a system message mid-trail**, so the thread carries several system messages at shifting positions.
7. **The dedup is late and partial.** `_dedup_system_messages` runs only at a fold, only over the folded region, never the exempt tail (`compaction.py:541-559`).

### 6.3 The narrow bugs

- **N1 - the `mechanism_typist` skill is re-appended per call** (`mechanism_typist.py:482,500,508`), the single clearest Lane A violation in the analysis module.
- **N2 - the reflection prose is triplicated per chunk** (`:336`, `:371`, plus the assistant trail).
- **N3 - the `data_modeller` extraction prompt re-embeds the reflection prose** (`data_modeller.py:568-569`), the same class as N2 at a smaller scale.
- **N4 - the assigner re-adds its prompt per chunk** (`assigner.py:522`) - correct output today because the provider re-anchors, but the same smell and the same latent risk if the prefix ever destabilizes.
- **N5 - the usage path records a null `prompt_tokens_details` as `cache_read = 0`** (`usage.py:107-122`), so "provider omitted" and "cache miss" are indistinguishable in the ledger and the trial record. This is the measurement bug behind the perceived 0%.

### 6.4 The framework-primitive answer (the operator's design-smell question)

The operator asked whether a native primitive exists to keep the agent's REASONING in the checkpointed context state, given the session thread is kept because "the graph does not carry the agent's reasoning".

Answer: the primitive EXISTS and is already used. A LangGraph checkpointer persists the full message trail, and an assistant message's reasoning rides its `additional_kwargs` (`reasoning_content` / `provider_specific_fields.reasoning_details`); the session seam re-persists it each turn through the official `agent.update_state` API (`session.py:427-459`, `reasoning.py:255-304`) so the next turn restores a replay-ready prefix. So the reasoning IS in the checkpointed state, and the "graph does not carry reasoning" framing is imprecise: the live graph is the write-side accumulator for PROPOSALS, while the session thread is the reasoning memory - two different stores, both persisted. The design smell is not a missing primitive; it is that the analysis proposers do not use the native `system_prompt` seam the pod/hunting agents use, and that the reasoning-carrying thread is unbounded.

### 6.5 The operator's two named bugs (confirmed)

- **Bug 1 (confirmed):** the skill should be bound through the native `system_prompt` (`stateful_turn(system_prompt=...)` -> `create_agent(system_prompt=...)`), as the pod/hunting agents do, not re-embedded as a `SystemMessage` per call.
- **Bug 2 (confirmed):** the 3-call chain over one thread is the growth multiplier; it should be re-shaped so the stable prefix is bound once and only the per-call task rides the human message.

Both apply to all three analysis proposers, not `mechanism_typist` alone.

---

## 7. Recommended work (ordered)

1. **App-side, no-regret (all proposers): bind the role prompt once via `stateful_turn(system_prompt=...)`** and delete the per-call `SystemMessage(prompt)` from `assigner.py:522`, `data_modeller.py:745,770`, `mechanism_typist.py:482,500,508`. Keep the one-shot test seam working by prepending the prompt in `_default_invoke_fn`.
2. **App-side: stop embedding the reflection prose in the later prompts** (`mechanism_typist.py:336,371`; `data_modeller.py:568-569`); rely on the stacked assistant message. Quality-affecting: validate on a live eval.
3. **App-side: reconsider the 3-call chain** (`mechanism_typist`), so one chunk contributes one bounded turn rather than three appends.
4. **Measurement: distinguish "provider omitted `prompt_tokens_details`" from "cache read zero"** in `usage.py` (N5), so the ledger and the trial record do not report a false 0%.
5. **Design: amend D7** to allow a budget-aware replay tail, because a fixed 30K tail plus the re-rendered context makes the fold fire often (`compaction-caching-investigation.md` S2).

### Acceptance criteria
- The per-call prompt for every analysis proposer carries ONE role-prompt copy; the skill's token share is constant.
- A live `mechanism_typist` lane over >= 20 calls reports a cached share at least the `assigner`'s (target >= 60%) from a source that distinguishes an omitted field from a zero.
- The `mechanism_typist` context-growth slope is materially below the observed ~8,260 tokens/call.
- Extraction quality (systems + edges) does not regress against the baseline run.

---

## 8. Open questions and honest weak links

- The Langfuse `input` is truncated at ~259K chars, so the full `mechanism_typist` vs `data_modeller` trail diff could not be read end to end; the structural difference (section 3.6) rests on the readable head and the per-call cache data.
- The live replay probe (5.4) ran after the trial, so it proves the body is cacheable but not that the cache was warm at run time.
- H1 vs H2 is not cleanly separable from the recorded data alone; the decisive test is a controlled live run after the restructuring (section 7.1) read through the N5-fixed ledger.
- Whether the provider's null is a proxy or upstream behaviour is unresolved; the gateway forwards `x-opencode-session` (verified in the pinned litellm source), so the seam to file a provider bug is the opencode-go lane.
