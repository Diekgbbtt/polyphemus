# Steel browser: session-only decisions (#395)

*Status: operator rulings recorded 2026-10-20. Implementation recorded 2026-10-21; the upstream CLI `--session-state` flag remains open, so live reuse is the current interactive fallback.*
*Supersedes D17 and its #395 amendment in `browser-cli-221-decisions.md`.*
*Supersedes the cloud-profile retention in `steel-profile-replacement-impact-map-395.md` and the two-primitive-pack proposal in `steel-session-first-395.md`.*
*Companion evidence: `docs/design/evidence/steel-359/t395-fingerprint-consistency.md`.*
*Companion impact map: `docs/design/steel-session-only-impact-map-395.md`.*

## 1. Operator rulings

The tool uses sessions only.
Profiles are retired from the tool in the cloud and in the local deployment.
The Steel product may keep profiles for other consumers; the tool does not use them.

The durable browser state is exactly:

- cookies;
- localStorage;
- sessionStorage;
- indexedDB.

Dimensions, proxy configuration, credentials configuration, extension IDs, history, cache, and the full fingerprint object are not first-class concerns.
The privileged application state that a resumed session needs is carried by the four state items above.

There is one unique `steel-browser` skill.
It is identical for the cloud and the local deployment.
It does not mention the deployment, the endpoint, the API key, `--local`, profiles, or `sessionContext`.
The agent remains blind to the infrastructure.

The internal wiring is runtime-agnostic.
Runtime selection is a deployment edge, not an agent decision.
A `steel` wrapper, or the `steel_exec` gateway, hides the mode from every command and script.

The only cloud-specific configuration attribute is `STEEL_API_KEY`.
The local deployment needs no API key.
`STEEL_BROWSER_API_URL` remains a generic runtime address, not a cloud attribute.
A deployment is configured when it has a key or an endpoint.

Fingerprint policy:

- The cloud platform may jitter browser parameters natively. That is accepted and requires no tool logic.
- The local deployment does not offer the cloud jitter controls.
- The tool must not randomise the user agent, viewport, or region.
- Cheap local user-agent consistency is implemented at the deployment boundary.
- The local deployment fixes one user agent and disables random fingerprint injection.
- Non-important attributes may vary.

Rate-limit policy:

- The crawl must not request jittered browser instances.
- Cloud-native jitter remains a platform behaviour, not a tool behaviour.
- A local fresh session does not change the fingerprint or the egress IP.
- The crawl prompt must not claim that a fresh local session creates a new fingerprint or region.

Two caveats are settled:

- Q5 is resolved by silent disregard.
  An old `steel.profile` reference is not read, warned about, aliased, or migrated.
  It may remain stale on disk.
  There is no compatibility branch for it.
- Q6 is resolved by authenticated replication, not state-only or cookie-only.
  The crawl attempts to replicate an authenticated session from cookies or other authentication material.
  It gates that attempt on application state or on the response to an authenticated part of the surface.
  Session state supplies application context; it is not authentication evidence by itself.

## 2. Why profiles were chosen

D17 chose profiles because they are a durable, server-side bundle.
The bundle held:

- a full Chrome user data directory;
- a server-generated fingerprint object;
- a user agent and viewport;
- proxy and credentials configuration;
- extension IDs;
- a status and retention lifecycle;
- a project and source-session association.

The strongest reason was fingerprint consistency.
The profile bound one generated fingerprint across sessions.
A session create does not expose a fingerprint object.
The session create exposes a user agent, dimensions, timezone, state, and a skip-fingerprint flag.

The initial decision was rational for the cloud.
The local OSS runtime has no profile store, so the same bundle was never portable.
The session-only design keeps the state and accepts the loss of the server-generated fingerprint, history, and cache.
The accepted loss is recorded in the risk register.

## 3. Domain model

