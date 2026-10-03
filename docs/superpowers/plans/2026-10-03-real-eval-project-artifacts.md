# Unified Eval Project Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing project page into one workspace for live operations and completed eval Trials, including each Trial's immutable L0/L1 graph, hunting artifacts, and project-authored skill bundles.

**Architecture:** Capture the final graph before Trial teardown, then publish it atomically with the allowlisted project artifacts in a schema-v2 immutable snapshot. Keep `/snapshot` lightweight and serve historical graph/artifact bodies through GET-only routes. Reuse the existing project routes and `GraphCanvas` for a unified hub while keeping live and historical data sources visibly separate.

**Tech Stack:** Python 3, PyYAML, FastAPI, pytest, Docker Compose, React 19, TypeScript, React Router, Vitest/Testing Library, `react-markdown`, `rehype-sanitize`, `prism-react-renderer`.

**Spec:** `docs/superpowers/specs/2026-10-03-real-eval-project-artifacts-design.md`

## Global Constraints

- New materializations use store schema version 2; schema-v1 Trials remain readable and report unavailable project graph/artifacts without becoming degraded.
- Capture `project-graph.json` at Trial finalization before instance teardown; materialization must never query or reconstruct a live graph.
- Publish graph and artifact inventory as one auxiliary project snapshot: both available or both unavailable. Snapshot failure never changes the Trial eval outcome or hides its validated verdict/diagnosis bundle.
- Reuse the existing `GraphData`, `GraphCanvas`, projection, colors, and independent L0/L1 toggles for historical graphs.
- Historical routes must never silently fall back to `GET /projects/{project_id}/graph`; returning to the live project is an explicit navigation action.
- Join projects to Trials with `project_id`; address a Trial by the full `(target_id, target_run_id, trial_id)` tuple.
- Snapshot only completed materialized Trials. Never read project artifacts from `<store>/<instance_id>/live/`.
- Preserve project-relative paths below `<trial>/<project_id>/`; existing verdict evidence references must continue to resolve.
- Copy only the hunting and skill allowlist in the spec; reject symlinks, special files, traversal, and resolved paths outside the project root. Safe dynamic segments may contain domain punctuation including `:` and repeated `::`, but never slash, backslash, NUL, control characters, `.` or `..`.
- First publication is immutable. Equal `snapshot_sha256` is an idempotent no-op; different content for the same Trial is `snapshot_conflict`.
- The read API remains GET-only and never accepts an arbitrary filesystem path or returns an absolute host path.
- Text and Markdown previews stop at 512 KiB; YAML larger than 2 MiB is download-only; raw content streams instead of being loaded wholly into memory.
- Binary and active content use `Content-Disposition: attachment`; the frontend never renders them inline.
- Keep `eval/docker-compose.dashboard.yml` demo-only. Real deployment uses a separate overlay with `/srv/eval-artifacts` mounted read-only and loopback-only published ports.
- Do not modify or commit the pre-existing untracked files listed by `git status`; stage only files named by the active task.

## Review Focus

- Real fault keys containing `:` or repeated `::` must catalog normally while separators/control characters remain rejected; Task 1 pins this.
- A graph-capture failure or unsafe nested artifact must preserve the core eval result while publishing no partial project snapshot; Tasks 2 and 3 pin this.
- A repeated materialization with identical bytes but a later clock must preserve original timestamps, while one changed byte must raise `snapshot_conflict`; Task 3 pins this.
- Invalid UTF-8, malformed YAML, exact preview boundaries, and path-like artifact ids must not crash, over-read, or escape the manifest inventory; Task 6 pins this.
- The same `project_id` with different live and historical graphs must render the selected source only, including during late responses and direct-route refresh; Tasks 7 and 8 pin this.

---

## File map

- `eval/orchestrator/project_artifacts.py`: allowlist discovery, classification, ids, media/representation metadata, and canonical inventory serialization.
- `eval/orchestrator/project_graph.py`: `GraphData` validation, deterministic normalization, canonical bytes, metadata, and capture errors.
- `eval/orchestrator/trial.py`: capture the final project graph beside `trial.yaml` and persist capture state without changing the eval terminal.
- `eval/orchestrator/store.py`: schema-v2 staging, complete-tree fingerprint, immutable publication, and manifest integration.
- `eval/orchestrator/files.py`: injectable filesystem operations required for safe walking, staging, and publication.
- `eval/read_api/project_graph.py`: manifest-backed historical graph lookup and digest verification.
- `eval/read_api/artifacts.py`: manifest-backed inventory lookup, safe preview parsing, digest verification, and streamed content.
- `eval/read_api/source.py`: storage-neutral source methods for snapshot, inventory, detail, and content.
- `eval/read_api/app.py`: GET route mapping and safe HTTP errors only.
- `eval/read_api/projection.py`: lightweight per-Trial artifact summary and schema-v1 compatibility.
- `frontend/src/eval/ProjectArtifactsPage.tsx`: grouped hunting/skills index.
- `frontend/src/eval/ProjectArtifactPage.tsx`: route-scoped detail loading and layout.
- `frontend/src/eval/ProjectArtifactRenderers.tsx`: semantic YAML, sanitized Markdown, text/code, and binary rendering.
- `frontend/src/eval/projectArtifacts.ts`: grouping and display-only helpers; no fetching or React state.
- `frontend/src/pages/ProjectEvalsPage.tsx`: completed Trials for one project.
- `frontend/src/pages/ProjectTrialPage.tsx`: unified historical workspace shell and links to eval details/artifacts.
- `frontend/src/graph/GraphView.tsx`: reusable graph loading/empty/error presentation over supplied `GraphData`.
- `frontend/src/eval/TrialProjectGraph.tsx`: route-scoped historical graph loader using the shared graph view.
- `eval/docker-compose.dashboard.real.yml`: co-located real read API and frontend with read-only store bind.

### Task 1: Allowlisted project-artifact catalog

**Implementation state:** Complete in `30799ff9` plus compatibility fix
`021d884d`; independently verified with 8 focused tests passing.

**Files:**
- Create: `eval/orchestrator/project_artifacts.py`
- Create: `tests/eval/test_orchestrator_project_artifacts.py`
- Modify: `eval/orchestrator/files.py`

