# Steel profile replacement: capability, impact, and complexity map (#395)

*Status: analysis, 2026-10-19. No code changed by this document.*
*Scope: the local Steel runtime and the polymerhus browser tool. Cloud behaviour is the baseline, not the target.*
*Sources: `docs/design/browser-cli-221-spec.md` and `browser-cli-221-decisions.md` (D16, D17); `docs/design/steel-local-deployment-359-spec.md` (D359-7); `docs/design/steel-session-lifecycle-395-decisions.md`; `docs/design/auth-store-220-decisions.md`; `docs/design/evidence/steel-359/t395-local-capability-profile-gap.md`; `docs/design/evidence/steel-359/t395-oss-profile-research.md`.*
*Live checks: Steel CLI 0.5.0-preview.6 help and source; Steel Python SDK 0.19.0 `SessionCreateParams`; local Steel API 0.5.3 schema and controller; `steel_exec` source; eval kali runtime.*

## Bottom line

The tool uses 8 of the 14 profile features: name, mint, mount, persist, list, state, status verification, and the one-writer rule.
It does not use credentials, extensions, proxy binding, project scoping, import, or delete.
A full local profile service is therefore larger than the problem.

The two seams are asymmetric:

- The SDK accepts `sessionContext`; the crawl path can replace the profile mount with it.
- The CLI `start` has no `sessionContext` flag; the interactive path cannot restore state through the CLI.

The lowest-complexity local design is:

- live session reuse plus auth-store cookies for interactive;
- `sessionContext` for the crawl path;
- a loud refusal of the local profile flags.

That design is 140 to 275 lines of code and 330 to 540 lines of tests in this repository.
It keeps the agent interface unchanged and makes the capability loss visible.

The only seamless durable interactive option is an upstream CLI `--session-context` flag.
A local profile service is a compatibility facade over `sessionContext` and costs 930 to 1,620 lines of TypeScript plus an image fork.

## 1. Decision question

The local Steel OSS runtime has no profile store.
The browser tool currently uses profiles in two places:

1. The interactive auth path mounts a named profile before a login or a reuse flow.
2. The agentic crawl mounts the account's profile read-only while it crawls.

The question is not "can profiles be emulated".
The question is:

- Which profile functions does the tool actually need?
- Which other Steel capabilities can cover each function?
- What is the least complex replacement that keeps the agent interface seamless and the failure modes loud?
- What does each replacement cost in code, tests, and reliability?

## 2. Design invariants

The following invariants come from the existing design and must survive any replacement.

- One runtime address. `STEEL_BROWSER_API_URL` is the only selector; unset means cloud.
- One interactive seam. Agents reach the browser through `steel_exec` and the `steel-browser` skill.
- One crawl seam. The pipeline reaches the browser through the crawl pod and the in-process Steel provider.
- One auth store. The store holds WHAT (accounts, credentials, tokens, profile references); the skills hold procedures.
- Cloud behaviour stays byte-identical when the endpoint is unset.
- A local profile mount must never look like success.
- Browser state carries target secrets and must never be logged.
- The local runtime has no Profiles API, no Credentials API, no Files API, no managed proxies, and no managed CAPTCHA.
- `sessionContext` is the local state primitive; `persist` is a fixed shared directory, not a named profile.

## 3. Tool capability map

### 3.1 Capabilities and profile use

| ID | Tool capability | Agent-facing surface | Profile functions used | Criticality | Local profile need |
|---|---|---|---|---|---|
| T1 | Interactive session lifecycle | `steel_exec` -> CLI -> `steel-browser` skill | named identity, one live session | High | Optional |
| T2 | Interactive navigation and page reads | CLI commands | none | High | None |
| T3 | Interactive interaction | CLI commands and batch | none | High | None |
| T4 | Interactive authentication and state | CLI, auth store, authn skill | mint, mount, write-back, list | High | **Primary** |
| T5 | One-shot scrape | `steel scrape` | none | Low | None |
| T6 | Bounded spider | CLI loop over navigate | none | Low | None |
| T7 | Agentic crawl | pipeline -> crawl pod -> provider -> SDK | mount read-only | Medium | Optional |
| T8 | State persistence and teardown | profile or `sessionContext` client | mint, persist, state storage | High | **Primary** |
| T9 | Profile catalogue and admin | CLI `profile` family | list, import, sync, delete | Low | Admin only |
| T10 | Authn gateway | auth skill, auth store, authn loop | durable reference, validity | High | Reference only |
| T11 | Deployment and endpoint | compose, resolver, kali | none | High | None |
| T12 | Observability | Langfuse tool spans | none | Medium | Secret policy |

The profile is not one capability.
It is a bundle of identity, storage, lifecycle, and cloud tenancy.
Only part of that bundle is used.

### 3.2 Profile domain features actually used

| ID | Profile feature | Used by the tool | Where | Notes |
|---|---|---|---|---|
| P1 | Named profile identity (name to id) | Yes | auth store `steel.profile`, skill, CLI map | The name is the durable handle |
| P2 | Mint on first login | Yes | authn skill `start --profile --update-profile` | Cloud creates the profile |
| P3 | Mount read-only | Yes | crawl provider `profile_id`; interactive start | Crawl never writes back |
| P4 | Persist on release | Yes | interactive `--update-profile` | Release is the persistence call |
| P5 | Profile list | Yes | `catalogue.sh` | Name and id only; no status poll |
| P6 | Import from a local browser | No agent use | CLI admin | Not part of the recon flow |
| P7 | Delete | No agent use | CLI admin, local map only | Server state unaffected |
| P8 | Server-side browser state | Yes | the core value | Cookies, storage, history, cache |
| P9 | Status machine and readiness | Implicit | settle plus navigation verify | No CLI poll; 409 not handled explicitly |
| P10 | Project scoping and source session | No | cloud only | The tool scopes the name itself |
| P11 | Credentials configuration | No | cloud only | Auth store owns credentials |
| P12 | Extension IDs | No | cloud only | Not used |
| P13 | Proxy and fingerprint binding | No | cloud only | Session options are separate |
| P14 | One live session per profile | Yes, by rule | skill | No merge; last writer wins |

