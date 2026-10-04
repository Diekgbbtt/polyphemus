# Unified Target and Trial Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the dashboard into a read-only Target → Trial SPA that shows each Trial's saved results, resolved L0/L1 graph, and resolved Hunting/Skill artifacts without exposing schema-v1/v2 storage details to the browser.

**Architecture:** Keep `/snapshot` as the authoritative Target/Trial index and add a backend resolution layer that prefers immutable schema-v2 captures, then safely falls back to the matching eval instance's current Neo4j graph and allowlisted raw project directory. The frontend consumes only the resolved Trial APIs, presents Targets first, and keeps graph, results, Hunting, and Skills as independent sections so one unavailable source cannot blank the workspace.

**Tech Stack:** Python 3, FastAPI, PyYAML, pytest; React 19, TypeScript, React Router 7, Vitest/Testing Library; Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-04-unified-target-trial-workspace-design.md`

## Global Constraints

- Preserve the existing `/snapshot`, strict historical `/project-graph`, and strict historical `/artifacts` endpoints and their response semantics.
- Do not mutate Trial records, materialized store files, Neo4j, or raw project data. Both filesystem mounts remain read-only.
- Resolve fallback `project_id` and `instance_id` only from a server-side Trial record. Never accept a filesystem path from the client.
- Permit fallback only when the Trial `instance_id` equals `EVAL_INSTANCE_ID`; otherwise return that section as unavailable.
- Reuse `orchestrator.project_artifacts.collect_project_artifacts` and its exact artifact-kind allowlist. Do not add a second recursive walker.
- Inventory/detail/content must revalidate containment, regular-file status, symlink absence, size, and SHA-256 before returning bytes.
- Never include host/container paths, credentials, raw exception messages, or arbitrary file content in errors or `/snapshot`.
- A corrupt schema-v2 capture is never served. The resolved endpoint may fall back to matching project storage, but must return a safe `fallback_reason`; the strict historical endpoint remains the integrity diagnostic.
- Use only `source: "trial_snapshot" | "project_storage"` in resolved responses. The UI labels these `Captured with Trial` and `Saved for project`.
- Do not show schema-version terminology, fake zero counters, or empty graph canvases in the primary SPA.
- Retain compatibility for existing `/p/...` and `/eval/...` URLs by redirecting to the canonical Target/Trial route where identity is known.
- Work in the writable implementation checkout, preserve unrelated dirty files, and use `apply_patch` for hand edits.

## Review Focus

1. A Trial from another `instance_id` must never read this server's raw directory or Neo4j graph even if its `project_id` matches.
2. A malformed or digest-mismatched schema-v2 capture must never leak bytes; fallback must be explicit and strict historical endpoints must still report the integrity error.
3. Two Trials sharing one `project_id` may expose identical current project data, but neither response may imply that it was captured independently with either Trial.
4. Raw inventory is a view of current project storage: detail re-resolves current metadata, and content binds to the digest returned by detail. If a file disappears or changes during either request, fail with a path-free 404/409 rather than serving unverified bytes.
5. Agent timeout, invalid graph JSON, or graph 404 must degrade only the graph section; verdicts, diagnoses, Hunting, and Skills remain usable.
6. Raw/live project IDs without a proving Trial relationship must appear only under `Unassigned saved data`, never under an arbitrary Target.

---

### Task 1: Add a safe Trial-resolution context

**Files:**
- Create: `eval/read_api/resolved.py`
- Test: `tests/eval/test_read_api_resolved.py`

- [ ] **Step 1: Write failing Trial-context tests**

Cover exact identity lookup from the projected snapshot, safe handling of an unknown Trial, missing `project_id`, missing `instance_id`, and eligibility only when `trial.instance_id == configured_instance_id`.

The public seam should be small and typed:

```python
@dataclass(frozen=True)
class TrialContext:
    target_id: str
    target_run_id: str
    trial_id: str
    project_id: str | None
    instance_id: str | None
    fallback_eligible: bool