**Interfaces:**
- Consumes: `FileStore`, `<data_root>/<project_id>` and the exact allowlist from the spec.
- Produces: `ProjectArtifact` dataclass; `collect_project_artifacts(data_root: str | Path, project_id: str, *, files: FileStore) -> tuple[ProjectArtifact, ...]`; `artifact_manifest(entries: Sequence[ProjectArtifact], *, project_id: str, captured_at: str, snapshot_sha256: str) -> dict`.
- `ProjectArtifact` exposes `artifact_id`, `category`, `kind`, `relative_path`, `media_type`, `size_bytes`, `sha256`, `representation`, and the internal `source_path`; `as_manifest_entry()` omits `source_path`.

- [x] **Step 1: Write catalog tests that fail before the module exists**

Add tests named `test_collects_every_hunting_and_skill_family`, `test_excludes_neighboring_project_files`, and `test_missing_optional_directories_are_empty`. Assert deterministic POSIX-relative ordering, exact `kind` classification, SHA-256 content digest, and `artifact_id == sha256(relative_path.encode()).hexdigest()`.

- [x] **Step 2: Run the focused tests and confirm the import failure**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py -q`

Expected: FAIL because `orchestrator.project_artifacts` or its interfaces do not exist.

- [x] **Step 3: Implement the minimal catalog and filesystem seam**

Add `FileStore.walk_regular_files(path: str | Path) -> list[Path]`, `FileStore.is_symlink(path) -> bool`, and `FileStore.file_size(path) -> int`. Classify only the spec patterns; skill support directories recurse, hunting patterns do not. Use explicit extension/media mappings before `application/octet-stream`; representation is `yaml`, `markdown`, `text`, or `binary`.

- [x] **Step 4: Add unsafe-input tests**

Add `test_rejects_symlink_inside_allowlisted_tree`, `test_rejects_unsafe_project_and_dynamic_segments`, and `test_rejects_special_or_escaped_files`. Assert a coded project-artifact exception without exposing the absolute source path in `str(exc)`.

- [x] **Step 5: Run the catalog suite**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py -q`

Expected: all tests PASS.

- [x] **Step 6: Commit the catalog**

```bash
git add eval/orchestrator/project_artifacts.py eval/orchestrator/files.py tests/eval/test_orchestrator_project_artifacts.py
git commit -m "feat(eval): catalog project artifacts for trial snapshots"
```

- [x] **Step 7: Add the failing real-key compatibility regression**

Add `test_accepts_domain_punctuation_in_dynamic_segments`. Create allowlisted
files below dynamic directories containing `fault:http:request`,
`fault::auth`, `spec:variant`, and `skill:name`; assert collection succeeds and
keeps exact POSIX paths. Extend the unsafe-segment test to reject `.`, `..`,
slash, backslash, NUL, and a control character.

- [x] **Step 8: Run the new regression and observe the current rejection**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py -q`

Expected: FAIL only for valid punctuation rejected by the current segment
validator.

- [x] **Step 9: Relax only the dynamic-segment validator**

Replace the restrictive character allowlist with a path-safety predicate that
accepts domain punctuation but rejects the exact unsafe values from Step 7.
Keep project-id validation, containment, symlink/special-file behavior,
classification, and all public interfaces unchanged.

- [x] **Step 10: Run the complete catalog suite**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py -q`

Expected: all tests PASS.

- [x] **Step 11: Commit the compatibility fix**

```bash
git add eval/orchestrator/project_artifacts.py tests/eval/test_orchestrator_project_artifacts.py
git commit -m "fix(eval): accept path-safe artifact domain keys"
```

```text
[WORKER TASK]
File to modify: eval/orchestrator/project_artifacts.py; tests/eval/test_orchestrator_project_artifacts.py
Goal: Close the Task 1 compatibility gap so real domain keys containing colons are cataloged safely.
Exact Changes & Constraints: Preserve every delivered interface and classification; accept path-safe punctuation including `:` and repeated `::`; continue rejecting `.`, `..`, slash, backslash, NUL, control characters, symlinks, special files, and containment escapes; keep exception messages path-free; do not modify store publication.
Tests to write: `test_accepts_domain_punctuation_in_dynamic_segments` plus exact unsafe-character cases added to `test_rejects_unsafe_project_and_dynamic_segments`; run the full Task 1 suite.
```

### Task 2: Final L0/L1 graph capture

**Files:**
- Create: `eval/orchestrator/project_graph.py`
- Create: `tests/eval/test_orchestrator_project_graph.py`
- Modify: `eval/orchestrator/trial.py`
- Modify: `tests/eval/test_orchestrator_trial.py`
- Modify if affected: `tests/eval/test_orchestrator_seeded.py`

**Interfaces:**
- Consumes: the existing `api.project_graph(project_id)` call, `ApiRunner`, and `FileStore.write_bytes_atomic(...)`.
- Produces: `PROJECT_GRAPH_FILENAME = "project-graph.json"`; `ProjectGraphCapture` with `status`, `captured_at`, `sha256`, `node_count`, `link_count`, and `failure`; `normalize_project_graph(payload: Mapping, *, project_id: str) -> dict`; `capture_project_graph(payload: Mapping, *, project_id: str, captured_at: str, destination: Path, files: FileStore) -> ProjectGraphCapture`.
- Extends `TrialRecord` with additive `project_graph: dict | None = None`; available records serialize capture metadata, unavailable records serialize a stable failure and no digest.

- [ ] **Step 1: Write failing pure graph-contract tests**

Add `test_normalizes_graph_order_and_canonical_digest`,
`test_rejects_graph_for_another_project`, and
`test_rejects_malformed_nodes_and_links`. Assert nodes sort by `id`, links by
`(source, target, type)`, nested mapping keys serialize canonically, exact
`project_id` is required, and errors expose no response content or host path.

