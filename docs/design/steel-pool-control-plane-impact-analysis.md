# Steel worker pool: critical impact analysis

Date: 2026-11-03.
Status: analysis, not approved.
Scope: a pool of self-hosted Steel API workers for concurrent polymerhus agents.
This document tests the proposed design.
The design has a pre-created pool, lazy leases per agent, a pending request when the pool is full, and a default size of 4.

## Verdict

The pool is feasible.
The proposed shape is not the lowest-risk shape.
The session is not a platform object.
A live session is bound to one Steel API worker and one CLI daemon.
The pool only needs to choose a worker at `start`.
The hard problem is release certainty, not assignment.
A per-instance static pool is the lowest-risk first step.
A per-agent lease is the wrong unit.
A default size of 4 is below the running instance's concurrency ceiling.

## 1. The session-storage assumption

The assumption is half right.
The Steel API stores the live session.
The platform does not store the live session.
The CLI stores a client-side handle.

The Steel API has one `activeSession` and a `pastSessions` list.
`POST /v1/sessions` replaces the active session.
The API source is `steel-dev/steel-browser`, commit `9fb9b923`.
See `api/src/services/session.service.ts` at lines 67 and 93-121.

The pinned CLI is `0.5.0-preview.6`.
It runs one daemon per named session.
The daemon files live in the Kali container:

- `/root/.config/steel/daemon-<name>.pid`
- `/root/.config/steel/daemon-<name>.sock`
- `/root/.config/steel/daemon-<name>.log`

The daemon holds the client-side session state and the CDP connection.
It is bound to the worker that served the `start`.
The CLI's local state is therefore the affinity mechanism.

Live probe results:

- `steel browser start --session pool-probe` created a session on the deployed worker.
- `steel browser eval ... --session pool-probe --api-url http://127.0.0.1:9/v1` succeeded.
  The daemon ignored the wrong `--api-url`.
- `steel browser stop --session pool-probe --api-url http://127.0.0.1:9/v1` stopped the session.
  The daemon used its original worker.
- `steel browser start --session pool-flag-probe --api-url http://127.0.0.1:9/v1` failed.
  The error was `Failed to reach Steel API at http://127.0.0.1:9/v1/sessions`.
  The `start` command honors the flag.

The consequence is narrow and useful:

- Route `start` to a worker.
- Let the daemon pin every later command.
- Do not build a per-request router.
- Do not expect a live session to move workers.

The platform stores account state, not live sessions.
`src/polymerhus/app/steel_session_state.py` captures cookies, localStorage, sessionStorage, and indexedDB.
It restores that state through the create call.
A restored session gets a new id.
The tabs and in-memory state are lost.
A worker restart therefore ends the session.

### What session reuse means

Reuse has three cases:

- Same Kali, same session name: reuse works through the daemon.
- Different Kali, same session id: the current CLI source supports attach by id; verify the pinned build.
- Different worker: no live reuse; recreate from account state.

The pool must not promise more than the first case.
The second case needs a shared session id and worker URL.
The third case is a new session with a new id.

## 2. The actual call path

The browser command path is:

1. The agent calls the Kali MCP `execute_command` tool.
2. The MCP sanitizer checks the command and the live catalogue.
3. The shell resolves `steel` to `kali/steel_wrapper.sh`.
4. The wrapper adds `--local` and fixes the user agent after `start`.
5. The wrapper calls the guard at `kali/steel_guard.py`.
6. The guard validates, runs the real CLI, records a trace, and classifies the result.
7. The real CLI talks to the per-session daemon or creates one.
8. The daemon talks to the assigned Steel API worker.

The wrapper is not the reliable seam.
A nested shell can call the real binary through the guard.
The guard is the reliable seam because the real binary is private.
`kali/steel_guard.py` already parses `start`, `stop`, and the start output.
It already reads the new session id at lines 409-418.
It can own the pool client without changing the skill.

The guard must do four things:

- Acquire a worker before `start`.
- Inject `--api-url` into the real argv.
- Release on `stop`, `close`, `quit`, and `exit`.
- Heartbeat the lease on every command.

The guard must also strip a user-supplied `--api-url`.
Otherwise an agent can bypass the pool and pin a worker.
The wrapper already recognizes `--api-url` at line 33.
The guard must make the pool the only source of that flag.

