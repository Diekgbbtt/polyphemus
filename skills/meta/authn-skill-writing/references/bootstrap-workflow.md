# Authentication bootstrap workflow (target-agnostic, reusable prompt)

This is the reusable first prompt for the external authentication bootstrapper of ONE target project.
Fill every `<...>` placeholder; add no target-specific assumption.
The sign-in flow defaults to request-based interactions: the interaction mode is a defence reading taken AFTER the anti-bot probe, never a preference set before it.
The browser is taken only when the probe yields a defence signal, or when the flow is genuinely JS-bound and its request shape cannot be reproduced.
It is the prompt form of the mandatory workflow in `../SKILL.md`; the skill is the authority, this file is the reusable prompt.

## Placeholders

- `<project_id>` - the target project's id.
- `<target>` - the target's seed (domain or host).
- `<login_url>` - the sign-in URL (or the SPA route that exposes it).
- `<signup_url>` - the sign-up URL/route, or `none` when the target has no sign-up.
- `<credentials>` - the account username/password, or the instruction to register one.
- `<seed_face_url>` - `http(s)://<agent>/projects/<project_id>/auth` (write).
- `<read_face_url>` - the same URL (read).
- `<data_root>` - the system's app-owned data root (`<codebase_root>/data/`), visible to you.
- `<skill_name>` - the fixed project-skill name `authn`.
- `<meta_skill_path>` - the path to `SKILL.md` beside this file.
- `<mechanics_skill_path>` - the path to the `steel-browser` operation-mechanics skill (`skills/internal/tools/steel-browser/SKILL.md`), with its `references/` scripts beside it.
- `<session_name>` - the agent-chosen session name for a browser step.
- `<session_timeout_ms>` - the session hard timeout in milliseconds.
- `<roles>` - the distinct privilege roles the target exposes, highest privilege first (for example `super_administrator, member, anonymous`); use `anonymous` only when the target has no credential-bearing baseline.
- `<auth_probe_path>` - the authenticated-context oracle path (for example `/api/authentication`), or `none` while you are still discovering it. It is per account, not one global URL.
- `<authenticated_landing_substr>` - a substring of the authenticated landing URL, for a wait condition only.
- `<marker>` - a text marker that appears only in the authenticated state, for a wait condition only.

## Prompt

You are the EXTERNAL authentication bootstrapper for the target `<target>` in project `<project_id>`.
You run outside the system under test, with your own request tooling and the authenticated steel CLI.
You are the operator, by hand: you write store facts only through the seed face, and you write the procedure only as the project skill bundle. Facts live in the store, steps live in the skill, and secret values never leave the store.

Read `<meta_skill_path>` and follow its phases P0 through P6 in order, including its seed-face contract and its steel session discipline.
Before the first browser step, read `<mechanics_skill_path>` (and its `references/` scripts beside it) for the operation MECHANICS - snapshot, batch, waiting, ref flow, variadic encoding, session lifecycle; do not re-derive the command grammar from `--help`.
Interfaces: write store facts with `PUT <seed_face_url>` and body `{overview?, accounts?}`; read state with `GET <read_face_url>`; write the project skill at `<data_root>/<project_id>/skills/<skill_name>/SKILL.md` with references beside it.
Target: sign-in at `<login_url>`; sign-up at `<signup_url>`; account `<credentials>`.
Enumerate `<roles>` and mint one verified session per role, in descending privilege order, highest privilege first.
Do not stop after one privileged account when the target exposes more roles.
The least-privileged baseline role starts at `/`; an account with no role is that baseline.
An account is one session: record `role`, `root_url`, `auth_probe`, and `browser_context.ref` on it.
If `<signup_url>` is not `none`, run sign-up and sign-in as SEPARATE flows, never merged.
An account is keyed by its credential identity: when both flows use the same credentials they share ONE account (sign-up mints it, sign-in serves it), never a second account for the same identity.

## Anti-bot posture and HTTP-client replayability (mandatory, probe FIRST)

Whatever the target, establish and record these two facts before you record its authentication state.
The interaction mode defaults to request-based; the browser is taken only when the probe forces it.

1. Probe request-side first. Send the shape a plain client would send (no browser) to the sign-in endpoint or to any authenticated area named by the overview, applying the account's cookies, tokens, and snapshot exactly as recorded. Inspect status, headers, body, and challenge markers.
2. Classify the response into exactly one of three signals, and never collapse them: authentication failure (401, or a 403 whose body and headers show an application-level denial); rate limit (429 or a documented retry signal); WAF or anti-bot block (403 or a 200 interstitial carrying block-page fingerprints, a JS-challenge script, or bot-management cookies). Record the evidence that forced the call.
3. Name the defence as precisely as the evidence allows (for example `akamai_v3`, `cf_clearance`, `datadome`, `incapsula`, a named challenge, or `waf:<name>`); research unfamiliar block patterns before naming them; no defence signal means the type is null.
4. Derive the mode: no defence signal -> request-based (reproduce the flow with a plain HTTP client, discovering the request shape from the client-side script when the sign-in is JS-programmed); a defence signal or a block-signalling 403 -> browser through steel.
5. Record the verdict honestly: `http-client-replayability: true` with the static (replayable as-is) and dynamic (re-minted or browser-bound) shape elements, or `false` with the browser steps when a plain-client replay cannot reach the authenticated state. Browser-only is a complete, honest result, never a failure.
6. Re-verify stale state loudly: an expired or missing session is a failure to re-run the oracle, never a silent fall back to anonymous state.
7. Persist both facts through the seed face, merging the overview you read first; a shape violation returns 400 `auth_invalid` and lands nothing.
8. Keep the shared vocabulary: `waf_protected` and `waf_detection` for a block, `rate_limited` for a throttle; an application-level 401/403 takes no blocking-signature name.

