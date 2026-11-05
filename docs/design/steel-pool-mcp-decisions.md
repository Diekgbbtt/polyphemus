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
