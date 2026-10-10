# Spec: the agent sub-module - per-agent lifecycle control (#317)

*Status: ratified design; implementation tracked by a single `workflow` ticket. Design decisions and rejects: `docs/design/hunting-317-agent-submodule-adr.md`. Ontology: `docs/design/domain-model.md` section 3.8.*

## Problem Statement

The hunting module runs a pipeline of three agents - the orchestrator, the hunter, and the test-executor pod - over one project run.
Today the operator has only two control granularities: the WHOLE module (pause / resume / drain), which stops all three roles at once, and a SINGLE run (the bootstrap task), which cancels everything.
There is no way to take one pipeline stage down while its siblings keep running, and the surfer that dispatches the roles has no per-role admission input.
So an operator cannot park the hunter while the orchestrator finishes planning, or stop the pod while the hunter authors specs, and the eval framework that drives the module has no stable per-agent control surface.

## Solution

Introduce the **agent sub-module**: the addressable implementation of one agent of one module, carrying its own lifecycle state and admission gate.
For hunting the agent sub-modules are exactly the three agent roles (orchestrator, hunter, pod); the run bootstrap and the run-scoped surfer are runtime infrastructure and are never sub-modules.
Each role can be started and stopped independently, layer under the module's own switch, and is enforced at the surfer's single dispatch point.
The control is exposed on the app module REST API, which is the stable interface callers (including the eval) consume.
Single-thread stop and resume reuse the existing per-session verbs.

## User Stories

1. As an operator, I want to stop the hunter sub-module without stopping the orchestrator or the pod, so that I can pause one pipeline stage in isolation.
2. As an operator, I want to start a stopped sub-module, so that dispatching for that role resumes.
3. As an operator, I want a stopped sub-module to refuse new dispatch for its role, so that no new agent of that role is started.
4. As an operator, I want in-flight threads of a stopped sub-module to pause at their next unit boundary, so that their work is preserved and can resume.
5. As an operator, I want to read each sub-module's state, so that I know what is up or down.
6. As an operator, I want to list every live thread of a run with its role and held state, so that I can index and control individual agents.
7. As an operator, I want to stop and resume a single thread by its id, so that I can control one agent instance without touching its role.
8. As an operator, I want the start and stop of a sub-module to be idempotent, so that a repeated call is safe.
9. As an operator, I want a stopped role to leave its dispatchable work in produced and hold the run open, so that nothing is dropped while it is down.
10. As an operator, I want the whole-module switch to remain, so that I can still take every role down at once.
11. As an operator, I want a module-level pause or drain to imply every role is down, so that the hierarchy is consistent.
12. As an operator, I want the surfer to be the single dispatch enforcement point, so that no agent is dispatched while its role is down.
13. As an operator, I want role state to reset to up on process start, so that a stale down never silently blocks the pipeline after a restart.
14. As the eval framework, I want the control surface on the app module REST API, so that I depend on a stable interface rather than hunting internals.
15. As an operator, I want an unknown role or thread to fail clearly, so that I can detect an addressing mistake.
16. As a maintainer, I want the agent sub-module to reuse the existing lifecycle state type and gate, so that there is one lifecycle vocabulary and one gate mechanism.
17. As a maintainer, I want the sub-module to expose only start and stop, so that its surface stays minimal and free of the parent's verb overlap.
18. As a maintainer, I want the surfer enforcement to reuse the mover's existing refusal rule, so that no new delivery path is introduced.
19. As a maintainer, I want single-thread stop and resume to reuse the existing per-session verbs, so that no parallel thread primitive exists.
20. As a maintainer, I want the run bootstrap and the run-scoped surfer to stay ungated, so that the enforcement machinery cannot deadlock itself.

## Implementation Decisions

### The primitive

- An **agent sub-module** is the implementation of one specific agent of one module. It is addressed by `(module, run, role)`; for hunting the roles are `orchestrator`, `hunter`, and `pod`.
- The run bootstrap and the run-scoped surfer are runtime infrastructure, never agent sub-modules. They must always run, because they enforce the gates.
- The role of a live session is derived from its session id: the segment after `hunting:{run_id}:` (`orchestrator`; `hunt:...` -> hunter; `pod:...` -> pod).

### State and gate

- The sub-module's state reuses the existing lifecycle state type; it mints no new enum.
- The sub-module's gate reuses the existing per-module gate class; it mints no new gate mechanism.
- The sub-module owns exactly two verbs, `start` and `stop`, and two reachable states, `running` (up) and `paused` (down). It never owns `drain` or `restart`; the terminal states belong to the module's drain and shutdown. This removes the parent's `resume`-versus-`restart` overlap from the sub-module surface.
- `stop` moves the role to `paused`: it refuses new dispatch for the role AND holds the role's in-flight threads at their next unit boundary (the cooperative pause the module gate already uses). `start` returns the role to `running` and releases the held threads.

### Topology

