# Steel pool MCP decisions

Date: 2026-11-05.
Status: accepted decisions and open questions.
The open questions gate the system design spec.

## Accepted

D1. The pool manager and the browser MCP server are one component on Kali.

D2. The lease unit is the named browser session.
The owner is the project or trial.

D3. The MCP progress token is optional.
The tool result is the contract.

D4. Workers are created greedily at stack boot.
The pool manager has no Docker write access.

D5. The selected image is `steel-browser-api:v0.5.5-beta`.
The image is used as shipped.

D6. nginx is disabled with `--no-nginx`.

D7. Browser control uses the commands API.

D8. CDP uses the API endpoint with a single `Host: localhost` header.

D9. The direct 9222 port is not exposed.
Chrome binds it to `127.0.0.1`.

D10. The pool size is a policy value.
The execution gate is the concurrency ceiling.

D11. The release ladder is explicit end, MCP close, owner stop, agent
timeout, worker session gone, and TTL.

D12. The `steel_crawl` rebase is the last work item.
The incoming branch is authoritative for the recon module.
This branch owns the wiring to the browser pool.

D13. E2E runs on the eval server with low mocking.

## Open

Q1. Executor identity: CLI main plus guard, or commands API direct.

Q2. MCP server process and endpoint shape.

Q3. Worker registry, provisioning host, and image build.

Q4. Tool surface and skill contract.

Q5. Owner, admin, and project stop hook.

Q6. Mandatory release signals in the first slice.

Q7. `steel_crawl` seam ownership and rebase mechanics.

Q8. E2E target and acceptance scope.

## Findings from the stable-CLI verification

F1. The stable CLI `0.4.4` is not compatible with the 0.5.4 or 0.5.5 API.
The daemon exits with "Session timeout reached".
The 0.4.4 start path takes the API `timeout` value (0) before its own option.
The 0.5.0-preview.6 CLI uses its own option and works against both APIs.

F2. The loopback naming removes the Host-header and nginx problem.
With `DOMAIN=localhost:<port>`, the CLI connects through an SSH loopback
forward and sends `Host: localhost`.
Chrome accepts the browser-level API proxy.
The 9223 nginx proxy is not on the CLI path.

F3. The v0.5.5 API does not accept create-time `timeout` or
`inactivityTimeout`.
The 0.5.0-preview.6 CLI keeps its own timeout state and the session works.
The 0.4.4 CLI reads the zero API value and exits.

F4. The 0.5.0-preview.6 CLI start against the v0.5.5 API with
`DOMAIN=localhost:<port>` returns `remainingMs` 117236 and a live session.
The start works without nginx and without an image patch.

## Revised decisions

D14. The CLI remains the only browser executor.
The commands API is the transport only where the CLI uses it.

D15. The selected compatible pair is the v0.5.5 image and the
0.5.0-preview.6 CLI.
The stable 0.4.4 is not compatible with the v0.5.4 or v0.5.5 API.

D16. The API root WebSocket proxy is the CLI daemon's CDP transport.
The 9223 nginx proxy is removed from the critical path.

D17. Workers expose a loopback API contract.
`DOMAIN=localhost:<port>` and an SSH loopback forward make the Host
`localhost`.
The pool manager does not need the worker's public address.

D18. The agent sees only the browser lifecycle.
There is no `browser_status`, no `pool_status`, and no `release_owner` tool.
The MCP session is the lease key.
The project id is not part of the lease.

D19. The project stop is the MCP server termination.
The MCP connections close, and the co-located pool manager clears its table.

D20. The browser pool and Polyphemus are fully decoupled.
The operator owns container lifecycle.
The pool size is a configuration value.
The pool manager reads container state through the tunneled Docker socket.
The effective worker count is counted from labels.
A count below the configured size raises a warning.

D21. Discovery uses Docker labels and published ports, not full addresses.
The operator marks each worker with a pool label and publishes its API port
on the pool host loopback.
The pool manager derives `localhost:<port>` from the label and port.
The SSH forward uses the same port.

D22. E2E uses White Jotter for the pool, CLI, and CDP path, and ComfyUI for
the `steel_crawl` path.
The eval host is the jump host.
No key pairs are stored on the eval host or the pool host.
No service is exposed to the internet.

## Open after the findings

Q1a. Accept the v0.5.5 image with the 0.5.0-preview.6 CLI, or keep the stable
0.4.4 with the older 0.4.4 API and lose the v0.5.5 features?

Q2. Is the browser MCP server a separate FastMCP process on Kali port 8003
with the pool manager in-process, or a second app in the existing 8000
process?

Q3a. Does the eval host use the operator's forwarded SSH agent and a
ControlMaster to the pool host?
Does the operator reserve the same loopback port on both hosts for each
worker?

Q7a. Does the external CLI wrapper plus loopback API record keep
`session.py`, `live.py`, and `crawl_pod.py` unchanged?
If not, which of those conjunction files may this branch modify?

Q8a. Which image pair is pinned for the E2E: v0.5.5 plus the
0.5.0-preview.6 CLI, or v0.5.4 plus the 0.5.0-preview.6 CLI?

