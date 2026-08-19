# Statefulness Pattern Matrix

*Status: RATIFIED 2026-08-10 (feat/async-actor-agents). Living reference for every
agent's execution model and statefulness mechanism.*

## Matrix

Each cell records the agent's invocation function, the file:line of the call site,
and the thread identity (how concurrent instances avoid collision).

### Legend

| Dimension | Values |
|---|---|
| **Execution model** | `sync leaf` = called synchronously from a graph node or function; `async actor` = persistent `run_session_agent` loop with `AgentInbox`; `StateGraph` = LangGraph `StateGraph` compiled and invoked |
| **Statefulness** | `checkpointer (create_agent)` = `run_session_turn` / `arun_session_turn` / `stateful_turn` -> `create_agent` with a `BaseCheckpointSaver`; `ContextVar + stateful_turn` = a `ContextVar` routes to `stateful_turn` when set, `invoke_role` when absent; `invoke_role` = stateless `function_calling` call; `StateGraph checkpointer` = the graph itself is compiled with a checkpointer; `StateGraph (no checkpointer)` = the graph is compiled without one |

### Recon

| Agent | Execution | Statefulness | Invocation | Thread identity | File:line |
|---|---|---|---|---|---|
| `configurator` (pod) | sync leaf | ContextVar + stateful_turn | `_pod_ctx().get()` -> `stateful_turn` or `invoke_role` | `PodSession(run, phase, tool, asset)` via ContextVar | `pod.py:589-597` |
| `triager` (pod) | sync leaf | ContextVar + stateful_turn | `_pod_ctx().get()` -> `stateful_turn` or `invoke_role` | `PodSession(run, phase, tool, asset)` via ContextVar | `pod.py:647-653` |
| `pod_graph` | StateGraph (sync `graph.invoke`) | **StateGraph (no checkpointer)** | `pod_graph.invoke(state)` | N/A (runs in worker thread per pod) | `job_agent.py:187` |
| `job_agent` | StateGraph (sync `graph.invoke`) | **StateGraph (no checkpointer)** | `job_agent.invoke(state)` | N/A (runs in worker thread per job) | `job_agent.py:187` |
| `ReconOrchestratorActor` | async actor | checkpointer (create_agent) | `run_session_agent` -> `arun_session_turn` | `OrchestratorSession(run_id)` | `orchestrator_agent.py:202` |
| `decide_routing` (legacy) | sync leaf | invoke_role | `invoke_role("job_orchestrator", ...)` | N/A (one-shot) | `orchestrator_agent.py:110-113` |
| `crawl_agent` | async (vendored ReAct) | stateless | `_run_agentic_crawl` loop | N/A | `crawl_agentic.py:60` |

### Analysis

| Agent | Execution | Statefulness | Invocation | Thread identity | File:line |
|---|---|---|---|---|---|
| `supervisor` | StateGraph (async `ainvoke`) | **StateGraph (no checkpointer)** - in-memory, the deterministic-pipeline pattern | `compiled.ainvoke(state, config)` | `run_id` (one graph per run) | `supervisor.py:322-330` |
| `assigner` | sync leaf | checkpointer (create_agent) | `stateful_turn("assigner", address, ...)` | `AnalysisSession(run_id, "assigner")` | `assigner.py:593` |
| `mechanism_typist` | sync leaf | checkpointer (create_agent) | `stateful_turn("mechanism_typist", address, ...)` | `AnalysisSession(run_id, "mechanism_typist")` | `mechanism_typist.py:413` |
| `data_modeller` | sync leaf | checkpointer (create_agent) | `stateful_turn("data_modeller", address, ...)` | `AnalysisSession(run_id, "data_modeller")` | `data_modeller.py:704` |
| `bootstrapper` | sync leaf | invoke_role | `invoke_role("analyser", ...)` | N/A (one-shot) | `bootstrap.py:911,950` |
| `anatomy` | sync leaf | invoke_role | `invoke_role("analyser", ...)` | N/A (one-shot) | `anatomy.py:183` |
| `curation` | sync leaf | invoke_role | `invoke_role("analyser", ...)` | N/A (one-shot) | `curation.py:237` |
| `sweep` | sync leaf | invoke_role | `invoke_role("analyser", ...)` | N/A (one-shot) | `sweep.py:176` |

### Hunting

