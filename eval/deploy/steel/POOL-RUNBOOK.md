# Steel browser pool runbook

Operator steps for the in-stack Steel pool (#359, W10).
The pool is part of the polymerhus instance compose project.
There is no SSH tunnel, no Docker socket forward, and no target reverse tunnel.

## Topology

- The pool is one Compose service, `steel-worker`, replicated with
  `deploy.replicas`.
- The baseline count is `deploy.replicas: 2`.
- The worker API runs on port 3000 inside `polymerhus-net`.
  Its `DOMAIN` and `CDP_DOMAIN` stay `localhost:3000`.
- The browser MCP runs in Kali.
  It starts one reverse proxy per worker on `127.0.0.1:3100+i`.
  The proxy rewrites the session `websocketUrl` to
  `ws://localhost:3100+i/` and forwards HTTP and WebSocket traffic to the
  worker's container IP with a localhost Host.
- The agent's CDP capture connects directly to the worker's container IP on
  port 3000 with `Host: localhost:3000`.
- The raw Chrome debug port stays inside the worker container.
- The eval orchestrator writes the synthetic target host into every worker's
  `/etc/hosts`, using the same rewrite as the Kali alias.

## 1. Build the worker image for the host architecture

The eval host is arm64.
The old pool host image is amd64; do not copy it.
Build the worker natively on the eval host from the pinned tag:

```bash
git clone --depth 1 --branch v0.5.5-beta \
  https://github.com/steel-dev/steel-browser.git src
docker build -t steel-browser-api:v0.5.5-beta -f src/api/Dockerfile src
docker image inspect steel-browser-api:v0.5.5-beta \
  --format '{{.Architecture}}/{{.Os}}'
```

The last command must print `arm64/linux` on the eval host.
The Dockerfile installs Debian `chromium` and `chromium-driver`, both of which
have arm64 candidates.
Record the image digest in the trial evidence.

## 2. Start the stack

From the instance worktree, with the instance `.env`:

```bash
docker compose -p ph-<short> \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  -f docker-compose.pool.yml \
  -f eval/docker-compose.eval.yml \
  up -d
```

The baseline starts two workers.
The thin mode omits the pool file and starts none:

```bash
docker compose -p ph-<short> \
  -f docker-compose.yml \
  -f docker-compose.thin.yml \
  up -d
```

The thin overlay omits the worker service, clears
`STEEL_POOL_DOCKER_SOCKET`, and clears `KALI_BROWSER_MCP_URL`.

## 3. Verify

Run these with the same `-f` file set as the start command.

```bash
docker compose -p ph-<short> ps steel-worker
docker compose -p ph-<short> exec kali \
  tail -20 /var/log/kali-browser-mcp.log
docker compose -p ph-<short> exec kali \
  ls -l /var/lib/steel/sessions
```

The pool log must contain `pool.discovered` with the same worker count as the
Compose service and `healthy` equal to that count.
The browser MCP listens on port `8003` on the compose network; it is not
published on the host.
The agent reaches it at `http://kali:8003/mcp`.
The public proxy ports start at `3100` and are loopback-only inside Kali.

Check the three-tool surface from Kali:

```bash
docker compose -p ph-<short> exec -i kali /opt/venv/bin/python - <<'PY'
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://127.0.0.1:8003/mcp") as client:
        print(sorted(tool.name for tool in await client.list_tools()))
        start = await client.call_tool("browser_start", {"name": "runbook-smoke"})
        print(start.data)
        print((await client.call_tool(
            "browser_exec", {"command": "navigate http://localhost:3000/v1/health"}
        )).data)
        print((await client.call_tool("browser_end", {})).data)

asyncio.run(main())
PY
```

The tool list is exactly `browser_start`, `browser_exec`, and `browser_end`.
`browser_start` returns `cdp_url` and `cdp_host`; the normal browser tool strips
both before the model sees them.
`browser_end` reports `stopped`, `released`, `captured`, and `saved`.

## 4. Change the pool size

The count is a bootstrap setting, not a runtime command.

1. Edit `deploy.replicas` on `steel-worker` in `docker-compose.yml`.
2. Run `docker compose -p ph-<short> -f docker-compose.yml -f docker-compose.pool.yml up -d --remove-orphans`.
3. Read `pool.discovered` in the browser MCP log.

`--scale` is deliberately not the supported path.
The architecture is modular, so a later runtime configuration layer can edit
the count without changing the worker contract.
Drain an active lease before scaling down.

## 5. Target alias

The eval orchestrator resolves the replicas with:

```bash
docker compose -p ph-<short> ps -q steel-worker
```

It writes the synthetic host into every replica's `/etc/hosts`.
The alias IP is the worker's `host.docker.internal` gateway.
The target front is the shared `ph-eval-front` on host port 80.

## 6. Troubleshooting

- No workers discovered: check that the worker service is running and carries
  the label `polymerhus.steel-pool=true`.
  Check that the Kali container mounts `/var/run/docker.sock`.
- `pool.warning`: the discovered count is lower than expected.
  Inspect `docker compose ps steel-worker`.
- A CDP 500: the Host header is not localhost.
  Check the MCP reverse proxy and the capture's `cdp_host`.
- The CLI cannot start: check the proxy port `3100+i` is listening in Kali and
  the worker health endpoint answers.
- The worker exits on arm64: rebuild the image on the eval host; do not use the
  amd64 image.
