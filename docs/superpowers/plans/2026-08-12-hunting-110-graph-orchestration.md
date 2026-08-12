# Hunting-110: Stateful per-fault-unit graph orchestration + app-runtime seam wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single batched gate turn of the hunting orchestration pass with ONE flexible LangGraph `StateGraph` workflow: a supervisor-state schedule loop that drives per-fault-unit(s) stateful LLM-analysis stretches (each stretch chaining multiple tool_call-responses with deterministic termination) interleaved with deterministic stages (park/resume, mint, dispatch, budget), keeping the current async-native actor model shape - the `HuntOrchestratorActor` per run stays stateful throughout all pairs and remains live listening for messages after the graph completes. Then wire the hunting module's runtime obligations against the ratified seam (`hunting-module-runtime-seam.md`): `start_hunting` lifecycle, `hunting_runs` status table + startup reconcile, three endpoints, fixed store path, tear-down flush. Re-derive the existing assertion catalogue (unit / C1-C12 / E3-E16) to the new engine.

**Architecture:**

- **The engine** (contract item 2: ONE flexible graph, not one per pair): a supervisor-state schedule loop modelled on `analysis/supervisor.py`. The supervisor is the single routing authority (`Command(goto=...)` only from it - DP-5: both-paths-fire impossible). Two phases in one graph:
  - **REASON phase**: the supervisor pops the next candidate pair from `schedule` and routes via `Command(goto="reason")`. The `reason` node runs THAT pair's stateful turn on the run's `hunting_orchestrator` thread (same actor, same session, monotonic across pairs), then returns to the supervisor via a static edge (the loop restarts naturally). Carried directions accumulate on the `directions` reducer. Empty schedule -> `Command(goto="budget")`.
  - **BUDGET stage** (deterministic, batch): `budget_fn` over the whole carried set (preserves O9/C12 semantics) writes cut trail events, sets `worklist`.
  - **DISPATCH phase**: the supervisor pops each allowed direction and routes via `Command(goto="dispatch")`. The `dispatch` node does park/resume + rematch (yellow), deterministic mint, then the dispatch with inline back-edge rounds (S5/S6/D67-14), writes trail events, returns to the supervisor. Empty worklist -> `Command(goto=END)`.
  - Determinism: last-write for single-writer channels (`schedule`, `current`, `worklist`, `phase`); exactly TWO append-only reducer channels - `directions` (the pair accumulator consumed by budget) and `trail` (report bookkeeping), mirroring the supervisor's `receipts` discipline.
- **The LLM-analysis stretch** (operator-ratified): the `reason` node is instantiated via `Command`. It synchronously invokes the actor's gate turn (`_resolve_orchestrator().reason(...)`, `actors.py:244`) for the single pair, with the orchestrator's tools bound (back-edge, store reads, read-only graph view) so the model chains multiple tool_call-responses in-turn. **Termination is deterministic**: the structured-output `GateDecision` (ToolStrategy, `actors.py:210-218`) is a step without a tool call, and the mint stage that follows a carried direction IS the config-creating terminal step; the #73 escalating-timeout retry bounds the turn. A dead actor returns None and the pair is carried (fail-open, unchanged).
- **Actor lifecycle change**: `arun_orchestration` no longer reaps the actor in `finally` (`hunt_orchestrator.py:694-696`). The actor is resolved from a per-run registry (analysis `_SUPERVISORS` pattern) and survives graph completion to stay live listening; the module's stop path reaps it. `run_orchestration` stays the thin sync wrapper.
- **Seam wiring** (contract sections 3.1-3.5): `start_hunting` coroutine sets hunting module context and runs orchestration then persists terminal status; `hunting_runs` DDL + accessors + `reconcile_orphaned_hunting_runs` in `app/clients/pg.py` (additive migration, mirrors `reconcile_orphaned_analysis_runs`); three endpoints as an additive block in `project_management/api.py` (`POST /projects/{id}/hunting`, `POST .../{hunting_run_id}/stop`, `GET .../{hunting_run_id}`); `HuntStore` default at the FIXED path `src/polymerhus/attack/hunting/data/hunts/`; tear-down flush hook (fail-open).
- **Control-plane dependency**: `app/runtime.py` (runtime.schedule / cancel_run / module_context) is NOT yet on `dev` - it lands with the module-runtime-independence PR first, and #110 rebases (seam doc 3.3, sequenced landings). So the marshalling harness imports `app.runtime` lazily and degrades fail-open (503 "hunting runtime unavailable") when absent; tests inject a fake runtime. No file written here conflicts with the runtime PR (checked: seam doc 3.3).