The tool uses P1 to P5, P8, P9, and P14.
It does not use P6, P7, P10, P11, P12, or P13.
A replacement therefore does not need the full cloud profile domain.

### 3.3 Ownership

The cloud profile aggregate is owned by the Steel Cloud Profiles service; the Python SDK and the CLI are clients.
The OSS API has no profile owner.
The closest OSS components are `session.service.ts` for `userDataDir`, `CDPService` for capture and injection, `ChromeContextService` for storage extraction, and `FileService` for session files.
None of them owns a profile aggregate, a status machine, or a durable catalogue.

An application-level replacement would be owned by two seams:

- `src/polymerhus/app` for the state client and optional registry;
- `src/polymerhus/recon/control/auth_feed.py` for projecting the stored state to the crawl provider.

The browser provider would be the only mount point.
The skills would own the procedure, not the state.

### 3.4 What the tool does not use

- Credentials injection through the Profile API. The auth store holds credentials and tokens.
- Extension IDs. The local runtime installs extensions at build time.
- Profile proxy configuration. The crawl provider passes proxy, region, user agent, and dimensions at session create.
- Profile fingerprint binding. The provider randomizes its own fingerprint, so a cloud profile fingerprint would conflict.
- Profile status polling. The CLI exposes no state poll; the skill uses settle plus navigation.
- Profile import, sync, and delete in normal agent work. These are operator admin commands.

This is important for the complexity estimate.
A local replacement that only covers named state plus mint, mount, write-back, and list is much smaller than a profile service.

## 4. Candidate replacement capabilities

### 4.1 Assessment summary

Scores are 1 (low) to 5 (high).
Complexity is engineering effort, not runtime cost.

| Candidate | Covers | Seam for agents | Reliability | Complexity | Verdict |
|---|---|---|---|---|---|
| S. `sessionContext` store | Cookies, localStorage, sessionStorage, indexedDB | SDK and HTTP; **not CLI `start`** | High if captured and pinned | 2 for crawl; 4 for interactive | Adopt for crawl |
| C. Auth-store cookies and tokens | Cookies and auth headers | Auth store plus CLI cookie set | High for cookie auth | 1 | Keep as auth source |
| L. Live session reuse | Full state while live | Existing named sessions | High within a flow | 1 | Adopt for interactive local |
| Z. CLI post-start injection | Cookies and storage keys | CLI commands, one per item | Medium; lossy | 3 | Fallback only |
| Y. Upstream CLI `--session-context` | Full `sessionContext` | CLI, same grammar | High | 3 external | Best if durable interactive state is required |
| P. `persist` or `userDataDir` | Full Chrome profile | API/SDK only; fixed path | Low; shared | 1 code, 4 risk | Reject |
| E. Playwright `storageState` | Cookies and localStorage | Python only | Medium | 2 crawl; 4 interactive | Reject; S is better |
| F. Raw CDP storage | All four state classes | New driver | Medium | 4 | Reject; S wraps it |
| D. Local profile service | Full profile facade | CLI `--profile` | High if built | 5 | Reject unless a product requirement |
| G. Cloud profiles | Full | CLI and SDK | High | 1 local | Keep cloud; guard local |

### 4.2 Coverage matrix

`yes` means the candidate covers the feature for the tool.
`partial` means it covers the common case with a known loss.
`no` means it does not cover the feature.

| Profile feature | S | C | L | Y | P | D | G |
|---|---|---|---|---|---|---|---|
| P1 name | partial: file name | partial: account | partial: session name | partial: file name | no | yes | yes |
| P2 mint | partial: capture after login | partial: token write | no | partial: capture | no | yes | yes |
| P3 mount | yes: SDK and HTTP | partial: cookies | yes: live only | yes: CLI | no | yes | yes |
| P4 write-back | partial: capture again | partial: auth store write | no | partial: capture | no | yes | yes |
| P5 list | partial: registry | partial: auth store | partial: sessions | partial: registry | no | yes | yes |
| P8 state | yes: four classes | partial: cookies | yes: live only | yes: four classes | partial: shared | yes | yes |
| P9 status | no | partial: auth status | partial: live | no | no | yes | yes |
| P14 one writer | partial: file lock | partial: store lock | yes: one session | partial: file lock | no | yes | yes |

### 4.3 `sessionContext` (S)

`sessionContext` is the local API's native state field.
The schema carries four classes:

- cookies;
- localStorage by origin;
- sessionStorage by origin;
- indexedDB by origin.

The create path injects cookies through CDP.
It registers a frame navigation handler for the storage classes.
The client exists in `src/polymerhus/app/steel_session_state.py`.
The client captures, stores atomically, releases, and restores.

**What it covers**

- The state that makes a returning user: cookies and site storage.
- The state that carries client-side tokens: localStorage and sessionStorage.
- The state that carries some application data: indexedDB.

**What it does not cover**

- HTTP cache and history.
- Service worker registrations and caches.
- Browser extensions.
- The cloud profile status machine and 30-day reaper.
- A named catalogue. A name-to-file registry must be supplied by the caller.
- Fingerprint binding. The context does not carry the user agent or viewport.
- A per-profile write lock. One writer must be enforced by the caller.

**Seam**

- The SDK exposes `session_context` on `SessionCreateParams`.
- The local HTTP API accepts `sessionContext` on `POST /v1/sessions`.
- The CLI `start` does **not** expose a session-context flag.
- The CLI `start` always creates a fresh session; it stops an existing local daemon and recreates.
- The CLI cannot attach to an API-created remote session.
- Therefore `sessionContext` is seamless for the crawl provider and the state client, and **not seamless for the interactive CLI**.

**Reliability**

- High when the context is captured after the authenticated navigation.
- Medium when the context is stale; cookies expire and storage keys rotate.
- Medium when the session uses a different user agent or viewport from the capture.
- Risk of large IndexedDB payloads in the create body.
- The context contains secrets and must be stored with owner-only permissions.

**Complexity**

