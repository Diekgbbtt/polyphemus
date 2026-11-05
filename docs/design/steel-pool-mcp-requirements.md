# Steel worker pool: revised requirements and MCP transport evaluation

Date: 2026-11-04.
Status: requirements analysis and design evaluation, not approved.
Supersedes on lease ownership, capacity, crawler, start atomicity, and graceful stop:
`docs/design/steel-pool-control-plane-impact-analysis.md`.
The session-affinity findings in that document remain valid.

> Revision 2026-11-05: the MCP server and the pool manager are one co-located
> component on Kali. The progress token is removed as a correctness requirement.
> The outlier release ladder is expanded. The crawler uses the MCP channel.
> The persistent MCP session was proven with FastMCP 2.14.7.
> The CLI is the authoritative executor. The existing guard and contract logic
> stay in the loop unchanged. The selected deployment path is the v0.5.5-beta
> image with `--no-nginx` and `ENABLE_COMMANDS_API=true`. Browser control uses
> the commands API. CDP uses the API endpoint with a single `Host: localhost`
> header. The 9223 nginx proxy and the image-internal Host patch are removed.
> The CLI main is the matching commands-API client. The pinned daemon CLI is not
> compatible with the no-nginx path.
> See `docs/design/steel-pool-mcp-prototype-report.md`.

## 1. Purpose

This document does two things.

1. It integrates the operator feedback into a precise change requirement.
2. It evaluates a dedicated Steel MCP transport against the symbolic-layer pool design.

The target is a pool of Steel API workers.
Each worker has one live Steel session.
Agents lease a worker for the life of one named browser session.
The pool must assign, track, and release leases without losing capacity.

## 2. Definitions

**Worker**: one Steel API container.
It supports one active browser session.

**Browser session**: one named Steel CLI session and its client-side daemon.
The daemon lives in the Kali container's home directory.
It is bound to the worker that served its `start`.

**Terminal session**: the `session_id` argument of the Kali MCP `execute_command` tool.
It selects the workdir `/work/<session_id>`.
It is not a process, a browser, or a lease owner.

**Kali container**: one container per Polyphemus instance.
It runs the Kali MCP server, the Steel CLI, the wrapper, and the guard.
All terminal sessions in one Kali share the home directory and the CLI daemons.

**Cross-Kali**: across two Kali containers, which means two Polyphemus instances.
The CLI daemons and local session records do not cross.
A session started in one Kali is invisible to the other, except through the worker API.

**Cross-terminal**: within one Kali, across `session_id` workdirs.
The CLI daemon is shared.
Reuse by name works across terminal sessions.
A name collision is also possible across terminal sessions.

**Symbolic layer**: the deterministic code that turns a browser intent into a CLI invocation or a tool call.
It is not the LLM.
It owns worker addressing.
It receives the worker identifier from the pool manager and injects it into the invocation.

**Pool manager**: the external service that assigns workers and holds the lease ledger.
It is the single writer for worker assignment.

**Live connection table**: the pool manager's record of active leases and their MCP sessions.
It is the capacity source of truth.
A project stop must empty the owner's rows.

**Steel client**: the agent-side component that holds the browser lease.
In the MCP design it is the MCP client session plus the server-side session record.

**Steel MCP server**: the dedicated Kali MCP endpoint that runs Steel CLI commands and owns the session-to-lease mapping.
It is separate from the exec MCP server.

**Owner**: the project or trial that owns a lease.
It is not the LLM role and not the terminal session.
The owner is stable across roles and enables shared sessions.

## 3. Feedback corrections

### 3.1 Cross-Kali is a container boundary

The earlier document used "Kali" to mean the Kali container.
It did not mean a terminal session.
The distinction matters:

- A terminal session cannot own a browser lease.
  All terminal sessions in one Kali share the same CLI daemon.
- A cross-terminal name collision is possible inside one Kali.
- A cross-Kali session cannot be reused by name.
  The daemon and the local record live in the other container.

The requirement is to make the lease owner the project or trial, not the terminal session.

### 3.2 Pool size 4 is a policy value

The execution gate is the concurrency ceiling for agents.
The browser pool is the concurrency ceiling for browsers.
The two values are independent.
A pool of 4 is acceptable when the gate and the measured browser duty cycle make it safe.

