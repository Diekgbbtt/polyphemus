# Steel pool MCP work items

Date: 2026-11-05.
Spec: `docs/design/steel-pool-mcp-system-design.md`.
Plan: `docs/design/steel-pool-mcp-workstream-plan.md`.

## Dependency map

```text
W1 Session store ─┐
W2 Pool discovery ─┼─> W3 CLI mount ─┐
                    │                 ├─> W5 MCP server ─> W6 Deployment
                    └─> W4 Heartbeat ─┘                    ├─> W7 Skill
                                                            └─> W8 White Jotter E2E
                                                                     │
                                                                     v
                                                              W9 steel_crawl
```

W1 and W2 are independent.
W3 needs W1 and W2.
W4 needs W2.
W5 needs W3 and W4.
W6, W7, and W8 need W5.
W9 is last.

## W1 - Browser session store

Deliver:

- Record model.
- Atomic owner-only file store.
- Name validation.
- `sessionContext` projection and restore.
- Redacted representation.

Tests:

- Round trip.
- Missing and corrupt records.
- Invalid names.
- File and directory modes.
- Atomic replacement.
- Restorable and evidence fields.

Gate: unit tests pass. No CLI, no Docker, no MCP.

## W2 - Pool discovery and worker registry

Deliver:

- Docker API client over a Unix socket.
- Label filter.
- Published port parsing.
- Worker URL `localhost:<port>`.
- Health check.
- Pool size warning.
- Worker state.

Tests:

- Fake Docker API.
- Label filtering.
- Port parsing.
- Missing or fewer workers.
- Health failures.
- No container write calls.

Gate: unit tests pass. No Steel API needed.

## W3 - CLI mount and execute

Deliver:

- API session create with `sessionContext`.
- CLI 0.5.0-preview.6 attach by session id.
- API context capture.
- CLI stop and API release.
- Guard pass-through.
- Readiness and error envelopes.

Tests:

- Fake API and fake CLI.
- Create, attach, exec, capture, stop, release.
- Create failure compensation.
- Attach failure compensation.
- Guard refusal propagation.
- No worker URL in the tool result.

Gate: unit tests pass. No live worker.

## W4 - Lease, heartbeat, and TTL

Deliver:

- Lease state machine.
- Idle heartbeat at 120 s.
- TTL at 600 s.
- Reset after every browsing command.
- Capture, stop, and release on TTL.
- MCP close and server shutdown hooks.

Tests:

- Fake clock.
- Idle heartbeat.
- Command resets the idle clock.
- TTL release.
- MCP close release.
- Shutdown release.
- No release on CDP sidecar death.

Gate: unit tests pass. No live worker.

## W5 - Browser MCP server

Deliver:

- FastMCP process on 8003.
- `browser_start(name, url=None)`.
- `browser_exec(command)`.
- `browser_end()`.
- MCP session close hook.
- Structured events.

Tests:

- In-memory FastMCP client.
- Start, exec, end.
- No status or admin tools.
- Worker obscurity.
- Session close release.
- Error envelopes.

Gate: unit tests pass. No live worker.

## W6 - Deployment wiring

Deliver:

- Kali entrypoint starts the browser MCP process.
- Compose mounts the Docker socket and session store.
- Worker labels and loopback ports.
- Operator runbook.
- Pool size and warning.

Tests:

- Compose render.
- Entrypoint probe.
- Missing socket and missing store fail loud.
- Pool size warning.

Gate: configuration tests pass.

## W7 - Skill adjustment

Deliver:

- Minimal `steel-browser` skill changes.
- MCP tool calls instead of shell invocations.
- The command grammar stays.
- No pool or worker language.

Tests:

- Skill validation.
- Tool contract test.
- No `browser_status` reference.

Gate: skill tests pass.

## W8 - White Jotter E2E

Deliver:

- Two v0.5.5 workers on the pool host.
- Operator SSH tunnels.
- White Jotter target.
- Two agents.
- Pool, CLI, and CDP path.
- Low mocking.

Tests:

- Start and mount.
- Concurrent exec.
- End and release.
- CDP capture through the API endpoint.
- TTL and MCP close.

Gate: the White Jotter E2E passes on the eval server.

## W9 - steel_crawl rebase and ComfyUI E2E

This is the last work item.

Deliver:

- Integration worktree and branch based on `feat/steel-crawl`.
- Rebase of this branch's commits.
- Incoming branch authoritative for the recon engine.
- Browser-pool wiring at the conjunction points.
- ComfyUI `steel_crawl` E2E.

Tests:

- Recon engine tests unchanged.
- Conjunction tests.
- ComfyUI E2E.
- No 9223 nginx dependency.

Gate: the rebase is clean. The ComfyUI E2E passes.