def resolve_trial_context(
    snapshot: Mapping[str, object],
    target_id: str,
    target_run_id: str,
    trial_id: str,
    *,
    configured_instance_id: str | None,
) -> TrialContext: ...
```

Use a coded, path-free `ResolvedDataError(code, status_code)`; unknown or unsafe identities return `trial_not_found`/404.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `pytest -q tests/eval/test_read_api_resolved.py`

Expected: import or assertion failures because the resolution module does not exist.

- [ ] **Step 3: Implement the minimal context resolver**

Look up the full `(target_id, target_run_id, trial_id)` tuple in `snapshot["trials"]`; never infer association by `project_id`. Treat missing/unsafe IDs as unavailable metadata rather than paths. Do not perform I/O at import time.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `pytest -q tests/eval/test_read_api_resolved.py`

- [ ] **Step 5: Commit**

```bash
git add eval/read_api/resolved.py tests/eval/test_read_api_resolved.py
git commit -m "feat(eval-api): resolve trial storage context"
```

### Task 2: Resolve schema-v2 and raw project artifacts behind one contract

**Files:**
- Create: `eval/read_api/resolved_artifacts.py`
- Modify: `eval/read_api/artifacts.py`
- Modify: `eval/read_api/resolved.py`
- Test: `tests/eval/test_read_api_resolved_artifacts.py`
- Test: `tests/eval/test_read_api_artifacts.py`

- [ ] **Step 1: Write failing source-selection and safety tests**

Create fixtures for:

- valid schema-v2 inventory plus different raw files: captured inventory wins and reports `trial_snapshot`;
- schema-v1 Trial with matching instance: raw Hunting and Skill files are collected and report `project_storage`;
- schema-v1 Trial with mismatched/missing instance or project: no raw lookup occurs;
- malformed/digest-mismatched v2 capture: captured bytes are rejected and matching raw fallback carries a stable `fallback_reason`;
- two Trials sharing one project: both return the same project-storage inventory and source note;
- symlink, traversal-like ID, special file, and a file disappearing/changing during detail or content verification: safe coded failure with no absolute path;
- empty/missing raw project directory: available empty inventory or a stable unavailable response, as fixed by the contract below.

Resolved inventory contract:

```json
{
  "status": "available",
  "source": "trial_snapshot",
  "project_id": "...",
  "fallback_reason": null,
  "groups": []
}
```

Use `status: "unavailable"`, `reason`, `source: "project_storage"`, `project_id`, and `groups: []` when fallback is ineligible or unreadable. A real, readable project with zero allowlisted files is `available` with empty groups.

- [ ] **Step 2: Run artifact tests and confirm RED**

Run: `pytest -q tests/eval/test_read_api_resolved_artifacts.py tests/eval/test_read_api_artifacts.py`

- [ ] **Step 3: Refactor artifact rendering around an internal inventory source**

In `artifacts.py`, extract internal helpers that accept a trusted root plus validated entries for grouping, lookup, preview, and streaming. Keep all existing public functions and strict schema-v2 behavior unchanged. Do not expose private filesystem handles in serialized values.

In `resolved_artifacts.py`, define one resolved inventory object containing only `source`, `project_id`, root, validated entries, and optional safe fallback reason. For raw fallback:

- call `collect_project_artifacts(project_data_root, context.project_id, files=FileStore())`;
- convert only `ProjectArtifact.as_manifest_entry()` to the wire inventory;
- retain `source_path` internally solely for re-verification;
- issue artifact IDs only from the inventory;
- rebuild resolved detail/content URLs, never trust a stored URL;
- include the detail entry's SHA-256 as an encoded `expected_sha256` query on its resolved content URL, and require the content endpoint to compare it before streaming. A list-to-detail change is intentionally reported as the latest current-project metadata; a detail-to-content change is rejected.

- [ ] **Step 4: Run focused and regression tests**

Run: `pytest -q tests/eval/test_read_api_resolved.py tests/eval/test_read_api_resolved_artifacts.py tests/eval/test_read_api_artifacts.py tests/eval/test_orchestrator_project_artifacts.py`

Expected: all pass; strict historical tests remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add eval/read_api/resolved.py eval/read_api/resolved_artifacts.py eval/read_api/artifacts.py tests/eval/test_read_api_resolved_artifacts.py tests/eval/test_read_api_artifacts.py
git commit -m "feat(eval-api): resolve trial artifact sources"
```

### Task 3: Resolve captured and current L0/L1 graphs server-side

**Files:**
- Create: `eval/read_api/resolved_graph.py`
- Modify: `eval/read_api/resolved.py`
- Test: `tests/eval/test_read_api_resolved_graph.py`
- Test: `tests/eval/test_read_api_project_graph.py`

- [ ] **Step 1: Write failing graph precedence and isolation tests**

