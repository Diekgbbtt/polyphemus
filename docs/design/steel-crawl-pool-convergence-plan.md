# Steel crawl pool convergence: implementation plan

Status: active, 2026-11-07.
Design: `docs/design/steel-crawl-pool-convergence.md`.
Branch: `feat/steel-crawl-convergence`.
Method: one vertical slice at a time, red then green, the targeted suite after
every slice, and the full suite at each phase gate.
No slice is closed with a failing or unrun test.

## Phase A - Pool data plane

### A1 Worker and registry

- Red: container-IP discovery, stable public port `3100 + i`, no published
  port, health through the container IP, malformed payload rejection.
- Green: `kali/steel_pool/pool.py` (`Worker`, `parse_worker`,
  `discover_workers`, `WorkerRegistry`).
- Gate: `tests/kali/test_steel_pool_docker.py` green.

### A2 Worker proxy

- Red: HTTP forward, Host preservation, `websocketUrl` rewrite, chunked and
  fixed-length responses, WebSocket upgrade passthrough, upstream failure.
- Green: `kali/steel_pool/proxy.py` (`WorkerProxy`).
- Gate: `tests/kali/test_steel_pool_proxy.py` green.

### A3 Lease, service, and boot

- Red: proxy start on acquisition, proxy stop on end and abandonment,
  `LeaseView.cdp_url`/`cdp_host`/`restored`, `browser_start` fields,
  `browser_end.success` true only on stopped or released, proxy shutdown.
- Green: `kali/steel_pool/lease.py`, `kali/steel_pool/server.py`,
  `kali/steel_pool/__init__.py`; delete `forward.py` and its test.
- Gate: `tests/kali` green.

## Phase B - Crawl client

### B1 MCP browser client

- Red: start/exec/end envelopes over the real streamable-HTTP MCP protocol,
  typed mapping of every MCP error code, transport failure, bounded timeout.
- Green: `src/polymerhus/recon/crawl/steel/mcp_client.py`
  (`McpBrowserClient`).
- Gate: `tests/recon/crawl/steel/test_mcp_client.py` and
  `test_mcp_client_contract.py` green.

### B2 Session client backend

- Red: `attach` mounts through MCP start, `execute` sends the bare grammar,
  `stop` ends and carries `saved`, `no_session` maps to `SessionMissing`,
  every existing CLI test unchanged.
- Green: split `session.py` into `CliBackend` and an injected backend;
  `SteelSessionClient` keeps its engine-facing surface.
- Gate: `tests/recon/crawl/steel/test_session.py` and
  `test_session_boundary.py` green plus the new backend tests.

### B3 Live CDP transport

- Red: lazy connect, `sock` to the container address, `Host` from
  `cdp_host`, page auto-attach, close before connect, event replay unchanged.
- Green: `LiveCdpTransport` in `src/polymerhus/recon/crawl/steel/live.py`.
- Gate: `tests/recon/crawl/steel/test_live_transport.py` green.

### B4 Live run and pod

- Red: 600-second default, no action cap, MCP URL required, stable session
  name from `extra`, start before sidecar, end in the job close, `saved=false`
  makes the manifest partial, partial manifest routes to reduced coverage.
- Green: `live.py`, `job.py`, `crawl_pod.py`.
- Gate: the crawl job, run, pod, and live tests green.

## Phase C - Auth store and gateway

### C1 Stable state key

- Red: `browser_session_name` produces `steel-<project>[-<account>]`, safe
  characters, bounded length; `project_steel_state` falls back to it.
- Green: `app/steel_session_state.py`, `control/auth_feed.py`,
  `control/pipeline.py`.
- Gate: the auth feed and pipeline tests green.

### C2 Browser auth reduction

- Red: `project_browser_auth` returns only `auth_probe` and `login_url`.
- Green: `control/auth_feed.py`.
- Gate: the auth feed tests green.

### C3 Gateway binding and prompt

- Red: the gateway binds the three browser tools over one MCP session,
  closes the session after the turn, and the prompt uses the three tools and
  the stable key.
- Green: `control/orchestrator_agent.py`,
  `control/prompts/auth-gateway.md`.
- Gate: the gateway, orchestrator, and authn-loop tests green.

### C4 Authn skill mapping

- Red: the meta skill and bootstrap workflow use the three browser tools,
  the stable key, and the pool store; no CLI session flags remain.
- Green: `skills/meta/authn-skill-writing/SKILL.md` and
  `references/bootstrap-workflow.md`; the project skill template.
- Gate: the skill tests green.

## Phase D - Documentation

- D1: update `docs/design/steel-crawl-spec.md` sections 2.1, 4.1, 4.3, 4.4,
  9.1, 12, and 15.
- D2: update the pool design, decision record, conjunction, runbook, and
  operator guide.
- D3: record the conjunction and the E2E evidence.

## Phase E - Adversarial review and fix loop

- Dispatch one adversarial review with the critical-thinking frame.
- The review hunts: non-functional requirement coverage, technical invariants
  and environmental constraints, spec divergence, unhandled outliers, design
  smells, high risk, cheap patches instead of wider component change,
  ambiguous interfaces, high cyclomatic complexity, and documentation
  convergence.
- Each finding becomes a fix slice with its own red test.
- Repeat until a full review pass reports no residual quality defect.
- Gate: the reviewer reports clean.

## Phase F - E2E execution

- F1: build `steel-browser-api:v0.5.5-beta` for arm64 on the eval host.
- F2: sync the instance, start the baseline stack, and verify two healthy
  workers and the three-tool surface.
- F3: run the ComfyUI `steel_crawl` E2E.
- F4: run the White Jotter authenticated E2E.
- F5: record evidence and close the work items.