- [ ] **Step 2: Run the graph tests and confirm the missing module**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_graph.py -q`

Expected: FAIL because `orchestrator.project_graph` does not exist.

- [ ] **Step 3: Implement deterministic validation and capture**

Validate the existing `GraphData` fields without adding graph semantics: node
`id`, `name`, and `type` plus link endpoints/types are strings, `properties` is
a mapping, and extra fields already returned by the API remain intact. Serialize UTF-8 JSON
with sorted keys and stable separators, end with one newline, hash those exact
bytes, then write atomically.

- [ ] **Step 4: Add failing Trial-finalization tests**

Add `test_finish_captures_project_graph_before_writing_record` and
`test_graph_capture_failure_preserves_terminal_and_records_unavailable`.
Assert the graph API is called once after phase execution, the file sits beside
`trial.yaml`, metadata and bytes agree, and transport/validation failure leaves
the original terminal unchanged with no graph file.

- [ ] **Step 5: Integrate capture into `Trial._finish`**

For a finalized Trial with a non-empty project id, capture before writing
`trial.yaml`. Catch ordinary API/validation/I/O exceptions at this auxiliary
boundary, store the path-free `project_graph_unavailable` or
`project_graph_invalid` failure, and continue writing the Trial record. Never
retry or defer capture to materialization.

- [ ] **Step 6: Run graph and Trial tests**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_graph.py tests/eval/test_orchestrator_trial.py tests/eval/test_orchestrator_seeded.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit graph capture**

```bash
git add eval/orchestrator/project_graph.py eval/orchestrator/trial.py tests/eval/test_orchestrator_project_graph.py tests/eval/test_orchestrator_trial.py tests/eval/test_orchestrator_seeded.py
git commit -m "feat(eval): capture final project graph per trial"
```

```text
[WORKER TASK]
File to modify: eval/orchestrator/project_graph.py; eval/orchestrator/trial.py; tests/eval/test_orchestrator_project_graph.py; tests/eval/test_orchestrator_trial.py; tests/eval/test_orchestrator_seeded.py only if its existing call assertions require the final read
Goal: Capture one deterministic historical L0/L1 graph before a Trial instance can be torn down.
Exact Changes & Constraints: Implement the Task 2 interfaces; preserve the existing GraphData payload shape; normalize ordering and canonical JSON bytes; write project-graph.json atomically beside trial.yaml; persist additive capture metadata; capture failure must not change the Trial terminal or raise from _finish; materialization must not call the live API.
Tests to write: The five named normalization, validation, finalization, and failure-isolation tests; run all three focused suites.
```

### Task 3: Schema-v2 immutable Trial publication

**Files:**
- Modify: `eval/orchestrator/store.py`
- Modify: `eval/orchestrator/files.py`
- Modify: `eval/read_api/projection.py`
- Modify: `tests/eval/test_orchestrator_store.py`
- Modify: `tests/eval/test_orchestrator_cli_store.py`

**Interfaces:**
- Consumes: Task 1 `collect_project_artifacts(...)` / `artifact_manifest(...)` and Task 2 `PROJECT_GRAPH_FILENAME` / `ProjectGraphCapture` metadata from `trial.yaml`.
- Produces: unchanged public `store.materialize(...) -> Path`; `STORE_SCHEMA_VERSION = 2`; manifest `project_snapshot`, `project_artifacts`, and `project_graph`; stable `snapshot_sha256`; named `StoreError(failure="snapshot_conflict")`.
- Adds `FileStore.make_staging_dir(root: Path) -> Path`, `FileStore.publish_tree(staging: Path, destination: Path) -> None`, and `FileStore.remove_tree(path: Path) -> None` for testable staging cleanup and atomic first publication.

- [ ] **Step 1: Replace the old mutable-rematerialization expectation with failing immutable tests**

Add `test_materialize_publishes_schema_v2_graph_and_artifacts`,
`test_auxiliary_failure_publishes_core_with_project_snapshot_unavailable`,
`test_equal_rematerialization_preserves_original_timestamps`,
`test_changed_rematerialization_refuses_snapshot_conflict`, and
`test_core_failure_leaves_no_visible_trial_or_staging_tree`. Update the
existing test that expects edited source bytes to overwrite a published Trial.

- [ ] **Step 2: Run focused store tests and observe the schema/idempotence failures**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py -q`

Expected: FAIL on schema version, missing graph/inventory metadata, auxiliary
failure isolation, and current overwrite-on-rematerialize behavior.

- [ ] **Step 3: Implement staged complete-tree publication**

Build under `<store>/_staging/<unique-id>`, union evidence-chain sources with
Task 1 candidates by normalized relative path, and validate the Task 2 graph
bytes against its recorded digest. Stage verdicts and optional diagnoses in all
cases. Stage graph plus artifact union only when both validate; otherwise emit
all three project-snapshot sections as unavailable with one path-free failure.
Extend `projection.SKIP_DIRNAMES` with `_staging`. Compute `snapshot_sha256`
from sorted non-manifest file digests plus canonical manifest data excluding
`copied_at`, `captured_at`, and `snapshot_sha256`.

- [ ] **Step 4: Implement immutable replay behavior**

When destination exists, load its schema-v2 fingerprint: equal fingerprint
returns the existing path without rewriting; different or missing fingerprint
raises `snapshot_conflict`. For a new destination, publish staging only after
core self-containment and, when available, graph/inventory verification pass;
always clean staging on exceptions.

- [ ] **Step 5: Add deduplication and safety regression tests**

Add `test_evidence_and_project_snapshot_copy_the_same_path_once`,
`test_project_symlink_publishes_no_partial_auxiliary_snapshot`,
`test_graph_digest_mismatch_publishes_no_partial_auxiliary_snapshot`, and
`test_cli_dry_run_names_schema_v2_destination_without_writing`. Assert the
core bundle stays readable, neither graph nor artifact inventory is exposed,
and `_staging` is never projected as a Target.

- [ ] **Step 6: Run store, CLI, and projection tests**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py tests/eval/test_read_api_projection.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit immutable publication**

```bash
git add eval/orchestrator/store.py eval/orchestrator/files.py eval/read_api/projection.py tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py tests/eval/test_read_api_projection.py
git commit -m "feat(eval): materialize immutable project snapshots"
```

```text
[WORKER TASK]
File to modify: eval/orchestrator/store.py; eval/orchestrator/files.py; eval/read_api/projection.py; tests/eval/test_orchestrator_store.py; tests/eval/test_orchestrator_cli_store.py
Goal: Publish immutable schema-v2 Trial trees whose historical graph and artifact inventory are atomically available or unavailable.
Exact Changes & Constraints: Use Task 1 and Task 2 interfaces; retain store.materialize signature; stage below _staging; always preserve a valid core eval bundle when only the auxiliary snapshot fails; never expose a partial graph/inventory; fingerprint the normalized Trial payload; equal replay preserves timestamps; changed replay is snapshot_conflict; never project staging.
Tests to write: Every named Task 3 publication, failure-isolation, digest, deduplication, replay, CLI, and staging case plus the updated mutable-rematerialization test.
```

### Task 4: Lightweight projection and reproducible demo data

**Files:**
- Modify: `eval/read_api/projection.py`
- Modify: `eval/read_api/demo_data.py`
- Modify: `tests/eval/test_read_api_projection.py`
- Modify: `tests/eval/test_read_api_demo_data.py`
- Modify: `frontend/src/eval/types.ts`

