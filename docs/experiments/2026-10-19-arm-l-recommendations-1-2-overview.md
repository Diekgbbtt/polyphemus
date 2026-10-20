# Arm L recommendations 1 and 2: failure modes, root causes and fixes (2026-10-19)

Status: agreed direction; fixes pending (2026-10-19).
Companion documents: `docs/experiments/2026-10-19-arm-l-384-385-fixes-and-thinking-trials.md` (the measurements and the recommendations), `docs/experiments/2026-10-19-arm-l-high-vs-max-analysis-comparison.md` (the analysis-pipeline residual).
Scope: this document is a step back from the arm L numbers.
It explains the two accepted recommendations in plain terms: what failed, why it failed, and what the fix is.
Recommendations 3 (budget-aware hunting schedule) and 4 (serde allow-list on the trial stack) are deferred by operator decision and stay out of scope.

## Reading guide

Both recommendations sit on technical debt that is invisible in the arm L results table.
Recommendation 1 is one missing prompt line with a working safety net around it.
Recommendation 2 is one unnormalized exception type plus a missing retry on an idempotent read.
Each section below follows the same shape: the moving parts, the observed failure, the step-by-step failure sequence, the root cause, the fix, and the verification.
No code changed with this document.

---

# Recommendation 1: name the triager's structured-output tool in its prompt

## The moving parts (plain names)

- **Structured channel**: a workflow step where the model must deliver its answer by calling a named tool with the payload as the tool arguments.
  The workflow reads the tool call.
  It does not read the message text.
- **Text channel**: the model writes the same payload as plain message text instead, sometimes inside a fenced code block.
- **Channel drift**: the model answers on the text channel where the workflow expects the structured channel.
- **Structured-channel recovery**: the seam's second, corrective turn that names the tool and asks for a tool call.
  Arm L shipped this as the #385 fix.
- **Fail-open**: when the corrective turn also fails to produce a tool call, the seam parses the text payload and accepts it.
  The workflow keeps its data.
  It pays one extra call.

## What failed (observed)

The recon triager drifted on 5 of its turns across the two arm L trials.
Trial 1 (`high`) drifted twice.
Trial 2 (`max`) drifted three times.
The app log shows five warnings of the same shape:

```
2026-10-19T08:56:09 WARNING polymerhus.app.llm.session: stateful_turn triager structured-channel correction produced no structured result (empty); accepting the parsed text-channel payload (fail-open)
2026-10-19T09:01:06 WARNING polymerhus.app.llm.session: stateful_turn triager structured-channel correction produced no structured result (empty); accepting the parsed text-channel payload (fail-open)
2026-10-19T10:36:21 WARNING polymerhus.app.llm.session: stateful_turn triager structured-channel correction produced no structured result (empty); accepting the parsed text-channel payload (fail-open)
2026-10-19T10:42:08 WARNING polymerhus.app.llm.session: stateful_turn triager structured-channel correction produced no structured result (empty); accepting the parsed text-channel payload (fail-open)
2026-10-19T10:42:50 WARNING polymerhus.app.llm.session: stateful_turn triager structured-channel correction produced no structured result (empty); accepting the parsed text-channel payload (fail-open)
```

The traces show both answer shapes side by side.
Trial 1's first triager turn returned text: `"content": "```json\n[]\n```\n\n**Reasoning:** ..."`.
Trial 2's first triager turn returned a tool call: `"tool_calls": [{"name": "_ObservationBatch", "args": {"observations": []}, ...}]`.
The drift is therefore not thinking-specific.
It appears in both arms, and the recovery worked in all five cases: the text payload was parsed and accepted, and no observations were lost in either trial.

## The failure sequence, step by step

1. The pod's triage node calls `default_triage_fn` (`src/polymerhus/recon/domain/pod.py:764`).
2. The node runs `stateful_turn("triager", ..., schema=_ObservationBatch, ...)` (`pod.py:816`).
   The schema is bound through the LangChain `ToolStrategy`, so the model has a tool named `_ObservationBatch`.
3. The triager's system prompt is `src/polymerhus/recon/domain/prompts/writing-observations.md` (132 lines).
   This prompt never names the tool.
4. When the model writes the payload as message text, the tool-call parse returns an empty structured result.
   The seam's earlier reading of that shape was the "silent empty" bug shape.
5. The #385 recovery detects the shape and sends one corrective turn.
   `_STRUCTURED_CHANNEL_INSTRUCTION` (`src/polymerhus/app/llm/session.py:1076`) names the tool and requires a tool call.