**Tech Stack:** Python 3.13, LangGraph `StateGraph` / `Command` / `END` / `START` (already a dependency of the analysis/recon graphs), the existing `HuntOrchestratorActor` mailbox actor, `app/llm/checkpoints.py` pooled session checkpointer, psycopg, pytest. No new third-party dependencies.

## Global Constraints

- Do not reimplement or relocate the O1-O10 canon's seam shapes: `DeliveredCandidate`, `GateInput`, `GateDecision`, `EnvisionedDirection`, `HuntConfig`, `DispatchResult`, `MatchVerdict`, `OrchestratorReport`, `OrchestratorTools`, `ReadOnlyGraphView`, `revival_key`, `normalize_candidates`, `mint_hunt_config`, `build_back_edge_request`, `_record_back_edge`, `_write`, `_unresolved`, `_await_seam`, `_resolve_orchestrator` stay in `attack/hunting/hunt_orchestrator.py`. The O1-O10 canon is SINGLE-SOURCED; the graph is its engine, `run_orchestration` its thin sync wrapper.
- Every injected collaborator (`reason_fn`, `rematch_fn`, `dispatch_fn`, `kb_retrieve_fn`, `budget_fn`, `orchestrator_factory`, `tools`) keeps its exact signature so the existing unit / C1-C12 / E3-E16 catalogue drives the graph identically. `dispatch_fn` is consumed per config (contract item 3): the dispatch node builds the hunting agent per `HuntConfig` via `build_hunting_agent(...)` (per-config harness) with `dispatch_fn` as the injected override.
- Determinism: routing ONLY from the supervisor via `Command(goto=...)`; static edges everywhere else; one logical writer per super-step; two reducer channels only (`directions`, `trail`). No `Send` fan-out in this graph (single orchestrator thread).
- Fail-open on every collaborator (KB, back-edge, graph view, store, dispatch, actor): the run always advances to a terminal report. No hunting code raises through the control plane (seam 3.5).
- Record ordering (C11/IA-7): the graph is sequential, so `config < dispatch < result` `_seq` ordering is preserved by construction.
- No store tool for the LLM (seam 3.4): fault attributes ride the initial prompt; the store stays the append-only audit trail.
- Tests run with `.venv/bin/pytest` from repo root; unit/integration must not need live LLM/Neo4j (inject fakes). All graph nodes remain importable with no I/O at import (CODING_STANDARD §6).
- Keep the model current: update `attack/hunting/CONTEXT.md` (engine shape, actor lifecycle, seam obligations) in the same change.

---

### Task 1: Graph state + node topology (TDD, engine skeleton)

**Files:** Create `src/polymerhus/attack/hunting/orchestrator_graph.py`; Test `tests/attack/test_orchestrator_graph.py`.

**Interfaces - Produces:**
- `HuntOrchestrationState` (TypedDict): `project_id`, `run_id` (last-write); `schedule: list[DeliveredCandidate]`, `current`, `worklist: list[EnvisionedDirection]`, `phase` (last-write); `kb_evidences`, `kb_degraded`, `surface`, `tools`/`store` refs (read-only, assembled by the driver); reducer channels `directions: Annotated[list, operator.add]` and `trail: Annotated[list, operator.add]`.
- `build_hunting_graph(*, reason_node=None, budget_node=None, dispatch_node=None) -> StateGraph` - build (do NOT compile): `START -> supervisor`; supervisor routes via `Command(goto=...)` only; `reason -> supervisor` (static), `dispatch -> supervisor` (static); supervisor -> `Command(goto=END)` on empty worklist. Injecting node closures is the seam for tests (mirror `build_supervisor_graph`).
- `_supervisor(state) -> Command`: REASON phase - pop `schedule` head -> set `current` -> `Command(goto="reason")`; empty -> `Command(goto="budget")`. DISPATCH phase - pop `worklist` head -> `Command(goto="dispatch")`; empty -> `Command(goto=END)`.
- `_reason(state) -> dict`: the LLM stretch for `state["current"]`; appends the pair's `GateDecision` outcome(s) to `directions` + trail events; fail-open carries.
- `_budget(state) -> dict`: deterministic batch `budget_fn` over `directions`; sets `worklist`, `phase="dispatch"`, writes cut trail events; returns via static edge to supervisor (set phase in returned update, supervisor sees it).
- `_dispatch(state) -> dict`: park/resume + rematch for yellow, deterministic mint, per-config dispatch (build_hunting_agent or injected `dispatch_fn`), inline back-edge rounds, trail events.