| Agent | Execution | Statefulness | Invocation | Thread identity | File:line |
|---|---|---|---|---|---|
| `HuntOrchestratorActor` | async actor | checkpointer (create_agent) | `run_session_agent` -> `arun_session_turn` | `HuntingOrchestratorSession(run_id)` | `actors.py:117` |
| `HuntingHunterActor` | async actor | checkpointer (create_agent) | `run_session_agent` -> `arun_session_turn` | `HuntSession(run_id, hunt_id)` | `actors.py:117` |
| `_hunter_turn` (legacy sync) | sync leaf | ContextVar + stateful_turn | `_hunt_ctx().get()` -> `stateful_turn` or `invoke_role` | `HuntSession(run_id, hunt_id)` via ContextVar | `llm.py:104-112` |
| `build_gate_reason_fn` (legacy) | sync leaf | invoke_role | `invoke_role(GATE_ROLE, ...)` | N/A (one-shot) | `llm.py:237` |
| `build_rematch_fn` (legacy) | sync leaf | invoke_role | `invoke_role(REMATCH_ROLE, ...)` | N/A (one-shot) | `llm.py:259` |
| `build_actor_hunting_agent` -> `build_hunting_agent` dispatch seam | async harness (dispatch_fn) | working set in closure + per-hunt `HuntingHunterActor` author/judge | `dispatch_fn(config, routed)` passed to `arun_orchestration` as the graph's `dispatch_fn` | `HuntSession(run_id, hunt_id)` via `HuntingActorRegistry` | `llm.py:332-355` (builder); `hunting_agent.py:373` (harness) |

**Hunting-agent wiring status (as of this matrix):** the harness and its production seam are BUILT but NOT wired into the runtime path. `start_hunting` (attack/hunting/runtime.py) calls `arun_orchestration` without injecting `dispatch_fn`, so the orchestration graph's dispatch node (hunt_orchestrator.py:701 `if dispatch_fn is None`) degrades to the "hunting agent unavailable" outcome and the agent is never invoked in production. The wiring is scoped by #110's "Dispatch placement" decision.

## Outliers and deviations

### OUTLIER-1: `pod_graph` and `job_agent` have no StateGraph checkpoint

**Location**: `recon/domain/pod.py:443`, `recon/control/job_agent.py:254`

Both graphs return `g.compile()` with no checkpointer argument. This means:
- A pod crash mid-execution cannot resume from the last successful super-step.
- A job agent crash loses all intermediate pod results.

**Status**: Known gap. The `pod_graph` runs synchronously in a worker thread per pod
and is retried at the job level; the `job_agent` fans out via `Send` and aggregates
results. Both are short-lived enough that checkpointing adds marginal value relative
to the complexity of wiring a checkpointer through `graph.invoke` on worker threads.
The pod's per-node fail-open discipline (each node degrades independently) provides
fault tolerance without graph-level checkpointing.

**If checkpointing is desired**: pass a checkpointer to `g.compile(checkpointer=...)`
and ensure the calling thread has access to the module's checkpointer pool.

### OUTLIER-2: (resolved) the supervisor's per-run `AsyncPostgresSaver` is gone

**Location**: `analysis/supervisor.py` (removed in `feat/supervisor-inmemory`)

The supervisor graph previously opened a fresh `AsyncPostgresSaver` +
`AsyncPostgresStore` from `POSTGRES_DSN` per run. That PG open is
**retired**: the graph is now compiled in-memory - the deterministic-pipeline
pattern (`job_agent`) - since each pass builds a fresh graph and schedule, and
the run's durable archive lives in the proposers' pooled session checkpointer
(`AnalysisSession` threads on `get_session_checkpointer`), not in the
supervisor's own.

The future full conversion of the supervisor into an async-native
actor-with-mailbox (pooled checkpointer + `create_agent`) is ticketed:
https://github.com/Diekgbbtt/polyphemus/issues/102.

### OUTLIER-3: `decide_routing` / `build_gate_reason_fn` / `build_rematch_fn` are legacy sync seams

**Location**: `orchestrator_agent.py:99`, `llm.py:226,248`

These are the pre-actor sync one-shot seams that the actor versions
(`ReconOrchestratorActor`, `HuntOrchestratorActor`) supersede. They remain as
thin compatibility wrappers for tests and rollback. The production default is the
actor path.

