# The steel_crawl to pool MCP conjunction

Date: 2026-11-05.
Status: historical analysis. The decision and the implementation record are
`docs/design/steel-crawl-pool-convergence.md`; this note states the problem,
not the current contract.
Scope: the `feat/steel-crawl` crawler and the `feat/steel-crawl-pool` browser pool MCP.

This note states the discrepancy, not a solution.
The crawler and the pool MCP are different executors with different lifetime,
transport, state, and capture contracts.
A small conflict resolution cannot bridge them.
The decision must choose which process owns the browser, which store is
authoritative, and where the CDP capture runs.

## 1. Three executors exist today

| Executor | Code | Who calls it | Session owner | Transport | Agent tools |
|---|---|---|---|---|---|
| Deterministic crawl engine | `recon/crawl/steel/*` | the crawl pod (`crawl_pod.live_run_crawl_fn`) | the engine, by name, attached to a pre-authenticated session | `steel` CLI subprocess in the pod's environment | none; it is a pod collaborator |
| Retired agentic crawl | `recon/crawl/steel_provider.py`, `crawl_agent.py` | `legacy_agentic_run_crawl_fn` only | the provider, by SDK create | Steel Python SDK plus Playwright over CDP | six `steel_*` tools |
| Browser pool MCP | `kali/steel_pool/server.py` | the hunting agent and the W8 binding | the MCP lease, keyed by MCP session id | MCP streamable HTTP, three tools | `browser_start`, `browser_exec`, `browser_end` |

The production crawl is the deterministic engine (`crawl_pod.py` sets
`default_run_crawl_fn = live_run_crawl_fn`).
The agentic provider is a controlled fallback, not the production path.
The pool MCP is the new browser executor for the agent.

The three do not share one session, one state store, or one capture plane.

## 2. Layer-by-layer discrepancy

### 2.1 Process and topology

The deterministic engine runs in the crawl pod, which runs in the agent
container.
It shells out to the `steel` CLI from `STEEL_CRAWL_CLI` or from `PATH`.
It attaches to a browser session on the runtime named by
`STEEL_BROWSER_API_URL`.
Its CDP sidecar runs in the same pod and connects to the session's
`websocket_url`.
Its HTTP-history client posts normalized flows to
`KALI_HTTP_HISTORY_EDGE_URL`, which is a Kali process.

The pool MCP runs in Kali.
The browser runs on a worker on the pool host.
The CLI runs inside the MCP server, not in the agent.
Kali reaches the worker through the operator's forward and the loopback relay.
The agent never sees the worker URL, the worker port, or the CDP websocket.

The agent container has no route to the loopback-only pool workers.
The agent cannot run the deterministic engine's CLI path against the pool
directly.
The MCP is the only agent path to the pool browser.

The target also reaches the browser from the worker, not from the agent.
The worker needs the synthetic-host alias and the pool-host forward.
The agent's `/etc/hosts` alias is irrelevant to the browser's DNS resolution.
The current live target chain is:

```
worker Chrome -> 172.21.0.1:80 (pool host relay)
              -> 127.0.0.1:18080 (eval-host reverse tunnel)
              -> eval front :80 (Host t-<id>.target)
              -> target host port
```

The crawler's `target_url` is the same synthetic host.
The worker resolves it through the worker alias.
This part works and is verified for White Jotter and ComfyUI.

### 2.2 Agent tool surface

The agentic provider exposes six high-level tools:
`steel_crawl_start`, `steel_navigate`, `steel_frontier`, `steel_eval`,
`steel_click`, and `steel_crawl_finish`.
They carry a crawl id, a frontier, a network delta, and a manifest.
They are a crawl API, not a browser command API.

The pool MCP exposes three low-level tools:
`browser_start(name, url=None)`, `browser_exec(command)`, and
`browser_end()`.
They carry a durable session name and one browser command.
They do not carry a frontier, a crawl id, or a manifest.

The hunting agent already binds the three MCP tools through
`attack/hunting/browser_tools.py`.
The crawl pod does not use that binding.
The crawl pod builds its own tools from `steel_client.get_crawl_tools`.

The tool surfaces cannot be merged by name.
The six tools create and release their own sessions.
The three tools mount and end a lease.
An agent cannot mount a pool session and then call the six SDK tools on it.

### 2.3 Session identity and lifecycle

