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
