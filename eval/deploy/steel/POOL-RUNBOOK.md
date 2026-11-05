# Steel browser pool runbook

Operator steps for the external Steel pool and the Docker socket tunnel (#359, W6).
This runbook deploys nothing itself.
It states the state the operator must create and the checks that prove it.

## Topology

- Pool host: `dj-viscon-workshop-1.vsos.ethz.ch` (`192.33.91.87`).
- Eval host: `46.224.225.245`.
  It runs the polymerhus stack and the Kali container.
- Workers: `steel-1` on `127.0.0.1:3100` and `steel-2` on `127.0.0.1:3101`.
- Browser MCP: `http://kali:8003/mcp` on the compose network.
  It is not published.
- Worker APIs: reachable only on the pool host loopback and through the tunnel.

The data path is:

```text
agent -> kali:8003/mcp -> browser MCP -> localhost:3100 (inside Kali)
                                      -> ssh tunnel -> pool host 127.0.0.1:3100
                                      -> Steel worker -> Chrome
```

The pool manager reads the Docker socket through the same tunnel.
It never opens an SSH connection itself.

## Prerequisites

- The image `steel-browser-api:v0.5.5-beta` exists on the pool host.
  Build it from the pinned tag when it is absent:

```bash
cd /home/ubuntu/steel-pool
git clone --depth 1 --branch v0.5.5-beta \
  https://github.com/steel-dev/steel-browser.git src
docker build -t steel-browser-api:v0.5.5-beta -f src/api/Dockerfile src
```

- The operator's SSH agent holds a key that reaches the pool host.
- The operator has shell access to the eval host.

## 1. Deploy the workers on the pool host

Copy `eval/deploy/steel/docker-compose.steel-pool.yml` to the pool host.
Run it there:

```bash
cd /home/ubuntu/steel-pool
docker compose -f docker-compose.steel-pool.yml up -d
```

Check both workers:

```bash
docker ps --filter label=polymerhus.steel-pool=true \
  --format '{{.Names}}  {{.Status}}  {{.Ports}}'
curl -fsS http://127.0.0.1:3100/v1/health
curl -fsS http://127.0.0.1:3101/v1/health
```

Both lines show `(healthy)` and both health calls answer `{"status":"ok"}`.
The ports section shows `127.0.0.1:3100->3000/tcp` and `127.0.0.1:3101->3000/tcp`.
A `0.0.0.0` publish is a defect: stop the worker and fix the compose file.

The image is single-session per worker.
Two workers serve two concurrent browser sessions.
The pool host has 2 CPUs and about 3.8 GiB of memory, so two heavy Chrome pages are the practical ceiling.

## 2. Forward the agent to the eval host

From the operator workstation:

```bash
ssh -A ubuntu@46.224.225.245
```

The `-A` flag exposes the operator agent on the eval host through `SSH_AUTH_SOCK`.
No key pair is copied to the eval host or the pool host.

Confirm the pool host answer from the eval host before the next step:

```bash
ssh -o BatchMode=yes ubuntu@dj-viscon-workshop-1.vsos.ethz.ch true
```

## 3. Start Kali with the pool overlay

On the eval host, from the polymerhus checkout:

```bash
export SSH_AUTH_SOCK=$SSH_AUTH_SOCK
docker compose -f docker-compose.yml \
               -f docker-compose.pool-overlay.yml up -d kali
```

The overlay mounts the agent at `/run/ssh-agent.sock` and sets `STEEL_POOL_DOCKER_SOCKET=/run/steel-pool/docker.sock`.
Compose refuses to render when `SSH_AUTH_SOCK` is unset.
That guard exists so a missing agent cannot create a directory at the socket path.

The entrypoint starts the exec MCP first.
It then waits up to 300 seconds for the Docker socket, so the next step can run after the container is up.
The browser MCP is not on the exec plane: its failure never stops `kali:8000/mcp`.

Set the expected pool size in the instance `.env` when it differs from 4:

```bash
STEEL_POOL_SIZE=2
```

## 4. Create the tunnel inside Kali

The tunnel must terminate inside the Kali container.
The worker API derives each session URL from `DOMAIN=localhost:<port>`, so the client address is `localhost` and the tunnel must answer on both loopback families.

Run this on the eval host:

```bash
docker exec -d polymerhus-kali-1 sh -c '
  rm -f /run/steel-pool/docker.sock
  exec ssh -N \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L 127.0.0.1:3100:127.0.0.1:3100 \
    -L [::1]:3100:127.0.0.1:3100 \
    -L 127.0.0.1:3101:127.0.0.1:3101 \
    -L [::1]:3101:127.0.0.1:3101 \
    -L /run/steel-pool/docker.sock:/var/run/docker.sock \
    ubuntu@dj-viscon-workshop-1.vsos.ethz.ch'
```

`rm -f` removes a stale socket from a previous tunnel.
`ExitOnForwardFailure=yes` turns a busy port into an immediate failure instead of a half-open tunnel.
`BatchMode=yes` makes a missing agent fail instead of prompting.
`accept-new` records the pool host key on first use in the container.
The operator must verify that fingerprint against the pool host out of band.

For one worker, drop the second pair of forwards.
For a third worker, add one pair per port and add the worker to the pool compose file.

## 5. Verify

Check the tunneled Docker socket:

```bash
docker exec polymerhus-kali-1 \
  curl -fsS --unix-socket /run/steel-pool/docker.sock http://localhost/_ping
```

The answer is `OK`.

Check that both worker forwards listen on loopback inside Kali:

```bash
docker exec polymerhus-kali-1 ss -ltn | grep -E ':3100|:3101'
```

Both listeners show `127.0.0.1` or `[::1]`.
A listener on `0.0.0.0` is a defect: kill the tunnel and re-run the command.

Check the browser MCP log:

```bash
docker exec polymerhus-kali-1 tail -20 /var/log/kali-browser-mcp.log
docker logs polymerhus-kali-1 2>&1 | grep 'browser MCP'
```

The entrypoint line reads `browser MCP ready on 127.0.0.1:8003`.

Check the tool surface and one full session from inside Kali:

```bash
docker exec -i polymerhus-kali-1 /opt/venv/bin/python - <<'PY'
import asyncio

from fastmcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8003/mcp") as client:
        tools = sorted(tool.name for tool in await client.list_tools())
        print("tools:", tools)
        start = await client.call_tool(
            "browser_start", {"name": "runbook-smoke"}
        )
        print("start:", start.data)
        step = await client.call_tool(
            "browser_exec",
            {"command": "navigate http://localhost:3000/v1/health"},
        )
        print("navigate:", step.data)
        url = await client.call_tool(
            "browser_exec", {"command": "get url"}
        )
        print("url:", url.data)
        end = await client.call_tool("browser_end", {})
        print("end:", end.data)


asyncio.run(main())
PY
```

`tools` is exactly `['browser_end', 'browser_exec', 'browser_start']`.
`start` carries no URL, no port, and no container name.
`navigate` answers `success: true`.
`end` answers `ended: true`.

Check the saved record:

```bash
docker exec polymerhus-kali-1 ls -l /var/lib/steel/sessions
```

The file `runbook-smoke.json` exists with mode `0600`.

Check the pool warning path.
The log line appears when fewer workers answer than `STEEL_POOL_SIZE`:

```bash
docker exec polymerhus-kali-1 grep '"event": "pool.warning"' \
  /var/log/kali-browser-mcp.log
```

The event carries `reachable` and `configured`.
The pool still leases every healthy worker.
The warning is the operator signal, not a hard stop.

## Failure recovery

- The tunnel dies: the stale socket stays behind.
  Re-run step 4, which removes it first.
- Kali restarts: the tunnel dies with the container.
  Re-run step 4. The entrypoint waits for the socket.
- The browser MCP is absent from the log: read the log.
  A configuration error names the missing input.
  Fix the input, restart Kali, and re-run step 4.
  The restart drops the tunnel with the container.
- A worker is unhealthy: recreate only that worker on the pool host.
  The pool manager rediscovers it on the next lease.
- A session is stuck `live` on a worker: end it through the worker API.
  A failed end quarantines the worker, and the pool skips it.

## Security

- The Docker socket forward grants root-equivalent control of the pool host to any process in Kali.
  Forward it only while the pool is in use.
  Treat `docker exec` access to Kali as pool-host root access.
- The worker APIs listen on the pool host loopback only.
  The tunnel binds `127.0.0.1` and `::1` only.
- The browser MCP port 8003 is not published.
  Only the compose network reaches it.
- No key pair is stored on the eval host or the pool host.
  The agent is forwarded and the mount is removed when the overlay is not used.
- The session store is owner-only.
  Its name is the access key and the agent never reads it.
- The retired single-worker deployment published `3000` and `9223`.
  It is removed. Nothing publishes either port now.

## Shutdown

Stop Kali with `docker compose stop kali`.
The signal runs the end path for every active lease: capture, save, stop, and release.
The tunnel dies with the container.