Cover valid captured graph precedence; schema-v1 matching-instance fallback; shared project across Trials; instance mismatch; missing project ID; agent 404; empty graph; timeout; non-JSON body; invalid graph shape; and a corrupt captured graph followed by an explicitly labelled fallback.

Inject the network seam rather than opening sockets in unit tests:

```python
class ProjectGraphClient(Protocol):
    def get_graph(self, project_id: str) -> Mapping[str, object]: ...
```

Resolved graph contract:

```json
{
  "status": "available",
  "source": "project_storage",
  "project_id": "...",
  "captured_at": null,
  "fallback_reason": "project_graph_unavailable",
  "graph": {"nodes": [], "links": []}
}
```

Empty or failed live graphs instead return `status: "unavailable"`, a stable `reason`, and no graph body.

- [ ] **Step 2: Run graph tests and confirm RED**

Run: `pytest -q tests/eval/test_read_api_resolved_graph.py tests/eval/test_read_api_project_graph.py`

- [ ] **Step 3: Implement the resolver and bounded HTTP client**

Attempt `read_project_graph` first. On a coded historical-unavailable/invalid/digest failure, retain the safe code as `fallback_reason`; never return bad captured bytes. If fallback is eligible, query exactly `GET {EVAL_AGENT_BASE_URL}/projects/{quoted_project_id}/graph` with a bounded timeout, then normalize through `orchestrator.project_graph.normalize_project_graph(project_id=...)`.

Map transport, HTTP, decode, and normalization failures to stable path-free reasons. Never forward agent response bodies or raw exception strings.

- [ ] **Step 4: Run focused and regression tests**

Run: `pytest -q tests/eval/test_read_api_resolved.py tests/eval/test_read_api_resolved_graph.py tests/eval/test_read_api_project_graph.py`

- [ ] **Step 5: Commit**

```bash
git add eval/read_api/resolved.py eval/read_api/resolved_graph.py tests/eval/test_read_api_resolved_graph.py tests/eval/test_read_api_project_graph.py
git commit -m "feat(eval-api): resolve trial graph sources"
```

### Task 4: Publish resolved endpoints and enumerate unassigned saved data

**Files:**
- Modify: `eval/read_api/source.py`
- Modify: `eval/read_api/app.py`
- Modify: `eval/read_api/resolved.py`
- Modify: `eval/read_api/resolved_artifacts.py`
- Test: `tests/eval/test_read_api_source.py`
- Test: `tests/eval/test_read_api_app.py`
- Test: `tests/eval/test_read_api_resolved.py`

- [ ] **Step 1: Write failing source/API contract tests**

Extend the injected source fake and route assertions for exactly four new GET families:

```text
/trials/{target_id}/{target_run_id}/{trial_id}/resolved-graph
/trials/{target_id}/{target_run_id}/{trial_id}/resolved-artifacts
/trials/{target_id}/{target_run_id}/{trial_id}/resolved-artifacts/{artifact_id}
/trials/{target_id}/{target_run_id}/{trial_id}/resolved-artifacts/{artifact_id}/content
```

Test GET-only behavior, status-code mapping, response headers for raw content, and absence of host paths. Test environment values are read at factory-call time:

```text
EVAL_PROJECT_DATA_ROOT
EVAL_AGENT_BASE_URL
EVAL_INSTANCE_ID
```

Test `/health` reports whether the optional raw root and graph client are configured without making a readable materialized store unhealthy. Test `/snapshot.unassigned_saved_data` contains only safe project IDs not referenced by a Trial for the configured instance, with compact Hunting/Skill counts and no inventory paths. Each row has `project_id`, `status`, `hunting`, `skills`, and an optional stable `reason`; a safe-named symlink/unreadable directory is listed as unavailable but never traversed.

- [ ] **Step 2: Run API/source tests and confirm RED**

Run: `pytest -q tests/eval/test_read_api_source.py tests/eval/test_read_api_app.py tests/eval/test_read_api_resolved.py`

- [ ] **Step 3: Extend the source protocol and filesystem adapter**

Add explicit resolved graph/list/detail/content methods to `SnapshotSource`; the content method also receives the required `expected_sha256`. Configure `ArtifactStoreSnapshotSource` with optional `project_data_root`, `agent_base_url`, `instance_id`, and an injectable graph client factory. Each resolved request builds the snapshot, resolves one Trial context, then delegates to the appropriate resolver.

