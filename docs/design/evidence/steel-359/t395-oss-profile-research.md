# OSS profile-management research (#395)

*Status: recorded 2026-10-19. Research executed on `dj-viscon-workshop-1` (`ubuntu@192.33.91.87`). No code was modified.*

## Verdict

The `steel-dev/steel-browser` open-source stack contains **no profile-management component**.
The profile domain exists only in Steel Cloud.
This is not a deployment gap, not a missing env var, and not a newer tag.

Three separate claims, each proven below:

1. **Not in the pinned image.** The running image has no profiles route, no profiles module, and no profile field in its create schema.
2. **Not anywhere in OSS history.** No commit on any of the 133 remote branches or 23 tags ever contains `persistProfile`, `persist_profile`, `ProfileStatus`, `UPLOADING`, or a `/profiles` route.
   The only near-miss is an unmerged branch that used profile semantics as a test fixture, then deleted them.
3. **Present but not deployed? No.** The pinned image's `api/src` is byte-identical to current `main`.
   `main` is newer than every tag. So no tag, branch, or commit has a deployable profiles component.

The one open-source primitive that resembles a profile is `persist` + `userDataDir`.
It is a single shared, non-durable directory, not a named profile store.
Its own commit message calls it "foundation for usr-data-dir persistence" and "option for saving profiles".

The docs do not claim self-hosted profiles work.
The self-hosting Profiles page exists but is empty.
The "Steel Local vs Steel Cloud" table omits Profiles entirely, which is the source of the ambiguity.

## 1. Ground truth of the pinned artifact

| Property | Value | Source |
|---|---|---|
| Repo digest | `sha256:eb8567bac2221d2856923184cf693a08df9a488680431ebded73cab63aa181eb` | `docker image inspect` on the host |
| Config digest | `sha256:ebbab5fc2bdbab3870db69c54a99040eef757117bcd864a0efec14f6ed958da8` | same |
| Created | `2026-10-13T15:55:14.324357117Z` | same |
| Labels | `org.opencontainers.image.source=https://github.com/steel-dev/steel-browser` only | same |
| Package version | `@steel-browser/api` `0.5.3` | `/app/api/package.json` in the container |
| Platform | multi-arch index, amd64 + arm64 | GHCR manifest `application/vnd.oci.image.index.v1+json` |

The image carries **no version or revision label**.
Only the source URL is labelled.
Version must therefore be inferred from the source tree, not from image metadata.

Version inference:

- `api/package.json` reports `0.5.3`.
- The newest tag is `v0.5.4-beta` (`3fe2410`, 2026-08-25).
- `main` is 8 commits ahead of `v0.5.4-beta`.
- So the image is a post-tag build of `main`, not a build of any release tag.

Proof that "newer tag" is not the answer:

```
$ git rev-list --count v0.5.4-beta..main
8
$ git for-each-ref --sort=-creatordate --format='%(refname:short) %(creatordate:iso)' refs/tags | head -1
v0.5.4-beta 2026-08-25 15:40:29 -0400
```

## 2. The pinned image is byte-identical to current `main`

```
$ sudo docker cp polymerhus-steel-steel-api-1:/app/api/src ./img-src
$ diff -rq img-src repo/api/src
$ echo $?
0
IDENTICAL: running image api/src == main api/src
```

`main` is `807bf29410d74aecd1a1b8427a25124358bd7fd9` (2026-10-19).
Only one commit follows the CDP lifecycle change on `main`, and it does not touch `api/src`:

```
$ git log --oneline d8a4a7e..main -- api/src
(no output)
$ git log --oneline d8a4a7e..main
807bf29 fix(deps): bump @fastify/static, defuddle, file-type and vitest for security advisories (#377)
```

Consequence: "not in the pinned image" and "not on `main`" are the same statement.
No separate image-versus-source gap exists.

## 3. What the running image actually exposes

### Modules present

```
$ sudo docker exec polymerhus-steel-steel-api-1 ls /app/api/build/modules
actions
cdp
files
logs
selenium
sessions
```

Source equivalents:

