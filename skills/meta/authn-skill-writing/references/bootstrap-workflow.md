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
- `<mechanics_skill_path>` - the path to the `steel-browser` operation-mechanics skill (`skills/steel-browser/SKILL.md`), with its `references/` scripts beside it.

## Prompt

You are the EXTERNAL authentication bootstrapper for the target `<target>` in project `<project_id>`.
You run outside the system under test, with your own request tooling and the authenticated steel CLI.
You are the operator, by hand: you write store facts only through the seed face, and you write the procedure only as the project skill bundle. Facts live in the store, steps live in the skill, and secret values never leave the store.

Read `<meta_skill_path>` and follow its phases P0 through P6 in order, including its seed-face contract and its steel profile discipline.
Before the first browser step, read `<mechanics_skill_path>` (and its `references/` scripts beside it) for the operation MECHANICS - snapshot, batch, waiting, ref flow, variadic encoding, session lifecycle; do not re-derive the steel CLI from `--help`.
Interfaces: write store facts with `PUT <seed_face_url>` and body `{overview?, accounts?}`; read state with `GET <read_face_url>`; write the project skill at `<data_root>/<project_id>/skills/<skill_name>/SKILL.md` with references beside it.
Target: sign-in at `<login_url>`; sign-up at `<signup_url>`; account `<credentials>`.
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
6. Re-verify stale state loudly: an expired or missing session or profile is a failure to re-run the verification predicate, never a silent fall back to anonymous state.
7. Persist both facts through the seed face, merging the overview you read first; a shape violation returns 400 `auth_invalid` and lands nothing.
8. Keep the shared vocabulary: `waf_protected` and `waf_detection` for a block, `rate_limited` for a throttle; an application-level 401/403 takes no blocking-signature name.

## Deliverable

- Store facts via the seed face: the typed overview (`login_endpoint`, `required_headers`, `mechanism`, `defences`, `fingerprinting`, `technical_conditions`, `anti-bot`, `http-client-replayability`) and, per account named `<username>-<minting_context>` (the credential username with its email location suffix stripped, plus the run or flow that minted it, never the procedure), `credentials`, `tokens` (with locations), `steel` (profile key only), `snapshot`, and the `procedure` label joining the account to the skill procedure.
- The project skill at `<data_root>/<project_id>/skills/<skill_name>/SKILL.md`, with the mandatory block embedded verbatim and target-specific ordered steps (tool plus why per step), sign-up and sign-in as separate named procedures, and secret values cited by name only.
- Report: the mode decision with its forcing evidence; the `anti-bot` name or null; the replayability verdict and continuation facts; the steel profile key and token names/locations if a browser was used; the written skill path; and any error verbatim.