Augment `snapshot()` with deterministic `unassigned_saved_data` after projection. Enumerate only direct safe child directories of the configured raw root. Consider a directory assigned only when a projected Trial has the same `project_id` and matching `instance_id`; otherwise expose only its ID and category counts.

- [ ] **Step 4: Add routes without changing strict endpoints**

Map only coded resolution errors. Stream content with the existing `Content-Disposition`, `Content-Length`, and `X-Content-Type-Options: nosniff` behavior.

- [ ] **Step 5: Run focused and regression tests**

Run: `pytest -q tests/eval/test_read_api_source.py tests/eval/test_read_api_app.py tests/eval/test_read_api_resolved.py tests/eval/test_read_api_resolved_artifacts.py tests/eval/test_read_api_resolved_graph.py tests/eval/test_read_api_artifacts.py tests/eval/test_read_api_project_graph.py`

- [ ] **Step 6: Commit**

```bash
git add eval/read_api/source.py eval/read_api/app.py eval/read_api/resolved.py eval/read_api/resolved_artifacts.py tests/eval/test_read_api_source.py tests/eval/test_read_api_app.py tests/eval/test_read_api_resolved.py
git commit -m "feat(eval-api): expose resolved trial data"
```

### Task 5: Add typed resolved clients and canonical Target routes

**Files:**
- Modify: `frontend/src/eval/types.ts`
- Modify: `frontend/src/eval/client.ts`
- Modify: `frontend/src/eval/EvalBreadcrumbs.tsx`
- Modify: `frontend/src/projectPaths.ts`
- Test: `frontend/src/eval/client.test.ts`
- Test: `frontend/src/eval/navigation.test.tsx`

- [ ] **Step 1: Write failing URL and wire-contract tests**

Add `ResolvedSource`, `ResolvedProjectGraph`, resolved artifact inventory/detail, and `UnassignedSavedData` types. Keep `unassigned_saved_data` optional on the TypeScript snapshot type for old fixtures/servers, while the new backend always emits it. Assert all IDs and the expected digest are encoded, every request uses `VITE_EVAL_API_BASE_URL`, abort signals propagate, and resolved content URLs point only at the new endpoint.

Canonical path helpers:

```text
target(targetId) -> /targets/:targetId
trial(targetId, targetRunId, trialId) -> /targets/:targetId/trials/:targetRunId/:trialId
trialArtifact(...) -> .../artifacts/:artifactId
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cd frontend && npm test -- --run src/eval/client.test.ts src/eval/navigation.test.tsx`

- [ ] **Step 3: Implement types, clients, and path helpers**

Add `getResolvedTrialGraph`, `getResolvedArtifacts`, `getResolvedArtifact`, and `resolvedArtifactContentUrl`. Do not leave any direct call from a Trial component to the live agent `getGraph`; source choice belongs to the eval API.

- [ ] **Step 4: Run focused tests and TypeScript**

Run: `cd frontend && npm test -- --run src/eval/client.test.ts src/eval/navigation.test.tsx && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/eval/types.ts frontend/src/eval/client.ts frontend/src/eval/EvalBreadcrumbs.tsx frontend/src/projectPaths.ts frontend/src/eval/client.test.ts frontend/src/eval/navigation.test.tsx
git commit -m "feat(eval-ui): add resolved trial client"
```

### Task 6: Replace the project catalog with a Target-first home

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/pages/ProjectNav.tsx`
- Modify: `frontend/src/site.css`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/eval/navigation.test.tsx`

- [ ] **Step 1: Write failing catalog and compatibility-route tests**

Assert `/` renders one row per `snapshot.targets`, ordered by `target_id`, with Trial and outcome counts and a link to `/targets/:targetId`. It must not render one primary row per `project_id`.

Add an `Unassigned saved data` section that merges backend raw-only IDs with current agent projects that no Trial proves belong to a Target. It is diagnostic only and must not fabricate a Trial link. If either source fails, the Target catalog from the other source remains usable.

Assert canonical `/targets/:targetId`, `/targets/:targetId/trials/:targetRunId/:trialId`, and `.../artifacts/:artifactId` routes mount under the shared eval provider. Existing `/eval/targets/...`, `/eval/trials/...`, and project-scoped Trial links redirect to canonical routes while preserving full Trial identity.

- [ ] **Step 2: Run catalog/navigation tests and confirm RED**

Run: `cd frontend && npm test -- --run src/App.test.tsx src/eval/navigation.test.tsx`

- [ ] **Step 3: Implement the Target catalog and redirects**