| Term | Definition | Note |
|---|---|---|
| Session | A live Steel browser instance addressed by `--session <name>`. | The only runtime object. |
| Session state | The four captured browser stores: cookies, localStorage, sessionStorage, indexedDB. | The only durable browser state. |
| State reference | A per-account key that locates the stored session state. | Recommended field: `steel.state`. |
| Browser identity | Stable attributes such as user agent, viewport, timezone, and locale. | Not a stored first-class object. |
| Profile | The retired Steel durable bundle. | Not used by the tool. |

`sessionContext` is a wire field name.
It is not the session, and it is not the capability.
The design term is session state.

A session is short-lived.
Session state is durable.
The state reference connects an account to its state.
The browser identity is a deployment property, not a per-flow object.

## 4. Stored state

The state client stores only the four fields above.
Extra fields returned by the runtime are ignored, not persisted.
The state file is owner-only.
The file is written atomically.
The file is per account and one writer holds it at a time.
The state carries cookie values and target secrets, so it is treated like a credential.
It must never appear in logs, tool results, or traces.

The recommended location is a project-scoped, account-keyed file:

```
<data_root>/<project_id>/steel-state/<account>.json
```

The auth store holds only the reference, not the state.
Recommended account shape:

```yaml
steel:
  state: <account>
```

The state file is the WHAT.
The auth store is the index.
The browser is the live user.

## 5. Runtime wiring

The one skill teaches `steel ...` commands.
It does not teach `--local`.
It does not teach `profiles`.
It does not teach a cloud or local branch.

Mode selection happens below the skill:

- A `steel` wrapper is the single seam.
- It injects `--local` for every `steel browser` or `steel scrape` invocation when `STEEL_BROWSER_API_URL` is set.
- It does not inject the flag for `steel --version`, `steel login`, or a command that already carries `--local` or `--api-url`.
- After a local `browser start`, it sets the fixed user agent with `steel browser set useragent`.
- It discards that follow-up output so the start envelope stays unchanged.
- It is a deployment artifact, not skill content.

The wrapper is the preferred single seam because script text is not rewritten today.
It removes the `--local` branch from the skill and from the agent.
It also removes the regex insertion path in `steel_exec` once the wrapper is in place.
The gateway keeps its version, timeout, session-name, and variadic guards.

`steel_configured()` must return true when either the API key or the endpoint is present.
The local runtime ignores the key.
A local deployment without `STEEL_API_KEY` must still run the crawl.

## 6. Fingerprint consistency

The measured local behaviour is in `docs/design/evidence/steel-359/t395-fingerprint-consistency.md`.

Summary:

- The default local create generated Chrome 142 in one session and Chrome 145 in another.
- The default CLI sessions observed Chrome 142, Chrome 144, and Chrome 142 in three sampled starts.
- `skipFingerprintInjection` alone produced `HeadlessChrome/155`, which is a bot tell.
- A fixed `userAgent` produced the exact fixed user agent.
- The screen stayed 800x600 while the inner viewport followed the requested dimensions.

The cheap local design is deployment-level and uses the CLI primitive that already exists:

1. Set `SKIP_FINGERPRINT_INJECTION=1` on the local Steel API.
2. After a local `steel browser start`, the wrapper calls:

```
steel browser set useragent --local --session <name> --json '<one fixed UA>'
```

3. The fixed version should match the pinned browser image major version.
   The pinned local image currently reports HeadlessChrome 155.
   The fixed user agent uses Chrome/155 and removes the `Headless` token.

Live proof:

- before the set, the local session reported Chrome/144;
- the set command returned the Chrome/155 string;
- after the set, `navigator.userAgent` reported Chrome/155.

`CHROME_ARGS` was rejected as the carrier because the local API splits it on spaces, so a user-agent string cannot survive as one argument.
The CLI `set useragent` takes the quoted string as one variadic argument and works.