The requirement is not to cover every agent at once.
The requirement is to make the wait explicit, bounded, and visible.
The pool size is a deployment value.
The operator aligns it with the gate.
A queue entry must return a typed `pool_exhausted` or `pool_wait` response with a retry hint.
The queue entry must cancel when the caller disconnects or the tool call times out.

### 3.3 The symbolic layer owns worker addressing

The pool manager returns a worker identifier.
The symbolic layer injects it into the Steel invocation.
The agent never chooses the worker.
The guard is not the allocator.
The guard may enforce and report, but it does not own the assignment.

In the CLI design, the symbolic layer is the `SteelSessionClient` prefix or the deployment wrapper.
In the MCP design, the symbolic layer is the Steel MCP server.

### 3.4 Start is one contract step

`start` is the one command that creates a session.
The agent sees one tool call or one command.
On success it gets a live session and a lease.
On failure it gets a typed error and no lease.

The implementation still performs three internal steps:

1. Acquire the worker.
2. Create the session.
3. Record the session id and the lease.

The contract must be atomic.
A partial internal failure must compensate.
The compensation is a release, a stop, or a quarantine.
The agent must never see a lease without a session.

### 3.5 Release is owned by the Steel client

The lease client belongs to the Steel client.
It is not a separate lease daemon.
A separate daemon introduces an independent failure and a second lifecycle.

The lease is keyed by the named browser session.
The owner is the project or trial.
The client releases on `end`, `stop`, `close`, `quit`, or `exit`.
The client releases all leases on `stop --all`.
The server or pool manager releases on TTL, disconnect, or project stop.

"No independent failure" is a design goal, not a literal property.
A server process can still fail.
The requirement is that its failure is the client's connection failure, not a hidden daemon failure.
The pool manager's TTL and reconciler are the final backstop.

### 3.6 The graceful project stop must clear the table

A project stop closes the agents and their MCP sessions.
That closes the live browser sessions as a consequence.
The pool manager's live connection table must also be emptied.
The table is the source of truth for capacity.
A stale table blocks future leases.

The stop handler must:

- call the pool manager's `release_all(owner)`;
- mark the owner's entries released;
- clear the live connection table for that owner;
- be idempotent across repeated stops;
- tolerate an unreachable pool manager by marking entries stale and relying on the TTL.

The eval orchestrator calls `POST /projects/{id}/execution/stop`.
That endpoint is the integration point.
The MCP server's session close is the backstop.
The pool manager's table is authoritative over the MCP server's cache.

### 3.7 The crawler is now a CLI session consumer

`feat/steel-crawl` rewrites the crawler as a deterministic engine.
The engine attaches to a pre-authenticated session by name and runtime id.
It never starts a session.
It stops the session it owns by default.
It can be told not to stop a shared session.

The engine uses `SteelSessionClient`.
That client has an injectable `exec_fn` and a `cli_prefix`.
It accepts a worker-specific prefix such as `steel --api-url <worker> browser`.
This is a symbolic-layer seam.

The agent image does not install the Steel CLI.
The default `("steel", "browser")` prefix would fail in the agent container.
The clean fix is to route the crawler's `exec_fn` through the Steel MCP server.
That also gives the crawler the pool lease and the session record.

The crawler's `stop_session` flag must be coordinated with the lease.
If the crawler stops the owned session, the lease is released.
If the session is shared, the crawler must not stop it.
The owner remains the project or trial.

## 4. Revised requirements

### 4.1 Lease lifecycle

- L1: The lease unit is the named browser session.
- L2: The lease owner is the project or trial.
- L3: The lease client is part of the Steel client.
- L4: `start` acquires the worker and creates the session as one contract step.
- L5: A failed create releases or quarantines the lease.
- L6: `end`, `stop`, `close`, `quit`, and `exit` release the lease.
- L7: `stop --all` releases every lease owned by the client.
- L8: A start on an existing name is idempotent and reuses the same worker.
- L9: A start on a stale name releases the old lease before creating a new session.
- L10: A lease has a TTL and a heartbeat.
- L11: The TTL exceeds the longest browser command.
- L12: The TTL and the Steel session clocks are aligned on `start`.
- L13: The pool drains instead of preempting a live session.

