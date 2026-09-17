---
name: authn-skill-writing
description: Use when executing authentication against a target project by hand and authoring that target's per-project authentication skill from verified state.
metadata:
  version: '1.0'
---
# Authn skill writing

You are external to the system under test, operationalised by the operator by hand.
Your job is to execute authentication against one target and author that target's per-project authentication skill (the authn skill) from what you verified.
Work the phases P0 through P6 in order.
Record nothing until its gate passes.

## Prerequisites

You need generic request tooling for probe and replay work.
You need the steel CLI, authenticated (`steel login`, `steel doctor --preflight`, smoke test `steel scrape https://example.com`).
You need reachability of the seed face `PUT /projects/{project_id}/auth` and the state-read face `GET /projects/{project_id}/auth`.
You need no polymerhus internals beyond the seed-face contract stated below.

## The two planes and the one join

The store holds the WHAT: durable verified state (credentials, tokens, steel profile key, snapshot, roles, overview).
The authn skill holds the HOW: the replayable procedure a follower executes.
The only formal edge between them is the `procedure` label on an account record, naming the skill procedure that minted or serves that account.
Every procedure cites the account and token NAMES it uses, never their values.
Keep the planes non-overlapping: facts live in the store, steps live in the skill.

## Seed-face contract (mirror, kept terse by design)

The following mirrors the seed-face contract only, which is the single write path available to you.
Write facts with `PUT /projects/{project_id}/auth` and body `{overview?, accounts?}`.
Read state with `GET /projects/{project_id}/auth`, which returns the full `{"overview": ..., "accounts": ...}` state.
Each present section REPLACES the operator-owned state wholesale.
Each absent section is left untouched.
Seeded accounts are stamped `origin: operator` server-side, so never put `origin` in the payload.
Agent-stamped accounts survive every seed untouched.
A seeded operator name colliding with a live agent record keeps the agent record and drops the operator entry, so preserve the join when you see it.
Shape violations return 400 `{ok: false, error: "auth_invalid", detail}` and land nothing.
An unknown project returns 404.
The in-process agent store tool is the in-system agent path, not yours: do not use it and do not document it.
Per account record: `credentials` (username, password, login_url, plus optional domain and form selectors), `tokens` (each `{value, location: cookie|header|storage, target?, expiry?}`), `steel` (`{profile}` key only, never browser state), `snapshot` (`{headers, cookies, params, captured_at}`), `roles` with `default_role` where multiple roles exist, `notes`.
Overview fields, all optional: `login_endpoint`, `required_headers`, `mechanism`, `defences`, `fingerprinting`, `technical_conditions` (a list of `{name, check}`), `notes`.
Procedural prose never lands in the store.
Secret values never land in the skill.

## P0 - Read state

Read the store full state and any existing authn skill bundle before acting.
Treat `overview` as operator ground truth: `mechanism`, `defences`, `fingerprinting`, `required_headers`, `login_endpoint`, `technical_conditions`.
Gate: you can name the operator-stated mechanism and defences, or you know they are absent.

## P1 - Posture probe

Probe request-side FIRST, since the mode decision is a defence reading, never a preference.
Look for WAF and anti-bot markers, fingerprinting signals, and any 403 whose body or headers indicate a WAF or bot block.
Treat any marker vocabulary as conditions to verify on the target, never as a defined taxonomy.
Derive the interaction mode from what you observe: no defence signal means request-based, while a defence signal or a 403 indicating a WAF or bot block means browser through steel.
Gate: the chosen mode is stated with the evidence that forced it.

## P2 - Discover auth surfaces

Find the sign-in feature (endpoint, form or API shape, required headers, CSRF or anti-forgery handling, selectors).
Find the sign-up feature separately where one exists, with the same shape detail.
Keep sign-in and sign-up DISTINGUISHABLE as separate flows with separate accounts.
Gate: each flow states its endpoint or form plus its required headers and anti-forgery handling, or states which element could not be found.

## P3 - Execute and verify

Request path: reproduce the request shape exactly, then verify success before capturing anything.
Browser path: create the profile in flow on first login with `start --profile <name> --update-profile`, or mount an operator-created profile (made via `steel profile import`) with `start --profile <name>`.
Session state is not saved back unless `--update-profile` is passed: browsing mounts read-only by default, so write back only past the verify gate below.
Record the profile id from the mint to the account `steel` reference in P4.
Verify with concrete commands: `navigate` to the target URL, `wait --load networkidle` to settle, then `get url` to read the current URL and confirm the authenticated landing state.
There is no CLI state poll: this is live-observed CLI behaviour recorded in the browser-capability decision record (D17), where `profile list` returns name plus id only, so settle-then-verify-by-navigation is the procedure.
The #221 decision record is the authority for the steel profile write discipline: where the vendored steel references and that record disagree, follow the record.
Gate: a verification predicate fired for the flow, where request success means a new session cookie plus a non-login URL and browser success means navigation to the authenticated landing state.
An unverified flow never yields a verdict and never advances to P4.

