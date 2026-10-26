# 425 - Pod-owned failure boundary and typed terminals

**What to build:** Move the primary failure detection into the pod graph with LangGraph node timeouts and an error handler, write a typed `PodExport` from the durable trail, and keep the surfer watchdog as a typed last-resort backstop.

**Blocked by:** none

**Status:** done

**Seams:** `attack/hunting/pod/graph.py`, `attack/hunting/pod/pod.py`, `attack/hunting/pod/config.py`, `attack/hunting/pod/failures.py`, `attack/hunting/pod/types.py`, `attack/hunting/surfer.py`

## Context

Iteration B produced 86 pod directories and 66 exports.
58 of the 66 exports were the 2700-second surfer watchdog's `budget-timeout` envelope, with zero raw observations.
The pods were progressing, not wedged: 37 of the 58 wrote a probe observation less than five minutes before the export; the median gap was 3.3 minutes.
The unit-wide pod batch put 20 pods on the qemu target at once.

The approved fix path moved the primary failure detection into the pod graph.
The surfer remains a last-resort backstop.

## Result

- `PodTimeouts` gives `runner_agent`, `triager`, and `tool_exec` a LangGraph `TimeoutPolicy`.
  The node idle timeout is 600 seconds and the tool idle timeout is 300 seconds.
  The optional node run timeout is off by default.
- The node `error_handler` routes `node-timeout`, `context-window-exceeded`, `graph-limit`, and `tool-timeout` to `degraded_terminal`.
  A provider failure re-raises for the surfer's retry/pause policy.
  A generic error keeps the `technical-infeasibility` degrade.
- `degraded_terminal` writes the typed `PodExport` from the durable experiment log.
- The surfer split the hunter and pod backstops: 2700 seconds for a hunter, 3600 seconds for a pod.
  The pod backstop writes `pod-watchdog-timeout`; the pod's own lap budget writes `budget-timeout`.
- Both surfer degraded envelopes now use the same `{verdict, evidence}` shape as the pod.
- The `TERMINAL_REASONS` vocabulary is split into domain and harness sets; the triager cannot choose a harness terminal.

## Verification

- `tests/attack/pod/test_failures.py`: 8 passed.
- `tests/attack/pod/test_graph.py`: 35 passed.
- `tests/attack/pod/test_verification.py`, `test_prompts.py`, `test_variant_mint.py`: passed.
- `tests/attack/test_hunting_session_watchdog.py`: 5 passed.
- `tests/attack`: 1143 passed.
- `tests/app` and `tests/eval`: 1157 passed, 22 skipped.
- `tests/project_management`: 159 passed, 6 skipped.
- Hunting integration selection: 50 passed, 28 skipped.
