# Real Eval Project Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve real completed eval Trials from the eval server and let the frontend inspect each Trial's immutable hunting artifacts and project-authored skill bundles.

**Architecture:** Extend materialization with a schema-v2, allowlisted project snapshot and stable manifest inventory. Keep `/snapshot` lightweight, expose inventory/detail/content through GET-only read-API routes, then add on-demand frontend index and detail routes. Keep the synthetic demo overlay and the real read-only deployment overlay separate.

**Tech Stack:** Python 3, PyYAML, FastAPI, pytest, Docker Compose, React 19, TypeScript, React Router, Vitest/Testing Library, `react-markdown`, `rehype-sanitize`, `prism-react-renderer`.

**Spec:** `docs/superpowers/specs/2026-10-03-real-eval-project-artifacts-design.md`

## Global Constraints

- New materializations use store schema version 2; schema-v1 Trials remain readable and report `project_artifacts_unavailable` without becoming degraded.
- Snapshot only completed materialized Trials. Never read project artifacts from `<store>/<instance_id>/live/`.
- Preserve project-relative paths below `<trial>/<project_id>/`; existing verdict evidence references must continue to resolve.
- Copy only the hunting and skill allowlist in the spec; reject symlinks, special files, unsafe segments, traversal, and resolved paths outside the project root.
- First publication is immutable. Equal `snapshot_sha256` is an idempotent no-op; different content for the same Trial is `snapshot_conflict`.
- The read API remains GET-only and never accepts an arbitrary filesystem path or returns an absolute host path.
- Text and Markdown previews stop at 512 KiB; YAML larger than 2 MiB is download-only; raw content streams instead of being loaded wholly into memory.
- Binary and active content use `Content-Disposition: attachment`; the frontend never renders them inline.
- Keep `eval/docker-compose.dashboard.yml` demo-only. Real deployment uses a separate overlay with `/srv/eval-artifacts` mounted read-only and loopback-only published ports.
- Do not modify or commit the pre-existing untracked files listed by `git status`; stage only files named by the active task.

## Review Focus

- A symlink nested under an otherwise allowlisted skill directory must fail materialization before publication; Task 1 and Task 2 pin this.
- A repeated materialization with identical bytes but a later clock must preserve the original timestamps, while one changed byte must raise `snapshot_conflict`; Task 2 pins this.
- Invalid UTF-8, malformed YAML, 512 KiB text boundaries, and the 2 MiB YAML boundary must not crash or over-read the API; Task 4 pins this.
- URL-encoded identifiers and unknown or path-like artifact ids must resolve only through manifest inventory and return safe 404/409 responses; Task 4 and Task 5 pin this.
- A route change while an artifact request is outstanding must not render stale content into the next Trial; Task 5 and Task 6 pin cancellation and route-scoped state.

---

## File map

- `eval/orchestrator/project_artifacts.py`: allowlist discovery, classification, ids, media/representation metadata, and canonical inventory serialization.
- `eval/orchestrator/store.py`: schema-v2 staging, complete-tree fingerprint, immutable publication, and manifest integration.
- `eval/orchestrator/files.py`: injectable filesystem operations required for safe walking, staging, and publication.
- `eval/read_api/artifacts.py`: manifest-backed inventory lookup, safe preview parsing, digest verification, and streamed content.
- `eval/read_api/source.py`: storage-neutral source methods for snapshot, inventory, detail, and content.
- `eval/read_api/app.py`: GET route mapping and safe HTTP errors only.
- `eval/read_api/projection.py`: lightweight per-Trial artifact summary and schema-v1 compatibility.
- `frontend/src/eval/ProjectArtifactsPage.tsx`: grouped hunting/skills index.
- `frontend/src/eval/ProjectArtifactPage.tsx`: route-scoped detail loading and layout.
- `frontend/src/eval/ProjectArtifactRenderers.tsx`: semantic YAML, sanitized Markdown, text/code, and binary rendering.
- `frontend/src/eval/projectArtifacts.ts`: grouping and display-only helpers; no fetching or React state.
- `eval/docker-compose.dashboard.real.yml`: co-located real read API and frontend with read-only store bind.

