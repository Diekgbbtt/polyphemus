# ADR: provider failures are a distinct, typed infrastructure class (#329)

*Status: RATIFIED pending verifier review (2026-10-06). Match check: no existing ADR covers the provider-failure classification; `docs/design/eval-provider-resilience.md` Part 2 is the umbrella design (#331), and this record scopes the #329 slice of it. Supersedes nothing; complements `hunting-module-runtime-seam.md` and the #186 actor degrade hook.*

## Context

A persistent provider `429` (`GoUsageLimitError: Go usage limit exceeded`, `limitName: 5 hour`) with no fallback model group cascaded through round-3 of the eval (`docs/design/eval-bugs-map.md` section 0, EV-21):

- the `comfyui-1` hunting run `c4ed6cea` persisted `failed` because the hunt pass's `DegradedTurnBreaker` (#280 Part 2) aborted on sustained degradation and the runtime caught the abort as a generic failure;
- **23 of 27** pod exports carried `terminal_reason: technical-infeasibility` with `error="Error code: 429 ..."` - the pod's catch-all (`pod/pod.py:114-118`) fabricated a DOMAIN verdict on an INFRASTRUCTURE raise;
- the pod triager laundered a provider failure into a benign `no-symptom-evidence` domain decision.

The root cause: a provider failure was not classified as its own kind. It was silently folded into a domain verdict or a run failure. This mis-states infrastructure conditions as target/domain outcomes, poisoning the assessment and failing runs that should pause.

The umbrella (`#331`) designs the full app-layer stop/flush/resume pattern. This record scopes ONLY the confirmed #329 code gap: classify a provider failure distinctly, back off, never fail a run outright, and never record it as `technical-infeasibility`. The stop/flush/resume re-scheduling and the eval-monitor `interrupted` handling remain #331.

## Decision

### 1. One shared typed classifier

`app/llm/provider_failure.py` is the ONE classifier:

- `ProviderUnavailableError` - a typed, `retryable` infrastructure error carrying `status_code`, `retry_after_s`, `provider`, `model`, and `quota_exhausted`.
- `is_provider_unavailable(exc)` - the classification: timeout, transport error, 429, 5xx, or a duck-typed status / last-resort throttle message. A raise matching none of these is NON-provider (a domain or application error).
- `as_provider_error(exc, ...)` - wraps a provider failure as the typed error, else None.

`app/llm/actor.py::_is_retryable` delegates here, so the actor retry budget and the classification cannot drift. The classifier is stdlib-only at import; the provider SDKs are lazy-imported.

### 2. A provider failure never becomes a domain verdict

- The test-executor pod (`pod/pod.py`) keeps its IA-4 fail-open degrade for genuine INTERNAL errors, but a provider failure propagates as `ProviderUnavailableError` - no `PodExport`, no fabricated `technical-infeasibility`.
- The production pod triager (`pod/agents.py::default_triager_fn`) re-raises a provider failure instead of returning a `no-symptom-evidence` decision.
- The surfer's pod session (`surfer.py::run_pod_session`) re-raises instead of fabricating a `surfer-dispatch-degraded` export.

`technical-infeasibility` remains ONLY for a genuine runner-asserted or internal infeasibility. `PodExport` carries no infrastructure state.

### 3. A provider-caused pass abort pauses the run

The `DegradedTurnBreaker` now takes the degrading turn's cause. The orchestrator actor records its last degraded-turn exception (`_TurnActor.last_degrade_cause`, cleared per request); the pass reads it, and a phase seam that itself raises a provider error supplies it directly. At the abort threshold the typed `HuntOrchestrationDegradedError` carries `provider_cause`. `runtime.start_hunting` persists the resumable terminal **`interrupted`** for a provider-caused abort, and **`failed`** (unchanged) for a non-provider degradation or any other exception.

The breaker's bounded backoff is unchanged - a provider throttle is still backed off between turns before the pass pauses.

## Consequences

### The good

- A provider throttle is named once, at one seam, and never fabricated into domain data.
- The run pauses (`interrupted`, resumable) instead of failing, so the checkpointer trail survives for #331's resume.
- The classification is shared, so the actor retry layer, the pod, and the runtime agree by construction.

### Still open (deferred to #331)

1. **Resume.** #329 lands `interrupted` but does not re-schedule the affected sessions; #331 adds the app-layer stop/flush/resume that restarts each agent type from its pre-failure checkpoint.
2. **Quota vs transient policy.** `ProviderUnavailableError.quota_exhausted` distinguishes a period-quota exhaustion from a per-minute throttle but no terminal-vs-resumable policy consumes it yet (#331's 429-vs-403 semantics).
3. **Eval monitor.** The eval monitor must not escalate `interrupted`; that handling stays #331.
4. **Retry-After-driven backoff.** The typed error carries `retry_after_s`; the breaker's backoff does not yet honour it.

## Impact map (as built)

- `src/polymerhus/app/llm/provider_failure.py` (new) - the classifier and typed error.
- `src/polymerhus/app/llm/actor.py` - `_is_retryable` delegates to the shared classifier.
- `src/polymerhus/attack/hunting/pod/pod.py` - provider failures propagate; the domain fabricate stays only for non-provider errors.
- `src/polymerhus/attack/hunting/pod/agents.py` - the triager re-raises provider failures.
- `src/polymerhus/attack/hunting/surfer.py` - the pod session re-raises provider failures.
- `src/polymerhus/attack/hunting/actors.py` - the actor records its last degrade cause.
- `src/polymerhus/attack/hunting/hunt_orchestrator.py` - the breaker threads the cause into `HuntOrchestrationDegradedError(provider_cause=...)`.
- `src/polymerhus/attack/hunting/runtime.py` - a provider-caused abort persists `interrupted`.
