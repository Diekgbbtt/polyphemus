# Real eval project artifacts dashboard design

## Status

Approved design for `feat/eval-pipeline-frontend`. This document extends the
read-only eval dashboard defined in `docs/design/eval-dashboard-290-spec.md`.
It does not authorize implementation by itself; implementation follows a
separate reviewed plan.

## Objective

Serve the dashboard from the real eval server and let an operator inspect the
immutable hunting artifacts and project-authored skills that belonged to a
completed eval Trial.

Success means:

- the read API runs beside the real artifact store and mounts it read-only;
- a newly materialized Trial contains a complete, immutable snapshot of the
  approved project-artifact paths;
- `/snapshot` remains lightweight while project artifacts load on demand;
- the frontend provides semantic views for known formats and raw access for
  every allowlisted artifact;
- a malformed or unavailable artifact affects only its own view;
- historical Trials remain readable without pretending that a complete
  project snapshot can be reconstructed after the fact.

## Decisions

1. Project artifacts are captured per Trial, not read from the mutable
   `<store>/<instance_id>/live/` mirror.
2. Only completed, materialized Trials are in scope. Live monitoring and
   polling are out of scope.
3. The read API is co-located with `/srv/eval-artifacts`; browsers never access
   the filesystem directly.
4. The API stays GET-only. `/snapshot` carries summaries and identifiers, not
   artifact bodies.
5. Known YAML receives a semantic representation, Markdown is sanitized,
   scripts and logs are rendered as text, and binary assets are download-only.
6. Every artifact retains a raw representation.
7. Existing demo behavior remains separate from the real deployment overlay.
8. Historical schema-v1 Trials expose `project_artifacts_unavailable`; the
   system does not backfill them from `live/`.

## Existing storage model

The eval setup files configure the durable store at `/srv/eval-artifacts`.
The current materializer publishes authoritative Trial trees at:

```text
<store>/<target_id>/<target_run_id>/<trial_id>/
  run-manifest.yaml
  verdicts.yaml
  diagnoses.yaml
  <project_id>/...       # copied verdict evidence only
```

The instance data root contains the full project state at:

```text
<instances_root>/<instance_id>/data/<project_id>/
```

The secondary one-way mirror lives at:

```text
<store>/<instance_id>/live/<project_id>/
```

The mirror is unsuitable as a historical source: it changes after a Trial and
uses `delete = false`, so moved or removed source files can remain stale.

## Target storage contract

Materialization preserves the data-root-relative layout already used by
verdict evidence. The new snapshot fills the approved hunting and skills
subtrees under the same project directory:

```text
<store>/<target_id>/<target_run_id>/<trial_id>/
  run-manifest.yaml
  verdicts.yaml
  diagnoses.yaml
  <project_id>/
    hunting/
      orchestration/hunt_configs/{produced,consumed}/...
      hunter/test-specs/<fault_key>/{produced,consumed}/...
      test-executor-pod/<spec_id>/
        variants/...
        experiment-log/...
        <run_id>.yaml
    skills/
      <skill_name>/
        SKILL.md
        references/...
        scripts/...
        assets/...
```

Existing evidence-chain paths continue to resolve unchanged because the
snapshot uses the same `<project_id>/...` namespace. Duplicate source paths are
copied once and represented once in the inventory.

Only regular files are eligible. Symlinks, sockets, devices, traversal,
absolute paths, and any resolved path outside the project root are rejected.
Directories absent from the source are valid empty groups.

## Artifact allowlist

The materializer recognizes only these project-relative patterns:

```text
hunting/orchestration/hunt_configs/produced/*.yaml
hunting/orchestration/hunt_configs/consumed/*.yaml
hunting/hunter/test-specs/<fault_key>/produced/*.yaml
hunting/hunter/test-specs/<fault_key>/consumed/*.yaml
hunting/test-executor-pod/<spec_id>/variants/*.yaml
hunting/test-executor-pod/<spec_id>/experiment-log/*.yaml
hunting/test-executor-pod/<spec_id>/*.yaml
skills/<skill_name>/SKILL.md
skills/<skill_name>/references/**
skills/<skill_name>/scripts/**
skills/<skill_name>/assets/**
```