**Interfaces:**
- Consumes: schema-v2 `run-manifest.yaml` from Task 3.
- Produces: every projected `EvalTrial` retains `project_id` and carries `artifact_summary: {status, hunting, skills}` plus `project_graph_summary: {status, nodes, links, captured_at}`; demo Trials contain a deterministic historical graph and safe synthetic hunting/skill artifacts.

- [ ] **Step 1: Add failing schema compatibility tests**

Add `test_schema_v2_projects_lightweight_project_snapshot_summaries` and
`test_schema_v1_project_snapshot_is_unavailable_not_degraded`. Assert
`project_id`, counts, statuses, and graph capture time are present while
`/snapshot` contains no nodes, links, `relative_path`, artifact body, or
inventory entries.

- [ ] **Step 2: Run projection tests and confirm the missing field**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_projection.py -q`

Expected: FAIL because project graph/artifact summaries are absent.

- [ ] **Step 3: Implement summary projection and TypeScript wire type**

Add `ProjectArtifactSummary` and `ProjectGraphSummary` in
`frontend/src/eval/types.ts`, and require both summaries plus `project_id` on
`EvalTrial`. Treat malformed or non-atomic schema-v2 project sections as
unavailable without changing Trial `availability` or `reason`.

- [ ] **Step 4: Extend the synthetic corpus through production inventory helpers**

For at least one complete demo Trial, create a normalized synthetic graph plus
a hunt config, test spec, pod export/log/variant, `SKILL.md`, Markdown
reference, script, and binary asset. Generate graph metadata through Task 2
helpers and inventory through Task 1 helpers; do not hand-author ids or
digests. Keep the Compose demo overlay unchanged.

- [ ] **Step 5: Pin demo determinism and privacy**

Add assertions that two generations are byte-equivalent, graph/artifact counts
are stable, no graph or binary body enters `/snapshot`, and the intentionally
degraded demo Trial stays degraded only for its existing reason.

- [ ] **Step 6: Run projection and demo tests**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_projection.py tests/eval/test_read_api_demo_data.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit projection compatibility**

```bash
git add eval/read_api/projection.py eval/read_api/demo_data.py tests/eval/test_read_api_projection.py tests/eval/test_read_api_demo_data.py frontend/src/eval/types.ts
git commit -m "feat(eval): project snapshot summaries into dashboard"
```

```text
[WORKER TASK]
File to modify: eval/read_api/projection.py; eval/read_api/demo_data.py; tests/eval/test_read_api_projection.py; tests/eval/test_read_api_demo_data.py; frontend/src/eval/types.ts
Goal: Add lightweight historical graph/artifact summaries and a deterministic demo corpus for the unified project UI.
Exact Changes & Constraints: Preserve project_id; schema v1 reports both project surfaces unavailable without degrading the Trial; schema v2 reports only counts/status/captured_at; no nodes, links, inventory paths, or bodies enter /snapshot; generate demo graph and artifact metadata with production helpers.
Tests to write: The named Task 4 schema-v1/v2 and determinism tests plus stable graph/artifact count and body-absence assertions.
```

### Task 5: Manifest-backed historical graph read API

**Files:**
- Create: `eval/read_api/project_graph.py`
- Create: `tests/eval/test_read_api_project_graph.py`
- Modify: `eval/read_api/source.py`
- Modify: `eval/read_api/app.py`
- Modify: `tests/eval/test_read_api_app.py`

**Interfaces:**
- Consumes: Task 3 schema-v2 manifest and immutable `project-graph.json`.
- Produces: `HistoricalProjectGraph` response `{status, captured_at, sha256, graph}`; extend `SnapshotSource` with `get_project_graph(target_id: str, target_run_id: str, trial_id: str) -> dict`; exact route `GET /trials/{target_id}/{target_run_id}/{trial_id}/project-graph`.
- Errors: unknown Trial is path-free 404; unavailable snapshot, malformed manifest, missing graph, or digest mismatch are path-free 409 with stable codes from the spec.

- [ ] **Step 1: Write failing source and route tests**

Add `test_get_project_graph_returns_graphdata_and_capture_metadata`,
`test_project_graph_route_uses_full_trial_identity`, and
`test_project_graph_route_never_calls_or_mentions_live_api`. Assert individual
URL segment decoding cannot escape the configured store.

- [ ] **Step 2: Run focused tests and observe missing interfaces**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_project_graph.py tests/eval/test_read_api_app.py -q`

Expected: FAIL because the source method and route do not exist.

- [ ] **Step 3: Implement manifest-backed graph lookup**

Resolve only the full Trial identity below the configured store, require all
project-snapshot sections to be available, load the fixed filename rather than
client input, verify regular-file containment and SHA-256, validate `GraphData`,
and return the exact wrapper from the spec. Never proxy the agent API.

- [ ] **Step 4: Add integrity and compatibility tests**

Cover schema-v1, schema-v2 unavailable, missing file, malformed JSON,
project-id mismatch, digest mismatch, symlink replacement, path-like Trial
ids, and absolute-path absence from every error.

- [ ] **Step 5: Run all graph read-API tests**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_project_graph.py tests/eval/test_read_api_source.py tests/eval/test_read_api_app.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit historical graph API**

```bash
git add eval/read_api/project_graph.py eval/read_api/source.py eval/read_api/app.py tests/eval/test_read_api_project_graph.py tests/eval/test_read_api_app.py
git commit -m "feat(eval): serve historical project graphs"
```

```text
[WORKER TASK]
File to modify: eval/read_api/project_graph.py; eval/read_api/source.py; eval/read_api/app.py; tests/eval/test_read_api_project_graph.py; tests/eval/test_read_api_app.py
Goal: Serve the immutable L0/L1 graph captured for one fully identified Trial.
Exact Changes & Constraints: Add the Task 5 source method and GET route; read only project-graph.json selected by the manifest/full Trial tuple; verify containment, regular-file status, GraphData shape, project id, and digest; never query the live agent API; keep all errors path-free.
Tests to write: Every named happy-path, identity, compatibility, integrity, symlink, traversal, and no-live-proxy case in Task 5.
```

### Task 6: Manifest-backed artifact read API

**Files:**
- Create: `eval/read_api/artifacts.py`
- Create: `tests/eval/test_read_api_artifacts.py`
- Modify: `eval/read_api/source.py`
- Modify: `eval/read_api/app.py`
- Modify: `tests/eval/test_read_api_app.py`