The window size remains a residual.
The local screen is 800x600 while the default inner viewport is 1920x992.
A local wrapper may also call `steel browser set viewport` with the native screen size, but that is a second optional consistency step, not required for user-agent stability.

The cloud deployment leaves the skip setting unset.
The cloud platform keeps its native jitter.
The tool never sends a random user agent.

The provider change is a removal:

- remove `_UAS`;
- remove `_VIEWPORTS`;
- remove `_REGIONS`;
- remove the random choice;
- do not pass `user_agent` or `dimensions` by default;
- do not pass `profile_id`.

## 7. Crawl auth and state

The crawl does not mount a profile.
It uses two inputs:

1. session state, as application context;
2. auth material, as the authentication attempt.

Auth material is cookies plus any other material the auth store records:

- cookies from the snapshot and cookie-located tokens;
- required headers and header-located tokens;
- storage-located tokens, grouped by their target origin.

The provider builds the create context from the stored state and merges the auth cookies and storage tokens.
Cookies and storage are merged into `sessionContext`.
Header material is scoped to the target origin through a route interceptor, not set as global extra headers.

The auth attempt is not trusted until a gate passes.
The gate has two accepted signals:

- application state: a replicated storage token or cookie is present in the live application state;
- authenticated surface response: a request to an authenticated part of the surface returns a response that is not a login redirect, a 401, or a 403.

The verification target defaults to the crawl target.
When the account or its skill records an authenticated landing URL, that URL is used instead.
The login endpoint from the overview is the negative marker, never the verification target.

The gate must use the authenticated surface, not a cookie name alone.
A cookie name can exist before login.
A login page can answer 200.
The gate therefore accepts either a verified application-state signal or a verified authenticated-surface response.
The authenticated-surface response is the stronger signal when it is available.

If the gate fails, the crawl records a typed `auth_replication_failed` and does not present the session as authenticated.
The crawl pod degrades to reduced coverage.
It does not silently run an anonymous crawl under an authenticated job.

The request-tool auth feed remains separate.
The browser projection is a new `project_browser_auth` beside `project_request_auth`.
It shares the token and snapshot rules and adds the storage-token projection.

The crawl captures session state before release.
The capture happens while the session is live.
The release always runs.
A failed capture is a typed failure and must not leave the session alive.

The programmatic path restores state through the SDK.
The interactive CLI path uses live reuse.
A new interactive CLI session can restore state only with an upstream CLI state flag.
The pinned CLI has no state flag.
This is the critical path in section 9.

## 8. Rate-limit and block handling

The provider no longer requests a random region, user agent, viewport, proxy, or stealth bundle.
`use_proxy` remains a caller input, but the local runtime strips it.
The local runtime also strips `stealthConfig`, `solveCaptcha`, and `region`.

The crawl prompt currently says that a fresh session is a new fingerprint and a new region.
That is false on the local runtime.
The prompt must say that a fresh session is a fresh browser context only.
A local fresh session does not change the egress IP or the configured user agent.

Recommended policy:
- no automatic jitter;
- at most one fresh context retry when a session-bound block is plausible;
- no claim of a new fingerprint or region;
- keep the captured coverage and abandon after the retry.

