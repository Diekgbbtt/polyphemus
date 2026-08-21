# Hunting 84 - Test-executor Pod Regrounding Decisions (grilling 2026-08-21)

Decisions taken for the regrounding of the test-executor pod onto the dev abstractions.
Companion to `docs/design/hunting-67-test-executor-pod-spec.md` and `docs/design/domain-model.md` §3.7.
Records are operator-authoritative where marked VERDICTED; pushed-back items are deferred to distinct passes.

---

## D84-1 - Pod roles: separate model keys, session + high (Q1 + Q11 VERDICTED)

**Decision:** Register `pod_runner` and `pod_triager` in `HUNTING_ROLES` (`app/llm/providers.py`) as `session` with `thinking="high"` for both.

**Model keys:** `LLM_MODEL_POD_RUNNER` and `LLM_MODEL_POD_TRIAGER` (one env var per agent).
Precedent is `HUNTING_ROLES` one-key-per-agent (`hunting_orchestrator` / `hunting_hunter`), not the `ROLES` many-to-one analyser sharing.
`validate_hunting_llm_config` is the sole validator (hunting bootstrap), never app boot.

**Rationale:** Actor (probe stretch) and critic (classification) are distinct cognitive jobs with independent tuning surfaces.
Thinking stays `high` for both - the operator directs high-cost reasoning for the looped, feedback-driven probe/interpret work.
A future many-to-one share is a one-line `model_key` edit if tuning shows no divergence.

**Files:** `src/polymerhus/app/llm/providers.py`, `.env.example`, `docs/design/statefulness-pattern-matrix.md`, `src/polymerhus/attack/hunting/CONTEXT.md`.

---

## D84-2 - Pod session address: reuse HuntSession + canonical hash (Q2 VERDICTED)