### Task 1: Allowlisted project-artifact catalog

**Files:**
- Create: `eval/orchestrator/project_artifacts.py`
- Create: `tests/eval/test_orchestrator_project_artifacts.py`
- Modify: `eval/orchestrator/files.py`

**Interfaces:**
- Consumes: `FileStore`, `<data_root>/<project_id>` and the exact allowlist from the spec.
- Produces: `ProjectArtifact` dataclass; `collect_project_artifacts(data_root: str | Path, project_id: str, *, files: FileStore) -> tuple[ProjectArtifact, ...]`; `artifact_manifest(entries: Sequence[ProjectArtifact], *, project_id: str, captured_at: str, snapshot_sha256: str) -> dict`.
- `ProjectArtifact` exposes `artifact_id`, `category`, `kind`, `relative_path`, `media_type`, `size_bytes`, `sha256`, `representation`, and the internal `source_path`; `as_manifest_entry()` omits `source_path`.

- [ ] **Step 1: Write catalog tests that fail before the module exists**

Add tests named `test_collects_every_hunting_and_skill_family`, `test_excludes_neighboring_project_files`, and `test_missing_optional_directories_are_empty`. Assert deterministic POSIX-relative ordering, exact `kind` classification, SHA-256 content digest, and `artifact_id == sha256(relative_path.encode()).hexdigest()`.

- [ ] **Step 2: Run the focused tests and confirm the import failure**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py -q`

Expected: FAIL because `orchestrator.project_artifacts` or its interfaces do not exist.

- [ ] **Step 3: Implement the minimal catalog and filesystem seam**

Add `FileStore.walk_regular_files(path: str | Path) -> list[Path]`, `FileStore.is_symlink(path) -> bool`, and `FileStore.file_size(path) -> int`. Classify only the spec patterns; skill support directories recurse, hunting patterns do not. Use explicit extension/media mappings before `application/octet-stream`; representation is `yaml`, `markdown`, `text`, or `binary`.

- [ ] **Step 4: Add unsafe-input tests**

Add `test_rejects_symlink_inside_allowlisted_tree`, `test_rejects_unsafe_project_and_dynamic_segments`, and `test_rejects_special_or_escaped_files`. Assert a coded project-artifact exception without exposing the absolute source path in `str(exc)`.

- [ ] **Step 5: Run the catalog suite**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit the catalog**

```bash
git add eval/orchestrator/project_artifacts.py eval/orchestrator/files.py tests/eval/test_orchestrator_project_artifacts.py
git commit -m "feat(eval): catalog project artifacts for trial snapshots"
```

```text
[WORKER TASK]
File to modify: eval/orchestrator/project_artifacts.py; eval/orchestrator/files.py; tests/eval/test_orchestrator_project_artifacts.py
Goal: Build the deterministic, allowlisted catalog used by Trial materialization.
Exact Changes & Constraints: Implement the Task 1 interfaces exactly; preserve the FileStore seam; enumerate only spec-approved paths; reject symlinks/special files/unsafe segments without leaking host paths; do not integrate store publication yet.
Tests to write: The six named Task 1 tests covering all families, exclusions, empty directories, symlinks, unsafe segments, and escaped/special files.
```

### Task 2: Schema-v2 immutable Trial publication

**Files:**
- Modify: `eval/orchestrator/store.py`
- Modify: `eval/orchestrator/files.py`
- Modify: `eval/read_api/projection.py`
- Modify: `tests/eval/test_orchestrator_store.py`
- Modify: `tests/eval/test_orchestrator_cli_store.py`

**Interfaces:**
- Consumes: `collect_project_artifacts(...)` and `artifact_manifest(...)` from Task 1.
- Produces: unchanged public `store.materialize(...) -> Path`; `STORE_SCHEMA_VERSION = 2`; manifest `project_artifacts` and stable `snapshot_sha256`; named `StoreError(failure="snapshot_conflict")`.
- Adds `FileStore.make_staging_dir(root: Path) -> Path`, `FileStore.publish_tree(staging: Path, destination: Path) -> None`, and `FileStore.remove_tree(path: Path) -> None` for testable staging cleanup and atomic first publication.

- [ ] **Step 1: Replace the old mutable-rematerialization expectation with failing immutable tests**

Add `test_materialize_publishes_schema_v2_project_snapshot`, `test_equal_rematerialization_preserves_original_timestamps`, `test_changed_rematerialization_refuses_snapshot_conflict`, and `test_failure_leaves_no_visible_trial_or_staging_tree`. Update the existing test that expects edited source bytes to overwrite a published Trial.

- [ ] **Step 2: Run focused store tests and observe the schema/idempotence failures**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py -q`

