# Module restructure: `src/` layout + three-context split

Status: in progress (branch `refactor/src-layout-bounded-contexts`).
This is the plan of record for removing the top-level `agent/` package and realising the bounded contexts named in `CONTEXT-MAP.md` as physical modules.

## Motivation

The code carried one flat `agent/` package with `recon` as a catch-all: Layer-1 Analysis lived under `agent/recon/analysis/`, the operator-intent surface was scattered across `agent/app/routes.py` and `agent/app/clients/pg.py`, and recon mixed its orchestration (the pipeline control flow) with its domain model (the sole-writer and parsers) at one directory level.
The goal is deeper modules with slim interfaces (Ousterhout) mapped onto the bounded contexts the domain already names (`CONTEXT-MAP.md`).

## Target layout

```
src/polymerhus/
  app/                     generic composition root / infra (kept thin, §0)
    main.py  config.py
    clients/  kali_mcp.py  neo4j_client.py  pg.py   (single Postgres gateway)
    llm/      providers.py roles.py
    observability/ langfuse_tracing.py
  recon/                   Layer 0 bounded context (observed)
    __init__.py            slim entry point -> run_pipeline
    config.py              recon exec budgets (MAX_PODS, timeouts, crawl)
    control/               application/orchestration layer
        pipeline  jobs  job_agent  orchestrator_agent
        auth  batching  async_bridge  scope  steering  targeted
    domain/                the model + sole-writer (pure where possible)
        curator  types  findings  pod  graph_read
        selectors  noise_filter  skills  parsers/
    crawl/                 agentic crawl subpackage
  analysis/                Layer 1 bounded context (judged)
    (analyser_types anatomy bootstrap curation* delivery index_card
     l1_curator l1_inventory l1_read l1_types pod streaming sweep)
  project_management/      operator-intent surface (the future context, now minted)
    api.py                 project/settings/run endpoints (from app/routes.py)
    repository.py          operator use-cases over the pg gateway
```

## Context boundaries and the dependency direction

- **recon** is one bounded context with an explicit internal seam: a **control layer** (the impure orchestrators of CODING_STANDARD §3 - they decide *when/whether* to run) sits over a **domain layer** (the pure model and the sole-writer). `recon/__init__.py` exposes `run_pipeline` as the context's slim public interface.
- **analysis** consumes recon's published Layer-0 substrate. Its only structural tie to recon is the L0 vocabulary in `recon.domain.types` (the anti-corruption seam: judged nodes `MATCH` observed nodes, never `MERGE`). The recon->analysis edge is the single lazy `stream_analyser_step` import inside `pipeline`.
- **project_management** is the operator-intent surface. It **launches** recon (lazy import inside the endpoint, as `_launch_pipeline` already does) and reads/writes Project + settings + run-request state through the `app` Postgres gateway. It never sits under recon.
- **app** is generic supporting infrastructure - clients, llm, observability - kept thin (CODING_STANDARD §0). `app/clients/pg.py` remains the single thin Postgres gateway.

Resulting graph is acyclic:
`project_management -> {recon (lazy), app}`, `recon -> app`, `analysis -> {recon.types (ACL), app}`.

## The pg.py cut (why it is NOT split)

`pg.py` stays whole in `app/clients/`. Splitting the raw run/job SQL into `project_management` would invert or cycle the dependency arrow: recon's control layer writes run/job execution state (`set_run_status`, `upsert_job`, `touch_run_heartbeat`, `record_targeted_job`), while project_management launches recon. One thin gateway, consumed by both, keeps the graph acyclic and honours "persistence generic and kept thin" (§0).
`project_management/repository.py` is the operator **use-case** layer over that gateway (create/list projects, settings validate+save, launch run, list running / reap) - a deep module, not a raw-SQL copy.

## Entry points touched

- `pyproject.toml` (new): `[tool.pytest.ini_options] pythonpath = ["src"]`.
- `agent/Dockerfile` -> `src/polymerhus`, CMD `polymerhus.app.main:app`, `PYTHONPATH=/srv/src`.
- `docker-compose.yml` / `docker-compose.dev.yml`: build context + bind mounts + reload dir.
- `tests/`: import roots `agent.*` -> `polymerhus.*`. Test tree mirrors the contexts: `tests/analysis/` and `tests/project_management/` were extracted alongside `tests/recon/` and `tests/app/`. The parser `fixtures/` stay with the recon parser tests that load them; the pg-gateway tests (`test_pg_liveness`, `test_reaper`) stay in `tests/app/` since they exercise `app.clients.pg` directly, while the operator API/repository/auth-context tests (`test_rest_api`, `test_read_endpoints`, `test_auth_context`) moved to `tests/project_management/`.

## Docs kept current in the same change (CLAUDE.md rule)

`CONTEXT-MAP.md`, `recon/CONTEXT.md`, `analysis/CONTEXT.md`, a new `project_management/CONTEXT.md`, the `CODING_STANDARD.md` `path:line` citations, and the `CLAUDE.md` path references.
