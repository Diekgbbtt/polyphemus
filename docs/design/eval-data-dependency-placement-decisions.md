# Eval data-dependency placement - decisions

Status: accepted (implementation).
Owner: project-management + app/auth + app/llm/skills + analysis/scaffold.
Related: `eval/DATA-DEPENDENCIES.md`, `docs/design/auth-store-220-decisions.md`, `docs/design/recon-auth-gateway-223-spec.md`, `docs/design/eval-multi-instance-spec.md`, `docs/design/skill-writing-primitives-spec.md`.

## Context

The eval harness builds three pre-built data dependencies per target: the L1 surface, the AuthContext (`overview.yaml` + `credentials.yaml`), and the project `authn` skill.
The operator directive is that the agent container finds these files already present under the data directory at startup - a MOUNT, not a runtime provision.
The trial therefore creates the project deterministically, then places the artifacts through NEW app-API endpoints.
The old delivery was the inline `TargetConfig.auth` blob plus the `PUT /projects/{id}/auth` seed, which is obsolete.

## D1 - Topology: mount-at-startup, not trial-side provision

The app-owned data root is the mount seam.
The four placement endpoints write the canonical project-scoped paths under `<data_root>/<project_id>/`, which is the same layout `AuthStore` and `SkillStore` read.
A container that mounts `<data_root>/<project_id>/` at startup sees the artifacts without any in-container provisioning call.
The project is created first (`POST /projects`), so every placement has a live `project_id` and a scaffolded project directory.

## D2 - The four endpoints and their contract

All four are `POST`, project path-scoped (the codebase convention; `project_id` is the path parameter, not a body key), and NON-IDEMPOTENT: each call always overwrites, and creates the canonical file when absent.

| Method | Path | `file` part | Landing |
|---|---|---|---|
| POST | `/projects/{project_id}/data-dependencies/authn-skill` | a `.tar.gz`/`.zip` bundle | `<data_root>/<project_id>/skills/authn/` (`SKILL.md` + `references/`) |
| POST | `/projects/{project_id}/data-dependencies/auth-overview` | `overview.yaml` bytes | `<data_root>/<project_id>/auth/overview.yaml` |
| POST | `/projects/{project_id}/data-dependencies/auth-credentials` | `credentials.yaml` bytes | `<data_root>/<project_id>/auth/credentials.yaml` |
| POST | `/projects/{project_id}/data-dependencies/l1` | `operator_kb.md` bytes | the L1 graph (no file) |

Response on success is `{ok: true, ...}` with the artifact-specific detail: the skill names its files, the auth endpoints name the written path, and the L1 endpoint returns `{services_written, systems_written}`.
Error mapping: unknown project -> 404; malformed upload/archive -> 400 `data_dependency_invalid`; a store shape refusal -> 400 `auth_invalid` / `skill_invalid` / `skill_target`; a credential-identity collision -> 500 `duplicate_identity`; a broken KB (zero Services) -> 400 `scaffold_invalid`; a degraded graph (the sole-writer merged nothing) -> 503 `l1_persist_blocked`; an unavailable store -> 500 `store_unavailable`.
Every refusal lands nothing, because the stores validate before writing.
A missing `file` part is FastAPI's own 422 (required-part validation).

## D3 - The transport is multipart/form-data, not a JSON pack envelope

The files are YAML/Markdown and the server creates the canonical file, so JSON double-encoding was the wrong transport.
Each endpoint is `multipart/form-data` with one required `file` part (`type: string, format: binary`) carrying the raw bytes.
`fileName` is an optional multipart attribute kept only as a natural part of the content-type; it is NEVER used to build a path (the canonical destination is hardcoded server-side).

The exact requestBody on all four operations:

```yaml
requestBody:
  required: true
  content:
    multipart/form-data:
      schema:
        type: object
        properties:
          fileName: { type: string }
          file: { type: string, format: binary }
      required: [file]
```

FastAPI emits `contentMediaType: application/octet-stream` for an `UploadFile`, not `format: binary`, so `app/main.py` installs a `custom_openapi` that stamps the exact schema onto the four operations (`data_dependencies.patch_openapi`).

