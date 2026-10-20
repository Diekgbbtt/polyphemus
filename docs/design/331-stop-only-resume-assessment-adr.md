# ADR: the resume decision is derivable from the stamped provider cause (#331, stop-only)

*Status: RATIFIED pending verifier review (2026-10-09).
Match check: `docs/design/eval-provider-resilience.md` Part 2 is the umbrella design; `docs/design/hunting-329-provider-failure-classification-adr.md` scopes the typed classifier; `docs/design/hunting-331-provider-resume-adr.md` scopes the landed cause-recording slice; `docs/design/open-operator-decisions.md` D-3 records the operator ruling.
This record scopes the STOP-ONLY slice of #331: the app-layer stop/flush handoff, and the proof that a resume decision is derivable from the stamped attributes alone.
The resume IMPLEMENTATION is explicitly deferred to a future ticket - see "Deferred scope" below.*

## Context

The first #331 slice recorded an `interrupted` run's cause in `hunting_runs.stats` and surfaced it to the eval.
It did not stop the run's sessions: a provider-caused abort stamped `interrupted` while the run-scoped surfer session stayed live, so the terminal could race a still-working dispatcher (the #331 verifier finding).

The operator ruled (#331 comments, D-3) that the RESUME is gated on a background eval health-checker that does not exist yet, and that the stop path itself is sound.
This ticket therefore implements the stop path and DEFERS the resume.

## Decision

### 1. One app-layer stop/flush/stamp handler

`attack/hunting/runtime.py::stop_hunting_for_provider_failure` is the ONE handler a provider failure reaches.
It performs, in order:

1. **STOP** - cancel every live component session of the run through the shared runtime's per-session `cancel_run` primitive (reached via the control plane's `cancel_session`).
   Per agent type (ADR Q13 session id): the orchestrator pass, every hunter, and every pod are running LLM agents and are hard-cancelled; the surfer mover has no LLM but would keep dispatching hunters and pods, so it is cancelled with them.
   `hold_session` is the runtime's PAUSE verb and is deliberately NOT used by stop-only, because the run is terminalized rather than paused in process; the resume ticket reintroduces the hold for the types it keeps.
2. **DRAIN** - wait until no component session of the run remains live before the terminal lands, so the `interrupted` stamp never races a live session.
3. **FLUSH** - archive the run's committed threads through the shared run-scoped chokepoint `flush_run_scoped("hunting", run_id)`, so the pre-failure checkpoint is durable for the (future) resume.
4. **STAMP** - persist the resumable terminal `interrupted`, never `failed`, with the accurate cause.

The handler is fail-open: cancel, drain, reap, flush, and stamp are each guarded, so a provider failure always lands a terminal and never raises through the control plane.

### 2. The stamped terminal carries the accurate cause

`runtime._provider_interrupt_stats` authors the run row's `stats`:

```
{"interrupted": true,
 "interrupt_reason": "provider unavailable (status=429, quota_exhausted=true, retry_after_s=45)",
 "provider_status": 429,
 "quota_exhausted": true,
 "retry_after_s": 45.0}
```

`ProviderUnavailableError.interrupt_reason()` renders the one-liner once, at the classifier.
The structured fields - `quota_exhausted`, `provider_status`, `retry_after_s` - are the machine-readable surface the resume decision reads.
The eval trial records the cause on the hunting phase (`_phase_hunting` -> `_hunting_failure`), so the trial record is never `failure=None` for an interrupted hunt.

### 3. The resume decision, from the stamped attributes alone

The decision table reads ONLY the run row's `stats` (the stamped attributes), never a free-form error message:

| `quota_exhausted` | meaning | decision |
|---|---|---|
| `false` | a transient throttle (a per-minute 429, a 5xx, or a timeout) | RESUMABLE: resume after `retry_after_s` seconds, or after a default backoff when `retry_after_s` is null |
| `true` | a period quota or credit exhaustion (`Go usage limit exceeded`) | TERMINAL: do not resume; the provider will not serve until the period resets |
| missing or unknown (no `stats`, or a non-provider reason such as the process-restart reconcile) | the class is not established | DO-NOT-RESUME (fail-closed) |

### 4. Why the decision is reliable and repeatable