Keep the current vertical `<ul>/<li>` list styling. Remove `Live only`, `Eval only`, and `Live + Eval` as primary concepts. Use plain source diagnostics only inside `Unassigned saved data`. Ensure loading resolves independently and never sticks when one request rejects.

- [ ] **Step 4: Run focused tests and TypeScript**

Run: `cd frontend && npm test -- --run src/App.test.tsx src/eval/navigation.test.tsx && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/ProjectsPage.tsx frontend/src/pages/ProjectNav.tsx frontend/src/site.css frontend/src/App.test.tsx frontend/src/eval/navigation.test.tsx
git commit -m "feat(eval-ui): make targets the primary catalog"
```

### Task 7: Extract one reusable Trial-results section

**Files:**
- Create: `frontend/src/eval/TrialResults.tsx`
- Modify: `frontend/src/eval/TrialPage.tsx`
- Modify: `frontend/src/eval/TrialArtifactPage.tsx`
- Test: `frontend/src/eval/TrialResults.test.tsx`
- Test: `frontend/src/eval/navigation.test.tsx`

- [ ] **Step 1: Write failing result-presentation tests**

Assert every verdict row remains distinct, including repeated rows for one vulnerability. Each row shows `identified`/`partial`/`missed`, confidence, safe match fields, and safe evidence references. Diagnoses pair by vulnerability without inventing missing diagnoses; unmatched diagnoses remain visible and explicitly labelled.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cd frontend && npm test -- --run src/eval/TrialResults.test.tsx src/eval/navigation.test.tsx`

- [ ] **Step 3: Extract and reuse `TrialResults`**

Move presentation only; keep the existing snapshot wire data and safety filtering. Give identified/partial/missed text labels independent of colour. Update existing Trial views to use the component without changing their routes yet.

- [ ] **Step 4: Run tests and TypeScript**

Run: `cd frontend && npm test -- --run src/eval/TrialResults.test.tsx src/eval/navigation.test.tsx && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/eval/TrialResults.tsx frontend/src/eval/TrialPage.tsx frontend/src/eval/TrialArtifactPage.tsx frontend/src/eval/TrialResults.test.tsx frontend/src/eval/navigation.test.tsx
git commit -m "refactor(eval-ui): share trial result presentation"
```

### Task 8: Make the Trial graph consume only the resolved API

**Files:**
- Modify: `frontend/src/eval/TrialProjectGraph.tsx`
- Modify: `frontend/src/eval/TrialProjectGraph.test.tsx`

- [ ] **Step 1: Write failing resolved-graph tests**

Assert the component calls only `getResolvedTrialGraph`, never the agent client. Test both source labels, existing L0/L1 controls, unavailable/empty graph without a canvas, abort behavior, and a graph error confined to the graph section.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `cd frontend && npm test -- --run src/eval/TrialProjectGraph.test.tsx`

- [ ] **Step 3: Simplify `TrialProjectGraph`**

Remove `projectId`, summary-driven source selection, `getGraph`, `HttpError`, and the live-graph link. Fetch by full Trial identity, render `Captured with Trial` or `Saved for project`, pass only non-empty graph data to `GraphView`, and render `No graph available` for the unavailable contract.

- [ ] **Step 4: Run tests and TypeScript**

Run: `cd frontend && npm test -- --run src/eval/TrialProjectGraph.test.tsx src/graph/GraphView.test.tsx src/graph/projection.test.ts && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/eval/TrialProjectGraph.tsx frontend/src/eval/TrialProjectGraph.test.tsx
git commit -m "feat(eval-ui): render resolved trial graphs"
```

### Task 9: Render resolved Hunting and Skill artifacts

**Files:**
- Create: `frontend/src/eval/ResolvedArtifactsSection.tsx`
- Modify: `frontend/src/eval/ProjectArtifactsPage.tsx`
- Modify: `frontend/src/eval/ProjectArtifactPage.tsx`
- Modify: `frontend/src/eval/projectArtifacts.ts`
- Modify: `frontend/src/eval/eval.css`
- Test: `frontend/src/eval/ResolvedArtifactsSection.test.tsx`
- Test: `frontend/src/eval/ProjectArtifactsPage.test.tsx`
- Test: `frontend/src/eval/ProjectArtifactPage.test.tsx`

- [ ] **Step 1: Write failing inventory/detail/content tests**

Assert one inventory request per Trial; separate Hunting and Skills groups; explicit `No Hunting artifacts` and `No Skill artifacts`; both source labels; source-local error handling; canonical detail links; semantic YAML/text/binary renderers; and a raw download URL bound to the detail SHA-256.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cd frontend && npm test -- --run src/eval/ResolvedArtifactsSection.test.tsx src/eval/ProjectArtifactsPage.test.tsx src/eval/ProjectArtifactPage.test.tsx`

