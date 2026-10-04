# Unified Target and Trial Workspace

**Status:** proposed
**Date:** 2026-10-04

## Intent

The eval dashboard is a read-only SPA for browsing every eval Target and its
Trials. A person opens one Target and reads, in one ordered flow, the Trial
outcomes, L0/L1 graph, Hunting artifacts, Skill artifacts, diagnoses, and
evidence that are actually still present on the eval server.

The UI must not require the operator to understand store schema v1 versus v2,
the materialized store layout, the live Neo4j database, or the raw project data
root. Those remain data-source concerns handled by the read API.

## Non-goals

- Do not modify the eval runner, Trial records, verdicts, diagnoses, Neo4j, or
  raw project files.
- Do not reconstruct a historical graph that was never captured.
- Do not assign an orphan project directory to a Target without a Trial record
  proving that association.
- Do not copy raw data into the authoritative Trial store.
- Do not remove the existing historical APIs or break existing URLs.

## Domain and navigation

The primary hierarchy is:

```text
Target
└── Trial
    ├── results: identified / partial / missed
    ├── diagnoses and evidence
    ├── L0/L1 graph
    ├── Hunting artifacts
    └── Skill artifacts
```

`project_id` is the storage join key carried by a Trial. It remains visible as
technical metadata, but it is not a primary navigation entity.

The SPA routes are:

```text
/                              Target catalog
/targets/:targetId             Unified Target workspace
/targets/:targetId/trials/:targetRunId/:trialId
                               Stable deep link to one Trial section
```

Existing `/p/...` and `/eval/...` links remain valid through compatibility
routes or redirects. The Target catalog replaces the current project-id-first
home as the primary entry point.

## Server data sources

The read API joins three read-only sources.

### 1. Materialized Trial store

The authoritative eval history under:

```text
/srv/eval-artifacts/<target_id>/<target_run_id>/<trial_id>/
```

It provides Trial identity, phases, verdicts, diagnoses, evidence, and, for a
schema-v2 Trial, a captured graph and materialized project-artifact inventory.

### 2. Project data root

The execution output under:

```text
/opt/polymerhus-dev/eval/instances/eval-server-1/data/<project_id>/
```

It may contain allowlisted Hunting and Skill artifacts even when a schema-v1
Trial did not copy them into the materialized store. The eval API receives this
root through a read-only bind mount and never accepts a host path from a client.

### 3. Current project graph

The existing agent endpoint:

```text
GET /projects/<project_id>/graph
```

It reads the L0 and L1 nodes and edges currently stored in Neo4j for that
project. The eval API reaches it through a configured internal agent base URL.

## Trial resolution rules

The read API resolves each Trial independently.

Fallback data is eligible only when the Trial's `instance_id` matches the
configured live instance. A Trial from another instance never reads the
current instance's Neo4j graph or project directory merely because a project
ID happens to match.

### Graph

1. If the Trial contains a valid captured schema-v2 graph, return it with
   `source: trial_snapshot`.
2. Otherwise query the current agent graph using the Trial's `project_id` and
   return it with `source: project_storage`.
3. A missing project, empty graph, or unavailable agent produces an unavailable
   graph section only; it never hides the Trial results.

The fallback graph is real saved server data, but not a historical capture.
The response and UI state that fact without requiring the user to understand
schema versions.

### Artifacts

1. If the Trial contains a valid schema-v2 artifact inventory, use the
   immutable materialized artifacts with `source: trial_snapshot`.
2. Otherwise collect the allowlisted files beneath the Trial's `project_id` in
   the project data root and return them with `source: project_storage`.
3. A missing directory is an empty/unavailable artifact section only; it never
   hides verdicts, diagnoses, or the graph.

The existing artifact kinds remain the complete public vocabulary:

- Hunting: `hunt_config`, `test_spec`, `pod_variant`, `experiment_log`,
  `pod_export`.
- Skills: `skill_procedure`, `skill_reference`, `skill_script`, `skill_asset`.

When multiple Trials carry the same `project_id`, their fallback graph and raw
artifact inventory are shared project data. The API returns that source
explicitly instead of pretending each Trial captured a separate copy.

## Unified read API

Existing historical endpoints keep their strict current semantics. New
resolved endpoints provide the source-independent view used by the SPA:

```text
GET /trials/:targetId/:targetRunId/:trialId/resolved-graph
GET /trials/:targetId/:targetRunId/:trialId/resolved-artifacts
GET /trials/:targetId/:targetRunId/:trialId/resolved-artifacts/:artifactId
GET /trials/:targetId/:targetRunId/:trialId/resolved-artifacts/:artifactId/content
```

Resolved graph responses include `status`, `source`, optional `captured_at`,
and the existing `GraphData` body. Resolved artifact responses preserve the
existing inventory, detail, preview, and content contracts and add `source`.

`/snapshot` remains the Target/Trial index. It gains a compact list of raw
project directories that cannot be associated with any Trial. The SPA exposes
these under an `Unassigned saved data` diagnostic section so no saved directory
is silently hidden or falsely attributed.

Runtime configuration is explicit:

```text
EVAL_PROJECT_DATA_ROOT=/srv/eval-project-data
EVAL_AGENT_BASE_URL=http://agent:8080
EVAL_INSTANCE_ID=eval-server-1
```

The dashboard compose overlay binds the host project data root to
`/srv/eval-project-data:ro`. The authoritative Trial store remains separately
mounted read-only.

## SPA presentation

### Target catalog

The home page lists Targets derived from the eval snapshot, ordered
deterministically. Each entry summarizes Trial count and outcome counts. It
does not create one top-level card for every internal `project_id`.

### Target workspace

The Target page orders Trials newest first. Each Trial section presents:

1. Trial identity, terminal state, phase information, and `project_id` metadata;
2. identified, partial, and missed outcomes with diagnoses and evidence;
3. its resolved L0/L1 graph using the existing layer controls and canvas;
4. its resolved Hunting artifact inventory and detail views;
5. its resolved Skill artifact inventory and detail views.

Sections remain independently usable. Missing graph data produces `No graph
available`. Missing artifact data produces `No Hunting artifacts` or `No Skill
artifacts`. Empty canvases, fake zero counters, and schema-version terminology
are not shown.

A compact source note distinguishes `Captured with Trial` from `Saved for
project`. It is informational rather than a separate workflow.

## Safety

- Both filesystem roots are mounted read-only.
- Project IDs are resolved from server-side Trial records or enumerated safe
  directory names, never accepted as filesystem paths.
- Artifact discovery reuses the existing allowlist and rejects symlinks,
  non-regular files, traversal, and paths outside the selected project root.
- Detail and content requests resolve only inventory-issued artifact IDs.
- Responses never expose host paths, container paths, credentials, or arbitrary
  files outside Hunting and Skills.
- Agent timeouts, malformed graphs, and unreadable artifacts degrade only their
  own sections.

## Compatibility

- Schema-v2 captured data always wins and retains its immutable behavior.
- Schema-v1 gains graph and artifact visibility only when the referenced
  project data still exists.
- Existing snapshot, historical graph, and historical artifact contracts remain
  available for current clients and tests.
- Existing project/eval deep links redirect to or embed the corresponding
  Target/Trial workspace without losing identity.

## Testing

Backend tests cover:

- v1 Trial with both Neo4j graph and raw Hunting/Skill artifacts;
- v1 Trial with only one fallback source;
- v2 Trial precedence over changing live/raw data;
- two Trials sharing one project;
- missing, empty, malformed, and timed-out sources;
- orphan raw directories;
- allowlist, symlink, traversal, content, digest, and host-path protections.

Frontend tests cover:

- Target-first catalog and routing;
- chronological Trial sections;
- continuous results, graph, Hunting, and Skills presentation;
- L0/L1 controls for resolved graphs;
- semantic/raw artifact views and downloads;
- source notes and independent empty/error states;
- compatibility redirects from existing URLs.

## Acceptance against the current eval server

For `comfyui-1`, the SPA lists all five materialized Trials. The three Trials
whose current projects remain in Neo4j show their respective graphs:

- `c0641257-a1a9-4e13-acee-6effa28311f5`: 82 nodes / 49 links;
- `75991388-1787-49f9-8f28-3448942add0f`: 374 / 341;
- `b52151db-05b7-4725-a411-2c71e08d34d1`: 368 / 335.

The older projects without a current Neo4j graph show the simple unavailable
state. Every Trial continues to show its valid verdicts and diagnoses. Raw
Hunting and Skill files are shown under the Trial whose record carries the same
`project_id`; unlinked raw directories remain visible only as unassigned data.

No source data is mutated during indexing, browsing, preview, or download.