- Crawl path: 100 to 150 lines of code plus 200 to 300 lines of tests.
- Application-level registry: optional; 80 to 120 lines if a name-to-file catalogue is required.
- Interactive path: not available without a new CLI seam or a new driver.

**Verdict**

Adopt for the crawl path.
Do not claim it as the interactive replacement until the CLI can accept it.

### 4.4 Auth-store cookies and tokens (C)

The auth store already holds cookies, header tokens, and storage-located tokens.
`auth_feed.project_auth_cookies` projects the cookie subset to the crawl provider.
The crawl provider seeds `context.add_cookies` before navigation.
This path already authenticates the crawl when the profile is absent.

**What it covers**

- Session cookies and header tokens.
- The auth material that most recon flows need.

**What it does not cover**

- localStorage, sessionStorage, and indexedDB beyond individual named tokens.
- Browser cache, history, and anti-bot warmth.
- A server-side state snapshot.

**Seam**

- The auth store tool is already agent-facing.
- The crawl provider already consumes the cookie subset.
- The interactive CLI can set cookies one at a time through `steel browser cookies set`.

**Reliability**

- High for cookie-based authentication.
- Medium when the target binds auth to localStorage or IndexedDB.
- Cookie expiry is visible through the auth store status and the verification step.

**Complexity**

- Zero new code for the crawl path; it already works.
- Interactive cookie seeding requires a skill procedure or a small helper.
- 30 to 60 lines of skill content; 3 to 5 tests.

**Verdict**

Keep as the primary auth source.
Use it for crawl when no full context is stored.
Use it for interactive only when a live session cannot be kept.

### 4.5 Live session reuse (L)

The skill already supports named sessions and catalogue checks.
A live session keeps the full browser state: cookies, storage, cache, history, and the current page.
The agent can continue the flow across tool calls by reusing the same name.

**What it covers**

- Full state while the session lives.
- No serialization, no restore, no secret file.

**What it does not cover**

- State across a release, a timeout, a crash, or a process restart.
- State across separate jobs or agents.
- A durable account identity.

**Seam**

- Already part of the interactive skill.
- No code change.

**Reliability**

- High within a flow.
- The session timeout and inactivity timeout are the limits.
- An orphaned session is the main failure mode; the stop owner and catalogue check already cover it.

**Complexity**

- Zero code.
- 30 to 50 lines of skill wording; 2 to 3 tests.

**Verdict**

Use as the default interactive local state mechanism.
Accept the loss of cross-session durability.

### 4.6 CLI post-start injection (Z)

This candidate starts a fresh session, then writes cookies and storage through CLI commands.
`steel browser cookies set` takes one cookie per call.
`steel browser storage local set` and `storage session set` take one key per call.

**What it covers**

- Cookies with name, value, domain, path, secure, and httpOnly.
- localStorage and sessionStorage keys, one at a time.

**What it does not cover**

- Cookie `sameSite`, expiry, partition keys, and priority.
- IndexedDB.
- Bulk restore.
- A secret-safe interface; the values appear in command arguments.

**Seam**

- Uses the existing CLI.
- Requires a helper script that parses the stored context and loops.
- The browser must navigate to each origin before setting that origin's storage.

**Reliability**

- Medium.
- A partial cookie set can produce a half-authenticated session.
- A missing `sameSite` can change browser behaviour.
- The operation is slow for large jars.

**Complexity**

- 100 to 180 lines of shell or Python helper.
- 5 to 8 tests.
- No external dependency.

**Verdict**

Fallback only.
Do not call it a profile replacement.

### 4.7 Upstream CLI `--session-context` (Y)

The CLI already sends `profileId` and `persistProfile`.
It does not send `sessionContext`.
The daemon protocol carries create options to the daemon.
The API client builds the create body.

A `--session-context <file>` option would add:

- one field in `start.rs`;
- one field in `DaemonCreateParams`;
- one field in `CreateSessionOptions`;
- one branch in `build_create_body`;
- one read of the JSON file before daemon spawn.

The daemon and the API already understand the field.
The CLI would not need a new state driver.

**What it covers**

- Full `sessionContext` through the existing CLI grammar.
- The skill's current local advice becomes executable.

**What it does not cover**

- A named registry; the caller still supplies a file path.
- A status machine; the caller still verifies.

**Seam**

- Perfect: same `start` command, one new flag.
- The agent can pass a path written by a helper or the state client.

**Reliability**

- High; it is the same API field the SDK uses.
- The CLI must read and validate the JSON before creating the session.

**Complexity**

- 120 to 180 lines of Rust plus tests, upstream.
- 2 files in this repo for the pin bump.
- 50 to 80 lines of skill content.
- One new CLI release and one pin review.

**Verdict**

The best long-term option if durable interactive state is required.
Do not build a local profile service before asking upstream for this flag.

### 4.8 `persist` and `userDataDir` (P)

The local API accepts `persist` and `userDataDir`.
`persist: true` resolves to one fixed directory: `/app/api/user-data-dir`.
An explicit `userDataDir` is not honored as a path; any truthy value selects that fixed directory.
The directory is on the container overlay, not the durable volume, and every persistent session shares it.

**What it covers**

- A full Chrome profile, including cache and history, in one global directory.

**What it does not cover**

- Per-account isolation.
- Named profiles.
- Durability across a container rebuild.
- Concurrency beyond one session.
- Reachability from the CLI; `start` has no `--persist` or `--user-data-dir`.

**Seam**

- API and SDK only.
- The CLI cannot use it.

**Reliability**

- Low in a multi-account eval.
- One flow's cookies leak into the next.
- The data is lost on a rebuild.

**Complexity**

- Zero code.
- High operational risk.
- A per-profile directory would require an API patch.

**Verdict**

Reject.
It is not a profile, and it is not safe for isolation.

### 4.9 Playwright `storageState` (E)

Playwright can export cookies and localStorage origins.
The crawl provider already uses Playwright.
It could capture and restore storage state without the HTTP client.

**What it covers**

- Cookies and localStorage.

**What it does not cover**

- sessionStorage.
- IndexedDB.
- The CLI path.

