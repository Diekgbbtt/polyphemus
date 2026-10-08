# ADR: transient upstream faults - classify the bare-400, ride out the window, rotate the session (#299)

*Status: RATIFIED pending verifier review (2026-10-07); AMENDED by the operator D-1 ruling (2026-10-08) to narrow the transient-400 matcher to the exact opencode-go deepseek lane signature.*
*Match check: no existing ADR owns the transient-upstream policy.*
*It complements the #329 provider-failure classification (`hunting-329-provider-failure-classification-adr.md`), the #186 actor degrade hook, and the D12 provider request primitive (`llm-gateway-100-decisions.md`).*
*It supersedes nothing.*
*It records the operator caveat that this defect is NOT deterministically reproducible, so the change is unit-tested at the classification and retry-loop seams and the live property stays unverified.*

## Context

The OpenCode Go lane for `opencode-go/deepseek-v4.1-flash` intermittently enters a short degraded window.
During the window it returns a bare HTTP 400 for EVERY request, independent of the client's request well-formedness (#299, ticket; `diag/opencode-go-400` `DEBUG.md`).

The observed bodies are the same class of fault:

- empty (`Error code: 400`), seen in the live trial `eb552ed2` at 07:54:03Z and 08:15:54Z-08:16:15Z;
- `{'model': 'deepseek-v4.1-flash'}`, seen in the controlled repro window at 2026-10-01T17:18:22Z-26Z (~5s);
- `{'model': 'deepseek-v4-flash'}`, seen in the #285 recon drop.