- [ ] **Step 3: Add the inline resolved inventory**

Load `getResolvedArtifacts` independently of graph/results and split it using existing `artifactSections`. Reuse group/kind/representation labels. A zero-entry readable inventory shows both explicit empty states, not a misleading unavailable message.

- [ ] **Step 4: Switch detail and download to resolved endpoints**

Make current artifact pages wrappers around resolved data so compatibility URLs still work. Validate returned artifact ID, use the detail entry's digest when building the content URL, and keep all existing safe preview renderers.

- [ ] **Step 5: Run focused tests and TypeScript**

Run: `cd frontend && npm test -- --run src/eval/ResolvedArtifactsSection.test.tsx src/eval/ProjectArtifactsPage.test.tsx src/eval/ProjectArtifactPage.test.tsx && npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/eval/ResolvedArtifactsSection.tsx frontend/src/eval/ProjectArtifactsPage.tsx frontend/src/eval/ProjectArtifactPage.tsx frontend/src/eval/projectArtifacts.ts frontend/src/eval/eval.css frontend/src/eval/ResolvedArtifactsSection.test.tsx frontend/src/eval/ProjectArtifactsPage.test.tsx frontend/src/eval/ProjectArtifactPage.test.tsx
git commit -m "feat(eval-ui): render resolved trial artifacts"
```

### Task 10: Assemble the continuous Target → Trial workspace

**Files:**
- Create: `frontend/src/eval/TrialSection.tsx`
- Modify: `frontend/src/eval/TargetPage.tsx`
- Modify: `frontend/src/pages/ProjectTrialPage.tsx`
- Modify: `frontend/src/eval/TrialPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/eval/eval.css`
- Test: `frontend/src/eval/TargetPage.test.tsx`
- Test: `frontend/src/eval/navigation.test.tsx`

- [ ] **Step 1: Write failing workspace and isolation tests**

For one Target with multiple Trials, assert newest-first order by `copied_at` with full Trial identity as a deterministic tie-breaker. Every Trial section shows identity, terminal, phase sequence, `project_id`, degraded notice, `TrialResults`, `TrialProjectGraph`, and `ResolvedArtifactsSection`.

Assert one graph error does not remove results/artifacts and one artifact error does not remove results/graph. Assert the deep canonical Trial URL renders the same section. Assert legacy eval/project Trial URLs preserve identity when redirecting.

- [ ] **Step 2: Run workspace/navigation tests and confirm RED**

Run: `cd frontend && npm test -- --run src/eval/TargetPage.test.tsx src/eval/navigation.test.tsx`

- [ ] **Step 3: Implement `TrialSection` and Target ordering**

Keep each async section mounted independently. Use stable DOM anchors from `(target_run_id, trial_id)` and avoid loading all artifact detail/content bodies: load inventories only until a user opens an artifact.

- [ ] **Step 4: Canonicalize Trial routes**

The deep route renders the same `TrialSection`, not a second project-centric workspace. Convert `ProjectTrialPage` and legacy `TrialPage` to identity-preserving redirects or thin wrappers. Do not make `project_id` a route parent.

- [ ] **Step 5: Run focused tests, full frontend tests, and build**

Run: `cd frontend && npm test -- --run src/eval/TargetPage.test.tsx src/eval/TrialResults.test.tsx src/eval/TrialProjectGraph.test.tsx src/eval/ResolvedArtifactsSection.test.tsx src/eval/navigation.test.tsx`

