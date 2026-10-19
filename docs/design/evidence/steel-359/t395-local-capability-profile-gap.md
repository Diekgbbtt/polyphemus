# Local Steel capability check: profiles vs session context (#395)

*Status: recorded 2026-10-19, against the pinned local runtime (`ghcr.io/steel-dev/steel-browser-api@sha256:eb8567...`) and the rebuilt kali images.*
*Question: does the open-source local stack satisfy the browser capability surface the tool layer uses, and is the profile feature still a capability?*

## Verdict

For the local OSS stack, the profile feature is **not** a server capability.
Sessions are.
Session state can still be carried explicitly through `sessionContext`.
That is narrower than a profile: a profile snapshots the whole Chrome User Data Directory, while `sessionContext` carries cookies and web storage.

The tool layer **is designed to use profiles**, in two places:

- the interactive skill teaches `start --profile`, `--update-profile`, `profile list|import|sync|delete`, and `references/profile-mount.sh`;
- the crawl provider passes `profile_id` to the Steel SDK (`src/polymerhus/recon/crawl/steel_provider.py`).

Against the local API, both paths silently degrade.
The create call succeeds, but the profile fields are stripped.
There is no error and no profile mount.
That silent success is the real risk.

The bigger stack that owns the delta is **Steel Cloud**.
The OSS `steel-browser` main branch has no `profiles` module.
The cloud Profiles API stores a User Data Directory snapshot and exposes `profileId` / `persistProfile`.

## 1. What the tool layer asks for

### Interactive CLI

The skill's profile path is `references/profile-mount.sh`.

```bash
steel browser start --session "$SESSION" --session-timeout 600000 \
  --profile "$PROFILE" [--update-profile] --json
steel browser stop --session "$SESSION" --json
```

The orchestrator prompt also tells the auth actor to mount the persisted profile or mint one under `--update-profile` (`src/polymerhus/recon/control/orchestrator_agent.py`).

### SDK crawl provider

`_random_session_opts` sends these session options:

```python
{
    "use_proxy": use_proxy,
    "region": random.choice(_REGIONS),
    "user_agent": random.choice(_UAS),
    "dimensions": {"width": w, "height": h},
    "headless": False,
    "stealth_config": {"humanize_interactions": True},
    # plus "profile_id" when the auth feed carries one
}
```

The feed sets `extra["steel_profile"]` only when the auth account carries `steel.profile` (`project_steel_profile` in `src/polymerhus/recon/control/auth_feed.py`).
So the profile path is conditional, not universal.

## 2. What the CLI actually sends

A logging proxy sat between the rebuilt kali CLI and the local API.
The command was:

```bash
steel --local --api-url http://127.0.0.1:3900/v1 browser start \
  --session ph-prof3 --session-timeout 120000 \
  --profile ph-test --update-profile --stealth --json
```

The proxy recorded this `POST /v1/sessions` body:

```json
{
  "inactivityTimeout": 120000,
  "persistProfile": true,
  "profileId": "prof_ph_probe",
  "solveCaptcha": true,
  "stealthConfig": {
    "autoCaptchaSolving": true,
    "humanizeInteractions": true
  },
  "timeout": 120000
}
```

The CLI resolved `profileId` from its **client-side** store at `~/.config/steel/profiles/<name>.json`.
`steel --local profile list --json` reads that store:

```json
{"data":[{"name":"ph-test","profileId":"prof_ph_probe"}],"success":true}
```

That is a local mapping, not server state.

## 3. What the local API does with it

The local `CreateSession` schema (`api/src/modules/sessions/sessions.schema.ts`) has none of `profileId`, `persistProfile`, `stealthConfig`, `solveCaptcha`, `useProxy`, `namespace`, or `region`.
Fastify's zod schema strips unknown keys by default.
The session is created; the fields are discarded.

Observed results:

| probe | result |
|---|---|
| `POST /v1/profiles` | `404 Route POST:/v1/profiles not found` |
| `GET /v1/profiles` | `404 Route GET:/v1/profiles not found` |
| SDK `sessions.create(profile_id=..., persist_profile=True)` | session created; response `profile_id=None`, `persist_profile=None` |
| CLI `start --profile ... --update-profile` | session created; receipt has no profile field; no write-back |

The create response has no `profileId`, so the CLI's write-back branch (`if let Some(returned_profile_id) = info.profile_id`) never fires.

### `persist` and `userDataDir`

These two local fields exist in the schema, but they do not provide named profiles.

`persist: true` resolves to a fixed path:

```
/app/api/user-data-dir
```

That path is on the container overlay, not on the durable `/app/.cache` volume.
It is shared by every persistent session.

An explicit `userDataDir` is also ignored as a path.
Creating with `{"userDataDir": "/tmp/ph-custom-profile"}` produced no `/tmp/ph-custom-profile`; it created `/app/api/user-data-dir` instead.
The expression is `(options.userDataDir || options.persist === true) ? <fixed path> : <default>`, so any value selects the fixed path.