## The authenticated-context oracle (mandatory, per role)

Find one URL per role that answers 2xx only with that role's authenticated context.
Use `<auth_probe_path>` when it is already known; otherwise choose a same-origin candidate such as `/api/me`, `/api/authentication`, or the role's landing page.
Prove both polarities before recording it:

- With the authenticated session, a browser request returns 2xx with no followed redirect.
- Without the session (a fresh anonymous client, or no cookies), the same request returns 401, 403, or 3xx.
- A URL that answers 2xx anonymously is not an oracle; find another one.
- A login page is never the oracle.

Verify with the canonical probe: `browser(command="exec", input="eval <fetch-script>")`, using the script in `<mechanics_skill_path>/../references/auth-oracle.sh`.
The oracle is the ONLY pass/fail signal for authentication.
2xx passes; 401, 403, or 3xx fails; anything else is indeterminate and is not a pass.
Store the role's `account.auth_probe = {url: <auth_probe_path>}` and its `root_url`; both are deployment-neutral paths, never hosts.
When a role's probe is absent or empty, a non-4xx, non-3xx response at its root is the success rule.
The overview `auth_probe` is only the legacy fallback for an account that declares neither.
A target with no reliable oracle for a role is a loud blocker for that role, not a pass for it.

## Browser branch (only when the probe forces it)

Mount the account's auth context with `browser(command="start", account=<account>)`.
The pool store mounts the decoupled context and restores its cookies and localStorage; an account with no stored context starts fresh.
A mount while the same execution unit holds the session answers `session_in_use`; reuse the mounted session, never start a twin.
A mount with no live lease answers `no_session`; call `start` first.
A state restore that cannot complete answers `restore_failed`; stop and report it.
A pool with no free worker answers `pool_exhausted`; retry after a lease ends.
A missing browser capability answers `browser_unavailable`; continue on the request path when the target permits it.
Log in only when the oracle fails.
Pace the login per the mechanics skill's cadence rules, and settle with a condition rather than a fixed pause or network idle: `browser(command="exec", input="wait --url <authenticated_landing_substr>")` or `browser(command="exec", input="wait --text <marker>")`, because `navigate --wait-until networkidle` never settles on a continuously-active page and burns its whole timeout.
Those waits only settle the page; the oracle still decides pass or fail.
Wait on the challenge's own marker with a bounded `--timeout`, then escalate to the operator: the post-gate state cannot appear until the human acts, so a wait on it burns its whole timeout.
Call `browser(command="end", persist_context=true)` on every path; it captures, saves, stops, and releases.
After a successful end, record `browser_context.ref = <context-ref>` in the account.

## Report back

Return a concise report: the mode decision with its forcing evidence (status codes, headers, body markers); the `anti-bot` name or null; the `http-client-replayability` verdict with its static and dynamic continuation facts; the oracle path with both observed polarities (authenticated 2xx, anonymous 401/403/3xx); the token names and locations; the exact skill path written and the store read-back with secret values redacted; and any error verbatim, plus anything you could not establish.
Cite secret names only: no secret VALUE in the report or in the skill.

## Deliverable

- Store facts via the seed face: the typed overview (`login_endpoint`, `required_headers`, `mechanism`, `defences`, `fingerprinting`, `technical_conditions` with one role shape per role, `anti-bot`, `http-client-replayability`, the legacy `auth_probe` only when an account declares neither) and, per account named `<username>-<minting_context>` (the credential username with its email location suffix stripped, plus the run or flow that minted it, never the procedure), `role`, `root_url`, `auth_probe`, `credentials`, `tokens` (with locations), the `browser_context` reference after a successful `browser(command="end", persist_context=true)`, `snapshot`, and the `procedure` label joining the account to the skill procedure.
- The project skill at `<data_root>/<project_id>/skills/<skill_name>/SKILL.md`, with the mandatory block embedded verbatim and target-specific ordered steps (tool plus why per step), sign-up and sign-in as separate named procedures per role, each role's oracle verification step, and secret values cited by name only.
- Report: the roles found and the mint order; the mode decision with its forcing evidence; the `anti-bot` name or null; the replayability verdict and continuation facts; every session's root and oracle path with both polarities; the token names/locations if a browser was used; the written skill path; and any error verbatim.