The deterministic client treats a session as a live, named CLI session.
`SteelSessionClient.catalogue()` runs `steel browser sessions --json`.
`SteelSessionClient.attach(name)` runs the catalogue, then
`steel browser sessions --session <name> --json`, and optionally
`GET /v1/sessions/<id>` through `api_fn`.
It stores the runtime id and, when the API read succeeds, the CDP
`websocketUrl`.
`SteelSessionClient.stop()` runs `steel browser stop --session <name> --json`
and then proves the name is gone from the catalogue.
The client never starts a session; it requires a live session created by the
auth gateway or by the operator.

The pool MCP treats a session as a durable name plus a lease.
`browser_start(name)` creates a new CLI session on a leased worker.
It restores cookies and localStorage from `/var/lib/steel/sessions/<name>.json`
when that record exists.
It returns `{name, session_id}` and never a full record.
`browser_end()` captures, saves, stops, releases, and settles.
The MCP session id is the lease key.
A name mounted by another MCP session answers `session_in_use`.
A name not mounted answers `no_session` on `browser_exec`.

The crawler's live attach and the MCP's lease are mutually exclusive.
A name held by the auth gateway's MCP session is `session_in_use` to the
crawler's MCP session, even when the HTTP name is the same.
There is no catalogue, no attach, and no runtime-id lookup in the MCP.
The only cross-session handoff the MCP supports is:
the first client calls `browser_end`, the pool store saves the state, and a
later client calls `browser_start` with the same name.
That handoff creates a new runtime id and a new browser context.
It does not preserve the live JavaScript, the open pages, or sessionStorage
and indexedDB as restored state.

### 2.4 Lease, ownership, and release

The deterministic engine's stop owner is the crawl job.
`job._close` calls `session.stop` when `stop_session` is true.
The auth gateway owns the session before the crawl job.
The current contract assumes the gateway leaves the session live and the job
attaches and later stops it.

The MCP lease owner is the MCP session.
The heartbeat keeps the lease alive while the MCP client is connected.
Every `browser_exec` resets the TTL.
The MCP close hook, the `browser_end`, the server shutdown, and the TTL all
release the lease.
A CLI daemon death and a CDP sidecar death do not release it.

The crawler's stop owner and the MCP's lease owner are different objects.
A crawler that opens its own MCP session can hold the lease.
A crawler that runs in a separate process from the auth gateway cannot share
the gateway's lease.
The pool manager's one-live-session-per-worker rule makes a second session on
the same worker impossible while the gateway holds it.

### 2.5 Command grammar

The deterministic client builds:

```
[*prefix, verb, "--session", <name>, "--json", *args]
```

The prefix is `("steel", "browser")` or `(<STEEL_CRAWL_CLI>, "browser")`.
The `--session` and `--json` options sit before the positional and before a
variadic verb's mandatory `--` boundary.
The client deliberately refuses `start`.
The `stop` verb is built by the dedicated `stop()` method.

The MCP `parse_browser_command` accepts the bare browser grammar.
It refuses `start`, `stop`, `sessions`, `live`, and `scrape`.
It refuses `--session`, `--api-url`, `--local`, and `-l`.
It strips `--json`.
The MCP's `SteelCli._with_session` inserts `--session` and `--json` itself,
before a variadic `--` boundary.
The `SteelCli._command` also inserts `--api-url` and `--local`.

Every command the deterministic client builds carries two flags the MCP
refuses.
A crawler adapter must send the bare verb and its arguments, not the
session-bound argv.
That change is mechanical in `command()` and `batch` elements.
It is not mechanical in `attach`, `stop`, and the catalogue.

### 2.6 Return envelope and evidence

The deterministic client's `_subprocess_exec` adds three process facts to the
CLI's JSON:
`returncode`, `stderr`, and `duration_ms`.
The guard's trace adds `steel_events`.
`SteelResult` carries `output`, `success`, `error`, `warning`,
`steel_events`, `exit_code`, `stderr`, `duration_ms`, and `read_back`.

The MCP `browser_exec` returns the CLI's own envelope for a command-level
success or failure.
It returns a typed MCP error envelope for a refusal, a missing lease, a pool
exhaustion, a capture failure, or an internal error.
The MCP does not add the CLI process's `returncode`, `stderr`, or
`duration_ms`.
The MCP does not return the guard's `steel_events`, because `SteelCli._run`
does not read the guard trace.
The crawler's `SteelResult` would see `None` for those fields.
The ledger evidence would be weaker unless the adapter maps or the MCP adds
them.

### 2.7 Error taxonomy and retry