**Decision:** Reuse the built `HuntSession(run_id, hunt_id, role_id, spec)` (`app/llm/session_address.py`) - its `spec` slot is explicitly reserved for the pod (#84 docstring).

**Shape:** `HuntSession(run_id, hunt_id, role_id="pod_runner" | "pod_triager", spec=<spec_hash>)`.
Thread id: `_compose(run_id, hunt_id, spec_hash, role_id)` -> `run:{hunt_id}:{spec_hash}:pod_runner` etc.
Matches the ratified `run:{hunt_id}:{spec_hash}:pod` reservation (`llm-role-architecture-agent-prompt.md` §0.1 line 44).

**Spec discriminator:** The parent's canonical hash `hunting_agent._canonical_hash` (sha256 of sorted-json spec) - the same function that keys the parent's experiment log (C9 idempotency).
Relocate the helper into `src/polymerhus/attack/hunting/pod/` (pure, e.g. `context.py` or `types.py`) and have `hunting_agent.py` import from the pod - pod is the substrate, parent consumes.
Ensures #85 fusion (`read_session_memory`) and #124 resume enumeration correlate by identical thread ids.

**Rationale:** No new address type; reuses the reserved, typed `SessionAddress` Protocol shape; per-role threads under one spec (recon PodSession parity - configurator/triager each own thread).

**Files:** `src/polymerhus/app/llm/session_address.py` (docstring touch only), `src/polymerhus/attack/hunting/pod/context.py` or `types.py` (helper), `src/polymerhus/attack/hunting/hunting_agent.py` (import), `src/polymerhus/attack/hunting/pod/pod.py` (address derivation), `src/polymerhus/attack/hunting/pod/graph.py` (binding).

---

## D84-3 - Async-native pod: mirror the async-actor pattern (Q4 VERDICTED)

**Decision:** Replicate the project pattern for every similar agent: `arun_pod` async + `run_pod` sync wrapper via `run_coro_blocking`, graph via `ainvoke`, every injected seam called through the `_call_maybe_await` / `_await_seam` pattern (await when async, `asyncio.to_thread` when sync).

**Rationale:** Parity with `arun_orchestration` / `build_sync_hunting_agent` (`orchestrator_graph.py`, `actors.py`).
When dispatched via the hunting agent's `_await_seam(pod, spec)` the async entry is awaited natively, not `to_thread`-ed.

**Files:** `src/polymerhus/attack/hunting/pod/pod.py`, `src/polymerhus/attack/hunting/pod/graph.py`.

---

## D84-4 - Message channels: BaseMessage + add_messages (Q5 VERDICTED, with caveat)

**Decision:** Channels hold `BaseMessage` (id-bearing) with `Annotated[list, add_messages]` - replicate project patterns consistently.

**Caveat (operator):** The full scaffold for message creating and feeding e2e is not yet created - do not make assumptions on client/server code when writing.
Implement the channel shape and reducer; leave client/server feeding wiring minimal and behind the seams until the scaffold lands.
No id-duplication assumptions; the pod's own dedup ledger (`ExperimentLog.executed`) remains the O7/C10 dedup, not `add_messages` id-merging.

**Rationale:** The langgraph review's recommended improvement; converters already exist (`context.py` `_dicts_to_lc` / `_lc_to_dicts`); future-proofs #85 fusion reads and #95's `messages` channel `add_messages` reducer.

**Files:** `src/polymerhus/attack/hunting/pod/context.py`, `src/polymerhus/attack/hunting/pod/graph.py`, `src/polymerhus/attack/hunting/pod/agents.py` (boundary conversion).

---

## D84-5 - E2E walkthroughs: bounded hunting pipeline + isolated pod scaffold (Q6 VERDICTED)

**Decision:** E2E tests execute the stack at runtime and verify production state seams.
Once `hunt-orchestrator` and `hunting hunter` are tested, use an old project with an existing L1 and a bounded, contained hunting pipeline (a couple faults from the fault KB - 2 candidates) via the real `start_hunting` path.
If the orchestrator/hunter are not yet wired, bring up the stack from this worktree with a sibling agent container, mint a sample realistic `TestImplementationSpec`, and dispatch solely the test-executor pod through a scaffold.

**Rationale:** E1 is not isolated - it rides the full chain where possible; the isolated-pod scaffold is the fallback until #110 dispatch placement lands.

**Files:** `tests/e2e/test_test_executor_pod_walkthrough.py`, `tests/e2e/test_hunting_chain_walkthrough.py` (or reuse), `tests/e2e/fixtures/eval-targets.yaml` reference.

---

## D84-6 - Compaction wiring: 95 is the owner, this module writes the correct client code (Q10 VERDICTED)

**Decision:** #95 (`feat/context-window-manager-95`) owns compaction; its branch `~/polymerhus/.claude/worktrees/95-context-compaction` is at final e2e phase and will shortly merge to `dev`.

**Client pattern to wire (inspected 2026-08-21):**

* Shared builder: `polymerhus.app.llm.compaction.build_role_compaction_middleware(role_id, window, threshold, store)` -> `AgentMiddleware` with `.manager`.
* Hunting-side helper: `polymerhus.attack.hunting.llm.build_hunter_compaction_middleware` -> `C.build_role_compaction_middleware(HUNTER_ROLE, ...)`.
* Session turn: `run_session_turn` / `arun_session_turn` accept `middleware=[compaction_mw, ...]` (plus inbox middleware for actors).
* Actor wiring: `attack/hunting/actors.py` auto-wires via `C.build_role_compaction_middleware` unless `compaction=False` (tests).

**This module's obligation:** Write the two pod-role compaction middlewares exactly as every other stateful agent does:
`build_role_compaction_middleware("pod_runner")` and `build_role_compaction_middleware("pod_triager")`, pass as `middleware=[compaction_mw]` into the `stateful_turn` / `run_session_turn` calls (the pod's runner/triager are sync leaves, so the shared `cached_role_compaction_middleware` pattern also applies if desired - see `compaction.cached_role_compaction_middleware`).
Fast-forwarding this branch onto merged `dev` will then be seamless.

**Rationale:** Replicates the pattern applied across all other agents; keeps the interface stable before 95 lands.

**Files:** `src/polymerhus/attack/hunting/pod/agents.py` or `pod.py` (middleware factories), `src/polymerhus/app/llm/session.py` consumption on merge.

---

## D84-7 - Graph-owned ContextVar (Q12 VERDICTED)

**Decision:** Respect the project pattern: the graph owns the per-instance session binding.
`runner_agent` and `triager` nodes set a pod-session ContextVar (typed `SessionContext(HuntSession(...), checkpointer)` plus the committed cursor if needed) read by the default seams.
The pod binding reads the parent's `hunt_session` ContextVar to derive `run_id` / `hunt_id` when present; direct invocation leaves `hunt_id` empty and `run_id` defaulted.

**Rationale:** Parity with recon `pod.py::pod_session_thread_id` / `default_triage_fn` and hunting `llm.py::hunt_session`.

**Files:** `src/polymerhus/attack/hunting/pod/pod.py`, `src/polymerhus/attack/hunting/pod/graph.py`, `src/polymerhus/attack/hunting/pod/agents.py`.

---

## D84-8 - Living docs in the same change (Q14 VERDICTED)

**Decision:** Land all ontology-adjacent docs in the regrounding PR (never defer):
`attack/hunting/CONTEXT.md` pod entry (session-stateful runner/triager + reused address + `clean`/`init_validation`), `statefulness-pattern-matrix.md` Hunting rows for `pod_runner`/`pod_triager`, `hunting-67-test-executor-pod-spec.md` D5 4-value -> ratified 6-value + `clean` + `init_validation`, `session_address.py` HuntSession docstring touch, `domain-model.md` §3.7 if the pod address sharpens, and the `llm-role-architecture` matrix reservation release.

**Files:** `src/polymerhus/attack/hunting/CONTEXT.md`, `docs/design/statefulness-pattern-matrix.md`, `docs/design/hunting-67-test-executor-pod-spec.md`, `docs/design/domain-model.md`, `src/polymerhus/app/llm/session_address.py`, `docs/design/llm-role-architecture-agent-prompt.md`.

---

## D84-9 - Q3.1 Inbox pooling: graph owns delivery, idle gate is runner_agent entry (Q3.1 VERDICTED)

**Decision:** Pool inbox messages in graph state (`feedback: str`, `differential: dict` as last-write channels, plus the hunter's `spec` via `PodState.spec`). The `runner_agent` node at entry is the idle gate: when `feedback`/`differential` present, compose one `HumanMessage` with the verbatim and clear the inbox channels after handing the delta to `stateful_turn`. No inbox is fed while the `create_agent` ReAct loop is mid-trajectory.

**Validation:** When this ticket is addressed the operator will give validation feedback on the graph shape. The agent implementing the graph must use `/overthink` and the harness should track internal plan execution state (acknowledged as complex given the pod's feedback-driven loop nature).

**Files:** `src/polymerhus/attack/hunting/pod/graph.py` (PodState, runner_agent node, feedback/differential channels), `src/polymerhus/attack/hunting/pod/pod.py`.

---

## D84-10 - Q3.2 Effective feeding: system_prompt + HumanMessage verbatim (Q3.2 VERDICTED)

**Decision:** Two-part feeding, both replicated ubiquitously:
- **System prompt** via the `create_agent` `system_prompt` param each `stateful_turn` call (not as a `SystemMessage` appended to the `messages` channel). The decision-tree workflow is re-presented each turn as `system_prompt`; tool responses are never re-presented as system. Current `pod/prompts.py` prompts are defective (lack bidirectional workflow) and will be rewritten under `/writing-for-agents`.
- **Feedback verbatim** as one `HumanMessage` per consumption at request level (the ubiquitous HumanMessage-as-instruction pattern), with a fixed introductory verbatim (sub-work item: craft optimal template coherent with D67-06, e.g. "Feedback from triager on variant {ref}: classification={c} note={n}. Declined attribute: {attr}. Adjust the test accordingly; this is new variant {new_ref} derived from {parent_ref}. Previous probes: {executed}.") + the filtered `ExperimentLog` slice.

**Files:** `src/polymerhus/attack/hunting/pod/prompts.py` (rewritten via writing-for-agents), `src/polymerhus/attack/hunting/pod/agents.py` (system_prompt + verbatim composer), `src/polymerhus/attack/hunting/pod/context.py` (ExperimentLog slices).

---

## D84-11 - Q3.3 Delta via inbox deletion, not committed tracking (Q3.3 VERDICTED)

**Decision:** Do not track a committed-ids set. Inbox messages are **deleted from the inbox when consumed**, reliably (graph state update clearing the `feedback`/`differential` channels via the `add_messages`/`last-write` reducer or explicit `RemoveMessage`). `new_messages` to `stateful_turn` is exactly the consumed inbox `HumanMessage` delta; the thread holds full history so no duplication tracking is needed. Reliability of deletion is the load-bearing invariant (the graph's state update must be atomic with the `stateful_turn` call).

**Rationale:** Simpler than tracking `runner_committed_ids`/`triager_committed_ids`; inbox pooling + deletion is the pattern the operator prefers when reliable. The messages channel (`add_messages` BaseMessage) itself is the thread's memory, not a separate graph copy needing a cursor.

**Files:** `src/polymerhus/attack/hunting/pod/graph.py` (inbox channels, deletion on consume), `src/polymerhus/attack/hunting/pod/pod.py` (stateful seam delta is inbox delta).

---

## D84-12 - Q3.4 Compaction determinism inside the ReAct loop (Q3.4 VERDICTED)

**Decision:** Wire `CompactionMiddleware` on the `create_agent` agent itself, not on the pod graph. The runner's `create_agent` is built with `middleware=[build_role_compaction_middleware("pod_runner")]` (and triager analogously). The ledger's `after_model` fires per model step inside the ReAct loop, `after_agent` spawns out-of-band, `before_model` barriers before the next model step inside the same `stateful_turn`. The pod graph's `runner_agent` node does not add a second barrier; it only pools inbox between session turns (Q3.1), so inbox and compaction never race inside the loop.

**Rationale:** Replicates `analysis/assigner.py` and `attack/hunting/actors.py` exactly. Guarantees compaction determinism without diverging from the D1/D4 spawn+barrier contract.

**Files:** `src/polymerhus/attack/hunting/pod/agents.py` (middleware factories), `src/polymerhus/app/llm/session.py` consumption.

---

## D84-13 - Q13 curate_messages removed (RATIFIED)

**Decision:** 95 completely replaces `curate_messages` as interim - remove it. `curate_messages` in `pod/context.py` (1200-char tool slice + 6000-token `trim_messages` window with marker) and `HUNT_POD_SESSION_TOKENS` in `pod/config.py` are deleted. Tool-body handling becomes `tool_output` offload headers (header-preserving, body stored with exact retrieval); window compaction becomes the shared `CompactionManager` (threshold, running summary, replay tail). `ExperimentLog.runner_context`/`triager_context` filtered slices remain as domain prompt construction.

**Files:** `src/polymerhus/attack/hunting/pod/context.py` (remove curate_messages), `src/polymerhus/attack/hunting/pod/config.py` (remove HUNT_POD_SESSION_TOKENS), `src/polymerhus/attack/hunting/pod/graph.py` (remove curate calls).

---

## D84-14 - Q9 Drop stateless fallback entirely (VERDICTED)

**Decision:** Drop the stateless `invoke_role` lane for both `pod_runner` and `pod_triager`. The default seams are pure `stateful_turn` (ToolStrategy, high thinking, compaction middleware on the `create_agent` agent). If the LLM does not support structured output or statefulness primitives the agents fail silently; the parallel capability-adaptive layer owns that rare case.

**Risks accepted:** Contract tier injects fakes so unaffected; direct `arun_pod` without injection and without `LLM_MODEL_POD_*` will hard-fail at `stateful_turn` (resolve_role) instead of degrading to symbolic - acceptable as rare. E1 isolated scaffold uses `symbolic_runner_step_fn` so safe; a future real-LLM E1 needs a manually seeded `HuntSession` + checkpointer. No degraded-by-fallback marker - observability relies on `stateful_turn` failure logging + the adaptive layer.

**Files:** `src/polymerhus/attack/hunting/pod/agents.py` (remove fallback branches).

---

## D84-15 - Q7 Drop the sync wrapper (VERDICTED)

**Decision:** Pod is async-only. `arun_pod` is the sole entry; the `run_pod` sync wrapper (`run_coro_blocking`) is removed. All callers - 50 contract tests, parent `_await_seam(pod, spec)` - must be async. The parent already does `_await_seam` (await when async, `to_thread` when sync); after this, the async path is the only path, so the pod is awaited natively.

**Rationale:** Mirrors the async-native hunt-orchestrator / hunting hunter; removes the last sync fallback that masked statefulness bugs.

**Files:** `src/polymerhus/attack/hunting/pod/pod.py` (remove `run_pod`, keep `arun_pod`), `tests/attack/pod/*` and `tests/integration/test_test_executor_pod_contracts.py` (migrate to `@pytest.mark.asyncio`), `src/polymerhus/attack/hunting/hunting_agent.py` `_pod_loop` already async.

---

## D84-16 - Runner = pure ReAct plan designer, KB tool must be wired (VERDICTED)

**Decision:** The runner is NOT a static decision-tree machine. It is a pure plan designer running as a `create_agent` ReAct loop: perceive a tool result, interpret, reason on the next step, repeat. The workflow graph outlines only a HIGH-LEVEL map; the plan is the kill-chain's probe phase (a procedure local to the vuln-testing domain, validating whether the hypothesised vulnerability is present), NOT a probe list.

**KB wiring hole (defect found in grilling):** `kb_retrieve` exists in `pod/tools.py` and in the prompt text, but the regrounding to `stateful_turn`/`create_agent` binds no tools (`tools=()` default). The runner must bind `tools=[exec, kb_retrieve]` on its agent - otherwise the adversarial-knowledge concretization step is impossible. Must-fix.

**Plan (vuln-testing probe phase), fixed sub-problem decomposition** (in the hunt-orchestrator a->b->c->d style):
- P0 Feasibility validation: falsify the load-bearing assumptions (contradicted -> infeasible; unconfirmed-but-uncontradicted holds, default-open); target reachable; capability/instrument obtainable (install if needed); authorization level + request context from the spec.
- P1 Concretization (KB-augmented): envision target unit failure modes; build success + failure symptom space for every variant (each operationalized into a concrete observable: status / body marker / timing delta / structural differential); enumerate the payload vector + scheme space to test (query `kb_retrieve`; author as a pool reachable by any capability-using step); mechanism primitives (from spec); weaponization step (exploit a low-impact vuln to reach the target vuln when chaining required).
- P2 Execute: ReAct perceive->interpret->next-step; control-then-intervene (baseline, minimal payload as single changed variable); minimal-first; confound anticipation (WAF/cache/redirect/rate-limit distinct from absent); precondition chaining.
- P3 Confirm exhaustion: a TERMINAL KB re-query; if the primitives returned equal the initial query's set, the space is genuinely exhausted -> conclude, hand to the triager.

**Triager role (amended):** evaluates from a THIRD-PARTY perspective whether a NEW variant that changes a fundamental parameter (and therefore the testing fields) is worth mining - never a per-lap re-derivation of the runner's plan.

**Files:** `src/polymerhus/attack/hunting/pod/agents.py` (bind `exec` + `kb_retrieve`), `src/polymerhus/attack/hunting/pod/prompts.py` (runner prompt = the plan + meta-reasoning paradigm, written under `/writing-for-agents`), `src/polymerhus/attack/hunting/pod/tools.py` (kb_retrieve as a bound tool).

---

## D84-17 - Q3.5 Runner per-stretch ReAct, note-taking final step (VERDICTED)

**Decision (Q3.5a):** ONE `stateful_turn` per ReAct stretch - a full `create_agent` invocation with `tools=[exec, kb_retrieve]` and compaction middleware. Inside it the model perceives tool results, reasons, calls the next tool, sees the `ToolMessage`, repeats; bounded by `HUNT_POD_MAX_TOOL_CALLS` (the loop cap) and the compaction barrier. The graph does NOT interrupt per tool result.

**Pattern evidence:** `crawl_agentic._run_agentic_crawl` (canonical `bind_tools` + iterate `messages.append(ai)` + append `ToolMessage` + next model call, capped by `max_iterations` + soft deadline) and `session.create_agent` (`tools`, `middleware`, `checkpointer`; `before_model` barrier fires per internal model step). The pod replicates this shape.

**Defect (1) fixed:** no experiment-log entry per tool call (noise). The harness records each tool result into the ReAct `runner_messages` trail; a NOTE-TAKING FINAL STEP (P3, space exhausted) writes ONE consolidated experiment summary from the whole stretch's logs - pure prompt verbatim, the final workflow step.

**New note-taking tool (writes AND reads, used by the triager):** requires investigation first - whether the existing experiment-log indexing algorithm + retrieval mechanism cover the note requirements, or whether new requirements surface. See Task 8 in the plan.

**Files:** `src/polymerhus/attack/hunting/pod/graph.py` (per-stretch runner node = one `stateful_turn`), `src/polymerhus/attack/hunting/pod/agents.py` (+note_tool), `src/polymerhus/attack/hunting/pod/context.py` (note store/indexing investigation).

---

## D84-18 - Q3.6 Plan lives in the ReAct session thread (VERDICTED)

**Decision:** (a) The plan lives in the model's ReAct session thread only - prompt-driven, preserved across laps via the compaction running summary. No graph-state `plan` channel. (b) (the graph state / plan tool) is exactly ticket #136's LongHorizon harness control-plane - OUT OF SCOPE here; the idea is recorded and deferred.

**Files:** none beyond prompts/session; #136 owns the plan-tool.

---

## REMAINING (distinct passes)

* **Q3 second question (verbatim)** - `/writing-for-agents` skill to craft the feedback HumanMessage template coherent with the D67-06 loop; use `/overthink` when the ticket is addressed (operator will give validation feedback).
* **Q3 third question (reasoning-bearing workflow)** - runner prompt = the D84-16 plan (P0-P3) + meta-reasoning paradigm, written as a bidirectional decision tree; the harness tracks the HIGH-LEVEL map only (per D84-17/D84-18).
* The note-taking tool's index/retrieval applicability investigation (Task 8).

---

## D84-19 - NEW DEVELOPMENT ITEM - pod-local NoteStore (sub-agent verdict 2026-08-21)

**Verdict:** A small new development item is warranted in this stream (D84-17 Task 8 outcome). The current `ExperimentLog` (a dedup/termination ledger + filtered prompt slices) CANNOT serve note-write + note-read. New requirements the experiment-log index does NOT cover:

1. A **read-side retrieval contract** - the triager reads a note by identity (per variant / per stretch) via a tool call; today retrieval is prompt-injected, never tool-mediated.
2. **Full-body verbatim summary returns** - the 1200-char `_BODY_SLICE` caps raw observation bodies; a summary note is a different object and must return un-truncated (prompt-verbatim).
3. **Per-`variant_ref` (per-stretch) note keys** - one consolidated summary per stretch; the triager must address a specific one.
4. **Multi-stretch accumulation** - notes accumulate across outer laps (each `mint_variant` -> new stretch); a store persists all summaries and reads back without loss.
5. **Indexed vs store-scoped** - recommended in-memory + D6 export (pod-local lifecycle, triager reads within the run).

**Implementation direction (sub-agent):** a pod-local `NoteStore` on the same in-memory pod seam as `ExperimentLog` (append-only, per-`variant_ref`, monotonic `_seq`), a `note_tool` write/read seam in `agents.py` / `context.py` / `graph.py`. Grep-match / `_seq` mechanics borrowed as a PATTERN from `ProjectMemoryStore`. **Do NOT import `ProjectMemoryStore` (#137/#140)**: wrong bounded context (cross-project, `(unit_id, fault_class)` namespace), note-kind enum mismatch, cross-run durability, and importing it breaches the pod's no-store boundary (spec 1.5 / `types.py:4-5`).

**OPEN (operator concern):** the boundary question - does the pod relax spec 1.5's "no store access" to persist notes beyond the run? Recommended: NO for #84 (pod-local in-memory + D6 export); revisit if a cross-run pod-note consumer appears. Needs operator confirmation during spec re-write.

---

## D84-20 - X1 NoteStore: PERSISTENT hunting test-executor memory store (VERDICTED)

**Decision:** Amend spec 1.5 **partially**: the experiment logs must PERSIST in a NEW memory store of hunting test-executors (not in-memory-only). `ProjectMemoryStore` is a hunt-orchestrator memory system, but its indexing/retrieval model INCLUDING the data model applies - replicate ALL memory-system patterns consistently:

- **Data model**: experiments keyed by `TestImplementationSpec` identifiers (spec canonical-hash), each with a child attribute containing ALL variants; each variant carries the relevant attributes encoding insightful information for later note reads.
- **Indexing/retrieval + storage**: replicate `ProjectMemoryStore` patterns - per-spec (per-id) files or keyed records, monotonic `_seq`/`_ref`, append-only, grep-match read (parent_key / key_keyword / body_keyword), read-latest.
- **NOT** a cross-project `(unit_id, fault_class)` namespace import - the pod's own test-executor memory store, keyed by spec id, living under the hunting module's store seam (sibling to the hunt store).

**Spec 1.5 amendment:** the pod "has no GRAPH access"; its experiment-memory store (spec-keyed) is its OWN write - the parent additionally persists the D6 envelope via the hunt-store write. The pod's note tool reads this pod-owned store.

**Files:** `src/polymerhus/attack/hunting/pod/` (a pod memory store module modeled on `ProjectMemoryStore`, `note_tool` write/read), spec 1.5 re-write.

---

## D84-21 - X2 Observability: whole tool-call/reason graph in the trace (VERDICTED)

**Decision:** (a) session = thread id, one trace per pod run, spans per `stateful_turn`. PLUS the operator's directive: **the trace must showcase the WHOLE tool-call/reason graph** - the full ReAct chain (each model step, each tool call, each reasoning span, the interleaved ToolMessages). If the observability seam (`get_langfuse_callbacks`, 95's `_observe_config`, cmds callbacks at construction) does NOT already surface the tool-call/reason graph, REFACTOR it to do so - the spec's "spans per loop iteration named probe/execute/observe/interpret" is superseded by the per-`stateful_turn` span set + the full ReAct graph inside it.

**Run check:** whether the current Langfuse wiring captures the inner create_agent tool-call/reason graph (it SHOULD via the model/tool chain callbacks; verify and refactor if not).

**Files:** observability wiring in `pod/pod.py` / `session.py` `_observe_config`; spec 1.8 re-write.

---

## D84-22 - X3 Harness-capability middleware: cap only, validation is the tool contract (VERDICTED)

**Decision:** G1/G2/G4 belong to the pod harness symbolic layer via a `create_agent` middleware (before_tool/after_tool/wrap_tool_call). TWO corrections from the operator:

- `HUNT_POD_MAX_TOOL_CALLS` defaults to **200** (not the pre-existing 6).
- **"Tool validation" is tautological in the tool itself:** a tool provides a contract; any request must respect it, and a wrong parameter FAILS as a tool-call request REJECTED, with an error message + code describing the semantic explicitly. The harness does NOT re-validate tool-call arguments - the tool's own contract is the validator. The harness middleware owns only the CAP (G1), RAW recording (G4), and dedup (O7).

**Files:** `src/polymerhus/attack/hunting/pod/config.py` (`HUNT_POD_MAX_TOOL_CALLS="200"`), a `build_harness_middleware` factory, spec re-write (G2 defined as tool-contract rejection, not harness validation).

---

## D84-23 - X4 Triager input = note + triager_context + variant_refs, no RunnerStep (VERDICTED; answer to X4's question)

**Decision:** The triager's `new_messages` delta is the note (from the note tool) + the filtered `triager_context` (current variant, latest observation, differential, `variant_refs`, budget) - no structured `RunnerStep` crosses the seam.

**Answer to X4's embedded question ("aren't 'recent interpretations' the variant_refs?"):** NO - `variant_refs()` is the flat list of every tried variant REF (`["v0","v1",...]`), used for non-duplication. `interpretations` are the per-variant NL classification NOTES (each `Interpretation{variant, classification, note}`), currently surfaced as the last-5 list. They are distinct objects. Design keeps BOTH: `variant_refs` (dedup) and interpretations (per-lap records) - but the consolidated NOTE (P3 final step) becomes the triager's primary reasoning artifact, superseding the raw last-5 interpretations as the summary source.

**Files:** `src/polymerhus/attack/hunting/pod/graph.py` (triager node input), `agents.py` (note_tool).

---

## D84-24 - X5 Symbolic lane removed; E1 is real e2e (VERDICTED)

**Decision:** `symbolic_runner_step_fn` is legacy deterministic stateless code; remove it. If it exists only to serve a deterministic E1 without the LLM, it should not - E1 is an e2e test and must exercise the REAL ReAct pod (`arun_pod`). The symbolic LAYER keeps its still-load-bearing pure helpers (`evaluate_symptom` as the triager's symbolic fast-path for E1's symbolically-decidable symptom, `compute_differential` for the differential) - but `symbolic_runner_step_fn` and any `curl_command`-based default-probe-only path that exists solely for E1 is deleted.

**E1 consequence:** E1 runs `arun_pod` with the real ReAct runner + the injected `exec_fn` against the live target; the default probe is issued by the RUNNER's first ReAct turn, not by a symbolic pre-issuer.

**Files:** `src/polymerhus/attack/hunting/pod/agents.py` (remove `symbolic_runner_step_fn`), `symbolic.py` (keep `evaluate_symptom`/`compute_differential`), E1 test (`tests/e2e/test_test_executor_pod_walkthrough.py`) rewrite.

**NOTE:** E1 is now LLM-dependent (the runner's default probe needs the pod_runner model wired). If E1 must remain LLM-free, that is a leading contradiction to resolve in the spec re-write (E1 in-network with the stack provides LLM, so the model IS available - acceptable).

---

## D84-25 - X6 `run_pod` removed, `arun_pod` everywhere (VERDICTED)

**Decision:** Switch fully to `arun_pod` (await-only). `__init__.py` re-exports `arun_pod`; all sync callers (contract tests, E1, any harness) migrate to async. Confirmed mechanical (Task 4 of the plan).

**Files:** `src/polymerhus/attack/hunting/pod/__init__.py`, `pod.py`, all test callers.

---

## GREY FIELD STATUS

X1-X6 all verdicted. Remaining: (a) the spec re-write itself (from `hunting-67-test-executor-pod-spec.md`), (b) the runner/triager prompt penultimate drafts (D84-9/10 operator validation), (c) E1 LLM-dependency note (D84-24). Grey field else EMPTY.

---

## D84-26 - KB retrieval tool = query_lightrag (LightRAG workstream), langgraph-native (VERDICTED)

**Decision:** The pod's `kb_retrieve` is bound as a LangChain `BaseTool` into the Runner's `create_agent` `tools=[exec, kb_retrieve]`, exactly like the hunting agent's author tool (`actors.py:356-360`: `build_lightrag_tool()` gated by `HUNTING_LIGHTRAG_TOOL` in `tools=[...]` on `create_agent`) and the canonical `bind_tools` ReAct loop (`crawl_agentic.py`). This is the ESTABLISHED codebase tool-call wiring pattern; langgraph-native `create_agent` supports it directly.

**LightRAG workstream (NOT merged to dev):** the actual KB tool + its loadable skill + the KB itself live on the `lightrag` branch - `src/polymerhus/lightrag/tool.py::LightRagQueryTool(BaseTool)` (`name="query_lightrag"`, `args_schema=QuerySpecV1`, `_run`/`_arun`), `skills/hunting/lightrag-query/SKILL.md` (the loadable usage skill via `skill_for`), and `src/polymerhus/attack/hunting/data/fault-kb.yaml`. Pulled into a separate worktree (`~/.claude/worktrees/lightrag-probe`) and evaluated on 2026-08-21.

**Findings:**
1. LangChain-native: `BaseTool` subclass with typed `args_schema` - matches the codebase pattern; fits `create_agent` `tools=[...]` directly. YES to langgraph-native abstraction.
2. `query_spec.py`'s own header: the production `QuerySpecV1` is "owned by the Polyphemus module on dev"; the prototype must respect that seam (provisional contract replaced when the dev contract lands).
3. D84-22 contract compliance: `args_schema` (pydantic) rejects a wrong parameter with a parse error before `_run` - the tool's OWN contract is the validator, matching "tool-call request rejected with explicit error" (needs prototype confirmation of the error shape).

**Boundary:** integration of the lightrag BRANCH (the tool module, the skill, the KB artifact) is a SEPARATE workstream; #84 consumes the seam (`build_lightrag_tool()` or an equivalent `kb_retrieve` `BaseTool`) once merged. The pod prototype (sub-agent 2026-08-21) validates the WIRING shape on a minimal stub.

**Files:** pod `agents.py` / `tools.py` (bind `kb_retrieve` as a `BaseTool`), the lightrag merge is the sibling stream's concern.

---

## D84-27 - Note tool on the tool surface + memory entries in prompts (VERDICTED)

**Decision (tool surface):** the pod tool surface is THREE tools, not two: `exec`, `kb_retrieve`, and the **`note_tool`** (write + read, used by the Runner at P3 and the Triager per lap). All three bound into the respective `create_agent` `tools=[...]` (Runner: exec + kb_retrieve + note write; Triager: note read + kb_retrieve).

**Decision (memory entries in prompts):** replicate the hunt-orchestrator's memory-prompt pattern EXACTLY (`orchestrator_graph.py` / `hunt_orchestrator.py` / `llm.py` `_compose_gate_prompt`'s prior-config KEY-LIST + reading-tool guidance): the pod prompts embed an INDEXABLE LIST of the pod memory's keys (per spec id + variant refs) plus note-reading guidance, so the Runner/Triager can index into the pod memory store when required. Written under `/prompt-engineering-patterns` discipline (system-vs-user split, the key-list as an indexable header, positive phrasing). This is part of the prompt work blocked on the sub-agent's taxonomy (D84-28).

**Files:** pod `agents.py` (note_tool), `prompts.py` (memory key-list + reading guidance), `pod_memory.py` (the store).

---

## D84-28 - Pod memory store keys/values/taxonomy (VERDICTED by prototype, 2026-08-21)

**Decision:** delegated to the prototype sub-agent (`impl-20260821-220932`). The sub-agent decided keys/values/taxonomy + the `NOTE_KINDS` enum for the pod memory store, replicating `ProjectMemoryStore` patterns precisely (append-only, `_seq`/`_ref`, grep-match read, read-latest) WITHOUT importing it. The pod prompts embed indexable memory-key lists (D84-27). Operator validates the prototype + taxonomy.

**Status:** sub-agent running; record its verdict + the operator's validation when it lands.

**VERDICTED 2026-08-21:** prototype GREEN (28 tests in `tests/attack/pod/`), taxonomy ratified provisionally pending operator validation:

- **Store root:** `src/polymerhus/attack/hunting/data/pod-memory/` (the hunting module's store seam, sibling to `data/hunts/`). Layout `<root>/specs/<spec_id>/notes.yaml`.
- **`spec_id`:** `canonical_spec_id(spec)` = sha256 of sorted-key JSON, byte-identical to the parent's `hunting_agent._canonical_hash` (D84-2), relocated into the pod.
- **Note key hierarchy:** `notation_key(spec_id, variant_ref, note_name) = "<spec_id>:<variant_ref>:<note_name>"` - parent index = spec id (D84-19.3 per-variant, per-stretch).
- **Note VALUE fields (the consolidation attributes, D84-20):** `{_seq, _ref, key, spec_id, variant_ref, note_name, kind, body, classification, symptom_status, differential_shape, kb_primitives_used, exhaustion_evidence, resume_point, evidence, provenance}`; `_seq` monotonic per spec, `_ref = note-<seq:04d>`; append-only; grep-match read (`parent_key` / `key_keyword` / `body_keyword`); read-latest.
- **Closed `POD_NOTE_KINDS`:** `("experiment_summary", "kb_insight", "freeform")` - `experiment_summary` = the ONE consolidated P3 note per stretch (primary triager artifact, D84-17/19/23); `kb_insight` = a KB-derived testing primitive (the `implicit_test_primitive` analogue); `freeform` = any forward-useful note.
- **Prompt-memory pattern (hunt-orchestrator replication, `_compose_gate_prompt` + `config_keys`/#141):** `MEMORY_READ_GUIDANCE` (persistent SYSTEM block: tool contract + kinds + read filters) + `compose_memory_guidance(store, spec_id)` (per-turn USER INDEXABLE key-list header) - both embedded in the Runner's lap opener and the Triager's delta; no deterministic retrieval stage, the agent indexes then calls the `note` tool.
- **Tool:** `PodNoteTool(BaseTool)` with `args_schema=NoteToolSpec` (`extra="forbid"` - D84-22), operation discriminator write/read, coded contract rejections (`NOTES_ARGS_REJECTED`, `NOTES_EMPTY_BODY`, `NOTES_BAD_KIND`, `NOTES_NO_STORE`), fail-open on None store (O10). Proven in a real `create_agent` ReAct loop (fake model): valid write persists, wrong param becomes the `Error invoking tool 'note' ... Extra inputs are not permitted` ToolMessage, valid read returns the note un-truncated.

**Files (prototype):** `src/polymerhus/attack/hunting/pod/pod_memory.py`, `note_tool.py`, `__init__.py`, `tests/attack/pod/test_pod_memory.py`, `test_note_tool.py` - all untracked in `~/.claude/worktrees/hunting-84-prototype-kb-note`, awaiting operator validation.

---

## D84-29 - StateGraph seams: pod graph sole seam, tool_exec retired (VERDICTED by prototype)

**Decision:** the pod's `graph.py` StateGraph remains the SOLE StateGraph seam; the Runner and Triager become `create_agent` sub-graphs reached from the graph's `runner_agent`/`triager` nodes via `arun_session_turn`/`stateful_turn`. NO second StateGraph level.

**Node set the re-specified graph needs** (D84-16/17/22/23 mapped):
- `init` - schema + **environment-contract** validation (extension: pre-regrounding `verification.validate_spec` ranges the typed base only; env-contract validation is an uncovered capacity in `verification.py`, not necessarily a new node).
- `runner_agent` = ONE `arun_session_turn` per stretch: `tools=[exec, kb_retrieve, note]`, `middleware=[build_role_compaction_middleware("pod_runner"), build_harness_middleware]`, `system_prompt` = the P0-P3 plan (D84-10/16), `new_messages` = the consumed inbox delta (D84-9/11). **The tool-call loop lives INSIDE `create_agent` - the `tool_exec` node DISAPPEARS; G1 cap / G4 raw recording / O7 dedup move into the harness middleware (D84-22).**
- `triager` = `new_messages` delta = the verbatim P3 note + filtered `triager_context` + `variant_refs`; its own `arun_session_turn` with `ToolStrategy(TriagerDecision)` and compaction middleware.
- `decide_router` - the six-way termination + outer cap; the literal `[POD-BUDGET CHECK]` phase could be an explicit node (a decision, not a requirement).
- `mint_variant` - unchanged (variant_ref provenance).
- Four terminals - unchanged vocabulary.
- **New phases with no covering node:** (a) INIT environment-contract validation; (b) the P3 note-write final step lives INSIDE the runner's ReAct (the runner calls the `note` tool as its final tool call) - spec corrected so `note` is on the runner's `tools=` line; (c) potential explicit POD-BUDGET CHECK node.

---

## D84-30 - Differential removed entirely (VERDICTED, work-preamble ticket T0)

**Decision:** Remove the differential machinery COMPLETELY from the pod implementation and spec. It is a legacy design artifact inherent to the pre-regrounding Runner (a structured per-turn proposer with a graph-owned baseline slot), NOT synergic with a ReAct loop. In ReAct the agent perceives each raw observation and reasons about attribution itself (confound-anticipation guides that reasoning); the normalized `compute_differential` dict imposes one fixed, lossy vocabulary (status / body_len) onto signals the runner should interpret freshly.

**Removed:** `symbolic.py::compute_differential`; `types.py::RawObservation.differential` + `PodState.baseline_obs`/`differential` + `ProbeStep` baseline role; `graph.py` differential computation + baseline slot; the `differential` param on the `runner_step_fn`/`triager_fn` seam signatures (`agents.py`) and in `context.py::runner_context`/`triager_context` + `prompts.py` ("the differential between baseline and payload", "use the differential", "structural differential"); `differential_shape` in the note value fields + `note_tool` schema (D84-28 trimmed). The "control-then-intervene" heuristic stays as a ReAct-directed habit, reworded without the machine differential.

**Keep:** `evaluate_symptom` (triager symbolic fast-path), `probe_signature` (O7/C10 dedup). `default_probe_from_spec` is within D84-24's remit.

**Filed as:** work-preamble ticket (T0) - a contained removal inside the pod package (implementation + tests + spec/ADR wording), landed BEFORE the regrounded runner builds on top.

---

## D84-31 - `resume_point` removed from the note schema (VERDICTED)

**Decision:** Remove `resume_point` from the pod note value fields + `note_tool` schema. The pod's P3 note is a TERMINAL artifact written at space-exhaustion - nothing resumes from it. The live resume state already lives in (a) the ReAct thread + compaction running summary and (b) #136's DAG harness (resume is its control-plane concern). A `resume_point` on an exhausted-stretch summary tells the triager nothing it does not get from `body` + `exhaustion_evidence`.

---

## D84-32 - Note value fields (CANONICAL, post-D84-30/31)

**Canonical NOTE value fields:** `{_seq, _ref, key, spec_id, variant_ref, note_name, kind, body, classification, symptom_status, kb_primitives_used, exhaustion_evidence, evidence, provenance}`.
`differential_shape` (D84-30) and `resume_point` (D84-31) removed.
`NoteToolSpec` write fields: `operation, variant_ref, note_name, kind, body, classification, symptom_status, kb_primitives_used, exhaustion_evidence` + read filters `parent_key`, `key_keyword`, `body_keyword`.
The prototype (`impl-20260821-220932` output) must be updated to these fields when T4 lands.
