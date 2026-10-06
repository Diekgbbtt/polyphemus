# polymerhus — platform stack

Autonomous vulnerability-discovery harness. Iteration 1 (recon MVP) substrate:
four containers the recon pipeline and documentation-ingestion subsystem run on.

## Prerequisites
All images build in-repo from Dockerfiles (`docker images` to check):
`polymerhus-agent:latest` (`Dockerfile`), `redamon-kali-sandbox:latest`
(`Dockerfile.kali`, slim recon-tools image), `polyphemus-ingestion:latest`
(`src/polymerhus/Dockerfile.ingestion`). The rest are pulled public images.

## Run
    cp .env.example .env
    docker compose up -d --build                # prod-ish
    # dev (agent hot-reload + live source):
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

Services: agent `:8080/health` · kali fastmcp `:8000/mcp` · neo4j `:7474`/`:7687` (neo4j/polymerhus) · postgres `:5432`.

## Verify

Tests are tiered. Full reference: `docs/design/testing-strategy.md`.

    # UNIT tier - needs nothing running. Must never touch a real database
    # (enforced: tests/conftest.py raises on any live Neo4j access).
    .venv/bin/python -m pytest tests/ -q

    # INTEGRATION / E2E tier - run INSIDE the compose network, so it resolves
    # `neo4j` by service DNS exactly as the agent does.
    docker compose -f docker-compose.yml -f docker-compose.dev.yml \
      run --rm tests tests/integration -q

    .venv/bin/python -m pytest tests/e2e/ -q   # deep e2e + observability

Expected (2026-07-22): unit tier 892 passed / 37 skipped / 0 failed; in-network
integration 41 passed / 0 skipped.

Note `tests/e2e/test_stack_smoke.py` runs `docker compose up -d --build`, so a
plain suite run rebuilds your stack - do not run it concurrently with an
in-network run.

`tests/e2e/` covers real work + failure paths: a live jsluice URL-extraction run,
idempotent neo4j MERGE, pgvector cosine search, checkpoint persistence, and the
observability paths (a degraded backend is reported *and diagnosed*, exec failures
surface returncode/stderr/timeout).

`GET /health` returns `{"status":"ok","checks":{...},"errors":{}}` when healthy; on a
degraded backend, `status` is `degraded`, its check is `false`, and `errors.<backend>`
carries the reason (e.g. connection refused).

## Reload during dev
- agent: automatic (`uvicorn --reload`).
- kali MCP server / gap-fill: `docker restart kali`.
- schemas: neo4j re-applied by the agent on reload; postgres `init.sql` re-runs only on `down -v`.

## Schemas
- Neo4j Layer-0 constraints: `db/neo4j/schema.py` (applied by the agent at startup).
- Postgres app + `doc_chunks` corpus: `db/postgres/init.sql` (first DB init).
- LangGraph checkpoints: `AsyncPostgresSaver.setup()` at agent startup.

## Kali recon tools
`Dockerfile.kali` bakes the ProjectDiscovery suite (subfinder/dnsx/naabu/httpx/katana incl. the main-branch `-pcs` flags/ffuf) + arjun/paramspider/masscan/nmap/subzy/jsluice/whois/openvpn into the image; `kali/postrun.sh`
gap-fills massdns/puredns/whois/graphql-cop/kiterunner into a persisted volume on first `up`.

## Launching a recon run

### Interfaces

The agent REST API (`:8080`) is the only interface that can create projects, configure a
target, and launch a run.
Everything is plain JSON over HTTP, so `curl`, the Python client, or any HTTP tool works.

    POST   /projects                          # {name} -> {project_id}
    GET    /projects                           # -> {projects: [...]}
    PUT    /projects/{id}/settings              # {recon: {target_domain, ...}} -> {ok}
    POST   /projects/{id}/recon                 # {jobs?: [...]} -> {run_id}
    GET    /projects/{id}/recon/{run_id}        # -> {status, current_phase, per_job}
    GET    /runs?status=running                 # -> {runs: [...], liveness_ttl_seconds}
    GET    /projects/{id}/graph                 # -> {nodes, links} (reads Neo4j live)

The frontend (`cd frontend && npm run dev`, default `:5173`) is a read-only viewer.
It proxies `/projects` and `/runs` to the agent (`vite.config.ts`, override the target with
`AGENT_PROXY_TARGET`) and renders the projects list, the live graph, and running-run status.
It has no launch or settings form, so a run always starts through the API above.

## Eval read API and the `/eval` page

The read-only eval viewer is a separate service that reads *only* the materialized
artifact store `<artifact_store>/<target_id>/<target_run_id>/<trial_id>/`. It takes
Target/TargetRun/Trial identity plus `eval_sha`/`stack_fingerprint` from each trial's
`run-manifest.yaml`, counts a success only for an `identified` verdict in
`verdicts.yaml`, and ignores `_sync/`, `live/`, and anything outside those trees. A
missing or malformed trial is reported as *degraded* (with no host paths) instead of
failing the whole report.