`<fault_key>`, `<spec_id>`, and `<skill_name>` are path-safe single segments.
Nested files are accepted only below the three named skill support
directories. Files outside the allowlist remain private even if present in the
data root or live mirror.

## Manifest and identity

New materializations use store schema version 2. `run-manifest.yaml` gains:

```yaml
project_artifacts:
  status: available
  project_id: <project_id>
  captured_at: <UTC timestamp>
  snapshot_sha256: <digest of the normalized complete Trial file set>
  entries:
    - artifact_id: <sha256 of normalized project-relative path>
      category: hunting | skill
      kind: hunt_config | test_spec | pod_variant | experiment_log | pod_export | skill_procedure | skill_reference | skill_script | skill_asset
      relative_path: <project-relative POSIX path>
      media_type: <normalized media type>
      size_bytes: <integer>
      sha256: <content digest>
      representation: yaml | markdown | text | binary
```

The artifact id is deterministic within the Trial and is resolved only through
the manifest inventory. The client never submits a filesystem path. The
content digest is checked again before the API serves an artifact.

`snapshot_sha256` is computed from the sorted relative paths and content
digests of every non-manifest Trial file plus the canonical manifest payload
with `copied_at`, `captured_at`, and `snapshot_sha256` omitted. It therefore
stays stable when identical inputs are materialized at a later time and avoids
a self-referential digest.

Schema-v1 manifests remain supported. Their projected Trial carries:

```json
{
  "artifact_summary": {
    "status": "project_artifacts_unavailable",
    "hunting": 0,
    "skills": 0
  }
}
```

This status means the historical snapshot was never captured. It is not a
degraded Trial and does not affect verdict or diagnosis availability.

## Materialization lifecycle

Before publishing, the materializer:

1. loads and validates the Trial record, verdicts, diagnoses, and evidence
   chain exactly as today;
2. enumerates the allowlist from the Trial's project directory;
3. rejects unsafe entries and records metadata and digests for regular files;
4. copies the evidence chain and project-artifact union into a staging tree;
5. writes verdicts, diagnoses, and the schema-v2 manifest into staging;
6. verifies that every inventory entry exists, remains contained, matches its
   digest, and that the existing self-contained evidence checks pass;
7. publishes the complete Trial tree only after all checks succeed.

A first publication is immutable. Repeating materialization with the same
prospective `snapshot_sha256` is an idempotent no-op and retains the original
timestamps. A different fingerprint for an already published Trial fails with
a named `snapshot_conflict` error rather than silently changing historical
evidence.

Missing allowlisted directories are normal. An unsafe path or read failure
prevents publication. Invalid YAML is copied and inventoried; its entry exposes
`parse_error` at read time while preserving the raw bytes.

## Read API

The existing `/snapshot` response adds `artifact_summary` to every Trial:

```json
{
  "status": "available",
  "hunting": 14,
  "skills": 6
}
```

Artifact bodies are served on demand through these GET-only routes:

```text
GET /trials/{target_id}/{target_run_id}/{trial_id}/artifacts
GET /trials/{target_id}/{target_run_id}/{trial_id}/artifacts/{artifact_id}
GET /trials/{target_id}/{target_run_id}/{trial_id}/artifacts/{artifact_id}/content
```

The list route returns inventory entries grouped by hunting family and skill
bundle. The detail route returns metadata plus one safe representation:

- `yaml`: `yaml.safe_load` output when valid, or `parse_error` with no parsed
  value when invalid;
- `markdown`: UTF-8 source for sanitized client-side rendering;
- `text`: UTF-8 source suitable for a code/log viewer;
- `binary`: metadata and the content URL only.

The content route streams original bytes without loading the complete file in
memory. Active or binary content is always an attachment with
`Content-Disposition: attachment`; it is never rendered inline by the API.
Text and Markdown previews are limited to 512 KiB and report truncation. YAML
larger than 2 MiB is download-only and is not parsed. Raw download remains
available at either limit.

Every request resolves the Trial under the configured store, loads the
manifest, maps `artifact_id` to an inventory entry, re-checks containment and
file type, and verifies the digest. Unknown Trial and artifact identifiers are
404. Unsafe metadata, digest disagreement, or an unreadable file produces a
safe artifact-local error without exposing host paths.