- `api/src/modules/` contains exactly those six directories.
- `api/src/routes.ts:2-5` exports `sessionsRoutes`, `seleniumRoutes`, `filesRoutes` and the rest, with no profiles route.
- `api/src/steel-browser-plugin.ts:81-84` registers `sessionsRoutes`, `seleniumRoutes`, `filesRoutes` under `/v1`.

### Routes present

```
$ sudo docker exec polymerhus-steel-steel-api-1 node -e 'const s=require("/app/api/openapi/schemas.json"); console.log(Object.keys(s.paths).sort().join("\n"))'
/v1/devtools/inspector.html
/v1/events
/v1/health
/v1/logs/
/v1/logs/export
/v1/logs/query
/v1/logs/stats
/v1/logs/stream
/v1/pdf
/v1/scrape
/v1/screenshot
/v1/sessions
/v1/sessions/debug
/v1/sessions/pdf
/v1/sessions/release
/v1/sessions/scrape
/v1/sessions/screenshot
/v1/sessions/{id}/live-details
/v1/sessions/{sessionId}
/v1/sessions/{sessionId}/context
/v1/sessions/{sessionId}/files
/v1/sessions/{sessionId}/files.zip
/v1/sessions/{sessionId}/files/{*}
/v1/sessions/{sessionId}/release
```

There is no `/v1/profiles` entry.
The bundled `openapi/schemas.json` has 24 paths and omits `/v1/search`; the served `/documentation/openapi.json` has 25 and includes it.
The one-route difference is search, not profiles.
Neither artifact has a profiles route, so this is not a documentation omission.

### Live probe against the running container

```
$ curl -s -o /dev/null -w 'GET  /v1/profiles -> %{http_code}\n' http://127.0.0.1:3000/v1/profiles
GET  /v1/profiles -> 404
$ curl -s -o /dev/null -w 'POST /v1/profiles -> %{http_code}\n' -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:3000/v1/profiles
POST /v1/profiles -> 404
$ curl -s -o /dev/null -w 'GET  /v1/health  -> %{http_code}\n' http://127.0.0.1:3000/v1/health
GET  /v1/health  -> 200
```

The 404 is a real absence, not a container fault: `/v1/health` returns 200 on the same process.

### The only `profile` strings in application code

```
$ sudo docker exec polymerhus-steel-steel-api-1 sh -c 'grep -rn -i profile /app/api/build --include=*.js'
/app/api/build/services/cdp/cdp.service.js:26:import { ..., getProfilePath, ... } from "../../utils/context.js";
/app/api/build/services/cdp/cdp.service.js:1154: const preferencesPath = getProfilePath(userDataDir, "Preferences");
/app/api/build/services/cdp/cdp.service.js:1156: await fs.promises.mkdir(defaultProfileDir, { recursive: true });
/app/api/build/services/context/chrome-context.service.js:79: const localStoragePath = getProfilePath(userDataDir, "Local Storage", "leveldb");
/app/api/build/services/context/chrome-context.service.js:96: const sessionStoragePath = getProfilePath(userDataDir, "Session Storage");
/app/api/build/utils/context.js:362: * Helper to get Chrome profile paths in a cross-platform way
/app/api/build/utils/context.js:365: export function getProfilePath(userDataDir, ...pathSegments) {
```

Every hit is a **Chrome user-data-directory path helper**, not a profile domain.
Source: `api/src/utils/context.ts:456-471`.
The function chooses between the `Default` and `Profile 1` subdirectories of a `userDataDir`.
It answers "where inside Chrome's data directory do I write Preferences?".
It does not answer "which named profile does this session mount?".

## 4. Exhaustive history search

The clone contains 133 remote branches and 23 tags.

### Pickaxe search over all refs

```
$ git log --all --oneline -SpersistProfile
(no output)
$ git log --all --oneline -Spersist_profile
(no output)
$ git log --all --oneline -SProfileStatus
(no output)
$ git log --all --oneline -SUPLOADING
(no output)
$ git log --all --oneline -S"/profiles"
(no output)
$ git log --all --oneline -SprofileId
53f32ba test(cdp): keep lifecycle coverage independent of consumers
ff717f1 fix(cdp): restore profiles before saving incoming sessions
```

