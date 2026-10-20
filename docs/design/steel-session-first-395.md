# Session-first browser design (#395): correction and profile retirement

*Status: revision, 2026-10-19. Superseded in part 2026-10-20 by `steel-session-only-395-decisions.md`: profiles are retired in the cloud too, there is one runtime-agnostic skill (not two primitive packs), and local user-agent consistency uses the CLI `set useragent` primitive rather than `CHROME_ARGS`. Keep this record as the session-first analysis; read the newer decision record for the binding decisions.*
*Scope: the tool's use of the Steel browser, cloud and local. The Steel product may keep profiles; the tool will not use them.*
*Evidence: CLI 0.5.0-preview.6 source and live local runtime; CLI `main` source; SDK 0.19.0; local API 0.5.3; D17; D359-7; D395-2.*

## 1. Corrections

### 1.1 The CLI has a real session primitive

The earlier statement "the CLI `start` always creates a fresh session" was too broad.
The precise behaviour is:

- `steel browser start --session <name>` creates or replaces a live session.
- A second `start` with the same name stops the existing daemon and creates a new session.
- Every other command with `--session <name>` attaches to the live named session.
- The name is the session handle for navigation, interaction, reads, and stop.
- The CLI cannot attach to an API-created remote session, and it cannot pass session state at `start`.

Live proof on the local runtime:

- Two consecutive `start --local --session probe-attach-2` calls returned two different session ids.
- A separate `start --local --session ua-probe-e` followed by `eval --local --session ua-probe-e` returned the page value from the live session.
- The CLI help text says "Create or attach"; the source and the live result show create-or-replace.

The tool therefore already has the session reuse primitive.
The missing primitive is state restore at create, not session identity.

### 1.2 Naming

Use one name per concept.

| Concept | Correct name | Wire or interface name |
|---|---|---|
| Live browser instance | session | CLI `--session <name>` |
| Captured cookies and storage | session state | API field `sessionContext` |
| Stable browser attributes | browser identity | session create fields |
| Steel cloud durable bundle | profile | `profileId` / `persistProfile` |

`sessionContext` is a wire field.
It is not the session, and it is not the capability.
The design term is **session state**.
The proposed CLI flag is `--session-state <file>`, which maps to the API field `sessionContext`.

### 1.3 Skills must not branch on infrastructure

The current `steel-browser` skill tells the agent to use a different state path when the runtime is local.
That is a defect.
The agent must not know whether the runtime is cloud or local.

The correct shape is:

- one canonical operation body;
- two primitive packs, one cloud and one local;
- the packs differ only in command forms and runtime constraints;
- the loader selects the pack from the deployment;
- the agent sees one skill and one procedure.

The skill names can remain `steel-browser` for the agent.
The variants are `steel-browser-cloud` and `steel-browser-local` in the loader.
A parity test asserts that the operation body is identical and that only the primitive section differs.

The current skill's "Local runtime", "Profiles are cloud-only", and "pass `--local` in scripts" text moves out of the operation body.
The operator documentation owns those facts.
The local primitive pack encodes `--local`; the agent does not see the reason.

## 2. Why profiles were chosen

D17 records the original decision:

> durable browser identity lives in Steel profiles (long-lived named server-side state), not in client-side session-context JSON.

The concerns were:

- state should live server-side, not shuttle through agent context;
- the identity should survive sessions and jobs;
- the browser should present a warm returning user, not a stranger;
- the profile should bind a stable browser identity;
- the auth store should hold only a small key, never the browser state.

The profile object holds more than a session:

| Attribute | Profile | Session create |
|---|---|---|
| Durable state | `userDataDir` zip: cookies, storage, IndexedDB, history, cache | `sessionContext` at create; live state only |
| User agent | `userAgent` | `userAgent` |
| Viewport | `dimensions` | `dimensions` |
| Proxy | `useProxyConfig`, `proxyUrl` | `proxyUrl`, `useProxy` |
| Credentials | `credentialsConfig` | `credentials` |
| Extensions | `extensionIds` | `extensionIds` |
| Fingerprint | server-generated `fingerprint` object | No fingerprint object; only `skipFingerprintInjection` |
| Lifecycle | `status` UPLOADING/READY/FAILED, timestamps, reaper | Session status and timeout |
| Scope | `projectId`, `sourceSessionId` | `projectId` |
| One writer | one live session per profile | No built-in rule |

The additional properties are therefore:

1. a durable server-side state zip;
2. a stable server-generated fingerprint bundle;
3. a persisted identity bundle: UA, dimensions, proxy, credentials, extensions;
4. a server-side status and retention lifecycle;
5. a project and source-session association.

The tool uses the state and the identity.
It does not use credentials injection, extensions, proxy binding, project scoping, or status polling.
The fingerprint consistency is the strongest reason that remains.

The session create API exposes UA, dimensions, proxy, credentials, extensions, timezone, and state.
It does not expose a fingerprint object.
Therefore a session-first design can keep the state and most of the identity, but not the server-generated fingerprint object.

## 3. Session-first domain

The tool should use three objects and no profile.

### 3.1 Session

A live browser instance with a name.
Create it once with the stored identity and state.
Attach to it with `--session` for every operation.
Release it explicitly.
Reuse it for a flow instead of recreating it.

### 3.2 Browser identity

A stable per-account record:

- `user_agent`;
- `dimensions`;
- `timezone`;
- `locale`;
- optional cloud proxy;
- optional cloud credentials;
- optional cloud extensions.

Store it in the auth store with the account.
Pass the same values on every session create.
Do not randomise per session.

### 3.3 Session state

The captured browser state:

- cookies;
- localStorage;
- sessionStorage;
- indexedDB.

Capture it while the session is live.
Store it at a per-account path with owner-only permissions.
Restore it through the create field `sessionContext`.
Lock one writer per account.

### 3.4 Flow

```
identity + state -> create session -> operate -> capture state -> release -> store
```

For a single interactive flow:

```
create once -> operate with --session -> release
```

The live session covers the flow.
The stored state covers the next session.

### 3.5 What is lost

- The server-generated fingerprint object.
- Server-side status and retention.
- Server-side project and source-session association.

The first loss is material for anti-bot fidelity.
The second is mostly operational; the application can verify and expire.
The third is not used by the tool.

## 4. Local consistency

### 4.1 Measured current state

A local CLI session in the current eval image reports:

- user agent: `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ... Chrome/142.0.0.0 Safari/537.36`;
- platform: `Linux x86_64`;
- language: `en-US`;
- screen: `800x600`;
- timezone: `Europe/Zurich`.

The local API has `SKIP_FINGERPRINT_INJECTION` unset.
The native user agent was Chrome/142 in the sampled sessions.
The native screen is small and may not match the viewport the tool requests.
The generator can still run on another build, so the environment setting is required for determinism.

### 4.2 The provider is the inconsistency

`steel_provider.py` currently chooses from:

- `_UAS`: Chrome 137, 136, and 135;
- `_VIEWPORTS`: five desktop sizes;
- `_REGIONS`: five cloud regions.

The local browser is Chrome 142.
A random Chrome 135 to 137 user agent is both outdated and inconsistent with the client hints of the Chrome 142 browser.
The local API uses the supplied user agent and skips fingerprint generation.
The provider therefore actively replaces a stable native identity with a random, mismatched one.

### 4.3 Minimal fixes

1. Remove the `_UAS` and `_VIEWPORTS` random choice.
   Use one `BrowserIdentity` per account, or omit the fields and use the native identity.
2. For the local runtime, omit `user_agent` and `dimensions`.
   The native Chrome 142 identity is then stable.
3. Set `SKIP_FINGERPRINT_INJECTION: "1"` on the local Steel API service.
   The API env parser accepts `"1"`.
   This prevents a future fingerprint-generator success from changing the identity per session.
