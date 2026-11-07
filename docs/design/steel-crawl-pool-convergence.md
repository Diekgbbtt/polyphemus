> 2026-11-07: section 12 supersedes the session-key and `steel.state`
> details in sections 3-5 and 10. The durable object is the decoupled auth
> context; the session key is ephemeral and derived by the binding.

# Steel crawl pool convergence: final decisions

Status: design closed, 2026-11-07.
Branch: `feat/steel-crawl-convergence`, based on `feat/steel-crawl-pool`.
Base engine: `feat/steel-crawl` at `4c245af5`.
The JEV engine is unchanged.

## 1. Topology

- The browser pool belongs to the polymerhus instance compose project.
  Every instance has its own workers, browser MCP, and store.
- One Compose service, `steel-worker`, carries the worker definition.
  It lives in `docker-compose.pool.yml`; the baseline includes that file.
  Compose replication provides the pool size.
- The baseline count is `deploy.replicas: 2`.
  Thin mode omits `docker-compose.pool.yml`, sets
  `STEEL_POOL_DOCKER_SOCKET=""`, and sets `KALI_BROWSER_MCP_URL=""`.
  A `deploy.replicas: 0` override is not enough: Compose still plans the
  worker image pull for a declared service, so a thin host without the image
  would fail to start.
- The workers are normal containers on `polymerhus-net`.
  There are no worker sidecars and no shared network namespaces.
- The browser MCP runs in Kali.
  It starts one reverse proxy per worker on `127.0.0.1:3100+i`.
- The worker keeps `DOMAIN=localhost:3000` and `CDP_DOMAIN=localhost:3000` inside its own container.
- No SSH agent, no Docker socket tunnel, no worker-port forward, and no target reverse tunnel.
- The eval orchestrator writes the synthetic target host into each worker's `/etc/hosts`.
  It uses the same exact-field rewrite as the Kali alias.

## 2. Scale

- `deploy.replicas` is the declarative count.
  `docker compose up -d` applies it.
- `--scale` is not the runtime mechanism.
  The count is a bootstrap setting.
  Runtime configuration is deferred.
- The pool manager discovers the actual replicas.
  The discovered count is the truth.
- Thin mode removes the worker service (by omitting the pool file) and the
  agent's browser URL.

## 3. Host contract

- The CLI runs in Kali and uses `--api-url http://localhost:3100+i/v1`.
  It sends `Host: localhost:3100+i`.
- The MCP reverse proxy forwards the HTTP traffic to the worker's container IP on port 3000.
  It rewrites the session create response's `websocketUrl` to `ws://localhost:3100+i/`.
  It proxies the WebSocket upgrade with the same Host.
- The worker's CDP proxy sees a localhost Host.
  Chrome accepts it.
- The agent's CDP capture connects its socket to the worker's container IP on port 3000.
  It uses `ws://localhost:3000/` as the URI, so the Host header is `localhost:3000`.
  The `websockets` `sock` parameter separates the connect address from the URI host.
- The raw Chrome debug port stays inside the worker container.
- `browser_start` returns `cdp_url=ws://<container-ip>:3000/` and `cdp_host=localhost:3000`.
  The agent-facing `browser` tool never returns either field.

## 4. Session state

- The durable auth context is `steel-auth-<project_slug>-<account_slug>`.
  The session key is ephemeral and derived from the execution unit.
  The run id stays in the lease, the ledger, and the manifest.
- The gateway mounts the decoupled auth context, checks the authenticated-context oracle, re-authenticates if needed, and saves the same context.
- A failed save overwrites the same key.
  The next gateway turn detects the non-authenticated state and re-authenticates.
  There is no versioned store and no pointer commit.
- `accounts.<account>.browser_context.ref` holds the context reference.
- `browser_auth` carries only `auth_probe` and `login_url` to the crawl.
  Cookies and localStorage live in the pool store.

## 5. Lifecycle and stop

- The crawl mounts the decoupled auth context with an ephemeral session key and no URL.
  The sidecar attaches before the root navigation.