### Route and field search over every ref

```
$ for ref in $(git for-each-ref --format='%(refname)' refs/remotes refs/tags); do
    n=$(git grep -l -i 'profiles' $ref -- 'api/src/*.ts' 'ui/src/*.ts' 'ui/src/*.tsx' 2>/dev/null | wc -l)
    [ "$n" != "0" ] && echo "$ref ($n files)"
  done
refs/remotes/origin/fix/cdp-fingerprint-consistency (1 files)
```

The single hit on `fix/cdp-fingerprint-consistency` is the comment `// Non-Chromium profiles do not expose UA Client Hints.` at `api/src/services/cdp/cdp.service.ts:1523`.
It refers to browser profiles in the Chrome sense.

`profileId` appears in **no** `api/src` or `ui/src` file on any ref.

### Files ever named `*profile*`

```
$ git rev-list --all | while read c; do git ls-tree -r --name-only $c | grep -i profile; done | sort -u
api/src/services/cdp/cdp.profile-lifecycle.test.ts
```

One file, ever. It was added by `ff717f1` and deleted by `53f32ba`, both on the unmerged branch `fix/profile-restore-before-save`.

### The near-miss, precisely

`ff717f1` (2026-10-13) is titled `fix(cdp): restore profiles before saving incoming sessions`.
It adds `api/src/services/cdp/cdp.profile-lifecycle.test.ts` and a two-line fix to `cdp.service.ts`.

Critical detail: the test **models** profile restore and persist with a fixture.
It does not implement them.

```ts
service.registerLaunchHook((config) => {
  const profile = config.extra?.profile as ProfileOptions | undefined;
  if (profile?.useProfileId) {
    events.push(`restore:${profile.useProfileId}`);
    browserData = { ...stored.get(profile.useProfileId) };
  }
});
```

The `ProfileOptions` interface is declared inside the test file.
No production file defines it.

The branch then dropped the semantics entirely:

```
$ git log -1 --stat 53f32ba
 api/src/services/cdp/cdp.lifecycle.test.ts         | 202 +++++++++++++++++
 api/src/services/cdp/cdp.profile-lifecycle.test.ts | 238 ---------------------
 api/src/services/cdp/cdp.service.ts                |   2 +-
$ git grep -n -i profile origin/fix/profile-restore-before-save -- api/src/services/cdp/cdp.lifecycle.test.ts
(no output)
```

So the final branch state has **zero** profile code.
The branch ships only the hook-ordering fix, which landed on `main` separately as `d8a4a7e` (`#376`).

```
$ git merge-base --is-ancestor ff717f1 main; echo $?
1
$ git branch -a --contains ff717f1
  remotes/origin/fix/profile-restore-before-save
```

`ff717f1` is not an ancestor of `main`.
`d8a4a7e` is.

This branch is the strongest possible counter-evidence, and it does not survive inspection.
It tests that lifecycle hooks stay bound to the outgoing browser.
The profile shape is a fixture used to give the ordering bug a concrete failure mode.

## 5. The profile object, mapped to OSS code

The object model comes from the Python SDK, which is generated from the cloud OpenAPI spec.

```
$ awk '/^class ProfileCreateResponse/,0' src/steel/types/profile_create_response.py
class ProfileCreateResponse(BaseModel):
    id: str
    created_at: datetime = FieldInfo(alias="createdAt")
    credentials_config: object = FieldInfo(alias="credentialsConfig")
    dimensions: Optional[Dimensions] = None
    extension_ids: Optional[List[str]] = FieldInfo(alias="extensionIds", default=None)
    fingerprint: Optional[Fingerprint] = None
    project_id: Optional[str] = FieldInfo(alias="projectId", default=None)
    source_session_id: Optional[str] = FieldInfo(alias="sourceSessionId", default=None)
    status: Literal["UPLOADING", "READY", "FAILED"]
    updated_at: datetime = FieldInfo(alias="updatedAt")
    use_proxy_config: object = FieldInfo(alias="useProxyConfig")
    user_agent: Optional[str] = FieldInfo(alias="userAgent", default=None)
```

### Field and operation mapping