**Interfaces:**
- Consumes: schema-v2 manifest inventory and immutable files from Task 3.
- Produces: extend the existing `SnapshotSource` protocol with `list_artifacts(target_id, target_run_id, trial_id) -> dict`, `get_artifact(..., artifact_id) -> dict`, and `stream_artifact(..., artifact_id) -> ArtifactDownload`; `ArtifactDownload` provides `filename`, `media_type`, `size_bytes`, and a chunk iterator.
- Inventory response is `{status, project_id, groups}`. Each recursive group is `{key, label, category, entries, children}`; hunting keys are `hunt-configs/{side}`, `test-specs/{fault_key}`, and `pod-executions/{spec_id}`, while skill keys are `skills/{skill_name}/{procedure|references|scripts|assets}`. Groups and entries sort lexically by key/path.
- HTTP routes are exactly the three routes in the spec. Detail response is `{entry, preview: {text, parsed, truncated, parse_error}, content_url}`. `text` carries the raw preview for YAML/Markdown/text, `parsed` is non-null only for valid bounded YAML, and binary has both fields null.

- [ ] **Step 1: Write failing route and source-contract tests**

Test grouped inventory, YAML detail, text/Markdown detail, binary metadata-only detail, raw streaming, URL encoding, read-only methods, and source factory injection. Verify no absolute path appears in JSON or error text.

