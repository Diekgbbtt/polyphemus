# ADR: proposer prompt-cache misses - per-batch memory, a constant request shape, and a per-role compaction threshold

**Status:** EXPERIMENT, operator-directed (2026-10-10; branch `exp/proposer-cache`, off `dev` `cfee00a`).
**Amended 2026-10-11** by `service-sourced-analysis-adr.md` (D17/D26/D35): the batch unit becomes the business Service in the service-sourced mode, and the per-role compaction thresholds are re-mined for that unit (section 8). The streamed default keeps the per-chunk unit described here, byte-for-byte.
**Amended 2026-10-11** (branch `fix/proposer-context-dedup`, adopted across all proposers): the tool shape is the factory's EXACT derivation (`OutputToolBinding.from_schema_spec`), not merely the same shape, and the `tool_choice` axis is normalized so one role's turns send one wire value (section 9).
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

**Implementation.** `providers.Role` gained `compaction_threshold: float | None = None`, originally set for the two mined proposers (`data_modeller` `0.016`, `mechanism_typist` `0.08` - 2x headroom over the mined per-batch occupancy of ~8,162 and ~41,424 tokens on the 1M window). `compaction.resolve_threshold` owns the order and `resolve_window` calls it; `build_role_compaction_middleware` inherits it. The global `LLM_COMPACTION_THRESHOLD` stays the fallback (back-compatible), and every path fails fast on an unusable value.

**SUPERSEDED 2026-10-13** (`endpoint-first-prefix-adr.md`): the two per-role defaults are REMOVED. The arm E trial (same threshold values) measured a regression - compaction churn (8 `consecutive-pass cap` warnings against 0) rewrote the request prefix, dropping cache hygiene to 76.2% against arm D's 87.8%, and quality fell with it (29 aggregates against 70). The operator directed a reset to the global 0.2 for all agents, so no role carries a default and the global env is authoritative. The resolution MECHANISM is unchanged (a role default is still honoured if one is ever declared); only the two analysis defaults are gone.

**Tests.** `tests/test_llm_compaction.py::test_per_agent_threshold_env_beats_the_global`, `::test_per_agent_threshold_falls_back_to_the_module_default`, `::test_per_agent_threshold_is_validated_fail_fast`, `::test_role_compaction_middleware_reads_the_resolved_threshold`.

## 6. What this does NOT change

- The proposers' call counts, the fail-closed reflection gate, the soft pass-through, and the six shaping gates are untouched.
- The one-shot/legacy seam: `proposer_batch` is inert outside a scope, and `_prose_tools` binds nothing unless the role's negotiated method is `ToolStrategy`.
- The prompt delivery: the role prompt still rides `create_agent(system_prompt=...)` as the ephemeral leading block.

## 7. Consequences and follow-up

The three changes compose: change 1 makes the reflection/extraction tool set identical, change 2 keeps each chunk's context small so the constant prefix remains the dominant cached span, and change 3 keeps a single chunk under the compaction budget. A live eval re-measuring `cache_read` per role is the confirmation step; the plan's mined defaults are the starting values, not a proven optimum.

## 8. Amendment (2026-10-11): the batch unit becomes the Service

In the service-sourced mode (`service-sourced-analysis-adr.md`) the proposers no longer process a recon JOB's `L0Chunk`.
Stage 1 groups the whole settled surface into one global assign pass; stage 2 iterates the bootstrapped Services and runs mechanism_typist then data_modeller per Service, over the Service's aggregated slice (a `Chunk` whose `chunk_id` IS the Service slug).

Two of the three changes carry over unchanged, and their UNIT is re-scoped:

- **Constant request shape (change 1).** Unchanged and extended: every turn of a role's sub-problem chain still binds the same tool set (`AnalysisTurn` plus the analysis `notes` tool), which is what keeps the provider prefix cached across the whole chain (ADR D26).
  The reflection is now a real turn, so this property is load-bearing rather than incidental.