Internally the API depends only on a `SnapshotSource` protocol (`snapshot()` + `health()`):
`GET /snapshot` asks the source for the snapshot and `GET /health` asks it for its health,
nothing else. The default source, `ArtifactStoreSnapshotSource`, adapts the filesystem store
above, and `create_app()` accepts an injectable factory — so a future real source (REST,
database, …) can replace the store without touching the routes or the frontend. The
`EVAL_ARTIFACT_STORE`, `EVAL_DATASET_ID`, and `EVAL_DATASET_NAME` variables are read by the
filesystem factory at request time (never at import). An unconfigured source degrades
`/health` and makes `/snapshot` return a path-free `503`.

`/snapshot` is the SPA's single data contract. Additively to `dataset`, `summary`, `targets`,
`successes`, and `degraded_trials`, it carries:

- `trials` — every discovered trial with its manifest metadata (`instance_id`, `project_id`,
  `start_phase`, `terminal`, `copied_at`), its `phases` (`phase`, `status`, `run_id`), its
  `eval_sha`/`stack_fingerprint`, *every* verdict (`identified`/`partial`/`missed`) with its
  sanitized evidence references, the diagnoses paired to `partial`/`missed`, and an
  `availability` (`complete`/`degraded`) + safe `reason` code;
- `versions` — an aggregation per `eval_sha + stack_fingerprint` pair; the same `eval_sha`
  under a different fingerprint stays a distinct version;
- `identified`/`partial`/`missed` counts in the summary and on every Target.

`successes` stays identified-only. A diagnosis exposes only allowlisted fields (`vuln`,
`failure_mode`, `root_cause.type`/`combination_of`/`extended_description`,
`diagnosis_overview`, and one of the safe `closest_issue`/`proposed_issue` shapes); a defect
in the diagnoses or the evidence chain degrades that one trial, never the whole snapshot.
Evidence appears as plain relative, path-safe text references — no download links, no
absolute paths, traversal, credentials, ground truth, or file contents.

### The `/eval` pages

    /                                              the unified Target catalog
    /targets/:targetId                             one Target and every Trial, newest first
    /targets/:targetId/trials/:targetRunId/:trialId  one Trial workspace
    /targets/.../:trialId/artifacts/:artifactId    one resolved artifact (semantic / raw)

    /eval                                          dashboard (coverage donuts)
    /eval/datasets/:datasetId                      dataset and its Target roster
    /eval/versions/:evalSha/:stackFingerprint      results of one version + environment
    /eval/vulnerabilities                          identified vulnerabilities only

The `/eval/targets/...` and `/eval/trials/...` deep links stay valid for compatibility: they
redirect to the matching canonical `/targets/...` route, preserving the full Trial identity.

`EvalDataProvider` loads `/snapshot` once and shares loading/error/data across all of them
(no polling, no mutation). `target_id` is always visible and used as the stable identifier;
the UI labels it “Target (machine)” while `Target` stays the canonical term. Breadcrumbs and
cross-links keep browser back/forward and refresh working.

    # 1. serve the API against a store
    export EVAL_ARTIFACT_STORE=/srv/polymerhus/eval-artifacts
    cd eval && PYTHONPATH=. ../.venv/bin/python -m uvicorn read_api.app:app --port 8090
    # -> GET /snapshot  (dataset, targets, identified vulnerabilities, degraded trials)
    # -> GET /health    ({"status": "ok"|"degraded", ...}); no mutating routes exist

    # 2. run the frontend and open /eval
    cd frontend && npm run dev      # http://localhost:5173/eval

The page uses `VITE_EVAL_API_BASE_URL` (independent of `VITE_AGENT_BASE_URL`). In dev set it
to `/eval-api`, which Vite proxies to the eval service (`EVAL_PROXY_TARGET`, default
`http://localhost:8090`); in production point it at the service's full URL. The dataset is
fixed to `webexploitbench` / “WebExploitBench” and can be overridden with `EVAL_DATASET_ID` /
`EVAL_DATASET_NAME`.

The unified workspace needs three more read-only variables beside `EVAL_ARTIFACT_STORE`:

    EVAL_PROJECT_DATA_ROOT=/srv/eval-project-data      # the instance's raw Hunting/Skill tree
    EVAL_AGENT_BASE_URL=http://agent:8080              # current L0/L1 graph only
    EVAL_INSTANCE_ID=eval-server-1                     # gates fallback eligibility

All three are read at request time. `EVAL_PROJECT_DATA_ROOT` is mounted read-only; nothing in
the read API writes to it. `EVAL_AGENT_BASE_URL` is only ever queried for a Trial whose
`instance_id` equals `EVAL_INSTANCE_ID`.

The production overlay `eval/docker-compose.dashboard.real.yml` wires them for the eval server:

    EVAL_ARTIFACT_STORE_HOST_PATH=/srv/eval-artifacts \
    EVAL_PROJECT_DATA_ROOT_HOST_PATH=/opt/polymerhus-dev/eval/instances/data/eval-server-1 \
    EVAL_RUNS_ROOT_HOST_PATH=/opt/polymerhus-dev/eval/runs \
      docker compose -f docker-compose.yml -f docker-compose.dev.yml \
        -f eval/docker-compose.dashboard.real.yml \
        up -d --no-deps eval-api eval-dashboard