The deterministic client's typed errors are:
`unknown_session`, `session_missing`, `session_taken`, `target_lost`,
`browser_stuck`, `invalid_command`, `command_failed`, and `guard_error`.
`job.run_with_session_retry` retries one `session_missing` and then stops.

The MCP's typed errors are:
`pool_exhausted`, `session_in_use`, `no_session`, `invalid_command`,
`invalid_argument`, `browser_error`, `capture_failed`, `restore_failed`,
`store_error`, `pool_unavailable`, `lease_error`, and `internal_error`.

The maps do not overlap by name.
A `session_in_use` is not a `session_taken` retry.
A `no_session` is not a `session_missing` retry.
A `pool_exhausted` is a retryable pool wait, not a browser fault.
The crawler's `_stop_reason` and the pod's reduced-coverage path must learn
the MCP codes.

### 2.8 Durable state and auth handoff

The auth store records an account and a `steel.state` reference.
`app/steel_session_state.py` is the one capture and restore seam:
`capture_session_context` reads `GET /v1/sessions/<id>/context`.
`save_session_context` writes the four fields atomically and owner-only.
`restore_session` feeds them back through the SDK create call's
`sessionContext`.

The deterministic engine does not use that seam.
It attaches to an already-authenticated live session and never captures or
restores browser state.
The `steel_state` and `browser_auth` values reach `crawl_pod` but the
production `live_run_crawl_fn` uses only `auth_probe`, `login_url`, and
`account`.
The state file is a provider-era artifact.

The pool MCP uses a different store:
`/var/lib/steel/sessions/<name>.json`.
It captures cookies, localStorage, sessionStorage, and indexedDB as evidence.
It restores cookies and localStorage only, and the restore is lossy for cookie
expiry, SameSite, priority, and source metadata.
It is not the auth store's `steel.state`.
The two stores have different keys, formats, and writers.

The auth oracle is the one shared idea.
`steel/auth.py::session_fetch_fn` runs one `eval` fetch through the session
client.
The MCP can run the same `eval` through `browser_exec`.
The oracle itself is portable.
The state around it is not.

### 2.9 CDP capture and HTTP history

`run_live_crawl` reads the CDP websocket from the attached session's
`websocketUrl`.
It opens `LiveCdpTransport(websocket)` and `CaptureSidecar(transport)` in the
crawl pod.
The sidecar subscribes to network and page events, normalizes flows, and the
history client posts them to the Kali HTTP-history edge.
The engine's page status and network evidence depend on this sidecar.

The MCP returns no websocket.
`browser_start` returns only the name and the runtime session id.
The MCP server could read the worker's `GET /v1/sessions/<id>` because it has
the worker API client, but that record contains the worker origin.
Exposing it to the agent would break the "agent never sees the worker address"
rule.
The agent also has no route to the worker websocket.
The sidecar cannot run in the agent against a pool worker without a second
relay and a second Host-preserving proxy.

The HTTP-history edge is in Kali, but the sidecar is in the pod.
The edge is a sink, not a proxy.
The worker's traffic never passes through Kali.
The pool path therefore has no network capture unless one of these is added:
a server-side capture in the MCP, a privileged websocket endpoint, or a
capture sidecar on the pool host.

### 2.10 Configuration

The deterministic engine reads `STEEL_BROWSER_API_URL` and
`STEEL_CRAWL_CLI`.
The agentic provider reads `STEEL_API_KEY` and `STEEL_BROWSER_API_URL`.
The pool MCP reads `KALI_BROWSER_MCP_URL` on the agent side and
`STEEL_POOL_*`, `STEEL_CLI`, and `STEEL_GUARD` on the Kali side.
The workers read `DOMAIN` and `CDP_DOMAIN`.

The live eval instance still carries:
`STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1`, the retired public API.
It also carries a live `STEEL_API_KEY`.
The pool needs neither.
The agentic provider would use both and bypass the pool.
The deterministic engine would use the public endpoint and fail, because that
endpoint is retired and the workers are loopback-only.
The `KALI_BROWSER_MCP_URL` value is the only agent-side value the pool path
needs.

The worker `DOMAIN` has a hard constraint.
The Steel API builds its `websocketUrl` from `DOMAIN`.
The API's CDP proxy forwards the client's `Host` header to Chrome.
Chrome answers 500 to a non-localhost `Host`.
A client that connects through a host alias must therefore preserve
`Host: localhost:<port>`.
The live eval solved this with a loopback relay in Kali:
the worker keeps `DOMAIN=localhost:<port>`, the relay listens on both loopback
families, and the upstream is the eval host's forward.
A direct `DOMAIN=host.docker.internal` was tried and failed with a 500.
This is a constraint on any crawler that connects to the worker CDP directly.

