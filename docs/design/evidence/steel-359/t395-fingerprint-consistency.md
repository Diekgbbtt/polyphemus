# Fingerprint consistency in the local Steel runtime (#395)

*Status: measured 2026-10-20.*
*Runtime: pinned local Steel API at `192.33.91.87:3000`, CLI 0.5.0-preview.6.*
*Companion decision: `docs/design/steel-session-only-395-decisions.md`.*
*No API key is printed in this record.*

## 1. Question

Profiles are retired.
A resumed session now carries only cookies, localStorage, sessionStorage, and indexedDB.
That leaves a high fingerprint-drift risk.

The question is which cheap mechanism gives reliable user-agent consistency across local sessions without adding a branch to the one browser skill.

## 2. Measurements

### 2.1 Default create

A default `POST /v1/sessions` with an empty body produced:

```
ua: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36
screen: 800x600
inner: 1920x992
tz: Europe/Zurich
uad: null
```

A separate SDK create with no explicit user agent produced Chrome/145.
A separate CLI start produced Chrome/142.
A later CLI start produced Chrome/144.

The default user agent is therefore not stable across sessions.
The range observed is Chrome 142 to Chrome 145.

### 2.2 Skip fingerprint injection only

`{"skipFingerprintInjection": true}` with no user agent produced:

```
ua: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/155.0.0.0 Safari/537.36
screen: 800x600
inner: 1920x992
tz: Europe/Zurich
uad: null
```

This is worse than the default.
The `HeadlessChrome` token is a direct bot tell.

### 2.3 Fixed user agent at create

`{"userAgent": "<Chrome 142>", "dimensions": {"width": 1920, "height": 1080}, "skipFingerprintInjection": true}` produced:

```
ua: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36
screen: 800x600
inner: 1920x992
tz: Europe/Zurich
uad: null
```

A Chrome/137 user agent with 1366x768 produced:

```
ua: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
screen: 800x600
inner: 1366x680
tz: Europe/Zurich
uad: null
```

The create-time user agent is exact.
The inner viewport follows the requested dimensions.
The screen stays at 800x600, so a mismatch remains unless the window matches the screen.

### 2.4 CLI `set useragent` after start

The CLI exposes a primitive that was not in the earlier command-family inventory:

```
steel browser set useragent [OPTIONS] [USER_AGENT]...
```

Live local run:

```
before: Chrome/144
set:    {"data":{"userAgent":"... Chrome/155.0.0.0 ..."},"success":true}
after:  Chrome/155
```

The primitive works on a live local session.
It takes the quoted user-agent string as one argument.
It overrides the page user agent through CDP `Emulation.setUserAgentOverride`.

### 2.5 `CHROME_ARGS` is not a user-agent carrier

The local API env parses `CHROME_ARGS` as a space-separated list:

```ts
CHROME_ARGS: z.string().optional()
  .transform((val) => (val ? val.split(" ").map((arg) => arg.trim()) : []))
  .default("")
```

A user-agent string contains spaces.
Putting it in `CHROME_ARGS` splits it into several arguments.
It cannot reliably set a full user-agent string.

The local API also appends `CHROME_ARGS` after the dynamic launch arguments.
That ordering is useful for scalar flags, but it does not solve the word-splitting defect.

## 3. Findings

1. The local default is not user-agent stable.
   It generated Chrome 142, 144, and 145 across sessions.
2. Disabling injection alone exposes `HeadlessChrome`.
3. A create-time fixed user agent is stable, but the CLI `start` has no user-agent flag.
4. The CLI `set useragent` primitive fixes the CLI path after start.
5. The API create path can set `userAgent` directly.
6. The screen and inner viewport can still disagree.
7. `navigator.userAgentData` was null in every local probe.
   Client hints were not observable from JavaScript.
   Network `Sec-CH-UA` behaviour remains unverified.

## 4. Recommended cheap edit

The local deployment should do two things:

1. Set `SKIP_FINGERPRINT_INJECTION=1` so the API does not inject a random user agent before the fixed override.
2. The local `steel` wrapper should run `steel browser set useragent` with one fixed value immediately after every `browser start`.

The fixed value should match the pinned browser major version.
The current browser is HeadlessChrome 155.
The fixed value is Chrome 155 with the `Headless` token removed:

```
Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36
```

The wrapper applies only when `STEEL_BROWSER_API_URL` is set.
The cloud path is untouched and keeps native jitter.
The skill never sees the user-agent step.

The optional viewport fix is a second wrapper action:

```
steel browser set viewport --local --session <name> --json 800 600
```

This matches the native screen.
It is not required for user-agent stability.

## 5. Rejected alternatives

| Alternative | Verdict | Reason |
|---|---|---|
| Leave the default random user agent | Rejected | Observed drift across 142 to 145. |
| Disable injection without a fixed user agent | Rejected | Exposes HeadlessChrome 155. |
| Set `CHROME_ARGS=--user-agent=...` | Rejected | The env parser splits the string on spaces. |
| Pass `user_agent` in the SDK only | Partial | Covers crawl, not the CLI. |
| Patch the local API to add a default user agent | Rejected for now | More code and an image-local patch; the CLI primitive is cheaper. |
| Capture the first user agent and reuse it | Rejected | Adds state and can go stale across browser builds. |
| Keep profiles for fingerprint consistency | Rejected by ruling | The operator retired profiles. |
| Pin the user agent in the cloud | Rejected by ruling | Cloud jitter is accepted and needs no tool logic. |

## 6. Residual risk

- The full canvas, WebGL, fonts, and audio fingerprint is not carried by session state.
- History, cache, service workers, and HTTP auth are not carried.
- The screen is 800x600 while the default inner viewport is 1920x992 unless the viewport is set.
- The fixed user agent must be updated when the pinned browser image changes major version.
- Network client hints were not measured at the HTTP layer.
  A future live check should read the request headers through a controlled echo endpoint.
- The cloud path may change its user agent natively; that is accepted.

## 7. Cost

- Local API compose: one environment line for `SKIP_FINGERPRINT_INJECTION`.
- Local `steel` wrapper: about 40 to 70 shell lines including mode injection, `start` detection, and the user-agent call.
- Provider: remove the random user-agent, viewport, and region table; about 25 to 40 lines removed.
- Crawl prompt: remove the false new-fingerprint and new-region claims; a few lines.
- Tests: wrapper unit tests, local live UA check, provider option test; about 80 to 140 lines.

The change is small and has no nested runtime branch inside the tool or the skill.
The only runtime branch is the deployment wrapper.
