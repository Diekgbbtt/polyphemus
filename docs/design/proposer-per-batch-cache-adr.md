# ADR: proposer prompt-cache misses - per-batch memory, a constant request shape, and a per-role compaction threshold

**Status:** EXPERIMENT, operator-directed (2026-10-10; branch `exp/proposer-cache`, off `dev` `cfee00a`). **Amended 2026-10-11** (branch `fix/proposer-context-dedup`): the tool shape is made byte-identical by binding the factory's EXACT tool derivation, and the harness entities are carried once per batch (section 8).
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

**Implementation.** `analysis/proposer_turn.py::session_invoke_fn` now binds the role's OWN structured tool on a prose turn via the seam's `tools=` parameter, leaving the reflection's `response_format` prose. The structured turn supplies the SAME tool through `response_format`; binding it there as well would duplicate it, so only a prose turn gets the `tools=` binding (`_prose_tools`). `_prose_tools` returns the EXACT tool the agent factory builds for the structured turn - `langchain.agents.structured_output.OutputToolBinding.from_schema_spec(spec).tool` - not a hand-built `StructuredTool` (see section 8 for why the earlier hand-built shape was superseded). When the negotiated method is `ProviderStrategy` (native `response_format`, no tool) the prose turn binds nothing, and the tool set is still constant (empty on both).

**Why this keeps the reflection returning prose.** Passing the schema directly on the reflection invoke (`schema=L1DeltaBatch`) would make `stateful_turn` read its result from `structured_response` (None for a prose answer), so the reflection would be lost. Binding the tool via `tools=` instead leaves `response_format=None`, so `_to_turn` returns the assistant's prose, exactly as before. The reflection prompt still instructs "write prose, do not emit a tool call". Fail-open: an unbuildable shape binds nothing and the session still starts.

**Test.** `tests/analysis/test_proposer_turn.py::test_every_roles_prose_turn_binds_the_structured_turns_exact_tool` drives the REAL seam for all three roles and asserts the bound tool objects are EQUAL (not merely same-shaped), plus identical name/description/`tool_call_schema`/`convert_to_openai_tool`; `..._a_roles_tool_set_is_constant_across_reflection_and_extraction` and `..._covers_the_whole_mechanism_typist_chain` pin the constant set across the `P,S` and `P,S,S` chains.

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

## 8. Amendment 2026-10-11 - the exact tool, and harness entities carried once

A Langfuse trace of a run after section 3 landed showed the cache still missing on the `P,S` lanes. Two defects remained.

**8.1 Measured entity distribution.** The reflection `user` carried the streamed surface + inventory + candidate services + observations + scaffold; the following extraction `user` REBUILT and re-sent the inventory/candidate blocks (`_extraction_prompt` in `data_modeller.py`, `_systems_prompt`/`_linking_prompt` in `mechanism_typist.py`). Because the whole proposer runs in ONE session per batch, those blocks already sat in the trail when the extraction turn ran, so the re-injection was pure duplication. The streamed surface was 48% of `data_modeller`'s harness input and 61% of the typist's; the typist's average 3-turn request was half repeated entities.

**8.2 Why the tool must be byte-identical.** The provider prefix cache is a function of the serialized request, tool definitions included. A tool whose name/description/JSON schema match but whose object differs is not guaranteed to serialize the same under a future SDK; the invariant is the DERIVATION, not the shape. `_prose_tools` now returns `OutputToolBinding.from_schema_spec(spec).tool`, the exact object the agent factory builds for the `ToolStrategy` structured turn, so the two turns cannot drift. The test asserts object equality, not just `convert_to_openai_tool` equality.

**8.3 Harness entities once per batch.** The reflection `user` is the single carrier of the role/goal header, the known-items inventory, the candidate owning services, the streamed surface, the origin observations, and the CoT scaffold. The extraction and linking `user` messages carry ONLY their own instruction and refer to what the reflection already showed. `data_modeller._extraction_prompt` drops its inventory + candidate blocks; `mechanism_typist._systems_prompt` drops the `CURRENTLY-DEFINED SYSTEMS` block; `_linking_prompt` drops the already-defined-systems half of its list (it keeps the Systems proposed this step, which are its own input). The static `vocabulary_prompt` (the output-contract allowlist, not a harness entity) stays on the systems turn.

**8.4 Superseded decision.** The section 3 (2026-10-10) choice of a hand-built `StructuredTool` with a no-op `func` is SUPERSEDED by 8.2: it was the same shape, not the same object, and it could drift. The no-op `func` (the earlier "inert stray call") is dropped with it; the reflection prompt forbids a tool call, and the structured-output tool is only intercepted by the factory on the structured turn.

**Tests.** `tests/analysis/test_proposer_turn.py::test_every_roles_prose_turn_binds_the_structured_turns_exact_tool` (byte-identical object per role), `..._within_a_batch_the_reflection_user_is_the_shared_prefix` (shared prefix + fresh thread per chunk); `tests/analysis/test_data_modeller.py::test_extraction_prompt_does_not_reinject_the_inventory_or_candidates`; `tests/analysis/test_mechanism_typist.py::test_N6_extend_prompt_shows_existing_description_and_demands_enrichment` (adjusted: the description rides the reflection, not the extraction) and `::test_linking_prompt_does_not_reinject_the_defined_systems_inventory`.