Keep `STEEL_BROWSER_API_URL` set to a valid fallback in pool mode.
The wrapper uses it to add `--local`.
The guard uses it for the catalogue query.
The fallback must not be a worker that the pool leases.
Use a dedicated fallback worker, or make the fallback path fail closed.

## 3. Lease model

The correct lease unit is the named browser session.
It is not the agent.
It is not the request.

Reasons:

- The CLI daemon is keyed by session name.
- The daemon already carries the worker affinity.
- A request-scoped lease would drop the session between commands.
- An agent-scoped lease is too coarse and has no stable identity at the guard.
- The guard sees a command and a session name, not an LLM agent.

Lease operations:

- `acquire(name, owner, ttl)` on `start`.
- `heartbeat(lease_id)` on every command.
- `release(lease_id)` on `stop`, `close`, `quit`, and `exit`.
- `release_all(owner)` on `stop --all`.
- `replace(name, owner)` on `start` when the name already has a lease.

The acquire must be idempotent by name.
A repeated `start` for the same name must not consume a second worker.
The CLI replaces the existing session on the same worker.
The lease service should return the same lease.

The owner should be the project or trial, not the LLM role.
The auth gateway and the hunter can share a session by name.
The project identity is stable across roles.
An agent identity is not.

The `default` session name is unsafe in pool mode.
All agents in one Kali share the same daemon for `default`.
Require an explicit name, or namespace it per project.

Sessionless `steel scrape` needs a short lease.
The command is one-shot and has no session.
The guard can acquire any free worker, run the scrape, and release it.

Queue behavior:

- Bound the wait.
- Return a typed `pool_exhausted` error.
- Include a `retry_after_ms` value.
- Cancel the queue entry when the caller disconnects or the guard dies.
- Never leave a pending request without a client.

The proposed "leave the request pending" is not safe.
The MCP tool call has a timeout.
The LLM turn has a timeout.
A long queue stalls the trial and hides the capacity problem.

Lease clocks must agree with Steel clocks:

- The Steel inactivity timeout can release a session while the lease says active.
- The lease TTL can expire while a long command is still running.
- The wrapper and skill use a 300000 ms inactivity timeout in the reference scripts.
- The CLI default inactivity timeout is 600000 ms.
- The pool TTL must exceed the longest command.
- The guard must heartbeat during long commands.
- The pool should set the session timeout on `start` or read it from the command.

The pool must drain, not preempt.
Killing a live session to free a worker loses browser state.
Reject new leases first.
Let active sessions finish.
Reap only after the command, the lease TTL, or the session timeout.

## 4. The control plane

The control plane needs these parts:

- A worker registry.
- A lease table.
- A wait queue.
- A health checker.
- A reaper.
- A reconciler.
- An optional Docker lifecycle manager.
- Metrics and structured logs.
- An authenticated, fixed-function API.

The hard problem is release certainty.
The API session record has no name.
The probe of `GET /v1/sessions` showed only `id`, `status`, timestamps, URLs, and browser fields.
There is no `name` field.
The CLI name exists only in the Kali daemon.

The guard can report the session id from the `start` output.
The pool can then check `GET /v1/sessions/<id>` and require `status == "live"`.
If the report is lost, the pool sees a live session with no lease.
It must quarantine the worker, release the session, and free the worker after a grace period.
That loses the agent's session.
The alternative is a durable mapping from session id to lease.
The guard must write that mapping before it returns the start result.

The create is a two-phase operation:

1. Acquire the lease.
2. Create the session.

The create can fail.
The response can be lost.
The session can exist without a reported id.
There is no transaction across the lease table and the Steel API.
The reconciler is therefore mandatory.
A lease table alone will drift.

The reconciler must:

- Poll every worker's `GET /v1/sessions`.
- Filter `status == "live"`.
- Compare the live id with the lease's reported id.
- Adopt a matching session.
- Quarantine an unknown live session.
- Release an orphan after the grace period.
- Free a worker only after the session is gone.

The API list includes past sessions.
A naive `len(sessions) == 0` check is wrong.
Use the `status` field.

The pool service needs a single writer.
Two services can assign the same worker.
Use one central service, or partition workers statically per instance.
Do not run one allocator per Kali against a shared worker list.