**Seam**

- Python provider only.
- A new interactive driver would be required for the CLI path.

**Reliability**

- Medium for crawl; worse coverage than `sessionContext`.
- No benefit over the API field.

**Complexity**

- 60 to 100 lines for the crawl path.
- High for interactive.

**Verdict**

Reject.
`sessionContext` is the better primitive.

### 4.10 Raw CDP storage (F)

A CDP client can read and write cookies, DOM storage, and IndexedDB.
The local API already implements this internally.
Reimplementing it in the tool adds a new driver and duplicates upstream code.

**What it covers**

- All four state classes.

**What it does not cover**

- A CLI seam.
- A named registry.

**Seam**

- New Python or Node driver.
- Not the CLI.

**Reliability**

- Medium; the code is subtle and version-bound.

**Complexity**

- 200 to 400 lines plus tests.

**Verdict**

Reject.
Use the API field.

### 4.11 Application-level profile registry (D-app)

This is a polymerhus module, not a Steel API module.
It stores a name, a context file, and metadata.
It lists names and loads a context for the crawl provider.

**What it covers**

- Named state for crawl and programmatic sessions.
- A catalogue for agents.
- A place for `captured_at`, `verified_at`, and account binding.

**What it does not cover**

- The CLI interactive path.
- A server-side status machine.
- The `--profile` flag.

**Seam**

- Internal to the crawl path.
- The interactive skill cannot use it without a CLI seam.

**Reliability**

- High for crawl if it uses a per-account lock and atomic writes.
- The existing `steel_session_state` client already provides the capture, store, and restore primitives.

**Complexity**

- 150 to 250 lines plus tests.
- No new service, no image build.

**Verdict**

Adopt only as the crawl/state store, not as a profile service.
The auth store can hold the reference; a separate registry is optional.

### 4.12 Steel API profile service (D-api)

This is a new module inside the Steel API image.
It would implement profile routes, metadata, zip or JSON storage, status, TTL, and session hooks.
It would make the CLI `--profile` flag work locally.

**What it covers**

- Full cloud-compatible profile semantics.
- The existing CLI interface.
- A server-side catalogue.

**What it does not cover**

- The fixed `userDataDir` behavior without a session service patch.
- The cloud profile's 300 MB and 30-day semantics without a database and object store.

**Seam**

- CLI and SDK, if the routes match the cloud contract.
- The local API's `profileId` field would need to resolve to a stored context.

**Reliability**

- High if built and tested like the cloud feature.
- High maintenance: a fork of the upstream API image.

**Complexity**

- 1,200 to 2,500 lines of TypeScript and tests.
- A session service patch of 100 to 200 lines.
- A custom image and a pin.
- 30 to 50 tests.
- Ongoing divergence from upstream.

**Verdict**

Reject for the current local/eval requirement.
It is a compatibility facade over `sessionContext` with a large maintenance cost.

### 4.13 Cloud profiles (G)

The cloud runtime keeps the full profile feature.
No local code changes are needed for the cloud path.
The local branch must be explicit and guarded.

**Verdict**

Keep unchanged.

## 5. Impact map by candidate

### 5.1 `sessionContext` for the crawl path

This is the cleanest replacement because the provider is internal and the SDK supports the field.

| Component | Change | Estimate |
|---|---|---|
| `src/polymerhus/recon/crawl/steel_provider.py` | Add `session_context` to `_random_session_opts`, `_create_steel_session`, `SteelCrawlProvider`, and `_steel_crawl_start`. Preserve it across the fallback ladder. | 40 to 60 lines |
| `src/polymerhus/recon/crawl/steel_client.py` | Thread the context through `_default_client_factory` and `get_crawl_tools`. | 10 to 15 lines |
| `src/polymerhus/recon/crawl/crawl_agent.py` | Add the context parameter and pass it to the tool factory. | 5 to 10 lines |
| `src/polymerhus/recon/crawl/crawl_pod.py` | Read `extra["steel_context"]` and pass it to the run function. | 5 to 10 lines |
| `src/polymerhus/recon/control/auth_feed.py` | Add `project_steel_context`; keep cookies as the fallback. | 10 to 15 lines |
| `src/polymerhus/recon/control/pipeline.py` | Project the context for agent-mode crawl. | 5 to 10 lines |
| `src/polymerhus/app/auth/records.py` | Accept `steel: {context}` as an alternative to `steel: {profile}`. | 10 to 15 lines |
| `src/polymerhus/app/auth/tool.py` | Update the account schema description. | 3 to 5 lines |
| Tests | Provider, client, pod, agent, feed, pipeline, records. | 200 to 300 lines |

**Behavioral rules**

- A supplied context must not silently degrade to an anonymous session.
- If the context create fails, the provider should log the failure and fall back to the cookie path only when cookies are present.
- If neither context nor cookies is present, the crawl runs anonymously and the pod records reduced coverage.
- The context file path must be per-account and outside a shared temp directory.
- The provider must pin or carry the user agent and viewport used at capture time.

**Why this is not enough for interactive**

The CLI `start` has no session-context field.
The daemon creates the remote session itself.
The CLI cannot attach to an API-created remote session.
A live interactive session therefore starts fresh.
The skill's sentence "pass the stored JSON as `sessionContext` on the next create" is not executable through the CLI.

### 5.2 Auth-store cookies for the interactive path

| Component | Change | Estimate |
|---|---|---|
| `skills/steel-browser/SKILL.md` | Teach the local branch: reuse the live session; seed cookies with `cookies set` only when needed. | 30 to 50 lines |
| `skills/meta/authn-skill-writing/SKILL.md` | Replace the profile mount procedure with a local branch. | 30 to 50 lines |
| `skills/meta/authn-skill-writing/references/bootstrap-workflow.md` | Replace the profile mint/mount steps. | 20 to 30 lines |
| `skills/steel-browser/references/profile-mount.sh` | Keep the capability guard; mark the whole script cloud-only. | 5 to 10 lines |
| `skills/steel-browser/references/catalogue.sh` | Stop printing profiles on a local runtime. | 5 to 10 lines |
| Tests | Skill rule, bootstrap walkthrough, mocked actions. | 80 to 150 lines |

