# Assertions - the agent sub-module (#317)

**Scope:** work-item "the agent sub-module - per-agent lifecycle control".
**Source:** `docs/design/hunting-317-agent-submodule-spec.md` and `docs/design/hunting-317-agent-submodule-adr.md`.
**Seams under assertion:** the runtime manager's agent-sub-module verbs and role gate (module runtime seam); the surfer's dispatch builder (the mover's `coro_for` seam); the app module REST surface for agent sub-modules and threads.

## Contract predicates (integration)

### The runtime manager seam (agent sub-module verbs + role gate)

- **C1 - a booted run has its roles up.** Given module `hunting`, run `R`, registering the three role handles and reading each state -> all three are `RUNNING`. Delivery semantic: success.
- **C2 - stop is idempotent.** `stop(R, "hunter")` twice -> state `PAUSED` after each call, no error raised, one state (not two). Delivery semantic: duplicate-idempotent.
- **C3 - start releases and is idempotent.** `stop(R, "hunter")` then `start(R, "hunter")` -> `RUNNING`; a further `start` on a running role -> `RUNNING`, no error. Delivery semantic: duplicate-idempotent.
- **C4 - an unknown role is a named refusal.** `stop(R, "sorcerer")` -> a typed unknown-role error, and no role handle is created. Delivery semantic: malformed.
- **C5 - stop refuses new dispatch for the role.** With the hunter role `PAUSED`, a fresh dispatch admission for a new hunter session -> refused (`ModuleAdmissionRefused` or the role-gate refusal); zero new sessions registered. Delivery semantic: degradation.
- **C6 - the role gate holds an in-flight unit and start releases it.** A coroutine enters the hunter role gate and reaches its boundary; with the role `PAUSED` it does not pass (its next unit stays held); after `start` it passes. Two concurrent hunters with the role down -> both held; `start` -> both resume. Delivery semantic: barrier/ordering.
- **C7 - the hierarchy holds.** With the MODULE `PAUSED`, a role whose own state is `RUNNING` still does not pass its gate (the module gate dominates); after module `resume` it passes. Delivery semantic: ordering.
- **C8 - a module drain settles the role gates.** After `drain("hunting")`, the module reaches `STOPPED` and the run's role handles are reaped; no role gate admits. Delivery semantic: success.
- **C9 - state is in-memory and resets up.** A freshly started manager (no prior calls) reports every hunting role `RUNNING`. Delivery semantic: success.

### The surfer dispatch seam

- **C10 - a down hunter denies hunter dispatch.** Given a produced RATIFIED config at the surfer dispatch seam with the hunter role `PAUSED` -> the dispatch builder yields no coroutine; the mover records it refused and leaves the config in `produced/` (at-least-once). Delivery semantic: degradation.
- **C11 - a down pod denies pod dispatch.** Given a produced SPECIFIED spec with the pod role `PAUSED` -> no coroutine; the spec stays in `produced/`. Delivery semantic: degradation.
- **C12 - an up role dispatches and acquires the role gate.** With the hunter role `RUNNING`, the produced ratified config yields one hunter session, and that session holds the hunter role gate around its active stretch (a concurrently `PAUSED` role holds it). Delivery semantic: success.

### The REST surface

- **C13 - start/stop are idempotent over HTTP.** `POST .../agent-submodules/hunter/stop` twice -> `200` twice, and `GET .../agent-submodules` reports `hunter: paused` once. `POST .../start` -> `200`, `running`. Delivery semantic: duplicate-idempotent.
- **C14 - the role listing shape.** `GET /projects/{id}/hunting/{run_id}/agent-submodules` -> exactly the three roles `orchestrator`, `hunter`, `pod`, each with its current state. Delivery semantic: success.
- **C15 - the thread listing shape.** `GET /projects/{id}/hunting/{run_id}/threads` on a live run -> every live thread of the run as `{thread_id, role, held}`, including the surfer and the bootstrap threads; a non-role thread reports its derived role or `infra`. Delivery semantic: success; empty-valid when no run.
- **C16 - unknown run / role / thread fail clearly.** `POST .../agent-submodules/sorcerer/stop` -> `404` (or `422`) with a named error and no state change; `POST` on an unknown `run_id` -> `404`; `POST .../threads/{unknown}/stop` -> `404`. Delivery semantic: malformed.
- **C17 - thread stop / resume idempotency.** A live thread `POST .../threads/{id}/stop` -> `held=true`; a second `stop` -> `200`, still held (one effect); `POST .../resume` -> `held=false`; a `resume` on a not-held thread -> `200`, no-op. Delivery semantic: duplicate-idempotent.
- **C18 - no active runtime degrades cleanly.** With no active runtime, the agent-sub-module endpoints -> `503`, never an unhandled error. Delivery semantic: degradation.

## Walkthrough predicates (end-to-end)

- **E1 - a down hunter holds the run open.** Grounds: user stories 1, 3, 9; the quiesce decision.
  Entry seam: `POST /projects/{id}/hunting` (start a run) after one `POST /projects/{id}/hunting/hunt` enqueues a produced RATIFIED config, with `POST .../agent-submodules/hunter/stop` issued BEFORE the run's first surfer tick dispatches it.
  Input: project `P`, run `R`, one hunt config with the stated fault identity, hunter role `paused`.
  Live edge: the model provider (the configured eval model, live). Nothing inside this edge is substituted.
  Path: the bootstrap schedules the orchestrator and the surfer; the surfer ticks, reads the produced config, consults the hunter role state (`paused`) -> no coroutine, refused; the config stays in `hunting/orchestration/hunt_configs/produced/`; `run_work_remaining` stays true, so the run never quiesces.
  Terminal: `hunting_runs.status = "running"`; the config is still in `produced/`; zero hunter sessions live.
  Observed: `GET .../{R}` -> `running`; `GET .../agent-submodules` -> `hunter: paused`; `GET .../{R}/threads` -> the orchestrator and surfer threads, no `hunt:` thread; the produced file present on disk.
- **E2 - starting the role completes the run.** Grounds: user stories 2, 12; the at-least-once decision.
  Entry seam: `POST .../agent-submodules/hunter/start` on the run from E1.
  Input: run `R`, hunter role transitioned `paused -> running`.
  Live edge: the model provider (live).
  Path: the next surfer tick sees the hunter role `running`, dispatches the hunter for the produced config, the config moves `produced -> consumed`; the hunter authors a spec, the surfer dispatches the pod, the pod exports, the run quiesces.
  Terminal: `hunting_runs.status = "complete"`; the config in `consumed/`; the hunter and pod role gates released.
  Observed: `GET .../{R}` -> `complete`; the produced/consumed move; `GET .../threads` empty or settled for role threads.
- **E3 - a single thread stops and resumes.** Grounds: user story 7; the per-session reuse decision.
  Entry seam: `POST .../threads/{thread_id}/stop` on a live `hunt:` thread.
  Input: run `R`, live thread id `hunting:{R}:hunt:{config_id}`, `held` initially false.
  Live edge: the model provider (live).
  Path: the per-session hold clears the thread's hold event; the thread pauses at its next unit boundary but stays registered.
  Terminal: the thread id is still in the run's live registry; `held = true`.
  Observed: `GET .../threads` -> that `thread_id` present with `held: true`; after `POST .../resume` -> `held: false` and the thread continues.

Bootstrap note (operator-supplied): E1-E3 need a live project with one enqueued hunt config and a running app+runtime (the dev docker stack built from the merged branch). The model provider is the live edge and must serve requests; if the provider is quota-blocked the walkthroughs are blocked, not substituted.

## Attachment

This catalogue is attached to the `workflow` ticket for #317 and to the spec. The executable tests live in the repo test tree: contract predicates in the integration tier, walkthroughs in the e2e tier; the unit red/green loop never selects them.