`authn-skill`'s `file` is a SINGLE ARCHIVE (`.tar.gz` or `.zip`); the server validates and unpacks it into the canonical bundle, rejecting traversal (`..`), absolute (`/`, drive-letter) and symlink members. Endpoints 2/3/4 take a single file's bytes.
There is no packed file-content codec: the previous JSON pack envelope is retired.

## D4 - L1 persistence reuses the deterministic scaffold

The L1 endpoint does NOT run the two-LLM `POST /bootstrap`.
It reuses the eval's existing deterministic scaffold, now moved into the platform as `polymerhus.analysis.scaffold` (extracted from `eval/scaffold.py`, which is now a thin CLI wrapper).
`scaffold_project(project_id, operator_kb)` runs `build_shells` -> `shells_to_batch` -> `proposals_to_deltas` -> `l1_curator.l1_curate` - the same sole-writer path the LLM bootstrap uses, with no LLM call and no run-to-run drift.

The L1 payload is therefore the structured `operator_kb.md` bytes (the format the scaffold consumes).
The richer graph-ready `l1-surface.yaml` rendering is NOT consumed by this endpoint or by the wired delivery at all (see D6 and Non-goals).
The `SYSTEM_KINDS` vocabulary is single-sourced from `l1_curator` so the scaffold and the sole-writer cannot drift.
A sole-writer that merges zero units is a degraded graph, so the endpoint fails closed with 503 `l1_persist_blocked` rather than a zero-count success (the bootstrap's fail-closed rule).

## D5 - The `PUT /auth` seed and inline `TargetConfig.auth` are retired

The `PUT`/`GET /projects/{id}/auth` seed face and the `TargetConfig.auth` mapping delivered the AuthContext by merge/seed.
The new endpoints deliver the same state by exact file write, which is what the mount topology requires: the agent reads the file the operator wrote, not a store projection of a seed.
The old `PUT /auth` handler and its use-cases are NOT deleted in this change (the frontend and existing tests still use them), but they are deprecated for eval placement and must not be used by the eval harness.
`save_project_settings` already refuses the retired `auth_context` settings key, so no settings-blob auth path survives.

The store's write path is reused, never hand-rolled:

- `AuthStore.put_overview` / `AuthStore.put_credentials` validate through `records.validate_overview` / `validate_account` and replace the canonical file wholesale (never a merge).
  `put_credentials` defaults a missing `origin` to `operator`, stamps `updated_at` server-side, and refuses an identity collision with `DuplicateIdentityError`.
- `SkillStore.replace_bundle` writes a pre-built bundle verbatim (no frontmatter composition or version bump), re-validating the `SKILL.md` frontmatter and rejecting unsafe paths.

## D6 - `l1-surface.yaml` is delivered as the graph-ready companion (amended 2026-10-07)

Originally: the L1 bootstrap consumed `operator_kb.md` ONLY and the graph-ready `l1-surface.yaml` was NOT delivered, with no converter built for it.
Amended: the `l1-surface.yaml` IS delivered for every pre-pulled target.
It is the graph-ready rendering of the same surface `operator_kb.md` describes - pure Neo4j knowledge-graph data the backend persists at project start through one parameterised MERGE per unit and per edge, with `project_id` the sole query parameter (never baked into the file), exposed through the data-dependency placement REST face.
Its format is the L1 write contract:

- `label` in `{Service, System}`; a Service is keyed `business_function_slug`, a System `kind` + `discriminator` (the identify/authenticate/authorize linchpins use the literal `__singleton__`).
- `props` are valid L1 props only; edges are `EXPOSED_VIA` / `AUTHENTICATED_BY` / `AUTHORIZED_BY` (and `CONSUMES` / `PRODUCES` where a DataItem exists).
- Every edge endpoint resolves within the file and every identity is unique.

The delivered `operator_kb.md` remains the companion the deterministic scaffold consumes; the `l1-surface.yaml` node set is verified equal to `shells_to_batch`'s output (set-equality), so the two renderings cannot drift.

## Build-artifact conformance (normalized 2026-10-04)

The builder's own validator (`eval/validate_data_dependencies.py`) originally checked presence and top-level shape only, never `validate_overview` / `validate_account`, so it accepted artifacts the endpoints then refused.
The validator now calls the app's T1 seam, and the artifacts were normalized to it (only `phpbb` conformed before):

- `account.roles`: the LIST of role names was converted to a mapping role -> credential set (a copy of the account's own `credentials`, which all role lists duplicated) in 7 targets.
- `account.snapshot.cookies`: the MAPPING was converted to a list of `{name, value}` in 8 targets.
- `overview.login_endpoint` / `overview.fingerprinting`: null values were removed (comfyui, siyucms); `ofbiz`'s list `fingerprinting` and mapping-shaped `defences` entries were joined into the string/list-of-strings the seam requires.
- Header-located token names `access_token_openremote` / `access_token_admin_cli` (openremote) were renamed to RFC 7230 tokens `access-token-openremote` / `access-token-admin-cli`; the skill was updated consistently.
- `prestashop`'s `admin_token` used `location: query`, a carrier the closed location enum cannot express; its value was preserved as `snapshot.params.admin_token` (its real query carrier) and the token entry removed, with the skill updated.

All secret values were preserved. Re-verified: all 11 targets conform to the T1 seam.

## D7 - Impact map: the delta from the old provision path

The endpoint-surface change ripples across the eval system. Consumers of the old inline-`TargetConfig.auth` + `seed_auth` PUT path and the host-side scaffold, and their disposition:

| Component | Old behaviour | New behaviour |
|---|---|---|
| `eval/orchestrator/trial.py` | `seed_auth` PUT + `write_text` of the skill + host-side `scaffold.py` command | `_place_data_dependencies` uploads auth-overview / auth-credentials / authn-skill (as a `.tar.gz`) through the multipart endpoints; `_place_l1` uploads `operator_kb.md`; `ScaffoldSpec` / `plan_scaffold` deleted; the trial verifies the skill landed |
| `eval/orchestrator/api.py` | `seed_auth(overview, accounts)` PUT builder, JSON-only `HttpApiRunner` | `place_auth_overview/credentials/authn_skill/l1` builders; `ApiFile` + multipart body encoding in `HttpApiRunner`; `seed_auth` deleted |
| `eval/orchestrator/cli.py` | `auth=run.target_config.auth`, built `ScaffoldSpec` | `data_dir=_data_dependency_dir(...)` and `auth_surface=<data_dir>/skills/authn exists`; no `scaffold=` |
| `eval/orchestrator/setup.py` | `TargetConfig.auth` / `l1_surface` mappings | `TargetConfig.data_dir`; the retired keys are refused; the dead shadowing `TargetConfig` dataclass removed |
| `eval/orchestrator/files.py` | `authn_skill_path` (used by the trial writer) | unchanged (still the read path the predicate and the trial's landing check use) |
| `eval/orchestrator/predicates.py` | `recon_entry` reads the skill file + `GET /auth` | unchanged (reads the placed state; no write) |
| `eval/scaffold.py` | standalone deterministic scaffold | thin CLI wrapper over `polymerhus.analysis.scaffold` (the platform module the `l1` endpoint reuses) |
| `eval/setups/first-8.yaml` | inline `auth:` blocks per target | blocks removed; each target declares `data_dir: eval/data/webexploitbench/<target>`; auth-bootstrap work item complete |
| `eval/setups/{first,comfyui-*.yaml,webexploitbench-chain,mock-local}.yaml` | no inline `auth:` (never carried one) | unchanged |
| `eval/prompts/orchestrator.md` | "provisions the next [image]" (image provisioning, not auth) | unchanged (image provisioning is unaffected) |
| `eval/prompts/{assessment,diagnoser,assessor-workflow,diagnoser-workflow}.md`, the monitor tool | describe post-execution workflow only | unchanged (no auth/provision wording) |
| app API (`project_management/api.py`, `data_dependencies.py`) | - | the four multipart endpoints + archive unpack + OpenAPI stamp |

## Non-goals

- No direct `l1-surface.yaml` ingestion (would need a surface-to-delta converter).
- No deletion of the legacy `PUT /auth` seed face (the frontend keeps using it).
- No change to the auth record shapes or the skill frontmatter contract.
- No packed content codec (the transport is multipart).

## Consequences

- The eval harness places all three data dependencies through one uniform, non-idempotent request shape.
- The deterministic scaffold is now a platform capability, so app and eval cannot diverge.
- The auth and skill stores gained a wholesale-replace entry point; their existing merge/seed paths are unchanged.
