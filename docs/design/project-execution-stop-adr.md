# ADR: project execution stop

## Status

Accepted (2026-10-12).

## Context

A token-budget or deadline stop must end a trial's COMPUTE, not merely the trial process.
The v2 comfyui eval exposed the gap.
The trial enforced the budget on the project's cumulative capped-token spend, but stopped only the single run its poll had launched (`api.stop_run(project_id, run_kind, run_id)`).
The project ran recon, analysis, and hunting as INDEPENDENT runs.
`POST /recon` (combined) starts recon and analysis as two runs; the analysis run is correlated to the recon run but is its own lifecycle (`analysis_runs`, `analysis/lifecycle.py`).
The recon-start trial path launched recon with `with_analysis=True`, so the analysis ran without the trial ever holding its id.
When the budget fired during the hunting poll, the stop reached hunting only.
The analysis kept draining (~3 more hours in the observed run), and its drain then chained a fresh hunting run (`hunt_after_analysis`, default ON), which the trial never saw.
The project consumed 160,727,360 capped tokens against a 4,000,000 budget.

The module stop interface was NOT the gap.
`analysis` is a registered module (`_MODULES = ("recon", "analysis", "hunting")`), so `POST /projects/{id}/modules/{module}/{pause|resume|drain}` addresses it.
`POST /projects/{id}/analysis/{run_id}/stop` stops it gracefully, and `RuntimeManager.cancel_run("analysis", run_id)` hard-cancels it.
The gap is that no endpoint stops the WHOLE project execution, so the monitor had to address one run kind at a time.

## Decision

Add ONE project-scoped stop: `POST /projects/{project_id}/execution/stop`.

It stops EVERY live run of the project, all run kinds at once, and it is the ONE stop the token-budget and deadline monitors call.
The monitor no longer knows which run kinds are live, nor which analysis mode is armed (streamed or service-sourced); the project's execution is the unit it bounds, exactly as the project's cumulative token spend is.

The handler reads the live runs from the existing readers (`list_running_runs`, `list_running_analysis_runs`, `list_running_hunting_runs`) and stops each through the existing primitives.
The legs run in a fixed order: analysis first, then recon, then hunting.
Analysis is first because a DRAINED analysis chains a new hunting run, so stopping it before it can drain is what prevents a fresh hunt from spawning behind the stop.
The recon and hunting legs are hard cancels.
Each leg is best-effort and reported (`stopped` per kind, `errors`), so one already-terminal run never masks another, and the endpoint is idempotent (nothing live returns empty lists).

The trial monitor calls it through `eval/orchestrator/api.py::stop_project`.
`Trial._poll` and `Trial._poll_hunting` no longer carry a `(run_kind, run_id)`; the budget stop and the deadline stop both call `Trial._stop_project(project_id)`.

## Alternatives rejected

- **Model the analysis run in the trial chain and stop it individually.**
  Rejected: the analysis is launched by recon and/or by the app, and it can be streamed or batched, so a per-kind stop branches the monitor by run kind and by mode.
  The project-scoped stop needs no such branch.
- **Expose a module-level hard-stop verb (`POST /modules/{module}/stop`).**
  Rejected as the primary fix: it still makes the caller enumerate modules.
  The project-scoped endpoint is the operator-intent unit and covers every kind in one call.
- **Rely on the graceful per-run stops the existing routes issue.**
  Rejected as the stop the monitor uses: it stops one run, and it left the analysis (the actual spender) running.

## Consequences

- A budget or deadline stop ends the project's compute in one call; no run of the project keeps spending after the terminal.
- The pre-existing per-run stop routes stay for the operator and the surfer; they are not removed.
- The project-management surface gains one endpoint; its CONTEXT records the new term.

## Evidence

- Run tables for the observed run: recon complete 22:52:32; hunting `c1dd0163` stopped 23:38:32 (the trial's stop); analysis `d8be3a2e` drained 02:41:18; hunting `82782ad7` running from 02:41:18.
- The access log shows the single trial hunting launch and the single `.../hunting/c1dd0163/stop`; the second hunt was launched in-process by the analysis-drain chain.
- The usage ledger shows 160,727,360 capped tokens against a 4,000,000 budget.
