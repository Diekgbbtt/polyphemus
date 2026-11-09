---
name: authn
description: Use when authenticating to the siyucms target (SIYUCMS 6.1.8, ThinkPHP 6 + AdminLTE) - replay the admin sign-in form with a plain HTTP client to mint an admin PHPSESSID session, mint a member session and a JSON-API JWT through the CSRF-free api routes, and verify each authenticated landing. The sign-in procedures are request-replayable; the auth gateway mounts the one browser tool to validate the oracle and persist the decoupled browser context.
metadata:
  version: '1.1'
---

# Browser session

The auth gateway and the deterministic crawl mount the account's decoupled
browser context through the one `browser` tool.
The context reference is `accounts.<account>.browser_context.ref`; the pool
store holds the state, and the auth store holds only the reference.
Never start a raw Steel session, pass a session name, or mount a profile.
The session key is ephemeral and derived by the tool binding.

To establish or refresh the context:

1. `browser(command="start", account=<account>)` mounts the stored context.
2. Run the sign-in procedure below through `browser(command="exec", ...)` when
   the oracle fails.
3. Validate the selected account's `auth_probe` (or its `root_url` when the probe is empty) in
   the mounted browser. A 2xx with `redirected: false` passes; a 401, 403, or
   any 3xx fails.
4. `browser(command="end", persist_context=true)` captures, saves, stops, and
   releases the session.

The bootstrap procedures below are the operator's record.
The crawl mounts the restored context and never replays them.

# SIYUCMS project authentication skill

Target identity: SIYUCMS 6.1.8 (ThinkPHP 6 with the AdminLTE backend theme), Apache/2.4.52 (Debian) with PHP/7.3.33, reached at the target root (`<target-root>` on this run).
Store facts live in the AuthContext (`auth/overview.yaml`, `auth/credentials.yaml`); this file holds only the replayable steps.
Accounts: `admin-first_authn_bootstrap` (token `PHPSESSID`, backend role super_administrator) and `siyuprobe2026-first_authn_bootstrap` (token `jwt`, front-end member session plus API token).
Sign-in is request-based on all three surfaces: a plain HTTP client reaches the authenticated state. The auth gateway still mounts the one browser tool to validate the recorded oracle and persist the decoupled browser context; the sign-in procedure itself needs no browser.

```markdown
## Anti-bot posture and HTTP-client replayability (mandatory, target-agnostic)

Whatever the target, establish and record these two facts before you record its authentication state.

1. Probe request-side first. Using your own request tooling against the target, send the shape a plain client would send (no browser) to the sign-in endpoint or to any authenticated area named in the overview, applying the account's cookies, tokens, and snapshot exactly as recorded. Inspect status, headers, body, and challenge markers.
2. Classify the response, distinguishing three signals. An authentication failure is a 401, or a 403 whose body and headers show an application-level denial. A rate limit is typically a 429 or a documented retry signal. A WAF or anti-bot block is a 403 (or a 200 interstitial) carrying block-page fingerprints, a JS-challenge script, or bot-management cookies. Never collapse these into one another; record the evidence that forced the call.
3. Name the defence. If a WAF or anti-bot defence is present, name its type as precisely as the evidence allows (for example `akamai_v3`, `cf_clearance`, `datadome`, `incapsula`, a named challenge, or `waf:<name>`). Research unfamiliar block patterns (vendor block pages, challenge scripts, characteristic cookies) before naming them. If no defence signal appears, the type is null.
4. Replay the trusted context surgically. When a browser session holds the trusted context, attempt to reproduce it with a plain HTTP client. Start from the overview's `required_headers` (the single source of the required header fact), the account `snapshot` (cookies, params) and the stored tokens with their locations. Identify line by line what carries the trust: header set and order, cookies, token values and locations, user-agent and client hints, query and body parameters, request and network parameters you control, and TLS/HTTP signature specifics where your tooling lets you control them. Change one variable at a time and read the response; iterate until the replay reaches the authenticated state or you can name what blocks it.
5. Record the verdict honestly. When a plain-client replay reaches the authenticated state, record `http-client-replayability: true` and record which shape elements are static (replayable as-is) and which are dynamic (must be re-minted or are browser-bound): the continuation facts a follower needs. When replay cannot reach the authenticated state, record `http-client-replayability: false`; browser-only is a complete, honest result, never a failure.
6. Script-driven logins. When the sign-in is programmed by client-side script, fetch and read the script; replay the exact request shape it builds (endpoints, headers, nonces, parameter order); where the script derives values dynamically (nonces, signatures, fingerprints), say so and treat those parts as browser-bound.
7. Re-verify stale state. Treat an expired or missing session or profile as a loud failure. Re-run the verification predicate before recording or replaying; never fall back silently to anonymous state.
8. Persist through the operator seed face. Write both facts into the overview with `PUT /projects/{project_id}/auth`. A present `overview` section replaces wholesale, so read `GET /projects/{project_id}/auth` first and send the merged overview. A shape violation returns 400 `{ok: false, error: "auth_invalid", detail}` and lands nothing. This seed face is your write path: the in-process agent store tool is the in-system agents' path (their writes merge into the same overview, D220-12), so never use it here and never put `origin` in the payload.

Two rules bind every target: facts live in the store, steps live in the skill; secret values stay in the store, the skill cites names only.
```