Expected: FAIL on schema version, missing project inventory, and the current overwrite-on-rematerialize behavior.

- [ ] **Step 3: Implement staged complete-tree publication**

Build under `<store>/_staging/<unique-id>`, union evidence-chain sources with Task 1 candidates by normalized relative path, then write verdicts, optional diagnoses, and manifest. Extend `projection.SKIP_DIRNAMES` with `_staging`. Verify all files and compute `snapshot_sha256` from sorted non-manifest file digests plus canonical manifest data excluding `copied_at`, `captured_at`, and `snapshot_sha256`.

- [ ] **Step 4: Implement immutable replay behavior**

When destination exists, load its schema-v2 fingerprint: equal fingerprint returns the existing path without rewriting; different or missing fingerprint raises `snapshot_conflict`. For a new destination, publish staging only after `_verify_self_contained` and project-inventory verification pass; always clean staging on exceptions.

- [ ] **Step 5: Add deduplication and safety regression tests**

Add `test_evidence_and_project_snapshot_copy_the_same_path_once`, `test_project_symlink_fails_before_existing_trial_is_touched`, and `test_cli_dry_run_names_schema_v2_destination_without_writing`. Assert `_staging` is never projected as a Target.

- [ ] **Step 6: Run store, CLI, and projection tests**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py tests/eval/test_read_api_projection.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit immutable publication**

```bash
git add eval/orchestrator/store.py eval/orchestrator/files.py eval/read_api/projection.py tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py tests/eval/test_read_api_projection.py
git commit -m "feat(eval): materialize immutable project artifact snapshots"
```

```text
[WORKER TASK]
File to modify: eval/orchestrator/store.py; eval/orchestrator/files.py; eval/read_api/projection.py; tests/eval/test_orchestrator_store.py; tests/eval/test_orchestrator_cli_store.py
Goal: Publish complete schema-v2 Trial trees atomically and make published snapshots immutable.
Exact Changes & Constraints: Use Task 1 interfaces; retain store.materialize signature; stage below _staging; fingerprint the complete normalized Trial payload; equal replay is a no-op preserving timestamps; changed replay is snapshot_conflict; never expose staging through projection.
Tests to write: The seven named Task 2 tests plus the updated former mutable-rematerialization test.
```

### Task 3: Lightweight projection and reproducible demo data

**Files:**
- Modify: `eval/read_api/projection.py`
- Modify: `eval/read_api/demo_data.py`
- Modify: `tests/eval/test_read_api_projection.py`
- Modify: `tests/eval/test_read_api_demo_data.py`
- Modify: `frontend/src/eval/types.ts`

**Interfaces:**
- Consumes: schema-v2 `run-manifest.yaml` from Task 2.
- Produces: every projected `EvalTrial` carries `artifact_summary: {status: "available" | "project_artifacts_unavailable", hunting: number, skills: number}`; demo Trials contain safe synthetic hunting and skill artifacts.

- [ ] **Step 1: Add failing schema compatibility tests**

