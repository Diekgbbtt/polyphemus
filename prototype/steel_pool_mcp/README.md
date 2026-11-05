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

## Why the command API

The pinned CLI `0.5.0-preview.6` starts a per-session daemon that connects to the
Steel API root WebSocket. The local `latest` API image returns HTTP 500 on that
root proxy. The deployed API `0.0.1` works. The prototype uses the command API
to isolate the lease protocol from that image defect.

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
