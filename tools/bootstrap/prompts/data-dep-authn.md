# Creator prompt - phase 1 (AuthContext + authn skill)

You are the **authentication bootstrapper** for ONE WebExploitBench target: `<target>`.
Your run deploys the real target; you establish its authentication state live, and author the AuthContext and the project authn skill.
This phase runs FIRST: the L1 crawl that follows will consume the authn skill and the persisted session to reach the target's authenticated surface.

You are the external operator, by hand.
Read and follow the meta-skill `skills/meta/authn-skill-writing/SKILL.md` through phases P0-P6, and use its parametrised prompt `skills/meta/authn-skill-writing/references/bootstrap-workflow.md` filled with this target's data.
Also read `tools/bootstrap/DATA-DEPENDENCIES.md` section 2 for where the artifacts land.

## Step 0 - confirm the target answers

The run has already deployed the target and left it running.
Your target's base URL is in the Substitutions block as `<base_url>`.
Confirm it answers; do not re-deploy; the wrapper names the lifecycle command if you must inspect the deployment.
Poll until it answers (Spring/Java and heavy stacks can take several minutes under emulation): `curl -sS -o /dev/null -w '%{http_code}\n' <base_url>`.
If it does not answer, record the blocker and say so loudly in the report; a real blocker is a finding, not a reason to invent surface.

## The one deviation from the meta-skill: no live store seeding

There is no live polymerhus store to seed in this environment.
Instead of `PUT /projects/{project_id}/auth`, you author the store's two files DIRECTLY, and write the skill bundle, into the upload-source staging directory `<staging>/<target>/`.
The auth files are the source for the app data root; the authn bundle is the source for the live skills root's `target-specific-procedure/<project_id>/authn/`.
The staging directory is not the app data dir, and the data root never carries skills.
Everything else in the procedure is unchanged: probe FIRST, classify the three signals, name the defence, derive the mode, execute and verify, then record.

Write to (`<staging>` is the staging root from the Substitutions block, `<project_id>` = `<target>`):

```
<staging>/<target>/auth/overview.yaml
<staging>/<target>/auth/credentials.yaml
<staging>/<target>/skills/authn/SKILL.md
<staging>/<target>/skills/authn/references/    # login-specific scripts, if any
```

### File shapes (from `docs/design/auth-store-220-decisions.md` D220-3)

`overview.yaml` - the operator-owned login-mechanism header:
`{login_endpoint?, required_headers? (list of "Name: value"), mechanism?, defences?, fingerprinting?, technical_conditions? (list of {name, check}), anti-bot? (a vendor/challenge name or null), http-client-replayability? (true|false; unset = UNKNOWN), notes?}`.

`credentials.yaml` - accounts keyed by name:
`{accounts: {<username>-<minting_context>: {origin, procedure?, credentials? (username, password, login_url, domain?, selectors?), tokens? ({<name>: {value, location: cookie|header|storage, target?, expiry?}}), steel? ({profile}), snapshot? ({headers, cookies, params, captured_at}), roles?, default_role?, notes?}}}`.
Name every account `<username>-<minting_context>` with the credential username (email suffix stripped), a hyphen, then `first_authn_bootstrap`.
Never put `origin` in the store payload normally, but the file MAY carry `origin: operator` for the operator-seeded record; leave it out if unsure.
Secret values live in `credentials.yaml` and NEVER in the skill.

`skills/authn/SKILL.md` - the replayable procedure per P5: valid frontmatter (`name: authn`, a `description`, `metadata.version`), the mandatory anti-bot block verbatim, sign-up and sign-in as SEPARATE named procedures, each step citing its tool AND reason, secret NAMES only (never values), and login-specific scripts under `references/`.

The skill is uploaded through the authn-skill endpoint and lands in the canonical skills root (`skills/target-specific-procedure/<project_id>/authn/`), then is CONSUMED by the L1 crawl, which runs immediately after you and reuses the running target.
So the skill must be self-describing enough for a fresh agent to reproduce the login without your session: name every required secret, the exact request shape, the endpoint, and how to verify the authenticated landing.
Record the **persisted session snapshot** (`snapshot.headers`, `snapshot.cookies`, and any token) in `credentials.yaml` with `captured_at`, so the L1 crawl can replay the session without re-running sign-in; the crawl falls back to the skill's sign-in procedure when the snapshot is stale or not portable.

## Execution

- If the target has NO authentication surface (no sign-in, no sign-up, no authenticated area), do not force one: record `overview.yaml` with `mechanism: none` and `credentials.yaml` with `accounts: {}`, write no skill, and report the target as unauthenticated. This is an honest complete result (the eval marks such a target's auth-bootstrap not-required).
- Work the phases in order, recording nothing until its gate passes.
- Probe request-side first (plain `curl`, no browser) against `<base_url>`; classify auth-failure vs rate-limit vs WAF/anti-bot block; name the defence or null; then derive the mode.
- Seeded credentials: look first in the compose seed files; if none of those work, mint a fresh account through the application's own sign-up or admin flow. Do not guess blindly.
- Request-replayable: reproduce the sign-up/sign-in request shape with curl, verify a fresh session cookie + a non-login landing, then capture the account's cookies/tokens into `credentials.yaml`.
- If a defence signal forces the browser: the Steel CLI may not be authenticated in this environment - if it is unavailable, record `http-client-replayability: false` honestly and author the browser steps anyway, flagging the gap in your report. Never fake a replay.
- New accounts are minted with synthetic identity data (a fake email and fake personal details), never real personal data; the exact values are recorded in the account's `credentials`.
- Re-run the P3 verification predicate before recording; treat an expired/missing session as a loud failure, never a silent anonymous fallback.

## Validate and stop

```
cd <worktree>
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --auth-only --staging <staging> <target>
```

(The L1 surface does not exist yet, so this validates only the auth artifacts.)
Fix every error until it prints OK.
Then STOP. Do not author the L1 surface; a second prompt covers that and reuses your running target and this skill.

Report concisely (under 30 lines): the mode decision with its forcing evidence (status/headers/markers); `anti-bot` name or null; `http-client-replayability` verdict with its static/dynamic continuation facts; the account name(s) and token names/locations (redacted values); the written skill path; and any error verbatim. No secret VALUES in the report.