6. In the five observed drifts the corrective turn again produced no structured result.
   The seam then parsed the text payload and accepted it, fail-open (`_recover_structured_channel`, `session.py:1175`; outcome `accepted_text_payload`).
7. The batch continued through curation.
   Nothing was lost.
   The cost is one extra triager call per drift plus a warning.

## Root cause

The prompt does not name the structured channel.
The two analysis roles were fixed with exactly one line each:

- `src/polymerhus/analysis/prompts/assigner.md:2`
- `src/polymerhus/analysis/prompts/technical-system.md:50`

Both lines say: deliver the payload by CALLING the `L1DeltaBatch` tool with the JSON as its arguments; never write the JSON in the message text; the tool call is the only channel the workflow reads.
The triager prompt has no counterpart.
Its sections cover the anchor rule, the primitives rule, the `macro_kind` vocabulary, common mistakes and red flags.
None of them says how the payload must be delivered.
The triager drifts because the prompt leaves the delivery channel implicit.

## Why this matters even though the recovery works

- Each drift costs one extra triager call and one warning line (5 drifts across 2 trials; a rate of 2/17 and 3/17 of the triager turns).
- The recovery depends on the text being uniquely parsable.
  When the text is not uniquely parsable, the seam falls back to the blackloop recovery.
  The historic worst case of that path is a silently dropped batch (the arm K shape, `systems_written=0`).
- The warning hides in a busy log.
  Drift is easy to miss and easy to rediscover late.

## The fix

Add one delivery line to `writing-observations.md`, directly under the Overview section:

> Deliver every Observation batch by CALLING the `_ObservationBatch` tool with the JSON as its arguments - never by writing the JSON in your message text; the tool call is the only channel the workflow reads.

Notes on the line:

- Use the wire name `_ObservationBatch` exactly.
  It is the `ToolStrategy` spec name that the seam resolves at runtime (`_structured_tool_name`, `session.py:1085`), and it is the name that appears in the traces.
- Renaming the entity to `ObservationBatch` would read better, but it changes the tool wire name and touches checkpoint state and the structured-envelope serde.
  That rename is out of scope here and should ride its own change.
- Keep the line single-purpose and positive, in the same voice as the two analysis lines.
- Keep the #385 recovery in place.
  The prompt line is prevention.
  The recovery stays the safety net.

## Verification

- Unit test: assert that the loaded triager prompt names `_ObservationBatch` and contains the phrase "only channel the workflow reads".
  Add it next to the existing prompt tests for the analysis roles.
- Next trial: count the recovery warnings on the app log.
  Acceptance: `grep -c "stateful_turn triager structured-channel"` returns 0.
- Trace check: the triager generations' tool calls carry `_ObservationBatch`, and the trace metadata field `structured_channel_recovery` (`session.py:1239-1245`) stays absent.
- Keep the warning path and its counter.
  A drift after the fix is a finding, not noise to silence.

---

# Recommendation 2: bound the eval status-poll retries

## The moving parts (plain names)

- **Status poll**: the eval harness asks the instance API "is the run finished yet?".
  The call is an idempotent `GET` (`recon_status`, `analysis_status`, `hunting_status`; `eval/orchestrator/api.py:215-232`).
- **Read timeout**: the poll client allows 30 s for the answer (`HttpApiRunner.__init__`, `api.py:120`; `urlopen(..., timeout=self.timeout)`, `api.py:136`).
  A busy app can miss that deadline.
- **Transport failure**: a call that failed before any HTTP answer existed.
  The runner models this as `ApiError` with status 0.
- **Hard failure vs transient**: the trial treats a raised error as terminal.
  That intent is correct for a dead app.
  It is wrong for one slow answer.

## What failed (observed)

Trial 2's harness aborted at 87 minutes on a 30 s read timeout on a status poll.
The hunting arm was cut mid-run.
No trial record, no verdicts and no assessment exist for trial 2.
The analysis had already drained, so the primary criterion stayed valid.
The hunting phase is not comparable, and the artifact store has no trial 2 record to materialize.

## The failure sequence, step by step

1. The trial driver polls the run status.
   `Trial._poll` (`eval/orchestrator/trial.py:870`) calls `self._call(status_call)` in a loop.
2. The app was busy with analysis and hunting work.
   The HTTP connection opened, but the response did not arrive within 30 s.
3. `urlopen(...).read()` raised `TimeoutError: timed out`.
   Verified empirically: a stalled response raises `builtins.TimeoutError`, and `isinstance(exc, urllib.error.URLError)` is `False`.
4. `HttpApiRunner.__call__` wraps `HTTPError` and `URLError` into `ApiError` (`api.py:139-143`).
   It does not catch `TimeoutError`.
   The raw exception escaped the seam.
