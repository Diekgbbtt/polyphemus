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
The operator's configuration of a project's recon: `target_domain`, scope, the [AuthContext](#authcontext), and feature toggles.
Persisted as a JSON document and updated by PARTIAL PUT - a settings update deep-merges into the stored document (recursive jsonb merge in the gateway), so setting one field never wipes its siblings.
Concrete settings for the live e2e targets are held in the eval dataset `tests/e2e/fixtures/eval-targets.yaml`.

**AuthContext**:
The operator's declaration of how authenticated recon should authenticate: an optional `cookies` list, an optional autonomous-login `credentials` set, optional role/realm-tagged credential sets (FR-AUTH), and otherwise arbitrary HTTP headers emitted verbatim by the request-based tools.
It is a **value object** - defined wholly by its attributes, replaced rather than mutated - so its contract and validation invariant live in one place (`auth_context.py`), independent of both the HTTP surface that receives it and the settings use-case that persists it.
`cookies` (request-based crawling) and `credentials` (agentic login) are INDEPENDENT items; a partial PUT may set either without the other.

**Run-request**:
An operator's request to recon a project - `POST /projects/{id}/recon`.
It is guarded before launch (the project must exist, any job subset must be valid, and a `target_domain` must be configured - a targetless run is refused so the pipeline never silently scans the example.com placeholder) and then scheduled non-blocking, returning a `run_id` immediately.
The Run *entity* itself (its phases, jobs, heartbeat, terminal status) is Recon vocabulary; project-management owns only the request for one and the polling of its status.

**Module-lifecycle request** (#118/#121):
An operator's drive of the runtime plane over the wire - `POST /projects/{id}/modules/{module}/pause|resume|drain` (`module` in `recon|analysis|hunting`).
The verbs route to the module runtime's `RuntimeManager.pause/resume/drain` (the in-process lifecycle state machine), fail closed with 503 when no runtime is active, and 404 on an unknown module; pause of a stopped module and resume of a non-paused module are the runtime verb's own safe no-ops, and the response always reports the current state.

**Hunting-run launch surface** (#110, extended by wiring T5 #174):
The REST launch face over the hunting pipeline - `POST /projects/{id}/hunting` (whole-pipeline launch, 201; **409 Conflict while the project holds a live `running` hunting run** - the one-live-run-per-project guard read via `list_hunting_runs` before a new row opens, so the refusal never leaves an orphan; the `hunting_runs` row is the server-side at-most-once creation marker and any post-open refusal closes the row to `failed`), the singular component launches `POST /projects/{id}/hunting/hunt|pod|orchestrator` (202, enqueue into the component's handoff family for the project - a produced ratified hunt config, a produced specified test spec, or the orchestrator pass - so the run's inbox surfer dispatches one component on the next tick; a singular launch never fabricates a chained-dependency error and a replayed enqueue is refused 409 by the storage novelty gate), and the per-session lifecycle verbs `POST /projects/{id}/hunting/{rid}/sessions/{session_id}/pause|resume|stop` (route ONE registered session to the shared runtime's per-session `hold_session`/`resume_session`/`cancel_run`, keyed by the ADR #169 Q13 session id; 404 unknown run / unknown-unregistered session, 503 no active runtime).
The handler exercises are thin adapters over the hunting launcher seams and the shared control plane - they never boot a real run on the request loop.

## The layering

- `api.py` - the thin HTTP adapter. Every handler delegates to `repository` and maps its domain errors onto status codes (`ProjectNotFound`/`RunNotFound` -> 404, `ValueError` -> 400). It owns the one bit of orchestration that is HTTP-adjacent: the `_launch_pipeline` fire-and-forget seam, plus the module-lifecycle handlers that route `pause`/`resume`/`drain` through the runtime manager.
- `repository.py` - the operator use-case layer (the application layer). Each project/settings/run operation is a plain function over the Postgres gateway that raises domain errors, never HTTP. A deep module over a thin gateway (CODING_STANDARD §0).
- `auth_context.py` - the AuthContext value-object contract and its validation invariant.