Add `test_schema_v2_projects_lightweight_artifact_counts_without_content` and `test_schema_v1_artifacts_are_unavailable_not_degraded`. Assert `/snapshot` never contains `relative_path`, artifact body text, or inventory entries.

- [ ] **Step 2: Run projection tests and confirm the missing field**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_projection.py -q`

Expected: FAIL because `artifact_summary` is absent.

- [ ] **Step 3: Implement summary projection and TypeScript wire type**

Add `ProjectArtifactSummary` in `frontend/src/eval/types.ts` and the required `artifact_summary` field on `EvalTrial`. Treat malformed schema-v2 `project_artifacts` as unavailable without changing Trial `availability` or `reason`.

- [ ] **Step 4: Extend the synthetic corpus through production inventory helpers**

For at least one complete demo Trial, create a synthetic hunt config, test spec, pod export/log/variant, `SKILL.md`, Markdown reference, script, and binary asset under its project tree. Generate the inventory through Task 1 helpers; do not hand-author ids or digests. Keep the Compose demo overlay unchanged.

- [ ] **Step 5: Pin demo determinism and privacy**

Add assertions that two generations are byte-equivalent, counts are stable, binary content is not present in `/snapshot`, and the intentionally degraded demo Trial stays degraded only for its existing reason.

- [ ] **Step 6: Run projection and demo tests**

Run: `PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_read_api_projection.py tests/eval/test_read_api_demo_data.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit projection compatibility**

```bash
git add eval/read_api/projection.py eval/read_api/demo_data.py tests/eval/test_read_api_projection.py tests/eval/test_read_api_demo_data.py frontend/src/eval/types.ts
git commit -m "feat(eval): project artifact summaries into dashboard snapshots"
```

```text
[WORKER TASK]
File to modify: eval/read_api/projection.py; eval/read_api/demo_data.py; tests/eval/test_read_api_projection.py; tests/eval/test_read_api_demo_data.py; frontend/src/eval/types.ts
Goal: Add lightweight artifact availability/counts to snapshots and a deterministic demo corpus for the new UI.
Exact Changes & Constraints: Schema v1 reports project_artifacts_unavailable without degrading the Trial; schema v2 reports only counts/status; no inventory paths or bodies enter /snapshot; generate demo ids/digests with production helpers.
Tests to write: The four named Task 3 tests plus stable-count/body-absence assertions in the existing demo tests.
```

### Task 4: Manifest-backed artifact read API

**Files:**
- Create: `eval/read_api/artifacts.py`
- Create: `tests/eval/test_read_api_artifacts.py`
- Modify: `eval/read_api/source.py`
- Modify: `eval/read_api/app.py`
- Modify: `tests/eval/test_read_api_app.py`

**Interfaces:**
- Consumes: schema-v2 manifest inventory and immutable files from Task 2.
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

