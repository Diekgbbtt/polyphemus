# Steel pool MCP prototype

This directory contains the prototype for the co-located Steel MCP server and
pool manager. It demonstrates one MCP session per browser lease, a typed pool
wait, explicit release, owner stop, TTL reap, and a crawler-style command
sequence.

## What it runs

- Two `ghcr.io/steel-dev/steel-browser-api:latest` workers.
- One `polymerhus-kali:latest` container with the MCP server and pool manager.
- Two `polymerhus-agent:latest` clients that run concurrently.
- The MCP server on port 8003. The workers on ports 3100 and 3101.

The server leases a worker per MCP session. The client never sees the worker
URL. The server creates and drives the browser through the Steel command API.

## Executors

The production path is the pinned Steel CLI:

```bash
STEEL_EXECUTOR=cli STEEL_GUARD=1 bash prototype/steel_pool_mcp/run_scenarios.sh concurrent
```

The `cli` executor runs the CLI through the existing `kali/steel_guard.py`.
The guard keeps its command sanitization, live-session check, result
classification, and trace logic. The server transports the guard output
unchanged.

The `api` executor is a local fallback. It uses the Steel command engine.
It is not a production channel.

## The CDP Host fix

The local `latest` API image forwarded the container Host header to Chrome.
Chrome rejected it and the API root proxy returned HTTP 500.
The prototype applies two one-line fixes at container boot:

- `changeOrigin: true` on the root WebSocket proxy.
- `proxy_set_header Host localhost;` on the 9223 CDP proxy.

See `patch-steel-api.sh`. The production fix belongs in the API image.

Direct CDP is available at `ws://<worker>:9223/devtools/browser/<id>` for the
`steel_crawl` sidecar. The API root proxy is not on the crawler path.

## Run

From the repository root:

```bash
bash prototype/steel_pool_mcp/run_scenarios.sh concurrent
bash prototype/steel_pool_mcp/run_scenarios.sh exhaust
bash prototype/steel_pool_mcp/run_scenarios.sh outlier
bash prototype/steel_pool_mcp/run_scenarios.sh stop
bash prototype/steel_pool_mcp/run_scenarios.sh crawler
bash prototype/steel_pool_mcp/run_scenarios.sh all
```

The runner starts the workers and the server with Docker Compose, runs the
clients with the agent image, and writes evidence to
`prototype/steel_pool_mcp/logs/`.

Stop and remove the stack:

```bash
bash prototype/steel_pool_mcp/run_scenarios.sh down
```

## Scenarios

- `concurrent`: two clients, two workers. Both acquire a different worker and
  complete.
- `exhaust`: two holders occupy both workers. A third client gets
  `pool_exhausted` after the configured wait. The holders are killed and the
  TTL reaps them.
- `outlier`: one client is killed after it starts. The TTL reaps the lease.
- `stop`: two holders are released by `release_owner`.
- `crawler`: one client runs three navigations through one lease.

## Configuration

The server reads:

- `STEEL_POOL_WORKERS`: comma-separated worker base URLs.
- `STEEL_POOL_TTL_S`: idle TTL.
- `STEEL_POOL_WAIT_S`: bounded pool wait.
- `STEEL_MCP_PORT`: MCP port.
- `STEEL_POOL_LOG`: JSONL event log.

The client reads:

- `STEEL_EXECUTOR`: `cli` or `api`.
- `STEEL_GUARD`: `1` runs the CLI through `kali/steel_guard.py`.
- `STEEL_CLI`: the pinned CLI binary.
- `STEEL_MCP_URL`: MCP endpoint.
- `CLIENT_ID`: log identity.
- `OWNER`: lease owner.
- `HOLD_S`: idle hold before `browser_end`.
- `OUTLIER`: start and exit without `browser_end`.
- `WAIT_ONLY`: exercise the pool wait.
- `RELEASE_OWNER`: call the owner stop hook.
- `CRAWLER`: run the three-page probe.
- `STATUS_ONLY`: read the pool table without leasing.

## Scope

This is a prototype, not production code. The pool manager uses a static worker
list and has no Docker control. The admin tools are not owner-scoped. The MCP
session close is not wired to release. See
`docs/design/steel-pool-mcp-prototype-report.md`.