- [ ] **Step 2: Run API tests and confirm the new routes are 404**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_artifacts.py tests/eval/test_read_api_app.py -q`

Expected: FAIL because the routes and source methods are absent.

- [ ] **Step 3: Implement safe inventory resolution**

Resolve Trial ids as safe single segments, load only its manifest, locate artifacts only by exact `artifact_id`, revalidate allowlist/path containment/regular-file status, and compare SHA-256 before every detail or content response. Map missing Trial/artifact to 404 and unavailable/integrity failures to path-free 409 responses.

Require the combined project snapshot to be available. Use response codes
`project_snapshot_unavailable`, `project_artifacts_unavailable`,
`artifact_missing`, `artifact_digest_mismatch`, and `artifact_unsafe`. An id
absent from inventory is a plain 404 `artifact_not_found`; it must never be
interpreted as a path.

- [ ] **Step 4: Implement bounded representations and streaming**

Decode text with strict UTF-8; invalid UTF-8 returns `parse_error` and leaves download available. Read at most 512 KiB plus one byte for text/Markdown truncation. Parse YAML with `yaml.safe_load` only when size is at most 2 MiB; larger YAML is download-only. Stream content in bounded chunks and set attachment disposition for binary/active types.

- [ ] **Step 5: Add boundary and adversarial tests**

Add exact 512 KiB and 512 KiB+1 cases, exact 2 MiB and 2 MiB+1 YAML cases, malformed YAML, invalid UTF-8, digest mismatch, symlink replacement after materialization, path-like artifact id, and unknown URL-encoded ids.

- [ ] **Step 6: Run all read-API tests**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_app.py tests/eval/test_read_api_source.py tests/eval/test_read_api_projection.py tests/eval/test_read_api_artifacts.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit the read API**

```bash
git add eval/read_api/artifacts.py eval/read_api/source.py eval/read_api/app.py tests/eval/test_read_api_artifacts.py tests/eval/test_read_api_app.py
git commit -m "feat(eval): serve trial project artifacts on demand"
```

```text
[WORKER TASK]
File to modify: eval/read_api/artifacts.py; eval/read_api/source.py; eval/read_api/app.py; tests/eval/test_read_api_artifacts.py; tests/eval/test_read_api_app.py
Goal: Expose GET-only inventory, detail, and streamed raw-content endpoints backed solely by an available schema-v2 project snapshot and manifest ids.
Exact Changes & Constraints: Implement the Task 6 protocol and response shape; no client path input; require atomic project-snapshot availability; verify containment/type/digest each time; enforce 512 KiB and 2 MiB limits; keep errors path-free; preserve source injection and disabled docs.
Tests to write: Route/contract tests plus every named boundary and adversarial case in Task 6.
```

### Task 7: Unified project hub and completed-Trial navigation

**Files:**
- Create: `frontend/src/projectPaths.ts`
- Create: `frontend/src/pages/ProjectNav.tsx`
- Create: `frontend/src/pages/ProjectEvalLayout.tsx`
- Create: `frontend/src/pages/ProjectEvalsPage.tsx`
- Create: `frontend/src/pages/ProjectTrialPage.tsx`
- Create: `frontend/src/pages/ProjectEvalsPage.test.tsx`
- Modify: `frontend/src/pages/GraphPage.tsx`
- Modify: `frontend/src/pages/RunsPage.tsx`
- Modify: `frontend/src/eval/TrialPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/eval/eval.css`

**Interfaces:**
- Consumes: Task 4 `EvalTrial.project_id`, artifact/graph summaries, and existing `EvalDataProvider`.
- Produces: URL-encoding `projectPaths.live`, `projectPaths.runs`, `projectPaths.evals`, `projectPaths.trial`, `projectPaths.artifacts`, and `projectPaths.artifact`; routes `/p/:projectId`, `/p/:projectId/runs`, `/p/:projectId/evals`, and `/p/:projectId/evals/:targetId/:targetRunId/:trialId`.
- `ProjectEvalLayout` owns one `EvalDataProvider` for its child routes; `ProjectEvalsPage` filters by exact `project_id`; `ProjectTrialPage` rejects a route/project mismatch instead of displaying another project's Trial.

- [ ] **Step 1: Write failing route-helper and project-filter tests**

Assert every path segment is URL-encoded, one project's list excludes all
other Trials, ordering uses newest `project_graph_summary.captured_at` then
`copied_at` with stable full-identity tie-breakers, and duplicate `trial_id`
values under different target tuples remain distinct links.

- [ ] **Step 2: Run the focused tests and observe missing hub routes**

Run: `cd frontend && npm test -- src/pages/ProjectEvalsPage.test.tsx src/eval/navigation.test.tsx`

Expected: FAIL because project eval paths/pages do not exist.

- [ ] **Step 3: Implement shared project navigation and eval layout**

Add accessible Graph, Runs, and Eval Trials links to the existing live pages.
Mount one `EvalDataProvider` around the `/p/:projectId/evals` subtree with the
same loading/error behavior as the eval shell, without adding project data to
the eval snapshot or issuing duplicate snapshot requests per child route.

- [ ] **Step 4: Implement project Trial list and workspace shell**

Render only completed materialized Trials matching the route project. The
workspace shows identity, eval outcome, project snapshot availability, links
to the existing `/eval/...` Trial, and reserved Graph / Hunting / Skills
sections for Tasks 8-10. A mismatched or unknown tuple gets a not-found state.

- [ ] **Step 5: Add reciprocal navigation from the eval Trial page**

When `project_id` exists, link to the full project Trial route. Preserve every
existing `/eval/...` route and breadcrumb; do not redirect old deep links.

- [ ] **Step 6: Run hub/navigation tests and the frontend build**

Run: `cd frontend && npm test -- src/pages/ProjectEvalsPage.test.tsx src/eval/navigation.test.tsx src/eval/EvalPage.test.tsx && npm run build`

Expected: all tests PASS and the build exits 0.

- [ ] **Step 7: Commit the unified hub**

```bash
git add frontend/src/projectPaths.ts frontend/src/pages/ProjectNav.tsx frontend/src/pages/ProjectEvalLayout.tsx frontend/src/pages/ProjectEvalsPage.tsx frontend/src/pages/ProjectTrialPage.tsx frontend/src/pages/ProjectEvalsPage.test.tsx frontend/src/pages/GraphPage.tsx frontend/src/pages/RunsPage.tsx frontend/src/eval/TrialPage.tsx frontend/src/App.tsx frontend/src/eval/eval.css
git commit -m "feat(frontend): unify projects with eval trials"
```

```text
[WORKER TASK]
File to modify: frontend/src/projectPaths.ts; frontend/src/pages/ProjectNav.tsx; frontend/src/pages/ProjectEvalLayout.tsx; frontend/src/pages/ProjectEvalsPage.tsx; frontend/src/pages/ProjectTrialPage.tsx; frontend/src/pages/ProjectEvalsPage.test.tsx; frontend/src/pages/GraphPage.tsx; frontend/src/pages/RunsPage.tsx; frontend/src/eval/TrialPage.tsx; frontend/src/App.tsx; frontend/src/eval/eval.css
Goal: Make the existing project page the common entry point for live graph, runs, and completed eval Trials.
Exact Changes & Constraints: Implement Task 7 paths/routes; use the full Trial tuple; filter by exact project_id; keep one EvalDataProvider for the project-eval subtree; reject project/Trial mismatches; preserve all /eval routes and add reciprocal links; do not fetch graph/artifact bodies yet.
Tests to write: URL encoding, project isolation, duplicate trial-id identity, ordering, not-found/mismatch, provider loading/error, reciprocal navigation, and direct refresh cases from Task 7.
```

### Task 8: Shared live and historical L0/L1 graph presentation

**Files:**
- Create: `frontend/src/graph/GraphView.tsx`
- Create: `frontend/src/eval/TrialProjectGraph.tsx`
- Create: `frontend/src/eval/TrialProjectGraph.test.tsx`
- Modify: `frontend/src/pages/GraphPage.tsx`
- Modify: `frontend/src/pages/ProjectTrialPage.tsx`
- Modify: `frontend/src/eval/types.ts`
- Modify: `frontend/src/eval/client.ts`
- Modify: `frontend/src/eval/client.test.ts`
- Modify: `frontend/src/eval/eval.css`

**Interfaces:**
- Consumes: Task 5 `HistoricalProjectGraph` response and existing `GraphCanvas` / `LayerVisibility`.
- Produces: `getTrialProjectGraph(targetId, targetRunId, trialId, signal?) -> Promise<HistoricalProjectGraph>`; reusable `GraphView({data, loading, error, label, capturedAt?})`; `TrialProjectGraph` route-scoped loader.

- [ ] **Step 1: Add failing historical graph client tests**

Assert the full Trial tuple is individually URL-encoded, the eval base URL is
independent of `VITE_AGENT_BASE_URL`, non-2xx rejects with the stable code, and
an optional `AbortSignal` is forwarded.

- [ ] **Step 2: Extract the shared graph presentation under characterization tests**

Move layer toggles and loading/error/empty/both-off presentation from
`GraphPage` into `GraphView`. Existing live graph tests must keep passing
without changing `useGraphData` or the agent endpoint.

- [ ] **Step 3: Add failing historical workspace tests**

Cover snapshot label/capture time, L0/L1 toggle combinations, empty graph,
unavailable snapshot, API error, direct refresh, abort on route change, and a
late response ignored after navigation.

- [ ] **Step 4: Implement `TrialProjectGraph` and workspace integration**

Fetch only through the eval client and pass `response.graph` to `GraphView`.
Show `Trial snapshot` plus `captured_at`; provide an explicit link to the live
project. Never call `getGraph`, `useGraphData`, or fall back to live data on any
historical error.

- [ ] **Step 5: Pin temporal separation with different graphs**

In one test, give the same `project_id` a live graph node `live-only` and a
historical response node `trial-only`; assert the Trial workspace renders only
`trial-only`, including after the live request resolves.

- [ ] **Step 6: Run graph/client/workspace tests and build**

Run: `cd frontend && npm test -- src/graph src/eval/client.test.ts src/eval/TrialProjectGraph.test.tsx src/pages/ProjectEvalsPage.test.tsx && npm run build`

Expected: all tests PASS and the build exits 0.

- [ ] **Step 7: Commit historical graph rendering**

```bash
git add frontend/src/graph/GraphView.tsx frontend/src/eval/TrialProjectGraph.tsx frontend/src/eval/TrialProjectGraph.test.tsx frontend/src/pages/GraphPage.tsx frontend/src/pages/ProjectTrialPage.tsx frontend/src/eval/types.ts frontend/src/eval/client.ts frontend/src/eval/client.test.ts frontend/src/eval/eval.css
git commit -m "feat(frontend): render historical trial graphs"
```

```text
[WORKER TASK]
File to modify: frontend/src/graph/GraphView.tsx; frontend/src/eval/TrialProjectGraph.tsx; frontend/src/eval/TrialProjectGraph.test.tsx; frontend/src/pages/GraphPage.tsx; frontend/src/pages/ProjectTrialPage.tsx; frontend/src/eval/types.ts; frontend/src/eval/client.ts; frontend/src/eval/client.test.ts; frontend/src/eval/eval.css
Goal: Reuse the existing L0/L1 graph UI for immutable Trial snapshots while keeping live and historical sources separate.
Exact Changes & Constraints: Extract GraphView without changing live behavior; add the Task 8 eval client; historical graph uses only the eval endpoint/full Trial tuple, displays Trial snapshot/captured_at, aborts stale requests, and never falls back to the agent graph.
Tests to write: Client encoding/base/abort tests; shared graph characterization; snapshot labels/toggles/empty/unavailable/error/direct-refresh/stale-response; and the live-only versus trial-only separation regression.
```

### Task 9: Frontend contract, navigation, and grouped artifact index

**Files:**
- Create: `frontend/src/eval/projectArtifacts.ts`
- Create: `frontend/src/eval/ProjectArtifactsPage.tsx`
- Create: `frontend/src/eval/ProjectArtifactsPage.test.tsx`
- Modify: `frontend/src/eval/types.ts`
- Modify: `frontend/src/eval/client.ts`
- Modify: `frontend/src/eval/client.test.ts`
- Modify: `frontend/src/eval/EvalBreadcrumbs.tsx`
- Modify: `frontend/src/eval/TrialPage.tsx`
- Modify: `frontend/src/pages/ProjectTrialPage.tsx`
- Modify: `frontend/src/projectPaths.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/eval/eval.css`
- Modify: snapshot fixtures in `frontend/src/eval/*.test.tsx`

**Interfaces:**
- Consumes: Task 4 `artifact_summary`, Task 6 inventory response, and Task 7 project workspace/paths.
- Produces: `ProjectArtifactEntry`, `ProjectArtifactGroup`, `ProjectArtifactInventory`, and `ProjectArtifactDetail` wire types; `getProjectArtifacts(...)`, `getProjectArtifact(...)`, and `projectArtifactContentUrl(...)`; routes from the spec; pure `groupLabel(...)` and ordering helpers.

- [ ] **Step 1: Add failing client URL and type-contract tests**

Assert all ids are individually URL-encoded, base URL remains independent of `VITE_AGENT_BASE_URL`, non-2xx responses reject, and content URL construction performs no fetch.

- [ ] **Step 2: Implement client types and calls**

Accept an optional `AbortSignal` on list/detail fetches. Do not add project artifacts to `EvalDataProvider`; each new page owns route-scoped loading/error state so `/snapshot` remains one shared request.

- [ ] **Step 3: Add failing navigation/index tests**

Cover summary links from both eval and project Trial pages, the historical
unavailable notice with no link, empty available inventory, grouped
Hunting/Skills headings, both compatible route families, direct refresh,
unknown/mismatched Trial, API error, and an unresolved request aborted on route
change.

- [ ] **Step 4: Implement routes, paths, Trial entry, and index page**

Add `evalPaths.projectArtifacts(...)`, `evalPaths.projectArtifact(...)`, and
the Task 7 project equivalents. Register compatibility routes under `/eval`
and primary routes under the full project Trial path. Render groups in server
order with stable keys and artifact links; keep all identifiers visible as
text. Use `AbortController` cleanup for every route-scoped fetch.

- [ ] **Step 5: Add accessible index styling**

Extend existing eval CSS classes instead of introducing a second design system. Groups must be navigable by headings and lists, status must not rely on color, and the layout must stack at the existing mobile breakpoint.

- [ ] **Step 6: Run frontend client and index tests**

Run: `cd frontend && npm test -- src/eval/client.test.ts src/eval/ProjectArtifactsPage.test.tsx src/eval/EvalPage.test.tsx src/eval/navigation.test.tsx`

Expected: all tests PASS.

- [ ] **Step 7: Commit frontend navigation**

```bash
git add frontend/src/App.tsx frontend/src/projectPaths.ts frontend/src/pages/ProjectTrialPage.tsx frontend/src/eval/types.ts frontend/src/eval/client.ts frontend/src/eval/client.test.ts frontend/src/eval/EvalBreadcrumbs.tsx frontend/src/eval/TrialPage.tsx frontend/src/eval/projectArtifacts.ts frontend/src/eval/ProjectArtifactsPage.tsx frontend/src/eval/ProjectArtifactsPage.test.tsx frontend/src/eval/eval.css frontend/src/eval/*.test.tsx
git commit -m "feat(frontend): navigate trial project artifacts"
```

```text
[WORKER TASK]
File to modify: frontend/src/eval/types.ts; frontend/src/eval/client.ts; frontend/src/eval/EvalBreadcrumbs.tsx; frontend/src/eval/TrialPage.tsx; frontend/src/pages/ProjectTrialPage.tsx; frontend/src/projectPaths.ts; frontend/src/App.tsx; frontend/src/eval/eval.css; frontend/src/eval/projectArtifacts.ts; frontend/src/eval/ProjectArtifactsPage.tsx; related eval tests
Goal: Add on-demand artifact inventory loading and a grouped Hunting/Skills index reachable from both the project workspace and existing eval routes.
Exact Changes & Constraints: Match Task 6 wire types; URL-encode every id; keep artifact requests out of EvalDataProvider; use the full Trial tuple; abort stale requests; unavailable snapshots show no broken link; preserve /eval compatibility and make the project workspace the primary combined route.
Tests to write: Every named Task 9 client, dual-route, project-isolation, index, direct-refresh, unavailable, and stale-request case.
```

### Task 10: Semantic artifact detail renderers

**Files:**
- Create: `frontend/src/eval/ProjectArtifactPage.tsx`
- Create: `frontend/src/eval/ProjectArtifactRenderers.tsx`
- Create: `frontend/src/eval/ProjectArtifactPage.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/eval/eval.css`

**Interfaces:**
- Consumes: Task 6 detail response and Task 9 client/types/routes.
- Produces: route-scoped detail page; `ProjectArtifactRenderer({detail})`; kind-specific YAML cards plus generic tree fallback; sanitized Markdown; highlighted text; binary metadata/download; semantic/raw toggle.

- [ ] **Step 1: Install rendering dependencies and commit lockfile changes only with this task**

Run: `cd frontend && npm install react-markdown rehype-sanitize prism-react-renderer`

Expected: `package.json` and `package-lock.json` contain the three direct dependencies.

- [ ] **Step 2: Write failing renderer tests**

Cover HuntConfig fields (`hunt_id`, `unit_id`, `fault_class`, `status`, `vulnerability_class`), TestImplementationSpec fields (`target_identity`, `testing_pattern`, `verification_symptoms`, `assumptions`), PodExport fields (`verdict`, `terminal_reason`, `iterations`, `clean`), and generic YAML fallback.

- [ ] **Step 3: Add security and fallback tests**

Assert Markdown scripts/event handlers and unsafe links do not render; script/log text is escaped and highlighted; `parse_error` shows raw preview; truncated preview is labeled; binary exposes metadata and download only; raw toggle preserves exact preview text.

- [ ] **Step 4: Implement semantic renderers**

Dispatch by `entry.kind`, not filename. Render only known typed fields in semantic cards and send extra keys to the generic recursive YAML tree. Use `react-markdown` with `rehype-sanitize`; use `prism-react-renderer` for `skill_script`, `experiment_log`, and text fallback; never use `dangerouslySetInnerHTML`.

- [ ] **Step 5: Implement the detail route page**

Fetch by route ids with `AbortController`, show project-aware or eval-compatible
breadcrumbs and immutable metadata, isolate loading/error state, and provide
raw/download actions using Task 9 URL helpers. A late response after navigation
must be ignored.

- [ ] **Step 6: Run renderer tests and production build**

Run: `cd frontend && npm test -- src/eval/ProjectArtifactPage.test.tsx && npm run build`

Expected: tests PASS and TypeScript/Vite build exits 0.

- [ ] **Step 7: Commit semantic rendering**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/App.tsx frontend/src/eval/ProjectArtifactPage.tsx frontend/src/eval/ProjectArtifactRenderers.tsx frontend/src/eval/ProjectArtifactPage.test.tsx frontend/src/eval/eval.css
git commit -m "feat(frontend): render hunting artifacts and project skills"
```

```text
[WORKER TASK]
File to modify: frontend/package.json; frontend/package-lock.json; frontend/src/App.tsx; frontend/src/eval/ProjectArtifactPage.tsx; frontend/src/eval/ProjectArtifactRenderers.tsx; frontend/src/eval/ProjectArtifactPage.test.tsx; frontend/src/eval/eval.css
Goal: Render each project artifact safely with semantic, raw, and download views.
Exact Changes & Constraints: Use the three named dependencies; dispatch YAML cards by artifact kind; sanitize Markdown; highlight escaped text; never inline binary/active content or use dangerouslySetInnerHTML; abort/ignore stale requests; retain generic YAML and raw fallbacks.
Tests to write: Typed renderer, sanitization, escaping, parse-error, truncation, binary, raw-toggle, dual-breadcrumb, and stale-navigation cases named in Task 10.
```

### Task 11: Real-server overlay, cross-layer acceptance, and operator docs

**Files:**
- Create: `eval/docker-compose.dashboard.real.yml`
- Create: `tests/eval/test_real_project_artifacts_flow.py`
- Modify: `tests/eval/test_eval_overlay.py`
- Modify: `README.md`
- Modify: `eval/OPERATOR.md`
- Modify: `eval/read_api/source.py`
- Modify: `tests/eval/test_read_api_source.py`

**Interfaces:**
- Consumes: Tasks 1-10 complete stack.
- Produces: real overlay with `eval-api` and `eval-dashboard` only; read-only `${EVAL_ARTIFACT_STORE_HOST_PATH:-/srv/eval-artifacts}` bind; health fields `store_configured`, `store_readable`, and `materialized_trials`; documented server commands.

- [ ] **Step 1: Add failing Compose render tests**

Extend the staging helper to copy the real overlay. Assert exactly two added services, no `eval-store`, read-only host bind at `/srv/eval-artifacts`, loopback ports, proxy target `http://eval-api:8090`, and no mount of `live/` or the instance data root. Reassert the demo overlay still uses its dedicated named volume.

- [ ] **Step 2: Implement the real overlay**

Reuse the same images/commands/health checks as the demo API/dashboard, but remove generator/dependency wiring. Require or default `EVAL_ARTIFACT_STORE_HOST_PATH` exactly as the spec states; mount source and eval code read-only.

- [ ] **Step 3: Pin health semantics**

Make health `ok` only when the store is configured and readable. Add `materialized_trials` count without treating a readable empty store as degraded. Add tests for unset, nonexistent, unreadable/non-directory, empty, and populated stores.

- [ ] **Step 4: Write the materializer-to-HTTP acceptance test**

In `test_real_project_artifacts_flow.py`, build a realistic temporary project
with one L0/L1 graph, one hunting family, and one skill bundle. Capture the
graph through Task 2 helpers, run production `store.materialize`, create the
real source/app, then assert `/snapshot` summaries, historical graph, inventory
grouping, semantic detail, and streamed bytes agree on project identity and
digests. Add a second fixture whose graph capture fails and assert the core
verdict remains readable while graph and artifacts are both unavailable.

- [ ] **Step 5: Document real and demo startup separately**

Add exact Compose commands, loopback URLs,
`EVAL_ARTIFACT_STORE_HOST_PATH`, expected `/health` fields, project-hub routes,
the distinction between live and `Trial snapshot`, and schema-v1/unavailable
behavior. Do not describe the real overlay as live monitoring.

- [ ] **Step 6: Run backend, Compose, frontend, and build verification**

Run:

```bash
PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py tests/eval/test_orchestrator_project_graph.py tests/eval/test_orchestrator_trial.py tests/eval/test_orchestrator_seeded.py tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py tests/eval/test_read_api_projection.py tests/eval/test_read_api_demo_data.py tests/eval/test_read_api_source.py tests/eval/test_read_api_app.py tests/eval/test_read_api_project_graph.py tests/eval/test_read_api_artifacts.py tests/eval/test_real_project_artifacts_flow.py tests/eval/test_eval_overlay.py -q
cd frontend && npm test && npm run build
```

Expected: all pytest and Vitest tests PASS; frontend build exits 0. Docker-dependent tests may SKIP only when the Docker CLI is absent, using the existing skip marker.

- [ ] **Step 7: Review the final diff against the spec and commit**

Confirm `git diff --check`, no mutation route, no host path in fixture responses, and no unrelated untracked file is staged.

```bash
git add eval/docker-compose.dashboard.real.yml tests/eval/test_real_project_artifacts_flow.py tests/eval/test_eval_overlay.py eval/read_api/source.py tests/eval/test_read_api_source.py README.md eval/OPERATOR.md
git commit -m "feat(eval): deploy the real artifact dashboard"
```

```text
[WORKER TASK]
File to modify: eval/docker-compose.dashboard.real.yml; tests/eval/test_real_project_artifacts_flow.py; tests/eval/test_eval_overlay.py; eval/read_api/source.py; tests/eval/test_read_api_source.py; README.md; eval/OPERATOR.md
Goal: Deploy the unified project/eval dashboard against the real server store and prove graph plus artifact history end to end.
Exact Changes & Constraints: Keep demo and real overlays separate; real overlay has only eval-api/eval-dashboard, read-only store bind, and loopback ports; health distinguishes readable empty stores; document live versus Trial snapshot semantics and full project-hub routes; run the full verification matrix.
Tests to write: Real-overlay render assertions, health-state matrix, available and unavailable project-snapshot acceptance flows, and production capture→materialize→snapshot→graph→inventory→detail→content verification.
```
