# Steel: concurrent sessions versus concurrent tabs

Date: 2026-11-03.
Question: can the self-hosted Steel runtime run multiple sessions concurrently on one browser instance, and is there a native feature or a session-characterization trick that enables it?
Short answer: no for multiple sessions; yes for multiple tabs.
The tabs are pages in one browser context.
They are not isolated sessions.

## Sources

The source is `steel-dev/steel-browser` at commit `9fb9b9239325794b3e2d2a56c7e54c400a7d30bd` (2026-10-31).
The deployed API identifies itself as version `0.0.1`.
The deployed CLI is `0.5.0-preview.6` in the Kali container.

- API title and description: [`api/src/plugins/schemas.ts`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/plugins/schemas.ts#L39-L48).
  It says "Steel Browser Instance API" and "Documentation for controlling a single instance of Steel Browser".
- Session state: [`api/src/services/session.service.ts`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/session.service.ts#L67).
  The service has one `activeSession` and a `pastSessions` list.
- Session start: [`session.service.ts#L93-L121`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/session.service.ts#L93-L121).
  `startSession` calls `resetSessionInfo` before launching the browser.
- Session reset: [`session.service.ts#L314-L334`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/session.service.ts#L314-L334).
  `resetSessionInfo` completes the current session and replaces `activeSession`.
- Session end: [`session.service.ts#L278-L312`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/session.service.ts#L278-L312).
  The released session moves to `pastSessions`, and a new idle session is created.
- Unknown session id: [`sessions.controller.ts#L91-L126`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/modules/sessions/sessions.controller.ts#L91-L126).
  Any id other than `activeSession.id` returns a synthetic `released` record with `duration: 0` and an empty user agent.
- Release endpoint: [`sessions.controller.ts#L67-L80`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/modules/sessions/sessions.controller.ts#L67-L80).
  It calls `endSession()` and ignores the `sessionId` path parameter.
- Browser launch reuse and replacement: [`cdp.service.ts#L688-L780`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/cdp/cdp.service.ts#L688-L780).
  A similar config reuses the browser and refreshes the primary page.
  A different config closes the existing browser before launching a new one.
- Tabs: [`api/src/services/commands/tabs.ts#L555-L790`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/commands/tabs.ts#L555-L790).
  `TabRegistry.create` calls `browser.newPage()`.
  Tabs are named `t1`, `t2`, and so on.
  The registry tracks only pages in the default browser context.
- Per-command tab selector: [`api/src/services/commands/commands.ts#L6-L9`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/services/commands/commands.ts#L6-L9) and the `tab` fields on `navigate` and `eval` at lines 59 and 147.
  The selector is a tab id matching `^t\d+$`.
- Tab viewer: [`sessions.controller.ts#L142-L167`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/modules/sessions/sessions.controller.ts#L142-L167).
  The viewer accepts `pageId` or `pageIndex`.
- Live pages: [`sessions.controller.ts#L169-L235`](https://github.com/steel-dev/steel-browser/blob/9fb9b9239325794b3e2d2a56c7e54c400a7d30bd/api/src/modules/sessions/sessions.controller.ts#L169-L235).
  The endpoint returns `pages` with page ids, URLs, and titles.

## What the code says

The self-hosted API is a single-instance control plane.

`SessionService` holds one `activeSession`.
`startSession` calls `resetSessionInfo`, which completes the current session and replaces the active one.
The new session may reuse the existing browser when the launch config is similar.
Otherwise it closes the browser and launches a new one.
Either way, the previous session is no longer active.

`GET /v1/sessions/:id` does not look up a live session by id.
It compares the id to `activeSession.id`.
Any other id gets a synthetic `released` record.
`POST /v1/sessions/:id/release` releases the active session and ignores the id.
The `GET /v1/sessions` list is `[activeSession, ...pastSessions]`.

The `CreateSession` fields do not provide a concurrent session selector.
`sessionId` labels the one active session.
`sessionContext` injects cookies and localStorage into the primary page.
`extra` is metadata.
`persist` and `userDataDir` choose a Chrome profile.
`isSelenium` switches the browser mode.
None of them creates a second concurrent session.

The API does expose a `createBrowserContext` method, but no route or CLI command calls it.
The tabs are created with `browser.newPage()` in the default browser context.
They share cookies, localStorage, and session state.

The native concurrency feature is tabs.

The CLI exposes `steel browser tab new`, `tab list`, `tab switch`, and `tab close`.
The API source also supports a per-command `tab` field (`t1`, `t2`, ...) on `navigate`, `eval`, and other commands.
This selector addresses a tab directly instead of switching the global active tab.
The deployed API version `0.0.1` does not expose the `/v1/sessions/:id/commands` route: a live request returned 404.
So the deployed path is the CLI `tab` family, not the API command selector.

## Empirical checks on the deployed stack

All checks used the Kali container and the local API at `192.33.91.87:3000`.
No session was left running.

Single session and tabs:

- `steel browser start --session tab-test` succeeded.
- `steel browser tab new` opened a tab.
- `navigate https://example.com` in tab 1 succeeded.
- `tab new` plus `navigate https://example.org` in tab 2 succeeded.
- `tab list` showed the default blank tab, the example.com tab, and the example.org tab.
- `tab switch 1` followed by `eval location.href` returned `https://example.com/`.
- `tab switch 2` followed by `eval location.href` returned `https://example.org/`.

Two sessions:

- Start session A and navigate A: success.
- Start session B: success.
- Navigate A after B started: `CDP error (Page.navigate): Session with given id not found.`
- Navigate B: success.
- The CLI catalogue still listed both as live.
- The API list showed the active session and released or ghost records.

Same session, two clients:

- Two concurrent `steel browser eval` calls on the same session returned `2` and `4`.
- Steel did not refuse concurrent clients on one session.
- Two concurrent navigations on the same session raced.
- One navigation succeeded, one timed out, and the final URL was `about:blank`.

The session is shareable, but it is a shared mutable browser context.
The tabs are independent page states, but they share the browser context.

## Verdict

- Multiple sessions on one API instance: not supported.
  `POST /sessions` replaces the active session.
  The `sessionId` is not a routing key.
- Multiple tabs on one session: native and supported.
  Use `steel browser tab new`, `tab list`, `tab switch`, and `tab close`.
  The tabs are pages in one default browser context.
- Isolated contexts: not exposed.
  `createBrowserContext` exists internally but has no route or CLI.
  Tabs share cookies and storage.
- Session characterization trick: none in the deployed API.
  The source's per-command `tab` selector is the closest feature, but the deployed API `0.0.1` lacks the commands route.
- The sibling risk is state interference, not a singleton refusal.
  Concurrent clients on one session are accepted.
  Concurrent mutations race.
  Concurrent tabs avoid page-state races but not cookie or storage races.
- True isolated concurrency still requires one API instance per browser or the cloud API.

## Practical guidance

- For parallel work in one instance, open one tab per task and keep one session.
  `steel browser tab new <url>`, then `tab list` and `tab switch`.
- Do not create a second session for parallel work.
  It invalidates the first session's CDP target.
- Do not share a session between jobs that mutate the same page state.
  The last navigation or form submission wins.
- For cookie isolation, use separate API instances or the cloud.
  A second `POST /sessions` on the same API is a replacement, not a parallel context.