- [ ] **Step 1:** Write `tests/attack/test_orchestrator_graph.py` (no LLM/Neo4j): assert `build_hunting_graph()` compiles; a schedule of 2 pairs with fixture reason/dispatch nodes visits supervisor-reason-dispatch-supervisor-... in order and ENDs on an empty worklist; an empty schedule ENDs after budget; routing never fires both paths (a single `Command` return shape); `directions`/`trail` reduce (append) not overwrite; a raising reason node carries the pair (fail-open) and the graph still reaches END.
- [ ] **Step 2:** Run `.venv/bin/pytest tests/attack/test_orchestrator_graph.py -v` -> FAIL.
- [ ] **Step 3:** Implement `orchestrator_graph.py`.
- [ ] **Step 4:** Run -> PASS.
- [ ] **Step 5:** `git commit -m "feat(hunting): supervisor-state orchestration graph skeleton (#110)"`.

---

### Task 2: Re-source the canon through the graph engine (TDD)

**Files:** Modify `src/polymerhus/attack/hunting/hunt_orchestrator.py`; Test `tests/attack/test_hunt_orchestrator.py` (existing suite must stay green).

**Interfaces - Produces:**
- `arun_orchestration(...)` keeps its exact signature and becomes: normalize (intake, counts) -> KB evidence per fault -> surface read -> build `HuntOrchestrationState` -> compile `build_hunting_graph()` IN-MEMORY per pass -> `ainvoke` -> derive `OrchestratorReport` deterministically from `{intake counts + trail}`. The actor is resolved from a per-run registry, NOT reaped in `finally`.
- `HuntingActorRegistry`-style per-run actor resolution in the driver (lazy, keyed by run_id) so the SAME `HuntOrchestratorActor` (same `hunting_orchestrator` thread) serves every pair of the pass and survives for the next pass.
- All node closures delegate to the existing canon helpers (`mint_hunt_config`, `build_back_edge_request`, `_write`, `_record_back_edge`, `_unresolved`, `_await_seam`) - the canon stays single-sourced.

- [ ] **Step 1:** Run the existing `tests/attack/test_hunt_orchestrator.py` -> confirm green on current code (baseline).
- [ ] **Step 2:** Re-wire `arun_orchestration` to drive the graph; keep every seam signature. Run the suite -> RED where behaviour drifted (expected: the fail-open gate-carry, park/resume, dedup, budget, ordering assertions).
- [ ] **Step 3:** Fix to GREEN, asserting the report/trail derivation is byte-identical to the old canon for the fixture inputs.
- [ ] **Step 4:** `.venv/bin/pytest tests/attack/test_hunt_orchestrator.py tests/attack/test_orchestrator_graph.py -v` -> PASS.
- [ ] **Step 5:** `git commit -m "feat(hunting): drive O1-O10 canon through the graph engine; actor lives per-run (#110)"`.

---

### Task 3: Re-derive the integration catalogue C1-C12 (TDD)

**Files:** Modify `tests/integration/test_hunt_orchestrator_contracts.py`; Test = the same file.

