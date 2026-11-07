---
name: authn-skill-writing
description: Use when executing authentication against a target project by hand and authoring that target's per-project authentication skill from verified state.
metadata:
  version: '2.8'
---
# Authn skill writing

You are external to the system under test, operationalised by the operator by hand.
Your job is to execute authentication against one target, establish its anti-bot posture and HTTP-client replayability, and author that target's per-project authentication skill (the authn skill) from what you verified.
Work the phases P0 through P6 in order.
Record nothing until its gate passes.

## Prerequisites

You need generic request tooling for probe and replay work.
You need the one `browser` tool bound to your conversation. It is one software construct with three commands: `start`, `exec`, and `end`. Do not run the Steel CLI directly. Smoke-test it with `browser(command="start", account=<account>)`, `browser(command="exec", input="get title")`, and `browser(command="end")`.
You need reachability of the seed face `PUT /projects/{project_id}/auth` and the state-read face `GET /projects/{project_id}/auth`.
You need write access to the target project's skill bundle at `skills/target-specific-procedure/<project_id>/authn/` (the location P5 pins).
You need no polymerhus internals beyond the seed-face contract and that parametrized bundle location.

## The two planes and the one join

The store holds the WHAT: durable verified state (credentials, tokens, steel session-state reference, snapshot, roles, the anti-bot and replayability facts, overview).
The authn skill holds the HOW: the replayable procedure a follower executes.
The only formal edge between them is the `procedure` label on an account record, naming the skill procedure that minted or serves that account.
Every procedure cites the account and token NAMES it uses, never their values.
Keep the planes non-overlapping: facts live in the store, steps live in the skill.

## Seed-face contract (mirror, kept terse by design)