## Mode decision (consumed from the store, never restated as new fact)

- `anti-bot: null`, `http-client-replayability: true` (overview).
- Forcing evidence, from the bootstrap probes: every response carries only `Server: Apache/2.4.52 (Debian)` and `X-Powered-By: PHP/7.3.33` - no CDN header, no block-page fingerprint, no JS-challenge script and no bot-management cookie. A rejected admin sign-in is HTTP 200 with the JSON body `{"error":"1","msg":"帐号或密码错误"}`, and a sign-in POST without `__token__` (or with a foreign token) is HTTP 200 with `{"error":"2","msg":"验证有误"}`; an unauthenticated backend request is HTTP 302 to the login page. None of those is a 401, a 403 block page or a 429, so no `waf_protected`, `waf_detection` or `rate_limited` signal fired. Ten rapid unauthenticated backend GETs and five rapid wrong-password POSTs produced identical application responses with no retry header and no challenge.
- Consequence: every sign-in procedure below runs on the request path. The gateway oracle validation and context persistence use the one browser tool; the sign-in itself needs no browser.

## Roles and featured roots

The auth store is the session catalogue: one account is one browser session.
The crawl runs one lifecycle per valid account, in parallel up to the pool
size, and each lifecycle starts at that session's `root_url`.

- `super_administrator` (account `admin-first_authn_bootstrap`): the backend
  console. The featured root and the oracle are
  `/index.php/admin/Index/index.html`. Procedure: `sign-in-admin-backend`.
- `member` (account `siyuprobe2026-first_authn_bootstrap`): the front-end
  member centre. The featured root and the oracle are
  `/index.php/index/user/index.html`. Procedures: `sign-in-member` and
  `sign-up-member`.
- An account with no `role` starts at `/`. An account with no `auth_probe`
  uses its root URL as the oracle; the preflight accepts any non-4xx, non-3xx
  response there.

## Procedure: sign-in-admin-backend (verified)

Run every step with a plain HTTP client (curl), because no blocking defence was observed on the sign-in flow (mode decision above).
Account: `admin-first_authn_bootstrap`. Secret names used: `credentials.username`, `credentials.password` (values live only in the store).

1. Open a session and read the login form. Tool: `curl` against `overview.login_endpoint`'s page `/index.php/admin/Login/index.html`. Reason: ThinkPHP binds the CSRF `__token__` to the anonymous session, so the cookie jar and the token must come from the same session, and the token is single use.
   - `curl -sS -c jar.txt -o login.html "$BASE/index.php/admin/Login/index.html"`
   - `references/admin-signin-replay.sh` (this bundle) wraps steps 1-4; it reads the secret values from the environment, never from this file.
