# ADR: proposer prompt-cache misses - per-batch memory, a constant request shape, and a per-role compaction threshold

**Status:** EXPERIMENT, operator-directed (2026-10-10; branch `exp/proposer-cache`, off `dev` `cfee00a`).
**Related:** `docs/design/plans/2026-10-10-proposer-cache-experiment.md` (the directive), `docs/design/converged-agent-turn-adr.md` (the seam this builds on), `docs/design/context-compaction-95-decisions.md` (D2, the threshold), `docs/design/compaction-cache-convergence-348-adr.md` (the convergence failure mode).
**Touches:** `analysis/proposer_turn.py`, `analysis/{assigner,mechanism_typist,data_modeller}.py`, `app/llm/session_address.py`, `app/llm/providers.py`, `app/llm/compaction.py`.

---

## 1. The decision, in one line

Three surgical changes cut the analysis proposers' uncached input without changing their core model: (1) every turn of a role binds the SAME structured tool, so the request shape never toggles; (2) each streamed chunk starts a FRESH agent context (a per-batch session address); (3) compaction thresholds become per-role, so the mined per-batch values replace the global 0.90 for the two proposers whose context is small.

## 2. Root cause (measured, not re-litigated)

`data_modeller` reported `cache_read=0` on all 36 model calls while `over_budget=False` throughout (max occupancy 148,949 < 200,000), so compaction was NOT the cause. The message head was byte-stable and the trail append-only, so it was NOT an anchor cut either. The actual cause is the request SHAPE toggling every call: the reflection turn bound NO tool (`schema=None`), the extraction turn bound the `L1DeltaBatch` structured tool (the A6 voluntary rung). `data_modeller` runs strictly `P,S,P,S,...`, so no two consecutive calls shared a tool set and the provider prefix - which includes the tool definitions - never matched. `mechanism_typist` runs `P,S,S` per chunk, so its `S,S` pair shared the tool set and DID cache. The asymmetry is the signal.

A secondary amplifier: under a run-long thread, each chunk RE-INJECTED the streamed surface + inventory on top of the whole prior trail, which is what made occupancy climb while the model's own output stayed tiny (~2%).

## 3. Change 1 - the constant request shape per role

**Rule.** Across a role's calls the request's tool set is byte-identical; a prose (reflection) turn carries the same tool as a structured (extraction) turn.

**Implementation.** `analysis/proposer_turn.py::session_invoke_fn` now binds the role's OWN structured tool on a prose turn via the seam's `tools=` parameter, leaving the reflection's `response_format` prose. The structured turn supplies the SAME tool through `response_format`; binding it there as well would duplicate it, so only a prose turn gets the `tools=` binding (`_prose_tools`). The tool is the exact tool the ToolStrategy path (`structured_response_format` -> `ToolStrategy`) builds - same name, description, and JSON schema - so the two turns emit byte-identical tool definitions; when the negotiated method is `ProviderStrategy` (native `response_format`, no tool) the prose turn binds nothing, and the tool set is still constant (empty on both).

**Why this keeps the reflection returning prose.** Passing the schema directly on the reflection invoke (`schema=L1DeltaBatch`) would make `stateful_turn` read its result from `structured_response` (None for a prose answer), so the reflection would be lost. Binding the tool via `tools=` instead leaves `response_format=None`, so `_to_turn` returns the assistant's prose, exactly as before. The reflection prompt still instructs "write prose, do not emit a tool call"; the bound tool is rendered inert (same definition, a no-op function) so a stray call costs one benign tool message rather than a ToolNode error. `create_agent` is happy with an ordinary tool bearing the same definition.

**Test.** `tests/analysis/test_proposer_turn.py::test_a_roles_tool_set_is_constant_across_reflection_and_extraction` drives the REAL seam with a recording model and asserts the tool definitions`convert_to_openai_tool` are identical across the two turns and the prose turn still returns prose; `..._covers_the_whole_mechanism_typist_chain` extends it to the `P,S,S` chain.

## 4. Change 2 - stateful per batch (fresh context per streamed chunk)

