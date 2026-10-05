# ADR: a recon launch repairs a drained (`stopped`) recon module

## Status
Accepted (2026-10-05).

## Context
- Two round-3 eval trials failed at the recon phase: comfyui-1 `20261005T080051` (project `d3ac4eaf`) and jetlinks-1 `20261005T080209` (project `cc71f183`).
- The platform drained the recon module (`POST /projects/{id}/modules/recon/drain` -> `{"state":"stopped"}`) as a between-target teardown; the next trial's recon launch (`POST /projects/{id}/recon`) was refused `HTTP 503 ... module 'recon' is stopped; admission refused`.
- Root cause: `RuntimeManager.schedule` refuses admission unless the module is `running` (`app/runtime.py`), while `resume` only resumes from `paused` and is a no-op from `stopped`. The recon entry predicate (`_schedule_pipeline`) neither detected nor repaired a `stopped` module, so the launch 503'd.
- A drain is a graceful settle to the terminal `stopped` state, and a subsequent launch is the operator's intent to run recon. Refusing it on an admission check makes a routine teardown poison the next run.

## Decision
- Add `RuntimeManager.restart(module)` - the manager-internal `stopped -> running` transition: set the handle state to `running` and re-arm the module gate via `call_soon_threadsafe`. It has no HTTP route (no module-level sanction verb); the production revive is `ensure_running`.
- `restart` is a no-op on a `running` or `paused` module: only the terminal `stopped` state is revived, so a deliberate `pause` is preserved (`resume` remains the paused-only verb) and `schedule` keeps its refusal contract for a paused module (#118).
- Add `RuntimeManager.ensure_running(module)`, the silent idempotent admission precondition: it revives a `stopped` module and leaves a running, paused, or draining module untouched. The recon entry predicate (`_schedule_pipeline`, `project_management/api.py`) calls `ensure_running("recon")` before `schedule`, so the repair policy stays in the runtime and the HTTP adapter never re-encodes the admission rule by reading module state (fix-pass, code review).
- `resume` and `restart` share one private `_energize(name, *, revive_from)` (§8); `RuntimeLoopNotRunning` (a `RuntimeError`) names a revive attempted after the shutdown fan-out cleared the worker loop, replacing a bare `AttributeError` (fix-pass, code review).
- Scope is deliberately the recon entry predicate (the observed failure). The analysis (`start_analysis`) and hunting (`schedule_hunting`) entry points still refuse a drained module; the same repair there is a tracked follow-up of this class.

## Consequences
- A recon launch after a drain succeeds and revives the module; a trial no longer fails at the recon phase on an admission refusal.
- Restarting does not touch run rows, the flush result, or the registry beyond re-arming admission; the next drain re-settles and re-flushes normally.
- A revive after the shutdown fan-out refuses with `RuntimeLoopNotRunning`, never a half-revived module; the docstring and glossary no longer claim restart revives a shutdown module.
- Fix-pass (code review, low severity): the revive sits inside the launch's `except` guard, and `_admission_refused_503` maps `RuntimeLoopNotRunning` to 503, so a launch in the shutdown window (active runtime published, worker loop already cleared) returns 503 rather than 500. `restart` is described as manager-internal, not an operator verb; the dead module-level `restart(module)` wrapper is removed.
- The e2e FSM walk (`tests/e2e/test_module_runtime_plane_live.py`) now asserts the recon repair on launch and drains recon back to `stopped` to keep the walk's terminal invariant.
- Regression coverage: `tests/app/test_runtime_manager.py` (`restart` revive + no-op cases, `ensure_running`, and the after-shutdown guard) and `tests/app/test_module_lifecycle_api.py` (`POST /projects/{id}/recon` after a drain is 200, not 503).

## References
- #328 (this bug), #287 (a recon stop has no distinct `stopped` terminal), #118 (the admission-refusal contract), #121 (the module runtime manager), #332 (the sibling analysis/hunting repair, out of scope).
- `docs/design/module-runtime-architecture.md` section 5.11; `docs/design/module-runtime-assertions.md` C22; `src/polymerhus/app/runtime.py`; `src/polymerhus/project_management/api.py`.
