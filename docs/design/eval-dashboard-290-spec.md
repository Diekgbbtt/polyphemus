# Eval benchmark dashboard specification (#290)

## Status

Implemented in the companion change for ticket #290. This document defines the
read-only eval dashboard, its storage boundary, its user-facing domain model,
and the reproducible demo used while real evaluation runs are not yet
available.

## Objective

Provide a passive CSR SPA that lets an operator inspect:

- the active benchmark dataset;
- tested Targets (machines) and their TargetRuns;
- Trials and the artifacts materialized for each Trial;
- vulnerabilities classified as `identified`, `partial`, or `missed`;
- the Polyphemus version/environment identified by `eval_sha` plus
  `stack_fingerprint`.

The dashboard must remain useful before real results exist and must switch to
real data without changing the frontend contract.

## Domain model

```text
BenchmarkDataset
  -> Target
       -> TargetRun
            -> Trial
                 -> run-manifest.yaml
                 -> verdicts.yaml
                 -> diagnoses.yaml
                 -> evidence/

Trial -> VersionEnvironment(eval_sha, stack_fingerprint)
```

A TargetRun groups the configuration of one Target on one instance. A Trial is
one concrete execution within that group. `terminal` describes the technical
execution outcome; `availability` separately describes whether its materialized
artifacts are complete enough to project.

## Architecture

```text
materialized artifact store
  -> SnapshotSource
       -> GET /snapshot + GET /health
            -> EvalDataProvider
                 -> /eval CSR routes
```

The FastAPI application depends only on `SnapshotSource.snapshot()` and
`SnapshotSource.health()`. The default adapter reads the filesystem store from
`EVAL_ARTIFACT_STORE` at request time. A future REST, database, or object-store
adapter can replace it without changing the HTTP surface or the SPA.

The API is GET-only and deliberately exposes no OpenAPI/docs routes. The SPA
fetches one snapshot and shares it across nested routes; it performs no writes,
polling, or evaluation control.

## Authoritative store contract

The filesystem adapter reads only:

```text
<store>/<target_id>/<target_run_id>/<trial_id>/
```

Within that tree it recognizes:

- `run-manifest.yaml`: identity, phase pointers, terminal state, version and
  materialization metadata;
- `verdicts.yaml`: one stored row per assessment result, preserving
  `identified`, `partial`, and `missed`;
- `diagnoses.yaml`: one paired diagnosis for every `partial` or `missed`
  verdict;
- copied evidence-chain files referenced by the verdicts.

`_sync/`, `live/`, loose files, absolute paths, traversal references, URLs,
credentials, raw ground truth, and non-allowlisted fields are never projected.
A malformed or missing artifact degrades only its Trial and yields a safe reason
code instead of failing the whole snapshot.

## Snapshot semantics

The snapshot contains dataset identity, raw summaries, Targets, Trials,
versions, identified successes, degraded Trials, and deduplicated coverage.

- Raw Trial/Target counts preserve every verdict row.
- A success means exactly `identified`; `partial` is not a success.
- Vulnerability coverage deduplicates by `(target_id, vuln_id)` with precedence
  `identified > partial > missed`.
- A Target has identified findings when at least one of its projected verdicts
  is `identified`; this does not claim exploitation.
- A version is the pair `eval_sha + stack_fingerprint`; equal SHAs with
  different fingerprints remain separate environments.

## User experience

The route hierarchy mirrors the domain:

```text
/eval
/eval/datasets/:datasetId
/eval/targets/:targetId
/eval/trials/:targetId/:targetRunId/:trialId
/eval/trials/:targetId/:targetRunId/:trialId/manifest
/eval/trials/:targetId/:targetRunId/:trialId/verdicts
/eval/trials/:targetId/:targetRunId/:trialId/diagnoses
/eval/trials/:targetId/:targetRunId/:trialId/evidence
/eval/versions/:evalSha/:stackFingerprint
/eval/vulnerabilities
```

The dashboard leads with two coverage donuts: Targets with/without identified
findings and unique vulnerabilities found/not found. The Target page groups
Trials by TargetRun. The Trial page is an index of the four materialized
artifact classes; each opens a human-readable detail view. The verdict detail
preserves row order and duplicates exactly as stored, while the evidence index
may deduplicate safe references by vulnerability.

Every state is expressed in text rather than color alone. Breadcrumbs and real
routes support refresh, browser history, and direct sharing.

## Synthetic store

`python -m read_api.demo_data` produces deterministic, explicitly synthetic
data in the same self-contained layout as the real materializer. Complete demo
Trials use the production manifest builder, resolve every evidence-chain path,
and pass the production verdict and diagnosis readers. One intentionally broken
Trial injects `verdicts_missing` so the degraded UI remains testable; it is not
presented as the output of a successful materialization.

The expected demo snapshot is:

```text
summary:  targets=3 trials=5 identified=5 partial=2 missed=4 degraded=1
targets:  tested=3 with_identified=2 without_identified=1
coverage: total=9 found=5 not_found=4 partial=1
```

## Reviewer walkthrough

From the repository root, start Polyphemus plus the synthetic store, read API,
and dashboard with one command:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  -f eval/docker-compose.dashboard.yml up --build
```

Open:

- dashboard: <http://localhost:5173/eval>
- API health: <http://localhost:8090/health>
- API snapshot: <http://localhost:8090/snapshot>

Useful Trial checks:

- full pipeline: <http://localhost:5173/eval/trials/comfyui-1/run-demo-a/trial-1>
- seeded hunting-only: <http://localhost:5173/eval/trials/comfyui-1/run-demo-a/trial-2>
- degraded/interrupted: <http://localhost:5173/eval/trials/white-jotter-1/run-demo-b/trial-2>

If the default ports are occupied:

```bash
EVAL_API_PORT=18090 EVAL_DASHBOARD_PORT=15173 \
  docker compose -f docker-compose.yml -f docker-compose.dev.yml \
    -f eval/docker-compose.dashboard.yml up --build
```

Then use `http://localhost:15173/eval` and port `18090` for the API.

Stop the demo and remove only its dedicated volumes:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  -f eval/docker-compose.dashboard.yml down -v
```

## Verification

```bash
PYTHONPATH=eval .venv/bin/python -m pytest \
  tests/eval/test_read_api_projection.py \
  tests/eval/test_read_api_demo_data.py \
  tests/eval/test_read_api_source.py \
  tests/eval/test_read_api_app.py \
  tests/eval/test_eval_overlay.py -q

cd frontend
npm test
npm run build
```

## Compatibility and non-goals

This change is additive: existing `/`, `/p/:id`, and `/p/:id/runs` routes and
the normal Compose startup remain unchanged. The dashboard does not launch or
control runs, expose raw evidence contents, add polling, or define the future
deployment adapter for a non-filesystem store.

When real runs arrive, the first integration step is to point
`EVAL_ARTIFACT_STORE` at their materialized store and validate `/health` plus
`/snapshot`. Only a schema or source change requires a new adapter; it must not
leak storage concerns into the SPA.
