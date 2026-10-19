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
The OSS `steel-browser` has no profile path on any of 133 branches or 23 tags.
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

The OSS `steel-browser` has no profile path on any of 133 branches or 23 tags (`api/src/modules` contains actions, cdp, files, logs, selenium, sessions only).
So this is not a configuration gap that a local env var closes; it is a product-tier boundary.
The full history search is in `docs/design/evidence/steel-359/t395-oss-profile-research.md`.

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

## 8. Deeper OSS verification (2026-10-19)

The docs' local-vs-cloud table omits profiles, which leaves the question open. The code does not.

### Current OSS trees

GitHub tree API, recursive, at three refs:

| ref | paths | paths containing `profile` | API modules |
|---|---|---|---|
| `main` (`807bf294`, 2026-10-19) | 410 | 0 | actions, cdp, files, logs, selenium, sessions |
| `v0.5.4-beta` | 406 | 0 | same |
| `v0.5.3-beta` (the pinned image's version) | 382 | 0 | same |

The current main was committed on the same day as this check.
No profile route, page, service, schema, migration, or test path exists in any of the three trees.

### The pinned image (0.5.3)

The running API image is `steel-browser-api` version 0.5.3, built 2026-10-13.
Its full `api/src` grep for `profile` returns only `utils/context.ts`, and that hit is `getProfilePath`, a helper for Chrome's `Default` / `Profile 1` directory inside a userDataDir.
It is not a Steel profile.

`GET /documentation/openapi.json` has 25 paths and zero occurrences of `profile`, `profileId`, or `persistProfile`.
The plugin registers six route families only: actions, sessions, cdp, selenium, files, logs.
There is no profiles module, controller, service, schema, database table, or storage bucket.

The `files` module is session file upload/download under `/files`; it is not the cloud Files API.
The `ChromeContextService` reads localStorage and sessionStorage from a userDataDir; it does not package or reload a profile.
The `FileService` plus `archiver` can zip files; they are substrate, not a profile lifecycle.
`session.service.ts` sets `persist` / `userDataDir` to one fixed `/app/api/user-data-dir`; it has no profile id, status, or metadata.

### The cloud profile aggregate

The Python SDK (0.19.0) is generated from the cloud OpenAPI.
It exposes `/v1/profiles` (multipart `userDataDir`), `/v1/profiles/{id}` (update), and list/get.
The profile object carries:

```
id, status (UPLOADING | READY | FAILED),
createdAt, updatedAt, userAgent, dimensions,
useProxyConfig, credentialsConfig, extensionIds,
fingerprint, projectId, sourceSessionId
```

The binary `userDataDir` zip is create/update input, not a response field.
Sessions integrate through `profileId` (load the zip into the session userDataDir) and `persistProfile` (snapshot it back on release; `409` while `UPLOADING`; project-scoped).
That lifecycle is a Profiles module plus a ProfileService plus storage plus session hooks.
None of those components exist in the OSS API.
The local stack's state primitive is `sessionContext`, which carries cookies and web storage but not the full userDataDir.

### Why the docs and skills do not settle it

- `https://docs.steel.dev/overview/self-hosting/profiles` is empty in `llms-full.txt` (title and URL only).
- The local-vs-cloud table omits profiles.
- The cloud Profiles API page describes `persistProfile` / `profileId`.
- The official `steel-developer` skill is explicitly for "Steel cloud browsers"; its API routing table maps "Persist full browser state" to the Profiles API.
- The official `steel-reliability` feature-access reference treats profiles and credentials as cloud plan/fallback features.
- The official `steel-browser` skill uses `--profile` without a local caveat; its troubleshooting still distinguishes cloud vs local/self-hosted.

The docs are ambiguous; the code is not.
The GHCR `latest` image pulls for the API-only and combined images ended with `unexpected EOF`, so the recursive repo trees and the running 0.5.3 image are the evidence.
The combined image is built from the same repo tree, which has no profile path.

### Full history and the near-miss

The dedicated report is `docs/design/evidence/steel-359/t395-oss-profile-research.md`.

It searched 133 remote branches and 23 tags:

- pickaxe for `persistProfile`, `persist_profile`, `ProfileStatus`, `UPLOADING`, and `/profiles` is empty on every ref;
- `profileId` appears in no `api/src` or `ui/src` file on any ref;
- the only file ever named `*profile*` is `cdp.profile-lifecycle.test.ts` on the unmerged `fix/profile-restore-before-save` branch (`ff717f1`); its profiles are a test fixture, and the branch's final commit (`53f32ba`) deletes them;
- the pinned image's `api/src` is byte-identical to current `main`;
- `main` is 8 commits past `v0.5.4-beta`, so no tag or branch holds a deployable component;
- commit `459be5b` ("foundation for usr-data-dir persistence") added the `persist`/`userDataDir` primitive only; no management layer followed;
- the docs' self-hosting Profiles page is frontmatter only in `steel-dev/docs` (`content/docs/overview/self-hosting/profiles.mdx` at `c7c8883`), with no body.

The docs table omission is an oversight, not permission.
The artifact settles it.