## P4 - Record the facts (WHAT)

Write the verified facts into the store through the seed face from the contract section above.
Record per account only what P3 verified: `credentials`, `tokens`, `steel` profile key, `snapshot`, `roles` and `default_role`, `notes`.
Record overview only what P0 through P2 established: `login_endpoint`, `required_headers`, `mechanism`, `defences`, `fingerprinting`, `technical_conditions`, `notes`.
Gate: no procedure prose landed in the store and no secret value landed in the skill.

## P5 - Write the procedure (HOW)

Write the authn skill as replayable ordered steps, with sign-up and sign-in as separate named procedures.
Cite for EVERY step the tool it uses AND why it uses it (request-based because no blocking defence was observed, steel because a named WAF, anti-bot, or fingerprinting signal forced it).
Name for every steel step the profile to load, the concrete CLI commands, and the reference files they come from.
Resolve script citations to either the steel-CLI skill own siblings (`references/steel-browser-commands.md` and `references/steel-browser-lifecycle.md` beside that skill) or the authn skill own `references/` scripts.
Keep login-specific scripts in the authn skill own `references/`, and mechanics in the steel-CLI skill references.
Gate: a follower can replay each flow step by step, and the text reads as ordered steps rather than a fact dump.

## P6 - Wire the join and self-check

Set each served account `procedure` label to the skill procedure that minted or serves it.
Make each procedure cite the account and token names it uses.
Re-verify replayability: a follower holding only the skill plus the store can reproduce each flow.
Re-verify secrecy: the skill holds names and steps, never values.
Re-verify the failure branch: the skill unexpected-failure path cites the `overview.technical_conditions` checks as its diagnostic ladder.
Gate: the two planes are mutually consistent and non-overlapping, with no orphan account and no orphan procedure.

## Join map (store element, skill element, rule)

| Store element | Skill element | Rule |
| --- | --- | --- |
| `procedure` label | Named procedure | Sole formal edge, bidirectional |
| Account NAME | Procedure account citation | Known name means duplicate, never fork |
| `credentials` | Sign-in or sign-up step | Secrets stay in store, skill cites account |
| `tokens.<t>` value plus location | Token carrying or reading step | Location dictates where token travels |
| `steel: {profile}` | Browser mount step | Store holds key, skill names profile |
| `snapshot` | Request replay step | Replay the account snapshot exactly |
| `overview.mechanism`, `defences`, `fingerprinting` | P1 mode decision | Skill consumes ground truth, never restates |
| `overview.required_headers`, `login_endpoint` | Request step shape | Send exactly these |
| `overview.technical_conditions` | Unexpected-failure branch | Diagnostic ladder lives in store |
| `origin` trust split | Seed-face writes | Reader acts as operator, never as in-system agent |
| `roles`, `default_role` | Role procedures | Each role set maps to a procedure |
| Steel-CLI plus authn-skill `references/` | Script names in procedures | Store holds neither |

## Stale state

Treat expired or missing sessions and profiles as loud failures, never as silent anonymous state.
Re-run the P3 verification predicate after any expiry before recording or replaying.
Say in the skill which step fails loudly when its session or profile is stale.

## Red flags - stop and repair

| Flag | Repair |
| --- | --- |
| Mode stated without evidence | Return to P1 and record the forcing signal |
| Browser used with no defence signal | Justify or redo as request-based |
| Unverified flow recorded | Delete the record, return to P3 |
| Secret value in skill text | Move value to store, leave name citation |
| Procedure prose in store notes | Move steps to skill, keep facts only |
| Sign-up and sign-in merged | Split into separate procedures and accounts |
| Account without `procedure` label | Set label in P6 |
| Procedure without account citation | Cite account and token names |
| Step without tool plus reason | Add both before calling the flow replayable |
| Steel step without profile or commands | Name profile, commands, reference files |
| Write attempted outside seed face | Route through `PUT /projects/{project_id}/auth` |
| `origin` placed in seed payload | Remove it, server stamps operator |
| Failure branch without `technical_conditions` | Cite the checks as the diagnostic ladder |