Where the service runs matters:

- The Steel host has Docker access and the workers.
- The eval host has the Kali containers and the agent.
- The Steel API is at `192.33.91.87`.
- The eval server is at `46.224.225.245`.
- The eval host has 15 GB RAM and 10 GB free.
- The Steel host resources are unknown from this worktree.

A service on the Steel host avoids giving Docker access to the eval host.
The Kali containers reach it over the network.
The service must restrict its API to lease operations.
It must not expose a generic Docker proxy.

Lazy container creation is a separate decision.
Cold start includes image pull, API boot, and Chrome launch.
The first browser request may exceed the tool timeout.
Pre-create the containers at stack `up`.
Treat "lazy" as lazy lease assignment, not lazy container creation.

A stable endpoint is also a separate decision.
Injecting `--api-url` per `start` is simple and matches the daemon.
A session-aware reverse proxy is a larger product.
It must route by session id, rewrite viewer and connect URLs, and handle WebSockets.
Do not build it unless a single endpoint is a hard requirement.

## 5. Capacity

The running eval instance sets `MAX_PODS=5`.
The code default is 20 at `src/polymerhus/recon/config.py:9`.
`.env.example` sets 8.
The roles with the `steel-browser` skill are `pod_runner` and `hunting_hunter`.
See `src/polymerhus/app/llm/skills.py:712-713`.
The crawler uses the SDK path, not the CLI.

The worst case is therefore at least 6 concurrent CLI browser users:

- 5 pod runners.
- 1 hunting hunter.
- Plus the SDK crawler.

A default pool of 4 cannot guarantee capacity for all of them.
The claim "even if all agents use a browser at the same time" is false at 4.
A pool of 6 covers the CLI worst case for this instance.
The SDK crawler needs its own capacity or a shared lease.

Browser use is bursty.
The pool does not need to cover the worst case if the queue is acceptable.
That is a product decision, not an assumption.
Measure the concurrent live sessions per trial before choosing a size.

Resource sizing is also unresolved:

- The Steel docs ask for 4 GB RAM and 10 GB disk per instance.
- The pool fork estimates 100-300 MB per Chromium plus about 200 MB for the API.
- The truth depends on the page and the target.
- Measure a worker under a real target page.
- Check the Steel host, not the eval host, for capacity.

The pool size should be a deployment value.
`STEEL_POOL_SIZE` belongs on the pool service.
The Kali needs only the pool URL.
A safe starting point is `min(host_capacity, MAX_PODS + 1)`.
For the running instance that is 6, not 4.
If the SDK crawler shares the pool, add its concurrency.

Disk also matters.
Each worker writes Chrome profiles, logs, and exports.
Shared image layers reduce the image cost.
The writable layers and logs do not.

## 6. Failure modes

| Failure | Effect | Detection | Mitigation |
| --- | --- | --- | --- |
| Pool service down | New sessions fail | Lease API error | Fail closed with `pool_unavailable`; existing daemons keep working |
| Agent crashes after `start` | Worker stuck | Lease TTL; no command heartbeat | Reap after TTL; release the session |
| Guard crashes after acquire | Lease without session | Worker has no live session | Grace period, then free |
| Guard crashes after create | Live session without lease | Worker has unknown live id | Quarantine, report, release after grace |
| False reap | Session killed mid-work | Agent error; auth probe fails | Require two observations; drain, do not preempt |
| Worker restart | Daemon loses CDP | Daemon log; CLI error | Recreate session; restore account state |
| Stale daemon | CLI points at dead worker | `sessions` reports unknown | Remove daemon; start again |
| Double assignment | Session replaced | Two leases on one worker | Single writer; compare session ids; fence |
| Name collision | Two sessions share a name | Guard registry or logs | Require unique names; owner check |
| Queue leak | Worker assigned to dead caller | Lease has no heartbeat | Cancel on disconnect; TTL |
| SDK bypass | Crawler collides with CLI | Two live sessions on one worker | Integrate the SDK path |
| Env fallback bypass | Command hits a leased worker | Session replaced or 404 | Guard owns all routes; no fallback to pooled workers |
| `stop --all` | Leases leak | Worker has no live session | Release all leases for the owner |
| `start` replacement | Old session replaced | Same name, new id | Idempotent acquire; same worker |
| Cold start timeout | Tool call fails | Acquire exceeds timeout | Pre-warm; bounded wait |
| Port or `DOMAIN` mismatch | Viewer and CDP URLs wrong | Connect or viewer failure | Template `DOMAIN` and `CDP_DOMAIN` per worker |
| Worker unhealthy | Commands fail | Health check; CDP errors | Quarantine; do not reassign until reaped |
| Logs scattered | Slow diagnosis | Missing worker id in trace | Add worker id and lease id to the guard trace |

