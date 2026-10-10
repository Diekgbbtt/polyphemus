# Assessor lifecycle investigation - hang and leak

Status: diagnosis report, uncommitted, no production change made.
Author: diagnosis subagent, branch `investigate/assessor-lifecycle` (base `dev` `70b7b5e`).
Date: 2026-10-09.
Scope: the eval assessment dispatch layer (`eval/orchestrator`, `.opencode/`).

This report investigates two reported failures.
It separates observation from inference, states assumptions, tests each hypothesis against the recorded evidence, and flags the weak links.

- Failure 1: the assessment for trial `comfyui-1-20261009T110342-1fc05262` runs for over an hour with no `verdicts.yaml`.
- Failure 2: many `opencode run --agent eval-assessor` processes from 2026-10-08 onward stay resident on `eval-server-polyphemus`.

The two failures share one root cause.
The rest of this report proves that claim.

## 1. Executive answer

Failure 1 is not an extensive assessment.
The assessor process for that trial made no progress at all: its model stream errored at 11:03:50 with `AI_APICallError: Go usage limit exceeded`, and the pinned opencode (`1.18.34`) `run` command did not exit.
The process has been idle in an epoll wait ever since, with its hourly cleanup timer still firing, and it will never write `verdicts.yaml` or terminate.

Failure 2 is the same event repeated.
Every assessor dispatch since at least 2026-10-04 hits the provider quota, hangs after the stream error, and is never reaped.
No `verdicts.yaml` exists anywhere on the eval server: **zero** of the twelve trials have ever been assessed.

Two independent defects compose:

- A defect in the dispatch lifecycle in this repo: the harness launches the assessor with no wall-clock timeout, no process-group kill, and no reaping, so a subagent that hangs is never stopped.
- An upstream defect in opencode `1.18.34`: `run` does not terminate on a fatal provider stream error.

## 2. Observed evidence

All commands were read-only.
No process was killed and no file was modified on the server.

### 2.1 Failure 1 - the "still running" assessor

Process list (server time 2026-10-09 12:58 UTC):

```
PID     PPID  PGID      SID       STAT  STARTED                ELAPSED  PCpu  TIME     ARGS
3940799 1     3940799   3940799   Ssl   Fri Oct  9 11:03:42    01:55:19 2.3   00:02:44  opencode run --agent eval-assessor ... comfyui-1-20261009T110342-1fc05262 ...
```

Observations for PID 3940799:

- `State: S (sleeping)`, `Threads: 18`, `VmRSS: 434084 kB`.
- `wchan = ep_poll`; every non-main thread is `futex_do_wait`.
- `lsof -p 3940799` lists **no TCP/IP socket**.
- `ls -l /proc/3940799/fd` shows `stdin -> /dev/null`, `stdout -> ...verdicts.yaml.dispatch.log`, `stderr -> ...verdicts.yaml.dispatch.log`, plus the opencode db and log.
- It has **no child process** (`ps --ppid 3940799` is empty).
- Its dispatch log is 49 bytes: one banner line `> eval-assessor · deepseek-v4.1-flash` and no more.

The opencode log for this run shows the trigger and the aftermath:

```
11:03:49.987 process session.id=ses_edfaaa8... agent=eval-assessor mode=all
11:03:50.009 "llm runtime selected" llm.provider=opencode-go llm.model=deepseek-v4.1-flash
11:03:50.307 ERROR "stream error" ... agent=eval-assessor error.error="AI_APICallError: Go usage limit exceeded"
11:03:55.173 ERROR "stream error" ... agent=title error.error="AI_RetryError: Failed after 3 attempts. Last error: Go usage limit exceeded"
11:04:45.835 WARN "cleanup failed" exitCode=128 stderr="fatal: gc is already running ..."
12:04:45.954 INFO cleanup prune=7.days
```

The trial record confirms the state:

```
terminal: stopped
assessment:
  status: dispatched
  attempts:
  - attempt: 1
    outcome: dispatched
    at: '2026-10-09T11:03:42+00:00'
```

The event loop is alive, not deadlocked: opencode's own hourly `cleanup prune` fired at 11:04:45 and 12:04:45.
The model call is not blocked: there is no socket, and the stream error returned at 11:03:50.
The process is idle after a fatal error and simply never exits.

### 2.2 Failure 2 - the leaked processes