Use response codes `project_artifacts_unavailable`, `artifact_missing`, `artifact_digest_mismatch`, and `artifact_unsafe`. An id absent from inventory is a plain 404 `artifact_not_found`; it must never be interpreted as a path.

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
Goal: Expose GET-only inventory, detail, and streamed raw-content endpoints backed solely by schema-v2 manifest ids.
Exact Changes & Constraints: Implement the Task 4 protocol and response shape; no client path input; verify containment/type/digest each time; enforce 512 KiB and 2 MiB limits; keep errors path-free; preserve source injection and disabled docs.
Tests to write: Route/contract tests plus every named boundary and adversarial case in Task 4.
```

### Task 5: Frontend contract, navigation, and grouped artifact index

**Files:**
- Create: `frontend/src/eval/projectArtifacts.ts`
- Create: `frontend/src/eval/ProjectArtifactsPage.tsx`
- Create: `frontend/src/eval/ProjectArtifactsPage.test.tsx`
- Modify: `frontend/src/eval/types.ts`
- Modify: `frontend/src/eval/client.ts`
- Modify: `frontend/src/eval/client.test.ts`
- Modify: `frontend/src/eval/EvalBreadcrumbs.tsx`
- Modify: `frontend/src/eval/TrialPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/eval/eval.css`
- Modify: snapshot fixtures in `frontend/src/eval/*.test.tsx`

**Interfaces:**
- Consumes: Task 3 `artifact_summary` and Task 4 inventory response.
- Produces: `ProjectArtifactEntry`, `ProjectArtifactGroup`, `ProjectArtifactInventory`, and `ProjectArtifactDetail` wire types; `getProjectArtifacts(...)`, `getProjectArtifact(...)`, and `projectArtifactContentUrl(...)`; routes from the spec; pure `groupLabel(...)` and ordering helpers.

- [ ] **Step 1: Add failing client URL and type-contract tests**

Assert all ids are individually URL-encoded, base URL remains independent of `VITE_AGENT_BASE_URL`, non-2xx responses reject, and content URL construction performs no fetch.

- [ ] **Step 2: Implement client types and calls**

Accept an optional `AbortSignal` on list/detail fetches. Do not add project artifacts to `EvalDataProvider`; each new page owns route-scoped loading/error state so `/snapshot` remains one shared request.

- [ ] **Step 3: Add failing navigation/index tests**

Cover the Trial summary link for `available`, the historical unavailable notice with no link, empty available inventory, grouped Hunting/Skills headings, direct route refresh, unknown Trial, API error, and an unresolved request aborted on route change.

- [ ] **Step 4: Implement routes, paths, Trial entry, and index page**

Add `evalPaths.projectArtifacts(...)` and `evalPaths.projectArtifact(...)`; register both routes under `/eval`; render groups in server order with stable keys and artifact links; keep all identifiers visible as text. Use `AbortController` cleanup for every route-scoped fetch.

- [ ] **Step 5: Add accessible index styling**

Extend existing eval CSS classes instead of introducing a second design system. Groups must be navigable by headings and lists, status must not rely on color, and the layout must stack at the existing mobile breakpoint.

- [ ] **Step 6: Run frontend client and index tests**

Run: `cd frontend && npm test -- src/eval/client.test.ts src/eval/ProjectArtifactsPage.test.tsx src/eval/EvalPage.test.tsx src/eval/navigation.test.tsx`

Expected: all tests PASS.

- [ ] **Step 7: Commit frontend navigation**

```bash
git add frontend/src/App.tsx frontend/src/eval/types.ts frontend/src/eval/client.ts frontend/src/eval/client.test.ts frontend/src/eval/EvalBreadcrumbs.tsx frontend/src/eval/TrialPage.tsx frontend/src/eval/projectArtifacts.ts frontend/src/eval/ProjectArtifactsPage.tsx frontend/src/eval/ProjectArtifactsPage.test.tsx frontend/src/eval/eval.css frontend/src/eval/*.test.tsx
git commit -m "feat(frontend): navigate trial project artifacts"
```

```text
[WORKER TASK]
File to modify: frontend/src/eval/types.ts; frontend/src/eval/client.ts; frontend/src/eval/EvalBreadcrumbs.tsx; frontend/src/eval/TrialPage.tsx; frontend/src/App.tsx; frontend/src/eval/eval.css; frontend/src/eval/projectArtifacts.ts; frontend/src/eval/ProjectArtifactsPage.tsx; related eval tests
Goal: Add on-demand artifact inventory loading and the grouped Hunting/Skills index route.
Exact Changes & Constraints: Match Task 4 wire types; URL-encode each id; keep artifact requests out of EvalDataProvider; abort requests on unmount/route changes; schema-v1 Trials show unavailable without a broken link; follow existing eval accessibility/layout patterns.
Tests to write: Named client and index/navigation cases from Task 5, including stale-request cancellation.
```

### Task 6: Semantic artifact detail renderers

**Files:**
- Create: `frontend/src/eval/ProjectArtifactPage.tsx`
- Create: `frontend/src/eval/ProjectArtifactRenderers.tsx`
- Create: `frontend/src/eval/ProjectArtifactPage.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/eval/eval.css`

**Interfaces:**
- Consumes: Task 4 detail response and Task 5 client/types/routes.
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

Fetch by route ids with `AbortController`, show breadcrumbs and immutable metadata, isolate loading/error state, and provide raw/download actions using Task 5 URL helpers. A late response after navigation must be ignored.

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
Tests to write: Typed renderer, sanitization, escaping, parse-error, truncation, binary, raw-toggle, and stale-navigation cases named in Task 6.
```

### Task 7: Real-server overlay, cross-layer acceptance, and operator docs

**Files:**
- Create: `eval/docker-compose.dashboard.real.yml`
- Create: `tests/eval/test_real_project_artifacts_flow.py`
- Modify: `tests/eval/test_eval_overlay.py`
- Modify: `README.md`
- Modify: `eval/OPERATOR.md`
- Modify: `eval/read_api/source.py`
- Modify: `tests/eval/test_read_api_source.py`

**Interfaces:**
- Consumes: Tasks 1-6 complete stack.
- Produces: real overlay with `eval-api` and `eval-dashboard` only; read-only `${EVAL_ARTIFACT_STORE_HOST_PATH:-/srv/eval-artifacts}` bind; health fields `store_configured`, `store_readable`, and `materialized_trials`; documented server commands.

- [ ] **Step 1: Add failing Compose render tests**

Extend the staging helper to copy the real overlay. Assert exactly two added services, no `eval-store`, read-only host bind at `/srv/eval-artifacts`, loopback ports, proxy target `http://eval-api:8090`, and no mount of `live/` or the instance data root. Reassert the demo overlay still uses its dedicated named volume.

- [ ] **Step 2: Implement the real overlay**

Reuse the same images/commands/health checks as the demo API/dashboard, but remove generator/dependency wiring. Require or default `EVAL_ARTIFACT_STORE_HOST_PATH` exactly as the spec states; mount source and eval code read-only.

- [ ] **Step 3: Pin health semantics**

Make health `ok` only when the store is configured and readable. Add `materialized_trials` count without treating a readable empty store as degraded. Add tests for unset, nonexistent, unreadable/non-directory, empty, and populated stores.

- [ ] **Step 4: Write the materializer-to-HTTP acceptance test**

In `test_real_project_artifacts_flow.py`, build a realistic temporary project with one hunting family and one skill bundle, run production `store.materialize`, create the real source/app over that store, then assert `/snapshot` summary, inventory grouping, semantic detail, and streamed raw bytes agree on ids and digests.

- [ ] **Step 5: Document real and demo startup separately**

Add exact Compose commands, loopback URLs, `EVAL_ARTIFACT_STORE_HOST_PATH`, expected `/health` fields, and the schema-v1 unavailable behavior. Do not describe the real overlay as live monitoring.

- [ ] **Step 6: Run backend, Compose, frontend, and build verification**

Run:

```bash
PYTHONPATH=eval .venv/bin/python -m pytest tests/eval/test_orchestrator_project_artifacts.py tests/eval/test_orchestrator_store.py tests/eval/test_orchestrator_cli_store.py tests/eval/test_read_api_projection.py tests/eval/test_read_api_demo_data.py tests/eval/test_read_api_source.py tests/eval/test_read_api_app.py tests/eval/test_read_api_artifacts.py tests/eval/test_real_project_artifacts_flow.py tests/eval/test_eval_overlay.py -q
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
Goal: Deploy the dashboard against the real server store and prove the complete materializer-to-HTTP flow.
Exact Changes & Constraints: Keep demo and real overlays separate; real overlay has only eval-api/eval-dashboard, read-only store bind, and loopback ports; health distinguishes readable empty stores; document completed-Trial semantics; run the full verification matrix.
Tests to write: Real-overlay render assertions, health-state matrix, and the production materialize→snapshot→inventory→detail→content acceptance test.
```