| Profile capability | Would be implemented by | Present in OSS repo | Present in pinned image |
|---|---|---|---|
| `Profile.id` | profiles module + DB or object store | No | No |
| `Profile.status` (`UPLOADING`/`READY`/`FAILED`) | profiles service state machine | No | No |
| `Profile.createdAt` / `updatedAt` | profiles store | No | No |
| `Profile.userDataDir` zip upload | `POST /v1/profiles` multipart handler | No | No |
| `Profile.userAgent` | profiles schema + launch override | No | No |
| `Profile.useProxyConfig` | profiles schema + proxy plumbing | No | No |
| `Profile.fingerprint` | profiles schema | No | No |
| `Profile.extensionIds` | profiles schema | No | No |
| `Profile.projectId` / `sourceSessionId` | cloud tenancy fields | No | No |
| `client.profiles.create` | `POST /v1/profiles` | No | No |
| `client.profiles.update` | `PATCH /v1/profiles/{id}` | No | No |
| `client.profiles.list` / `retrieve` | `GET /v1/profiles`, `GET /v1/profiles/{id}` | No | No |
| CLI `profile delete` | local name-to-id map only (server state unaffected) | n/a | n/a |
| session `profileId` | `sessions.schema.ts` field + mount hook | No | No |
| session `persistProfile` | `sessions.schema.ts` field + release-time snapshot | No | No |
| `persist: true` | `session.service.ts:180-184` | **Yes, partial** | **Yes, partial** |
| `userDataDir: <path>` | `session.service.ts:180-184` | **Yes, but path ignored** | **Yes, but path ignored** |
| `sessionContext` capture/restore | `chrome-context.service.ts` | **Yes** | **Yes** |

The SDK confirms the route surface:

- `src/steel/resources/profiles.py:108` posts to `/v1/profiles`.
- `src/steel/resources/profiles.py:181` patches `/v1/profiles/{id}`.
- `src/steel/resources/profiles.py:222` lists `/v1/profiles`.
- `src/steel/types/session_create_params.py:116-120` declares `persistProfile` and `profileId`.
- `src/steel/_client.py:102-105` defaults the base URL to `https://api.steel.dev`.

Every one of those endpoints is absent from the OSS OpenAPI document.
The SDK is a cloud client, and it is the only artifact that defines the profile object.

## 6. The `persist` primitive is not a profile

`api/src/services/session.service.ts:180-184`:

```ts
const userDataDir =
  options.userDataDir || options.persist === true
    ? path.join(dirname(fileURLToPath(import.meta.url)), "..", "..", "user-data-dir")
    : env.CHROME_USER_DATA_DIR || path.join(os.tmpdir(), "steel-chrome");
await mkdir(userDataDir, { recursive: true });
```

Three consequences:

1. **Any** truthy `userDataDir` selects the same fixed path.
   A caller cannot choose a path.
   The expression is `(a || b) ? fixed : default`.
2. The fixed path resolves to `/app/api/user-data-dir`, which is on the container writable layer.
   The compose file mounts only `/app/.cache`.
3. All persistent sessions share that one directory.
   There is no name, no id, no status, and no per-caller isolation.

Verified on the running container:

```
$ sudo docker inspect polymerhus-steel-steel-api-1 --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
volume /var/lib/docker/volumes/polymerhus-steel_steel-cache/_data -> /app/.cache
$ sudo docker exec polymerhus-steel-steel-api-1 ls -ld /app/api/user-data-dir
drwxr-xr-x 9 root root 4096 Oct 19 16:26 /app/api/user-data-dir
```

`/app/api/user-data-dir` exists and is **not** a mount.
It dies with the container.

The commit that introduced this primitive states its intent:

```
$ git log -1 --format='%H%n%ci%n%s' 459be5b
459be5b857fa1d32d6dbfbcc0738bb839f8a4da2
2025-10-12 20:28:25 -0400
feat: foundation for usr-data-dir persistence (#210)
```

Its body includes the lines `feat: add persist, userDataDir option for saving profiles`.

This is the decisive nuance for the original context.
The OSS project did intend a profile-like capability.
It shipped the *storage primitive* only ("foundation"), and never the *management component*.
There is no later commit that builds the management layer.

