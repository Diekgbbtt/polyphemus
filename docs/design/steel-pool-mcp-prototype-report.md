# Steel pool MCP prototype: design revision and results

Date: 2026-11-05.
Status: prototype report, not production approval.
Supersedes the ownership, progress-token, outlier-release, and crawler sections of
`docs/design/steel-pool-mcp-requirements.md`.

## 1. Verdict

The co-located MCP server and pool manager on Kali works.
One MCP session is a stable lease handle across start, execute, and end.
The pool released explicitly, on owner stop, and on TTL.
The MCP connection close alone is not a release trigger in this prototype.
The progress token is not required for correctness.
The command engine is the working executor on the local Steel image.

The remaining production risk is not the lease protocol.
It is the Steel API image and CLI daemon compatibility.
The local `latest` image has a broken root CDP WebSocket proxy.
The pinned CLI daemon fails against it.
The deployed `0.0.1` API works.
The prototype used the command engine to isolate the lease protocol from that defect.

## 2. Design revision

### 2.1 One component on Kali

The MCP server and the pool manager are one component.
They run in one process in the Kali container.
The component owns:

- the MCP session map;
- the lease table;
- the worker registry;
- the release policy.

There is no external pool manager service.
There is no second lifecycle to fail independently.

This is the operator's ownership direction.
It also matches the reliability property under test:
the MCP session id is the lease handle, and the lease table is in the same process.

The component does not own Docker.
The prototype uses a static worker list from `STEEL_POOL_WORKERS`.
Worker provisioning stays outside the component.
If lazy container creation is required, a narrow privileged provisioner must own it.
The Kali component must not receive the raw Docker socket.

Scope: one component per Kali container.
A pool shared across Kali containers needs a shared ledger or a static worker partition.
The prototype tests the per-Kali model.

### 2.2 Pool size

Pool size 4 is a policy value.
The execution gate is the concurrency ceiling.
The browser pool is the browser-specific ceiling.
The two values are aligned by the operator.
The requirement is not to cover every agent at once.
The requirement is a typed wait with clear semantics when the pool is full.

The prototype used two workers and three clients.
Two clients acquired both workers.
The third received `pool_exhausted` after an 8 second wait.
The wait response carried `retry_after_ms: 1000`.

### 2.3 Progress token

The progress token is not required.

The LLM never sees the MCP progress channel.
It sees the tool call and its final result.
The progress token is an MCP protocol field for in-flight progress notifications.
It is needed only when the client asks for intermediate progress.

The prototype sent two `browser_navigate` progress events.
The client received them at value 0 and value 1.
The tool result was still one final payload.
The LLM would not see either event.

Removing the progress token from the correctness requirements simplifies the design.
Keep progress notifications as an optional diagnostic.
Use a transport-level keep-alive and a bounded command timeout for reliability.

### 2.4 Outlier release ladder

The TTL from the last command is the backstop, not the primary fix.
The prototype confirmed that a killed client is reaped after the TTL.
It also confirmed that a normal MCP close without `browser_end` is not a release trigger.

The release ladder is:

1. Explicit `browser_end`.
2. MCP DELETE from a normal client close.
3. MCP transport disconnect plus a grace period.
4. Agent run timeout from the platform supervisor.
5. CLI daemon death, when the CLI path is used.
6. Worker session gone, seen by the reconciler.
7. TTL from the last command.

Each signal has a different confidence and delay.
The server should use the strongest available signal.
The pool manager should reconcile the worker session state before freeing a worker.
The TTL remains the final backstop.

The prototype implemented signals 1 and 7.
It observed signal 2 but did not act on it.
FastMCP exposes the session object and id.
A production server should hook session termination if the framework exposes it.
If it does not, the TTL is the floor.

### 2.5 Crawler

`steel_crawl` moves to the MCP channel.

Start and stop are owned by the symbolic layer.
The crawler attaches to the session and executes commands.
The crawler does not start a session.
The crawler does not stop a shared session.
`stop_session` is false for a shared lease.

The prototype ran a three-page probe through one MCP session and one lease.
It navigated to three URLs, evaluated `location.href`, and read the title.
It ended the lease once.

