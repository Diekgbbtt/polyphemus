# W8/W9 status: the local and live browser-pool gates

Date: 2026-11-05.
Scope: #359 W8 and W9.

## Local gate

Two concurrent MCP clients through one browser MCP process, against two
labelled v0.5.5 workers on `127.0.0.1:3110` and `127.0.0.1:3111`.

- `prototype/steel_pool_mcp/probe_two_agents.py`
  Each client mounted a distinct worker (one live session per worker), both
  navigated the worker's own `/v1/health` concurrently, both ends reported
  `captured`, `saved`, and `stopped` true, the store held `two-a.json` and
  `two-b.json` at `0600`, and both workers settled with no live session.
- `prototype/steel_pool_mcp/probe_hunter_binding.py`
  The real `open_browser_tools` binding opened one MCP session, loaded exactly
  `browser_start` / `browser_exec` / `browser_end`, drove them through
  `invoke_tool`, and saved the record at `0600`.

The Kali entrypoint lane also passed live in the real image: the browser MCP
started beside the exec server, served the three tools, saved a record under
the mounted store, and released on `browser_end`.

## Live eval gate

The eval server is `46.224.225.245`.
The pool host is `dj-viscon-workshop-1` with `steel-1` on `127.0.0.1:3100` and
`steel-2` on `127.0.0.1:3101`.
The live instance is `ph-dd131acc`.
The Kali source is bind-mounted at `/opt/kali`, so the browser MCP runs from
the live tree without an image rebuild.

### White Jotter

The target was brought up from its targetctl contract:

```bash
cd /root/WebExploitBench
TARGETCTL_NO_BUILD=1 TARGETCTL_EXCLUDE_SERVICES=evaluator \
  scripts/targetctl up white-jotter
# http://0.0.0.0:55611/
```

The app answered `http://127.0.0.1:55611/` with the title
`白卷 - White Jotter`.
The shared front `ph-eval-front` was started and its
`eval-target-t-1618c524.target.conf` block now proxies
`t-1618c524.target` to `http://host.docker.internal:55611`.
The front answered 200 from the eval host and from Kali.

### ComfyUI

The pre-pulled image `ghcr.io/diekgbbtt/webench:comfyui-comfyui-manager`
(`pentestbench-comfyui:v0.3.76-isolated`) was brought up from the same
targetctl contract:

```bash
cd /root/WebExploitBench
TARGETCTL_NO_BUILD=1 TARGETCTL_EXCLUDE_SERVICES=evaluator \
  scripts/targetctl up comfyui
# http://0.0.0.0:42025
```

The app answered `http://127.0.0.1:42025/` with the title `ComfyUI`.
The shared front's `eval-target-t-1fc05262.target.conf` now proxies
`t-1fc05262.target` to `http://host.docker.internal:42025`.
Both workers and Kali read the ComfyUI title through the front.

### Target reachability from the pool

The eval host accepts only TCP 22 from the pool host.
The target path is therefore two forwards:

```
worker Chrome -> 172.21.0.1:80 (pool-host TCP relay)
              -> 127.0.0.1:18080 (eval-host SSH reverse tunnel)
              -> eval front :80 (Host t-<id>.target)
              -> target host port
```

The eval host ran:

```bash
ssh -M -S /tmp/steel-target-mux -fN \
  -R 127.0.0.1:18080:127.0.0.1:80 \
  ubuntu@dj-viscon-workshop-1.vsos.ethz.ch
```

The pool host ran a loopback relay from `172.21.0.1:80` to
`127.0.0.1:18080`.
Both workers received the aliases
`172.21.0.1 t-1618c524.target` and `172.21.0.1 t-1fc05262.target`.
Both workers read the White Jotter and ComfyUI titles.

### Worker-port forward and relay

The eval host ran:

```bash
ssh -M -S /tmp/steel-pool-mux -fN \
  -L /run/steel-pool/docker.sock:/var/run/docker.sock \
  -L 0.0.0.0:3100:127.0.0.1:3100 \
  -L 0.0.0.0:3101:127.0.0.1:3101 \
  ubuntu@dj-viscon-workshop-1.vsos.ethz.ch
```