**Limits**

- `cookies set` sets one cookie per call.
- It does not expose `sameSite`, expiry, partition keys, or priority.
- It cannot set IndexedDB.
- It exposes values in command arguments; the skill must not echo them.

### 5.3 Live session reuse for the interactive path

| Component | Change | Estimate |
|---|---|---|
| `skills/steel-browser/SKILL.md` | Make reuse the local default; keep the stop owner and catalogue proof. | 20 to 30 lines |
| `skills/meta/authn-skill-writing/SKILL.md` | Local branch: open once, operate, close; re-login on loss. | 20 to 30 lines |
| `skills/steel-browser/references/session-lifecycle.sh` | No change; it already surveys, opens, uses, and stops. | 0 |
| Tests | Skill rule and live interactive guard. | 30 to 60 lines |

**Limits**

- No state across a release or restart.
- The session timeout is the durability window.
- A long human step needs `--inactivity-timeout 0` or a stop owner.

### 5.4 CLI post-start injection

| Component | Change | Estimate |
|---|---|---|
| `skills/steel-browser/references/session-state.sh` (new) | Parse a stored context; navigate per origin; set cookies and storage; verify. | 100 to 180 lines |
| `skills/steel-browser/SKILL.md` | Document the helper and its limits. | 20 to 30 lines |
| `kali/mcp_server.py` | No change; scripts run verbatim. | 0 |
| Tests | Scaffold and shell tests. | 50 to 100 lines |

**Limits**

- Partial state only.
- Slow and error-prone.
- Secrets in process arguments.

### 5.5 Upstream CLI `--session-context`

| Component | Change | Estimate |
|---|---|---|
| Steel CLI `src/commands/browser/start.rs` | Add the flag and read the JSON file. | 20 to 30 lines |
| Steel CLI `src/browser/daemon/protocol.rs` | Add the field to `DaemonCreateParams`. | 5 to 10 lines |
| Steel CLI `src/api/session.rs` | Add the field to `CreateSessionOptions` and the create body. | 10 to 15 lines |
| Steel CLI tests | Start, daemon, and create-body tests. | 60 to 100 lines |
| `kali/postrun.sh` | Bump the pin. | 1 line |
| `kali/mcp_server.py` | Bump the version pin. | 1 line |
| `skills/steel-browser/SKILL.md` | Document the local restore flow. | 20 to 30 lines |
| Tests | Pin, skill rule, canonical actions. | 30 to 60 lines |

**Why this is the best interactive option**

- It preserves the CLI grammar and the skill's operation mechanics.
- It uses the API field that already exists.
- It avoids a new browser driver in the kali image.
- It keeps the agent interface seamless.

**Cost**

- It depends on an upstream release.
- A new pin is a skill-review event.
- The local eval would need the new CLI binary.

### 5.6 Local profile service

| Component | Change | Estimate |
|---|---|---|
| `api/src/modules/profiles/*` (new) | Routes, controller, service, schema, metadata store, state store, status, TTL. | 800 to 1,500 lines |
| `api/src/services/session.service.ts` | Resolve `profileId` to a stored context; honor the per-profile state; keep `userDataDir` behavior. | 100 to 200 lines |
| `api/src/plugins/steel-browser-plugin.ts` | Register the profiles module. | 5 to 10 lines |
| `api/src/openapi/schemas.json` | Add the routes and schemas. | 50 to 100 lines |
| `eval/deploy/steel/docker-compose.steel.yml` | Add the state volume. | 1 to 3 lines |
| Tests | Route, service, session hook, storage, status, TTL. | 500 to 900 lines |
| Image build and pin | Custom image, digest, reproducibility. | Operational |

**Why this is not recommended**

- The local API ignores an explicit `userDataDir`.
- A profile service must therefore store and inject `sessionContext`, which is the same capability as S.
- The only extra value is the `profileId` interface.
- The same interface can be provided by the upstream CLI flag at a fraction of the cost.
- The service forks the upstream image and must track upstream changes.

### 5.7 Cloud profiles and the local guard

| Component | Change | Estimate |
|---|---|---|
| `kali/mcp_server.py` | Refuse `start --profile` and `--update-profile` when the local endpoint is set. | 15 to 25 lines |
| `src/polymerhus/recon/crawl/steel_provider.py` | Log or raise when `profile_id` is supplied to a local runtime; prefer a context or cookies. | 10 to 20 lines |
| `skills/steel-browser/SKILL.md` | State the local branch and the refusal. | 10 to 20 lines |
| `tests/test_steel_exec.py` | Add refusal tests. | 30 to 50 lines |
| `tests/recon/crawl/test_crawl_auth.py` | Add the local no-profile behavior. | 30 to 50 lines |

**Why the guard is necessary**

- A local `start --profile` currently succeeds and mounts nothing.
- The authn procedure treats a successful start as a mounted profile.
- The agent can then crawl anonymously while believing it is authenticated.
- `profile-mount.sh` guards only the script path; a direct command still no-ops.
- The tool boundary must make the loss loud.
- The `steel_exec` guard covers command mode; script text stays verbatim, so the skill and `profile-mount.sh` cover the script path.

## 6. Exhaustive component inventory

Legend: D = direct profile logic, I = indirect or threaded, N = no profile touch.