2. Extract the hidden `__token__` value (32 hex characters) and confirm the form carries no `vercode` field. Tool: a text reader over `login.html`. Reason: the POST is refused without the session-bound token (see `overview.technical_conditions.admin_csrf_token_required`), and a rendered `vercode` input means tp_system.code was switched to 1, which captcha-gates the flow.
3. POST the form. Tool: `curl` with `Content-Type: application/x-www-form-urlencoded` (the overview's `required_headers`) against `/index.php/admin/Login/checkLogin.html` (the extensionless `/index.php/admin/Login/checkLogin` is the same route). Reason: the mechanism is a plain HTML form POST built by page script from the visible inputs; no value is derived client-side beyond copying `__token__`.
   - `curl -sS -b jar.txt -c jar.txt -X POST "$BASE/index.php/admin/Login/checkLogin.html" --data-urlencode "username=$SIYUCMS_ADMIN_USERNAME" --data-urlencode "password=$SIYUCMS_ADMIN_PASSWORD" --data-urlencode "__token__=$TOK"`
   - Success is HTTP 200 with `{"error":"0","href":"\/index.php\/admin\/Index\/index.html","msg":"登录成功"}` plus a `Set-Cookie` carrying the ROTATED `PHPSESSID` (ThinkPHP regenerates the session id on a successful admin sign-in, so the pre-login value no longer works).
4. Verify the authenticated landing, before recording anything. Tool: `curl` with the new cookie jar against an authenticated page. Reason: the P3 predicate is a non-login landing, and the sign-in JSON alone is not proof of authentication.
   - `curl -sS -b jar.txt -o land.html -w '%{http_code}\n' "$BASE/index.php/admin/Index/index.html"` must print 200, `land.html` must carry `<title>SIYUCMS | 控制台</title>`, and the same URL without the cookie must print 302 with `Location: /index.php/admin/Login/index.html`.
   - If the predicate does not fire, treat the session as a loud failure and stop; never continue into an anonymous crawl. Go to the failure branch below.
5. Persist the session. Tool: the AuthContext store (`auth/credentials.yaml`). Reason: the L1 crawl replays this snapshot instead of re-running sign-in. Record the rotated value under `tokens.PHPSESSID` (location `cookie`, target `/`), the same value in `snapshot.cookies`, and a fresh `snapshot.captured_at`. `snapshot.headers` records only the user agent that was sent, because `required_headers` names only the login POST's content type.

The web UI equivalent, for a human operator only: open `/index.php/admin/Login/index.html`, submit the username and password; the page posts the same form by AJAX and the browser follows `href` to the console.

## Procedure: sign-in-member (verified)

Run every step with a plain HTTP client (curl), because no blocking defence was observed.
Account: `siyuprobe2026-first_authn_bootstrap`. Secret names used: `credentials.username`, `credentials.password`, `tokens.jwt`.

1. Sign in through the api route to mint the token. Tool: `curl` against `/index.php/api/User/login` (POST, form-encoded `username`, `password`). Reason: the api app has no CSRF middleware on its login or register routes, so no token has to be read first; `username` matches the member's email or mobile.
   - `curl -sS -X POST "$BASE/index.php/api/User/login" --data-urlencode "username=$SIYUCMS_MEMBER_USERNAME" --data-urlencode "password=$SIYUCMS_MEMBER_PASSWORD"`
   - Success is HTTP 200 with `{"code":1,"msg":"登录成功","data":{"token":"<jwt>"}}`; a wrong credential answers `{"code":0,"msg":"帐号或密码错误"}`.
   - `references/member-signin-api.sh` (this bundle) wraps steps 1-2.
2. Verify the token against an authenticated api route. Tool: `curl` with the token in the `token` request header (the location recorded in `tokens.jwt`). Reason: the api middleware reads only that header; a body or cookie carrier is ignored.
   - `curl -sS -X POST "$BASE/index.php/api/User/index" -H "token: $JWT"` must print HTTP 200 with `{"code":1,...,"data":{"id":...,"email":"<member email>"}}`; without the header the same call prints `{"code":0,"msg":"token不能为空"}` and with a tampered token `{"code":0,"msg":"token已过期"}`.
3. Sign in through the front-end route to mint the member session. Tool: `curl` against `/index.php/index/user/login.html` (POST, form-encoded `username`, `password`). Reason: the member centre (`/index.php/index/user/index.html`) is session-gated separately from the api token, and this route needs no CSRF token and no captcha when tp_system.message_code is 0.
   - `curl -sS -c jar.txt -o /dev/null "$BASE/index.php/index/user/login.html"` then `curl -sS -b jar.txt -c jar.txt -X POST "$BASE/index.php/index/user/login.html" --data-urlencode "username=$SIYUCMS_MEMBER_USERNAME" --data-urlencode "password=$SIYUCMS_MEMBER_PASSWORD"`
   - Success is HTTP 200 whose page title is "跳转提示" with `<h1>登录成功</h1>` plus a `Set-Cookie` carrying the member `PHPSESSID`.
   - `references/member-signin-web.sh` (this bundle) wraps steps 3-4.
4. Verify the authenticated landing, before recording anything. Tool: `curl` with the member cookie jar. Reason: the P3 predicate is a non-login landing.
   - `curl -sS -b jar.txt -o ucenter.html -w '%{http_code}\n' "$BASE/index.php/index/user/index.html"` must print 200 and `ucenter.html` must carry the member email; without the cookie the same URL must print 302 with `Location: /index.php/index/user/login`.
5. Persist both sessions. Tool: the AuthContext store (`auth/credentials.yaml`). Reason: the L1 crawl replays them. Record the JWT under `tokens.jwt` (location `header`, target `POST /index.php/api/User/index`, `expiry` from the token's `exp` claim), the member `PHPSESSID` in `snapshot.cookies`, and a fresh `snapshot.captured_at`.

## Procedure: sign-up-member (verified)

The api register route is open, CSRF-free and captcha-free, so a plain HTTP client mints a member account end to end.
1. Register the account. Tool: `curl` against `/index.php/api/User/register` (POST, form-encoded `email`, `password`, optional `sex`). Reason: `register` is on the api middleware's `except` list, so it needs no token.
   - `curl -sS -X POST "$BASE/index.php/api/User/register" --data-urlencode "email=$SIYUCMS_MEMBER_USERNAME" --data-urlencode "password=$SIYUCMS_MEMBER_PASSWORD"`
   - Success is HTTP 200 with `{"code":1,"msg":"注册成功"}`; constraints enforced by the app are a password of at least six characters and a syntactically valid email (a duplicate email answers `{"code":0,"msg":"邮箱已被注册"}`).
   - `references/member-signup-api.sh` (this bundle) wraps steps 1-3.
2. Sign in with the new credentials. Tool: `curl`, replaying step 1 of `sign-in-member`. Reason: the P3 predicate for a minted account is a fresh session/token plus a non-login landing.
3. Verify and record. Tool: `curl` (P3 predicate of `sign-in-member`) then the AuthContext store. Reason: an unverified flow never yields a verdict. Record `credentials` (username, password, login_url, selectors), `tokens`, `snapshot`, and `procedure: sign-up-member`.

New accounts are minted with synthetic identity data - a fake email address and fake personal details - never real personal data; the exact values used are recorded in the account's `credentials`.
The admin backend has no self-service sign-up at all: `tp_admin` rows are provisioned from the operators' database seed or created by an already-authenticated administrator through `Admin/add` in the backend, so there is no separate admin sign-up procedure to replay.

## Static and dynamic continuation facts (P1 step 5)

Static elements, replayable as-is:

- the admin sign-in page `/index.php/admin/Login/index.html`, the POST endpoint `/index.php/admin/Login/checkLogin.html` (also reachable as `/index.php/admin/Login/checkLogin`), the POST method and the `Content-Type: application/x-www-form-urlencoded` header (the overview's `required_headers`);
- the admin form field names `username`, `password`, `__token__`, and the absence of `vercode` while tp_system.code is 0;
- the api endpoints `/index.php/api/User/login`, `/index.php/api/User/register` and `/index.php/api/User/index`, their form-encoded parameter names, and the `token` request-header carrier for the JWT (the location recorded in `tokens.jwt`);
- the front-end member endpoints `/index.php/index/user/login.html` and `/index.php/index/user/index.html` with the field names `username`, `password` and the cookie name `PHPSESSID`;
- the cookie name `PHPSESSID` and the recorded values in `tokens.PHPSESSID` / `snapshot.cookies` - a plain client replays the cookie as the sole `Cookie` header, with no user-agent or client hints required (the default curl user agent was accepted);
- the authenticated landing markers: `<title>SIYUCMS | 控制台</title>` for the backend, the member email in the member centre, and `{"code":1}` from `/index.php/api/User/index`.

Dynamic elements (must be re-minted, or are browser-bound):

- the admin `__token__` is minted per anonymous session by the login page GET and is single use; it must be read from the same session that issues the POST (`overview.technical_conditions.admin_csrf_token_required`), and a foreign or stale value answers `{"error":"2","msg":"验证有误"}`;
- the admin `PHPSESSID` rotates on a successful sign-in, so only the post-login value authenticates;
- the member JWT is HS256 with a 3600 s `exp`; it must be re-minted by `sign-in-member` step 1 when stale (`{"code":0,"msg":"token已过期"}`);
- the member `PHPSESSID` is a server-side file session with a 1440 s expire (config/session.php), so the snapshot goes stale after about 24 minutes of inactivity;
- nothing in this target's flows is browser-bound: no client-side-script nonce, signature or fingerprint was observed on any of the three sign-in surfaces.

## Failure branch (diagnostic ladder from the store)

Run the `overview.technical_conditions` checks in order when sign-in or replay misbehaves:

1. `service_reachable` - no HTTP response at all means the deployment, not the credentials, is the problem.
2. `admin_session_replay` / `member_session_replay` / `member_jwt_valid` - replay the stored snapshot first. HTTP 200 with the landing marker means the session is live; a 302 to the login page, or `token已过期`, means the snapshot is stale (never crawl anonymously) and the matching sign-in procedure must re-mint it.
3. `admin_login_surface` then `admin_csrf_token_required` - if the fresh login page carries no `__token__`, or the POST answers `{"error":"2","msg":"验证有误"}`, the token was fetched from a different session or reused; re-fetch the form and retry inside one session. If the page renders a `vercode` input, tp_system.code is 1 and the flow is captcha-gated: that is a configuration change, not a block.
4. `bad_credentials_denied` - `{"error":"1","msg":"帐号或密码错误"}` means the recorded credential is wrong, not that the target is blocked; `用户已被禁用!` means that admin row's status is 0.
5. `member_registration_open` - a register call answering `邮箱已被注册` means the account already exists and only the sign-in step is needed.
6. `no_throttle_or_block_signal` - if a 429, a retry header or a block-page fingerprint ever appears, stop and re-run P1: this target has no WAF, no anti-bot and no throttle at bootstrap time, so a block signal means the environment changed.
7. `session_lifetime` - if everything above is healthy but replay suddenly fails, wait past the session window and re-run the sign-in procedure; never fall back to anonymous crawling.
