# ADR: an interrupted run records its cause; the eval reads it (#331)

*Status: PARTIALLY RATIFIED pending verifier review (2026-10-06). Match check: `docs/design/eval-provider-resilience.md` Part 2 is the umbrella design; `docs/design/hunting-329-provider-failure-classification-adr.md` scopes the landed #329 slice (the typed `ProviderUnavailableError` classifier, the abolition of the pod's fabricated `technical-infeasibility`, and mapping a provider-caused hunt abort to `interrupted`). This record scopes the #331 slice that LANDED, and names the two #331 edges that are operator-gated and therefore ESCALATED, not guessed.*

## Context

#329 landed the classification and the `interrupted` terminal, but an `interrupted` hunting run carried no WHY: the `hunting_runs` row held only a status, and the eval trial (`eval/orchestrator/trial.py::_phase_hunting`) built a `PhaseRecord` with `failure=None` even though `interrupted` is a trial-stopping terminal. So the trial record said the run failed, but hid the provider class - the transient-throttle vs consumed-credits distinction the eval resume policy needs was unrecoverable after the process that saw the failure was gone.

The eval monitor (`eval/orchestrator/monitor.py::decide`) already defers any non-success terminal without escalating, so an `interrupted` execution is never assessed and no subagent is dispatched; that guarantee needed locking, not changing.

## Decision

### 1. The typed error rides the abort, not just a boolean

`DegradedTurnBreaker.record_outcome` now wraps the degrading cause with `as_provider_error` and stores the typed `ProviderUnavailableError` on `HuntOrchestrationDegradedError.provider_error` (alongside the existing `provider_cause` boolean). The boolean cannot carry the status or the quota class; the typed error can.

### 2. An `interrupted` run records its cause in `hunting_runs.stats`

`hunting_runs` gains an additive `stats JSONB` column (the same discipline as `analysis_runs`). On a provider-caused abort `runtime.start_hunting` stamps:

```
{"interrupted": true,
 "interrupt_reason": "provider unavailable (status=429, quota_exhausted=true)",
 "provider_status": 429,
 "quota_exhausted": true,
 "retry_after_s": 45.0}
```

`ProviderUnavailableError.interrupt_reason()` authors the one-liner (status, quota flag, retry hint) once, at the classifier. `reconcile_orphaned_hunting_runs` stamps a distinct process-restart reason, so a crash-orphaned `interrupted` is never causeless and is never mistaken for a provider pause.

### 3. The eval trial reads the cause into the phase failure

`PollResult` carries the terminal run row; `_phase_hunting` records `_hunting_failure(result)` - the row's `stats.interrupt_reason` when present, else `"hunting run interrupted (resumable)"`. The trial still stops at `interrupted` (it never chains), but the record now names WHY, and the surfer's evidence reader (`trial_evidence`) sees it.

### 4. The monitor defers `interrupted`, never escalates

`SUCCESS_TERMINALS` is unchanged; `interrupted` is not a success, so the monitor defers it to the surfer. A regression test pins that the monitor neither assesses nor escalates an `interrupted` trial.

## Consequences

### The good

- An `interrupted` run is never causeless: the durable cause (including the machine-readable `quota_exhausted` flag) survives the process, so the eval resume policy CAN distinguish a transient 429 from consumed credits once it consumes the field. The classification wiring itself (which code resumes, how long to wait, whether to synthesise a consumed-credits code) is deferred to the operator ruling below, so the eval does not yet make the distinction.
- The abort carries the typed error, so any future consumer (backoff, resume, policy) reads the classifier's own fields instead of re-deriving the class from a boolean.
- No domain fabrication, no new terminal value, no change to the six-value vocabulary.

### ESCALATED - not decided here

The ticket is design-gated and two #331 edges need an operator decision; they are NOT guessed:

1. **The 429-vs-403 resume policy.** The design (`eval-provider-resilience.md` 2.2 / Part 1) says: resume after the rate-limit window on a transient 429, never resume when credits are fully consumed, and the two must be distinguishable - a rate-limit (429, resumable) vs a fully-consumed-credits code (a distinct code such as 403, terminal). Open question for the operator: does the provider/LiteLLM actually emit a distinct code for consumed credits, or must we synthesise one at the gateway/classifier? The `ProviderUnavailableError` already carries `status_code` and `quota_exhausted`, and the run now records both, so either answer is implementable - but the policy (which code resumes, how long to wait, whether to synthesise) is the operator's.

2. **The app-layer stop/flush/resume re-scheduling.** The flush already lands (`flush_run_scoped` in `start_hunting`'s `finally`, before the `interrupted` stamp). The missing piece is the resume entry that re-schedules the affected session types (orchestrator / hunter / pod) from their flushed pre-failure checkpoints, and its trigger (operator call, eval surfer, or a health probe). The design names the granularity (ADR Q13 session ids) but not the trigger or the idempotency contract; guessing it would invent an interface the operator has not ratified.

The `#329` slice's `retry_after_s`-driven backoff and the eval monitor's execution-state introspection script remain #331/#330 and are not part of this change.

## Amendment (#312, 2026-10-08)

Decision 2 (an `interrupted` run records its cause in `hunting_runs.stats`) was scoped to a provider-caused ORCHESTRATOR pass abort.
A re-verification of the `trial-2` zero-spec outcome (ticket #312) found a provider failure in a dispatched HUNTER or POD session was still silently swallowed, so the run quiesced `complete` with zero specs and no cause.
The child-session failure now records on the run-local `RunDispatchState`, the surfer surfaces it, and `start_hunting` maps it to the same `interrupted` + `stats` terminal.
This is the terminal-marking half only; the resume re-scheduling named in ESCALATED item 2 remains the operator's. See `hunting-312-hunter-provider-failure-adr.md`.

## Impact map (as built)

- `src/polymerhus/app/llm/provider_failure.py` - `ProviderUnavailableError.interrupt_reason()`.
- `src/polymerhus/attack/hunting/hunt_orchestrator.py` - `HuntOrchestrationDegradedError.provider_error`; `record_outcome` wraps the typed error.
- `src/polymerhus/attack/hunting/runtime.py` - `_provider_interrupt_stats`; `start_hunting` stamps `stats` on the `interrupted` terminal.
- `src/polymerhus/app/clients/pg.py` + `db/postgres/init.sql` - `hunting_runs.stats` (additive migration); `set_hunting_run_status(..., stats=)`; `get_hunting_run`/`list_hunting_runs` expose it; `reconcile_orphaned_hunting_runs` stamps a reason.
- `eval/orchestrator/trial.py` - `PollResult.response`; `_hunting_failure` records the cause on the hunting phase.
- Tests: `tests/app/test_llm_provider_failure.py`, `tests/attack/test_hunt_degraded_breaker.py`, `tests/attack/test_hunting_runtime.py`, `tests/app/test_hunting_runs.py`, `tests/eval/test_orchestrator_trial.py`, `tests/eval/test_orchestrator_cli_monitor.py`.