**Chosen edit path: the per-batch session address (the plan's PREFERRED path).** `AnalysisSession` gained an optional `batch` discriminator (`thread = run:batch:role`, additive - with no batch the address is the documented `run:role`). The proposer bodies (`assign`, `type_mechanisms`, `model_data`) open a `proposer_batch(chunk.chunk_id)` scope around their invoke chain, and `session_invoke_fn` composes the address per call from the innermost scope. Within one chunk the reflection/extraction/(linking) turns share the thread; the next chunk addresses a fresh one.

**Why the preferred path over the fallback (reset at the dispatch boundary).**

- The fallback (`ModuleIndex.drop` per chunk in `analysis/supervisor.py`) would keep the `run:role` thread id and reset memory at dispatch. But the compaction middleware is built ONCE per run and keys its ledger by `thread_id`: resetting the same id leaves a STALE over-budget ledger entry that the next (small) trail would trip, driving spurious backstop passes and eventually the consecutive-pass cap escalation. Distinct per-batch ids give every batch its own ledger entry, so no staleness.
- The preferred path uses the existing thread-id-keyed checkpointer with no lifecycle code and no control-plane change, exactly as the plan anticipated.

**Why the chunk id is threaded by a scope, not an invoke kwarg.** The plan fixes the invoke contract at `(messages, *, schema, system_prompt)`. A new `batch=` parameter would have rippled through every injected `invoke_fn` in the unit, integration, and e2e tiers. `proposer_batch` is a ContextVar - the repo's established scoped-ambient pattern (`conversation_scope`, `module_context`) - so the chunk id reaches the seam from the body WITHOUT changing the invoke contract and without a parallel test suite. The per-batch discriminator is additive: an unscoped caller keeps `run:role`, so the observability/runtime contract is preserved.

**Note (honest debt).** The analysis run-terminal flush enumerates threads by a module-prefixed address (`_address_matches`), while `AnalysisSession.thread_id` has never carried the module prefix - a pre-existing mismatch this change does not alter. Per-batch threads remain in the in-memory index for the run's lifetime, bounded latest-only per thread.

**Tests.** `tests/test_session_address.py::test_analysis_session_batch_discriminator_is_per_streamed_chunk`; `tests/analysis/test_proposer_turn.py::test_per_batch_scope_gives_each_chunk_a_fresh_thread` (two chunks -> two distinct persisted threads; chunk 2's request carries none of chunk 1's messages) and `::test_no_batch_scope_keeps_the_run_role_thread` (back-compat); body-scope assertions in `test_data_modeller.py` and `test_mechanism_typist.py`.

## 5. Change 3 - the per-role compaction threshold

**Rule.** Resolution order: an explicit builder param > the per-agent env var `LLM_COMPACTION_THRESHOLD_<ROLE_ID_UPPER>` > the global `LLM_COMPACTION_THRESHOLD` > the role's declared default (`providers.Role.compaction_threshold`) > `0.90`.

**Implementation.** `providers.Role` gained `compaction_threshold: float | None = None`, set for the two mined proposers (`data_modeller` `0.016`, `mechanism_typist` `0.08` - 2x headroom over the mined per-batch occupancy of ~8,162 and ~41,424 tokens on the 1M window). `compaction.resolve_threshold` owns the order and `resolve_window` calls it; `build_role_compaction_middleware` inherits it. The global `LLM_COMPACTION_THRESHOLD` stays the fallback (back-compatible), and every path fails fast on an unusable value.

**Tests.** `tests/test_llm_compaction.py::test_per_agent_threshold_env_beats_the_global`, `::test_per_agent_threshold_falls_back_to_the_role_default`, `::test_per_agent_threshold_is_validated_fail_fast`, `::test_role_compaction_middleware_reads_the_role_default`.

## 6. What this does NOT change

- The proposers' call counts, the fail-closed reflection gate, the soft pass-through, and the six shaping gates are untouched.
- The one-shot/legacy seam: `proposer_batch` is inert outside a scope, and `_prose_tools` binds nothing unless the role's negotiated method is `ToolStrategy`.
- The prompt delivery: the role prompt still rides `create_agent(system_prompt=...)` as the ephemeral leading block.

## 7. Consequences and follow-up

The three changes compose: change 1 makes the reflection/extraction tool set identical, change 2 keeps each chunk's context small so the constant prefix remains the dominant cached span, and change 3 keeps a single chunk under the compaction budget. A live eval re-measuring `cache_read` per role is the confirmation step; the plan's mined defaults are the starting values, not a proven optimum.