`ps` of all `--agent eval-assessor` processes (server time 2026-10-09 12:59 UTC):

| PID | PPID | STARTED | ELAPSED | fd 1 (stdout) | destination trial |
|---|---|---|---|---|---|
| 1869692 | 1 | Oct 8 15:10 | 21:49 | pipe | comfyui-1-20261006T104129 |
| 1904355 | 1 | Oct 8 15:26 | 21:33 | pipe | comfyui-1-20261006T104129 |
| 2720305 | 1 | Oct 8 23:28 | 13:31 | dispatch log | comfyui-1-20261008T232836 |
| 2820259 | 1 | Oct 9 00:28 | 12:30 | dispatch log | comfyui-1-20261008T232836 |
| 2919522 | 2919521 | Oct 9 01:29 | 11:30 | pipe | comfyui-1-20261006T104129 |
| 3581483 | 3581482 | Oct 9 07:55 | 05:04 | pipe | jetlinks-1-20261006T125842 |
| 3940799 | 1 | Oct 9 11:03 | 01:55 | dispatch log | comfyui-1-20261009T110342 |
| 3940829 | 3940802 | Oct 9 11:03 | 01:55 | pipe | comfyui-1-20261006T104129 |

Total: 8 processes, about 2.8 GB RSS, oldest about 21.8 hours.
Every one is in `S`/`Ssl` (sleeping), and none has a network socket.

The stdout target splits them into two dispatch families:

- `stdout -> ...dispatch.log` (PIDs 2720305, 2820259, 3940799) were launched by the monitor through `BackgroundRunner` (detached, `start_new_session=True`).
- `stdout -> pipe` (PIDs 1869692, 1904355, 2919522, 3581483, 3940829) were launched by a synchronous runner (`subprocess.run(capture_output=True)`).

The pipe cases have `python3 -m orchestrator close-verify ...` as parent:

```
2919521  PPID 1  python3 -m orchestrator close-verify eval/setups/verify-4m.yaml ...
3940802  PPID 3897979  python3 -m orchestrator close-verify eval/setups/verify-4m.yaml ...
3581482  PPID 1  python3 -m orchestrator close-verify eval/setups/verify-4m-jetlinks.yaml ...
```

The three live `close-verify` parents (2919521, 3581482, 3940802) are themselves in `wchan = poll_schedule_timeout.constprop.0` - blocked.
They are blocked inside `subprocess.run` waiting for a child that never exits.

### 2.3 The provider error is the common trigger

`grep -c "Go usage limit exceeded" opencode.log` = 21.
The errors span 2026-10-04 through 2026-10-09.
Every leaked process maps to a `Go usage limit exceeded` error at its start time.
The provider is the `opencode-go` relay; the quota is the known, recurring 5-hour workspace limit recorded as EV-21 / #330 / #331 in `docs/design/eval-bugs-map.md`.

### 2.4 No assessment has ever succeeded

```
find /opt/polymerhus-dev/eval/runs -name verdicts.yaml    -> (empty)
find /opt/polymerhus-dev/eval/runs -name diagnoses.yaml   -> (empty)
```

All twelve trial records have no `verdicts.yaml`.

| trial | terminal | verdicts |
|---|---|---|
| comfyui-1-20261009T110342 | stopped | no |
| comfyui-1-20261008T232836 | stopped | no |
| comfyui-1-20261006T104129 | timeout | no |
| comfyui-1-20261008T152623 | timeout | no |
| jetlinks-1-20261006T125842 | timeout | no |
| jetlinks-1-20261007T120203 | timeout | no |
| siyucms-1-20261007T170558 | timeout | no |
| prestashop-1-20261007T140458 | timeout | no |
| dataease-1-20261007T224115 | timeout | no |
| white-jotter-1-20261007T202534 | timeout | no |
| comfyui-1-20261007T085807 | failed | no |
| comfyui-1-20261007T093538 | failed | no |

### 2.5 No orchestrator agent is current

`ps` shows only the 8 `--agent eval-assessor` processes.
No `--agent eval-orchestrator` process is running.
The trial record's assessment attempt history for `comfyui-1-20261009T110342` has exactly one attempt.
Therefore the monitor tick has not run since 11:03:42, and the re-dispatch/escalation path has not been exercised for that trial.

## 3. Hypothesis testing

### H1 - "A failed tool call or an LLM inference call is BLOCKED (hung)."

Rejected as stated.