The Kali entrypoint starts `steel_pool/forward.py` when
`STEEL_POOL_FORWARD_PORTS` is set.
The relay listens on `127.0.0.1` and `::1` for each port and forwards to
`host.docker.internal:<port>`.
It preserves the `Host: localhost:<port>` header.
The worker `DOMAIN` and `CDP_DOMAIN` stay `localhost:<port>`.
A direct `DOMAIN=host.docker.internal:<port>` was tried and the CLI failed
with a CDP 500, because the Steel API forwards the client `Host` to Chrome
and Chrome rejects a non-localhost host.

### Kali overlay

`docker-compose.pool-eval.yml` in the instance directory adds:

- `STEEL_POOL_DOCKER_SOCKET=/run/steel-pool/docker.sock`
- `STEEL_SESSION_STORE=/var/lib/steel/sessions`
- `STEEL_CLI=/opt/localbin/.steel/steel`
- `STEEL_GUARD=/opt/kali/steel_guard.py`
- `STEEL_POOL_SIZE=2`
- `STEEL_WORKER_HOST=localhost`
- `STEEL_POOL_FORWARD_PORTS=3100,3101`
- `STEEL_POOL_FORWARD_HOST=host.docker.internal`
- the `steel-sessions` volume
- the `t-1618c524.target:host-gateway` alias

The recreate command is:

```bash
cd /opt/polymerhus-dev/eval/instances/eval-server-1
docker compose -p ph-dd131acc \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  -f eval/docker-compose.eval.yml \
  -f docker-compose.pool-eval.yml \
  up -d --no-build --no-deps --force-recreate kali
```

The entrypoint reported:

```
[entrypoint] worker relay ready on 127.0.0.1 ports: 3100 3101
[entrypoint] browser MCP ready on 127.0.0.1:8003
```

The browser MCP log reported `pool.discovered` with `discovered: 2`,
`healthy: 2`, and `configured: 2`.

### MCP probe

A FastMCP client inside Kali called the three tools:

- `browser_start({"name": "eval-pool-smoke"})` returned
  `session_id=309dd555-5ab5-471d-b525-bb2353df5f1c`.
- `browser_exec({"command": "navigate http://t-1618c524.target/"})` returned
  the title `白卷 - White Jotter` and the URL
  `http://t-1618c524.target/index`.
- `browser_exec({"command": "get title"})` returned
  `白卷 - White Jotter`.
- `browser_exec({"command": "get url"})` returned
  `http://t-1618c524.target/index`.
- `browser_end({})` returned
  `ended: true, captured: true, saved: true, stopped: true, released: null`.

The store held `eval-pool-smoke.json` at `0600`.
Both workers reported an `idle` session and no `live` session.
The event sequence was `pool.discovered`, `lease.mounted`, `lease.released`,
and `session.close`.

The earlier `lease.mount_failed` was a missing guard dependency in the live
instance tree.
The guard imports `steel_contract` and `process_group`; the live tree lacked
both.
They were copied from this branch.
No image rebuild was needed.

### Wrapper removal

The `steel` wrapper is retired.
`postrun.sh` installs `kali/steel_guard.py` as `/opt/localbin/steel`.
The guard injects `--local` for a shell `browser` or `scrape` command when
`STEEL_BROWSER_API_URL` is set.
The browser MCP passes `--api-url` and `--local` itself.
The fixed user agent is gone; the pool keeps the v0.5.5 API's native value.

## Test results

- `tests/kali`: 546 passed.
- `tests/recon/crawl`: 531 passed, 7 skipped.
- `tests/test_steel_skill_rule.py`: 8 passed.
- The W8 binding and harness tests: 20 passed.
- `tests/eval/test_steel_deployment_contract.py`: 15 passed.
- `tests/recon/test_steel_session_only_surfaces.py`: 13 passed.
- `git diff feat/steel-crawl..HEAD -- src/polymerhus/recon/crawl` is empty.

## Remaining W9 conjunction

The deterministic crawl engine is not converged.
It still attaches to a live CLI session by name, calls the refused
`sessions` and `stop` verbs, builds `--session`/`--json` argv, and needs the
CDP websocket and the HTTP-history edge.
The pool MCP owns the lease, hides the worker, returns no websocket, refuses
the lifecycle verbs, and has its own state store.
The auth gateway and the crawl pod are separate phases, so they cannot share
one MCP session without a process change.

The full layer-by-layer discrepancy, the exact call sites, the hard
constraints, and the decision points are in
`docs/design/steel-crawl-pool-conjunction.md`.
The ComfyUI target is deployed and reachable.
The `steel_crawl` E2E is gated by the conjunction decision, not by the target.