4. For the SDK crawl path, pass `skip_fingerprint_injection=True` on local.
   This makes the choice explicit even if the environment changes.
5. If a desktop viewport is required, set it consistently:
   either `CHROME_ARGS=--window-size=1920,1080` plus `dimensions`, or use the native `800x600`.
   Do not set a 1920x1080 window with an 800x600 screen.
6. Store the observed identity in the auth store.
   Reuse it on the next session.
   Verify two consecutive sessions report the same user agent.

The compose change is one line.
The provider change is a small removal, not a new subsystem.

### 4.4 What cannot be fixed this way

The session create API has no `fingerprint` object.
The cloud profile is the only surface that binds the full generated fingerprint.
A session-first design can keep UA, viewport, timezone, and locale consistent.
It cannot reproduce canvas, WebGL, fonts, and audio fingerprint binding without an API change.

That is the accepted partial loss.
The user's condition is satisfied: low complexity, no profile service, and a structurally fixed user agent.

## 5. Skill architecture

### 5.1 Shared body plus primitive packs

```
skills/steel-browser/
  SKILL.md                 # operation body, runtime-neutral
  primitives/cloud.md      # command forms and cloud constraints
  primitives/local.md      # command forms and local constraints
```

The loader composes `SKILL.md` plus one primitive pack.
The agent sees one skill.
The operation body contains no "cloud", "local", `STEEL_BROWSER_API_URL`, or profile branch.

The primitive packs may differ on:

- `steel` versus `steel --local`;
- proxy and stealth support;
- state helper command;
- session state file location.

They do not differ on:

- survey, open, operate, close;
- refs, variadic boundary, timeout ordering;
- read projection and secret handling;
- stop owner and catalogue proof;
- session state capture and restore.

### 5.2 The authn meta-skill

`authn-skill-writing` follows the same rule.
It has one procedure body and two primitive packs.
The authored authn skill is runtime-neutral.
The agent reads the procedure and the selected primitives; it never sees a deployment branch.

### 5.3 Remove the profile scripts

- Delete `references/profile-mount.sh`.
- Remove the profile read from `references/catalogue.sh`.
- Add `references/session-state.sh` for capture, store, and restore.
- Update `references/extract-reads.sh` to feed the state capture.

If profiles remain in the Steel product, the tool still does not use them.
The skill does not mention them.

### 5.4 Loader selection

The deployment already knows the endpoint.
The skill loader selects the primitive pack from the same configuration that resolves `STEEL_BROWSER_API_URL`.
A test pins that the two composed skills have identical operation bodies.

## 6. Impact and complexity

### 6.1 Delta from the previous map

The previous map assumed cloud profiles would remain.
The session-first direction changes these rows:

| Component | Previous | Session-first |
|---|---|---|
| `auth/records.py` | Accept `steel.context` beside `steel.profile` | Replace `steel.profile` with `steel.identity` and `steel.state` |
| `auth_feed.py` | Project profile key or context | Project identity and state |
| `pipeline.py` | Project `steel_profile` | Project identity and state |
| `steel_provider.py` | Keep profile plus context | Remove `profile_id`; use identity and state |
| `steel_client.py` | Thread profile and context | Thread identity and state |
| `crawl_agent.py`, `crawl_pod.py` | Thread profile and context | Thread identity and state |
| `steel-browser` skill | Local branch inside the body | Shared body plus primitive packs |
| `authn-skill-writing` | Profile discipline | Identity and state discipline |
| CLI | Profile flag | `--session-state` flag upstream, or live reuse only |
| Local compose | No change | `SKIP_FINGERPRINT_INJECTION=1` |

The old `steel_profile` tests become identity and state tests.
The old profile-mount guard becomes a local capability test for the state helper.
The cloud profile path is no longer exercised by the tool.

### 6.2 Scenarios