The command names the two dashboard services explicitly with `--no-deps`, so it never starts,
recreates or builds the agent, Neo4j, Postgres or the eval workers; both images are prebuilt, so
it needs no `--build`. Every source is a read-only bind that must already exist
(`bind.create_host_path: false`), so a missing or mistyped root fails loudly instead of silently
becoming an empty directory. The defaults are the instance's persistent project data root (the
driver's `EVAL_DATA_ROOT`), the materialized store, and the **primary** harness runs root
(`/opt/polymerhus-dev/eval/runs`) that holds the new Trials' records. All of them are read at
request time, so a new evaluation shows up on the next poll with no API restart.

Because nothing is auto-created, **verify that every host root exists before starting** (for
example `test -d /opt/polymerhus-dev/eval/runs`). A root that is still missing is a stop-and-
confirm: the driver creates its own runs root on its first run, and a mount must never be pointed
at a directory this dashboard would have to invent.

Historical Trials live in a second, **optional** runs root. A fresh install never needs it; a host
that still holds earlier records adds the companion overlay:

    EVAL_RUNS_LEGACY_ROOT_HOST_PATH=/opt/eval-platform-model/eval/runs \
      docker compose -f docker-compose.yml -f docker-compose.dev.yml \
        -f eval/docker-compose.dashboard.real.yml \
        -f eval/docker-compose.dashboard.legacy.yml \
        up -d --no-deps eval-api eval-dashboard

`EVAL_RUNS_LEGACY_ROOT_HOST_PATH` defaults to `/opt/eval-platform-model/eval/runs` and is mounted
read-only at `/srv/eval-runs-legacy`; the API reads it as `EVAL_RUNS_LEGACY_ROOT` beside
`EVAL_RUNS_ROOT`. The recorded-spend resolver searches both roots by the Trial's full identity: a
record that appears in two different roots is ambiguous (never chosen arbitrarily), and the same
root configured twice is read once.

Only `eval-api`/`eval-dashboard` are started; the agent, Neo4j, Postgres, and the eval workers are
untouched. On a headless server, reach the SPA through an SSH tunnel rather than exposing the
ports:

    ssh -L 5173:127.0.0.1:5173 -L 8090:127.0.0.1:8090 root@<eval-server>
    # then open http://localhost:5173/  (the Target catalog)

The expected `comfyui-1` Target lists all five of its Trials, each with its saved results,
resolved L0/L1 graph, and Hunting/Skill inventory; the three Trials with a live project graph
show it labelled **Saved for project**, and the two without one show `No graph available`.

### The project workspace (live + historical)

    /p/:projectId                                             live L0/L1 graph
    /p/:projectId/runs                                        operational recon runs
    /p/:projectId/evals                                       materialized eval Trials for the project
    /p/:projectId/evals/:targetId/:targetRunId/:trialId       one Trial's workspace
    /p/:projectId/evals/.../:trialId/artifacts                grouped Hunting/Skills inventory
    /p/:projectId/evals/.../:trialId/artifacts/:artifactId    one artifact (semantic / raw)

**Resolved data, not live data.** The Trial workspace reads one source-independent view:
`/trials/.../resolved-graph` and `/trials/.../resolved-artifacts`. The server prefers the
immutable graph and inventory a schema-v2 Trial captured before teardown. When a Trial has no
capture (the schema-v1 history), it falls back to the matching eval instance's *current* L0/L1
graph and to the allowlisted Hunting/Skill files under that instance's project data root — but
only when the Trial's `instance_id` equals `EVAL_INSTANCE_ID`. A Trial from another instance
never reads this server's project data. Every resolved response names its source:

- **Captured with Trial** — an immutable capture written beside the Trial (`trial_snapshot`);
- **Saved for project** — the matching instance's current project storage (`project_storage`).

A raw project directory that no projected Trial proves belongs to this instance appears only
under **Unassigned saved data** on the catalog, never attributed to an arbitrary Target. A
graph or artifact failure degrades only its own section; the identity, verdicts, and diagnoses
stay readable.

The live graph and run list (`/p/:projectId`, `/p/:projectId/runs`) keep reading the operational
agent API and polling while the stack is up; the Trial workspace never merges live data into a
historical capture.

`GET /health` distinguishes configuration, readability, and materialized Trials:

    {"status":"ok","store_configured":true,"store_readable":true,"materialized_trials":5}

`ok` requires a configured, readable store; a readable empty store is healthy and reports
`materialized_trials: 0`. A Trial materialized before the project snapshot existed (schema v1)
reports `project_artifacts_unavailable` and `project_graph_unavailable`; a schema-v2 Trial whose
graph/artifact capture could not publish a complete snapshot reports
`project_snapshot_unavailable`. In every case the core verdicts stay readable.

When configured, `/health` also reports the optional resolved sources without degrading:
`project_data_configured`, `project_data_readable`, and `graph_client_configured`.