The full engine still needs the `exec_fn` adapter.
The crawler's `SteelSessionClient` accepts an injected `exec_fn`.
That is the seam for the MCP call.

## 3. Prototype

### 3.1 Components

- Two `ghcr.io/steel-dev/steel-browser-api:latest` containers.
- One `polymerhus-kali:latest` container for the MCP server and pool manager.
- Two `polymerhus-agent:latest` client processes.
- One Docker network `steel-proto-net`.
- The MCP server on port 8003.
- The workers on ports 3100 and 3101.

### 3.2 Why the command engine

The pinned CLI `0.5.0-preview.6` starts a per-session daemon.
The daemon connects to the Steel API root WebSocket.
The local `latest` API image returns HTTP 500 on that root proxy.
The error from the CLI is:

`CDP WebSocket connect failed: HTTP error: 500 Internal Server Error`

The deployed API `0.0.1` serves the root proxy correctly.
The local image's proxy path is the defect.

The command engine on `/v1/sessions/<id>/commands` works.
The prototype creates the session with `POST /v1/sessions`.
It drives it with the command engine.
It releases with `POST /v1/sessions/<id>/release`.

This isolates the MCP and pool protocol from the CLI daemon defect.
The production design must still choose the executor:
the command engine, or the CLI with a compatible API image.

### 3.3 Protocol

1. The client opens one MCP session to `http://steel-mcp:8003/mcp`.
2. The client calls `browser_start`.
3. The server acquires a worker from the local pool.
4. The server creates the session on that worker.
5. The server records the lease and returns the session id and worker name.
6. The client calls `browser_navigate`, `browser_eval`, and `browser_get`.
7. The server drives the command engine on the leased worker.
8. The client calls `browser_end`.
9. The server releases the worker.
10. The client closes the MCP session.

The client never sees the worker URL.
The server never exposes the pool token.

## 4. Scenario results

| Scenario | Clients | Workers | Result |
| --- | --- | --- | --- |
| Concurrent | 2 | 2 | Both acquired different workers, both completed, both released |
| Exhaustion | 3 | 2 | Third got `pool_exhausted` after 8 s, then both holders were reaped on TTL |
| Killed client | 1 | 2 | Client killed after 5 s, TTL reaped at 15.8 s, table empty |
| MCP close without end | 1 | 2 | Client closed normally, no `browser_end`, TTL reaped at 15.8 s |
| Owner stop | 2 | 2 | `release_owner` released both leases, table empty |
| Crawler probe | 1 | 2 | Three navigations through one lease, explicit release |
| Progress | 1 | 2 | Two progress events at 0 and 1, no errors |

### 4.1 Concurrent

The two clients started within 3 ms of each other.
They acquired `worker-1` and `worker-2`.
Both sessions were created in about 3.5 s.
Both navigated and read the page concurrently.
Both released explicitly.
The final `pool_status` showed two free workers and no leases.

### 4.2 Exhaustion

The two holders acquired both workers.
The third client waited 8 s.
It received `pool_exhausted`, `leases: 2`, `workers: 2`, and `retry_after_ms: 1000`.
The holders were killed.
The TTL reaped them at 16.6 s idle.
The final `pool_status` showed no leases.

### 4.3 Killed client

The outlier acquired `worker-1` and created a session.
The client was killed after 5 s.
The lease stayed idle.
The TTL reaped it at 16.1 s.
The release called the worker and freed the worker.
The final `pool_status` showed no leases.

### 4.4 MCP close without end

The client started a session and exited normally after 3 s.
It did not call `browser_end`.
The MCP client sent DELETE on close.
The server did not release on DELETE.
The TTL reaped the lease at 15.8 s.
The worker had no live session afterward.

This is the key gap for the production design.
The MCP DELETE is a strong signal.
The prototype does not act on it.
The TTL is the current floor.

### 4.5 Owner stop

Two holders acquired both workers.
A third MCP session called `release_owner` with the project owner.
The server released both leases with reason `owner_stop`.
The table was empty immediately.
The holders were removed.

This is the project stop hook.
The pool manager can clear the owner's rows without waiting for the clients.

