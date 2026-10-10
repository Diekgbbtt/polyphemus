# ADR: the agent sub-module - per-agent lifecycle control for the hunting module (#317)

*Status: RATIFIED by operator grilling (2026-10-10). This record scopes the hunting-module refactor of #317. The eval-side decoupling (issue AC1) is explicitly OUT of scope: the stable interface the eval consumes is the app module's REST API, and no eval code changes land here.*

## Context

#317 asks to "modularise the hunting module and the eval framework for independent evolution, without the current coupling".
Its acceptance criteria are (1) the eval framework depends on a stable hunting interface, not internals, and (2) the change lands without changing observable eval behaviour.

The control plane (`src/polymerhus/app/runtime.py`) already gives every module an independent lifecycle on ONE shared worker loop.
A module is a registry entry (`ModuleHandle`): its runs, its per-module `ModuleState`, and its per-module `ModuleGate`.
Per-run control exists too: `hold_session` / `resume_session` / `cancel_run` pause one run by its session id.

What does not exist is control at the granularity of a single agent inside a module.
The hunting run is a pipeline of three agent roles - the orchestrator, the hunter, and the test-executor pod - plus runtime infrastructure (the run bootstrap and the run-scoped surfer).
Today the only switches are the whole module (all three roles at once) and a single run (the bootstrap, which cancels everything).
There is no way to take the hunter down while the orchestrator and pod keep running, and the surfer that dispatches the roles has no per-role admission input.

The operator chose the following mechanism for #317.

## Decision

### 1. A new primitive: the agent sub-module

An **agent sub-module** is the implementation of one specific agent of one module.
It is the addressable unit of a module's agent hierarchy.
For hunting the agent sub-modules are exactly the three agent roles: `orchestrator`, `hunter`, `pod`.
The run bootstrap and the run-scoped surfer are runtime infrastructure, never agent sub-modules: they are the enforcement machinery and must always run.

### 2. The state is the existing `ModuleState`, over a reused `ModuleGate`

An agent sub-module carries a state typed `ModuleState` (`app/runtime.py`) and a per-role `ModuleGate` (same class).
No new state enum and no new gate mechanism are minted.
The state is re-expressed, not reinvented.

### 3. Topology: hierarchy, not replacement

The `hunting` module gate survives as the coarse whole-module switch and the `run_delivery_tick` admission check (`ModuleAdmissionRefused`).
The three role gates layer UNDER it.
A module down implies every role down; a role down leaves the module and its sibling roles up.
The module gate is not replaced: the run lifecycle (`drain` / shutdown) depends on one whole-module verb.

### 4. Granularity: per (run, role)

The gate set is per run - `hunting:{run_id}:agent-submodules:{role}`.
The project is not designed for multiple concurrent runs, so this coincides with per-role in practice.
The run id stays explicit so the surface is honest about the addressing.

### 5. The primitive is reversible and does not drain

An agent sub-module owns exactly two verbs: `start` and `stop`.
`stop` moves the role to `PAUSED`: no new dispatch for the role AND in-flight role threads pause at their next unit boundary.
`start` returns it to `RUNNING` and releases the held threads.
The sub-module never owns `drain` or `restart`; the terminal states `DRAINING` / `STOPPED` are reached only by the module's own drain and shutdown.
`start` is the single revive verb, so the parent's `resume`-versus-`restart` overlap does not exist on the sub-module surface.

### 6. Enforcement: the surfer is the one gate for dispatch

The surfer's dispatch decision (`build_run_dispatch.coro_for`) consults the target role's state.
A role that is not `RUNNING` makes `coro_for` answer `None`, which is the mover's existing "refused, stays produced, retried next tick" rule (at-least-once, never dropped).
Each dispatched role session also acquires its OWN role gate around its active stretch, so the cooperative pause holds in-flight threads at their next unit boundary exactly as the module gate does.
The orchestrator, dispatched directly by the run bootstrap, is gated at its launch point by the same role state.

### 7. A stopped role blocks quiesce by design

A stopped role leaves its dispatchable work in produced, so `run_work_remaining` stays true and the run cannot reach `complete` while the role is down.
This is intended: the switch is an operator pause, and the operator is the backstop.
The run stays `running`, not wedged.

### 8. State is in-memory and resets to `up` on boot

The role state lives on the runtime manager beside the module state.
A process start is a fresh control plane: every role starts `RUNNING`.
Nothing about the role state is persisted, and it is never restored.
Reading a role's state is PURE: a read never registers a handle, so a state read can never resurrect a role the run terminal reaped (decision 4 - handles are keyed per run and reaped at the run terminal); a declared role with no live handle reads its default `RUNNING`.

### 9. Threads keep their own stop/resume

Single-thread stop and resume are already delivered by the per-session `hold_session` / `resume_session` verbs, keyed by the thread id (session id = registry run name).
This change re-exposes them; it mints no new thread primitives.
A thread `stop` (hold) and a sub-module `stop` (role pause) are different scopes, addressed by different surfaces.