| Component | Role in the Steel tool | Touch | Recommended change | Full-replacement change |
|---|---|---|---|---|
| `kali/mcp_server.py` | `steel_exec` gateway; CLI guards; local flag injection | I | Add local profile refusal; no other change | Add state flag passthrough |
| `kali/postrun.sh` | Pinned CLI install | N | None | Pin bump if Y |
| `skills/steel-browser/SKILL.md` | Interactive operation mechanics | D | Local branch: live reuse; no false sessionContext claim | New restore procedure |
| `skills/steel-browser/references/profile-mount.sh` | Profile mount and guard | D | Keep cloud-only; guard already present | Rewrite for local state |
| `skills/steel-browser/references/catalogue.sh` | Session and profile survey | D | Hide profiles on local | List local state names |
| `skills/steel-browser/references/session-lifecycle.sh` | Named session lifecycle | N | None | None |
| `skills/steel-browser/references/stop-owner.sh` | Dead-man stop | N | None | None |
| `skills/steel-browser/references/extract-reads.sh` | Cookie and storage reads | I | Use for state capture | Use for state capture |
| `skills/steel-browser/references/other scripts` | Navigation, interaction, scrape, spider, eval | N | None | None |
| `skills/meta/authn-skill-writing/SKILL.md` | Login procedure authoring | D | Local branch; no profile mint/mount | New state procedure |
| `skills/meta/authn-skill-writing/references/bootstrap-workflow.md` | Bootstrap steps | D | Local branch; cookies and live session | New state steps |
| `src/polymerhus/app/steel_endpoint.py` | Runtime address resolver | N | None | None |
| `src/polymerhus/app/steel_session_state.py` | Capture, store, release, restore | I | Use for crawl/eval | Use for all programmatic paths |
| `src/polymerhus/app/auth/records.py` | Account schema and `steel` validation | D | Accept `steel.context` or omit `steel` | Profile-compatible schema |
| `src/polymerhus/app/auth/store.py` | Account store and merge | I | No profile-specific change | No change |
| `src/polymerhus/app/auth/tool.py` | Agent-facing auth tool | D | Describe the local branch | Describe profile parity |
| `src/polymerhus/app/llm/skills.py` | Skill loading and role mapping | I | None | None |
| `src/polymerhus/app/observability/langfuse_tracing.py` | Tool spans and payload caps | I | Ensure state values are not logged | Same |
| `src/polymerhus/recon/config.py` | `STEEL_API_KEY` and crawl knobs | I | None | None |
| `src/polymerhus/recon/control/auth_feed.py` | Project cookies and profile key | D | Add `project_steel_context` | Keep profile projection |
| `src/polymerhus/recon/control/authn_loop.py` | Probe and verdict state machine | I | None; procedure changes in the skill | None |
| `src/polymerhus/recon/control/job_agent.py` | Crawl pod routing | I | None | None |
| `src/polymerhus/recon/control/jobs.py` | `steel_crawl` job spec | I | None | None |
| `src/polymerhus/recon/control/pipeline.py` | Account resolution and `extra` projection | D | Project context for agent crawl | Keep profile projection |
| `src/polymerhus/recon/crawl/steel_provider.py` | Session create, CDP, crawl tools | D | Add `session_context`; guard local profile | Keep profile and add context |
| `src/polymerhus/recon/crawl/steel_client.py` | Provider factory and tool list | D | Thread context | Thread profile and context |
| `src/polymerhus/recon/crawl/crawl_agent.py` | Crawl adapter | D | Thread context | Thread profile and context |
| `src/polymerhus/recon/crawl/crawl_pod.py` | Crawl node and `extra` | D | Read `steel_context` | Read both |
| `src/polymerhus/recon/crawl/crawl_agentic.py` | ReAct loop | N | None | None |
| `src/polymerhus/recon/domain/parsers/steel_parser.py` | Manifest parser | N | None | None |
| `src/polymerhus/analysis/anatomy.py` | Deep webpage probe gated on Steel | I | None | None |
| `eval/deploy/steel/docker-compose.steel.yml` | Local runtime | N | None | Add state volume |
| `eval/OPERATOR.md` | Deployment instructions | I | Record the local state policy | Record the profile service |
| `docs/design/browser-cli-221-spec.md` | #221 specification | D | Amend D17 for the local branch | Amend for local profiles |
| `docs/design/browser-cli-221-decisions.md` | D16, D17, D223 references | D | Amend D17 | Amend D17 |
| `docs/design/steel-local-deployment-359-spec.md` | #359 deployment and portability | D | Keep D359-7; note the CLI gap | Keep |
| `docs/design/steel-session-lifecycle-395-decisions.md` | #395 lifecycle | D | Note the interactive gap | Note parity |
| `docs/design/auth-store-220-decisions.md` | Auth store schema | D | Add the local state reference | Keep profile |
| `src/polymerhus/recon/CONTEXT.md` | Glossary | D | Correct the local state claim | Update |
| `src/polymerhus/app/CONTEXT.md` | App seams | D | Correct the local state claim | Update |

### 6.1 Test inventory

Profile or state relevant test files:

| Test file | Focus | Direct profile references |
|---|---|---|
| `tests/recon/crawl/test_crawl_auth.py` | Crawl auth, profile mount, cookies | 9 |
| `tests/recon/test_auth_feed.py` | Cookie and profile projection | 6 |
| `tests/recon/crawl/test_steel_provider_cookies.py` | Cookie seeding and provider options | 12 |
| `tests/recon/crawl/test_steel_client.py` | Factory threading | 8 |
| `tests/recon/crawl/test_crawl_pod.py` | Pod `extra` and best-effort crawl | 11 |
| `tests/recon/crawl/test_crawl_agent.py` | Adapter threading | 5 |
| `tests/recon/test_pipeline.py` | Account projection | 2 |
| `tests/app/test_auth_records.py` | `steel` schema | 6 |
| `tests/app/test_auth_store*.py` | Store merge and read | 4 |
| `tests/test_steel_profile_guard.py` | `profile-mount.sh` refusal | 3 |
| `tests/test_steel_session_state.py` | State client | 0 |
| `tests/integration/test_steel_session_state_http.py` | State HTTP | 0 |
| `tests/e2e/test_steel_session_state_live.py` | Live restore | 0 |
| `tests/e2e/test_steel_interactive_local.py` | Live interactive | 1 |
| `tests/e2e/test_authn_bootstrap_walkthrough.py` | Auth procedure | 8 |
| `tests/e2e/test_steel_canonical_actions_mocked.py` | Reference scripts | 1 |
| `tests/test_steel_skill_rule.py` | Skill local rule | 1 |
| `tests/test_steel_exec*.py` | Gateway guards | 0 |
| `tests/e2e/test_authenticated_crawl_e2e.py` | Authenticated crawl | 0 |