### 2.11 Concurrency, TTL, and heartbeat

The deterministic engine runs one crawl job per session name.
The pool MCP runs one lease per MCP session and one live session per worker.
The pool size is the worker count.
A crawl that holds an MCP session holds one worker for its whole run.
The MCP heartbeat is 120 s and the lease TTL is 600 s.
Every `browser_exec` resets the TTL.
A long `snapshot`, `wait`, or `eval` is a live command, so the TTL stays
alive.
The crawl job's own budget is 900 s by default, longer than the TTL, so the
MCP session must stay open and the commands must keep flowing.

The auth gateway and the crawl job run in different phases.
If both open MCP sessions, they compete for the pool.
If the gateway holds a lease while the crawler starts, the crawler gets
`session_in_use` or `pool_exhausted`.
The pool wait is 30 s; the crawl job may need to wait longer.

### 2.12 Observability

The deterministic engine writes a run ledger, a manifest, and a summary.
The ledger carries each action and the CLI envelope.
The sidecar carries the network flows.
The MCP writes one JSON store record per name and structured events:
`pool.discovered`, `lease.mounted`, `lease.released`, and `session.close`.
The MCP does not write the crawler's ledger.
The crawler does not read the MCP's store.
A converged path must decide which record is the run evidence and which
record is the browser state.

## 3. Exact call sites that must change

| Symbol or file | Current assumption | Conflict with the pool MCP |
|---|---|---|
| `steel/session.py::SteelSessionClient.catalogue` | `sessions --json` is available | the MCP has no catalogue tool |
| `steel/session.py::SteelSessionClient.attach` | the name is live and attachable | the name is a lease; another MCP session gets `session_in_use` |
| `steel/session.py::SteelSessionClient.command` | `--session` and `--json` are part of the argv | the MCP refuses both and inserts them itself |
| `steel/session.py::SteelSessionClient.execute` | one CLI subprocess per command | one MCP tool call per command |
| `steel/session.py::SteelSessionClient.stop` | `browser stop` plus a catalogue proof | `stop` is refused; `browser_end` owns it |
| `steel/session.py::SteelSessionRegistry` | observes the catalogue | the MCP owns the lease; the registry has no source |
| `steel/command.py::CommandMapper.commands` | returns session-bound argv | must return bare argv |
| `steel/command.py::SteelResult` | CLI process facts and guard events | the MCP drops most of them |
| `steel/auth.py::session_fetch_fn` | `client.execute("eval", ...)` | portable through `browser_exec`, but needs the adapter |
| `steel/job.py::run` | `session.attach` then `sidecar.attach` | `browser_start` then a capture decision |
| `steel/job.py::_close` | `sidecar.close` then `session.stop` | `browser_end` owns the stop and the state |
| `steel/live.py::run_live_crawl` | `api_session_record` gives the websocket | the MCP does not expose the record or the websocket |
| `steel/live.py::LiveCdpTransport` | the pod can reach the worker websocket | the agent cannot reach the loopback worker |
| `steel/capture/sidecar.py` | one raw CDP page target | no websocket, no agent route |
| `steel/capture/history.py` | posts flows to the Kali edge | the pool browser traffic never reaches Kali |
| `steel_provider.py::SteelCrawlProvider` | SDK create plus Playwright | bypasses the pool lease and the MCP |
| `steel_client.py::get_crawl_tools` | six high-level tools | not the three-tool agent surface |
| `crawl_agent.py::run_crawl` | the six-tool ReAct loop | the new agent has the three-tool loop |
| `crawl_pod.py::live_run_crawl_fn` | `STEEL_CRAWL_CLI` and a live session name | the agent has no CLI and no live lease |
| `crawl_pod.py` | passes `steel_state` and `browser_auth` | the production engine ignores the state file |
| `app/steel_session_state.py` | capture and restore `steel.state` | the pool store is separate |
| `app/steel_endpoint.py` | `STEEL_BROWSER_API_URL` names the runtime | the pool worker is not agent-addressable |
| `eval/steel-crawl-e2e/scaffold.py` | copies the CLI into the agent | the agent must not install the CLI |

## 4. Hard constraints

1. One MCP session is one lease.
   There is no attach and no lease transfer.
2. The MCP hides the worker origin.
   It returns no runtime record and no CDP websocket.