### Synthetic demo store

To see the page without running real Trials, generate a fake store:

    PYTHONPATH=eval .venv/bin/python -m read_api.demo_data --output /tmp/polyphemus-eval-demo

The data is hand-written and **synthetic** (dataset WebExploitBench): it does **not**
represent real results, and contains no credentials or host paths. The generator is
deterministic and idempotent — it writes only the demo files it knows under the authoritative
layout and never removes or rewrites anything else in the output directory. Point `--output`
at a **fresh** directory: because it never deletes, an earlier run's files would otherwise
still be projected. The full flow:

    # 1. generate the store (command above)
    # 2. serve the API against it
    export EVAL_ARTIFACT_STORE=/tmp/polyphemus-eval-demo
    cd eval && PYTHONPATH=. ../.venv/bin/python -m uvicorn read_api.app:app --port 8090
    # 3. check it
    curl -s localhost:8090/health
    curl -s localhost:8090/snapshot
    # 4. run the frontend
    cd frontend && npm run dev      # VITE_EVAL_API_BASE_URL=/eval-api
    # 5. open it
    open http://localhost:5173/       # the Target catalog (`/targets/...` for one Target)

The corpus exercises the whole model **and** looks like a real materialized tree: every complete
trial's manifest is built by the production `orchestrator.store.build_run_manifest`, its
`chain_sources` list exactly the unique evidence references its verdicts name, and each
referenced hunt config, spec family, experiment log and pod export really exists under that
trial at the same relative paths `orchestrator.files` addresses — so `verdicts.yaml` and
`diagnoses.yaml` pass the production readers, pairing rule included.

The six trials are: `comfyui-1` (a full recon → analysis → hunting run with 2 identified + 1
partial, a seeded **hunting-only** run with 1 identified + 1 missed, and `run-demo-real-shape` — a
recon → hunting run stopped at the hunting cap with 3 missed verdicts — no evidence chain, since
it never reached assessment — and the recent real eval's 21-artifact hunting-only inventory: 10
consumed hunt configs, 5 test specs (2 produced / 3 consumed), 3 pod variants and 3 experiment
logs, with no pod exports and no skills), `jetlinks-1` (another full pipeline run, 2 identified +
1 missed), and
`white-jotter-1` (a resumed analysis → hunting run with 1 partial + 2 missed, plus the
deliberately broken trial below). One version+environment pair is shared across two Targets
(`demo-sha-a` + `demo-env-x`), the same `eval_sha` appears under a different fingerprint
(`demo-sha-a` + `demo-env-z`), and one Target carries two TargetRuns. Expected `/snapshot`
summary:

    {"targets": 3, "trials": 6, "identified": 5, "partial": 2, "missed": 7, "degraded": 1}

**`white-jotter-1/run-demo-b/trial-2` is intentional failure injection**, not the output of a
successful materialization: it models an interrupted run (`terminal: interrupted`) whose
`verdicts.yaml` was never written, so it carries a manifest and nothing else — no verdicts, no
diagnoses, no chain files. It exists only to keep the degraded path exercised; the other five
trials are valid, self-contained materializations.

The dashboard also reports deduplicated `coverage` (one entry per
`(target_id, vuln_id)`, precedence `identified > partial > missed`): targets
`{tested: 3, with_identified: 2, without_identified: 1}` and vulnerabilities
`{total: 12, found: 5, not_found: 7, partial: 1}` (partial is a subset of not_found).

#### One-command demo stack (Docker Compose)

`eval/docker-compose.dashboard.yml` is an overlay on top of the base + dev files, so the whole
demo — synthetic store, read API and dashboard — comes up beside the normal stack with one
command:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml \
      -f eval/docker-compose.dashboard.yml up --build

It adds three throwaway services on the base `polymerhus-net`: `eval-store` (one-shot, writes
the synthetic store into the dedicated `eval-dashboard-store` volume), `eval-api` (the read API
on `0.0.0.0:8090`, mounting that store **read-only**, started only after the generator
completes) and `eval-dashboard` (Vite on `0.0.0.0:5173`, started only after the API is healthy).

Then open **http://localhost:5173/** — the unified Target catalog; each Target opens its
workspace, and the coverage dashboard stays at `/eval`. The API is directly reachable at
`http://localhost:8090/health` (`{"status":"ok",…}`) and `http://localhost:8090/snapshot` (the
dataset, targets, trials, versions, coverage and identified vulnerabilities; expected summary
`{"targets":3,"trials":6,"identified":5,"partial":2,"missed":7,"degraded":1}`).

Both ports bind to loopback only and can be moved when they are taken:

    EVAL_API_PORT=18090 EVAL_DASHBOARD_PORT=15173 \
      docker compose -f docker-compose.yml -f docker-compose.dev.yml \
        -f eval/docker-compose.dashboard.yml up --build

Stop the demo — removing only its own volumes — with:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml \
      -f eval/docker-compose.dashboard.yml down -v