### 10. The stable interface is the app module REST API

The new control surface is REST endpoints on the existing `project_management/api.py` adapter, additive beside the current hunting routes.
The endpoints are idempotent and carry lean data contracts:

- `POST /projects/{id}/hunting/{run_id}/agent-submodules/{role}/start` and `/stop` - idempotent; a no-op when already in the target state; 404 unknown run; 422/404 unknown role.
- `GET /projects/{id}/hunting/{run_id}/agent-submodules` -> `[{role, state}]`.
- `GET /projects/{id}/hunting/{run_id}/threads` -> `[{thread_id, role, held}]` for every live thread of the run (a read surface, never a gate; the surfer and bootstrap appear here too).
- `POST /projects/{id}/hunting/{run_id}/threads/{thread_id}/stop` and `/resume` - idempotent; 404 unknown-unregistered thread.

The eval consumes this API (and its existing endpoints); it does not read hunting internals or Python seams.
No eval-side change is part of this ticket.

## Rejected alternatives

### Adapt `hold_session` / `resume_session` / `cancel_run` to be size-agnostic (option A)

Rejected as the wrong seam.
Those verbs act on ONE registered run by id, through a per-run hold event created at register.
A hold over "all threads of a role" cannot be expressed by clearing the present holds: a role thread admitted after the hold would not be held.
A role-level stop needs a role-level event consulted at the dispatch point - which is a per-role gate, not the per-run hold.
So option A forces a polymorphic verb AND still needs the role gate.

### Build new thread-management primitives (option B)

Rejected as duplication.
The per-run hold event plus the `_CURRENT_RUN_HOLD` ContextVar already IS the thread primitive, and the module gate already reads it.
A parallel primitive set would give a second source of truth for "is this thread held", and the gate would have to read both.

### Replace the module gate with three flat role gates

Rejected.
It loses the one-verb whole-module control (`pause` / `drain`) that the run lifecycle and the `run_delivery_tick` admission check depend on, and it makes "the module is running" a derived conjunction rather than one state.

## Consequences

### The good

- Each agent role gains an independent, reversible switch, expressed through the SAME state machine the module already uses, so there is one lifecycle vocabulary.
- Dispatch enforcement reuses the mover's existing refusal rule (`coro_for` -> `None` -> at-least-once), so the change is surgical at the surfer and adds no new delivery path.
- Thread control reuses the existing per-session verbs; no new mechanism.
- The public surface is the app REST API, which is the stable interface #317 AC1 names.

### The costs

- A forgotten `stop` keeps the run `running` indefinitely. Accepted: the operator is the backstop (operator ruling).
- The role state is not durable; a restart silently returns every role to `RUNNING`. Accepted and documented.
- The agent sub-module does not share the parent's full verb set, so the two surfaces are deliberately asymmetric. Accepted for cohesion (each verb addresses exactly one scope).

### Out of scope

- The eval-side decoupling work. The eval already consumes the REST API; no eval change lands here.
- Durable role state, per-role drain, and any cross-project role polling.

## Impact map (planned)

- `src/polymerhus/app/runtime.py` - an `AgentSubmoduleHandle` (`ModuleState` + `ModuleGate`) registry on the manager; the `agent_submodule_address` helper and the `UnknownAgentSubmoduleRole` refusal; the verbs `register_agent_submodule`/`start_agent_submodule`/`stop_agent_submodule`/`reap_agent_submodules`; and the PURE reads `agent_submodule_state`/`agent_submodule_states`/`agent_submodule_running` (a read never registers).
- `src/polymerhus/attack/hunting/surfer.py` - `build_run_dispatch` consults the role state per item (through the control plane's `role_running`); each role session acquires its own role gate (through the control plane's `role_gate`).
- `src/polymerhus/attack/hunting/mover.py` - the control-plane seam gains the role-state/role-gate reads (`role_running` / `role_gate`), so the surfer reads a role through the same control plane it dispatches through (no reason in the pure deduction).
- `src/polymerhus/attack/hunting/runtime.py` - the bootstrap gates the orchestrator launch on the orchestrator role state; the role gates are registered for the run.
- `src/polymerhus/project_management/api.py` - the additive REST surface (start/stop, list roles, list threads, thread stop/resume).
- `src/polymerhus/attack/hunting/CONTEXT.md` - the glossary entry (agent sub-module).
- `docs/design/domain-model.md` - the ontology entry.
- `docs/design/hunting-module-runtime-seam.md` - the seam contract amendment.
- `src/polymerhus/app/CONTEXT.md` - the runtime primitive note.
- Tests: `tests/app/test_runtime_manager.py` (role state/gate), `tests/attack/test_hunting_surfer.py` (dispatch refused when a role is down; per-role gate), `tests/attack/test_hunting_mover.py` (control-plane role reads), and an integration/e2e predicate set per `to-assertions`.