## 9. Risks

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| Local user-agent drift | High | High without config | Fixed deployment user agent and disabled random injection. |
| HeadlessChrome exposure when injection is disabled without a fixed user agent | High | Certain if `SKIP_FINGERPRINT_INJECTION=1` alone | The local wrapper sets the fixed user agent immediately after `start`, before navigation. |
| Provider random user agent mismatches the browser build | High | Certain today | Remove `_UAS` and never pass a random user agent. |
| Full fingerprint loss | High | Certain | Accept; session create has no fingerprint object. Document the reduction in anti-bot fidelity. |
| History and cache loss | Medium | Certain | Accept; only the four state fields are first-class. |
| Screen and inner-viewport mismatch | Medium | High today | Optional wrapper action: `steel browser set viewport` to the native screen. |
| CLI cannot restore state at `start` | High | Certain | Add upstream `--session-state`; else interactive restore is live-reuse only. |
| Local crawl fails without an API key | High | Certain if `steel_configured` is unchanged | Treat endpoint presence as configured. |
| State file leak | High | Medium | Owner-only permissions, atomic write, no logs, per-account file. |
| Concurrent writers on one account | Medium | Medium | One writer lock per account. |
| Old `steel.profile` remains stale on disk | Low | Certain | Silently disregard it; no warning, alias, or migration branch (Q5). |
| Auth material is stale or partial | High | Medium | Replicate the material, run the gate, and fail with `auth_replication_failed` when the gate fails. |
| Gate false positive | High | Medium | Prefer the authenticated-surface response; use application state as a corroborating signal, never a cookie name alone. |
| Gate false negative | Medium | Medium | Use the target and the login URL as the baseline; allow a configured authenticated-surface URL when the account records one. |
| Header auth material leaks to third-party origins | High | Medium | Scope injected headers to the target origin; do not set global extra headers for token material. |
| Storage token has no target origin | Medium | Medium | Skip the token and fail the gate loudly; the auth skill must record a target for storage tokens. |
| Cloud native jitter changes the user agent | Medium | Accepted | No tool logic; accept the platform behaviour. |
| One-skill wrapper misroutes cloud commands | Medium | Medium | Inject only for `browser` and `scrape`; pass through `--version` and login. |
| Docs and tests still assert profiles | Medium | Certain | The impact map lists every file; update in one change set. |
| `sessionContext` size or cloud support limits | Medium | Unknown | Measure; state only four fields; fail loud on restore rejection. |

## 10. Stale profile records

Existing `steel.profile` records are disregarded.
A cloud profile is a server-side user data directory, not a captured context.
A local profile never mounted.

There is no warning and no migration branch.
The old field may remain stale on disk.
No code reads it, aliases it, or reports it.
A record with only a profile reference behaves as a record with no browser state.
The next successful login captures state and writes `steel.state`.
The next crawl without state attempts auth-material replication and runs the gate.
No warning code is added, so no warning can become stale.

## 11. Resolved decisions

All frontier decisions were accepted on 2026-10-20.
Q5 and Q6 carry the operator caveats above.

| # | Decision | Resolution |
|---|---|---|
| Q1 | State reference shape | `steel.state` key. |
| Q2 | CLI state restore | Open upstream item: add `--session-state`. The current tool does not restore in the CLI; live reuse is the implemented interactive fallback. |
| Q3 | Local user-agent value | Match the pinned image major version; currently Chrome 155. |
| Q4 | Fresh-context retry | At most one, with no fingerprint or region claim. |
| Q5 | Existing profile records | Silently disregard. No warning, no alias, no migration branch, no compatibility path. |
| Q6 | Crawl auth source | Auth-material replication with a verification gate; not state-only and not cookie-only. |
| Q7 | Cloud user agent | Leave native cloud jitter. |
| Q8 | Local mode seam | The wrapper owns mode selection; the gateway keeps the grammar and lifecycle guards. |

## 12. Evidence

- Live local probe, 2026-10-20: default, skip, fixed UA 142, fixed UA 137.
- Local API `cdp.service.ts`: random fingerprint only when no user agent is supplied and injection is not skipped.
- Local API env: `SKIP_FINGERPRINT_INJECTION` accepts `1`; `CHROME_ARGS` is appended to the launch arguments.
- Local native browser: HeadlessChrome 155.
- Default generated user agent: Chrome 142 and Chrome 145 in separate sessions.
- CLI local sessions: Chrome 142, Chrome 144, and Chrome 142 in the sampled runs.
- Fixed `userAgent`: exact string observed in `navigator.userAgent`.
- The session create API has no fingerprint object.
- The CLI `start` has no state flag.
- The CLI `--session` is the live handle; `start` creates or replaces.
