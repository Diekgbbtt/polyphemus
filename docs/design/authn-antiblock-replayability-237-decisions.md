# Authn anti-bot + HTTP-client replayability (#237) - design decisions

Status: decided.
This document is the decision ledger for ticket #237 (the anti-bot defence type and the HTTP-client replayability fact in the auth-store overview contract, plus the meta-skill procedure that produces them).
It is the ADR equivalent for this change (`docs/agents/domain.md:42-49`).
Parent ticket: #237.
It amends the #220 auth-store contract (`docs/design/auth-store-220-decisions.md`) and authors the #220-owner meta skill `skills/meta/authn-skill-writing/SKILL.md`.
Consumer: #223 (the recon orchestrator's outer loop).
Runtime enforcement stays in #223 and is out of scope here: this ticket only produces and types the facts.

## D237-0 - Base and scope

The ticket modifies the auth store (`src/polymerhus/app/auth/`) and the meta skill, neither of which was on `dev` at dispatch; they land with the #220/#221/#222/#234 stack (tip `c126f86`, `feat/220-auth-store` == `feat/223-stateful-recon-job-auth`).
By operator ruling the branch is cut from that stack, and the #237 diff is confined to the overview contract, the meta skill, and their docs/tests - no recon-orchestrator change (out of scope), no settings-blob change (a different bucket, D220-7).

## D237-1 - The two facts are typed overview fields, named exactly as the operator interface

The overview contract gains `anti-bot` and `http-client-replayability`.
The names are hyphenated deliberately, against the repo's snake_case house style: they are the operator-to-system interface names fixed by the ticket and the target-agnostic verbatim block the operator feeds the external agent, and the acceptance criterion requires the skill text stay consistent with that block; the closed-key validator makes this a single explicit, tested exception.
`anti-bot` is optional; when present it is a non-empty string naming the defence type (for example `akamai_v3`, `cf_clearance`, `datadome`, `incapsula`, a named challenge, or `waf:<name>`), or `null` for none; absent also means none or not established.
The `anti-bot` value is free-form, never a closed enum: the vendor space is open, and the skill requires researching an unfamiliar block pattern before naming it.
`http-client-replayability` is optional; when present it is a real boolean (`true`/`false`); absent or `null` is UNKNOWN, deliberately distinct from `false`.
The fact is therefore three-valued - `true` / `false` / unknown - and a consumer must never read absence as `false`.
Closed-schema validation lands in `records._OVERVIEW_KEYS` and `validate_overview`, the one enforcement point; the seed body stays `Any` so a violation flows to the 400 `auth_invalid` envelope naming the field (D220-5 unchanged).

## D237-2 - The continuation facts live in the authn skill, not the store

The static-vs-dynamic shape elements are the replay procedure's content (the HOW), so they live in the per-project authn skill's HTTP-client-replayability section; the store keeps the concrete values they refer to (`snapshot`, `tokens`) and the two branchable typed facts.
This follows the two-planes rule (facts in the store, steps in the skill; D220-2) and "procedural prose never lands in the store" (D220-3): a follower replaying the context reads the skill, and a static-element finding that is a stable target property graduates into an existing typed overview field (`required_headers`, `defences`, `fingerprinting`), never a new field.
Rejected placements: `overview.notes` (procedural prose in the store), a new typed field (new persistence with no branchable consumer), the account `snapshot`/`notes` (the snapshot is the captured concrete state, not the replay judgement about it), and the `procedure` label (one identifier, not a list).

## D237-3 - The blocking-signature vocabulary is shared with #36 verbatim

The meta skill classifies each probe response into three signals and uses the recon harness's own names verbatim: `waf_protected` and `waf_detection` (the live blocking macro kinds, `src/polymerhus/recon/control/steering.py:16`) and `rate_limited` (the #36/AMV-17 rate-limit macro kind).
It never coins synonyms: the operator's classification and the harness's signals must speak one language, which is what #36's "build the detection once" requires.
The classification is: a 401, or a 403 whose body and headers show an application-level denial, is an authentication failure; a 403 or a 200 interstitial carrying block fingerprints, a JS-challenge script, or bot-management cookies is `waf_protected` / `waf_detection`; a 429 or a documented retry signal is `rate_limited`.
The `anti-bot` field is a different axis - the vendor/product/challenge NAME, not the classification signal - and the skill keeps the two apart: the classification decides which of the three signals fired; `anti-bot` names the defence behind a block.

