# Steel local stack: solutions for multiple concurrent sessions

Date: 2026-11-03.
Question: what are the viable ways to run multiple concurrent browser sessions on the local Steel stack, beyond one active session and beyond tab management?
Short answer: the official local image supports one active session.
The practical solution is one single-instance Steel API container per agent.
A single-container browser pool exists only as unmerged upstream work.
A custom context model is possible but not supported.

## 1. The official constraint

The Steel docs state the concurrency difference directly:

| Feature | Steel Local | Steel Cloud |
| --- | --- | --- |
| Concurrency | **1** | 10 on Launch, 100 on Scale, 1,000+ on Enterprise |

Source: [Steel Local vs Steel Cloud](https://docs.steel.dev/overview/self-hosting/steel-local-vs-steel-cloud).

The self-hosting docs describe one `api` container and one optional `ui` container.
The API exposes port 3000 and Chrome debugging on port 9223.
The docs list at least 4 GB RAM and 10 GB disk for one instance.
Source: [Docker self-hosting](https://docs.steel.dev/overview/self-hosting/docker).

The docs have a "Clustering" page, but it carries no content beyond the heading.
There is no supported local clustering or multi-session mode in the docs.
Source: [Clustering](https://docs.steel.dev/overview/self-hosting/clustering).

## 2. Why one instance is one session

The source is `steel-dev/steel-browser` at commit `9fb9b9239325794b3e2d2a56c7e54c400a7d30bd`.

- `SessionService` has one `activeSession` and a `pastSessions` list: [session.service.ts#L67](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/session.service.ts#L67).
- `startSession` calls `resetSessionInfo`, which completes the current session and replaces it: [session.service.ts#L93-L121](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/session.service.ts#L93-L121).
- `resetSessionInfo` does the replacement: [session.service.ts#L314-L334](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/session.service.ts#L314-L334).
- `GET /v1/sessions/:id` returns a synthetic `released` record for any id other than the active one: [sessions.controller.ts#L91-L126](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/modules/sessions/sessions.controller.ts#L91-L126).
- `POST /v1/sessions/:id/release` releases the active session and ignores the id: [sessions.controller.ts#L67-L80](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/modules/sessions/sessions.controller.ts#L67-L80).
- A session create with a similar launch config reuses the existing browser and refreshes the primary page.
  A different config closes the existing browser before launching a new one: [cdp.service.ts#L688-L780](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/cdp/cdp.service.ts#L688-L780).

`POST /sessions` therefore does not add a concurrent browser.
It replaces the current one, or restarts it with a different config.

The API source has a `createBrowserContext(proxyUrl)` method: [cdp.service.ts#L649-L654](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/cdp/cdp.service.ts#L649-L654).
No route or CLI command calls it.
The tab registry uses `browser.newPage()` and tracks only the default browser context: [tabs.ts#L555-L790](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/commands/tabs.ts#L555-L790).

## 3. Solution models

### A. One single-instance API container per agent

This is the lowest-code-risk model.

- Run N copies of `ghcr.io/steel-dev/steel-browser-api` (or the single-image `ghcr.io/steel-dev/steel-browser`).
- Each container has its own Chrome, its own port, its own `DOMAIN`, and its own `CDP_DOMAIN`.
- Each container supports one active session.
- Allocate one container per agent or per task.
- Point the agent's `STEEL_BROWSER_API_URL` or `--api-url` at its container.
- Release the session when the task ends; reuse the container for the next task.

Why it fits:

- No tabs management.
- Full browser isolation: separate Chrome processes, cookies, storage, and crash domains.
- The official image and the official API are unchanged.
- The CLI's one-session-per-instance assumption stays true.

Costs:

- The docs ask for 4 GB RAM and 10 GB disk per instance.
- The pool fork estimates 100-300 MB per Chromium and about 200 MB for the Node API.
- A 16 GB host can run several instances, but the API image includes Chrome, so disk and pull time matter.
- Each agent needs its own `STEEL_BROWSER_API_URL`, or a per-agent wrapper.
  One shared Kali container with one env var cannot address N APIs.
  The clean layout is one Steel API sidecar plus one Kali or agent per worker.

Operational work:

- A small allocator assigns a free instance/port to an agent.
- A reaper releases idle sessions and stops stale containers.
- A health check per instance.
- A unique `DOMAIN` per instance so the `websocketUrl` and `debugUrl` point at the right container.

This model was not live-tested here because the deployed Steel API is a single remote instance.
It follows directly from the official compose and the source.

### B. Browser-pool fork in one API container

This is the only single-container multi-session design found upstream.
It is not merged.

PR #264, "Add concurrent browser session support - PoC", is open since 2026-03-15:

- A `BrowserPool` of independent Chromium instances, each on its own CDP port.
- `SessionService` changes from one `activeSession` to a `Map<string, Session>`.
- `MAX_SESSIONS`, `CDP_PORT_BASE`, and `SELENIUM_PORT_BASE`.
- Session-specific URLs: `/v1/sessions/{id}/cdp` and `/v1/sessions/{id}/debug`.
- WebSocket routing by session id.
- HTTP 503 when the pool is full.
- A README with a full design, a concurrency test suite, and resource figures.
- Estimated 100-300 MB per Chromium and about 2 GB for five sessions.
- `shm_size: 2gb` is recommended for heavy pages.

Sources: [PR #264](https://github.com/steel-dev/steel-browser/pull/264), [README_CONCURRENT.md](https://github.com/lh-etals/steel-browser/blob/899db7a04d96bd5de89f46dca0990a59655530db/README_CONCURRENT.md).

PR #416, "feat: support concurrent browser sessions", is closed and unmerged:

- Opened 2026-11-03 04:06, closed 04:11 with no substantive review (only a bot greeting).
- 49 files changed, +2667/-635.
- Bounded browser pool with isolated CDP and Selenium ports.
- Session-scoped HTTP and WebSocket routing.
- 409 when a legacy route is ambiguous with multiple active sessions.
- The body says "Tests not run (not requested)".

Source: [PR #416](https://github.com/steel-dev/steel-browser/pull/416).

Assessment:

- The design matches the need: N browser processes, one API, session-scoped URLs.
- It is a fork, not an upstream feature.
- The pinned CLI's compatibility with the session-specific `connectUrl` is not proven.
  The local CLI expects the root `ws://host:3000/`; the fork returns `/v1/sessions/{id}/cdp`.
- Maintaining a 500+ line API fork is a continuous merge cost.
- The PR #416 closure and the open PR #264 suggest no near-term upstream merge.

### C. One Chrome, multiple isolated browser contexts

This is a smaller patch than the browser pool, but it is not upstream.

- Chrome supports multiple `BrowserContext`s in one process.
- The API already has `CDPService.createBrowserContext(proxyUrl)`.
- A fork could map `sessionId` to a `BrowserContext`, add a per-context tab registry, and expose session-scoped CDP/viewer routes.
- Cookies and storage are isolated per context.
- The Chrome process, crash domain, and some fingerprint/plugin state are shared.
- The tab registry, viewer, logs, and command engine must become context-aware.

Assessment:

- Less RAM than N Chrome processes.
- More complex than separate containers because the API, viewer, and tabs all assume one default context.
- Weaker isolation than separate Chrome processes.
- No upstream route exists today.

### D. Raw CDP multi-context client

- The API exposes the browser CDP on `CDP_DOMAIN` (`9223`) and the root WebSocket proxies to the browser.
- A custom client can call `Target.createBrowserContext`, `Target.createTarget`, and `Target.attachToTarget` directly.
- This creates isolated contexts and pages without the Steel session service.
- It bypasses the Steel API's session lifecycle, viewer, logs, and CLI.
- It is suitable only for a bespoke runner that already speaks CDP.

Assessment:

- Technically feasible.
- High custom code and no Steel support.
- Not a local stack solution for the existing CLI agents.

### E. Tabs in one session

- Native and already available: `steel browser tab new`, `tab list`, `tab switch`, `tab close`.
- Tabs are pages in the default browser context.
- They share cookies, storage, and login state.
- They are independent page states, not isolated sessions.

Assessment:

- Lowest deployment change.
- Highest application-level coordination cost: per-task tab lifecycle, active-tab races, shared auth state.
- Not a substitute for multi-agent isolation.

### F. Steel Cloud

- Official concurrency: 10 on Launch, 100 on Scale, 1,000+ on Enterprise.
- Each session is a separate cloud browser.
- No local Chrome, no local API pool, no fork.

Assessment:

- The managed solution.
- Cost, latency, and data placement differ from the local stack.
- The right fallback when local operations are not acceptable.

### G. Wait for or contribute upstream

The upstream direction is not multi-session yet.

- PR #375, "guard singleton ownership and cancel bounded launches", is open.
  It makes a second create return 409, a scoped release return 404 on a mismatch, and bounds launch/cleanup.
  It explicitly says it does not add multiple isolated browsers or scoped CDP/viewer endpoints.
  Source: [PR #375](https://github.com/steel-dev/steel-browser/pull/375), [SESSION_LIFECYCLE.md](https://github.com/xtianxian/steel-browser/blob/b761326ae01d1c0826de297eae65956fb274deeb/api/SESSION_LIFECYCLE.md).
- Issue #263, "Support more than one chrome process per container", is open since 2026-03-14.
  Its implementation idea is to force `shouldReuseInstance=false` so every start spawns a new Chrome.
  That alone does not add the session map or session-scoped routing.
  Source: [issue #263](https://github.com/steel-dev/steel-browser/issues/263).

The current upstream source still has the single `activeSession`.
No multi-session PR is merged.

## 4. Empirical checks on the deployed stack

The deployed API is the single-instance API at `192.33.91.87:3000`.

- Two sessions: start A, navigate A, start B, navigate A.
  A failed with `CDP error (Page.navigate): Session with given id not found`.
  B worked.
- Two tabs: start one session, open two tabs, navigate each, list and switch.
  Both tabs kept their own URL.
  The session stayed one.
- Two concurrent commands on one session: two `eval` calls both succeeded.
  Two concurrent navigations raced; one timed out and the final URL was `about:blank`.
- `GET /v1/sessions/:id` for a non-active id returned a synthetic `released` record.
- `POST /v1/sessions/:id/release` returned a different session id.
- The API's `/v1/sessions/:id/commands` route returned 404.
  The deployed API has the commands API disabled by default (`ENABLE_COMMANDS_API=false` in `api/.env.example`).

These checks confirm the source-level finding:
the local API is a single-active-session control plane, and tabs are pages in that one session.

## 5. Decision matrix

| Model | Isolation | Concurrency | Code change | Upstream | CLI compatibility | Ops cost | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| N single-instance API containers | Full, per browser | N | None | Official | Preserved | Medium: allocator, ports, reaper | **Recommended** |
| Browser-pool fork (PR #264/#416) | Full, per browser | N | Large fork | Unmerged | Unproven | High: fork maintenance | Pilot only |
| Multi-context fork | Cookies/storage, same Chrome | N | Medium | None | Needs new routes | Medium | Not supported |
| Raw CDP contexts | Cookies/storage, same Chrome | N | Custom client | None | None | High | Bespoke only |
| Tabs | None, shared context | Page-level | None | Native | Preserved | App-level coordination | Page-level only |
| Steel Cloud | Full, per browser | 10+ | None | Managed | Preserved | Cost and data placement | Fallback |
| Upstream wait | n/a | n/a | n/a | Not merged | n/a | Unknown | Not a solution now |

## 6. Recommendation

For the current eval stack, adopt **one single-instance Steel API container per agent**.

- It uses the official image and API.
- It avoids tabs, forks, and protocol changes.
- It gives full browser isolation.
- It fits a 16 GB host at three to five instances with a small allocator and a reaper (the eval server is one such host).
- Each agent's `STEEL_BROWSER_API_URL` points at its own instance.
  If one Kali container serves several agents, run one Kali per agent or add a per-agent Steel wrapper.
- Release the session after each task and reuse the container for the next task.

Do not use a second `POST /sessions` on one instance for parallel work.
It invalidates the first session.
Do not rely on the `/commands` per-tab selector in the deployed API.
It is disabled by default and the deployed route returns 404.

Use the browser-pool fork only if a single API endpoint is a hard requirement.
Pilot it with the pinned CLI and the session-scoped `connectUrl` before committing.
Treat the fork as a maintained product, not a drop-in image.

Use tabs only for page-level concurrency inside one agent.
They do not isolate cookies, storage, or crash domains.
