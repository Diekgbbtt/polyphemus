> 2026-11-07: the agent surface is one `browser` tool and the auth
> context is a decoupled pool-store object referenced by
> `accounts.<account>.browser_context.ref`. The stable-key and
> `steel.state` steps below are historical. See
> `docs/design/agent-browser-integration-plan.md`.

# Steel crawl pool convergence: implementation plan

Status: A, B, C, and D complete; E and F pending.
Design: `docs/design/steel-crawl-pool-convergence.md`.
Branch: `feat/steel-crawl-convergence`.
Method: one vertical slice at a time, red then green, the targeted suite after
every slice, and the full suite at each phase gate.
No slice is closed with a failing or unrun test.

## Phase A - Pool data plane (complete)

- [x] A1 Worker and registry: container-IP discovery, stable public ports,
  health through the container address; the worker lives in
  `docker-compose.pool.yml` so thin mode omits it instead of planning a pull.
- [x] A2 Worker proxy: HTTP and WebSocket forwarding, Host preservation,
  `websocketUrl` rewrite, chunked responses.
- [x] A3 Lease, service, and boot: proxy lifecycle, CDP fields, end-success
  rule, config constants, forward removal.
- Gate: `tests/kali` green.

## Phase B - Crawl client (complete)

- [x] B1 MCP browser client: persistent session, typed error mapping, real
  streamable-HTTP contract test.
- [x] B2 Session client backend: `CliBackend` and `McpBackend` behind one
  `SteelSessionClient`.
- [x] B3 Live CDP transport: lazy connect, container socket, localhost Host,
  page auto-attach.
- [x] B4 Live run and pod: 600-second budget, no action cap, close-before-
  manifest, `saved=false` partial, partial reduced coverage.
- Gate: `tests/recon/crawl` green.

## Phase C - Auth store and gateway (complete)

- [x] C1 Stable state key: `browser_session_name`, fallback projection,
  pipeline `steel_session`.
- [x] C2 Browser auth reduction: only `auth_probe` and `login_url`.
- [x] C3 Gateway binding and prompt: one MCP session for the three tools,
  stable key, `steel.state` write.
- [x] C4 Authn skill mapping: meta skill and bootstrap workflow use the three
  tools and the pool store.
- Gate: the gateway, orchestrator, authn-loop, auth-feed, and skill tests green.

## Phase D - Documentation (complete)

- [x] D1 Spec sections 2.1, 3, 4.1, 4.3, 4.4, 9.1, 12, 13, 14.5, and 15.
- [x] D2 Pool runbook, operator guide, convergence record, conjunction note.
- [ ] D3 Live E2E evidence (phase F).

## Phase E - Adversarial review and fix loop

- [x] Dispatch adversarial reviews with the critical-thinking frame.
- The reviews hunted: non-functional requirement coverage, technical invariants
  and environmental constraints, spec divergence, unhandled outliers, design
  smells, high risk, cheap patches instead of wider component change,
  ambiguous interfaces, high cyclomatic complexity, and documentation
  convergence.
- Each finding became a fix slice with its own red test.
- [x] Repeated until both reviewers reported PASS with no residual defect.
- Gate: both reviewers reported clean on `17a4bdfd`.

## Phase F - E2E execution

- [x] F1 Build `steel-browser-api:v0.5.5-beta` for arm64 on the eval host
  (`arm64/linux`, digest `sha256:0dfdb92e...`).
- [x] F2 Sync the instance, start the baseline stack, verify two healthy
  workers and the three-tool surface (`pool.discovered 2/2`).
- [x] F3 Run the ComfyUI `steel_crawl` E2E (`frontier_empty`, `partial=false`,
  541 endpoints, 553 flows).
- [x] F4 Run the White Jotter authenticated E2E (`frontier_empty`,
  `partial=false`, authenticated oracle, 19 endpoints, 29 flows).
- [x] F5 Record evidence in
  `docs/design/evidence/steel-pool-mcp/convergence-e2e-2026-11-07.md`.