## D237-4 - The meta skill is location-agnostic and self-contained

The external agent holds the target, generic request tooling, the authenticated steel CLI, and the two auth faces - no repository.
The dangling references are fixed: the published steel references are the scripts beside the steel-browser skill under `skills/steel-browser/references/` (`catalogue.sh`, `session-lifecycle.sh`, `stop-owner.sh`, `profile-mount.sh`, `extract-reads.sh`, `eval-inline.sh`, `eval-interact.sh`), so the skill cites those names and drops the non-existent `steel-browser-commands.md` and `steel-browser-lifecycle.md`.
The steel profile write discipline (the #221 stream's D16/D17) is INLINED rather than cited from an in-repo decision record: mint the profile in flow on first login (`start --profile <name> --update-profile`); mount by name (`start --profile <name>`), read-only by default, `--update-profile` present accumulates; settle-then-verify on every mount because the API's poll-READY has no CLI equivalent (`profile list` returns name plus id only); release is the persistence call, so any abnormal end forces re-verify; one live session per profile holds the last writer; hard timeout at create plus the platform inactivity backstop; explicit stop on every path.
No `docs/design/...` citation appears in the skill.

## D237-5 - The seed face needs no new code path

The seed body is `Any`-typed, so the new fields need no API change: `repository.seed_project_auth` delegates to `AuthStore.replace_operator_state`, which validates the overview through `validate_overview` before anything lands, and `repository.read_project_auth` returns the stored overview unchanged.
No new endpoint, no new persistence, and no store logic beyond the corrected docstring; reuse is the point (D220-5).

## D237-6 - The verbatim block is embedded exactly and pinned by a content test

The ticket's target-agnostic block is embedded in the skill verbatim inside a fenced block.
A unit content test holds a canonical copy of the block as an independent literal and asserts it appears in the skill body, so the skill text and the operator's block can never drift.
The same test asserts the skill conforms to the data-section contract (`validate_skill`), names the two new fields, names the shared blocking vocabulary, and carries no dangling or in-repo references.

## D237-7 - The worked example is a machine-checked fixture beside the skill

A worked example fixture (`skills/meta/authn-skill-writing/references/worked-example.yaml`) carries at least two scenarios: one defence classification with a `true` replayability verdict (request-replayable) and one browser-only case with `false`.
Each scenario carries the probe trace (status, headers, body markers), the classification signal, the anti-bot name, the continuation facts, and the seed overview payload.
A test loads the fixture and runs `validate_overview` over every payload, so the worked example can never drift from the schema.
The fixture travels with the skill, so the external agent can read it.

## D237-8 - Ledger and glossary homes

This document is the new ledger, and the #220 ledger gains a pointer noting the overview extension.
`src/polymerhus/recon/CONTEXT.md` gains `anti-bot` and `http-client-replayability` entries in the auth-store section.
`docs/design/domain-model.md` is unchanged: this is capability vocabulary inside Recon, not a new primitive, relationship, or open question (the #221 D18 precedent).
`src/polymerhus/project_management/CONTEXT.md` is unchanged: the seed face is unchanged, so the existing auth-endpoint pointer still holds.

## D237-9 - The meta skill names the parametrizable project-skill write location

The skill's P5 gains the project-skill write location as a PARAMETRIZED path, not a hardcoded absolute one: `<data_root>/<project_id>/skills/authn/SKILL.md`, with login-specific scripts under `<data_root>/<project_id>/skills/authn/references/`, where `<data_root>` is the app-owned data root (`<codebase_root>/data/`), `<project_id>` the target project, and `authn` the fixed project-skill name a follower resolves first (`app/llm/skills.py` names `authn` as the project-authored skill in `render_skill_index`).
This closes the gap surfaced by the e2e: the external agent knew the skill's content but not where to persist it, and no seed/bootstrap path exists for project skills (no catalogue `skills/authn/`, so the in-system `SkillStore.write` would refuse for lack of bootstrapped frontmatter).
The seed-face contract section is reworded to "the single write path for STORE facts", with the bundle named as the distinct second write path, so the two planes stay non-overlapping at the write boundary as well as in content.
Surgical by design: no absolute path, no repository coupling, no `docs/design` citation in the skill; the parametrized form preserves D237-4's location-agnosticism.
The content tier pins the location text.

### Resolved (operator ruling, 2026-09-19)

The missing-frontmatter case is NOT taken into account: it is a failure local to the skill domain and low risk, so `SkillStore._compose_procedure`'s refusal for a never-bootstrapped bundle stands unchanged.
A BOOTSTRAPPED project skill's procedure write already lands (the store composes from the project's own frontmatter and bumps the version), so the "the project authn skill may not be immutable" half of the operator's auth-store ruling is satisfied for every bundle the bootstrap created; the un-bootstrapped case remains the external bootstrap's job at the write location this decision pins.

## D237-10 - The reusable bootstrap prompt ships beside the skill

The external bootstrapper's first prompt is published as `skills/meta/authn-skill-writing/references/bootstrap-workflow.md`: the reusable, target-agnostic prompt with `<...>` placeholders (project id, target, login/signup URL, credentials, seed/read face, data root, skill name, meta-skill path) and the request-first anti-bot workflow.
It is the prompt form of the skill's mandatory block and defaults to request-based, taking the browser only on a defence signal - the correction of the e2e's first prompt, which presumed the browser.
The skill cites the file in its worked-example and references sections, so the existing cited-reference test resolves it; a content test pins the placeholders, the request-first default, the shared vocabulary, and the absence of any target name.

## D237-11 - The profile discipline mounts by name, not by id

The e2e surfaced a wording defect (not a code defect): the profile discipline said "Mount by id" while the command it gave is `--profile <profile-name>`, and D237-4 repeated "mount by id".
The CLI's `--profile` takes the profile NAME (the `profileId` also resolves, verified live, but the discipline as written mounts by name), and the store holds the name under `steel: {profile}`.
The wording is corrected to "Mount by name", P3 records "the profile name from the mint", and D237-4 is amended; a content test forbids "Mount by id" and requires "Mount by name".
The same correction is applied to the #221 records that carried the wording (`docs/design/browser-cli-221-decisions.md` D17, `docs/design/browser-cli-221-spec.md`), and the recon glossary's browser-profile entry now carries the mount-first ordering.

## D237-12 - Account identity is the credential, named `<email>-<minting_context>`

The e2e left two White Jotter accounts sharing one username and password, `whitejotter-signup` (procedure `sign-up`) and `whitejotter-signin` (procedure `sign-in`): a fork produced by treating `procedure` as an identity axis.
The account's identity is the credential it authenticates, and the NAME carries that identity: the tool contract (`AUTH_STORE_CONTRACT`), the meta skill's seed-face contract, and the reusable prompt now require `<email>-<minting_context>` (the credential username plus the run or flow that minted it, `first_authn_bootstrap`, `hunting_misauthr`, ...), assessed at write time.
The minting context is the run or flow, never the procedure, so sign-up and sign-in in one bootstrap share one account name and the second write collides on `duplicate_auth` to be merged.
The meta skill's "separate flows with separate accounts" instruction, its red-flag row, and the prompt's matching line are sharpened to "separate procedures; one account per credential identity".
The store did not yet enforce credential-identity uniqueness at the time of writing (the fork was storable under two names); the gate and the `procedure` cardinality (a single optional string cannot name two procedures) were recorded as open design questions and are resolved in the Resolved block below (D220-11).
Content tests pin the tool-contract markers and the meta-skill/prompt wording; the throwaway store-seam loop that showed two names sharing one username is deleted (it is the evidence for the open gate, not a regression test).

### Resolved (operator ruling, 2026-09-20)

- Hard identity gate: YES. The store refuses a create or seed whose credential username (default or any role) already belongs to another account, with the `duplicate_identity` tool envelope and HTTP 500 on the seed face; the repair is a ROLE on the existing account, never a second account. A fork is an agent that misread the record's role-assignment contract, not merely a naming miss. Decision recorded as D220-11 in `docs/design/auth-store-220-decisions.md`.
- `procedure` cardinality: ONE procedure. It stays a single optional string; a credential identity is one account and the label names the serving procedure, so no list is introduced.

## D237-13 - The browser fast path is inlined and the mechanics skill is cited (latency finding)

The magnific browser e2e ran 394 s wall, of which the transcript decomposes into ~108 s of tool execution and ~153 s of model gaps; the avoidable share was ~60-70 s, and it was concentrated in three primitives the bootstrapper re-derived live from `steel --help` because it had never been pointed at the operation-mechanics skill.
The measured offenders: a `navigate --wait-until networkidle` that timed out at 26 s (magnific never reaches network idle), three stale refs each costing a snapshot round-trip (~35 s) after `fill` calls, and fixed `sleep`s inside chained shell lines.
The root cause was a missing cross-reference, not a missing primitive: `skills/steel-browser/SKILL.md` already documents `batch`, `snapshot -i`, options-first encoding, `wait`, and the re-snapshot-after-navigate rule, and ships the reference scripts - but the bootstrap prompt told the agent to read only the authn meta skill.
Fix (three edits, all doc-level): (1) the bootstrap prompt gains `<mechanics_skill_path>` and instructs reading the mechanics skill (and its `references/` scripts) before the first browser step, "do not re-derive the steel CLI from `--help`"; (2) P3's verification line stops prescribing `wait --load networkidle` and instead uses `--wait-until load` plus a `wait --url/--text` condition, with the networkidle trap named; (3) the skill gains a "Browser fast path" block inlining the four habits - `snapshot -i`, `batch` to share a ref, options-before-the-`--`-boundary variadic encoding, and an observable `wait` over a fixed sleep.
The tool-level fold (D19 in `browser-cli-221-decisions.md`) is the complementary fix and lands by rebasing this branch onto `feat/221-browser-cli`.
Content tests pin the fast-path markers, the networkidle prohibition, and the prompt's mechanics-skill citation.

### D237-13 measurement (2026-09-21, re-run of the same magnific bootstrap)

A same-prompt re-run measured the fix; full record in `docs/design/authn-bootstrap-latency-237-experiment.md`.
The primitive fingerprint is clean and confound-resistant: `steel --help` re-derivation 5 -> 0, `networkidle` 1 -> 0, live stale-ref failures 3 -> 0, `batch` 0 -> 8, `snapshot -i` 0 -> 6, condition `wait` 0 -> 5, fixed `sleep` 8 -> 3.
Wall-clock did **not** improve (394 s -> 1168 s raw), and the cause is a target-side confound: magnific escalated to a visible reCAPTCHA Enterprise challenge that cost 251 s of human solving plus a 90 s recovery loop, larger than the effect the fix targets; the wall-clock result is therefore INCONCLUSIVE and no latency win is claimed in this ledger.
A new failure mode was observed from the fix-adjacent pattern: the agent replaced `sleep` with `wait --url /app`, but `/app` is reachable only after the out-of-band human reCAPTCHA solve, so the wait timed out three times (90 s) waiting on a human step it could not observe.
Follow-up applied: the mechanics rule now carries the qualifier - a `wait` never synchronises on an outcome gated by an out-of-band human action; wait on the challenge's own marker with a bounded timeout and escalate, instead.
The `steel_exec` D19 guard was not exercised by this run: the external bootstrapper drives the raw `steel` CLI, so only the skill-text half of the fix was measured.

## D237-14 - The browser bootstrap is fragile against reCAPTCHA scoring (grounded diagnosis)

*Diagnosed 2026-09-21 on the run-2 failure (a visible reCAPTCHA Enterprise challenge), following the diagnosing-bugs procedure.*

**The failure.** Run 2's fresh login was held by a visible reCAPTCHA Enterprise image challenge (400x580 frame), costing 251 s of human solving plus a 90 s blind-retry loop; the operator read the proximate cause as a low score.

**The loop (Phase 1).** `tests/e2e/harness/recaptcha_challenge_probe.py` drives the exact path under test - an optional profile, the homepage to `/log-in` route, the consent gate, the email-first form, and one submit - and detects the challenge's own frame without solving it: exit 0 GREEN (authenticated landing), exit 1 RED (challenge), exit 2 UNKNOWN.
It is red-capable (it asserts the exact symptom) and agent-runnable, and it is the closest available seam: the symptom is live and probabilistic, so no unit or integration seam can carry it.

**Reproduction (Phase 2).** The loop ran three times and did **not** reproduce the challenge (two single-submit runs and one retry-storm run, all GREEN; the storm never fired because the first submit succeeded).
The observed red is therefore 1 of 4 controlled-plus-observed attempts, and the honest reading is that the symptom is **intermittent**, consistent with a score near the threshold rather than a deterministic trigger; the loop's rate is too low to debug behaviourally without many credentialed attempts, each of which burns a login and further risks the account and the egress IP.
The minimised trigger from run 2 is: navigate `/log-in` (lands on the homepage), click the "Log in" link, dismiss consent, set the email, click Continue, set the password, click "Log in" - and then, in run 2, up to four blind submissions (three clicks plus a `requestSubmit()`) with 30 s `wait --url` timeouts between them.

**The safe path, proven.** Mounting the stored `magnific-authn` profile read-only and navigating to `/app` reached the authenticated landing with no login and no challenge (re-verified 2026-09-21), so the risky fresh login was also the unnecessary one.

**Grounded mechanisms.** Steel's own docs state that "Profiles persist browser identity, not network identity - pair with a dedicated IP for account-based agents", and name the failure mode the "impossible travel problem"; the CLI exposes `--proxy`, `--stealth` (humanize plus auto-CAPTCHA), `--session-solve-captcha`, and a `captcha` command family.
Measured directly: three sessions in one sitting egressed from three distinct datacenter ASNs (`216.246.40.79` CacheFly, `152.233.48.155` Datacamp, `64.34.81.170` Latitude.sh), with and without the profile mounted, while the user-agent stayed one value and the timezone stayed `America/New_York`.
The run-2 transcript supplies the interaction evidence: the fresh login ran on a disposable scratch profile (`magnific-scratch-tmp`, deleted afterwards), never wrote back to `magnific-authn`, used no `--stealth`, and retried the submit blindly.

**Implementation defects that contributed.**
1. No stable egress: proxy is off by default, sessions rotate datacenter IPs, and neither the store nor the profile key can express a pinned origin.
2. Fresh-login-by-default verification: the workflow re-authenticates even when a mounted profile already verifies, exposing the account to the most score-punished action for no information gain.
3. Disposable browser identity for the login: the login runs on an empty scratch profile, the least trustworthy identity, and its state is discarded.
4. No humanization: `--stealth` is never used, so interactions are fast and robotic.
5. No interaction cadence: repeated blind submits with fixed `sleep`s, themselves a bot signal.
6. No challenge protocol: no detection of the challenge's own marker, no bounded wait, no escalation - the agent improvised a viewer-URL prompt after minutes of retries.
7. Session lifetime versus a human in the loop: `--session-timeout 600000` expired mid-flow, and the default 120 s inactivity timeout can release the session while a human solves.
8. No network-identity continuity across mounts: even the safe mount path changes origin every time, so the authenticated profile is re-presented from a new network each run.

**Design risk report.** The systemic half is recorded as a Design Risk in `docs/design/recon-auth-gateway-223-spec.md` ("Network identity is not persisted with the browser profile"), because the same profile-rebind design governs the runtime gateway; the skill-and-prompt half is owned here.

**Seam finding (Phase 5).** There is no correct seam for a behavioural regression test of the symptom itself: it is live, third-party-scored, and intermittent, so the probe script is the regression vehicle and the fix hypotheses are recorded separately rather than locked into a unit test.

## D237-15 - Mount-first, and the non-reactive login discipline

*Implemented 2026-09-21 on the operator's ruling: proactive prevention only, no Steel-side solving, and the mount verification stays mandatory.*

The fix is three text-only edits, no schema change and no tool change.
The authn meta skill's profile discipline now orders the browser path: mount the stored profile read-only first, verify it against the authenticated landing, and log in only when the mount does not yield that landing - a missing OR unauthenticated mount being one fail-open trigger, mirroring the runtime gateway's D223-14 rule; that login runs on the account's own profile with `--update-profile` and is never disposable, so the warm identity (cookies and history) is written back rather than discarded.
The bootstrap prompt carries the same ordering for the external bootstrapper.
The mechanics skill carries the non-reactive hardening: submit once and wait on the condition rather than resubmitting blind, and size the session clock for a human step (`--session-timeout` covers a solve, `--inactivity-timeout` raised or `0` keeps the session alive while a person acts).
Explicitly excluded: any Steel-side CAPTCHA solving (`--stealth`'s auto-CAPTCHA half, `--session-solve-captcha`, the `captcha` family), because it is costly and does not port to a local Steel deployment; and any tool-layer guard, because the defended-target knowledge belongs to the procedure, not to the thin `steel_exec` gateway.
The residual score risk is the environment and network identity: the local Steel deployment that removes the `UNEXPECTED_ENVIRONMENT` and impossible-travel exposure is filed as #245, and the design risk stays recorded in `docs/design/recon-auth-gateway-223-spec.md` until that lands.
Content tests pin the ordering markers in both artifacts and the cadence and clock rules in the mechanics skill.