The synthetic store lives in its own named volume and is never the operator's
`EVAL_ARTIFACT_STORE`, so demo data cannot mix with a real artifact store; the services reuse the
`polymerhus-agent:latest` Python runtime plus a stock Node image, and no credential or host path
is baked into the overlay. Without the third `-f`, `docker compose up` is exactly what it was
before.

#### Storage-compatibility demo (the four persistent sources)

`docker-compose.storage-compat-demo.yml` is a **standalone** Compose project (its own project
name, network and volumes) that proves the dashboard end-to-end against the four sources the
read API now reads, without waiting for a real evaluation and without touching any real data:

    <root>/store        the materialized store       -> EVAL_ARTIFACT_STORE
    <root>/raw          the persistent project root  -> EVAL_PROJECT_DATA_ROOT
    <root>/runs         the primary runs root        -> EVAL_RUNS_ROOT
    <root>/runs-legacy  the historical runs root     -> EVAL_RUNS_LEGACY_ROOT

It starts exactly three services — `eval-corpus` (one-shot generator), `eval-api` (the read API)
and `eval-dashboard` (the unchanged production frontend) — and **never** the agent, Neo4j,
Postgres, Kali or an eval worker, and never mounts the real artifact store, raw data, benchmark
ground truth or Neo4j. The corpus is written by `eval/read_api/storage_compat_corpus.py`, which
reuses the production helpers (allowlist collection, graph capture, manifest building), so ids,
digests, counts and graph hashes are derived, never hand-authored.

Three cases ship in the corpus: a **complete** Trial (identified + partial + missed verdicts, a
captured L0/L1 graph, Hunting + Skill artifacts, linkable Evidence references and a recorded
spend from the primary root), an **interrupted** Trial (partial artifacts in the external raw
tree, no invented PodExport, `spent_tokens` absent rather than zero) and a **historical** Trial
(schema-v1 manifest in the legacy runs root, artifacts served from the raw fallback, no captured
graph). Every case's `verdicts.yaml` resolves through the production validator, so the historical
Trial's identified verdict carries a real Evidence chain (its variant, ExperimentLog and
PodExport). PodExport artifacts cover all six producer `terminal_reason` values, including the
`iterations: 0` / `clean: false` boundary. The dataset is clearly labelled synthetic
(`Synthetic — storage compatibility`).

Start it (both ports are loopback-only; reach the dashboard through an SSH tunnel):

    docker compose -f docker-compose.storage-compat-demo.yml up -d
    ssh -N -L 25173:127.0.0.1:25173 root@<host>
    # then open http://localhost:25173/

The API is at `127.0.0.1:28090` (`/health`, `/snapshot`); both published ports are configurable:

    STORAGE_COMPAT_API_PORT=38090 STORAGE_COMPAT_DASHBOARD_PORT=35173 \
      docker compose -f docker-compose.storage-compat-demo.yml up -d

To add new data **without restarting the API** (the frontend's own polling then sees it), run the
generator again as an explicit one-off — never a background timer. It adds one new materialized
Trial, one new allowlisted artifact in a partial Trial's raw tree, and one new/updated spend
record:

    docker compose -f docker-compose.storage-compat-demo.yml \
      run --rm eval-corpus python -m read_api.storage_compat_corpus \
      --root /srv/corpus --refresh

Stop it, removing only its own volumes:

    docker compose -f docker-compose.storage-compat-demo.yml down -v

The generator is deterministic and idempotent and only ever writes the four roots under the
volume it is given; it deletes nothing it did not write. Limits: operator ground truth and live
token usage are out of scope, this verifies integration/rendering rather than the real producer's
durability, and it cannot recover artifacts already deleted from a historical capture.

#### One-command real dashboard stack (Docker Compose)

`eval/docker-compose.dashboard.real.yml` serves the same dashboard from the **real** artifact
store instead of the synthetic demo. It adds only the read API and the Vite dashboard — no demo
generator — and binds the operator's store read-only:

    EVAL_ARTIFACT_STORE_HOST_PATH=/srv/eval-artifacts \
      docker compose -f docker-compose.yml -f docker-compose.dev.yml \
        -f eval/docker-compose.dashboard.real.yml \
        up -d --no-deps eval-api eval-dashboard

`EVAL_ARTIFACT_STORE_HOST_PATH` defaults to `/srv/eval-artifacts` and is mounted read-only at the
container's `/srv/eval-artifacts` (its `EVAL_ARTIFACT_STORE`). The overlay also binds the eval
instance's persistent project data root (`EVAL_PROJECT_DATA_ROOT_HOST_PATH`, default
`/opt/polymerhus-dev/eval/instances/data/eval-server-1`) and the primary harness runs root
(`EVAL_RUNS_ROOT_HOST_PATH`, default `/opt/polymerhus-dev/eval/runs`), both read-only; it never
mounts the raw `live/` mirror. Historical records come from the optional companion overlay
`eval/docker-compose.dashboard.legacy.yml` (see the section above). Every bind uses
`bind.create_host_path: false`, so a missing root is an error rather than an empty directory. Both
published ports are loopback-only and configurable (`EVAL_API_PORT`, `EVAL_DASHBOARD_PORT`).

