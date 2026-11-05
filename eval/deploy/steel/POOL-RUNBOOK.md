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
               -f docker-compose.pool-overlay.yml up -d kali agent
```

The overlay turns the pool on for both sides: it mounts the agent in Kali, sets the tunnel socket path, and points the agent at `http://kali:8003/mcp`.
The agent container must be recreated to read the URL.
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

## 4b. Variant: the forward lands on the Docker host

The published Kali image has no ssh client.
The eval deployment therefore runs the tunnel on the eval host and relays the
worker ports into Kali.

On the eval host:

```bash
mkdir -p /run/steel-pool
rm -f /run/steel-pool/docker.sock
ssh -M -S /tmp/steel-pool-mux -fN \
  -o StrictHostKeyChecking=accept-new \
  -L /run/steel-pool/docker.sock:/var/run/docker.sock \
  -L 0.0.0.0:3100:127.0.0.1:3100 \
  -L 0.0.0.0:3101:127.0.0.1:3101 \
  ubuntu@dj-viscon-workshop-1.vsos.ethz.ch
```

The `0.0.0.0` bind is on the eval host only.
Kali reaches it through `host.docker.internal`, which resolves to `172.17.0.1`.
The worker APIs stay loopback-only on the pool host.

The Kali overlay sets:

```yaml
STEEL_WORKER_HOST: localhost
STEEL_POOL_FORWARD_PORTS: "3100,3101"
STEEL_POOL_FORWARD_HOST: host.docker.internal
volumes:
  - /run/steel-pool/docker.sock:/run/steel-pool/docker.sock
  - steel-sessions:/var/lib/steel/sessions
```

The entrypoint starts `kali/steel_pool/forward.py`.
The relay listens on `127.0.0.1` and `::1` for each port and forwards to
`host.docker.internal:<port>`.
It preserves `Host: localhost:<port>`.
The worker `DOMAIN` and `CDP_DOMAIN` must stay `localhost:<port>`.
A direct `DOMAIN=host.docker.internal:<port>` makes the CLI fail with a CDP
500, because the Steel API forwards the client `Host` to Chrome and Chrome
rejects a non-localhost host.

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

## 6. Reaching an eval target from the pool

The eval system routes a target by a synthetic Host (`t-<short>.target`)
through the shared `ph-eval-front` container on the eval host.
The pool host cannot reach the eval host beyond TCP 22.
The worker reaches the front through two forwards.

1. The eval host opens a reverse tunnel to the pool host:

```bash
ssh -M -S /tmp/steel-target-mux -fN \
  -o StrictHostKeyChecking=accept-new \
  -R 127.0.0.1:18080:127.0.0.1:80 \
  ubuntu@dj-viscon-workshop-1.vsos.ethz.ch
```

2. The pool host relays its compose bridge gateway port to that tunnel.
   Read the bridge address with `ip -4 addr show`; the current pool compose
   uses `172.21.0.1`.
   Run the relay as root because it binds port 80:

```bash
sudo -n sh -c 'setsid python3 /home/ubuntu/steel-target-relay.py \
  >/root/steel-target-relay.log 2>&1 < /dev/null &'
```

The relay is a small TCP bridge:

```python
import asyncio

LISTEN = ("172.21.0.1", 80)
UPSTREAM = ("127.0.0.1", 18080)


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def handle(reader, writer):
    try:
        ur, uw = await asyncio.open_connection(*UPSTREAM)
    except Exception:
        writer.close()
        return
    await asyncio.gather(pipe(reader, uw), pipe(ur, writer))


async def main():
    server = await asyncio.start_server(handle, *LISTEN)
    async with server:
        await server.serve_forever()


asyncio.run(main())
```

3. The target's front block maps the Host to the target's published port.
   Run this on the eval host:

```bash
printf '%s\n' \
  'server {' \
  '    server_name t-<short>.target;' \
  '    listen 80;' \
  '    location / {' \
  '        proxy_pass http://host.docker.internal:<published>;' \
  '        proxy_set_header Host $host;' \
  '        proxy_set_header X-Real-IP $remote_addr;' \
  '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
  '        proxy_set_header X-Forwarded-Proto $scheme;' \
  '    }' \
  '}' \
| docker exec -i ph-eval-front sh -c \
  'cat > /etc/nginx/conf.d/eval-target-t-<short>.target.conf && nginx -t && nginx -s reload'
```

4. The worker maps the Host to the pool bridge gateway:

```bash
for c in steel-1 steel-2; do
  docker exec "$c" sh -c \
    'grep -q t-<short>.target /etc/hosts || \
     echo "172.21.0.1 t-<short>.target" >> /etc/hosts'
done
```

The worker's browser now reaches the target.
Kali also maps the Host to `172.17.0.1` for non-browser clients:

```bash
docker exec ph-<short>-kali-1 sh -c \
  'grep -q t-<short>.target /etc/hosts || \
   echo "172.17.0.1 t-<short>.target" >> /etc/hosts'
```

Check both targets from a worker:

```bash
docker exec steel-1 sh -c \
  'curl -sS -H "Host: t-<short>.target" http://t-<short>.target/ | grep -o "<title>[^<]*</title>"'
```

The title proves the worker resolved the Host, reached the pool relay, the
eval reverse tunnel, the front, and the target.
The eval front is the only place that maps the Host to the target port.
The worker and Kali aliases only name the pool bridge and the eval host.

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
