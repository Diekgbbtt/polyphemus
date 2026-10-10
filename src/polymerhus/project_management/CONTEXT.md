# Project-management

The operator-intent surface: the Project / settings / run-request lifecycle.
This context owns what the operator *wants* - create a project, configure how it should be reconned, request a run, poll its status - not the machinery that executes a run (that is [Recon](../recon/CONTEXT.md)'s control layer).

Vocabulary derived from `docs/design/domain-model.md` and the REST surface in `docs/design/recon-pipeline-design.md` §10.5; the module layout is recorded in `docs/design/module-restructure.md`.

## Position in the map

Project-management sits *above* recon: it LAUNCHES a recon run and then treats the run as something to observe.
The dependency is deliberately one-directional and lazy - the launch endpoint imports the pipeline only at call time (`_launch_pipeline`), so recon never depends on this context and the two never cycle.
Project and settings state is read and written through the shared Postgres gateway (`app.clients.pg`), which stays a thin generic persistence layer; the operator use-cases that give that state meaning live here.

## The atoms

**Project**:
The top-level unit of operator intent - a named target engagement, identified by a `project_id`.
It carries settings and owns the runs launched against it.
`Project` is a term shared with Recon (which stamps `project_id` as the identity partition of every L0 node); its full definition is here, Recon carries the one-line pointer.

**Settings**:
The operator's configuration of a project's recon: `target_domain`, scope, and feature toggles (the [AuthContext](#authcontext) entry below is retired, #223).
Persisted as a JSON document and updated by PARTIAL PUT - a settings update deep-merges into the stored document (recursive jsonb merge in the gateway), so setting one field never wipes its siblings.
Concrete settings for the live e2e targets are held in the eval dataset `tests/e2e/fixtures/eval-targets.yaml`.

**AuthContext** (retired, #223 - removal landed T4 #243):
The superseded operator value object - how authenticated recon used to declare its credentials (cookies, autonomous-login credentials, role/realm-tagged sets, arbitrary request headers) and the settings-blob anchor of auth.
Since #223 (D223-4) it is retired with its full footprint: the value-object module and its settings validation are deleted, the per-tool header serialisation lives on in the recon auth feed re-sourced from the shared auth store, and the orchestrator binds the selected account identifier into the pipeline state for lazy per-phase resolution (D223-19) - no settings-blob auth path survives.
Operator seeding of the shared auth store remains the operator's face over that state: `PUT /projects/{project_id}/auth` (`seed_auth` -> `seed_project_auth` -> `AuthStore.replace_operator_state`, present-section replace, never 409) and `GET /projects/{project_id}/auth` (`read_auth` -> `read_project_auth`).
A seed whose credential username already belongs to another account is refused with the `duplicate_identity` envelope and HTTP 500 (D220-11): the repair is a role on the existing account, never a second account.

**Data-dependency placement surface** (eval):
The four NON-IDEMPOTENT direct-write endpoints the eval harness uses to place a target's pre-built artifacts, so the agent container finds them by MOUNT at startup: `POST /projects/{id}/data-dependencies/authn-skill` (the project `authn` bundle), `.../auth-overview` and `.../auth-credentials` (the AuthContext), and `.../l1` (the L1 surface).
Each is `multipart/form-data` with one required `file` part carrying the raw bytes (`authn-skill` takes a single `.tar.gz`/`.zip` bundle, unpacked server-side with traversal rejected; `fileName` is optional and never builds a path), and each call overwrites, creating the canonical file when absent.
The auth/skill contents land through `AuthStore.put_overview`/`put_credentials` and `SkillStore.replace_bundle` (validated before writing); the L1 content is the structured `operator_kb.md` persisted through the deterministic `analysis/scaffold.py` path (`l1_curate`), never the two-LLM bootstrap.
These endpoints SUPERSEDE the inline `TargetConfig.auth` mapping and the `PUT /auth` seed for eval placement (see `docs/design/eval-data-dependency-placement-decisions.md`); the `PUT`/`GET /auth` faces remain for the frontend.

**Run-request**:
An operator's request to recon a project - `POST /projects/{id}/recon`.
It is guarded before launch (the project must exist, any job subset must be valid, and a `target_domain` must be configured - a targetless run is refused so the pipeline never silently scans the example.com placeholder) and then scheduled non-blocking, returning a `run_id` immediately.
The Run *entity* itself (its phases, jobs, heartbeat, terminal status) is Recon vocabulary; project-management owns only the request for one and the polling of its status.

**Recon stop** (`POST /projects/{id}/recon/{run_id}/stop`):
The operator's request to cancel a running recon, recon ONLY - the analysis
consumer is never touched and still drains what was already pushed. The handler
is a thin adapter over `RuntimeManager.cancel_run`; the Run row's first-class
`stopped` terminal is written by Recon's pipeline cancellation path (#287),
never here. Project-management requests the stop; Recon owns the Run terminal.
The cancellation unit is the Run, never a single Job (Recon owns that ruling);
the in-flight pod/tool teardown is a separate concern (#76).
_Avoid_: writing the run status in the HTTP adapter (the terminal belongs to the
pipeline).

**App-state read surface**:
The instance-wide running-state read - `GET /app-state` (optional `?project_id` scope, `idle` reflects the scope).
Per project it reports the in-flight runs of every run class the store expresses (recon `running`, analysis `draining`, hunting `running` - each the only live state of its lifecycle) plus the top-level `idle`; read-only, no mutation surface, with the equivalent direct-postgres query documented on the route as the fallback.
The pre-existing unscoped `GET /runs?status=running` stays as the recon-only listing; the new surface consolidates all three classes rather than multiplying per-class endpoints.

**Module-lifecycle request** (#118/#121):
An operator's drive of the runtime plane over the wire - `POST /projects/{id}/modules/{module}/pause|resume|drain` (`module` in `recon|analysis|hunting`).
The verbs route to the module runtime's `RuntimeManager.pause/resume/drain` (the in-process lifecycle state machine), fail closed with 503 when no runtime is active, and 404 on an unknown module; pause of a stopped module and resume of a non-paused module are the runtime verb's own safe no-ops, and the response always reports the current state.
As of #211, `drain` returns the module's flush result - `{module, state, flush: {committed, archived, dropped, dropped_thread_ids, cause}}` - the machine-readable teardown-assert surface (the eval harness asserts `dropped == 0`): a dropped flush at a drain is never silent. Drain stays graceful-completion (a test-executor pod drains to a produced PodExport); the halt-everything semantics belong to the forced process teardown.
Since #328 (recon) and #332 (analysis, hunting) a **launch after a drain is not refused**: every launch entry predicate calls the runtime's idempotent admission precondition `RuntimeManager.ensure_running(module)` before scheduling, which revives a `stopped` module (the `stopped -> running` transition) and leaves a running or paused module untouched, so a drained module never fails a trial on an admission refusal while a deliberate pause is preserved. The three predicates are the recon launch (`_schedule_pipeline`), the analysis launch (`start_analysis`/`_start_analysis_sync`, which also repairs the analysis module for the combined recon launch), and the hunting launch (`schedule_hunting`). Only a drain (or the shutdown fan-out) reaches the terminal `stopped` state; `restart` is the manager-internal transition back (`stopped -> running`), with no HTTP route - `ensure_running` is the production revive path. The shutdown fan-out clears the worker loop, so a revive after it refuses loudly with `RuntimeLoopNotRunning` rather than reopening a torn-down runtime.

**Hunting-run launch surface** (#110, extended by wiring T5 #174):
The REST launch face over the hunting pipeline - `POST /projects/{id}/hunting` (whole-pipeline launch, 201; **409 Conflict while the project holds a live `running` hunting run** - the one-live-run-per-project guard read via `list_hunting_runs` before a new row opens, so the refusal never leaves an orphan; the `hunting_runs` row is the server-side at-most-once creation marker and any post-open refusal closes the row to `failed`), the singular component launches `POST /projects/{id}/hunting/hunt|pod|orchestrator` (202 - the hunter launch enqueues a produced ratified hunt config (its body is the identity triple + orientation prose only - `hunt_id`, file name, and semantic key are DERIVED from the identity, #298/#300, never caller fields), **as of the identity-based refactor 2026-08-25 the POD launch resumes ONE stored/paused pod session by posting its coroutine id - it NEVER fabricates a produced `specified` spec (the whole-pod-component path stays the whole-pipeline run); a FAIL-CLOSED resume with no stored/paused pod session is refused 404**, and the orchestrator launch schedules its pass - each routed through the launcher seams `enqueue_hunt_config` / `resume_pod_session` / `launch_orchestrator` and a singular launch never fabricates a chained-dependency error), and the per-session lifecycle verbs `POST /projects/{id}/hunting/{rid}/sessions/{session_id}/pause|resume|stop` (route ONE registered session to the shared runtime's per-session `hold_session`/`resume_session`/`cancel_run`, keyed by the ADR #169 Q13 session id; 404 unknown run / unknown-unregistered session, 503 no active runtime).
**As of #317** the surface also carries the per-agent-sub-module control: `POST /projects/{id}/hunting/{rid}/agent-submodules/{role}/start|stop` (idempotent; move ONE agent role of the run between `running` and `paused`; 404 unknown run / role), `GET .../agent-submodules` (the three roles with their states), and `GET .../threads` (every live thread of the run as `{thread_id, role, held}`, including the surfer and bootstrap under role `infra`), plus the single-thread `POST .../threads/{thread_id}/stop|resume` (routes to the per-session `hold_session`/`resume_session`; both 404 an unknown-unregistered thread - the resume path checks registration explicitly, since the runtime resume verb is otherwise a no-op - while a registered-but-not-held thread resumes `200`). See `docs/design/hunting-317-agent-submodule-adr.md`.
The handler exercises are thin adapters over the hunting launcher seams and the shared control plane - they never boot a real run on the request loop.

## The layering

- `api.py` - the thin HTTP adapter. Every handler delegates to `repository` and maps its domain errors onto status codes (`ProjectNotFound`/`RunNotFound` -> 404, `ValueError` -> 400). It owns the one bit of orchestration that is HTTP-adjacent: the `_launch_pipeline` fire-and-forget seam, plus the module-lifecycle handlers that route `pause`/`resume`/`drain` through the runtime manager.
- `repository.py` - the operator use-case layer (the application layer). Each project/settings/run operation is a plain function over the Postgres gateway that raises domain errors, never HTTP. A deep module over a thin gateway (CODING_STANDARD §0).
- `auth_context.py` - DELETED (#223 T4 #243, D223-4: the AuthContext value-object contract retired with the settings-blob footprint; settings PUTs persist verbatim and auth lives in the shared store).