| Scenario | What it does | Code lines | Test lines | Interactive durability |
|---|---|---|---|---|
| S1. Session-first with CLI state flag | Identity and state stores; provider; upstream CLI flag; skill packs | 350 to 550 | 400 to 600 | Full |
| S2. Session-first with live reuse only | Identity and state stores; provider; no CLI flag | 250 to 350 | 300 to 500 | Live flow only |
| S3. Keep cloud profiles | Previous map | 140 to 275 | 330 to 540 | Cloud only; local none |

S1 includes 120 to 180 lines of upstream Rust and 60 to 100 lines of upstream tests.
The local code in S1 is about 350 to 450 lines plus tests.
S2 is the fallback if the CLI pin is frozen.
S3 contradicts the session-first direction.

### 6.3 Identity and state work breakdown

| Work item | Files | Code lines | Test lines |
|---|---|---|---|
| Browser identity in the auth store | 3 | 60 to 90 | 80 to 120 |
| Session state store and lock | 2 | 120 to 180 | 120 to 180 |
| Provider identity and state | 4 | 80 to 120 | 120 to 180 |
| Feed and pipeline projection | 3 | 40 to 60 | 60 to 90 |
| CLI `--session-state` upstream | 4 | 120 to 180 | 60 to 100 |
| Skill body and two primitive packs | 5 | 0 | 30 to 60 |
| Local identity compose line | 1 | 1 | 2 to 5 |
| **Total in this repo** | **about 15** | **300 to 450** | **410 to 630** |

### 6.4 UA consistency work breakdown

| Work item | Files | Code lines | Test lines |
|---|---|---|---|
| Remove `_UAS` and `_VIEWPORTS` randomness | 1 | 10 to 20 | 20 to 40 |
| Pass `skip_fingerprint_injection` on local | 1 | 5 to 10 | 10 to 20 |
| Add `SKIP_FINGERPRINT_INJECTION=1` to local compose | 1 | 1 | 1 to 2 |
| Identity reuse and verification | 2 | 30 to 50 | 40 to 60 |
| **Total** | **about 5** | **45 to 80** | **70 to 120** |

This work is small and independent of the CLI state flag.

## 7. Decision

1. Adopt session-first for the tool, cloud and local.
2. Retire profiles from the tool; keep the Steel feature for other consumers.
3. Split the browser skill into one shared body and two primitive packs.
4. Add `--session-state` to the Steel CLI upstream, or accept live reuse only.
5. Store browser identity and session state in the auth store.
6. Fix the local identity with `SKIP_FINGERPRINT_INJECTION=1` and provider pinning.
7. Do not build a local profile service.

The critical path is the CLI state flag.
Without it, the tool can reuse a live session but cannot restore state in a new interactive session.
The crawl path can restore state through the SDK immediately.

## 8. Evidence

- CLI source `src/commands/browser/start.rs` states that `start` always creates a fresh session.
- The same source stops an existing named daemon before creating.
- CLI `main` has the same behavior.
- Live local test: two `start --local --session probe-attach-2` calls returned different ids.
- Live local test: a following `eval --local --session` ran against the live session.
- CLI help lists `--profile` and `--update-profile`, but no `--session-state`, `--persist`, or `--user-data-dir`.
- The CLI reads `STEEL_BROWSER_API_URL` as the base URL, but local mode still requires `--local` or `--api-url`.
- SDK `SessionCreateParams` has `session_context` and `skip_fingerprint_injection`, but no `fingerprint` object.
- Local API `SessionContextSchema` carries cookies, localStorage, sessionStorage, and indexedDB.
- Local API `cdp.service.ts` generates a random fingerprint only when no user agent is supplied and fingerprint injection is not skipped.
- Local API env parser accepts `SKIP_FINGERPRINT_INJECTION=1`.
- Local CLI session reported Chrome/142, Linux, en-US, 800x600, Europe/Zurich.
- Provider source randomises user agent among Chrome 135 to 137.