- The crawl calls `browser_end()` in `finally`.
- `browser_start` reports `restored`.
- `browser_end` reports `stopped`, `released`, `captured`, and `saved`.
  `success` is true only when the session is stopped or released.
  A false `saved` makes the run partial.
- The crawl budget is 600 seconds.
  The 300-action cap is removed.
  Time is the only bound.
- The symbolic frontier owns `frontier_empty`.
  The JEV keeps returning `none` per page.
- `operator_cancel`, `session_deadline`, and `session_missing` are incomplete.
- `manifest.run.partial` is carried into the manifest.
  `crawl_pod` routes a partial manifest to reduced coverage.

## 6. Interfaces

| Plane | Module | Single responsibility | Interface |
|---|---|---|---|
| Pool | `WorkerRegistry` | discover and health-check workers | `refresh() -> PoolReport` |
| Pool | `WorkerProxy` | per-replica HTTP and WebSocket proxy | `start/stop` |
| Pool | `LeaseManager` | lease, heartbeat, TTL, release | `start/exec/end/close/shutdown` |
| Pool | `SteelCli` | subprocess, guard, capture, release | `start/exec/end` |
| Pool | `BrowserSessionStore` | atomic records and name validation | `load/save/validate` |
| MCP | `BrowserService` | three tools, grammar, response envelope | `start/exec/end` |
| Crawl | `McpBrowserClient` | tool calls, response mapping, error taxonomy | `start/exec/end` |
| Crawl | `SteelSessionClient` | session identity and `SteelResult` | `start/exec/end` |
| Crawl | `LiveCdpTransport` | CDP socket, Host override, page attach | `send/replay` |
| Crawl | `CaptureSidecar` | passive network observation | `attach/pump/close` |
| Crawl | `CrawlJob` | lifecycle order and finalize | `run` |
| Crawl | `Frontier` | traversal and stop proof | `run` |
| Crawl | `JevPolicy` | per-page choice | `choose` |
| Crawl | `CrawlRun` | wiring only | `run` |
| Crawl | `Manifest` and `RunLedger` | durable evidence | `write/finalize` |
| Pod | `crawl_pod` | pod wiring | `build_crawl_pod` |
| Control | `pipeline` and `auth_feed` | account and state projection | functions |
| Control | Auth gateway | auth decision | prompt and state machine |
| Eval | Target strategies | target front and aliases | `up/down` |

## 7. Configuration

- Hardcode the Docker socket, store, CLI, guard, pool label, and public port base.
- `STEEL_CLI_TIMEOUT_S=300`.
- Remove `STEEL_POOL_SIZE`, `STEEL_POOL_FORWARD_PORTS`, `STEEL_POOL_FORWARD_HOST`, `STEEL_WORKER_HOST`, `STEEL_CRAWL_CLI`, and `STEEL_CRAWL_MAX_ACTIONS`.
- Keep `STEEL_POOL_DOCKER_SOCKET` as the pool on/off switch.
  The base sets `/var/run/docker.sock`; the thin overlay sets empty.
- Keep `KALI_BROWSER_MCP_URL` empty in the base; the eval overlay sets `http://kali:8003/mcp`.
- Remove `STEEL_API_KEY` and the old `STEEL_BROWSER_API_URL` from the eval `.env`.
  `STEEL_API_KEY` stays in the accepted key set; when present, both Steel clients use the cloud.

## 8. Images

- Build `steel-browser-api:v0.5.5-beta` for the host architecture.
  The eval host is aarch64; the old pool host image is amd64.
  The arm64 build uses Debian's `chromium` and `chromium-driver`, both available.
- Do not transfer the amd64 image to the eval host.
- The agent image already has `fastmcp 2.14.7`, `langchain-mcp-adapters 0.3.2`, `mcp 1.30.0`, and `langchain-core 1.5.3`.
  No dependency rebuild is needed.
- The agent source is bind-mounted; the Kali source is bind-mounted.

## 9. Work items

