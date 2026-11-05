# Steel pool MCP prototype

This directory contains the prototype for the co-located Steel MCP server and
pool manager. It demonstrates one MCP session per browser lease, a typed pool
wait, explicit release, owner stop, TTL reap, and a crawler-style command
sequence.

The production design is in `docs/design/steel-pool-mcp-system-design.md`.
It uses the CLI 0.5.0-preview.6 for every browser command and the v0.5.5 API
only for context capture and release.
The commands API executor remains here for comparison and for the early
concurrency scenarios.

## What it runs

- Two Steel API workers from the v0.5.5-beta image.
- One `polymerhus-kali:latest` container with the MCP server and pool manager.
- Two `polymerhus-agent:latest` clients that run concurrently.
- The MCP server on port 8003. The workers on ports 3100 and 3101.
- The API endpoint is the CDP channel. Chrome's 9222 port is internal.

The server leases a worker per MCP session. The client never sees the worker
URL. The production path creates and drives the browser through the CLI; the
prototype's default commands API executor reaches the same commands API
directly.

## v0.5.5 image

The `v0.5.5-beta` image tag is not published on GHCR.
The `latest` tag is 0.5.4.
Build the tagged source locally:

```bash
curl -fsSL -o /tmp/steel-v055.tar.gz \
  https://github.com/steel-dev/steel-browser/archive/refs/tags/v0.5.5-beta.tar.gz
tar -xzf /tmp/steel-v055.tar.gz -C /tmp
docker build -f /tmp/steel-browser-0.5.5-beta/api/Dockerfile \
  -t steel-browser-api:v0.5.5-beta /tmp/steel-browser-0.5.5-beta
```

The image is used as shipped.

- `--no-nginx` is an official entrypoint flag.
  It removes the 9223 reverse proxy.
- `ENABLE_COMMANDS_API=true` enables the commands API.
- `HOST=0.0.0.0` lets Chrome expose its native CDP port on 9222.
- `CDP_DOMAIN=<worker>:3000` points the API's debugger URLs at the API endpoint.

No image files are patched.

## Why this path

The old path used the API root WebSocket proxy and the 9223 nginx proxy.
Both forwarded the client Host header to Chrome.
Chrome rejected the container hostname, and the proxy returned 500.

The structural fix is to avoid both proxies:

- browser control uses the commands API over HTTP;
- the crawler uses the API endpoint as the browser-level CDP channel;
- nginx is disabled;
- the direct 9222 port is not exposed.

The CDP client sets a single `Host: localhost` header.
Chrome accepts that Host.
The API proxy forwards the browser-level CDP.
The `steel_crawl` sidecar attaches to the page target and captures Network
events.

## Executors

The prototype default executor is `api`, the v0.5.5 commands API.
The production executor is `cli`.
The `api` executor remains for the early concurrency scenarios and for a
comparison path without the CLI.

The `cli` executor runs the CLI through the existing `kali/steel_guard.py`.
The guard keeps its command sanitization, live-session check, result
classification, and trace logic. The server transports the guard output
unchanged.

The pinned CLI `0.5.0-preview.6` uses the daemon/CDP path.
Its daemon reaches the API root WebSocket proxy, which is the compatible
no-nginx CDP transport; the 9223 nginx proxy is not used.
The live probe `probe_cli_mount.py` exercises this path against one worker.

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

Light v0.5.5 checks:

```bash
bash prototype/steel_pool_mcp/test_v055.sh
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
- `STEEL_EXECUTOR`: `api` or `cli`.
- `STEEL_GUARD`: `1` runs the CLI through `kali/steel_guard.py`.

The client reads:

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