5. `Trial.run` catches `api.ApiError` and writes a failed record through `_finish_api_failure` (`trial.py:612-649`).
   A raw `TimeoutError` matched no handler and propagated out of `run()`.
6. The abort skipped the record write.
   The run left no record, no verdicts and no assessment.

## Root causes

- **D1: incomplete error normalization in the runner.**
  A read-phase timeout escapes the `URLError` wrap.
  The class docstring promises that "a transport failure raises with status 0".
  A read timeout violates that promise.
- **D2: no retry on the poll.**
  One slow response is treated as terminal.
  A status poll is an idempotent read, so a bounded retry is safe and correct.
- **D3: containment depends on D1.**
  The driver's failed-record path is keyed on `ApiError`.
  While D1 exists, some transport failures lose the trial record entirely.

## The fix (two layers)

**Layer A - normalize the seam (`eval/orchestrator/api.py`).**
Catch the read-phase timeout and wrap it into the seam's own error type:

```python
except (TimeoutError, ConnectionError) as exc:
    raise ApiError(call, 0, str(exc)) from exc
```

This guarantees that no raw transport exception escapes, and that `_finish_api_failure` always writes its record.
The change is small and strictly increases correctness.

**Layer B - retry status polls with a bound (`eval/orchestrator/trial.py`).**
Add a helper that wraps `self._call(status_call)` in `_poll` and `_poll_hunting` only:

- Retry on retryable faults: `ApiError` with status 0 (transport) and 502/503/504 responses.
- Never retry 4xx.
  A 404 for a wrong run id is an answer, not transport noise.
- Attempts: 3.
  Backoff: for example 5 s, then 15 s.
  Each delay stays far below the trial budget and above one poll interval.
- Log every retry with the attempt number, the call path and the reason.
- After the last attempt, re-raise.
  The existing `ApiError` path then writes the failed record with the reached phase, so nothing is silent anymore.

Design notes:

- The retry sleeps run inside the poll loop, so they count against the trial budget.
  Document that in the helper.
- Keep the 30 s per-attempt timeout.
  The fix is about retrying a slow poll, not about waiting longer per attempt.
- Do not retry non-idempotent calls.
  The retry belongs to the poll seam, not to `HttpApiRunner`.
  The runner also issues `POST` launches, `PUT` settings and multipart file writes.
- Keep the abort path for persistent faults.
  A bounded retry must not turn a dead app into an infinite wait.

## Verification

- Runner test: a stub whose response read raises `TimeoutError` -> the runner raises `ApiError(status=0)`, not `TimeoutError`.
- Poll-helper tests:
  (a) one transport fault, then a terminal status -> the poll returns and the record is written;
  (b) persistent transport fault -> exactly 3 attempts, then the re-raise, and the trial record is a written failure naming the phase;
  (c) `ApiError(404)` -> raised immediately, one attempt;
  (d) a `POST` call is never retried (assert exactly one call on the spy).
- Trial-level check: run a trial against a stub API that stalls one poll.
  Assert the trial completes and the record exists.

---

# Order of work and ownership

1. Recommendation 1 first: one prompt line plus one test.
   Smallest diff, immediate noise reduction in the triager traces.
2. Recommendation 2 next: `api.py` (Layer A) plus `trial.py` (Layer B) plus the tests above.
3. Both fixes land before the next trial run.
   Recommendation 1 removes the recovery noise from the triager traces.
   Recommendation 2 protects the trial record from a single slow poll.

# References

- Code anchors: `src/polymerhus/recon/domain/pod.py:764,816`; `src/polymerhus/recon/domain/prompts/writing-observations.md`; `src/polymerhus/app/llm/session.py:819,1076,1085,1175,1239`; `src/polymerhus/analysis/prompts/assigner.md:2`; `src/polymerhus/analysis/prompts/technical-system.md:50`; `eval/orchestrator/api.py:111,120,124,139-143`; `eval/orchestrator/trial.py:530,612,620,870,942,1068`.
- Drift evidence: app log grep for `stateful_turn triager structured-channel` (5 lines, timestamps above); triager traces `/tmp/arml-traces/high_triager_0.jsonl` and `/tmp/arml-traces/max_triager_0.jsonl`.
- Abort evidence: `docs/experiments/2026-10-19-arm-l-384-385-fixes-and-thinking-trials.md`, Known Issues (trial 2 ended early).
- Timeout check: `urllib.request.urlopen("http://<stalling-server>", timeout=1).read()` raises `builtins.TimeoutError`; `isinstance(exc, urllib.error.URLError)` is `False`.

*Documented on 2026-10-19.*