3. The MCP refuses the CLI lifecycle verbs and the session and runtime flags.
4. The pool workers are loopback-only on the pool host.
   The agent has no route to them.
5. The worker API builds the websocket URL from `DOMAIN` and forwards the
   client `Host` to Chrome.
   A non-localhost `Host` is a 500.
6. The MCP store and the auth store are separate.
   The MCP restores cookies and localStorage only.
7. The MCP has no network capture.
   The HTTP-history edge is in Kali and the sidecar is in the pod.
8. The auth gateway and the crawl pod are separate phases.
   They cannot share an MCP session unless they share a process.

## 5. Decision points

D1. Where does the crawl executor run?
    In the agent's MCP client, in a Kali-side crawl service, in the MCP server
    itself, or in a local-only fallback?

D2. How does the pre-authenticated session reach the crawler?
    The same MCP session as the gateway, an end-then-start by name through the
    pool store, or a new transfer tool?

D3. Which store is authoritative?
    The pool store only, the auth store's `steel.state` only, or a bridge that
    reads and writes both?

D4. Where does CDP capture run?
    A privileged websocket endpoint, a sidecar in Kali, a server-side capture,
    or no network capture on the pool path?

D5. Does the six-tool `steel_*` surface survive?
    As a wrapper over the three MCP tools, as a server-side crawl engine, or
    not at all?

D6. Is the SDK and Playwright provider retired for the pool?
    Keep it local-only, delete it, or keep it as a fallback?

D7. What is the concurrency unit?
    One crawl per MCP session and worker, one crawl per pool lease, or a
    multiplexed session?

D8. What is the evidence contract?
    Map the MCP errors into the crawler's `SteelResult` and `stop_reason`, and
    decide whether the lost `steel_events` and process facts matter.

D9. Which E2E target path is the gate?
    The pool path for `steel_crawl`, or a local CLI worker?

## 6. Convergence options

### Option A: MCP-native crawler

Replace `SteelSessionClient` with an `McpSessionClient`:
`browser_start(name)` replaces `attach`.
`browser_exec(bare_command)` replaces `execute`.
`browser_end()` replaces `stop`.
The crawler owns one MCP session per crawl job.
The auth gateway either runs in the same MCP session or ends before the
crawler starts.
The crawler uses the pool store for state.
The CDP sidecar is dropped, or it is replaced by a new capture tool.

This is the smallest conceptual change to the crawler's command path.
It loses the live attach, the runtime id, the catalogue, the CDP websocket,
and the network history.
It makes the pool the only executor.

### Option B: Kali-side crawl bridge

Run a long-lived bridge in Kali.
The bridge holds one MCP session.
It exposes a small local API to the crawler:
`attach(name)`, `exec(command)`, `stop()`, and `record()`.
The bridge can run the auth gateway and the crawler in one MCP session.
The sidecar runs in Kali next to the bridge.
The bridge reads the worker's runtime record through its own API client and
feeds the sidecar, without exposing the worker to the agent.
The crawler becomes a thin HTTP client.

This is the smallest change to the crawler's internals.
It preserves the CDP capture and the HTTP history.
It adds a new service and a new trust boundary.
It still needs a decision on the state store.

### Option C: Server-side crawl engine

Move the deterministic engine into the browser MCP server or a sibling
service.
The engine owns the lease, the CLI, the CDP sidecar, the HTTP history, and the
state.
The agent calls one high-level crawl tool.
The auth gateway passes the account or the durable name to the engine.
The engine returns the manifest.

This is the clean end state for isolation and for the one-browser-path rule.
It is a large move of the crawl engine.
It removes the agent-side CLI and the agent-side CDP route.
It keeps the network capture next to the browser.

### Option D: Local-only crawler

Keep the deterministic engine on a local worker in Kali, with the CLI and the
sidecar.
Use the pool MCP only for the agent's browser tools.
Run the `steel_crawl` E2E against the local worker.

This is the least work.
It leaves two browser paths.
It does not make the pool the crawler's executor.

## 7. What is already verified

The pool MCP path is verified live on the eval server:
two workers, boot discovery 2/2 healthy, three tools only, a full
start-navigate-read-end on `http://t-1618c524.target/`, a `0600` store record,
and both workers settled.
The target chain is verified for White Jotter and ComfyUI from both workers.
The target fronts and the double forward are in place.
The guard is the public `steel` entrypoint and the wrapper is removed.
The worker domain stays `localhost:<port>` and the Kali relay preserves the
host contract.

The crawler is not converged.
No crawler code is changed on this branch.
The decision above is the gate.