Run: `cd frontend && npm test && npx tsc --noEmit && npm run build`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/eval/TrialSection.tsx frontend/src/eval/TargetPage.tsx frontend/src/pages/ProjectTrialPage.tsx frontend/src/eval/TrialPage.tsx frontend/src/App.tsx frontend/src/eval/eval.css frontend/src/eval/TargetPage.test.tsx frontend/src/eval/navigation.test.tsx
git commit -m "feat(eval-ui): unify target trial workspace"
```

### Task 11: Wire read-only production sources and document operation

**Files:**
- Modify: `eval/docker-compose.dashboard.real.yml`
- Modify: `README.md`
- Test: `tests/eval/test_read_api_source.py`
- Test: `tests/eval/test_real_project_artifacts_flow.py`

- [ ] **Step 1: Write failing configuration/integration tests**

Add a real-flow fixture containing one schema-v1 Trial, an allowlisted raw Hunting/Skill tree, and an injected current graph. Exercise `/snapshot`, resolved graph, resolved inventory, every detail, and every content endpoint. Assert no absolute path occurs anywhere in serialized responses.

Add a schema-v2 fixture whose live/raw data differs and prove the captured graph/artifacts win. Include a raw-only project and prove it appears only in `unassigned_saved_data`.

- [ ] **Step 2: Run integration tests and confirm RED**

Run: `pytest -q tests/eval/test_real_project_artifacts_flow.py tests/eval/test_read_api_source.py`

- [ ] **Step 3: Update the production overlay**

Add only read-only configuration to `eval-api`:

```yaml
environment:
  EVAL_PROJECT_DATA_ROOT: /srv/eval-project-data
  EVAL_AGENT_BASE_URL: http://agent:8080
  EVAL_INSTANCE_ID: ${EVAL_INSTANCE_ID:-eval-server-1}
volumes:
  - ${EVAL_PROJECT_DATA_ROOT_HOST_PATH:-/opt/polymerhus-dev/eval/instances/eval-server-1/data}:/srv/eval-project-data:ro
```

Do not add writes, `down`, volume deletion, orphan removal, or another Neo4j instance.

- [ ] **Step 4: Document the one-command startup and source labels**

Update `README.md` with the three required environment variables, SSH tunnel example, canonical `/` route, expected `comfyui-1` behavior, and the meaning of `Captured with Trial`, `Saved for project`, and `Unassigned saved data`.

- [ ] **Step 5: Run integration and full targeted verification**

Run:

```bash
pytest -q \
  tests/eval/test_read_api_resolved.py \
  tests/eval/test_read_api_resolved_artifacts.py \
  tests/eval/test_read_api_resolved_graph.py \
  tests/eval/test_read_api_source.py \
  tests/eval/test_read_api_app.py \
  tests/eval/test_read_api_projection.py \
  tests/eval/test_read_api_artifacts.py \
  tests/eval/test_read_api_project_graph.py \
  tests/eval/test_real_project_artifacts_flow.py \
  tests/eval/test_orchestrator_project_artifacts.py
```

Run: `cd frontend && npm test && npx tsc --noEmit && npm run build`

Expected: all targeted tests pass; only the already documented Vite chunk-size warning may remain.

- [ ] **Step 6: Commit**

```bash
git add eval/docker-compose.dashboard.real.yml README.md tests/eval/test_real_project_artifacts_flow.py tests/eval/test_read_api_source.py
git commit -m "docs(eval): wire unified dashboard sources"
```

### Task 12: Verify on the eval server without mutating source data

**Files:**
- No source file changes expected.

- [ ] **Step 1: Inspect deployment state before updating**

On the server, confirm the dashboard checkout is clean, on `feat/eval-pipeline-frontend`, and the store/raw paths exist. Stop if the worktree is dirty or the resolved host paths differ from the approved paths.

- [ ] **Step 2: Fast-forward and rebuild only dashboard services**

Use the existing compose file set. Rebuild and restart only `eval-api` and `eval-dashboard`; do not restart the eval worker, agent, Neo4j, or PostgreSQL and do not run `down`.

- [ ] **Step 3: Smoke-test API contracts**

Verify `/health`, `/snapshot`, every `comfyui-1` Trial's resolved graph, artifact inventory, one detail, and one content request. Confirm the three known current graphs report 82/49, 374/341, and 368/335; older missing graphs report unavailable; no response exposes `/opt`, `/srv`, or credentials.

- [ ] **Step 4: Smoke-test the SPA through the SSH tunnel**

At `/`, verify one `comfyui-1` Target entry and all five Trials. For each Trial, verify results always render, graph/artifact failures stay local, Hunting/Skills reflect saved files, L0/L1 toggles work on available graphs, and raw-only directories appear only under `Unassigned saved data`.

- [ ] **Step 5: Record evidence and final regression state**

Capture commit SHA, service health, snapshot counts, per-Trial source labels/counts, and the exact verification commands. Do not copy or rewrite any Trial/raw artifact as part of smoke testing.