The durable, per-caller state path is therefore `sessionContext`, not `persist`.

## 4. Capability matrix

| capability | tool use | local OSS status | evidence |
|---|---|---|---|
| sessions create/list/release | both | yes | live runs |
| CDP navigation, refs, snapshot, get, eval, click/fill/batch | skill | yes | live ComfyUI run |
| cookies/storage reads | skill | yes | live run |
| scrape/screenshot/PDF | skill | yes | local routes |
| `sessionContext` capture/restore | state client | yes | live round-trip test |
| `proxyUrl`, `userAgent`, `dimensions`, `headless` | CLI/SDK | yes | schema |
| `blockAds`, `optimizeBandwidth`, `extensions`, `timezone`, `userPreferences` | SDK | yes | schema |
| `persist` | SDK | partial: one shared, non-durable directory | `/app/api/user-data-dir`, overlay fs |
| `userDataDir` path control | SDK | no: any value selects the fixed path | live probe |
| named profiles (`profileId`, `persistProfile`) | CLI/SDK | **no: silently stripped** | wire body, SDK response |
| profile routes (`/v1/profiles`) | CLI import/sync | **no: 404** | live probe |
| `stealthConfig` / `solveCaptcha` | CLI/SDK | **no: silently stripped** | wire body |
| `useProxy` (Steel-managed proxy) | SDK | **no: silently stripped** | schema |
| `region`, `namespace`, `credentials` (cloud blob), `projectId`, `concurrency` | CLI/SDK | **no: stripped or unsupported** | schema, docs |
| create-time `timeout` | CLI | no: API reports `0`; the CLI daemon enforces it | #350, D359-10 |
| concurrency > 1 | eval | no: one session | live runtime / docs |

The docs' "Steel Local vs Steel Cloud" table agrees: local has concurrency 1, limited stealth, no CAPTCHA solving, no Credentials API, no Files API, and bring-your-own proxies.
The cloud has the advanced versions.

## 5. The bigger stack

Steel Cloud owns the missing delta:

- Profiles API: stores a User Data Directory snapshot; `persistProfile` creates one, `profileId` mounts it.
- Credentials API, Files API, CAPTCHA API, managed proxies, advanced stealth, concurrency.
- CLI `steel profile import|sync` uploads a zipped `userDataDir` to `{api_base}/profiles`; the cloud implements that route.
- The Python SDK exposes `profile_id`, `persist_profile`, `use_proxy`, `stealth_config`, `region`, `namespace`, and the rest.

The OSS `steel-browser` main branch has no `profiles` module (`api/src/modules` contains actions, cdp, files, logs, selenium, sessions only).
So this is not a configuration gap that a local env var closes; it is a product-tier boundary.

## 6. Impact on the tool

- Interactive `--profile` / `--update-profile` on local is a no-op. The profile-mount script can print "profile mount complete" while mounting nothing.
- The SDK crawl with a `steel_profile` runs anonymous on local. The provider's fallback ladder catches create exceptions, not field stripping, so the crawl does not fail loud.
- A login that depends on a profile mount will fail later, at the target, as an auth error that looks like a crawl or selector defect.
- Cookie/localStorage auth can be carried locally through `sessionContext`; full profile state (extensions, service workers, HTTP auth, browser settings) cannot.

Recommendation:

1. Treat the local runtime's state path as `sessionContext` only (`src/polymerhus/app/steel_session_state.py`).
2. Add a local capability guard at the profile seam: if the base URL is self-hosted and a `profile_id` rides, either translate to a stored `sessionContext` or fail loud with a typed error. Do not let a profile mount silently become anonymous.
3. Use Steel Cloud for profile-dependent auth until the OSS API implements the Profiles API.
4. Do not advertise `--profile` as a local capability in the skill; the current client is cloud-designed.

## 7. Rebuild verification

Local host:

- `polymerhus-kali-1` rebuilt and recreated, `steel 0.5.0-preview.6`, health `ok`.
- Live run against `http://192.33.91.87:3000/v1`: start, navigate `http://t-1fc05262.target/`, title `ComfyUI`, stop, catalogue empty.
- The local base `redamon-kali-sandbox:latest` is not present on this Mac, so the image was rebuilt from the existing `polymerhus-kali:latest` with the new `kali/` layer. The runtime `postrun.sh` fetched the pinned CLI.

Eval instance (`ph-dd131acc`):

- Instance worktree files updated: `kali/postrun.sh` and `kali/mcp_server.py` now pin `0.5.0-preview.6`.
- The instance compose predates #390 and did not pass `STEEL_BROWSER_API_URL` to kali. One env wiring line was added (backup kept).
- `ph-dd131acc-kali-1` rebuilt, recreated, `steel 0.5.0-preview.6`, endpoint `http://192.33.91.87:3000/v1`.
- Live run: start, navigate `http://t-1fc05262.target/`, title `ComfyUI`, stop, catalogue empty.

The merged repo already carries the env wiring, so a future instance worktree update includes it.