## 7. Documentation evidence

### The self-hosting Profiles page is empty

`llms-full.txt:13755-13759`, shown with `cat -A`:

```
# Profiles$
URL: https://docs.steel.dev/overview/self-hosting/profiles$
$
$
$
# Self-Host Steel Browser on Railway$
```

The page body is two blank lines.
The source file confirms it is a stub:

`steel-dev/docs`, `content/docs/overview/self-hosting/profiles.mdx` at `c7c8883e75ec33f6366a2c657c8a3b008109e08c`:

```mdx
---
title: Profiles
sidebarTitle: Profiles
description: Self-Hosting Steel Browser Using Profiles
full: true
llm: true
---
```

Frontmatter only.
No content was ever written.

A page that is *titled* "Self-Hosting Steel Browser Using Profiles" but has no body is strong evidence that the capability was planned and not delivered.
It is not evidence that the capability exists.

### The Local vs Cloud table omits Profiles

`llms-full.txt:13842-13850`:

```
| Feature          | Steel Local                               | Steel Cloud                                                  |
|------------------|-------------------------------------------|--------------------------------------------------------------|
| Concurrency      | 1                                         | 100+                                                         |
| Stealth          | Limited                                   | Advanced Stealth (docs)                                      |
| CAPTCHA Solving  | None                                      | Supported with the CAPTCHAs API                              |
| Proxies          | Bring your own                            | Bring your own + Steel Managed Proxies                       |
| Credentials      | Not supported                             | Supported with the Credentials API                           |
| Extensions       | Supported by loading in `api/extensions/` | Supported by using the Extensions API                        |
| Files            | Not supported                             | Supported by the Files API                                   |
```

Profiles appears in **neither** column.

The table explicitly enumerates four management components: CAPTCHAs API, Credentials API, Extensions API, Files API.
Profiles is a fifth member of that same family and is absent from the list.

This omission is the ambiguity named in the task.
Resolve it against the artifact, not the table: the artifact has no profiles route.
The table is incomplete, not permissive.

### The Profiles API docs never mention self-hosting

`llms-full.txt:13350-13365`:

```
# Overview
URL: https://docs.steel.dev/overview/profiles-api/overview

Steel's profiles API allows you to create, update, and persist profiles across sessions. ...

### Limits
- There is a 300 MB limit on the size of a profile, if the upload fails after a session, the profile will be set to a `FAILED` state and cannot be used
- If a profile is not used after 30 days, it will be automatically deleted
```

The lifecycle is described at `llms-full.txt:13362-13370`:

```
1. Session gets created with a `persistProfile` flag
2. Initial profile gets created with some information on the session and gets stored in an `UPLOADING` state
3. After the session is released, the userDataDir is persisted and the additional information on the profile is updated and the profile is set to the `READY` state
4. Whenever a session is created with the `profileId`, the profile is loaded from the storage and the session is started with the same userDataDir and context
```

The 300 MB limit and the 30-day retention rule are **server-side** properties.
They require an object store, a database, and a reaper job.
The OSS compose stack has none of these.

Section `llms-full.txt:13370` onward is titled "Persisting browser information manually" and shows `client.profiles.create` with a zip upload.
No passage in the Profiles API section mentions local mode, self-hosting, or `--api-url`.

### The cookbook strengthens the server-side reading

`llms-full.txt:8021`:

> A Steel profile is a named, long-lived browser identity. It holds everything a real Chrome user profile accumulates over time: cookies, localStorage, IndexedDB, history, installed extensions, autofill, site permissions. Every session you attach to the profile starts where the last one left off, and writes the user data directory back on release.

`llms-full.txt:8110`:

> Treat the profile like an account. Anyone who can call `sessions.create({ profileId })` on your workspace can drive a browser logged in as you.

"Workspace" is cloud tenancy.
A local stack has no workspaces.

### The one pro-profile sentence, and why it does not hold

`steel-dev/skills`, `steel-skill-creator/references/steel-primitives.md:11`, at `35bf278371312964a177f15b679b5e290f9ef275`:

```
| Site requires persistent logged-in state across sessions | Profile | All tiers |
```

"All tiers" sits in a column headed `Plan`.
Sibling rows read `Paid`.
So the value contrasts free and paid **cloud plans**, not local and cloud.
The same file at line 71 says:

> If the steel CLI doesn't expose a profile flag in your installed version, the generated skill should fall back to the SDK form and the body should note the CLI/SDK split.

`steel-dev/skills`, `steel-browser/references/steel-browser-lifecycle.md:146-155`:

```
## Profile persistence

steel browser start --session "$SESSION" --profile myapp --update-profile

- `--profile <name>`: Load a previously imported browser profile (cookies, storage, etc.) into the session.
- `--update-profile`: Save session state back to the profile when the session ends.

Profiles are created outside agent workflows via `steel profile import`. Agents should only consume them with the flags above.
```

Nothing in either skill claims local support.
The lifecycle doc lists `--local` and `--api-url` three lines earlier (`:140-144`) and does not qualify the profile flags with either.

That is the same trap the task context describes: the flags parse locally and do nothing.

## 8. Client-side behavior confirms cloud targeting

`steel-dev/cli` at `6ea1953f9770bcbdd5d0ae7e98c80a39ac931b95`.

- `src/browser/profile_store.rs:39-40`: profiles are stored under `config_dir()/profiles`.
  This is a local name-to-id map.
- `src/commands/profile.rs:100-104`: `list` reads that local map only.
- `src/commands/profile.rs:164-170`: `resolve_api()` **requires an API key**:

```rust
fn resolve_api() -> anyhow::Result<(String, String)> {
    let (_, base_url, auth) = api::resolve_with_auth();
    let api_key = auth.api_key.ok_or_else(|| {
        anyhow::anyhow!("Not authenticated. Run `steel login` or set STEEL_API_KEY.")
    })?;
    Ok((api_key, base_url))
}
```

- `src/browser/profile_porter.rs:1016`: upload/update sends `PATCH {api_base}/profiles/{profile_id}` as multipart.
- `src/commands/profile.rs:39-57`: `ImportArgs` has `name`, `--from`, `--browser`, `--full`.
  It has **no `--local` and no `--api-url` of its own**; the global flags on the top-level command cover that.

So `steel profile import` and `steel profile sync` target the configured base (cloud by default, or the global `--local` / `--api-url` base) and always require a key.
Against the local API the upload route 404s.
`steel profile list` and `steel profile delete` operate on local JSON only.

This explains the observed split in the tool layer:

- `profile list` works locally because it never touches the network.
- `POST /v1/profiles` 404s because the server never had the route.
- `start --profile` "succeeds" because the create schema strips the unknown keys.

## 9. Why the field stripping is silent

`api/src/modules/sessions/sessions.schema.ts:69-70` declares only:

```ts
persist: z.boolean().optional().describe("Flag to indicate if session should be persisted"),
userDataDir: z.string().optional().describe("User data directory path to use for the session"),
```

There is no `profileId` and no `persistProfile`.
The create object is a plain `z.object`, which strips unknown keys by default.
Fastify therefore accepts the body, drops the profile keys, and creates a session.

This is the mechanism behind the observed "silent success".
It is also why a capability probe that only checks HTTP 200 will not detect the gap.

## 10. Three-way distinction, stated explicitly

| Claim | Verdict | Evidence |
|---|---|---|
| Not found in the pinned image | **True** | modules list, OpenAPI paths, live 404s, grep of `/app/api/build` |
| Not found anywhere in OSS history | **True** | pickaxe for `persistProfile`/`persist_profile`/`ProfileStatus`/`UPLOADING`/`/profiles` all empty; no `profileId` in any `api/src` or `ui/src` on any ref |
| Present but not deployed | **False** | image `api/src` is byte-identical to `main`; `main` is 8 commits past the newest tag; no ref holds a profiles component |

The third row is the one that matters for the original doubt.
There is no hidden component to enable.
There is no build flag, no compose profile, no env var, and no newer tag.

## 11. What would have to exist, and does not

A self-hosted profile feature would need all of these.
None exists in the OSS repo.

