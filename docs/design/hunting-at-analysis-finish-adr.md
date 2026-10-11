# ADR: hunting launches at analysis finish, not at recon finish

Status: accepted (2026-10-11).

## Context

A trial runs `recon` then `hunting`, with the analysis consumer running
independently in the background (recon starts it and never waits, #75).
The trial's phase chain chained `recon` straight into `hunting`, so hunting
launched the moment recon reached its terminal.
Observed on a live `service_sourced` trial: hunting ran 16:08:15 -> 16:43:05
while the analysis had minted 0 analyser `L1System`s at hunt start (3 by 16:35).
The hunter therefore reasoned over the bootstrapped L1 only - the scaffolded
`L1Service`/`L1System` from `data-dependency-scaffold` - never over the analysis
findings.

Hunting reasons over the ANALYSIS surface. Launching it at recon finish hands it
an empty, bootstrapped surface, which is a wasted run and a false negative signal.

## Decision

Hunting launches at analysis finish, in two places:

1. **Eval trial phase chain** (`eval/orchestrator/trial.py`). After a successful
   recon the trial now enters the analysis phase and drains the analysis run to
   its terminal BEFORE it launches hunting, so the chain is
   `recon -> analysis -> hunting`. The combined recon dispatch already started the
   consumer, so the trial drains it and does not relaunch it (a second
   `POST /analysis` double-runs/409s); a recon-only dispatch starts one. The
   analysis terminal is recorded as its own phase, and the existing failure
   semantics are preserved (a block, timeout, token-budget stop, or failure stops
   the trial and never chains into hunting; a natural analysis `stopped` still
   chains).

2. **Polymerhus app pipeline** (`src/polymerhus/analysis/lifecycle.py`). The
   analysis supervisor chains ONE hunting run when the analysis genuinely
   `drained`, gated by the opt-in policy `settings.recon.hunt_after_analysis`
   (default OFF, read through `analysis.feed.resolve_hunt_after_analysis`). It
   reuses the SAME operator-intent launch seam as `POST /projects/{id}/hunting`
   (`project_management.api.launch_hunting`), so the one-live-run-per-project
   guard refuses a second live run (409, the idempotent no-op). Only `drained`
   chains; `withheld` (vacuous) and `stopped` (deliberate, resumable) do not.

## Rationale

- The trial owns the explicit `recon -> analysis -> hunting` sequence; the
  app-side auto-chain is opt-in because an unconditional app-side launch would
  collide with the trial's own hunting launch (the one-live-run 409).
- The app-side trigger lives at the analysis terminal (`_supervise`), the one
  place the analysis run's status is written. `analysis` must not import
  `attack.hunting` or `project_management` at import time (`CONTEXT-MAP.md`), so
  the launch resolves lazily and degrades loudly (fail-open): a missing control
  plane or a refused launch is logged, never raised into the supervisor.

## Consequences

- A hunting run always reasons over the analysis surface, not the bootstrap.
- The app-side chain is dormant by default; only a project that opts in gets it.
- A dedicated phase record for the analysis terminal exists on every
  `start_phase: recon` trial.

## Supersedes

The implicit `recon -> hunting` chain (the trial's earlier recon-path behaviour).
