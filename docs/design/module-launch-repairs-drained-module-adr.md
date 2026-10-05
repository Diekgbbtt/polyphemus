# ADR: a launch repairs a drained (`stopped`) module (recon, analysis, hunting)

## Status
Accepted (2026-10-05). Generalises the recon-only ADR `recon-launch-after-drain-328-adr.md` (#328 develops the recon instance; this record states the reusable contract) and supersedes that record once the two land together on integration.

## Context
- A drain is a graceful settle: `RuntimeManager.drain(module)` finishes the in-flight unit, cancels the rest, flushes the module index, and marks the module `stopped`.
- `stopped` is terminal for `RuntimeManager.schedule`: the entry predicate refuses every new run with `ModuleAdmissionRefused` -> the launch adapter maps it to HTTP 503 `admission refused`.
- Round-3 eval trials drained a module as a between-target teardown and then failed the next trial's launch:
  - recon (`POST /projects/{id}/recon`) - comfyui-1 `20261005T080051`, jetlinks-1 `20261005T080209` (#328);
  - analysis (`POST /projects/{id}/analysis`, and the combined recon launch that calls `start_analysis` one step later) and hunting (`POST /projects/{id}/hunting`) - the same class (#332).
- Refusing a routine launch on an admission check makes a routine teardown poison the next run; a launch is the operator's intent to run the module.

## Decision
- The shared primitive is `RuntimeManager.ensure_running(module)`, the silent idempotent admission precondition: it revives a `stopped` module and leaves a running, paused, or draining module untouched (a deliberate pause is preserved, so the #118 refusal contract for a paused module stands).
- `RuntimeManager.restart(module)` is the manager-internal `stopped -> running` transition (no HTTP route exposes it; `ensure_running` is the production revive path); `resume` remains the paused-only verb. `resume` and `restart` share the private `_energize(name, *, revive_from)` transition; `RuntimeLoopNotRunning` names a revive attempted after the shutdown fan-out cleared the worker loop (a `RuntimeError`, replacing a bare `AttributeError`).
- Every module's launch entry predicate calls `ensure_running(module)` before scheduling, so the repair policy lives once in the runtime and no adapter re-encodes the admission rule by reading module state:
  - recon: `_schedule_pipeline` in `project_management/api.py`;
  - analysis: `_start_analysis_sync` in `analysis/lifecycle.py`, reached by `start_analysis`, which the combined recon launch calls via `run_pipeline`;
  - hunting: `schedule_hunting` in `attack/hunting/runtime.py`, which serves both the whole-pipeline launch and the singular orchestrator launch.
- Scope is the launch entry predicates only. A launch never revives a paused module and never revives one after process shutdown.

## Consequences
- A launch after a drain succeeds and revives the module for every one of recon, analysis, and hunting; a trial no longer fails on an admission refusal.
- The revive transition touches no run rows, no flush result, and no registry beyond re-arming admission; the next drain re-settles and re-flushes normally.
- A revive after the shutdown fan-out refuses with `RuntimeLoopNotRunning`, never a half-revived module.
- Fix-pass (code review): each launch's revive sits INSIDE its guard, and `_admission_refused_503` maps `RuntimeLoopNotRunning` to a clean 503, so a launch in the shutdown window (active runtime published, worker loop already cleared) returns 503 rather than 500 for every one of recon, analysis, and hunting. `restart` is described as manager-internal, not an operator verb, and the dead module-level `restart(module)` wrapper is removed.
- Regression coverage: `tests/app/test_runtime_manager.py` (`restart` revive + no-op cases, `ensure_running` on running / paused / draining / stopped, the after-shutdown guard, and `start_analysis` on the worker loop repairing a drained analysis module - the exact seam the combined recon launch calls from `run_pipeline`, exercised directly rather than through the full pipeline); `tests/app/test_module_lifecycle_api.py` (`POST /projects/{id}/recon` and `POST /projects/{id}/analysis` after a drain are 200, not 503, and a launch during the shutdown window is 503, not 500); `tests/project_management/test_hunting_api.py` (`POST /projects/{id}/hunting` after a drain is 201, not 503).
- `tests/e2e/test_module_runtime_plane_live.py` asserts the repair on launch for all three modules and drains each back to `stopped` to keep the walk's terminal invariant.

## References
- #328 (the recon instance), #332 (the analysis/hunting generalisation), #118 (the admission-refusal contract), #121 (the module runtime manager), #287 (a recon stop has no distinct `stopped` terminal).
- `docs/design/module-runtime-architecture.md` section 5.11; `docs/design/module-runtime-assertions.md` C22; `docs/design/http-api-catalogue.md`; `src/polymerhus/app/runtime.py`, `src/polymerhus/project_management/api.py`, `src/polymerhus/analysis/lifecycle.py`, `src/polymerhus/attack/hunting/runtime.py`.