**Interfaces - Produces:**
- Each C1-C12 contract predicate is re-expressed against the graph engine (same assertions, driven through `run_orchestration`, unchanged seam fixtures). New assertions added where the engine changes observability:
  - C1 (empty pass O1), C2 (partial exhaustion O2/IA-1), C3 (dedup O7), C4 (malformed O10), C5 (graph-view rejects writes D67-04), C6 (dispatch degrade O6/IA-2), C7 (KB degrade D67-11), C8 (park/resume depth-1 O8/IA-6), C9 (inline back-edge routes on correlation_id IA-6/D67-14), C10 (store write failure O3/IA-7), C11 (record ordering IA-7), C12 (budget cut O9).
  - NEW contract: the LLM stretch is invoked PER PAIR and the same actor thread serves all pairs of a pass (assert via a reason_fn recording the thread/run; the fixture receives one candidate at a time). NEW: after graph completion the actor is NOT reaped - assert the registry-held actor is alive post-pass and a second pass on the same run_id reuses it (stateful across passes).
- [ ] **Step 1:** Run the existing file -> RED (engine change breaks ordering/lifecycle assumptions).
- [ ] **Step 2:** Re-derive the file to the new engine, preserving every contract's expected values from the spec.
- [ ] **Step 3:** `.venv/bin/pytest tests/integration/test_hunt_orchestrator_contracts.py -v` -> PASS.
- [ ] **Step 4:** `git commit -m "test(hunting): re-derive C1-C12 integration catalogue to the graph engine (#110)"`.

---

### Task 4: Re-derive the e2e walkthroughs E3-E16

**Files:** Modify `tests/e2e/test_hunt_orchestrator_isolated_e2e.py`; Test = the same file (live Neo4j graph grounding, read-only, lifecycle, degradations).

**Interfaces - Produces:**
- Each E3-E16 walkthrough is re-expressed against the graph engine. Real graph grounding (index_cards via `ReadOnlyGraphView`) still feeds the reason stretch; the e2e asserts the engine's loop-restart behaviour (multiple pairs in one pass) and the actor-live-after-completion property with the real store.
- [ ] **Step 1:** Run the existing file -> RED where the engine changed behaviour.
- [ ] **Step 2:** Re-derive to the new engine (same predicates, new engine-driven expectations).
- [ ] **Step 3:** `.venv/bin/pytest tests/e2e/test_hunt_orchestrator_isolated_e2e.py -v` -> PASS (requires the e2e harness/Neo4j; if the environment lacks it, mark and note - the loop verifier runs it).
- [ ] **Step 4:** `git commit -m "test(hunting): re-derive E3-E16 e2e walkthroughs to the graph engine (#110)"`.

---

### Task 5: `hunting_runs` status table + accessors + startup reconcile (TDD)

**Files:** Modify `src/polymerhus/app/clients/pg.py` + `db/postgres/init.sql`; Test `tests/unit/test_pg_hunting_runs.py` (or the existing pg test module).

**Interfaces - Produces:**
- `hunting_runs` table: surrogate `hunting_run_id` PK, `project_id`, `status` (`running -> complete | stopped | failed | interrupted`), timestamps. Additive idempotent migration in `_HUNTING_SCHEMA_MIGRATIONS` (mirror `_RECON_SCHEMA_MIGRATIONS`), mirrored in `init.sql`.
- `create_hunting_run(project_id) -> hunting_run_id` (status `running`); `set_hunting_run_status(hunting_run_id, status)`; `get_hunting_run(hunting_run_id) -> row | None`; `list_hunting_runs(project_id)`.
- `reconcile_orphaned_hunting_runs()` - flips orphaned `running` rows to `interrupted` (mirror `reconcile_orphaned_analysis_runs`, idempotent).
- [ ] **Step 1:** Write the test (inject a fake pool / use the existing pg test harness): status lifecycle, get/list, orphan reconcile.
- [ ] **Step 2:** Run -> FAIL.
- [ ] **Step 3:** Implement the migration + accessors + reconcile.
- [ ] **Step 4:** Run -> PASS.
- [ ] **Step 5:** `git commit -m "feat(hunting): hunting_runs status table, accessors, startup orphan reconcile (#110)"`.

---

### Task 6: `start_hunting` lifecycle + fixed store path + tear-down (TDD)

**Files:** Create `src/polymerhus/attack/hunting/runtime.py`; modify `attack/hunting/hunt_store.py`; Test `tests/attack/test_hunting_runtime.py`.