### 4.2 Pool manager

- P1: The pool manager is the single writer for worker assignment.
- P2: The pool manager returns a worker identifier or a typed wait response.
- P3: The pool manager records the owner, session name, lease id, worker id, and session id.
- P4: The pool manager reaps a lease when the worker has no live session.
- P5: The pool manager quarantines a worker with an unknown live session.
- P6: The pool manager frees a worker only after the session is gone.
- P7: The pool manager clears the live connection table on project stop.
- P8: The pool manager persists or drains its lease table on restart.
- P9: The pool manager exposes queue depth and lease latency.
- P10: The pool manager is the only component with Docker access.

### 4.3 Worker addressing

- W1: The agent never sees a worker URL or a pool token.
- W2: The symbolic layer injects the worker address.
- W3: A user-supplied `--api-url` is rejected or stripped.
- W4: The exec MCP path cannot run `steel` after cutover.
- W5: The Steel MCP server is a separate endpoint from the exec MCP server.
- W6: The worker network is private.
- W7: The CDP port is not published.
- W8: The pool API is fixed-function and authenticated.

### 4.4 MCP transport

- M1: One long-lived MCP session per browser task.
- M2: The MCP session id is the lease handle; the owner is the project or trial.
- M3: The client sends DELETE on normal completion.
- M4: The server releases on DELETE.
- M5: The server releases on a heartbeat timeout when DELETE is absent.
- M6: The server exposes `browser_start`, `browser_exec`, `browser_end`, and `browser_status`.
- M7: The server refuses a command before `start` and after `end`.
- M8: The server serializes commands per session.
- M9: The server enforces a command timeout and kills the process group.
- M10: The server returns structured errors.
- M11: The server records lease and worker ids in the trace.
- M12: The server releases all leases on graceful shutdown.
- M13: The server drains or re-adopts leases on restart.
- M14: The server reuses `steel_contract` and `run_in_process_group`.
- M15: The server exposes a sync exec seam for the crawler, or the crawler uses the async MCP client.

### 4.5 Graceful stop

- G1: The project stop handler calls `release_all(owner)`.
- G2: The handler clears the live connection table for the owner.
- G3: The handler is idempotent.
- G4: The MCP server's session close is the backstop.
- G5: An unreachable pool manager leaves entries stale, not live.
- G6: The eval records the stop outcome.

### 4.6 Eval

- E1: The eval records pool waits, failures, reaps, and worker ids.
- E2: The assessor treats pool exhaustion as infrastructure, not a target miss.
- E3: The pool drains between targets.
- E4: A shared pool across trials is opt-in and measured.
- E5: The pool size and the execution gate are recorded per trial.

## 5. The MCP design

### 5.1 Components

```text
agent container
  LLM role
    MCP client session  ------------------+
    crawler SteelSessionClient            |
      exec_fn -----------------------------+
                                           |
                                           v
kali container                             |
  steel MCP server (separate endpoint) <---+
    session map: mcp session -> lease
    lease client -> pool manager
    CLI runner -> steel wrapper -> guard -> CLI -> daemon
                                           |
                                           v
steel host
  pool manager
    lease table
    worker registry
    reaper
    Docker API
  worker 1 ... worker N
    Steel API + Chrome
```

The Steel MCP server runs in Kali because the CLI and the daemon live there.
The pool manager runs on the Steel host because it owns the workers.
The agent holds the MCP session and the lease.
The server executes the CLI and owns the session-to-lease mapping.
The pool manager owns the ledger and the table.

### 5.2 Sequence

1. The agent opens one MCP session to the Steel MCP server.
2. The agent calls `browser_start` with a session name and options.
3. The server asks the pool manager for a worker.
4. The pool manager returns a worker id or a typed wait.
5. The server runs `steel --api-url <worker> browser start ...`.
6. The server records the lease, the session id, and the worker.
7. The server returns the session id, name, and live URL. It does not return the worker URL.
8. The agent calls `browser_exec` for commands.
9. The server runs the command through the wrapper and guard.
10. The agent calls `browser_end`.
11. The server runs `steel browser stop`, confirms the session is gone, and releases the lease.
12. The agent closes the MCP session.