## Accepted after the latest round

D23. The selected pair is the v0.5.5 image and the 0.5.0-preview.6 CLI.
The CLI uses the API root WebSocket proxy.
The loopback `DOMAIN=localhost:<port>` makes the Host `localhost`.
The 9223 nginx proxy is not on the critical path.

D24. The browser MCP server is a separate FastMCP process on Kali port 8003.
The pool manager runs in that process.

D25. The pool manager is fully obscure to SSH.
The operator owns the SSH tunnels, the forwarded agent, the ControlMaster,
and the loopback port reservation.
The pool manager reads the local Docker socket and discovers the labeled
containers and their ports.
It uses `localhost:<port>` as the worker API.
It does not open SSH forwards.
The pool size is configured.
The effective count is read from the labels.
A lower count raises a warning.

D26. Release signals in scope: explicit `browser_end`, MCP close, the FastMCP
session-close hook, MCP server shutdown or project stop, and TTL.
CLI daemon death is not in scope.
The CDP sidecar death is not a release.
The worker session gone is not in scope.

D27. The E2E uses v0.5.5 and the 0.5.0-preview.6 CLI.
White Jotter covers the pool, CLI, and CDP path.
ComfyUI covers the `steel_crawl` path.
The eval host is the jump host.
No key pairs are stored on the eval host or the pool host.
Nothing is exposed to the internet.

## Open after the latest round

Q1b. Heartbeat mechanism and timing.
Q4a. `browser_start` signature and the meaning of `options`.
Q4b. Browser session store location, format, and access control.
Q4c. Session mount mechanism and the restorable state fields.
Q7a. The `steel_crawl` conjunction is deferred to integration time.

## Open session-store and heartbeat questions

Q1b. The Steel session timeout must be owned by the agent or the project.
The MCP server creates the API session with the stored `sessionContext`,
attaches the 0.5.0-preview.6 CLI by session id, and runs an async heartbeat.
The heartbeat runs a cheap `get url` command every 60 s for an idle lease.
The lease TTL is 180 s and releases the lease if the heartbeat stops.
The CLI `--session-timeout` and `--inactivity-timeout` are not relied on.
The heartbeat resets after every browsing command.
Termination stays with `browser_end`, MCP close, server shutdown, and the TTL.
Is this the intended mechanism, interval, and TTL?

Q4a. `browser_start(name)` uses `name` as the stored browser-session key.
The `options` map is removed.
An optional `url` is the only extra argument.
The MCP server owns the worker, the timeout, the heartbeat, and the local mode.
The result returns the session name and the Steel session id.
The agent never sees the worker.
Is the optional `url` needed?

Q4b. The browser-session store is a first-class entity in a volume owned by
the MCP server.
The record fields are name, account, cookies, localStorage, sessionStorage,
indexedDB, created_at, and updated_at.
The file spells the timestamps `createdAt` and `updatedAt`, matching the API
JSON.
The store is owner-only and written atomically.
The agent never reads the files.
The auth store's `steel.state` references the session name.
One live mount per name is allowed.
The session name is the access key.
The instance has one project.
Is the MCP-server-owned volume the right home, and is the name the right
access key?

Q4c. A mount uses `POST /v1/sessions` with `sessionContext` for cookies and
localStorage, then the CLI 0.5.0-preview.6 attaches by session id.
The end path captures `GET /v1/sessions/<id>/context`, saves the record,
stops the CLI, and releases the worker.
The current API restores cookies and localStorage.
It does not restore sessionStorage or indexedDB.
The record may still store those fields as best-effort evidence.
Is the API-create plus CLI-attach the intended mount?
Are the non-restorable fields acceptable as evidence only?

## Correction after the CLI source check

F5. The CLI 0.5.0-preview.6 `browser start` always creates a fresh API
session.
It has no `--session-context` flag and no attach-by-session-id option.
The CLI source builds the create body from `CreateSessionOptions`, which has no
`sessionContext` field.
The v0.5.5 API has `POST /v1/sessions`, `GET /v1/sessions/<id>/context`, and
`POST /v1/sessions/<id>/release`.
It has no context-update route.
The accepted API-create plus CLI-attach mount is therefore not available.

D28. The mount uses the CLI for all browser control.
The start runs `browser start` on the worker with `--session-timeout 3600000`
and `--inactivity-timeout 0` as safety values.
The lease TTL remains the termination authority.
The restore runs `browser cookies set` for each stored cookie.
The restore visits each stored origin and runs `browser storage local set` for
each key.
Cookie expiry, SameSite, priority, and source metadata are not restorable
through the CLI.
The end path captures `GET /v1/sessions/<id>/context` for full evidence, then
runs `browser stop`; the API release is the fallback.
If the API capture fails, the end path captures cookies with
`browser cookies` and localStorage for the current origin with
`browser storage local`.
sessionStorage and indexedDB stay evidence only.
The upstream `--session-context` flag remains the upgrade path if
full-fidelity restore is required.