**Interfaces - Produces:**
- `start_hunting(project_id, *, run_id=None, candidates, ...) -> hunting_run_id`: coroutine entry point. Sets the hunting module context for its full duration (a ContextVar + context manager mirroring the seam's `module_context("hunting")` semantics; must interoperate when the control plane lands). Creates the `hunting_runs` row (`running`), runs orchestration (the graph engine), persists `complete`, reaping the run's actor via the stop path. Fail-open: any collaborator failure still persists a terminal status, never raises.
- `stop_hunting(hunting_run_id)` - phase-1 hard stop: cancels the run's task + reaps its actor, persists `stopped` (the append-only store preserves the partial trail).
- `flush_hunting_checkpointer()` - the tear-down flush hook (in-memory checkpointer index -> pooled PG saver), fail-open.
- `HuntStore` default root = the FIXED path `src/polymerhus/attack/hunting/data/hunts/` (no env var; keep the explicit-root constructor for tests).
- The `runtime.schedule` / `cancel_run` marshalling harness: lazy `import polymerhus.app.runtime`, degrade to a local in-process fallback + warning when absent.
- [ ] **Step 1:** Write the test: `start_hunting` writes `running` then `complete`; a failing orchestration still writes a terminal status (fail-open, no raise); `stop_hunting` writes `stopped`; `flush_hunting_checkpointer` is a no-op/safe when PG is absent; store default path is the fixed path. Use a fake runtime + fake pg accessors.
- [ ] **Step 2:** Run -> FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run -> PASS.
- [ ] **Step 5:** `git commit -m "feat(hunting): start/stop lifecycle, fixed store path, tear-down flush (#110)"`.

---

### Task 7: The three seam endpoints (TDD)

**Files:** Modify `src/polymerhus/project_management/api.py`; Test `tests/.../test_hunting_api.py` (follow the existing api test conventions).

**Interfaces - Produces:**
- `POST /projects/{project_id}/hunting` - schedule `start_hunting` onto the hunting loop (via the marshalling harness), return `{hunting_run_id}` (201). 404 on unknown project.
- `POST /projects/{project_id}/hunting/{hunting_run_id}/stop` - hard-cancel, return the stopping acknowledgement.
- `GET /projects/{project_id}/hunting/{hunting_run_id}` - the run's status row (404 when absent).
- Additive block AFTER the runtime-independence PR lands; for now, guards on the harness availability with a fail-open 503 "hunting runtime unavailable" when `app.runtime` is absent (so the endpoint set is live and testable now, wired when runtime lands).
- [ ] **Step 1:** Write the test (FastAPI TestClient, mocked harness/runtime): launch returns an id; stop acknowledges; status returns the row; unknown id -> 404; runtime absent -> 503.
- [ ] **Step 2:** Run -> FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run -> PASS.
- [ ] **Step 5:** `git commit -m "feat(hunting): the three seam endpoints (launch/stop/status) (#110)"`.

---

### Task 8: Keep the model current + full-suite verification

**Files:** Modify `src/polymerhus/attack/hunting/CONTEXT.md` (+ `CONTEXT-MAP.md` if the engine names a new bounded term); commit together with any doc drift.

- [ ] **Step 1:** Update the hunting CONTEXT.md: the hunt-orchestrator entry (graph engine, per-pair stateful stretch, actor-lives-across-pairs), the runtime obligations (`hunting_runs`, `start_hunting`, three endpoints, fixed store path).
- [ ] **Step 2:** Full suite: `.venv/bin/pytest tests/attack tests/integration -q` (unit + integration green, no live LLM/Neo4j). If the e2e harness is available, run `tests/e2e/test_hunt_orchestrator_isolated_e2e.py`.
- [ ] **Step 3:** `git status` clean of unintended files; `git log` one commit per task, all on `feat/hunting-110-runtime-wiring`.
- [ ] **Step 4:** `git commit -m "docs(hunting): keep model current - graph engine + runtime seam obligations (#110)"`.
- [ ] **Step 5:** Hand off to the loop verifier: run the full catalogue, report the ticket for verifier APPROVAL, then open the PR against `main` (one PR per ticket).
