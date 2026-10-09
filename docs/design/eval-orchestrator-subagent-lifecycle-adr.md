# ADR D57 - The eval orchestrator dispatches subagents as bounded, awaited native opencode child sessions

*2026-10-09.* Supersedes D52 (the detached, non-blocking post-execution
dispatch) and amends D6.
Status: accepted.

## Context

The eval assessment layer had never succeeded: zero `verdicts.yaml` across
twelve trials.
The diagnosis (`docs/design/assessor-lifecycle-investigation.md`) proved two
composed defects.

1. The pinned opencode `1.18.34` `run` command does not exit after a fatal
   provider stream error.
   A `Go usage limit exceeded` (`AI_APICallError`) left the process idle in
   `ep_poll` forever, so `verdicts.yaml` never landed.
2. The harness dispatch had no process lifecycle.
   `BackgroundRunner` launched a detached `opencode run` with
   `start_new_session=True`, discarded the `Popen` handle, and returned a
   synthetic success.
   `LocalRunner` used `subprocess.run` with no `timeout=`.
   Nothing retained a pid, nothing killed a hung child, and a re-dispatch
   created a second hung child instead of replacing the first.

D52 assumed a subagent always terminates and that the output file is the only
completion signal.
The fourth outcome - the process neither writes, nor exits, nor raises - was
never considered, so the dispatch count bounded how many hung processes were
created without stopping any.

## Decision

The post-execution dispatch is a **bounded, awaited native opencode child
session**, driven synchronously, and reordered after target bring-up.

### The native primitive

The opencode harness exposes an awaited child dispatch through the plugin SDK
the runtime injects into every plugin (`PluginInput.client`):

- `client.session.create({ body: { title }, query: { directory } })` creates the
  child session.
- `client.session.prompt({ path: { id }, query: { directory }, body: { agent,
  parts: [{ type: "text", text }] } })` prompts it with a role agent and
  **awaits** the assistant message.
- `client.session.abort({ path: { id } })` stops it.

The awaited `prompt` is the key: unlike `opencode run`, it settles when the
session's assistant message completes, carrying the message's `error` field on a
provider failure.
So a fatal provider error is a non-zero terminal, never a hang.
No Python-side native client is needed: the plugin owns the dispatch because it
owns the authenticated SDK client.

### The plan/apply split

The symbolic Python layer stays the deterministic brain, and the plugin is the
only dispatcher.

- `orchestrator monitor --plan` is read-only.
  It emits, as JSON, each trial's tick state and the next action: a `dispatch`
  (the role agent, the launch message, and the destination) or an `escalate`
  (the named cause).
- The plugin runs each `dispatch` action as a native child, classifies its
  terminal (`success`, `no-output`, `failure`, `timeout`), and writes the
  terminals to a JSON file.
- `orchestrator monitor --results <file>` persists the attempts and re-plans,
  returning the next action.
  The plugin loops until nothing is pending.

The assessor and the diagnoser are therefore **fully synchronous within one
`eval_monitor` tool call**: the assessor runs to a terminal and writes
`verdicts.yaml`, then the diagnoser runs for the `missed`/`partial` verdicts and
writes `diagnoses.yaml`.
There is no fire-and-forget dispatch and no detached process.

### The reordered workflow

Each orchestrator iteration addresses configuration, launch, and health first,
then assessment and diagnosis.
`next_target` (reclaim, provision, `up`, health) runs before `eval_monitor`, so
the previous trial's assessment and diagnosis never delay or interleave with the
next target's bring-up.

### The lifecycle

- The plugin bounds each child with a wall-clock timeout and aborts it on
  expiry.
  A timed-out child is a `timeout` terminal, recorded as a `dispatcher_process`
  escalation when the bound is exhausted.
- `LocalRunner` (the synchronous path the manual `assess`/`diagnose` and
  `close-verify` verbs use) runs the command in its own process group under a
  wall-clock timeout, and on expiry kills the whole group (SIGTERM, a bounded
  grace, then SIGKILL) and reaps it.
  It returns exit code 124 instead of blocking the caller.
- The leaky `BackgroundRunner` (no wait, no kill, discarded handle) is removed.
- A provider-quota death is recorded as the distinct `provider` attempt outcome,
  and the tick backs the node off for `--provider-backoff-s` (default 5h)
  instead of hot-looping a new child against the exhausted window.

## Alternatives rejected

- **Keep the detached process, add a watchdog (D52 Option A).** It preserves
  concurrency but cannot fix the upstream `opencode run` hang and still needs a
  per-node process registry and reaper.
  The operator directive is to adopt the native primitive where one exists; it
  does.
- **Dispatch with a synchronous `opencode run` under a timeout (no native
  child).** It fixes the leak but keeps the upstream hang as the failure mode
  and still spawns a CLI process per dispatch.
  It remains only as the manual-verb path, now bounded.

## Consequences

- A subagent can no longer hang forever: the awaited child settles with an
  error, and the plugin aborts it past the bound.
- The assessor -> diagnoser flow is synchronous; a trial converges in one tick
  when the provider cooperates.
- The Python state machine (`orchestrator/monitor.py`) stays the single,
  unit-tested source of truth; it gains one branch, the provider-quota backoff
  (`DEFAULT_PROVIDER_BACKOFF_S`), and only the dispatch primitive moved.
- Residual risk: the native child-session dispatch depends on the opencode
  server's awaited `prompt` settling on a provider error.
  The diagnosis observed the session's own error handling does settle (the hang
  is in the `run` CLI, not the server session); the plugin's timeout + abort
  bounds the case where it does not.
  The bounded synchronous `LocalRunner` remains available as the manual path.

## Falsification checks

- `test_monitor_plugin_dispatches_awaited_native_child_sessions` - the plugin
  creates, prompts, and aborts child sessions and contains no `Popen`.
- `test_orchestrator_commands.py` - a timed-out `sleep 30` is killed and reaped
  within the grace window and returns exit 124.
- `test_orchestrator_cli_monitor.py` - a plan is read-only; an assessment
  `success` advances straight to the diagnosis; a `failure` records an `error`
  attempt and awaits; a provider death records `provider` and backs off; an
  escalation writes the named failure once.
- `test_orchestrator_monitor.py` - a provider death is awaited past the normal
  budget, re-dispatches only after the provider backoff, and escalates
  `dispatcher_process` when exhausted.