- **Per-batch memory (change 2).** The discriminator becomes the Service slug instead of the streamed chunk id: `run:<service-slug>:<role>` (`AnalysisSession(run_id, role_id, batch=<sanitised slug>)`, ADR D17/D18).
  The address is sanitised before it becomes a thread id, because `business_function_slug` is LLM-authored and unvalidated.

**Compaction thresholds (change 3) - re-mined, deferred to the phase-6 eval (ADR D35).** The values (`data_modeller` `0.016`, `mechanism_typist` `0.08`) were mined as 2x headroom over the per-CHUNK occupancy of ~8,162 and ~41,424 tokens on a 1M window.
The service-sourced unit's occupancy is different by construction: a per-Service slice is at most one Service's aggregated surface, and the global assign pass groups the WHOLE settled surface into one unit.
The thresholds are therefore NOT the re-mined optimum for the new unit.

Decision: leave the mined values in place for the mode's first outings, because they remain DEFENSIBLE in the safe direction - a fraction-of-window threshold that was generous for a larger per-chunk unit fires LESS often on the smaller per-Service unit, and the pass is behind a flag.
Re-mine them from the phase-6 eval's per-Service occupancy, exactly as the per-chunk values were mined, rather than guess them now.
This is recorded as deferred, with the re-mine owned by ADR D35 and the phase-6 run, so the stale value is never mistaken for a measured one.
## 9. Amendment 2026-10-11 (adopted across all proposers): the exact tool, and the `tool_choice` axis

Two further defects were measured after section 3 landed; both fixes are adopted for every proposer turn.

**9.1 The tool must be the EXACT object, not the same shape.** The provider prefix cache is a function of the serialized request, tool definitions included; a tool whose name/description/JSON schema match but whose object differs is not guaranteed to serialize the same under a future SDK, so the invariant is the DERIVATION. `_prose_tools` returns `langchain.agents.structured_output.OutputToolBinding.from_schema_spec(spec).tool`, the exact object the agent factory builds for the `ToolStrategy` structured turn, so the two turns cannot drift; the test asserts object equality, not just `convert_to_openai_tool` equality. The 2026-10-10 hand-built `StructuredTool` with a no-op `func` is SUPERSEDED.

**9.2 The `tool_choice` axis.** 9.1 made the tool object byte-identical, but a second wire axis still toggled. In the pinned `langchain` 1.3.14 the agent factory computes `tool_choice = "any" if structured_output_tools else request.tool_choice` before `model.bind_tools(final_tools, tool_choice=tool_choice, ...)`, so a structured turn binds with `"any"` while a prose turn binds with `None`. On a relaxed model (`_relax_forced_tool_choice`) with tools bound, `bind_tools` now normalizes the unset `tool_choice` to `"auto"` as well, so both turns send one identical value; `None` and `"auto"` are the same meaning with tools present. The forced rewrite is untouched and the unset normalization is gated to the relaxed rung.

**9.3 Harness entities.** The 2026-10-11 entity-dedup (one `user` carries the inventory/candidates/surface; later turns do not re-send them) was applied to the pre-workflow prompts (`data_modeller._extraction_prompt`, `mechanism_typist._systems_prompt`/`_linking_prompt`). Those functions are RETIRED by the reasoning workflow (`service-sourced-analysis-adr.md`, `analysis/reasoning_workflow.py`), which injects each sub-problem's declared `depends_on` artifacts verbatim and never re-embeds a dependency, so the dedup principle survives as the workflow's `inject` contract rather than as prompt surgery.

**Tests.** `tests/analysis/test_proposer_turn.py::test_every_roles_prose_turn_binds_the_structured_turns_exact_tool`; `tests/test_llm_providers.py::test_a6_relaxed_model_sends_one_tool_choice_for_prose_and_structured_turn`; the reasoning-workflow injection tests in `tests/analysis/test_reasoning_workflow.py`.
