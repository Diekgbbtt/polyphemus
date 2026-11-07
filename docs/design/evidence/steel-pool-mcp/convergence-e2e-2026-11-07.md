# Steel pool convergence: live E2E evidence

Date: 2026-11-07.
Host: `ubuntu-16gb-nbg1-1` (aarch64).
Branch: `feat/steel-crawl-convergence` at `17a4bdfd`.
Instance: `ph-dd131acc`.
Design: `docs/design/steel-crawl-pool-convergence.md`.

## Image

`steel-browser-api:v0.5.5-beta` was built natively on the eval host:

```bash
git clone --depth 1 --branch v0.5.5-beta \
  https://github.com/steel-dev/steel-browser.git steel-browser-build
docker build -t steel-browser-api:v0.5.5-beta \
  -f steel-browser-build/api/Dockerfile steel-browser-build
```

`docker image inspect` reported `arm64/linux`.
The OCI manifest digest is
`sha256:0dfdb92e9a04e4c84fa616f7696d97f8b128983f5140db54157c798e46b34704`.
The v0.5.5-beta tag lays the API Dockerfile out at `api/Dockerfile`, not
`src/api/Dockerfile`; the runbook and operator guide were corrected.

## Stack

The baseline stack started from the convergence worktree with
`docker-compose.pool.yml` included.
Both workers reported healthy:

```text
ph-dd131acc-steel-worker-1 Up (healthy)
ph-dd131acc-steel-worker-2 Up (healthy)
```

The browser MCP log carried:

```json
{"event": "pool.discovered", "discovered": 2, "healthy": 2}
```

The MCP exposed exactly `browser_end`, `browser_exec`, `browser_start`.
`browser_start` returned `cdp_url=ws://172.28.0.5:3000/`,
`cdp_host=localhost:3000`, `remaining_ms`, and `restored`.
`browser_end` reported `captured`, `saved`, `stopped`, and `released`.

The agent's CDP transport connected from the agent container to the worker
container address with `Host: localhost:3000` and evaluated
`Runtime.evaluate` successfully. The crawl's own session client and transport
were used (`eval/steel-crawl-e2e/pool_cdp_probe.py`).

Both worker replicas received the synthetic target aliases:
`172.17.0.1 t-1618c524.target` and `172.17.0.1 t-1fc05262.target`.
The eval orchestrator now writes the same aliases per replica in
`eval/orchestrator/routing.py`; the live stacks predated that code, so the
aliases were applied directly for this run.

## ComfyUI

- Project: `50312d46-7b60-4a99-add3-4ba9a2705620`.
- Run: `e2e-comfyui-20261107T133552Z`.
- Target: `http://t-1fc05262.target/`.
- Session: `steel-50312d46-7b60-4a99-add3-4ba9a2705620`.
- Manifest: `stop_reason=frontier_empty`, `partial=false`, no errors.
- Stats: 541 endpoints, 32 parameters, 553 flows, 481 scripts.
- Summary: `complete`, 1 page, 0 actions, `session_closed=true`.
- End record: `captured=true`, `saved=true`, `stopped=true`.

The crawl ran the production `steel_crawl` phase through `run_pipeline` in the
agent container. The target has no auth surface; the legacy surface gate
passed.

## White Jotter

- Project: `57a54b71-8c8e-4be0-9609-5c789451fba4`.
- Run: `e2e-white-jotter-20261107T134435Z`.
- Target: `http://t-1618c524.target/`.
- Account: `admin-wj-e2e`.
- Stable key: `steel-57a54b71-8c8e-4be0-9609-5c789451fba4-admin-wj-e2e`.
- Manifest: `stop_reason=frontier_empty`, `partial=false`, no errors.
- Auth block: `classification=authenticated`,
  `probe_source=overview.auth_probe.url`,
  `probe_url=http://t-1618c524.target/api/authentication`.
- Stats: 19 endpoints, 2 parameters, 29 flows.
- Summary: `complete`, 1 page, 0 actions, `session_closed=true`.
- End record: `captured=true`, `saved=true`, `stopped=true`.

The gateway-side act was deterministic for the E2E
(`eval/steel-crawl-e2e/wj_pool_gateway.py`): it mounted the stable key, set a
fresh `JSESSIONID` minted by the target's own `POST /api/login`
(`admin`/`123`), proved the oracle returned `200` with
`redirected: false` and `身份认证成功`, and called `browser_end`.
The pool store saved the state at
`/var/lib/steel/sessions/steel-57a54b71-8c8e-4be0-9609-5c789451fba4-admin-wj-e2e.json`.
The crawl then mounted the same key through the browser MCP, restored the
cookie, passed the same oracle, and completed.
The real LLM gateway prompt is covered by its content and unit tiers; this
E2E isolates the pool save/restore and the crawl.

## Commands

The phase runner ran inside the deployed agent container:

```bash
docker exec -e PYTHONPATH=/srv/src:/srv ph-dd131acc-agent-1 \
  python /tmp/phase_runner.py --config /tmp/convergence-<target>-config.json
```

The agent image already carried `fastmcp 2.14.7`,
`langchain-mcp-adapters 0.3.2`, `mcp 1.30.0`, and `langchain-core 1.5.3`;
no agent rebuild was needed.
The agent source and the Kali source are bind-mounted, so the new code ran
without an image build.

## Delta found and fixed

The v0.5.5-beta build path is `api/Dockerfile` with the repository root as
context. The runbook and operator guide said `src/api/Dockerfile`; that path
does not exist in the tag. The docs were corrected after the build.
The original instance `.env` carried `STEEL_API_KEY` and
`STEEL_BROWSER_API_URL`; the convergence worktree `.env` removes both, and
the eval overlay now sets only `KALI_BROWSER_MCP_URL`.

## Verdict

The live pool gate passed:
two healthy workers, the three-tool surface, the proxy Host contract, the
agent-to-worker CDP path, the stable-key state save, the crawl restore, and
the two target crawls.