If the agent disappears after step 7, the server sees a heartbeat timeout or the pool manager reaps the TTL.
If the server disappears, the MCP session closes and the pool manager reaps.
If the project stops, the handler calls `release_all` and clears the table.

### 5.3 Server state

The server holds one record per MCP session:

- MCP session id.
- Lease id.
- Owner project or trial.
- Browser session name.
- Steel session id.
- Worker id.
- Last activity.
- State: starting, active, ending, released, failed.

The record is a cache.
The pool manager's ledger is authoritative.
The server must be able to drain its records on restart.
It must not reassign a worker from a stale record.

### 5.4 Streaming

MCP tool calls are request and response.
The server can send progress notifications for long commands.
The client must send a progress token.
The current adapter may not surface progress to the LLM.
The final result still arrives once.

Streaming is useful for liveness and long commands.
It is not a replacement for a bounded timeout and cancellation.
The server must still enforce a timeout and kill the process group.

### 5.5 Keep-alive and disconnect

A streamable HTTP MCP session can stay open across tool calls.
The server can assign an `Mcp-Session-Id`.
The client must send it on every request.
The client should send DELETE when done.
The server may terminate the session at any time.

Disconnection is not cancellation in the MCP spec.
A dropped SSE stream does not prove the client is gone.
The server must use a heartbeat and a TTL.
The pool manager must reconcile the worker's live session.
The connection is a useful signal, not a guarantee.

## 6. Critical evaluation

### 6.1 Benefits

**One path to the browser.**
Every Steel command goes through one server.
The server sees the session, the lease, the worker, and the error.
The guard-only design sees only Kali shell commands.

**Explicit lifecycle.**
`browser_start` and `browser_end` are typed tools.
The server can refuse a command before start or after end.
The lease is not inferred from shell text.

**Worker address stays server-side.**
The agent never sees a worker URL or a pool token.
The agent cannot choose a worker with `--api-url`.
The server injects the address.

**Crawler integration.**
The new crawler has an `exec_fn` seam.
The server can be that seam.
The crawler gets the CLI, the lease, and the session record without installing the CLI in the agent image.

**Typed errors.**
The server can return `pool_exhausted`, `pool_wait`, `session_missing`, and `auth_required`.
The agent can react without parsing shell output.

**Observability.**
One server logs every command, lease, and worker assignment.
The trace can carry the lease id and worker id.
Debugging a failed session does not require searching several Kalis.

**Security.**
The worker URL and pool token are not agent-visible.
The server can enforce session ownership.
The exec path can be closed to `steel` commands.

**Maintenance.**
The CLI version pin, the wrapper, the guard, and the pool client live in one place.
The skill becomes a tool contract, not a shell-script contract.

### 6.2 Costs and risks

**Tool-surface migration.**
The skill, the auth gateway prompt, the crawler, and the tests teach or use `steel browser ...` shell commands.
Moving to MCP tools requires rewriting all of them.
This is the largest cost.

**Persistent MCP session risk.**
The current adapter opens a session per tool call.
The design needs one session per browser task.
The app has a precedent for holding a session, but the agent tool binding is different.
If the session is per call, the lease mapping breaks.
This is the make-or-break technical risk.

**Disconnect is not release.**
The MCP spec says disconnection is not cancellation.
A killed agent may leave a live lease until the TTL.
The server must heartbeat and the pool manager must reconcile.
The connection alone is not enough.

**Dual endpoints.**
The exec MCP and the Steel MCP are separate.
The agent must know which tool to use.
The exec MCP can still run `steel` unless it is closed.
A partially migrated agent can bypass the pool.

**Server state.**
The server holds a session map.
A restart loses it.
The pool manager must drain or reap.
The agent sees a broken MCP session and must restart the task.

**Streaming limits.**
MCP progress is optional and requires a token.
The adapter may not surface it to the LLM.
The tool call still blocks for the final result.
Streaming does not remove the need for timeouts and cancellation.

**Ownership split.**
If the server is in Kali, the client is in the agent and the executor is in Kali.
The lease owner is the client, but the process is separate.
This is not "no independent failure"; it is a failure that is visible as a connection error.
If the operator requires one ownership boundary, the CLI and server must move into the agent container.
That is a larger image and dependency change.