1. **A profiles module**: `api/src/modules/profiles/{routes,controller,schema}.ts`.
   Absent.
2. **Route registration**: a line like `fastify.register(profilesRoutes, { prefix: "/v1" })` in `api/src/steel-browser-plugin.ts`.
   Absent; only six route groups register at `:81-84`.
3. **Persistent storage**: a database for profile metadata and an object store for the `userDataDir` zip.
   `docker-compose.yml` defines only `api`, `ui`, and two named volumes for logs and exports.
   No database service, no S3 client, no bucket config.
4. **A status machine**: `UPLOADING` -> `READY`/`FAILED` with a reaper for the 30-day rule.
   Absent from `api/src` and from `api/src/services`.
5. **A release-time snapshot hook**: code that zips `userDataDir` on session release and uploads it.
   Absent.
   `session.service.ts` releases without archiving user data.
6. **Session integration**: `profileId` and `persistProfile` in the create schema, plus resolution to a stored directory at launch.
   Absent; `sessions.schema.ts:69-70` has only `persist` and `userDataDir`.
7. **A UI surface**: a profiles page in `ui/src`.
   `ui/src/containers` holds only `session-container.tsx`.
   `ui/src/components` holds `badges`, `header`, `icons`, `illustrations`, `loading`, `sessions`, `theme-provider.tsx`, `ui`.
   No profiles.

## 12. Residual uncertainty

Two small gaps remain, both immaterial to the verdict.

1. **The docs table omission is unexplained.**
   No source states why Profiles is missing from the Local vs Cloud table.
   The most likely reading is an oversight, since the family's other four members are listed.
   The artifact settles the question either way.
2. **The empty self-hosting page has no history on `main`.**
   The docs repo was cloned shallow, so the page's authorship date was not recovered.
   Its content is frontmatter only at `HEAD` (`c7c8883`), which is sufficient.

No other source was found that claims a self-hosted profiles implementation.

## 13. Reproducing this research

All commands were run on `dj-viscon-workshop-1`.

```bash
ssh ubuntu@192.33.91.87
df -h /
mkdir -p /tmp/steel-research && cd /tmp/steel-research

# repo, full history and all refs
git clone https://github.com/steel-dev/steel-browser.git repo
cd repo && git log -1 --format='%H %ci %s'
git tag | wc -l                 # 23
git branch -r | wc -l           # 133

# exhaustive negative searches
git log --all --oneline -SpersistProfile
git log --all --oneline -Spersist_profile
git log --all --oneline -SProfileStatus
git log --all --oneline -SUPLOADING
git log --all --oneline -S"/profiles"
git log --all --oneline -SprofileId   # ff717f1, 53f32ba only

# image identity and surface
sudo docker inspect polymerhus-steel-steel-api-1 --format '{{.Image}}'
sudo docker image inspect $(sudo docker inspect polymerhus-steel-steel-api-1 --format '{{.Image}}') \
  --format '{{.RepoDigests}} {{.Created}}'
sudo docker exec polymerhus-steel-steel-api-1 ls /app/api/build/modules
sudo docker exec polymerhus-steel-steel-api-1 node -e \
  'const s=require("/app/api/openapi/schemas.json");console.log(Object.keys(s.paths).sort().join("\n"))'

# image == main
sudo docker cp polymerhus-steel-steel-api-1:/app/api/src ./img-src
diff -rq img-src repo/api/src && echo IDENTICAL

# live probes
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/v1/profiles
curl -s -o /dev/null -w '%{http_code}\n' -X POST -d '{}' -H 'Content-Type: application/json' http://127.0.0.1:3000/v1/profiles

# docs and clients
curl -sSL -o llms-full.txt https://docs.steel.dev/llms-full.txt
git clone --depth 1 https://github.com/steel-dev/docs.git docs
git clone --depth 1 https://github.com/steel-dev/skills.git skills
git clone --depth 1 https://github.com/steel-dev/cli.git cli
git clone --depth 1 https://github.com/steel-dev/steel-python.git sdk
```

Local clones and image layers created during the first pass were deleted from the Mac.
The 911 MB research directory was removed before the remote run.