The inference call did **not** block.
It returned a fatal error at 11:03:50 (`AI_APICallError: Go usage limit exceeded`).
The hung process holds no socket, so it is not waiting on a network read.
The hang is **after** the failed call, not during it.

The precise statement is: the process does not terminate after a failed inference call.

### H2 - "The assessment's internal loop has NO reliable process-close lifecycle."

Confirmed.

opencode `1.18.34` `run` stays alive after the fatal stream error.
Evidence: no socket, `wchan = ep_poll` for hours, hourly `cleanup prune` still firing, no `run`-level log line after the error, and no `verdicts.yaml` written.
The process's event loop is healthy but its run completion never settles into an exit.

This is an upstream defect in the pinned opencode version.
It is not something the repo code can fix from the outside except by wrapping or upgrading opencode.

### H3 - "The `opencode run` primitive used for the dispatch is not the most optimal (fire-and-forget with no timeout/reaper)."

Confirmed for the monitor path, and worse for the synchronous path.

The monitor path uses `BackgroundRunner` (`eval/orchestrator/commands.py:83-123`).
It calls `subprocess.Popen(..., start_new_session=True)` and **discards the handle**, returning a synthetic `CommandResult(0)` at once.
Nothing stores the pid, nothing waits, nothing polls, and nothing kills the child.
A hung child is invisible to the tick and is never reaped.

The synchronous path (`close-verify`, manual `assess`, manual `diagnose`) uses `LocalRunner` (`eval/orchestrator/commands.py:62-77`), which is `subprocess.run(...)` with no `timeout=`.
A hung child therefore blocks the parent forever.

### H4 - "Subagents could be dispatched IN PLACE in the parent agent loop (a bounded, awaited child)."

Not yet tested - this is a design option, not an observed behaviour.
It is evaluated in section 5.

### H5 (own) - "The monitor's re-dispatch leaks a new process each time and never kills the previous one."

Confirmed by code, not yet observed at scale for the monitor.

`monitor.decide` (`eval/orchestrator/monitor.py:183-206`) re-dispatches a node after `DEFAULT_BUDGET_S = 3600.0` until `MAX_DISPATCHES = 2`, then escalates.
`cli._apply_monitor` (`eval/orchestrator/cli.py:1325-1339`) calls `assessment.dispatch`, which calls the dispatcher again.
There is no code anywhere that tracks or kills the previous dispatch's process.
The `AssessmentRecord` (`eval/orchestrator/trial.py`) stores no pid.
The docstring of `dispatch` in `assessment.py:104-121` and `subagents.py:246-260` says "fire-and-forget" explicitly.

The leak is already observed via `close-verify`, which re-invokes the dispatcher in a loop (`assessment.verify_trial`, `eval/orchestrator/assessment.py:214-224`): trials `comfyui-1-20261006T104129` have four separate hung assessor processes (1869692, 1904355, 2919522, 3940829).

## 4. Root cause

Both failures share one event (the provider quota) and one structural cause (no process lifecycle).

### 4.1 The hang

The exact chain:

1. The provider relay returns a fatal error: `AI_APICallError: Go usage limit exceeded`.
2. opencode `1.18.34` `run` logs the stream error but does not terminate the process.
   The process keeps an idle event loop and its hourly cleanup timer, and never writes the output.
3. The harness has no wall-clock timeout around the dispatch, so nothing stops the hung process.
4. The harness writes the output file as the only completion signal, so a hung process is indistinguishable from a slow one until the wait budget expires.

The design decision behind it is D52 (`docs/design/eval-multi-instance-decisions.md:424-478`).
D52 rejected "a fixed timeout around the synchronous runner" because "a timeout still blocks the tick" and "turns a slow but healthy subagent into a spurious failure".
That reasoning is sound for tick concurrency, but D52 then assumed only three subagent outcomes:

- the subagent writes its output (success), or
- the subagent exits without writing (caught by the bound as `empty_file`/`schema_invalid`), or
- the launch raises (caught as `dispatcher_process`).

D52 did not consider a fourth outcome: the process **neither writes, nor exits, nor raises** - it hangs forever.
The wrong assumption is: *"a subagent always terminates, so bounding the dispatch count is sufficient."*
The count bound limits how many hung processes are created; it does not stop any of them.

Two further wrong assumptions:

- That completion can be observed solely through the output file.
  A hung process produces no signal at all, and the re-dispatch logic creates a second hung process rather than replacing the first.
- That the provider always answers.
  The assessor inherits none of the app-layer provider-failure handling designed for EV-21 (#330/#331), because it is an external `opencode run` process, not an app-layer agent seam (`docs/design/eval-bugs-map.md` sections 8-9).

### 4.2 The leak

Three code sites cause the leak, none of which reaps or kills:

- `eval/orchestrator/commands.py:100-123` - `BackgroundRunner.__call__` spawns with `subprocess.Popen`, discards the handle, and returns `CommandResult(0)`.
  No pid is retained; no wait, poll, or kill is possible afterwards.
- `eval/orchestrator/commands.py:65-77` - `LocalRunner.__call__` uses `subprocess.run` with no `timeout=`, so a hung child blocks the parent forever.
- `eval/orchestrator/cli.py:1109-1118` - `close-verify` calls `assessment.verify_trial`, which calls the synchronous dispatcher before it records the attempt.
  A hung child blocks `close-verify` at the dispatcher call, so line 1118 (`record_assessment`) never runs and the trial record stays `assessment: null`.
  This is why the four hung assessors for `comfyui-1-20261006T104129` are not even visible as attempts.

The wrong assumption behind the leak is: *"the detached child is someone else's problem."*
But the tick that launches the child exits immediately, and no later tick can identify or stop the child, because no pid is ever recorded.

### 4.3 Confidence

- H1 refinement (hang is after the error, not during): high confidence. Direct log evidence, no socket, idle state.
- H2 (opencode does not exit on the fatal error): high confidence from observation; the internal reason is not visible from the server, so the mechanism is inferred.
- H3 and H5 (no timeout/reaper/kill): high confidence; verified in the code.
- The provider quota as trigger: high confidence; 21 matching errors and a documented recurring limit.

## 5. Dispatch-primitive evaluation

Requirement: the assessor must be isolated (write-only to one file, out of band), must not block the monitor tick, and must be bounded so a hung or slow run can never leak or block.

### Option A - keep `opencode run` detached, add a lifecycle wrapper

Keep `BackgroundRunner` for concurrency, but make it accountable:

- Record the child pid and process-group id.
- Enforce a hard wall-clock timeout (`Popen.wait(timeout=...)` or a watchdog on a timer).
- On timeout, kill the whole process group (`os.killpg(SIGTERM)`, then `SIGKILL`), and reap with `wait()`.
- On a re-dispatch, first kill and reap the previous child for that node.
- Resolve a fatal launch/exit outcome to a non-zero result so the tick can escalate `dispatcher_process` promptly instead of waiting for the budget.

Trade-offs: preserves process isolation and tick concurrency; keeps the assessor out-of-band.
Costs: a per-node process registry and a watchdog; still depends on opencode exiting cleanly on success.

### Option B - dispatch a bounded, awaited child in the parent agent loop

Use opencode's own subagent primitive (or an in-process `invoke_role`-style call) so the assessment is a child of the orchestrator agent's loop.

Trade-offs: no orphan process is possible, and the parent's own error handling bounds it.
Costs: the tick blocks while the child runs (unless the parent parallelises), which reintroduces the coupling D52 removed; the assessor's write-only isolation is less crisp; and a provider error would still hang the child unless the same fatal-error handling exists.

### Verdict

The primitive choice is secondary.
The decisive missing piece is **process lifecycle**: a hard timeout, a process-group kill, and a reap, plus killing the previous dispatch on re-dispatch.
Without that, neither primitive is safe.
With that, Option A is the smaller change and preserves the concurrency D52 wanted.

Option B is worth considering only as a later simplification, and only if opencode's subagent primitive converts a provider error into a terminal failure.

Separately, the opencode `run` behaviour must be addressed because it is the direct cause of the hang:
either upgrade/patch opencode so `run` exits non-zero on a fatal provider error, or wrap the dispatch command so a provider error is detected and the process is terminated.

Finally, the assessor dispatch should not run when the provider quota is known exhausted.
The tick should treat `Go usage limit exceeded` as a backoff condition, not as a normal dispatch, to avoid leaking a process per attempt.

## 6. Recommended fix

Three layers.
Layers 1 and 2 are required; layer 3 is the durable guard.

### Layer 1 - make the assessor fail fast on a provider error

- Wrap the dispatch so a fatal provider error terminates the child with a non-zero exit, or upgrade opencode to a version where `run` exits on a fatal stream error.
- Acceptance criteria:
  - A simulated provider error (`AI_APICallError`) makes the assessor process exit non-zero within a bounded time.
  - The dispatch log records the error.
  - The node escalates `dispatcher_process` on that non-zero exit.

### Layer 2 - give the dispatch a real lifecycle

- In `BackgroundRunner`, retain the `Popen` handle and its process-group id per node.
- Enforce a per-dispatch hard timeout.
- On timeout or re-dispatch, kill the process group (`SIGTERM`, then `SIGKILL`) and reap.
- Give `LocalRunner` a `timeout=` and treat a timeout as a failed dispatch, so `close-verify` cannot block forever.
- Acceptance criteria:
  - A dispatched command (`sleep 3600`) is killed at the timeout and reaped; no process remains.
  - A second dispatch for the same node kills the first.
  - `close-verify` against a hung assessor returns within the timeout and records an escalation.
  - No `opencode run` process older than the timeout remains after a run.

### Layer 3 - quota-aware backoff

- Detect the provider-quota error and back off the assessment dispatch for the node until the rolling window clears, rather than dispatching into a known failure.
- Acceptance criteria:
  - With the quota exhausted, a tick does not launch a new assessor process.
  - The trial records an `awaiting` or deferred state, not a leak.

### Immediate operator remediation (not performed in this investigation)

- The 8 leaked processes on `eval-server-polyphemus` are safe to terminate once the operator chooses to (`kill` the pids, or `pkill -f 'agent eval-assessor'`).
- The 3 blocked `close-verify` parents must be terminated too, or their children will be respawned by the loop.
- No data is lost: none of them ever wrote an output file.

## 7. Ticket proposal (do not file unless asked)

Title: `Assessment/diagnosis dispatch has no timeout, kill, or reap; a hung opencode run leaks forever and blocks close-verify`.

Category: bug, HIGH.

Summary:
A fatal provider error (`AI_APICallError: Go usage limit exceeded`) makes `opencode run` 1.18.34 neither exit nor write its output.
The harness dispatch (`BackgroundRunner`, `LocalRunner`) has no timeout, no process-group kill, and no reaping, so every such dispatch leaks a process forever, and the synchronous `close-verify` path blocks forever inside `subprocess.run`.
This currently blocks the entire assessment layer: zero `verdicts.yaml` have been produced on the eval server.

Evidence:
- 8 leaked assessor processes, about 2.8 GB RSS, oldest about 21.8 hours, all sleeping with no socket.
- `wchan = ep_poll`, hourly `cleanup prune` still firing, no output written.
- `find runs -name verdicts.yaml` empty across 12 trials.
- `close-verify` parents blocked in `poll_schedule_timeout`.

Root cause (file:line):
- `eval/orchestrator/commands.py:100-123` `BackgroundRunner` discards the `Popen` handle.
- `eval/orchestrator/commands.py:65-77` `LocalRunner` has no `timeout=`.
- `eval/orchestrator/assessment.py:104-121` / `subagents.py:246-260` fire-and-forget dispatch with no lifecycle.
- `eval/orchestrator/cli.py:1109-1118` `close-verify` blocks before recording the attempt.
- Design assumption in D52 (`docs/design/eval-multi-instance-decisions.md:424-478`) that a subagent always terminates and that the output file is the only completion signal.

Proposed fix: layers 1-3 above.

Acceptance criteria: as listed per layer.

Related: EV-21 / #330 / #331 (provider quota and app-layer provider-failure handling).
Note: the assessor is an external `opencode run` and therefore outside the #331 app-layer handler; this ticket covers the harness dispatch lifecycle.

## 8. Weak links and open questions

- The internal opencode mechanism that prevents the process from exiting is inferred, not read from source.
  The observable behaviour is certain; the fix in layer 1 should be validated against a specific opencode version or an upstream issue.
- The stall of the eval-orchestrator agent (no tick since 11:03:42) was not investigated.
  It is consistent with an operator stop, but the operator should confirm whether the orchestrator was intentionally halted.
- Whether the monitor path has ever created a second hung process for the same node was not observed live; it is proven from the code and observed in the `close-verify` path.
- The provider quota itself (EV-21) is environmental and out of scope; this report treats it as the reliable trigger it is.