**Crawler stop coordination.**
The crawler stops the session it owns by default.
If the session is shared, it must not stop it.
The lease release must follow the stop.
A crawler stop that bypasses the server leaves a stale lease.

**Testing.**
The server needs tests for start, exec, end, disconnect, TTL, restart, ownership, and the crawler seam.
The eval needs two concurrent agents, a pool of one, a forced disconnect, and a project stop.

### 6.3 Comparison

| Dimension | Guard-only | Dedicated Steel MCP |
| --- | --- | --- |
| Lease owner | Guard process in Kali | MCP client session plus server record |
| Release trigger | Explicit stop, TTL | Explicit end, DELETE, TTL, project stop |
| Worker address | Injected by wrapper or guard | Injected by server, never agent-visible |
| Agent surface | Shell strings | Typed tools |
| Skill impact | Low | High, full rewrite |
| Crawler fit | Bypasses the guard | Natural `exec_fn` seam |
| Error shape | Parsed shell output | Structured tool errors |
| Observability | Per-command trace | Session and lease trace |
| Streaming | CLI stdout | MCP progress, limited |
| Independent failure | Guard process | Server process, visible as connection failure |
| Migration risk | Low | High |
| Long-term maintainability | Two paths | One path, one server |

### 6.4 Verdict

The MCP design is directionally better for reliability and maintainability.
It centralizes the browser path and makes the lease explicit.
It fits the rewritten crawler better than the guard-only design.

It is not a drop-in.
It is a tool-surface migration with one make-or-break risk: the persistent MCP session.
Prove that first.

Do not remove the guard yet.
Keep it as defense-in-depth until the exec path is closed and the MCP server is proven.
The guard can remain the shell-level enforcement point while the MCP server becomes the canonical path.

The pool manager stays external.
The MCP server is the lease client, not the pool manager.
The pool manager is the single writer and the source of truth for the table.

## 7. Proofs required before build

1. Hold one MCP session across `browser_start`, several commands, and `browser_end` with the current adapter.
   If the adapter cannot, build a custom client session.
2. Prove a normal DELETE releases the lease.
3. Prove a killed client leaves a lease that the TTL reaps.
4. Prove the server refuses a command before start and after end.
5. Prove the server serializes two commands on one session.
6. Prove the server kills a timed-out command process group.
7. Prove the crawler's `exec_fn` runs through the server.
8. Prove the crawler's `stop_session=False` path does not release a shared lease.
9. Prove the project stop clears the live connection table.
10. Prove a pool of one with two agents produces one lease and one typed wait.
11. Prove the wait cancels when the caller disconnects.
12. Prove a server restart drains and does not double-assign.
13. Prove the agent environment and tool output carry no worker URL or pool token.
14. Prove the exec MCP cannot run `steel` after cutover, or the guard covers it.
15. Prove the eval records pool waits, failures, and reaps.

## 8. Recommendation

Run a narrow spike before the full build.

The spike has four parts:

1. A steel MCP server on a separate Kali endpoint.
2. A persistent MCP client session in the agent.
3. `browser_start`, `browser_exec`, `browser_end`.
4. A fake pool manager with two workers and a TTL.

Measure four things:

- Whether the client session survives the whole browser task.
- Whether a killed client releases through the TTL.
- Whether the crawler's `exec_fn` works through the server.
- Whether the project stop clears the table.

If the spike passes, migrate the skill and the crawler to the MCP tools.
Keep the guard and the single-endpoint mode as rollback.
If the spike fails on the persistent session, fall back to the symbolic-layer CLI design.
That design is less elegant but keeps the existing skill and crawler surface.

## 9. Open questions

- Where must the pool guard live: the agent container or the Kali container?
- If it must be the agent container, should the Steel CLI move there?
- Can the current MCP adapter hold one session across a whole browser task?
- Should the server expose typed tools per verb, or one `browser_exec`?
- Should the crawler use the MCP tool surface or a plain HTTP exec endpoint?
- Does the project stop handler live in this repo or the platform API?
- How does the stop handler reach the pool manager?
- What is the measured concurrent browser count per trial?
- What is the browser duty cycle per role?
- Is a shared pool across trials acceptable?
- What is the worker memory under the heaviest target?
- How long does a cold worker take to serve its first session?