The classifier in `actor.py::_is_retryable` covered only transport/timeout/5xx/429, so a 400 degraded the turn immediately.
Even where a retry did fire, it re-fired inside the same window with no temporal backoff and the same session id, so a pinned bad replica was never abandoned.
A short window therefore killed a long hunt (and silently dropped a recon extraction, #285).

The upstream window is external and not reproducible on demand (~5s in hours of probing).
No acknowledged external incident exists for the live-trial times.
The root cause is confirmed as a temporal upstream fault; H1 (global window) and H2 (session-scoped bad replica) are not fully separated.
The remediation covers both, because session rotation helps under either.

## Decision

### 1. One pure classifier, distinct from the provider-failure class

`app/llm/transient.py` is the ONE home of the transient-fault policy.
`classify_error(exc, *, provider=None, model=None) -> Literal["transient", "contract", "fatal"]` is pure (no I/O) and fail-open.
`provider`/`model` are the LANE identity the caller threads from its own routing (the resolved role, or the `<provider>:<model>` call label); when they are unknown the 400 leg cannot match.

- `transient`: the existing transport/timeout/5xx/429 class, read through the shared `provider_failure.is_provider_unavailable` (#329), PLUS the EXACT opencode-go deepseek single-model-echo 400 (below).
- `contract`: an HTTP 400 whose body carries a recognisable actionable marker (`MissingSessionID`, `reasoning_content`, `response_format`, `top_p`, `tools[N].function missing field name`).
- `fatal`: anything else, including an EMPTY 400, a foreign/unrecognised model echo, any multi-key envelope, and any non-400 client error (403, 404, ...).

#### The transient-400 signature (operator ruling D-1, 2026-10-08)

The earlier rule - "an HTTP 400 whose body is empty or is exactly `{"model": <str>}`" - OVER-FIRED: an empty 400 from ANY lane, and any `{"model": ...}` envelope, armed the fallback, so a deterministic contract 400 could masquerade as a window.
The D-1 ruling narrows the branch to the FULL conjunction of the exact lane signature:

1. **status 400** (through the litellm-wrapped `Error code: 400` shape the SDK exposes);
2. the parsed JSON body is an object whose **ONLY key is `model`** - no `error`/`message`/`type`/`param`/`code`/`detail` key - and whose string value **EQUALS the wire model id for THIS call** (the stripped id the upstream echoes; the deepseek lane ids are `deepseek-v4.1-flash` and the `deepseek-v4-flash` variant of #285);
3. the response is from the **opencode-go provider** for that model - the lane identity the caller passes - NOT a model id alone, so another provider serving the same id cannot match.

Everything else stays `contract`/`fatal` and MUST NOT arm the fallback: an empty 400 (indistinguishable from a bare contract error from any provider), a `{"model": <foreign-id>}` echo, and any `{"error": ..., "model": ...}` envelope.

**The header leg is UNVERIFIED.** The D-1 ruling preferred a discrete response-header attribute (e.g. a specific `content-type`/`server`/provider header) as the lane discriminator.
No discrete header value was confirmed from the live capture: `diag/opencode-go-400` `DEBUG.md` probed response headers (`probes/monitor.py` captured `content-type`/`cf-ray`) only to REJECT the Cloudflare-HTML hypothesis (the 400 body is JSON, not HTML) and recorded no 400 header set that discretely separates the lane.
Per the ruling, the conjunction therefore rests on (status 400) AND (single-key `model` body == the configured deepseek wire id) AND (provider == opencode-go) - the tightest body+provider conjunction available - and this ADR records that the header leg is unverified.
If a future live capture confirms a discrete header, it is added as a REQUIRED leg.

The actor retry layer `actor.py::_is_retryable` delegates to `classify_error` with the role's resolved `(provider, model)`, so the retry budget and the classification can never drift.
The one-shot seam (`providers.invoke_with_escalating_timeout`) parses the `<provider>:<model>` call label for the same identity.
A contract or fatal 400 still degrades/fails-fast immediately: only the exact transient signature is newly retried, so a deterministic client error is never masked as a window.

**Grey point (classification of an unknown 400).** An unrecognised 400 body is `fatal`, not `contract`.
The consequence is identical at the actor (no retry, degrade), but the label stays honest: `contract` means a body we can name, `fatal` means a body we cannot.
Fail-open is preserved: an unknown fault is never retried.

**Grey point (consequence for the empty-body live variant).** The live-trial episode returned an EMPTY upstream body (`DEBUG.md`, `eb552ed2`); under D-1 that shape is deliberately NO LONGER transient, because it cannot be told apart from a bare contract 400.
Only the reproduced single-key `{"model": "deepseek-v4.1-flash"}` shape (the controlled E7 window) branches.
This is the operator's explicit trade: accept the empty-body blind spot to eliminate the contract-400 over-fire.

**Grey point (reading the body).** The body is read from the SDK's own `.body`, then the response JSON, then the response text.
`litellm` forwards the upstream body verbatim, and the pinned openai SDK exposes it on `.body`, so the classifier does not parse the exception string.
The wire id is derived with `sync_mapping.native_litellm_model`, the SAME mapping `build_chat_model` and the gateway use, so a provider-prefixed configured id (`opencode-go/deepseek-v4.1-flash`) compares against the stripped echoed id (`deepseek-v4.1-flash`).

### 2. Ride out the window: jittered temporal backoff plus session rotation

The actor retry loop (`actor.py::_turn`) and the one-shot loop (`providers.invoke_with_escalating_timeout`) gain the same policy:

- a jittered, exponential, capped delay between transient attempts - `jittered_backoff(attempt)`: `min(cap, base * 2**(attempt-1))` scaled by `1 +/- jitter`.
- a rotated conversation id per attempt - `rotate_conversation(thread_id, attempt)`: attempt 0 is the thread's own id, later attempts append `#r<attempt>`.

Defaults and knobs:

| Env | Meaning | Default |
|---|---|---|
| `LLM_TRANSIENT_BACKOFF_S` | base backoff between transient retries | `2.0` |
| `LLM_TRANSIENT_BACKOFF_MAX_S` | backoff cap | `30.0` |
| `LLM_TRANSIENT_JITTER` | jitter fraction (0..1) | `0.3` |
| `LLM_ATTEMPT_TIMEOUTS_S` | existing attempt schedule (reused) | `300,600,900,2700` |

A non-transient raise is NOT delayed by the transient wait: a `contract` 400 fails fast at both seams, and a `fatal` raise keeps the one-shot seam's today-immediate escalation for a parse failure, so the transient wait is reserved for faults it can outlast.
The backoff wait is a module-level seam (`actor._sleep` async, `providers._sleep` sync), so the unit tier injects a fake clock and never waits in real time.

**Grey point (rotation naming and agent memory).** The rotated id is `<thread_id>#r<attempt>`.
It reaches ONLY the provider conversation primitive (`x-opencode-session`), through the new `conversation_id` parameter of `run_session_turn` / `arun_session_turn`.
The checkpointer's `configurable.thread_id` and the returned `SessionTurn.thread_id` stay the original `thread_id`.
Rotation therefore abandons a pinned bad upstream replica without forking agent memory - the exact invariant the ticket demands.
The `session_id` of the reasoning-replay/checkpoint trail is unchanged, so a rotated turn still resumes the same conversation memory.

### 3. Bounded model fallback on exhaustion

`providers.resolve_fallback(role)` resolves a fallback model after the primary schedule is exhausted: the per-role `LLM_FALLBACK_<ROLE>` first, then the global `LLM_FALLBACK_MODEL`, both `<provider>:<model>`.
The fallback is attempted EXACTLY once - the actor runs one extra turn, and `invoke_role` runs one bounded attempt through `max_attempts=1`.
A malformed value fails open (a loud warning, no fallback), because this is read mid-retry and must not convert a recoverable turn into a hard failure.

**D-1 arming gate (amended 2026-10-08).** The fallback fires ONLY when the primary schedule is exhausted on a TRANSIENT fault (the exact lane signature) or on an all-None unmet-generation run.
A deterministic `contract`/`fatal` raise - an empty 400, a foreign-model echo, a contract-marker 400, or any other 400 - NEVER arms it.
At the actor, a non-retryable raise `break`s the loop and skips the `else: fallback` arm; at the one-shot seam, `invoke_with_escalating_timeout` takes a `fallback` callable and arms it only when the last raise classifies `transient` (or no raise was seen), and any non-transient 400 fails fast at the first attempt.

**Grey point (does a fallback role exist?).** No separate fallback role exists in the registry today, so the fallback is a MODEL OVERRIDE FOR THE SAME ROLE, not a different role id.
`roles.chat_model_for(..., model_override=...)` and `session._override_model_factory` build the override model with the role's own `thinking` baseline.
The structured-output METHOD is negotiated once for the primary and reused by the fallback; a fallback whose capabilities differ could need a re-negotiation, and that is a recorded forward step, not built here.

### 4. Observability: one structured record per transient attempt

`transient.record_transient(role, model, conversation_id, attempt, status, body_shape)` emits one structured WARNING record per transient attempt and increments a process-wide counter keyed by `(role, model, body_shape)`.
`transient_counts()` reads the counter (the unit tier's observable), and `reset_transient_counts()` isolates tests.
The record makes a recurring window visible before it exhausts the schedule and kills the run; the existing `actor turn degraded` warning stays the terminal signal.
A durable Langfuse span tag is a recorded forward step; the log line is the first observable.

**Grey point (the counter shape).** The counter is `(role, model, body_shape)`, and the log line carries the full `{role, model, conversation_id, attempt, status, body_shape}`.
The counter is deliberately in-process: the durable export is the log aggregation, matching the repo's current observability (there is no metrics sink).

## Consequences

### Proven by unit tests (the deterministic half)

- `classify_error`, with the lane identity, over the exact bodies the ticket records: `{"model": "deepseek-v4.1-flash"}` (and the `deepseek-v4-flash` variant) for `opencode-go` is `transient`; an EMPTY 400, a foreign-model echo (`{"model": "something-else"}`), a same-id body from another provider, and a multi-key `{"error": ..., "model": ...}` envelope are NOT transient (`fatal`); `MissingSessionID` / `reasoning_content` / `response_format` / `top_p` / `tools[].function` 400s are `contract`; 5xx/429/timeout are `transient`; unknown is `fatal`.
- The actor rides out a simulated bare-400 window (first N attempts fail), the turn completes, the provider conversation id rotates per attempt (`thread` / `thread#r1` / `thread#r2`), and `SessionTurn.thread_id` stays the original.
- A deterministic contract 400 degrades with exactly one attempt (no wasted retries) and emits no transient counter.
- The one-shot seam sleeps the jittered backoff and rotates only on a transient raise, never on a non-transient one, and fails fast on a contract 400.
- D-1 arming: the one-shot fallback is NOT fired for an empty 400, a foreign-model echo, or a multi-key envelope; the actor fallback is likewise skipped for every non-transient raise.
- `LLM_FALLBACK_<ROLE>` / `LLM_FALLBACK_MODEL` are attempted exactly once after a transient exhaustion.
- The transient counter is emitted once per attempt.
- An unconfigured environment (no fallback) behaves as before at every other seam.

### NOT proven (the live half, per the operator caveat)

- The upstream window itself is external and not reproducible on demand, so no test proves the fix rides out a REAL window.
- H1 (global) vs H2 (session-scoped) stays undiscriminated; the fix does not depend on the distinction.
- The fallback is a mitigation, not a fix; it is bounded to one attempt so it cannot mask a sustained outage.

### Behaviour changes and risk

- The EXACT opencode-go deepseek single-model-echo 400 is now retried instead of degrading. This is the intended fix; the class is narrow (status 400 AND a single-key `model` body equal to the configured deepseek wire id AND the opencode-go lane).
- An empty 400 that was previously retried (per the pre-D-1 rule) now fails fast as `fatal`: the deliberate narrowing trade recorded above.
- `classify_error` gains keyword-only `provider`/`model`; `actor._is_retryable` and `invoke_with_escalating_timeout` thread the lane identity.
- `invoke_with_escalating_timeout` gains keyword-only params (`model`, `max_attempts`, `fallback`) and binds a conversation scope per attempt. Existing callers pass positionally and are unchanged; test doubles that patch the seam must accept the new kwargs (updated in `tests/test_llm_probe.py`).
- `run_session_turn` / `arun_session_turn` gain two defaulted params (`conversation_id`, `model_override`); the default path is byte-identical.

## Impact map (as built)

- `src/polymerhus/app/llm/transient.py` (new) - `classify_error(outcome, provider, model)` with the D-1 lane-signature matcher (`_is_transient_lane_400`, `_wire_model_id`), `body_shape`, `jittered_backoff`, `rotate_conversation`, `record_transient`, the counter, and the env readers.
- `src/polymerhus/app/llm/provider_failure.py` - public `status_code`, the shared status reader.
- `src/polymerhus/app/llm/actor.py` - `_lane_identity`; `_is_retryable` delegates to `classify_error` with the role's lane identity; `_turn` gains jittered backoff, rotation, the transient record, and the bounded fallback; `_sleep` wait seam.
- `src/polymerhus/app/llm/providers.py` - `resolve_fallback`; `invoke_with_escalating_timeout` gains backoff, rotation, lane identity via `model`, `max_attempts`, and the D-1-gated `fallback` callable; `_sleep` wait seam.
- `src/polymerhus/app/llm/session.py` - `conversation_id` and `model_override` on both turn entry points; `_override_model_factory`.
- `src/polymerhus/app/llm/roles.py` - `chat_model_for(model_override=...)`; `invoke_role` rotates through the shared seam and passes the D-1-gated bounded fallback.
- `tests/test_llm_transient.py` (new) plus #299 cases in `test_llm_actor.py`, `test_llm_providers.py`, `test_llm_roles.py`, `test_llm_session.py` - including the D-1 cells (empty 400, foreign echo, foreign provider, multi-key envelope are not transient and do not arm the fallback).
- `.env.example` - the `LLM_TRANSIENT_*` and `LLM_FALLBACK_*` knobs.
- `src/polymerhus/app/CONTEXT.md` - the sub-module pointer, the fundamental decision, the "transient upstream fault" glossary entry, and the repeatable pattern.