`eval/docker-compose.dashboard.real.yml` interpolates `EVAL_RUNS_ROOT_HOST_PATH`. On the existing
eval server the dashboard env file (`.eval-dashboard.env`) still pins the **previous** value: a
shell export takes precedence over an env file, so pass the current paths explicitly on the
command line (as above) and leave that remote file untouched. Without the override the primary
runs mount would keep pointing at the old tree.

Open **http://localhost:5173/p** for the project hub and **http://localhost:5173/eval** for the
read-only eval pages; the API is reachable at `http://localhost:8090/health` and
`http://localhost:8090/snapshot`. This overlay reads completed Trials only — it is not live
monitoring. Stop just these two services with:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml \
      -f eval/docker-compose.dashboard.real.yml \
      stop eval-api eval-dashboard

#### Operator-only ground truth (separate API, second tunnel)

The reference shown beside each materialized verdict is **the current WebExploitBench checkout
ground truth**, not a capture saved with the Trial — the UI labels it `Ground truth (current
benchmark)`. It comes from its own opt-in service so the discovery agent has no route to it:

    # 1. check the host path first, from the repository root (never creates it,
    #    never changes directory)
    EVAL_WEB_DIR_HOST_PATH=/home/<operator>/WebExploitBench \
      PYTHONPATH=eval python -m operator_api.preflight

    # 2. start only the operator service and the dashboard beside them
    EVAL_WEB_DIR_HOST_PATH=/home/<operator>/WebExploitBench \
      docker compose -f docker-compose.yml -f docker-compose.dev.yml \
        -f eval/docker-compose.dashboard.real.yml \
        -f eval/docker-compose.dashboard.operator.yml \
        up -d --no-deps eval-operator-api eval-dashboard

`eval-operator-api` joins only its own bridge network (`eval-operator-net`), publishes
`127.0.0.1:8091` (`EVAL_OPERATOR_PORT`), and mounts the benchmark checkout and `./eval`
read-only. It is never on `polymerhus-net` and never bound to a public interface.
`EVAL_WEB_DIR_HOST_PATH` is **required and absolute**; a missing value fails the Compose render
and a wrong one fails the preflight, rather than mounting an empty directory. The approved
setup basenames come from `EVAL_OPERATOR_SETUP_FILES` (default
`first.yaml,webexploitbench-chain.yaml`), the only source of the
`target_id -> <dataset>/<target>` mapping — a target is never resolved by stripping an ID
suffix.

Open both forwards in one SSH command:

    ssh -N -L 15173:127.0.0.1:5173 -L 18091:127.0.0.1:8091 root@<eval-server>

The SPA is then at `http://localhost:15173/` and calls the operator API at
`http://localhost:18091/`. CORS allows exactly one origin, defaulting to
`http://localhost:15173` (`EVAL_OPERATOR_FRONTEND_ORIGIN`); the browser base defaults to
`http://localhost:18091` (`VITE_OPERATOR_GT_API_BASE_URL`). Changing the local forwarded ports
means changing both to match — the browser base accepts only a loopback `http(s)` URL.
Without the second forward the Trial page still shows its results, diagnoses, graph and
artifacts; only the ground-truth rows fall back to `Ground truth non disponibile`.

### Walkthrough

    # 1. create a project
    curl -s -X POST localhost:8080/projects -H 'Content-Type: application/json' \
      -d '{"name":"my-target"}'
    # -> {"project_id": "<id>"}

    # 2. point it at a target (see seed-host modes below)
    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' \
      -d '{"recon":{"target_domain":"www.example.com"}}'

    # 2.b. [OPTIONAL] feed an auth context (see "Project settings" below for the full shape)
    e.g. authn cookies:
    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' \
      -d '{"recon":{"auth_context":{"cookies":[{"name":"session","value":"..."}]}}}'
    # or an arbitrary auth header (header-agnostic: any non-reserved key is a request header):
    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' \
      -d '{"recon":{"auth_context":{"Authorization":"Bearer <token>"}}}'

    # 3. launch a run (omit "jobs" to run the full phase plan)
    curl -s -X POST localhost:8080/projects/<id>/recon -H 'Content-Type: application/json' -d '{}'
    # -> {"run_id": "<run_id>"}

    # 4. poll until status leaves "running"
    curl -s localhost:8080/projects/<id>/recon/<run_id>

    # 5. pull the mapped attack surface once complete
    curl -s localhost:8080/projects/<id>/graph -o graph.json

### Project settings

Settings are the `recon` object sent to `PUT /projects/{id}/settings` and persisted as the
`settings.recon` JSONB blob. Writes are a **recursive (deep) merge**, so a PUT that sets only
`auth_context` preserves a previously-set `target_domain`, and a PUT that sets only
`auth_context.credentials` preserves a previously-set `auth_context.cookies` (nested items are
independent at any depth; scalars and arrays like the cookies list are replaced wholesale).
Everything below is optional except `target_domain`, which a run requires (a targetless
`POST /recon` is rejected 400).