The listed test files total 3,603 lines.
They contain about 77 profile-related references.
Most of those references are assertions about threading, not browser behaviour.

## 7. Complexity quantification

### 7.1 Method

The existing code is counted with `wc -l`.
Direct profile references are counted with a fixed pattern over `src`, `kali`, `skills`, and `tests`.
The baseline is:

- 60 direct references to `profile_id`, `steel_profile`, `persist_profile`, and the profile flags across `src`, `kali`, `skills`, and `eval`;
- 60 direct references to the same profile terms in `tests`, and about 77 profile-related references in the listed test files;
- 14 direct profile references in the skills tree;
- 4,631 lines across the Steel source modules, not all profile-specific;
- 3,603 lines across the listed test files, not all profile-specific.

New code is estimated from comparable modules:

- `steel_session_state.py`: 256 lines for a typed HTTP client with tests.
- `auth_feed.py`: 287 lines for projection and resolution.
- `crawl_pod.py`: 300 lines for a graph node.
- `mcp_server.py`: 589 lines for the gateway and guards.

The estimates are ranges because the final shape depends on the chosen registry and test depth.
The test estimates assume one unit test per behavior and one integration test per seam.

### 7.2 Scenario A: recommended local design

This scenario keeps cloud profiles unchanged and uses:

- live session reuse plus auth-store cookies for interactive;
- `sessionContext` for the crawl path;
- a local profile refusal at the gateway;
- no local profile service.

| Work item | Files | Code lines | Test lines | Skill lines |
|---|---|---|---|---|
| Local profile refusal in `steel_exec` | 1 | 15 to 25 | 30 to 50 | 10 |
| Crawl `session_context` threading | 7 | 100 to 150 | 200 to 300 | 0 |
| Auth store `steel.context` and feed | 4 | 25 to 40 | 40 to 70 | 0 |
| Interactive local branch (live reuse plus cookies) | 4 | 0 to 60 | 40 to 80 | 60 to 100 |
| Skill and design corrections | 8 | 0 | 20 to 40 | 80 to 120 |
| **Total** | **about 18** | **140 to 275** | **330 to 540** | **150 to 230** |

**Properties**

- No new service.
- No custom image.
- No new runtime dependency.
- The crawl path keeps the state the API captures, which is cookies and site storage, not cache or history.
- The interactive path loses cross-session durability.
- The failure mode is loud at the gateway.

**Risk**

- Medium for the crawl context lifecycle.
- Low for the interactive branch.
- Medium for the skill and auth-store schema changes.

### 7.3 Scenario B: local profile service

This scenario implements cloud-compatible profile routes in the local Steel API.

| Work item | Files | Code lines | Test lines |
|---|---|---|---|
| Profile routes, controller, schema | 4 | 300 to 500 | 150 to 250 |
| Profile metadata and state store | 3 | 300 to 500 | 150 to 250 |
| Status, TTL, and reaper | 2 | 150 to 250 | 80 to 150 |
| Session service hook for `profileId` | 2 | 100 to 200 | 80 to 150 |
| OpenAPI and plugin registration | 2 | 60 to 120 | 20 to 40 |
| Image build and deployment | 2 | 20 to 50 | 10 to 20 |
| **Total** | **about 15** | **930 to 1,620** | **490 to 860** |

**Properties**

- Full CLI `--profile` compatibility.
- The largest maintenance surface.
- A fork of the upstream API image.
- The local API's fixed `userDataDir` still needs a session service patch.
- The capability is a facade over `sessionContext`, not a new primitive.

**Risk**

- High: upstream drift, storage growth, status races, upload size, secret handling.

### 7.4 Scenario C: upstream CLI plus crawl context

This scenario adds `--session-context` to the Steel CLI and uses Scenario A for the crawl path.

| Work item | Files | Code lines | Test lines |
|---|---|---|---|
| Upstream CLI flag and protocol | 4 | 120 to 180 | 60 to 100 |
| Local pin bump | 2 | 2 | 10 to 20 |
| Skill restore procedure | 3 | 0 | 20 to 40 |
| Crawl context from Scenario A | 7 | 100 to 150 | 200 to 300 |
| **Total in this repo** | **about 10** | **100 to 150** | **230 to 360** |
| **Total upstream** | **4** | **120 to 180** | **60 to 100** |

**Properties**

- The only seamless durable interactive state option.
- The skill's current local advice becomes true.
- No new browser driver.
- One new CLI release and one pin review.

**Risk**

- Medium: upstream acceptance and release timing.
- Low: the local code is the same as Scenario A.

### 7.5 Scenario D: cloud-only plus refusal

This scenario makes no local state replacement.

| Work item | Files | Code lines | Test lines | Skill lines |
|---|---|---|---|---|
| Gateway refusal | 1 | 15 to 25 | 30 to 50 | 10 |
| Provider warning | 1 | 5 to 10 | 10 to 20 | 0 |
| Skill and design correction | 5 | 0 | 10 to 20 | 40 to 60 |
| **Total** | **about 7** | **20 to 35** | **50 to 90** | **50 to 70** |

**Properties**

- Lowest code cost.
- No local durable state.
- No silent no-op.
- The operator must accept re-login and live-session limits.

### 7.6 Summary

| Scenario | Code lines | Test lines | Skill lines | External dependency | Local durability | Complexity | Reliability |
|---|---|---|---|---|---|---|---|
| A. Live plus cookies plus crawl context | 140 to 275 | 330 to 540 | 150 to 230 | None | Crawl only | Medium | High if guarded |
| B. Local profile service | 930 to 1,620 | 490 to 860 | 50 to 100 | Custom image | Full | High | High if maintained |
| C. Upstream CLI plus crawl context | 100 to 150 | 230 to 360 | 70 to 110 | New CLI release | Full interactive | Medium | High |
| D. Cloud-only plus refusal | 20 to 35 | 50 to 90 | 50 to 70 | None | None | Low | High |

Scenario A is the best fit for the stated constraints.
Scenario C is the best fit if durable interactive state is non-negotiable.
Scenario B is not justified by the tool's actual profile use.
Scenario D is the honest minimum.

