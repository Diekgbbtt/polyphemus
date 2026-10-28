---
name: authn
description: >-
  Browser-only fixture for the Steel session end-to-end run. Reuse the
  pre-authenticated Steel session wj-gateway-e2e, prove the administrator
  session through the browser, assert it in the auth store, and never replay
  the login over HTTP.
metadata:
  version: '2.0.0'
---

# White Jotter authentication skill - browser-only fixture

This scenario skill is a deliberate overlay for the Steel session end-to-end run.
The target is actually request-replayable, but the operator sets `anti-bot` truthy and `http-client-replayability` false to force the browser-only branch.
The overlay is test configuration, not a target fact.
The live Steel session `wj-gateway-e2e` holds the pre-authenticated administrator browser context.
The account `admin-sessiononly-e2e` stores only that session: a `JSESSIONID` token and a cookie snapshot.
It stores no credentials and no roles.

## Accounts

- `admin-sessiononly-e2e` - the selected account.
  It has `tokens.JSESSIONID` in `location: cookie` and a `snapshot` with the `JSESSIONID` and `rememberMe` cookies.
  It has no `credentials` and no `roles`.
  Its `status` is absent until this turn asserts it.

## Anti-bot posture (mandatory, target-agnostic)

1. Probe request-side first.
   Send the shape a plain client would send to the sign-in endpoint or to an authenticated area named in the overview, applying the account's cookies, tokens, and snapshot exactly as recorded.
2. Classify the response.
   Distinguish an authentication failure (401, or an application-level 403), a rate limit (429 or a documented retry signal), and a WAF or anti-bot block (403 or a 200 interstitial carrying block-page fingerprints, a JS challenge, or a bot-management cookie).
   Never collapse these into one another.
3. Name the defence.
   If a WAF or anti-bot defence is present, name its type as precisely as the evidence allows.
   If no defence signal appears, the type is null.
4. Replay the trusted context surgically.
   When a browser session holds the trusted context, attempt to reproduce it with a plain HTTP client.
   Change one variable at a time and read the response.
5. Record the verdict honestly.
   When a plain-client replay reaches the authenticated state, record `http-client-replayability: true`.
   When replay cannot reach the authenticated state, record `http-client-replayability: false`; browser-only is a complete, honest result, never a failure.
6. Re-verify stale state.
   Treat an expired or missing session as a loud failure.
   Re-run the verification predicate before recording or replaying, and never fall back silently to anonymous state.

## Mode decision for this fixture

- The overview records `anti-bot: steel-e2e-browser-only-fixture` and `http-client-replayability: false`.
- The branch directive is therefore `browser_only`.
- Do not attempt a request replay.
- Do not start a new Steel session.
- Reuse `wj-gateway-e2e` exactly as the operator created it.
- The hash forms `/#/login` and `/#/register` are wrong for this SPA because the Vue router runs in history mode.
  The real paths are `/login` and `/register`.
  A navigation to `/#/login` loads `/index#/login` and renders the public index page, not the login form.
- Do not use `alert` or any other blocking JavaScript dialog.
  The runtime does not dismiss it, so the page and every later command time out.
- Do not use `wait --load-state` after a page is loaded.
  The runtime waits for a fresh `Page.loadEventFired` event and returns `1` with `Timeout waiting for Page.loadEventFired`.
  Use `wait --selector` or `wait --text` when a wait is needed.

## Procedure: browser-session-reuse (verified)

1. Confirm the live session catalogue.
   Command: `steel browser sessions --json`.
   Reason: the operator owns `wj-gateway-e2e`; if the name is absent, the fixture cannot mint a new session because the account has no credentials.
   On absence, skip to the failure branch.
2. Reattach to the authenticated admin surface.
   Command: `steel browser navigate http://t-1618c524.target/admin/dashboard --wait-until domcontentloaded --session wj-gateway-e2e --json`.
   Then run `steel browser snapshot -i --session wj-gateway-e2e --json`.
   Reason: the admin dashboard proves that the browser session reached the application, while the API probes below prove that the server accepted its httpOnly cookie.
3. Prove the live server session.
   Command: `steel browser navigate http://t-1618c524.target/api/authentication --wait-until domcontentloaded --session wj-gateway-e2e --json`.
   Then run `steel browser eval "document.body.innerText" --session wj-gateway-e2e --json`.
   Reason: `GET /api/authentication` answers `身份认证成功` only when the httpOnly `JSESSIONID` is sent and valid.
   An unauthenticated or stale request answers `302` with `Location: /nowhere`.
4. Probe the privileged feature.
   Command: `steel browser navigate http://t-1618c524.target/api/admin/role --wait-until domcontentloaded --session wj-gateway-e2e --json`.
   Then run `steel browser eval "document.body.innerText" --session wj-gateway-e2e --json`.
   Reason: the response must carry `code: 200` and the `sysAdmin` role with the `users_management` permission.
   The member session would receive an empty `200` body.
5. Assert the account in the store.
   Tool call: `auth_store` with `{"command": "write", "path": "accounts.admin-sessiononly-e2e.status", "value": "valid"}`.
   Reason: the store already holds the token and the snapshot.
   A root write to `accounts.admin-sessiononly-e2e` is a create and refuses a pre-seeded account with `duplicate_auth`.
   The leaf write merges and is the assertion the authn loop expects.
   Never rewrite the token value.
6. Run the outer skill-judging loop.
   Re-read this skill only if the turn produced a durable route, selector, or runtime fact.
   If a durable lesson exists, use `write_skill` with `{"skill": "authn", "target": "procedure", "content": "<the complete updated procedure>"}`.
   Otherwise skip the write.
   Never put a token, a cookie value, or a credential in the skill.
7. Emit the gateway verdict.
   The verdict must be `outcome: authenticated`, `account: admin-sessiononly-e2e`, and `branch: browser_only`.
   Leave `replayability_resolved` false because the overview already records the known `http-client-replayability: false`.
   The rationale must cite the `身份认证成功` marker and the `sysAdmin` role with the `users_management` permission.
   The rationale must not contain the token, a cookie value, or any credential.

## Failure branch

- If `wj-gateway-e2e` is absent from `sessions --json`, do not start a replacement.
  Write `accounts.admin-sessiononly-e2e.status` as `not_valid`, emit `outcome: failed`, and report that the operator must re-mint the session.
- If `/api/authentication` answers `302 /nowhere`, the server session is stale or absent.
  Do not fall back to a request login.
  Write `not_valid`, emit `failed`, and report that the operator must re-mint the session.
- If `/api/admin/role` returns an empty body while `/api/authentication` succeeds, the session is valid but the account lacks the administrator role.
  Do not retry the login.
  Emit `failed` with the role-gate evidence.
- If the admin dashboard does not render, the browser path is broken, not the session.
  Capture the page URL and the snapshot, then emit `failed` with the browser evidence.
- The operator owns the session lifecycle.
  Do not run `steel browser stop --session wj-gateway-e2e`.
  The next scenario reuses the same session.