| Setting | Type | Purpose |
|---|---|---|
| `target_domain` | string | The recon target. `example.com` / `app.example.com` = exact host (discovery suppressed); `*.example.com` = wildcard/zone (subdomain discovery fans out). See "Exact vs wildcard seed hosts" below. **Required to launch.** |
| `auth_context` | object | Authentication material, threaded into every `use_auth` job (httpx, katana, ffuf, steel_crawl, arjun). **Header-agnostic:** besides the reserved structural keys below (`cookies`, `scope`, `credentials`), any other key is treated as an arbitrary HTTP request header. All sub-fields optional; omit `auth_context` entirely for an anonymous run. |
| `auth_context.cookies` | list of `{name, value}` | Session cookies. Joined into the `Cookie: k=v; k2=v2` header for the **request-based** tools, and injected into the Steel browser context for a **non-interactive** authenticated agentic crawl. Each entry may also carry optional `domain`/`path`. This is the one source of the `Cookie` header; a literal `Cookie` header key is rejected. |
| `auth_context.<Header-Name>` | string | Any other key is an **arbitrary request header** sent verbatim by the request-based tools, e.g. `"Authorization": "Bearer <token>"` or `"X-Api-Key": "<key>"`. Header names must be HTTP tokens (letters/digits/hyphen); values are non-empty strings with no CR/LF (header-injection guard). Applies to the request-based tools only (not the Steel browser context yet). |
| `auth_context.scope` | string | Optional auth scope hint. Reserved structural key, not sent as a header. |
| `auth_context.credentials` | object | **Autonomous agentic-crawl login (D23).** The Steel crawl agent logs itself in with these before crawling - the credentials channel drives the *agentic* crawl, while `cookies` drive the *request-based* tools. |
| `auth_context.credentials.username` | string | Login username/email. **Required** inside `credentials`. |
| `auth_context.credentials.password` | string | Login password. **Required** inside `credentials`. Sent to the target you authorize; may appear in the crawl LLM trace (accepted under the pen-test threat model). |
| `auth_context.credentials.login_url` | string | URL of the sign-in page to navigate to. **Required** inside `credentials`. May be a different origin than the target (e.g. `login.example.com`); login succeeds only if it yields an in-scope target session. |
| `auth_context.credentials.domain` | string | Optional. Restricts which target host the login is attempted against (else derived from `login_url`), so one app's credentials are not submitted to every host in a run. |
| `auth_context.credentials.username_selector` | string | Optional CSS selector override for the username field (else auto-detected). |
| `auth_context.credentials.password_selector` | string | Optional CSS selector override for the password field (else `input[type=password]`). |
| `auth_context.credentials.submit_selector` | string | Optional CSS selector override for the submit control (else the form's submit). |

Launch-time (not persisted, sent to `POST /projects/{id}/recon`):

| Field | Type | Purpose |
|---|---|---|
| `jobs` | list of strings | Optional job subset, e.g. `{"jobs": ["httpx", "naabu"]}`. Omit to run the full phase plan. Rejected 400 if a selected job's input type isn't produced by an earlier selected job. |

Example with credentials:

    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' -d '{
      "recon": {
        "target_domain": "*.example.com",
        "auth_context": {
          "cookies": [{"name": "session", "value": "..."}],
          "credentials": {
            "username": "user@example.com", "password": "...",
            "login_url": "https://login.example.com/", "domain": "example.com"
          }
        }
      }
    }'

> Note: deployment-level knobs (`MAX_PODS`, `MAX_JOB_ASSETS`, `CRAWL_*`, `STEEL_API_KEY`,
> `DISCORD_WEBHOOK_URL`, `LANGFUSE_*`, ...) are **environment variables**, not project settings -
> see `.env.example`. A `max_pods` key inside a project's `recon` blob is not read.

### Exact vs wildcard seed hosts

`target_domain` is parsed into a scope (`src/polymerhus/recon/control/scope.py`, decision D14) that decides
whether subdomain discovery runs at all:

| `target_domain` value        | mode       | seeded host          | subdomain discovery |
|-------------------------------|------------|-----------------------|----------------------|
| `*.example.com`               | `wildcard` | `example.com` (apex)  | runs (subfinder, amass, dnsx, puredns fan out across the zone) |
| `example.com`                 | `exact`    | `example.com`         | suppressed - recon stays confined to that single host |
| `app.example.com`             | `exact`    | `app.example.com`     | suppressed - recon stays confined to that single host |
| unset / empty                 | `exact`    | `example.com` (default placeholder) | suppressed |

In `exact` mode `subfinder`/`amass`/`dnsx`/`puredns` are dropped from the phase plan and the
seeded host is injected directly into the post-discovery input set, so `httpx`/`naabu` still
probe it (D11).
`subdomain_takeover` and the passive harvesters (`whois`, `paramspider`) are never gated
by scope mode, since they either take an out-of-scope asset as a parameter or don't enumerate
subdomains in the first place.
Use wildcard (`*.example.com`) when you want the whole zone fanned out, and an exact host when
you already know the target and want a fast, narrow run.

### Phases

Jobs run in ordered, gated phases (`src/polymerhus/recon/control/jobs.py`). A phase is a **hard barrier**: the next
phase does not start until every job in the current phase has finished. **Within a phase, jobs run
sequentially** (one at a time) - each job still fans its assets out across up to `MAX_PODS`
concurrent pods, but only one job's fan-out runs at once, so peak concurrency is bounded to a
single tool's `MAX_PODS` rather than `jobs x MAX_PODS` (the latter exhausted the agent's memory).