- Hierarchy, not replacement. The module's own state and gate survive as the coarse whole-module switch and the mover's admission check. The role gates layer UNDER the module gate: a module `pause` / `drain` takes every role down; a role `stop` pauses only that role.
- The module's `drain` / shutdown settles the role gates with the module, so no role gate outlives its run.

### Enforcement (one point)

- The surfer's dispatch decision is the single enforcement point. It consults the target role's state: a role that is not `running` makes the dispatch builder answer "no coroutine", which is the mover's existing refusal rule (the item stays produced and is retried next tick, at-least-once, never dropped).
- Each dispatched role session acquires its OWN role gate around its active stretch, so a `down` role holds its in-flight threads at the next unit boundary.
- The orchestrator, dispatched directly by the run bootstrap rather than by the surfer, is gated at its launch point by the orchestrator role's state.
- The run bootstrap starts the surfer only after the orchestrator pass is admitted: an orchestrator session REFUSED by admission fails the run and the surfer is never spun up without it. A stopped orchestrator role is different - it is a deliberate pause, so the pass is not launched but the surfer still runs, letting already-produced configs dispatch.

### Granularity and registration

- Role gates are keyed per run: `hunting:{run_id}:agent-submodules:{role}`.
- The role handles are registered when a run boots and reaped at the run's terminal path, so they never outlive the run.
- Reading a role's state is PURE: a read never registers a handle, so a state read can never resurrect a role the run terminal reaped. Only the run boot (and an explicit operator stop/start before the boot) creates a handle; a declared role with no live handle reads its default `running`.
- State is in-memory and resets to `running` on process start; it is never persisted or restored.

### Quiesce

- A stopped role leaves its dispatchable work in produced, so the run's pending-work predicate stays true and the run cannot reach `complete` while the role is down. This is intended: the switch is an operator pause and the operator is the backstop. The run stays `running`, not wedged.

### The REST surface (app module API)

Additive beside the existing hunting routes, idempotent, lean contracts:

- `POST /projects/{id}/hunting/{run_id}/agent-submodules/{role}/start` and `/stop` - idempotent (a no-op when already in the target state); `404` unknown run; `404` (or `422`) unknown role; `503` no active runtime.
- `GET /projects/{id}/hunting/{run_id}/agent-submodules` - the roles and their states.
- `GET /projects/{id}/hunting/{run_id}/threads` - every live thread of the run as `{thread_id, role, held}`; this read surface includes the surfer and the bootstrap.
- `POST /projects/{id}/hunting/{run_id}/threads/{thread_id}/stop` and `/resume` - idempotent; `404` unknown-unregistered thread; these route to the existing per-session hold / resume verbs.

## Testing Decisions

- **Seams.** Prefer existing seams: the runtime manager's public verbs (unit tier), the surfer's dispatch builder (unit/integration tier), and the app REST API (integration/e2e tier). No new seam is introduced for the control logic itself.
- **A good test is behavioural.** It drives a public verb or an HTTP call and reads back the observable state (the state value, whether a dispatch was admitted, whether a held thread resumed, the HTTP status), never internal fields.
- **Unit tier.** The runtime manager verbs: register a role handle, `stop` then `start` round-trips the state; `stop` refuses schedule for that role; a held in-flight coroutine resumes on `start`; a module drain settles the role gates; an unknown role is a named refusal.
- **Unit/integration tier.** The surfer's dispatch builder: with the hunter role down, a produced ratified config yields no coroutine (refused, stays produced); with the pod role down, a produced specified spec yields no coroutine; with the role up, dispatch proceeds and the session acquires the role gate.
- **Integration tier.** The REST surface against a live runtime manager: `start`/`stop` idempotency, the state listing, the thread listing shape, `404` on an unknown run / role / thread. Prior art: the existing hunting endpoint tests and the runtime-manager fixture tests.
- **E2E tier.** Against the docker stack built from the merged branch: boot a run, stop a role before its first dispatch, assert the produced work stays produced and the run does not reach `complete`; `start` the role and assert dispatch proceeds and the run completes. The live edge is the model provider; the target is the run's project.
- **Assertions.** The verification predicates are catalogued in `docs/design/hunting-317-agent-submodule-assertions.md`; the unit red/green loop never selects the integration/e2e predicates.

## Out of Scope

- Any eval-framework change. The eval consumes the app REST API as its stable interface; no eval code lands here.
- Durable role state.
- Per-role `drain` / `restart`.
- Agent sub-module control for the recon and analysis modules. The primitive is general, but only the hunting roles are wired in this ticket.
- Changing the module-level verbs or the per-session thread verbs.

## Further Notes

- The rejected alternatives (a size-agnostic session verb, a parallel thread-primitive set, and a flat three-gate replacement of the module gate) are recorded in the ADR.
- The design keeps exactly one mechanism per scope: the module gate (whole module), the agent-sub-module gate (one role), and the per-session hold (one thread).
- The flywheel argument for the hierarchy: the module gate is what `run_delivery_tick` consults for admission, so removing it would break the mover; layering under it is the smallest change that keeps every existing contract.