## 7. Eval validity

A pool shared across trials changes the experiment.
Two trials can compete for the same workers.
A missed browser action can look like a missed finding.
The eval must record pool state per trial:

- Acquires.
- Waits.
- `pool_exhausted` errors.
- Reaps.
- Worker ids.

The assessor and diagnoser must treat pool exhaustion as infrastructure.
They must not score it as a target miss.
The `trial.yaml` evidence should carry the pool metrics.
The `eval_monitor` assessment prompt may need a rule for this.

Drain the pool between targets.
The `next_target` step changes the target host.
Old sessions are useless and hold capacity.
The eval orchestrator should call the pool drain before the next target.

A per-instance pool preserves trial isolation.
A shared pool couples trials and weakens the benchmark.
Use a shared pool only when the utilization gain is measured and acceptable.

## 8. Security

The local Steel API has no authentication.
A worker URL is a full browser control handle.
A shared pool network makes every worker reachable from every Kali.
The pool API must not reveal other workers' URLs.
The worker network must be private.
Do not publish the CDP port.

The pool service needs Docker access if it creates workers.
That is a high-value target.
The service must expose only fixed-function lease operations.
It must not accept an image, command, mount, or network from the caller.
Use fixed templates and a fixed size cap.
Run it on the Steel host, not in the agent container.

The pool token is readable by the agent.
The agent runs shell commands inside Kali.
The token is a capability, not a secret from the agent.
Limit what the token can do.
Prefer a socket or network policy over a broad token.

The worker API is keyless.
Isolate the pool network.
Do not expose workers to the eval host or the public network.
The viewer URL is for operators, not agents.

The guard trace should record the worker id and lease id.
It must not record API keys or cookies.
The existing `steel_events` trace is a good place.

## 9. Code and config impact

| Area | File | Change | Risk |
| --- | --- | --- | --- |
| Wrapper | `kali/steel_wrapper.sh` | Keep local mode and UA; optionally call a pool helper | Bash JSON is fragile; prefer the guard |
| Guard | `kali/steel_guard.py` | Acquire, inject, heartbeat, release, strip `--api-url` | Central change; test every verb |
| Contract | `kali/steel_contract.py` | Accept or strip `--api-url`; add pool error codes | Sanitizer and classifier must agree |
| MCP | `kali/mcp_server.py` | Pass owner env; account for pool wait in `timeout_s`; extend the envelope | Long waits can stall the tool |
| Skill | `skills/internal/tools/steel-browser/*` | Teach pool errors, naming, stop discipline, no retry storm | Agents may loop on `pool_exhausted` |
| Endpoint | `src/polymerhus/app/steel_endpoint.py` | One endpoint becomes allocator plus endpoint | Breaks D359-4 and CONTEXT |
| SDK crawl | `src/polymerhus/recon/crawl/steel_provider.py` | Acquire and release per crawl | Second client path; sync and async |
| SDK client | `src/polymerhus/recon/crawl/steel_client.py` | Pass the pool client | Contract change |
| State | `src/polymerhus/app/steel_session_state.py` | Restore only; no live migration | Do not imply session migration |
| Pipeline | `src/polymerhus/recon/control/pipeline.py` | Distinguish pool errors from auth failures | Fail-closed logic must not misclassify |
| Auth loop | `src/polymerhus/recon/control/authn_loop.py` | Same distinction | The oracle must stop only on real auth failure |
| Eval compose | `eval/docker-compose.eval.yml` | Add the pool service, network, and env | New required variables |
| Eval preflight | `eval/env_preflight.py` | Validate pool settings | Missing values must fail loud |
| Eval chain | `eval/orchestrator` | Drain between targets; record metrics | Cross-target lifecycle |
| Eval prompts | `eval/prompts/assessment.md` | Treat pool errors as infrastructure | Measurement validity |
| Tests | `tests/test_steel_wrapper.py`, `tests/test_steel_exec.py` | Exact argv changes; acquire and release cases | Broad test churn |