## 8. Reliability and failure modes

### 8.1 Silent anonymous crawl

The current crawl provider mounts `profile_id` and falls back to the unprofiled ladder on rejection.
The local runtime strips the field without an error.
The crawl then runs anonymously with `success: true`.
The cookie path may still authenticate, but a target that binds auth to storage will fail silently.
Mitigation: when a context or profile is supplied, a create failure must be loud or must fall back only to a cookie path that is present.

### 8.2 Silent anonymous interactive session

A local `start --profile` succeeds without mounting.
The authn procedure treats the start as a valid mount.
The agent may skip login and act anonymously.
Mitigation: the gateway refuses the profile flags on a local runtime; the skill states the local branch; the authn procedure verifies by navigation, never by the start response.

### 8.3 Stale or mismatched context

`sessionContext` is a point-in-time capture.
Cookies expire; storage keys rotate; the target may bind state to the user agent or viewport.
The crawl provider randomizes user agent and viewport per session.
A restored context can therefore look inconsistent to an anti-bot system.
Mitigation: store the capture time and the user agent and viewport with the context; reuse them on restore; re-verify before a verdict.

### 8.4 Context size and secrets

IndexedDB records can carry blobs.
The create body is JSON; a large context can exceed a request limit or slow the session create.
The context carries live cookies and tokens.
Mitigation: cap the stored context; store it with owner-only permissions; never log it; use a per-account path; prefer cookies when the full context is not needed.

### 8.5 Concurrency

The cloud profile has one live session per profile and last-writer-wins.
A local context file has no server-side lock.
Two crawl pods for the same account can capture and overwrite each other.
Mitigation: a per-account file lock or lease; one writer; the auth store's per-project lock is not per-account.

### 8.6 Session orphans

Live session reuse depends on the stop owner.
A long flow with `--inactivity-timeout` left at the default can be released mid-flow.
Mitigation: the stop-owner script and the catalogue proof; `--inactivity-timeout 0` for long human steps; `--session-timeout` sized for the flow.

### 8.7 CLI version drift

Scenario C adds a flag that older CLI pins do not have.
A deployment with the old pin and a skill that uses the flag fails at parse time.
Mitigation: the `steel_exec` version check already refuses a mismatched pin; bump the pin in the same change.

### 8.8 Secret exposure in command arguments

`cookies set` and `storage set` carry values in argv.
The `steel_exec` transcript and Langfuse spans can capture them.
Mitigation: do not use post-start injection for secret cookies when a context create is available; redact or avoid values in skill examples; never echo them.

## 9. Recommendation

### 9.1 Local design

1. Treat profiles as cloud-only.
2. Do not emulate them with `persist` or a shared `userDataDir`.
3. Make the local loss loud at the tool boundary.
4. Use live session reuse for interactive local flows.
5. Use auth-store cookies as the portable auth material.
6. Use `sessionContext` for the crawl path and programmatic state.
7. Do not build a local profile service unless local profile parity becomes a product requirement.

### 9.2 Work items, in order

| Priority | Work item | Why |
|---|---|---|
| P0 | Refuse `start --profile` and `--update-profile` on a local runtime | Stops the silent anonymous session |
| P0 | Correct the skill's local state claim | The CLI cannot pass `sessionContext` |
| P1 | Add `sessionContext` to the crawl provider | Replaces the crawl profile mount with full state |
| P1 | Add `steel.context` to the auth store and feed | Gives the crawl a durable state reference |
| P1 | Add the local interactive branch to both skills | Live reuse plus cookies |
| P2 | Propose `--session-context` upstream | The only seamless durable interactive option |
| P3 | Local profile service | Only if the operator requires full local parity |

### 9.3 What is lost, and why that is acceptable

| Loss | Impact | Acceptance |
|---|---|---|
| Cross-session interactive state | A restart or release requires re-login | Accepted for local eval; live reuse covers a single flow |
| Browser cache and history | Less anti-bot warmth | Accepted; cookies and storage still authenticate |
| Profile status and TTL | No server-side readiness; caller verifies | Accepted; the skill already verifies by navigation |
| Profile import and sync | No local browser seeding | Accepted; the login flow mints the state |
| Credentials, extensions, proxy binding | Not used by the tool | No loss |
| One-live-session rule | Caller must enforce a lock | Add a per-account lock for crawl |

### 9.4 What must not be lost

- The agent must never believe it is authenticated when it is not.
- The crawl must never silently drop an auth context.
- The state file must never be logged.
- The cloud path must remain unchanged.
- The endpoint must remain one value.

## 10. Open decisions

1. Does the operator require durable interactive state across tool calls and restarts?
2. Is an upstream CLI change acceptable, or is the CLI pin frozen?
3. Should the auth store hold the full `sessionContext` or only a path to a protected file?
4. Should the crawl use `sessionContext` or cookie-only auth by default?
5. Is a per-account state lock required for concurrent crawl pods?
6. Should the local runtime keep a dormant profile service for future parity?

## 11. Verification notes

- `steel browser start --help` on the eval kali lists `--profile` and `--update-profile` but no `--session-context`, `--persist`, or `--user-data-dir`.
- The CLI source `start.rs` builds a `DaemonCreateParams` with profile fields only.
- The daemon protocol has `profile_id` and `persist_profile` but no session context.
- The CLI `start` always stops an existing daemon and creates a fresh session.
- The SDK `SessionCreateParams` has `session_context`.
- The local API `sessions.schema.ts` accepts `sessionContext`.
- The local API `SessionContextSchema` carries cookies, localStorage, sessionStorage, and indexedDB.
- The local API `injectSessionContext` sets cookies through CDP and registers a frame navigation handler for storage.
- The local API's `persist` path is fixed at `/app/api/user-data-dir`; an explicit `userDataDir` is not honored as a path.
- `steel_exec` has no profile guard; `profile-mount.sh` has a `/v1/profiles` 404 guard.
- The profile-heavy test files total 3,603 lines and 60 direct profile references.