1. Pool plane: single `steel-worker` service, `deploy.replicas: 2`, thin overlay, Docker socket, entrypoint without forwards, runbook.
2. Discovery and proxy: worker container IP, public port, reverse proxy, `websocketUrl` rewrite, lease view CDP fields.
3. Crawl client: `SteelSessionClient` MCP backend, `SteelResult` mapping, `LiveCdpTransport` Host override, `run_live_crawl` lifecycle.
4. Lifecycle and stop: 600-second budget, action-cap removal, partial manifest, `crawl_pod` partial routing.
5. Auth store and gateway: decoupled auth context, `browser_context.ref`, `browser_auth` reduction, `authn` skill and prompt mapping.
6. Tests and E2E: unit seams, contract over the real MCP protocol, deployment compose checks, White Jotter and ComfyUI live E2E on the eval host.
7. Documentation: spec sections 2.1, 4.1, 4.3, 4.4, 9.1, 12, and 15; pool runbook; `eval/OPERATOR.md`; conjunction; evidence.

## 10. Implementation status

Implemented on `feat/steel-crawl-convergence`:

- `2b27ce71` - worker discovery, the per-replica reverse proxy, the CDP
  fields, and the end-success rule.
- `1aae0895` - the MCP browser client, the session backend facade, the lazy
  CDP transport, the 600-second budget, the partial manifest, and the
  reduced-coverage route.
- The auth store, gateway, skill, and prompt maps are in the same branch.

The live E2E passed on 2026-11-07 on `ubuntu-16gb-nbg1-1` (arm64):
the worker image built natively, the baseline stack discovered two healthy
workers, the three-tool surface and the agent-side CDP path worked, and the
ComfyUI and White Jotter crawls completed with `frontier_empty` and
`partial=false`.
Evidence: `docs/design/evidence/steel-pool-mcp/convergence-e2e-2026-11-07.md`.

## 11. Acceptance

- The thin stack renders and starts without the worker service or the browser URL.
- The baseline stack starts two workers and the MCP discovers both.
- The CLI reaches each worker through its proxy; the Host is localhost.
- The agent's CDP capture attaches through the worker container IP with Host localhost.
- The pool store saves the decoupled auth context and the crawl restores it.
- The White Jotter gateway authenticates, saves, and the crawl restores and crawls.
- The ComfyUI crawl starts a fresh auth context and completes with `frontier_empty`.
- The manifest carries `partial=false` on a complete crawl and `partial=true` on an incomplete one.
- The action ledger records every action with its true outcome.
- The JEV engine diff against `feat/steel-crawl` is empty.

## 12. Agent integration and the decoupled auth context (2026-11-07)

The crawl convergence left the agent surface incomplete: the hunter bound the
old three-tool wrapper, the pod runner carried the `steel-browser` skill
without the tools, and the threat modeller had neither.

The integration fixes that as one capability:

- The agent-facing surface is ONE tool:
  `browser(command="start"|"exec"|"end", url, input, account, persist_context)`.
  The tool description carries the usage contract; each agent's Tools
  paragraph carries one entry.
- The session key is never an agent parameter. The binding derives it from the
  execution unit (`steel-<project>[-<account>]-<role>-<instance>`).
- The auth context is a decoupled object in the pool store. The auth store
  holds only `accounts.<account>.browser_context.ref`.
- `browser(command="start", account=...)` mounts the object; the default
  `browser(command="end")` never overwrites it, and
  `persist_context=true` is the explicit write-back.
- `steel.state` is removed completely. There is no fallback.
- `BrowserTool` is a sync `BaseTool` over the shared `McpBrowserClient`, so the
  same one tool binds to the async agents and the sync `stateful_turn` agents.
- Fail-open everywhere. The lease TTL is the backstop.
- Actor-lifetime binding. End the browser when it is not needed anymore.
- The pool baseline stays two workers.
- The in-scope agents are the recon orchestrator, the threat modeller, the
  hunter, the pod runner, the pod triager, the recon triager, and the
  mechanism typist. The assigner, the skill evolver, the one-shot roles, and
  the removed legacy crawler stay out.
- The pod runner records every browser call as a `RawObservation` with a
  command hash, its result envelope, and the error code. The pod harness
  dedupes a repeated browser command.
- The legacy six-tool crawler is removed; see
  `docs/design/legacy-crawler-eol.md`.