| Phase | Jobs | Produces |
|---|---|---|
| 0 | `subfinder`, `amass`†, `whois` | Subdomain, IP, Domain |
| 1 | `dnsx`, `puredns`, `subdomain_takeover` | IP, DNSRecord, Subdomain, ExternalDomain |
| 2 | `naabu` | IP, Port, Service |
| 3 | `httpx` | BaseURL, Endpoint, Technology, Certificate, Header (+ `profile`) |
| 4 | `katana`, `ffuf`, `paramspider`, `steel_crawl` | BaseURL, Endpoint, Parameter |
| 5 | `jsluice`◦ | Endpoint, Secret |
| 6 | `httpx_reprofile` | BaseURL, Endpoint, Technology, Certificate, Header (+ `profile`) |
| 7 | `kiterunner`◦ *(api enumeration)* | Endpoint |
| 8 | `arjun` | Parameter |
| 9 | `graphql-cop`◦ *(static api testing)* | Endpoint |

† `amass` is currently **deferred** (see Tool status below).  ◦ gated on an upstream attribute.

**Profile-based routing (data dependency).** Phase 3 `httpx` tags each BaseURL/Endpoint with a
`profile` - `webapp`, `restapi`, or `graphql_api` (path heuristic, `noise_filter.classify_profile`).
But the phase-4 crawlers (`katana`/`ffuf`) and `jsluice` (phase 5) mint **new** BaseURLs - notably
the JS-derived API hosts `jsluice` recovers from bundles - which `httpx` never probed and so carry
no `profile`. Phase 6 `httpx_reprofile` re-probes **every** BaseURL (idempotent over
already-profiled ones) and classifies it via the same `classify_profile` path, so the whole
discovered surface - not just `httpx`'s originals - is profiled before the API phases. The
API-surface tools are then **gated** and produce nothing unless a match was tagged: `kiterunner`
(phase 7, *api enumeration*) consumes only `restapi` BaseURLs, `graphql-cop` (phase 9, *static api
testing*) only `graphql_api`. `arjun` (phase 8) runs after api enumeration so it discovers
Parameters on the routes `kiterunner` just found as well as `jsluice`'s recovered Endpoints. These
gates are real data dependencies: withdraw the upstream producer/attribute and the gated tool has
an empty input set.

In `exact` scope mode, phases 0 and 1 shrink to just `whois` and `subdomain_takeover` - the rest of
the pipeline is unaffected.

### Tool status

The pipeline schedules 17 tools (`src/polymerhus/recon/control/jobs.py::JOBS`). `auth` tools receive the
`auth_context` cookies/headers; gated tools consume only a matching upstream asset.

| Tool | Phase | Status | Gating / notes |
|---|---|---|---|
| `subfinder` | 0 | active | subdomain discovery |
| `amass` | 0 | **deferred** | amass v4.2.0 removed the `-json` flag, so it currently degrades; fix pending |
| `whois` | 0 | active | registrant / nameservers |
| `dnsx` | 1 | active | DNS resolution |
| `puredns` | 1 | active | mass DNS resolution |
| `subdomain_takeover` | 1 | active | dangling-CNAME check |
| `naabu` | 2 | active | port scan |
| `httpx` | 3 | active · auth | HTTP probe; sets the `webapp`/`restapi`/`graphql_api` `profile` |
| `katana` | 4 | active · auth | crawler; mints the `.js`/`.mjs` Endpoints `jsluice` consumes |
| `ffuf` | 4 | active · auth | content discovery; rate-throttled under WAF steering |
| `paramspider` | 4 | active | passive URL/param harvest |
| `steel_crawl` | 4 | active · auth | agentic browser crawl (cookies + autonomous credentialed login) |
| `jsluice` | 5 | active | gated to `.js`/`.mjs` Endpoints; batched; JS URLs + secrets + sourcemaps |
| `httpx_reprofile` | 6 | active · auth | re-probes every BaseURL (incl. crawler/JS-minted) to assign `profile`; reuses the `httpx` parser |
| `kiterunner` | 7 | active · auth | *api enumeration*; gated to `profile == restapi` |
| `arjun` | 8 | active · auth | parameter discovery (after api enumeration, so it sees `kiterunner` routes) |
| `graphql-cop` | 9 | active · auth | *static api testing*; gated to `profile == graphql_api` |
| `gau` | - | **deferred** | passive URL harvest, withdrawn (D-gau, 2026-07-09); to be reintroduced behind a noise filter |
