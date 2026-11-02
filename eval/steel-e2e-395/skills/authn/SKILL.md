---
name: authn
description: >-
  Browser-only fixture for the Steel session end-to-end run. Reuse the
  pre-authenticated Steel session wj-gateway-e2e, prove the authenticated
  context with the oracle at /api/authentication, assert it in the auth store,
  and never replay the login over HTTP.
metadata:
  version: '2.1.0'
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
   Re-run the oracle before recording or replaying, and never fall back silently to anonymous state.

## The authenticated-context oracle

The overview records `auth_probe: {url: /api/authentication}`.
The app resolves the path against the live project origin.
This is the ONLY pass/fail signal for the session:

- 2xx with no followed redirect: authenticated.
- 401, 403, or any 3xx (including a followed redirect): not authenticated.
- Anything else (network error, 5xx, other 4xx): indeterminate, which stops the run.

A 302 from `/api/authentication` to `/nowhere` is a 3xx and fails, even when the browser follows it and renders a page.
The login page is never the oracle.

Run the oracle in the live session:

```
steel browser eval "(async()=>{const r=await fetch('http://t-1618c524.target/api/authentication',{redirect:'follow',credentials:'include',cache:'no-store'});return {status:r.status,redirected:r.redirected,url:r.url}})()" --session wj-gateway-e2e --json
```

## Mode decision for this fixture

- The overview records `anti-bot: steel-e2e-browser-only-fixture` and `http-client-replayability: false`.
- The branch directive is therefore `browser_only`.
- Do not attempt a request replay.
- Do not start a new Steel session while `wj-gateway-e2e` is live.
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
   Reason: the operator owns `wj-gateway-e2e`.
   If the name is absent, go to the mint branch.
2. Run the oracle.
   Command: the `steel browser eval` fetch above, with the absolute URL read from `overview.auth_probe`.
   Reason: it answers 2xx only when the httpOnly `JSESSIONID` is accepted; 401, 403, or 3xx is not authenticated.
   Judge the `{status, redirected}` result, never the shell return code.
3. If the oracle passes, prove the fixture's administrator role.
   Command: `steel browser navigate http://t-1618c524.target/api/admin/role --wait-until domcontentloaded --session wj-gateway-e2e --json`, then `steel browser eval "document.body.innerText" --session wj-gateway-e2e --json`.
   Reason: the fixture expects the `sysAdmin` role with the `users_management` permission.
   This is an authorization check on top of authentication, not the oracle.
   A member session would receive an empty 200 body.
4. Assert the account in the store.
   Tool call: `auth_store` with `{"command": "write", "path": "accounts.admin-sessiononly-e2e.status", "value": "valid"}`.
   Reason: the store already holds the token and the snapshot.
   A root write to `accounts.admin-sessiononly-e2e` is a create and refuses a pre-seeded account with `duplicate_auth`.
   The leaf write merges and is the assertion the authn loop expects.
   Never rewrite the token value.
5. Run the outer skill-judging loop.
   Re-read this skill only if the turn produced a durable route, selector, runtime fact, or oracle correction.
   If a durable lesson exists, use `write_skill` with `{"skill": "authn", "target": "procedure", "content": "<the complete updated procedure>"}`.
   Otherwise skip the write.
   Never put a token, a cookie value, or a credential in the skill.
6. Emit the gateway verdict.
   The verdict must be `outcome: authenticated`, `account: admin-sessiononly-e2e`, and `branch: browser_only`.
   Leave `replayability_resolved` false because the overview already records the known `http-client-replayability: false`.
   The rationale must cite the oracle status and the `sysAdmin` role with the `users_management` permission.
   The rationale must not contain the token, a cookie value, or any credential.

## Mint branch (the session is gone)

The target has self-service sign-up.
The gateway may mint a NEW account; it never reads an existing secret.

1. If `wj-gateway-e2e` is absent, or the oracle returns 401, 403, or 3xx, do not start a replacement session.
2. Navigate to `http://t-1618c524.target/register` and register a new account with synthetic identity data (a fake email address and fake personal details).
   Use a fresh username and password that you generate.
3. Write the new account record with its `credentials` and `status: valid` through `auth_store` at `accounts.<new-account>`.
4. Re-run the oracle in the same live browser context.
   A 2xx with no followed redirect is the only success.
5. Emit `outcome: authenticated`, naming the new account.
   If sign-up fails or the oracle still fails, write `not_valid` when an account record exists, emit `outcome: failed`, and stop; never fail open.

## Failure branch

- If the tool returns `session_missing` or `unknown_session`, treat the designated session as absent: do not start a blank replacement, use the mint branch, and report the operator if minting fails.
- A `session_taken` response means the designated session is live: reuse it; never start a twin.
- If the oracle returns 401, 403, or 3xx, the session is not authenticated.
  Use the mint branch.
  Do not fall back to a request login.
- If the oracle is indeterminate (network error, 5xx, other 4xx), stop with `outcome: failed` and the evidence.
  Do not fail open.
- If the oracle passes but `/api/admin/role` is empty, the session is authenticated as a member.
  Report the role-gate evidence.
  Authentication succeeded; authorization did not.
- If the admin dashboard does not render, the browser path is broken, not the session.
  Capture the page URL and the snapshot, then emit `failed` with the browser evidence.
- The operator owns the session lifecycle.
  Do not run `steel browser stop --session wj-gateway-e2e`.
  The next scenario reuses the same session.