The "one deployment-level endpoint" invariant is the biggest design change.
`src/polymerhus/app/steel_endpoint.py` says the value is the one construction point.
The CONTEXT map repeats it.
A pool makes the endpoint a per-session value.
The abstraction must become "allocator plus endpoint".
That is a design decision, not a config tweak.

## 10. Operations

The pool adds a new service to deploy and monitor.
It needs:

- A health endpoint.
- A lease table view.
- Queue depth.
- Acquire and release latency.
- Reap counts.
- Worker health.
- Error rates by code.
- A restart procedure.

The restart procedure must not double-assign.
Either persist the lease table or drain all workers on restart.
Draining all workers is simpler and safer for the eval.
It kills live sessions, so document the impact.

The rollback is a feature flag.
With `STEEL_POOL_URL` unset, the guard uses the current single endpoint.
Test both modes.
Keep the single-endpoint path as the baseline.

The pinned CLI is a maintenance risk.
The repo pins `0.5.0-preview.6`.
The CLI `main` branch renamed the endpoint variable to `STEEL_API_URL`.
It warns about `STEEL_BROWSER_API_URL`.
The pool's `--api-url` injection is version-agnostic.
The env fallback and the daemon behavior are not.
Test the pool against the pinned binary before any CLI upgrade.

## 11. Alternatives

| Option | Isolation | Concurrency | New service | CLI fit | Eval isolation | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Single worker per instance | Full | 1 | None | Native | Full | Baseline |
| Per-instance static pool plus guard allocator | Full | N | Small | Native | Full | Recommended first step |
| Central shared pool | Full | N across instances | Large | Native | Weak | Later, after measurement |
| Browser-pool fork | Full | N | None | Unproven | Full | Pilot only |
| Tabs | None | Page level | None | Native | Full | Page only |
| Steel Cloud | Full | 10+ | None | Native | Full | Managed fallback |

The browser-pool fork is PR #264 and PR #416.
Both are unmerged.
PR #416 was closed after five minutes.
Neither is a supported product.
The CLI compatibility with a session-scoped `connectUrl` is unproven.
Do not make it the first step.

## 12. Recommendation

Build a per-instance static pool first.

- Pre-create the workers at stack `up`.
- Use a fixed list of worker URLs.
- Put the allocator in the guard.
- Use a per-session lease.
- Size the pool at `min(host_capacity, MAX_PODS + 1)`.
- Integrate the SDK crawl path.
- Drain between targets.
- Record pool metrics in the trial.
- Keep the single-endpoint mode as a rollback.

Do not build a central shared pool until the per-instance pool is measured.
Do not build a per-agent lease.
Do not make a request wait without a bound.
Do not treat the session as a platform object.

## 13. Proofs required before build

1. Measure concurrent live sessions per trial.
2. Measure the browser duty cycle per role.
3. Measure worker RAM, CPU, and disk under a real target page.
4. Measure cold start and warm start against the tool timeout.
5. Prove `--api-url` injection with the pinned CLI and the guard.
6. Prove the daemon pins the worker and ignores a wrong `--api-url`.
7. Prove `stop`, `stop --all`, `start` replacement, and daemon crash release.
8. Prove the SDK crawl path acquires and releases a worker.
9. Prove the reaper handles an unknown live session with no name.
10. Prove the queue cancels on client disconnect and does not leak.
11. Prove a pool service restart does not double-assign.
12. Prove the eval records pool contention and the assessor treats it as infrastructure.
13. Prove the pool API cannot create arbitrary containers or reach the Docker socket from Kali.

## 14. Open questions

- How many browser users run at the same time in a real trial?
- What is the p95 browser duty cycle per pod?
- What is the worker memory under the heaviest target?
- How long does a cold worker take to serve its first session?
- Is a single Steel endpoint a hard requirement?
- Can the eval tolerate cross-trial pool contention?
- What are the Steel host resources?
- Can the CLI be upgraded without breaking the wrapper and the daemon contract?
- Should the SDK crawler share the pool or get a dedicated worker?
- Who owns a shared session: the project, the trial, or the agent?