## Frontend information architecture

The Trial page retains its existing manifest, verdict, diagnosis, and evidence
views. It adds a `Project artifacts` summary and a dedicated route:

```text
/eval/trials/:targetId/:targetRunId/:trialId/project-artifacts
/eval/trials/:targetId/:targetRunId/:trialId/project-artifacts/:artifactId
```

The project-artifact index groups entries as:

```text
Hunting
  Hunt configs
    Produced
    Consumed
  Test specs
    <fault_key>
  Pod executions
    <spec_id>
Skills
  <skill_name>
    Procedure
    References
    Scripts
    Assets
```

An artifact detail page shows breadcrumbs, kind, relative path, size, digest,
semantic representation, and a `Raw` view or download action.

- Known YAML uses typed cards and tables, with a generic YAML tree fallback.
- `SKILL.md` and Markdown references render through sanitized Markdown.
- Scripts and logs use a syntax-aware text viewer.
- Binary assets show metadata and download only.
- A malformed representation shows the parse error and retains raw access.

Loading and failure state belongs to the artifact route. It must not replace or
degrade the already-loaded Trial snapshot. Browser history, refresh, and direct
links remain supported.

## Deployment

The synthetic overlay remains unchanged and explicitly demo-only. A separate
real dashboard overlay:

- omits the `eval-store` demo generator;
- runs the read API on the eval server;
- bind-mounts
  `${EVAL_ARTIFACT_STORE_HOST_PATH:-/srv/eval-artifacts}` read-only;
- sets the container's `EVAL_ARTIFACT_STORE` to the mounted path;
- points the frontend's `/eval-api` proxy at the co-located read API;
- binds API and frontend ports to loopback by default;
- never mounts the instance data root or the `live/` mirror separately.

Health reports distinguish configuration, store readability, and whether at
least one materialized Trial is discoverable. An empty readable store is
healthy but reports zero Trials.

## Error model

- `project_artifacts_unavailable`: historical schema-v1 Trial; normal
  compatibility state.
- `parse_error`: one text/YAML artifact cannot be interpreted; raw remains
  available.
- `artifact_missing`: an inventoried file is absent.
- `artifact_digest_mismatch`: bytes no longer match the immutable inventory.
- `artifact_unsafe`: containment, symlink, or allowlist verification failed.
- `snapshot_conflict`: a caller attempted to rematerialize an existing Trial
  with different bytes.

Artifact errors never reveal absolute host paths, credentials, or file
contents not requested through an inventory identifier.

## Testing strategy

Materializer unit tests cover:

- every allowlisted family and exclusion of neighboring paths;
- missing optional directories;
- deduplication between evidence-chain and project-snapshot copies;
- deterministic ids, metadata, and digests;
- symlink, traversal, unreadable file, and unsafe segment rejection;
- complete staged publication;
- equivalent rematerialization and `snapshot_conflict` on changed input;
- schema-v1 compatibility.

Read API tests cover:

- lightweight `/snapshot` summaries;
- grouped inventory, detail, preview, and raw download;
- YAML, Markdown, text, and binary representations;
- preview limits and truncation metadata;
- malformed YAML, missing files, digest mismatch, and unknown ids;
- path-free error responses and absence of arbitrary-path access.

Frontend tests cover:

- Trial summary and both project-artifact routes;
- hunting and skill grouping;
- typed YAML, sanitized Markdown, script/log, binary, and raw renderers;
- loading, empty, unavailable, parse-error, and download states;
- refresh, breadcrumbs, direct navigation, and isolated failures.

Integration verification uses a realistic temporary data root, materializes a
Trial, reads it through the actual FastAPI routes, and consumes the responses
with the frontend client contract. Compose validation checks both the unchanged
demo overlay and the new real overlay.

## Non-goals

- displaying or polling an eval while it is running;
- reading project artifacts directly from `live/`;
- modifying, deleting, or uploading artifacts;
- retroactively reconstructing complete snapshots for historical Trials;
- rendering active binary content inline;
- exposing arbitrary filesystem paths;
- public internet authentication or authorization for the dashboard;
- changing eval execution, assessment, or diagnosis semantics.