### 4.6 Crawler probe

One MCP session leased `worker-1`.
The client navigated to example.org, example.net, and example.edu.
It evaluated `location.href` and read the title after each navigation.
It released the lease once at the end.
The server log shows all commands on the same worker and the same session id.

### 4.7 Progress

The client passed a `progress_handler` for `browser_navigate`.
The server sent progress at 0 and 1 with the URL and a completion message.
The client logged both.
The tool result was still one payload.
The LLM would not see the progress events.

The first run used a synchronous handler.
FastMCP raised `object NoneType can't be used in 'await' expression`.
The client was changed to an asynchronous handler.
The final run had no error.

## 5. Measurements

- Worker creation to live session: about 1.5 to 3.5 s.
- Navigation: about 0.3 to 0.8 s.
- Eval and get: about 0.1 s.
- Explicit release: about 0.2 to 1.4 s.
- TTL reap: 15.8 to 16.6 s with a 15 s TTL and a 2 s reaper interval.
- Pool wait: 8 s, the configured wait.
- Worker memory: 475 MiB and 471 MiB.
- MCP server memory: 121 MiB.
- No live sessions remained on either worker.
- Each worker kept one idle default session and a list of released sessions.

## 6. Findings and caveats

**The local API image blocks the pinned CLI daemon.**
The root CDP WebSocket proxy returns 500.
The deployed API `0.0.1` works.
Pin the API image and test the CLI daemon path, or use the command engine.

**MCP DELETE is not a release trigger by itself.**
The prototype did not hook session termination.
The TTL is the backstop.
Add a server-side close hook if FastMCP exposes it.
Otherwise use the TTL and a heartbeat.

**The TTL must exceed the longest command.**
A 15 s TTL is fine for the probe.
Production must align the TTL with the session clocks and the longest browser command.

**The pool manager is static.**
The prototype reads two worker URLs from the environment.
It does not create containers.
Lazy container creation needs a separate privileged provisioner.
Do not give the Kali component the Docker socket.

**The admin tools are not scoped.**
`pool_status` and `release_owner` are open to any MCP client in the prototype.
Production must scope them to the owner or an operator identity.

**The progress token is optional.**
The prototype demonstrates it.
It is not part of the lease contract.
The final tool result is the contract.

**The MCP session is the lease handle.**
The client session survived start and several commands in every scenario.
This is the property the design depends on.
The prototype proves it with FastMCP 2.14.7 and the streamable HTTP transport.

**The crawler integration is a probe, not the engine.**
The prototype ran the command sequence.
The full `SteelSessionClient` still needs the `exec_fn` adapter and the attach/stop ownership rules.

## 7. Design deltas

- Co-locate the MCP server and the pool manager in one Kali component.
- Keep the worker registry static or move provisioning to a separate privileged service.
- Use the MCP session id as the lease handle.
- Use the project or trial as the lease owner.
- Make `browser_start` one contract step with internal compensation.
- Remove the progress token from the correctness requirements.
- Add the release ladder. Keep the TTL as the last resort.
- Add a server-side session close cleanup if the framework exposes it.
- Move `steel_crawl` to the MCP channel. Start and stop stay with the symbolic layer.
- Scope the admin tools to the owner or an operator.
- Pin the Steel API image and decide the executor: command engine or CLI daemon.
- Keep the guard and the single-endpoint mode as a fallback.

## 8. Recommendation

Adopt the co-located MCP server and pool manager for the next implementation slice.

The prototype proves the lease protocol, the two-worker concurrency, the typed wait, the TTL reap, the owner stop, and the crawler command channel.

Before production:

1. Add the MCP session close cleanup.
2. Add owner-scoped admin tools.
3. Add worker health checks and a static registry.
4. Align the TTL and the session clocks.
5. Decide the executor after testing the pinned CLI against the pinned API image.
6. Run the full `steel_crawl` engine through the channel.
7. Keep the guard and the single-endpoint mode as rollback.

The prototype code and the scenario runner are in `prototype/steel_pool_mcp/`.
The runner writes evidence to `prototype/steel_pool_mcp/logs/`.