- **Durable**: `stats` is a JSONB column on the `hunting_runs` row, written in the same terminal transition as the status; it survives the process that observed the failure.
- **Addressable**: the trial record's hunting phase carries the run id (`PhaseRecord.run_id`), so the eval re-reads `GET /projects/{id}/hunting/{run_id}` and gets the identical `stats` on every later process.
- **Structured, not prose**: the decision keys on `quota_exhausted` (a boolean) and `retry_after_s` (a number), so it does not depend on parsing `interrupt_reason`.
  The free-form `CREDIT_MARKERS` text scan in the surfer is a fallback for older records, not the authority.
- **Total**: the table covers every value the discriminator can take (`true`, `false`, missing/unknown), so no input is undecided; the unknown case fails closed.
- **Repeatable**: the same `stats` yields the same decision in any process, because the fields are stamped once and never recomputed.

### 5. The eval monitor defers, never escalates

`eval/orchestrator/monitor.py::decide` treats an `interrupted` terminal as DEFERRED: the surfer loop owns recovery, and no assessment or diagnosis subagent is dispatched.
It never escalates an interrupted trial, and the cause stays on the trial record.
This is pinned by `tests/eval/test_orchestrator_monitor.py::test_interrupted_execution_is_deferred_never_escalated` and `tests/eval/test_orchestrator_cli_monitor.py::test_monitor_defers_an_interrupted_execution`.

## Deferred scope (explicitly out of this ticket)

The resume IMPLEMENTATION is deferred to a future ticket. It is underspecified on three points, so implementing it now would yield a low-quality change:

1. **No bounded resume-window policy.** The decision table says "resume after `retry_after_s`", but nothing bounds how long to wait when the hint is absent, how many resumes are attempted, or how to back off across repeated throttles.
2. **No idempotency contract.** Resume must not double-dispatch a hunter or a pod. The at-least-once produced/consumed markers guard the mover, but the resume entry has no ratified contract for re-scheduling the flushed sessions without a second dispatch.
3. **No health signal.** The trigger is unresolved: the operator ruling (D-3) makes auto-resume gated on a background eval health-checker loop that does not yet exist. An operator verb is the floor, but the operator chose auto-resume.

Until those are ruled, the eval does not resume. It only DEFERS the interrupted run and records the reason.

Not implemented here, and not required for the derivability proof: consuming `quota_exhausted` inside the surfer's credit classifier, and re-reading the run row in the surfer. The data is available; the policy is the deferred ticket's.

## Consequences

### The good

- A provider failure stops the run cleanly: the terminal lands only after every component session has settled, so no live surfer can keep dispatching under an `interrupted` stamp.
- The affected threads are flushed before the terminal, so the pre-failure state is durable for a resume.
- The cause is durable and structured, so the resume decision is derivable and repeatable from the stamped attributes alone.
- No domain fabrication, no new terminal value, no change to the six-value vocabulary.
- The eval monitor defers the interrupted run and never escalates it.

### The cost

- The stop leg adds a drain wait (bounded, fail-open) to the provider-failure path.
- `hold_session` is unused on this path; a future resume ticket reintroduces it for the types it keeps.

## Amendment (#398 T11, 2026-10-20)

The operator verb - the ratified floor - has LANDED.
The auto-resume health checker remains a FOLLOW-UP.

### The operator verb

`POST /projects/{project_id}/hunting/{hunting_run_id}/resume` applies the decision table in section 3 through the ONE pure function `attack/hunting/resume.py::resume_decision`.
The function reads only the run row's status, `stats` and `finished_at`; `now` is injected, so the same row yields the same decision in every process.
Every row is decided, and every non-resumable row is a 409:

| run row | decision |
|---|---|
| `stopped` | resumable immediately |
| `interrupted`, `stats.quota_exhausted == false` | resumable after `retry_after_s`, or the default backoff when the hint is null |
| `interrupted`, `stats.quota_exhausted == true` | terminal (409) |
| `interrupted`, missing/unknown stats | do-not-resume (409, fail-closed) |
| `interrupted`, missing/unusable `finished_at` (`timing_unknown`) | do-not-resume (409, fail-closed) |
| `running` | 409 (already live) |
| `complete` / `failed` | 409 (terminal) |
| any other status | 409 (fail-closed) |

The null-hint default backoff is 60 seconds (`DEFAULT_RESUME_BACKOFF_S`): one per-minute provider window, the shortest window the table names for a transient 429.
A malformed hint (negative, non-finite, non-numeric) also takes the default, never zero.
The operator verb ENFORCES the wait window from `finished_at + retry_after_s` (or the default) and returns a 409 with a `Retry-After` header and a human-readable wait.
It has no `force` flag: a force would be an unratified interface.