**Status**: Superseded. Both `decide_routing` and `build_gate_reason_fn` /
`build_rematch_fn` are wired as injectable seams; the production callers pass
`None` to use the actor path. The sync versions are retained only for test
injection and sync rollback.

### OUTLIER-4: `_hunter_turn` dual-path (ContextVar or invoke_role)

**Location**: `attack/hunting/llm.py:97-112`

The `_hunter_turn` function checks `_hunt_ctx().get()` and dispatches to
`stateful_turn` (stateful) or `invoke_role` (stateless) based on whether a
hunt-session context is bound. This is the sync rollback lane for the hunting
agent - the production async path uses `HuntingHunterActor` turns instead.

**Status**: Intentional dual-path. The ContextVar is set by `hunt_session()` context
manager in the dispatch harness; when absent (tests, legacy callers), the stateless
path is used.

### OUTLIER-5: Analysis proposers are sync leaves despite being checkpointer-backed

**Location**: `assigner.py:593`, `mechanism_typist.py:413`, `data_modeller.py:704`

The analysis proposers run `stateful_turn` which calls `run_session_turn` which
calls `create_agent` (a compiled LangGraph graph) with a checkpointer. Each turn
IS a StateGraph execution. But the proposers themselves are invoked as sync leaves
from the supervisor's graph nodes, not as async actors or standalone StateGraphs.

**Rationale**: The proposers have data dependencies on each other (assigner ->
mechanism_typist -> data_modeller per chunk) and are dispatched sequentially by the
supervisor. Making them async actors would add concurrency that the data flow does
not support. The `stateful_turn` pattern gives them session memory (chunk N+1
resumes from chunk N's reasoning) without the overhead of a persistent actor loop.

## Summary: which pattern to use when

| Scenario | Recommended pattern | Example |
|---|---|---|
| Agent dispatches subagents and needs cross-turn memory | **async actor** (`run_session_agent` + `AgentInbox`) | `ReconOrchestratorActor`, `HuntOrchestratorActor` |
| Agent is a leaf with data dependencies, needs session memory | **sync leaf + `stateful_turn`** (`create_agent` with checkpointer) | `assigner`, `mechanism_typist`, `data_modeller`, `triager`, `configurator` |
| Agent is a leaf, stateless one-shot call | **sync leaf + `invoke_role`** (no checkpointer) | `bootstrapper`, `anatomy`, `curation`, `sweep` |
| Graph orchestrates multiple nodes with routing logic | **StateGraph without checkpointer** (in-memory; durable archive lives in the spawned agents' pooled checkpointer) | `supervisor` (see #102 for the actor-model conversion) |
| Graph is a deterministic pipeline, short-lived | **StateGraph without checkpointer** (fault tolerance via node-level fail-open) | `pod_graph`, `job_agent` |

## Compaction wiring (#95)

Every `checkpointer (create_agent)` consumer is COMPACTED as of #95 (ADR
`context-compaction-95-decisions.md` D9 + the H generalisation): the compaction
middleware rides the session construction seam as an additive `middleware`
parameter, never agent-logic changes.

| Consumer | Seam | Builder |
|---|---|---|
| `assigner` / `mechanism_typist` / `data_modeller` (analysis) | `stateful_invoke_fn` builds one middleware per run, passed through `stateful_turn` | `compaction.build_role_compaction_middleware(role_id)` |
| `configurator` / `triager` (recon pod) | the pod-graph node's ContextVar path passes a process-wide per-role middleware through `stateful_turn` (manager keyed by `thread_id`, so re-witnesses share state) | `compaction.cached_role_compaction_middleware(role_id)` |
| `ReconOrchestratorActor` / `HuntOrchestratorActor` / `HuntingHunterActor` | `_ensure_started` appends the middleware to `run_session_agent` (`compaction=None` auto-wires, `False` disables) | `compaction.build_role_compaction_middleware(role_id)` |

The one-shot `invoke_role` leaves (bootstrapper, anatomy, curation, sweep, the
legacy gate/re-match/decide_routing seams) and the StateGraph-without-checkpointer
pipelines (`supervisor`, `pod_graph`, `job_agent`) are NOT compacted - they hold no
resumable session thread to compact. The sync `_hunter_turn` ContextVar rollback
lane is deliberately NOT wired (D9).