The following mirrors the seed-face contract only, which is the single write path for STORE facts available to you; the project skill bundle is your other write path (P5).
Write facts with `PUT /projects/{project_id}/auth` and body `{overview?, accounts?}`.
Read state with `GET /projects/{project_id}/auth`, which returns the full `{"overview": ..., "accounts": ...}` state.
Each present section REPLACES the operator's section wholesale (an in-system agent write merges instead, D220-12).
Each absent section is left untouched.
Seeded accounts are stamped `origin: operator` server-side, so never put `origin` in the payload.
Agent-stamped accounts survive every seed untouched.
A seeded operator name colliding with a live agent record keeps the agent record and drops the operator entry, so preserve the join when you see it.
Shape violations return 400 `{ok: false, error: "auth_invalid", detail}` and land nothing.
An unknown project returns 404.
The in-process agent store tool is the in-system agent path, not yours: do not use it and do not document it.
Name every account `<username>-<minting_context>`: the credential username with its email location suffix stripped (`diegogobbetti69@gmail.com` -> `diegogobbetti69`), a hyphen, then the run or flow that minted it (`first_authn_bootstrap`, `hunting_misauthr`, ...), which you assess at write time.
The minting context is the run or flow, never the procedure, so sign-up and sign-in in one bootstrap share ONE account name; a second name for the same credential identity is a fork, not a second account.
Per account record: `credentials` (username, password, login_url, plus optional domain and form selectors), `tokens` (each `{value, location: cookie|header|storage, target?, expiry?}`), `steel` (`{state}` key only, never browser state), `snapshot` (`{cookies, params, captured_at}`; the required header fact single-sources on the overview's `required_headers`, never duplicated here), `roles` with `default_role` where multiple roles exist, `notes`.
Overview fields, all optional: `login_endpoint`, `required_headers`, `mechanism`, `defences`, `fingerprinting`, `technical_conditions` (a list of `{name, check}`), `anti-bot`, `http-client-replayability`, `auth_probe` (`{url}` - the authenticated-context oracle), `notes`.
`anti-bot` is the defence type (a vendor, product, or challenge name such as `akamai_v3`, `cf_clearance`, `datadome`, `incapsula`, or `waf:<name>`) or null when none; `http-client-replayability` is `true` or `false`, and leaving it unset means UNKNOWN, never false.
`auth_probe.url` is a deployment-neutral path such as `/api/authentication`, never a host.
It is the ONE deterministic authentication oracle: the target answers 2xx only with an authenticated context, and 401, 403, or a 3xx without one.
The app resolves the path against the project's canonical origin at read.
Procedural prose never lands in the store.
Secret values never land in the skill.
The skill bundle is a separate write path from the seed face: write facts to the store, steps to the bundle, and never cross the two.

## P0 - Read state

Read the store full state and any existing authn skill bundle before acting.
Treat `overview` as operator ground truth: `mechanism`, `defences`, `fingerprinting`, `required_headers`, `login_endpoint`, `technical_conditions`, `anti-bot`, `http-client-replayability`, `auth_probe`.
Gate: you can name the operator-stated mechanism and defences, say whether the two facts are already recorded, and name the existing oracle or know it is absent.

## P1 - Anti-bot posture and HTTP-client replayability

Run the block below exactly: it is the operator's mandatory target-agnostic text.
The notes after it pin the shared vocabulary, the continuation-facts home, and the browser fallback the block assumes.

```markdown
## Anti-bot posture and HTTP-client replayability (mandatory, target-agnostic)

Whatever the target, establish and record these two facts before you record its authentication state.

1. Probe request-side first. Using your own request tooling against the target, send the shape a plain client would send (no browser) to the sign-in endpoint or to any authenticated area named in the overview, applying the account's cookies, tokens, and snapshot exactly as recorded. Inspect status, headers, body, and challenge markers.
2. Classify the response, distinguishing three signals. An authentication failure is a 401, or a 403 whose body and headers show an application-level denial. A rate limit is typically a 429 or a documented retry signal. A WAF or anti-bot block is a 403 (or a 200 interstitial) carrying block-page fingerprints, a JS-challenge script, or bot-management cookies. Never collapse these into one another; record the evidence that forced the call.
3. Name the defence. If a WAF or anti-bot defence is present, name its type as precisely as the evidence allows (for example `akamai_v3`, `cf_clearance`, `datadome`, `incapsula`, a named challenge, or `waf:<name>`). Research unfamiliar block patterns (vendor block pages, challenge scripts, characteristic cookies) before naming them. If no defence signal appears, the type is null.
4. Replay the trusted context surgically. When a browser session holds the trusted context, attempt to reproduce it with a plain HTTP client. Start from the overview's `required_headers` (the single source of the required header fact), the account `snapshot` (cookies, params) and the stored tokens with their locations. Identify line by line what carries the trust: header set and order, cookies, token values and locations, user-agent and client hints, query and body parameters, request and network parameters you control, and TLS/HTTP signature specifics where your tooling lets you control them. Change one variable at a time and read the response; iterate until the replay reaches the authenticated state or you can name what blocks it.
5. Record the verdict honestly. When a plain-client replay reaches the authenticated state, record `http-client-replayability: true` and record which shape elements are static (replayable as-is) and which are dynamic (must be re-minted or are browser-bound): the continuation facts a follower needs. When replay cannot reach the authenticated state, record `http-client-replayability: false`; browser-only is a complete, honest result, never a failure.
6. Script-driven logins. When the sign-in is programmed by client-side script, fetch and read the script; replay the exact request shape it builds (endpoints, headers, nonces, parameter order); where the script derives values dynamically (nonces, signatures, fingerprints), say so and treat those parts as browser-bound.
7. Re-verify stale state. Treat an expired or missing session as a loud failure. Re-run the oracle before recording or replaying; never fall back silently to anonymous state. The oracle is a 2xx-only URL, not a landing-page heuristic.
8. Persist through the operator seed face. Write both facts into the overview with `PUT /projects/{project_id}/auth`. A present `overview` section replaces wholesale, so read `GET /projects/{project_id}/auth` first and send the merged overview. A shape violation returns 400 `{ok: false, error: "auth_invalid", detail}` and lands nothing. This seed face is your write path: the in-process agent store tool is the in-system agents' path (their writes merge into the same overview, D220-12), so never use it here and never put `origin` in the payload.

Two rules bind every target: facts live in the store, steps live in the skill; secret values stay in the store, the skill cites names only.
```

### Naming the signals (shared vocabulary)

Classify with the recon harness's own blocking-signature names, never a synonym, so your call and the harness's signals speak one language.
`waf_protected` and `waf_detection` are the WAF or anti-bot BLOCK signal: a 403 or a 200 interstitial carrying block-page fingerprints, a JS-challenge script, or bot-management cookies.
`rate_limited` is the THROTTLE signal: a 429 or a documented retry signal.
An authentication failure is a 401, or a 403 that is an application-level denial; it is not a block and takes no blocking-signature name.
The `anti-bot` field is a different axis from the signal: it names the defence behind a block (the vendor, product, or challenge), while the classification says which signal fired.

### The continuation facts (where they live)

The static and dynamic element lists from step 5 are replay PROCEDURE, so they live in the authn skill you author at P5, never in the store.
The store keeps the concrete values they describe (`snapshot`, `tokens`) plus the two typed facts (`anti-bot`, `http-client-replayability`).
A static element that proves to be a stable target property graduates into the overview's typed fields (`required_headers`, `defences`, `fingerprinting`), not a new field.

### Browser fallback: the one browser tool discipline

The pool store is the only durable browser-state store: cookies, localStorage, sessionStorage, and indexedDB are captured on `browser(command="end")`; cookies and localStorage are restored on `browser(command="start")`.
The store holds the decoupled auth-context object, never a secret value in the auth store.
The auth store holds only the reference: `browser_context: {ref}`.
The reference is `steel-auth-<project_slug>-<account_slug>` with an account.
A slug is lowercase; every run outside `[a-z0-9_-]` becomes one `-`, consecutive hyphens collapse, and leading or trailing `-`/`_` are trimmed.
The browser tool derives the ephemeral session key from the execution unit; you never pass a session name.

Mount with `browser(command="start", account=<account>)`.
The tool loads the account's decoupled auth context; an account with no stored context starts fresh.
A mount while the same execution unit already holds the session answers `session_in_use`; reuse the mounted session, never a twin.
A mount with no live lease answers `no_session`; call `start` first, never fabricate a replacement.
A state restore that cannot complete answers `restore_failed`; stop and report it.
A pool with no free worker answers `pool_exhausted`; retry after a lease ends.
A missing browser capability answers `browser_unavailable`; continue on the request path when the target permits it.
Log in when the mounted session does not pass the oracle.
Verify with the oracle: a browser request to `overview.auth_probe.url` answers 2xx only for an authenticated context; 401, 403, or 3xx is not authenticated; anything else is indeterminate and is not a pass.
An unverified session never passes a verdict.
Call `browser(command="end", persist_context=true)` on every authenticated path after the first mount.
It captures cookies, localStorage, sessionStorage, and indexedDB, saves them under the account's context reference, stops the browser, and releases the session.
Its result carries `captured`, `saved`, `stopped`, `released`, and `context_saved`; `saved: false` means the next start cannot restore the session state.
After a successful end, record `accounts.<account>.browser_context.ref = <context-ref>`.
The mechanics are the `steel-browser` skill; this skill owns only the login PROCEDURE.

A follower's rules differ from this bootstrap's.
A generated procedure that a gateway or pod runs must mount the same account's auth context and never start a twin.
A missing session is asserted `not_valid` and stops the run; it is not a reason to mint a blank session.
A follower may mint a NEW account through the sign-up procedure with synthetic identity data when the mounted context cannot authenticate and the target supports sign-up.
It writes the new credentials and proves the oracle; it never reads an existing secret.
A model-facing follower sees a REDACTED `auth_store` view: it cites token names and locations, uses the recorded HTTP history replay or the browser session, and never reads or pastes a secret value.
Authentication failure never fails open; collection does not run unauthenticated.

### Browser fast path (read this before the first browser step)

The operation MECHANICS are the `steel-browser` skill (`skills/internal/tools/steel-browser/SKILL.md`); this skill owns only the login PROCEDURE.
Read the mechanics skill before the first browser step; do not re-derive the command grammar.
Four habits carry almost all the latency and reliability:
1. Snapshot with `-i`: `browser(command="exec", input="snapshot -i")` returns only interactive elements with their refs, not the whole tree.
2. Batch to share state: `browser(command="exec", input="batch -- 'snapshot -i' 'fill @e6 -- <value>'")` reads a ref and uses it in one call, instead of a snapshot round-trip then an act.
3. A variadic verb carries its `--` boundary: `browser(command="exec", input="fill '#email' -- '<value>'")` (the value is taken verbatim; without the boundary a trailing flag folds into the value behind `success:true`).
4. Synchronise on an observable, never a fixed `sleep`: `browser(command="exec", input="wait --url <substr>")` / `--text <marker>` / `--selector <css>` with `--timeout <ms>`.
Re-snapshot after every `navigate`: refs do not cross a navigation (an old ref answers `Unknown ref` or silently re-binds), so refs come only from the snapshot you just read.
The command string is split like a shell but never executed by one; quote a value that contains a space or a shell-significant character.

### Worked example

`references/worked-example.yaml` beside this skill carries a request-replayable scenario (a defence classified, `http-client-replayability: true`) and a browser-only scenario (a JS-challenge defence, `http-client-replayability: false`), each with its probe trace and its seed payload.
Read it before your first probe.
`references/bootstrap-workflow.md` is the reusable, target-agnostic first prompt for the external bootstrapper: fill its placeholders, then work P0 through P6; it defaults to request-based and takes the browser only on a defence signal.

Gate: the classification is stated with the evidence that forced it; the defence is named or null; the replay verdict is recorded with its continuation facts, or the flow is honestly browser-only.

## P2 - Discover auth surfaces

Find the sign-in feature (endpoint, form or API shape, required headers, CSRF or anti-forgery handling, selectors).
Find the sign-up feature separately where one exists, with the same shape detail.
Keep sign-in and sign-up DISTINGUISHABLE as separate flows, each with its own procedure.
An account is keyed by its credential identity, so flows that share credentials share ONE account (sign-up mints it, sign-in serves it); they are separate accounts only when their credentials differ.

Find the authenticated-context oracle: one URL that answers 2xx only with an authenticated context.
Prefer a same-origin path such as `/api/me`, `/api/authentication`, or an account page that never renders anonymously.
Prove BOTH polarities before recording it:

1. With the authenticated session: a browser request returns 2xx with no followed redirect.
2. With an anonymous client (no cookies, or a fresh session): the same request returns 401, 403, or a 3xx.
3. If the anonymous request also returns 2xx, the URL is not an oracle; find another one.
4. If the authenticated request returns 3xx, the URL is not an oracle; find another one.

A login page is never the oracle: it answers 2xx anonymously.
Gate: each flow states its endpoint or form plus its required headers and anti-forgery handling, or states which element could not be found; and one oracle path is recorded with both observed polarities, or the target has no reliable oracle and the bootstrap reports that as a blocker.

## P3 - Execute and verify

Request path: reproduce the request shape exactly, then verify success before capturing anything.
Browser path: mount the account's auth context with `browser(command="start", account=<account>)`; verify it with the oracle per the fallback discipline above. Log in only when the oracle does not pass, and pace that login per the mechanics skill's cadence and escalation rules.
Call `browser(command="end", persist_context=true)` after verification and record `accounts.<account>.browser_context.ref = <context-ref>`.
Verify the oracle with the canonical browser request: `browser(command="exec", input="eval <fetch-script>")`, or the equivalent fetch from `<mechanics-skill-references>/auth-oracle.sh`.
The request must run in the mounted page context so it carries the session cookies.
Do not settle with `navigate --wait-until networkidle`: a login page or SPA with continuous activity (polling, websockets, analytics beacons) never reaches network idle, so the navigate times out and wastes its whole timeout; use `--wait-until load` (or `domcontentloaded`) and a `wait` condition instead when a step needs a page.
Gate: the oracle returns 2xx with no followed redirect for the flow.
A 401, 403, or 3xx is a failed verification.
Anything else is indeterminate and is not a pass.
An unverified flow never yields a verdict and never advances to P4.

## P4 - Record the facts (WHAT)

Write the verified facts into the store through the seed face from the contract section above.
Record per account only what P3 verified: `credentials`, `tokens`, the `browser_context` reference after a successful `browser(command="end", persist_context=true)`, `snapshot`, `roles` and `default_role`, `notes`.
Record overview only what P0 through P2 established: `login_endpoint`, `required_headers`, `mechanism`, `defences`, `fingerprinting`, `technical_conditions`, `anti-bot`, `http-client-replayability`, `auth_probe`, `notes`.
Set `anti-bot` to the named defence or null; set `http-client-replayability` to `true` or `false` only once the replay was actually run, otherwise leave it unset so it reads UNKNOWN.
Set `auth_probe` to the verified oracle path: `{url: /api/...}`.
Never store a host; the app resolves the path against the project's canonical origin at read.
Gate: no procedure prose landed in the store and no secret value landed in the skill.

## P5 - Write the procedure (HOW)

Write the authn skill as replayable ordered steps, with sign-up and sign-in as separate named procedures.
Every sign-up procedure carries this line verbatim, so every target mints new accounts the same way: "New accounts are minted with synthetic identity data - a fake email address and fake personal details - never real personal data; the exact values used are recorded in the account's `credentials`."
Cite for EVERY step the tool it uses AND why it uses it (request-based because no blocking defence was observed, steel because a named WAF, anti-bot, or fingerprinting signal forced it).
When `http-client-replayability` is `true`, the procedure cites the recorded HTTP history replay (`search_http_history`, `replay_http_request`) or the pipeline's server-side request material, plus the static/dynamic element names and locations. It never instructs a model-facing follower to read or paste a value; the `auth_store` view is redacted.
When it is `false`, the procedure carries the browser steps instead, and says plainly that a plain-client replay cannot reach the authenticated state. Those steps mount the account's auth context and never start a twin.
Every procedure, request or browser, carries the same verification step: run the oracle at `overview.auth_probe.url` and pass only on 2xx with no followed redirect. A 401, 403, or 3xx is a failure; anything else is indeterminate and stops the run.
The browser procedure's failure branch names the typed outcomes: `session_in_use` means the execution unit already holds the session and it must be reused, never twinned; `no_session` means no live lease exists and `start` must run first; `restore_failed` means the stored context could not be mounted; `pool_exhausted` means retry after a lease ends; `browser_unavailable` means the pool is unreachable. A follower asserts `not_valid` and stops when the context is gone. When the target supports sign-up, the follower may mint a new account with synthetic identity data, write its credentials, and prove the oracle; it never fails open.
Name for every browser step the account, the `browser(command="exec", input="...")` string, and the evidence it produces.
Resolve script citations to the steel-browser skill's published references beside that skill (`references/extract-reads.sh`, `references/eval-inline.sh`, `references/eval-interact.sh`, `references/auth-oracle.sh`) or the authn skill's own `references/` scripts.
Keep login-specific scripts in the authn skill's own `references/`, and mechanics in the steel-browser references.

### Where the project skill lands

Write the authn skill as one whole file at `skills/target-specific-procedure/<project_id>/authn/SKILL.md`, with login-specific scripts under `skills/target-specific-procedure/<project_id>/authn/references/`.
`<project_id>` is the target project you were pointed at; `authn` is the fixed project-skill name, so a follower resolves the project bundle first. The project's skill area is the `target-specific-procedure/` branch of the live `skills/` catalogue root.
Write frontmatter and body together in that one file, atomically; never route the skill through the store seed face, and never route store facts through this path.
Gate: the skill file exists at that path with valid frontmatter (name equal to the bundle directory, a description, a `metadata.version`), and no store write touched it.

## P6 - Wire the join and self-check

Set each served account's `procedure` label to the skill procedure that minted or serves it.
Make each procedure cite the account and token names it uses.
Re-verify replayability: the programmatic follower can reproduce each flow from the raw store, and a model-facing follower can reproduce it through the recorded HTTP history replay or the operator-owned browser session. The two recorded facts match what the procedure does.
Re-verify the oracle: the procedure names `overview.auth_probe.url` and passes only on 2xx with no followed redirect. Re-run it after any expiry.
Re-verify secrecy: the skill holds names and steps, never values.
Re-verify the failure branch: the skill's unexpected-failure path cites the `overview.technical_conditions` checks as its diagnostic ladder, and stops rather than failing open.
Gate: the two planes are mutually consistent and non-overlapping, with no orphan account and no orphan procedure.

## Join map (store element, skill element, rule)

| Store element | Skill element | Rule |
| --- | --- | --- |
| `procedure` label | Named procedure | Sole formal edge, bidirectional |
| Account NAME | Procedure account citation | Known name means duplicate, never fork |
| `credentials` | Sign-in or sign-up step | Secrets stay in store, skill cites account |
| `tokens.<t>` value plus location | Token carrying or reading step | Location dictates where token travels; a model-facing follower is redacted and the value is applied server-side |
| `browser_context: {ref}` | Browser session step | Store holds the decoupled context reference after a successful `browser(command="end", persist_context=true)` |
| `snapshot` | Request replay step | Replay the account snapshot exactly |
| `overview.anti-bot` | Defence-naming step (P1) | Store holds the vendor name, skill names it for the mode decision |
| `overview.http-client-replayability` | Replay verdict and continuation facts (P1/P5) | true means the skill carries replay steps; false means browser steps; unset means unknown |
| `overview.mechanism`, `defences`, `fingerprinting` | P1 mode decision | Skill consumes ground truth, never restates |
| `overview.required_headers`, `login_endpoint` | Request step shape | Send exactly these |
| `overview.auth_probe.url` | Verification step | The only pass/fail oracle: 2xx passes, 401/403/3xx fails, else indeterminate |
| `overview.technical_conditions` | Unexpected-failure branch | Diagnostic ladder lives in store |
| `origin` trust split | Seed-face writes | Reader acts as operator, never as in-system agent |
| `roles`, `default_role` | Role procedures | Each role set maps to a procedure |
| Steel-browser and authn-skill `references/` | Script names in procedures | Store holds neither |

## Stale state

Treat expired or missing sessions as loud failures, never as silent anonymous state.
Re-run the P3 oracle after any expiry before recording or replaying.
Say in the skill which step fails loudly when its session is stale, and that a failed or indeterminate oracle stops the run.

## Red flags - stop and repair

| Flag | Repair |
| --- | --- |
| Mode stated without evidence | Return to P1 and record the forcing signal |
| Browser used with no defence signal | Justify or redo as request-based |
| Classification collapsed (auth failure, block, and throttle read as one) | Re-probe, separate the three signals, record the evidence that forced the call |
| Defence named without research | Research the vendor block page, challenge script, or characteristic cookie, then name it or set null |
| Replayability set false on an unverified replay | Finish the iteration or leave the fact unset (unknown) |
| Unverified flow recorded | Delete the record, return to P3 |
| No oracle, or a login page named as the oracle | Return to P2 and prove both polarities |
| Oracle returns 401/403/3xx but the flow is recorded as valid | Re-authenticate or mint, then re-run the oracle; never waive it |
| Failure path falls back to unauthenticated collection | Stop the run, assert `not_valid`, and report the missing data dependency |
| Secret value in skill text | Move value to store, leave name citation |
| Procedure prose in store notes | Move steps to skill, keep facts only |
| Sign-up and sign-in merged | Split into separate procedures; keep ONE account per credential identity |
| Account without `procedure` label | Set label in P6 |
| Procedure without account citation | Cite account and token names |
| Step without tool plus reason | Add both before calling the flow replayable |
| Browser step without an account or commands | Name the account, commands, and reference files |
| Write attempted outside seed face | Route through `PUT /projects/{project_id}/auth` |
| `origin` placed in seed payload | Remove it, server stamps operator |
| Failure branch without `technical_conditions` | Cite the checks as the diagnostic ladder |

## References

- `references/worked-example.yaml` - two worked scenarios (a request-replayable target and a browser-only target) with their probe traces, classifications, and seed payloads.
- `references/bootstrap-workflow.md` - the reusable, target-agnostic first prompt for the external bootstrapper, with placeholders and the request-first anti-bot workflow.
- the steel-browser skill's `references/auth-oracle.sh` - the canonical browser oracle probe (2xx pass, 401/403/3xx fail, else indeterminate).