The admission is one atomic conditional update (`pg.claim_hunting_run_for_resume`): only the exact row the decision read - same project, same status - transitions back to `running`.
Two concurrent resumes therefore yield one 202 and one 409 (lost claim).
The SAME update CLEARS the provider-pause keys from `stats` (`interrupted`, `interrupt_reason`, `provider_status`, `quota_exhausted`, `retry_after_s`) and keeps the run record: after a resume the row advertises no pause, so a later crash + reconcile cannot inherit the pre-resume `quota_exhausted=false` and look resumable.
A post-claim conflict (another live run in the project) or admission refusal RESTORES the prior status AND re-stamps those pause keys, so the operator can retry.
The restore stamps a new `finished_at`, which restarts the wait window for a throttle: a conservative extension, never an early resume.

The INTAKE FREEZE consumes the same decision (S2 9.3): an `interrupted` producer whose decision is terminal or do-not-resume has its produced model archived to `abandoned/` and its unit retried; a resumable throttle - including one still inside its backoff window - keeps its model `in-flight`.
An `interrupted` producer with no classification available (a degraded run read) stays `in-flight` (fail-open).

The resumed run re-enters `start_hunting` with the EXISTING run id.
It re-enters at the recorded `intake_position`, adopts the committed models, recomputes `risk_total`, and never re-freezes or re-sorts the intake; a halted run resumes dispatch only.
The dispatch stays run-scoped: the run's own produced loops dispatch, a foreign run's stay produced, and a produced item whose hunter or pod session is already live is adopted (moved produced->consumed), never dispatched twice.

### The orphaned-run disposition

`reconcile_orphaned_hunting_runs` stamps a process-restart `interrupted` row with a restart reason and NO provider class (`quota_exhausted` absent).
Under the table that row is do-not-resume (fail-closed): the operator verb does not guess a cause for a crash-orphaned run, and the reconcile never reschedules one.
A provider-caused `interrupted` row carries the stamped class and is the only `interrupted` row the verb can resume.
A RESUMED-then-crashed row is the same case as a cold-start orphan: the claim cleared the pre-resume class, so the reconcile's restart stamp carries none and the table answers do-not-resume.

### The auto-resume follow-up (not built)

The operator's chosen direction (D-3) is a background health checker that auto-resumes a resumable `interrupted` run with backoff.
It is NOT built here.
The follow-up consumes `resume_decision` and `DEFAULT_RESUME_BACKOFF_S`; the operator verb is its floor, not a replacement.

## Impact map (as built)

- `src/polymerhus/attack/hunting/runtime.py` - `stop_hunting_for_provider_failure` (the stop/drain/flush/stamp handler); both provider-failure branches of `start_hunting` call it and leave `status=None` so the `finally` does not re-stamp.
- `src/polymerhus/attack/hunting/resume.py` - the pure resume decision table (`resume_decision`), the 60s default backoff, the operator-verb wait-window policy, and the pause-key/terminal-code constants the claim and the intake freeze consume.
- `src/polymerhus/attack/hunting/unit_intake.py` - the freeze's `interrupted` resumability branch: a terminal/do-not-resume producer's model is stale; a resumable one stays in flight.
- `src/polymerhus/project_management/api.py` - `POST .../hunting/{hunting_run_id}/resume`; the atomic claim and its 202/409 mapping; the live-run conflict and admission-refusal restore (status + pause keys).
- `src/polymerhus/app/clients/pg.py` - `claim_hunting_run_for_resume` (the conditional status transition; it clears the provider-pause keys in the same UPDATE).
- `eval/orchestrator/monitor.py` - `INTERRUPTED_TERMINAL`; `decide` defers an interrupted execution explicitly.
- Tests - `tests/attack/test_hunting_runtime.py::test_provider_abort_stops_the_runs_sessions_before_the_terminal`; `tests/attack/test_hunting_resume.py` (the decision table and the runtime resume path); `tests/project_management/test_hunting_api.py` (the resume endpoint); `tests/app/test_hunting_runs.py` (the claim, live PG); `tests/eval/test_orchestrator_monitor.py::test_interrupted_execution_is_deferred_never_escalated`.
- Docs - this record; the stop-only re-scope noted in `docs/design/hunting-331-provider-resume-adr.md` and `docs/design/eval-provider-resilience.md`.
