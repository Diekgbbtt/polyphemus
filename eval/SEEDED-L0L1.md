# Seeding a trial's L0/L1 (the seeded hunting entry)

A trial normally creates a fresh project, applies settings, scaffolds the L1
skeleton, and runs recon and analysis before hunting.
For an e2e hunting trial that only needs the L0/L1 surface, you can instead
transfer a pre-recon'd project from a local stack onto the eval instance and
hunt directly against it.

Set `existing_project_id` on a `TargetRun` (or pass `--existing-project-id` /
`EVAL_EXISTING_PROJECT_ID`) and the trial:

- skips `POST /projects`, the settings PUT, the `AuthContext` PUT, and the L1
  scaffold (it makes no call that creates or mutates the project),
- asserts the project exists and that its L1 carries services (the hunting-entry
  predicate),
- places any pre-mined artifacts exactly as the normal path, and
- enters hunting with the configured cap.

`start_phase` must be `hunting` when `existing_project_id` is set (it defaults to
`hunting`); a contradictory explicit phase is rejected, and a missing project or
an L1 with zero services blocks the trial with a named reason. There is no
fallback to creating a new project.

The committed example is `eval/setups/comfyui-hunting.yaml`.

## The known-good local example

A local run of the `comfyui` challenge produced a usable surface:

| field | value |
|---|---|
| project id | `12da8565-a266-4610-9968-9ebfb86dd563` |
| project name | `comfyui-trial-1` |
| L0/L1 | L1 24 services / 8 systems |

The parameters below are written for the `eval-server-1` instance of
`eval/setups/comfyui-hunting.yaml`; the compose project is `ph-<short>`
(`ph-dd131acc` for `eval-server-1`) and the synthetic Host is
`t-<short>.target` (`t-1fc05262.target` for `eval-server-1/comfyui-1`).

## 1. Transfer the pg and neo4j data

Bring the instance stack up once so its volumes exist, then stop the data
services **without** removing the volumes:

```
# From the repo root, with the instance worktree at eval/instances/eval-server-1
PYTHONPATH=eval python3 -m orchestrator up eval/setups/comfyui-hunting.yaml
docker compose -p ph-dd131acc \
  -f docker-compose.yml -f docker-compose.dev.yml -f eval/docker-compose.eval.yml \
  -f eval/instances/eval-server-1/docker-compose.yml stop postgres neo4j
```

Two transfer methods are equivalent; pick one.

**A. Raw volume tar/untar** (copies the whole store byte for byte).
The volume names are `<compose-project>_pg-data` and `<compose-project>_neo4j-data`:

```
LOCAL_PG=$(docker volume ls -q | grep -E '_pg-data$')
LOCAL_NEO=$(docker volume ls -q | grep -E '_neo4j-data$')

docker run --rm -v "$LOCAL_PG":/from -v ph-dd131acc_pg-data:/to \
  busybox sh -c 'rm -rf /to/* && cd /from && tar cf - . | (cd /to && tar xf -)'
docker run --rm -v "$LOCAL_NEO":/from -v ph-dd131acc_neo4j-data:/to \
  busybox sh -c 'rm -rf /to/* && cd /from && tar cf - . | (cd /to && tar xf -)'
```

**B. Logical dumps** (portable across image versions).
`pg_dump` the project rows and take a neo4j store dump:

```
pg_dump -U polymerhus -d polymerhus -t projects -t settings \
  --data-only --column-inserts > /tmp/seeded-pg.sql
docker cp /tmp/seeded-pg.sql ph-dd131acc-postgres-1:/tmp/seeded-pg.sql
docker exec ph-dd131acc-postgres-1 \
  psql -U polymerhus -d polymerhus -f /tmp/seeded-pg.sql

# neo4j: stop, dump, copy back, start (neo4j-admin dump requires a stopped store)
docker exec ph-dd131acc-neo4j-1 \
  neo4j-admin database dump neo4j --to-path=/tmp
docker cp ph-dd131acc-neo4j-1:/tmp/neo4j.dump /tmp/neo4j.dump
docker cp /tmp/neo4j.dump ph-dd131acc-neo4j-1:/tmp/neo4j.dump
docker exec ph-dd131acc-neo4j-1 \
  neo4j-admin database load neo4j --from-path=/tmp --overwrite-destination=true
```

Start the data services again:

```
docker compose -p ph-dd131acc \
  -f docker-compose.yml -f docker-compose.dev.yml -f eval/docker-compose.eval.yml \
  -f eval/instances/eval-server-1/docker-compose.yml start postgres neo4j
```

## 2. Verify the project and its L1

**Postgres** - the project row and the settings blob the scope gate reads:

```
docker exec ph-dd131acc-postgres-1 psql -U polymerhus -d polymerhus -c \
  "SELECT project_id, name FROM projects WHERE project_id = '12da8565-a266-4610-9968-9ebfb86dd563';"
docker exec ph-dd131acc-postgres-1 psql -U polymerhus -d polymerhus -c \
  "SELECT project_id, recon FROM settings WHERE project_id = '12da8565-a266-4610-9968-9ebfb86dd563';"
```

**Neo4j** - the L1 node tally (services > 0 is the hunting-entry assertion):

```
docker exec ph-dd131acc-neo4j-1 cypher-shell -u neo4j -p polymerhus \
  "MATCH (n) WHERE n.project_id = '12da8565-a266-4610-9968-9ebfb86dd563' \
   RETURN labels(n) AS labels, count(*) AS count ORDER BY count DESC;"
```

## 3. Update the target_seed to this run's synthetic Host

The seeded trial does not PUT settings, so the project's `settings.target_seed`
must already be this run's synthetic Host; otherwise the pipeline routes by one
Host and scans by another. Compute the Host (`t-1fc05262.target` for
`eval-server-1/comfyui-1`) and update the setting in place:

```
docker exec ph-dd131acc-postgres-1 psql -U polymerhus -d polymerhus -c \
  "UPDATE settings SET recon = jsonb_set(recon, '{target_seed}', '\"t-1fc05262.target\"') \
   WHERE project_id = '12da8565-a266-4610-9968-9ebfb86dd563';"
```

Confirm it reads back before running the trial:

```
docker exec ph-dd131acc-postgres-1 psql -U polymerhus -d polymerhus -c \
  "SELECT recon->>'target_seed' FROM settings WHERE project_id = '12da8565-a266-4610-9968-9ebfb86dd563';"
```

## 4. Run the seeded trial

```
PYTHONPATH=eval python3 -m orchestrator trial \
  eval/setups/comfyui-hunting.yaml eval-server-1 comfyui-1 --dry-run   # inspect the plan
PYTHONPATH=eval python3 -m orchestrator trial \
  eval/setups/comfyui-hunting.yaml eval-server-1 comfyui-1
```

The dry run shows the `seeded project reuse` step and the hunting entry, with no
project creation and no scaffold.
The trial record (`trial.yaml`) names the reused `project_id` and carries
`seeded: true`.

## Caveats

- `orchestrator down` runs `docker compose down -v`, which deletes the instance's
  docker volumes (neo4j/pg). It does NOT remove the instance worktree or its
  data root - those survive every stop/drain and eval termination; only the
  operator-only `orchestrator worktree-remove` drops a worktree. Never `down -v`
  between the transfer and the trial; use `stop`/`start` or a plain
  `docker compose down` **without** `-v` if you need to recycle the stack.
- The seeded project must be unique within the setup: two targets naming the same
  `existing_project_id` fail validation.
- A seeded project is read-only to the trial. If the L1 is wrong, fix the source
  project and re-transfer; the trial will not scaffold or repair it.
