# Frontend BFF MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a minimal read-only frontend for the recon system: a project-select landing, a project attack-surface graph, and a live running-runs page, served by three new FastAPI read endpoints plus a reliable heartbeat/liveness model.

**Architecture:** The FastAPI agent owns all data access and gains three read endpoints (`GET /projects`, `GET /projects/{id}/graph`, `GET /runs?status=running`); the graph-read Cypher and its node/link formatter are colocated with the Neo4j write path so one module owns the label contract. A `last_heartbeat_at` column plus a periodic heartbeat tick, read-time liveness derivation, and a self-healing reaper make running-run tracking crash-safe. The frontend is a standalone Vite React SPA with a force-graph render that talks to the agent over `fetch`.

**Tech Stack:** Python 3 / FastAPI / psycopg (sync) / neo4j-driver (backend); Vite + React 19 + TypeScript + react-router-dom + react-force-graph-2d (frontend); pytest (backend tests, live-infra gated) + vitest (frontend tests).

**Design source:** `docs/design/frontend-bff-mvp-design.md` (authoritative). Companion: `docs/design/recon-pipeline-design.md`.

## Global Constraints

- No em dash anywhere; use a plain dash `-`. (User global instruction.)
- Commit messages must NOT add an agent co-author. One sentence per line in any Markdown you write.
- STRICT scope discipline: this branch has concurrent history; commit each task with EXPLICIT file paths, never `git add -A` / `git add .`.
- Backend DB access uses the existing sync `psycopg.connect(config.POSTGRES_DSN)` pattern in `agent/app/clients/pg.py` - do not introduce an async pool or an ORM.
- Neo4j writes/reads go only through `agent/app/clients/neo4j_client.py` (the single Layer-0 path). Do not open ad-hoc drivers elsewhere.
- The recon graph is `project_id`-keyed; every Cypher read MUST filter `project_id = $project_id`.
- Liveness constants: `LIVENESS_TTL_SECONDS = 30`, `HEARTBEAT_TICK_SECONDS = 10`, `REAP_TTL_SECONDS = 30`, `REAPER_SWEEP_SECONDS = 60`. The invariant `HEARTBEAT_TICK < LIVENESS_TTL <= REAP_TTL` must hold. Configure them in `agent/app/config.py`.
- No auth, no multi-tenancy, no writes from the frontend, no SSE/websockets, no Prisma, no Langfuse dependency.
- Frontend node/link contract (fixed for the whole plan): a node is `{ "id": str, "name": str, "type": str, "properties": object }`; a link is `{ "source": str, "target": str, "type": str }`.
- Run status vocabulary (existing): non-terminal `"running"`; terminal `"complete"`, `"failed"`. Job status vocabulary: `"in_progress"`, `"success"`, `"degraded"`, `"skipped"`, `"failed"`.
- Live infra is already up (postgres/neo4j/kali healthy). Live-infra tests gate on env presence and skip cleanly when absent, mirroring the existing gated recon tests.

---

## File Structure

Backend (Python):
- `db/postgres/init.sql` - add `recon_runs.last_heartbeat_at` + a `recon_runs(status)` index (idempotent).
- `agent/app/config.py` - add the four liveness/reaper/tick constants.
- `agent/app/clients/pg.py` - heartbeat write-points; new reads `list_projects`, `list_running_runs`; reaper `reap_stale_runs`; helper `touch_run_heartbeat`.
- `agent/app/clients/neo4j_client.py` - add a read helper `read(cypher, params) -> list[dict-ish]`.
- `agent/recon/graph_read.py` (new) - `fetch_project_graph(project_id, *, read_fn=None) -> dict` + pure formatter `format_graph_records(records) -> dict` + `node_name(labels, props) -> str`.
- `agent/recon/pipeline.py` - wrap the run in a periodic heartbeat tick task.
- `agent/app/routes.py` - three new GET endpoints.
- `agent/app/main.py` - reaper startup sweep + periodic reaper task via the lifespan/startup hook.

Frontend (Vite React SPA), all under new `frontend/`:
- `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/.env.example`.
- `frontend/src/main.tsx`, `frontend/src/App.tsx` (router), `frontend/src/api/client.ts`, `frontend/src/api/types.ts`.
- `frontend/src/graph/GraphCanvas.tsx`, `frontend/src/graph/colors.ts`, `frontend/src/graph/useGraphData.ts`.
- `frontend/src/pages/ProjectsPage.tsx`, `frontend/src/pages/GraphPage.tsx`, `frontend/src/pages/RunsPage.tsx`.

Tests:
- `tests/recon/test_graph_read.py`, `tests/app/test_pg_liveness.py`, `tests/app/test_reaper.py`, `tests/app/test_read_endpoints.py`, `tests/recon/test_pipeline_heartbeat.py`.
- `tests/integration/test_frontend_bff_integration.py` (live-infra gated, the exhaustive interface-agreement + exception suite).
- `frontend/src/**/*.test.tsx` (vitest).

---

## Task 1: Schema delta - heartbeat column + status index

**Files:**
- Modify: `db/postgres/init.sql`
- Test: `tests/app/test_pg_liveness.py`

**Interfaces:**
- Produces: `recon_runs.last_heartbeat_at TIMESTAMPTZ` (nullable) and index `recon_runs_status_idx`. Consumed by Tasks 2, 4, 5, 7.

- [ ] **Step 1: Write the failing test** (live-PG gated)

```python
# tests/app/test_pg_liveness.py
import os
import psycopg
import pytest

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set (live PG)")


def test_recon_runs_has_heartbeat_column_and_status_index():
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='recon_runs' AND column_name='last_heartbeat_at'"
        )
        assert cur.fetchone() is not None, "last_heartbeat_at column missing"
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='recon_runs_status_idx'")
        assert cur.fetchone() is not None, "recon_runs_status_idx missing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DSN="$(grep '^POSTGRES_DSN=' .env | cut -d= -f2-)" .venv/bin/python -m pytest tests/app/test_pg_liveness.py::test_recon_runs_has_heartbeat_column_and_status_index -v`
Expected: FAIL (column/index absent on the live DB).

- [ ] **Step 3: Add the idempotent DDL to `db/postgres/init.sql`**

Append after the `recon_runs` table definition (the DDL must be safe to re-run):

```sql
ALTER TABLE recon_runs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS recon_runs_status_idx ON recon_runs (status);
```

- [ ] **Step 4: Apply to the already-running live DB** (init.sql only runs on a fresh volume)

Run: `docker exec -i polymerhus-postgres-1 psql -U postgres -d polymerhus -c "ALTER TABLE recon_runs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ; CREATE INDEX IF NOT EXISTS recon_runs_status_idx ON recon_runs (status);"`
(Resolve the exact `-U`/`-d` from `.env` `POSTGRES_DSN` if they differ.)

- [ ] **Step 5: Run test to verify it passes**

Run: `POSTGRES_DSN="$(grep '^POSTGRES_DSN=' .env | cut -d= -f2-)" .venv/bin/python -m pytest tests/app/test_pg_liveness.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add db/postgres/init.sql tests/app/test_pg_liveness.py
git commit -m "feat(frontend-bff): add recon_runs.last_heartbeat_at + status index"
```

---

## Task 2: Heartbeat write-points + touch helper

**Files:**
- Modify: `agent/app/clients/pg.py:57-85` (`create_run`, `set_run_status`), `agent/app/clients/pg.py:132-152` (`upsert_job`)
- Test: `tests/app/test_pg_liveness.py`

**Interfaces:**
- Produces: `create_run`, `set_run_status`, `upsert_job` all bump `recon_runs.last_heartbeat_at = now()`; new `touch_run_heartbeat(run_id: str) -> None`. Consumed by Tasks 3, 4.
- Consumes: Task 1 schema.

- [ ] **Step 1: Write the failing test** (append to `tests/app/test_pg_liveness.py`)

```python
import uuid
from agent.app.clients import pg


def _mk_project_and_run():
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "hb-test")
    pg.create_run(rid, pid)
    return pid, rid


def test_create_run_sets_heartbeat():
    _, rid = _mk_project_and_run()
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT last_heartbeat_at FROM recon_runs WHERE run_id=%s", (rid,))
        assert cur.fetchone()[0] is not None


def test_touch_run_heartbeat_advances_it():
    _, rid = _mk_project_and_run()
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recon_runs SET last_heartbeat_at = now() - interval '5 minutes' "
            "WHERE run_id=%s", (rid,))
        conn.commit()
    pg.touch_run_heartbeat(rid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT now() - last_heartbeat_at FROM recon_runs WHERE run_id=%s", (rid,))
        assert cur.fetchone()[0].total_seconds() < 10
```

- [ ] **Step 2: Run to verify it fails**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_pg_liveness.py -v`
Expected: FAIL (`create_run` does not set heartbeat; `touch_run_heartbeat` undefined).

- [ ] **Step 3: Implement in `agent/app/clients/pg.py`**

Change `create_run`'s INSERT to include the heartbeat:

```python
        cur.execute(
            "INSERT INTO recon_runs (run_id, project_id, status, started_at, last_heartbeat_at) "
            "VALUES (%s, %s, %s, now(), now()) "
            "ON CONFLICT (run_id) DO NOTHING",
            (run_id, project_id, "running"),
        )
```

In `set_run_status`, add `last_heartbeat_at = now()` to BOTH branches' `SET` lists (terminal and non-terminal). Add to `upsert_job` a heartbeat bump on the parent run right after its INSERT (same connection):

```python
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() WHERE run_id = %s", (run_id,))
```

Add the helper:

```python
def touch_run_heartbeat(run_id: str) -> None:
    """Bump last_heartbeat_at to now() to prove the run's process is alive."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() WHERE run_id = %s", (run_id,))
```

- [ ] **Step 4: Run to verify it passes**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_pg_liveness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/app/clients/pg.py tests/app/test_pg_liveness.py
git commit -m "feat(frontend-bff): bump run heartbeat on create/status/job writes"
```

---

## Task 3: Periodic heartbeat tick in run_pipeline

**Files:**
- Modify: `agent/recon/pipeline.py:68-172`
- Test: `tests/recon/test_pipeline_heartbeat.py`

**Interfaces:**
- Consumes: `pg.touch_run_heartbeat` (Task 2), `config.HEARTBEAT_TICK_SECONDS` (Task 7 adds it; add it here if not yet present).
- Produces: while `run_pipeline` runs, `last_heartbeat_at` is refreshed at least every `HEARTBEAT_TICK_SECONDS`, and the tick task is cancelled at the terminal `set_run_status`.

- [ ] **Step 1: Add the constant to `agent/app/config.py`** (idempotent with Task 7)

```python
    HEARTBEAT_TICK_SECONDS = int(os.environ.get("HEARTBEAT_TICK_SECONDS", "10"))
```

- [ ] **Step 2: Write the failing test**

```python
# tests/recon/test_pipeline_heartbeat.py
import asyncio
import pytest
from agent.recon import pipeline


@pytest.mark.asyncio
async def test_heartbeat_tick_fires_and_is_cancelled(monkeypatch):
    ticks = []

    class Reg:
        def create_run(self, *a, **k): pass
        def upsert_job(self, *a, **k): pass
        def set_run_status(self, *a, **k): pass

    monkeypatch.setattr(pipeline.config, "HEARTBEAT_TICK_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda rid: ticks.append(rid))

    async def fake_run_job(job, assets, **k):
        await asyncio.sleep(0.05)  # a slow single job with no registry writes
        return []

    await pipeline.run_pipeline(
        "proj", run_id="r1", job_subset=["subfinder"],
        run_job=fake_run_job, load_settings=lambda p: {}, registry=Reg(),
        read_assets=lambda t, p: [],
    )
    assert ticks, "heartbeat tick never fired during a slow job"
    await asyncio.sleep(0.03)
    n = len(ticks)
    await asyncio.sleep(0.05)
    assert len(ticks) == n, "heartbeat tick was not cancelled after the run finished"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/recon/test_pipeline_heartbeat.py -v`
Expected: FAIL (`_touch_heartbeat` undefined; no tick).

- [ ] **Step 4: Implement the tick in `agent/recon/pipeline.py`**

Add a module-level seam and wrap the phase loop. Near the imports add:

```python
from agent.app.config import config
from agent.app.clients.pg import touch_run_heartbeat as _touch_heartbeat


async def _heartbeat_loop(run_id: str) -> None:
    """Refresh the run heartbeat every HEARTBEAT_TICK_SECONDS until cancelled."""
    try:
        while True:
            await asyncio.sleep(config.HEARTBEAT_TICK_SECONDS)
            try:
                _touch_heartbeat(run_id)
            except Exception:  # best-effort; a heartbeat blip must not crash the run
                logger.warning("heartbeat tick failed for run %s", run_id, exc_info=True)
    except asyncio.CancelledError:
        return
```

Wrap the existing phase loop + terminal status. Replace the body from `registry.create_run(run_id, project_id)` through `registry.set_run_status(run_id, "complete")` so the phase loop runs under a started tick, and cancel it in a `finally`:

```python
    registry.create_run(run_id, project_id)
    hb = asyncio.create_task(_heartbeat_loop(run_id))
    try:
        for phase_idx, phase_jobs in enumerate(plan):
            ...  # existing per-phase body unchanged
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
    registry.set_run_status(run_id, "complete")
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/recon/test_pipeline_heartbeat.py -v`
Expected: PASS.

- [ ] **Step 6: Run the recon suite to confirm no regression**

Run: `.venv/bin/python -m pytest tests/recon -q`
Expected: all pass/skip as before.

- [ ] **Step 7: Commit**

```bash
git add agent/recon/pipeline.py agent/app/config.py tests/recon/test_pipeline_heartbeat.py
git commit -m "feat(frontend-bff): periodic heartbeat tick for the life of a run"
```

---

## Task 4: Liveness read - list_running_runs with job counts

**Files:**
- Modify: `agent/app/clients/pg.py`
- Test: `tests/app/test_pg_liveness.py`

**Interfaces:**
- Produces: `list_running_runs() -> list[dict]`, each `{run_id, project_id, project_name, status, current_phase, started_at, last_heartbeat_at, jobs: {total,in_progress,success,degraded,skipped,failed}}`. Liveness is derived later at the endpoint (Task 7), NOT here. Consumed by Task 7.
- Consumes: Tasks 1-2.

- [ ] **Step 1: Write the failing test**

```python
def test_list_running_runs_includes_job_counts():
    pid, rid = _mk_project_and_run()
    pg.upsert_job(rid, 0, "subfinder", "success")
    pg.upsert_job(rid, 0, "amass", "in_progress")
    rows = [r for r in pg.list_running_runs() if r["run_id"] == rid]
    assert len(rows) == 1
    r = rows[0]
    assert r["project_name"] == "hb-test"
    assert r["jobs"]["success"] == 1 and r["jobs"]["in_progress"] == 1
    assert r["jobs"]["total"] == 2


def test_list_running_runs_excludes_terminal():
    pid, rid = _mk_project_and_run()
    pg.set_run_status(rid, "complete")
    assert all(r["run_id"] != rid for r in pg.list_running_runs())
```

- [ ] **Step 2: Run to verify it fails**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_pg_liveness.py -v`
Expected: FAIL (`list_running_runs` undefined).

- [ ] **Step 3: Implement in `agent/app/clients/pg.py`**

```python
_JOB_COUNT_KEYS = ("in_progress", "success", "degraded", "skipped", "failed")


def list_running_runs() -> list[dict]:
    """Return running runs joined to project name, each with per-status job counts.
    Liveness is NOT derived here (the endpoint does that with the TTL)."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT r.run_id, r.project_id, p.name, r.status, r.current_phase, "
            "r.started_at, r.last_heartbeat_at "
            "FROM recon_runs r JOIN projects p ON p.project_id = r.project_id "
            "WHERE r.status = 'running' ORDER BY r.started_at DESC NULLS LAST"
        )
        runs = cur.fetchall()
        cur.execute(
            "SELECT run_id, status, count(*) FROM recon_jobs "
            "WHERE run_id IN (SELECT run_id FROM recon_runs WHERE status='running') "
            "GROUP BY run_id, status"
        )
        counts: dict[str, dict[str, int]] = {}
        for run_id, status, n in cur.fetchall():
            counts.setdefault(run_id, {})[status] = n
    out = []
    for run_id, project_id, name, status, phase, started, hb in runs:
        c = counts.get(run_id, {})
        jobs = {k: int(c.get(k, 0)) for k in _JOB_COUNT_KEYS}
        jobs["total"] = sum(jobs.values())
        out.append({
            "run_id": run_id, "project_id": project_id, "project_name": name,
            "status": status, "current_phase": phase,
            "started_at": started, "last_heartbeat_at": hb, "jobs": jobs,
        })
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_pg_liveness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/app/clients/pg.py tests/app/test_pg_liveness.py
git commit -m "feat(frontend-bff): list_running_runs with per-status job counts"
```

---

## Task 5: Self-healing reaper

**Files:**
- Modify: `agent/app/clients/pg.py`, `agent/app/config.py`, `agent/app/main.py`
- Test: `tests/app/test_reaper.py`

**Interfaces:**
- Produces: `pg.reap_stale_runs(ttl_seconds: int) -> int` (flips stale `running` -> `failed`, returns count). A startup sweep + a periodic asyncio task in `main.py`.
- Consumes: Tasks 1-2.

- [ ] **Step 1: Add constants to `agent/app/config.py`**

```python
    REAP_TTL_SECONDS = int(os.environ.get("REAP_TTL_SECONDS", "30"))
    REAPER_SWEEP_SECONDS = int(os.environ.get("REAPER_SWEEP_SECONDS", "60"))
```

- [ ] **Step 2: Write the failing test** (live-PG gated)

```python
# tests/app/test_reaper.py
import os, uuid, psycopg, pytest
from agent.app.clients import pg

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set (live PG)")


def test_reap_flips_stale_running_to_failed():
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "reap-test")
    pg.create_run(rid, pid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,))
        conn.commit()
    reaped = pg.reap_stale_runs(30)
    assert reaped >= 1
    assert pg.get_run(rid)["status"] == "failed"
    assert pg.get_run(rid)["finished_at"] is not None


def test_reap_leaves_fresh_running_alone():
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "reap-test")
    pg.create_run(rid, pid)  # heartbeat = now()
    pg.reap_stale_runs(30)
    assert pg.get_run(rid)["status"] == "running"
```

- [ ] **Step 3: Run to verify it fails**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_reaper.py -v`
Expected: FAIL (`reap_stale_runs` undefined).

- [ ] **Step 4: Implement `reap_stale_runs` in `agent/app/clients/pg.py`**

```python
def reap_stale_runs(ttl_seconds: int) -> int:
    """Flip running runs whose heartbeat is older than ttl_seconds (or NULL)
    to failed, stamping finished_at. Returns the number reaped."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recon_runs SET status='failed', finished_at=now() "
            "WHERE status='running' AND "
            "(last_heartbeat_at IS NULL OR last_heartbeat_at <= now() - make_interval(secs => %s))",
            (ttl_seconds,),
        )
        return cur.rowcount
```

- [ ] **Step 5: Wire the reaper into `agent/app/main.py`**

Add to the existing `_startup` handler (after `ensure_checkpoint_tables`), plus a periodic task:

```python
import asyncio
from agent.app.config import config

@app.on_event("startup")
async def _startup():
    await pg.ensure_checkpoint_tables()
    neo4j_client.ensure_schema()
    validate_llm_config()
    pg.reap_stale_runs(config.REAP_TTL_SECONDS)  # sweep zombies left by a prior crash
    app.state.reaper_task = asyncio.create_task(_reaper_loop())


async def _reaper_loop():
    while True:
        await asyncio.sleep(config.REAPER_SWEEP_SECONDS)
        try:
            pg.reap_stale_runs(config.REAP_TTL_SECONDS)
        except Exception:
            logging.getLogger(__name__).warning("reaper sweep failed", exc_info=True)


@app.on_event("shutdown")
async def _shutdown():
    task = getattr(app.state, "reaper_task", None)
    if task:
        task.cancel()
```

- [ ] **Step 6: Run to verify it passes**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_reaper.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agent/app/clients/pg.py agent/app/config.py agent/app/main.py tests/app/test_reaper.py
git commit -m "feat(frontend-bff): self-healing reaper for stale running runs"
```

---

## Task 6: GET /projects + list_projects

**Files:**
- Modify: `agent/app/clients/pg.py`, `agent/app/routes.py`
- Test: `tests/app/test_read_endpoints.py`

**Interfaces:**
- Produces: `pg.list_projects() -> list[dict]` (`{project_id, name, created_at}`); `GET /projects -> {"projects": [...]}`.

- [ ] **Step 1: Write the failing test** (uses FastAPI TestClient; live-PG gated)

```python
# tests/app/test_read_endpoints.py
import os, uuid, pytest
from fastapi.testclient import TestClient

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set (live PG)")


@pytest.fixture(scope="module")
def client():
    from agent.app.main import app
    return TestClient(app)


def test_get_projects_lists_created_project(client):
    from agent.app.clients import pg
    pid = str(uuid.uuid4())
    pg.create_project(pid, "list-test")
    r = client.get("/projects")
    assert r.status_code == 200
    ids = [p["project_id"] for p in r.json()["projects"]]
    assert pid in ids
```

- [ ] **Step 2: Run to verify it fails**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py::test_get_projects_lists_created_project -v`
Expected: FAIL (404 - route missing).

- [ ] **Step 3: Implement `pg.list_projects`**

```python
def list_projects() -> list[dict]:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id, name, created_at FROM projects ORDER BY created_at DESC")
        return [{"project_id": r[0], "name": r[1], "created_at": r[2]} for r in cur.fetchall()]
```

- [ ] **Step 4: Add the route to `agent/app/routes.py`**

```python
@router.get("/projects")
def list_projects() -> dict:
    return {"projects": pg.list_projects()}
```

- [ ] **Step 5: Run to verify it passes**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py::test_get_projects_lists_created_project -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/app/clients/pg.py agent/app/routes.py tests/app/test_read_endpoints.py
git commit -m "feat(frontend-bff): GET /projects"
```

---

## Task 7: GET /runs?status=running with derived liveness

**Files:**
- Modify: `agent/app/config.py`, `agent/app/routes.py`
- Test: `tests/app/test_read_endpoints.py`

**Interfaces:**
- Produces: `GET /runs?status=running -> {"runs": [...], "liveness_ttl_seconds": int}` where each run carries a derived `liveness: "live"|"stalled"`. Unsupported `status` -> `400`.
- Consumes: `pg.list_running_runs` (Task 4), `config.LIVENESS_TTL_SECONDS`.

- [ ] **Step 1: Add the constant to `agent/app/config.py`**

```python
    LIVENESS_TTL_SECONDS = int(os.environ.get("LIVENESS_TTL_SECONDS", "30"))
```

- [ ] **Step 2: Write the failing tests**

```python
def test_get_runs_requires_running_status(client):
    assert client.get("/runs?status=complete").status_code == 400
    assert client.get("/runs").status_code == 400


def test_get_runs_marks_stalled(client):
    import psycopg
    from agent.app.clients import pg
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "live-test"); pg.create_run(rid, pid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,)); conn.commit()
    body = client.get("/runs?status=running").json()
    assert body["liveness_ttl_seconds"] == 30
    row = next(r for r in body["runs"] if r["run_id"] == rid)
    assert row["liveness"] == "stalled"


def test_get_runs_marks_live(client):
    from agent.app.clients import pg
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "live-test"); pg.create_run(rid, pid)  # heartbeat now()
    row = next(r for r in client.get("/runs?status=running").json()["runs"] if r["run_id"] == rid)
    assert row["liveness"] == "live"
```

- [ ] **Step 3: Run to verify they fail**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py -k runs -v`
Expected: FAIL (route missing).

- [ ] **Step 4: Implement the route in `agent/app/routes.py`**

Add imports `from datetime import datetime, timezone` and `from agent.app.config import config`, then:

```python
@router.get("/runs")
def list_runs(status: str | None = None) -> dict:
    if status != "running":
        raise HTTPException(status_code=400, detail="only status=running is supported")
    ttl = config.LIVENESS_TTL_SECONDS
    now = datetime.now(timezone.utc)
    runs = []
    for r in pg.list_running_runs():
        hb = r["last_heartbeat_at"]
        live = hb is not None and (now - hb).total_seconds() <= ttl
        runs.append({**r, "liveness": "live" if live else "stalled"})
    return {"runs": runs, "liveness_ttl_seconds": ttl}
```

- [ ] **Step 5: Run to verify they pass**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py -k runs -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/app/config.py agent/app/routes.py tests/app/test_read_endpoints.py
git commit -m "feat(frontend-bff): GET /runs?status=running with derived liveness"
```

---

## Task 8: Graph read helper + Python formatter (isolated nodes included)

**Files:**
- Create: `agent/recon/graph_read.py`
- Modify: `agent/app/clients/neo4j_client.py`
- Test: `tests/recon/test_graph_read.py`

**Interfaces:**
- Produces: `neo4j_client.read(cypher: str, params: dict) -> list[dict]`; `graph_read.format_graph_records(records: list[dict]) -> dict`; `graph_read.node_name(labels: list[str], props: dict) -> str`; `graph_read.fetch_project_graph(project_id: str, *, read_fn=None) -> dict`.
- The Cypher MUST include zero-degree (isolated) nodes - a freshly-seeded Domain with no relationships must appear.

- [ ] **Step 1: Write the failing pure-formatter test** (no infra)

```python
# tests/recon/test_graph_read.py
from agent.recon import graph_read


def test_format_builds_nodes_and_links():
    records = [
        {"n": {"element_id": "a", "labels": ["Domain"], "props": {"name": "acme.com"}},
         "m": {"element_id": "b", "labels": ["Subdomain"], "props": {"name": "api.acme.com"}},
         "rtype": "HAS_SUBDOMAIN", "s": "a", "t": "b"},
    ]
    out = graph_read.format_graph_records(records)
    ids = {n["id"] for n in out["nodes"]}
    assert ids == {"a", "b"}
    assert {"source": "a", "target": "b", "type": "HAS_SUBDOMAIN"} in out["links"]
    dom = next(n for n in out["nodes"] if n["id"] == "a")
    assert dom["type"] == "Domain" and dom["name"] == "acme.com"


def test_isolated_node_has_no_links_but_is_present():
    records = [{"n": {"element_id": "x", "labels": ["Domain"], "props": {"name": "lone.com"}},
               "m": None, "rtype": None, "s": None, "t": None}]
    out = graph_read.format_graph_records(records)
    assert [n["id"] for n in out["nodes"]] == ["x"]
    assert out["links"] == []


def test_observation_node_name_uses_macro_kind():
    assert graph_read.node_name(["Observation"], {"macro_kind": "Exposed Admin"}) == "Exposed Admin"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/recon/test_graph_read.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `agent/recon/graph_read.py`**

Implement a `getNodeName` label mapping, extended with an `Observation` case. The read shape uses one row per node with an OPTIONAL relationship so isolated nodes survive.

```python
"""Read + format the project attack-surface graph for the frontend.

Node/link shape matches the design contract: node {id,name,type,properties},
link {source,target,type}, with an added Observation case. The Cypher
(fetch_project_graph) uses OPTIONAL MATCH so
zero-degree nodes are still returned."""
from __future__ import annotations


def node_name(labels: list[str], props: dict) -> str:
    label = labels[0] if labels else "Unknown"
    p = props or {}
    if label == "Observation":
        return str(p.get("macro_kind") or p.get("severity") or "Observation")
    for key in ("name", "url", "path", "address", "value", "number"):
        if p.get(key) is not None:
            return str(p[key])
    return label


def format_graph_records(records: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    links: list[dict] = []

    def _register(node: dict | None) -> None:
        if not node:
            return
        nid = str(node["element_id"])
        if nid not in nodes:
            nodes[nid] = {
                "id": nid,
                "name": node_name(node.get("labels", []), node.get("props", {})),
                "type": (node.get("labels") or ["Unknown"])[0],
                "properties": dict(node.get("props", {})),
            }

    for rec in records:
        _register(rec.get("n"))
        _register(rec.get("m"))
        if rec.get("rtype") and rec.get("s") is not None and rec.get("t") is not None:
            links.append({"source": str(rec["s"]), "target": str(rec["t"]), "type": rec["rtype"]})

    return {"nodes": list(nodes.values()), "links": links}


_GRAPH_CYPHER = (
    "MATCH (n) WHERE n.project_id = $project_id "
    "OPTIONAL MATCH (n)-[r]->(m) WHERE m.project_id = $project_id "
    "RETURN n{.*, element_id: elementId(n), labels: labels(n)} AS n, "
    "CASE WHEN m IS NULL THEN NULL ELSE m{.*, element_id: elementId(m), labels: labels(m)} END AS m, "
    "type(r) AS rtype, elementId(n) AS s, elementId(m) AS t"
)


def fetch_project_graph(project_id: str, *, read_fn=None) -> dict:
    if read_fn is None:
        from agent.app.clients import neo4j_client
        read_fn = neo4j_client.read
    rows = read_fn(_GRAPH_CYPHER, {"project_id": project_id})
    # Normalize driver rows into the dict shape format_graph_records expects.
    records = []
    for row in rows:
        n = row["n"]; m = row["m"]
        records.append({
            "n": {"element_id": n["element_id"], "labels": n["labels"],
                  "props": {k: v for k, v in n.items() if k not in ("element_id", "labels")}},
            "m": None if m is None else {"element_id": m["element_id"], "labels": m["labels"],
                  "props": {k: v for k, v in m.items() if k not in ("element_id", "labels")}},
            "rtype": row["rtype"], "s": row["s"], "t": row["t"],
        })
    return format_graph_records(records)
```

- [ ] **Step 4: Add `read` to `agent/app/clients/neo4j_client.py`**

```python
def read(cypher: str, params: dict) -> list[dict]:
    """Read-only query helper; returns a list of plain dict rows."""
    with _driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]
```

- [ ] **Step 5: Run to verify the pure tests pass**

Run: `.venv/bin/python -m pytest tests/recon/test_graph_read.py -v`
Expected: PASS.

- [ ] **Step 6: Add a live-Neo4j gated test for isolated-node coverage**

```python
import os
import pytest

NEO = os.environ.get("NEO4J_URI")


@pytest.mark.skipif(not NEO, reason="NEO4J_URI not set (live neo4j)")
def test_fetch_project_graph_includes_isolated_seed():
    from agent.app.clients import neo4j_client
    pid = "graphtest-" + os.urandom(4).hex()
    neo4j_client.merge(
        "MERGE (n:Domain {name:$name, project_id:$pid})", {"name": "lone.example", "pid": pid})
    out = neo4j_client.__dict__  # ensure import side effects
    from agent.recon.graph_read import fetch_project_graph
    g = fetch_project_graph(pid)
    assert any(n["type"] == "Domain" and n["name"] == "lone.example" for n in g["nodes"])
```

- [ ] **Step 7: Run the gated test**

Run: `NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... .venv/bin/python -m pytest tests/recon/test_graph_read.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add agent/recon/graph_read.py agent/app/clients/neo4j_client.py tests/recon/test_graph_read.py
git commit -m "feat(frontend-bff): project graph read + formatter (isolated nodes included)"
```

---

## Task 9: GET /projects/{id}/graph

**Files:**
- Modify: `agent/app/routes.py`
- Test: `tests/app/test_read_endpoints.py`

**Interfaces:**
- Produces: `GET /projects/{project_id}/graph -> {"project_id", "nodes": [...], "links": [...]}`; `404` on unknown project.
- Consumes: `graph_read.fetch_project_graph` (Task 8), `pg.project_exists`.

- [ ] **Step 1: Write the failing tests**

```python
def test_graph_404_unknown_project(client):
    assert client.get("/projects/does-not-exist/graph").status_code == 404


def test_graph_shape_for_known_project(client):
    from agent.app.clients import pg
    pid = str(uuid.uuid4()); pg.create_project(pid, "graph-shape")
    r = client.get(f"/projects/{pid}/graph")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert isinstance(body["nodes"], list) and isinstance(body["links"], list)
```

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_DSN=... NEO4J_URI=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py -k graph -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Implement the route**

```python
from agent.recon.graph_read import fetch_project_graph

@router.get("/projects/{project_id}/graph")
def project_graph(project_id: str) -> dict:
    if not pg.project_exists(project_id):
        raise HTTPException(status_code=404, detail="unknown project")
    g = fetch_project_graph(project_id)
    return {"project_id": project_id, "nodes": g["nodes"], "links": g["links"]}
```

- [ ] **Step 4: Run to verify they pass**

Run: `POSTGRES_DSN=... NEO4J_URI=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py -k graph -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/app/routes.py tests/app/test_read_endpoints.py
git commit -m "feat(frontend-bff): GET /projects/{id}/graph"
```

---

## Task 10: Scaffold the Vite React SPA

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/.env.example`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/vite-env.d.ts`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: a buildable SPA with three routes wired to placeholder pages; `VITE_AGENT_BASE_URL` env var read once.

- [ ] **Step 1: Create `frontend/package.json`** (pin versions matching the lifted render)

```json
{
  "name": "polymerhus-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^19.2.0",
    "react-dom": "^19.2.0",
    "react-router-dom": "^7.1.0",
    "react-force-graph-2d": "^1.26.0"
  },
  "devDependencies": {
    "@testing-library/react": "^16.3.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "vitest": "^4.1.0"
  }
}
```

- [ ] **Step 2: Create config files**

`frontend/vite.config.ts`:

```typescript
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", globals: true },
})
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022", "module": "ESNext", "moduleResolution": "bundler",
    "jsx": "react-jsx", "strict": true, "skipLibCheck": true,
    "esModuleInterop": true, "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "types": ["vitest/globals"], "noEmit": true
  },
  "include": ["src"]
}
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><title>polymerhus recon</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

`frontend/.env.example`:

```
VITE_AGENT_BASE_URL=http://localhost:8000
```

`frontend/src/vite-env.d.ts`:

```typescript
/// <reference types="vite/client" />
```

- [ ] **Step 3: Create `frontend/src/App.tsx` and `frontend/src/main.tsx`**

`frontend/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom"
import { ProjectsPage } from "./pages/ProjectsPage"
import { GraphPage } from "./pages/GraphPage"
import { RunsPage } from "./pages/RunsPage"

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/p/:id" element={<GraphPage />} />
        <Route path="/p/:id/runs" element={<RunsPage />} />
      </Routes>
    </BrowserRouter>
  )
}
```

`frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { App } from "./App"

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>)
```

- [ ] **Step 4: Create placeholder pages so the build compiles**

Create `frontend/src/pages/ProjectsPage.tsx`, `GraphPage.tsx`, `RunsPage.tsx`, each exporting a named component returning a heading (real bodies land in Tasks 12-13):

```tsx
export function ProjectsPage() { return <h1>Projects</h1> }
```

(Repeat with `GraphPage` and `RunsPage`.)

- [ ] **Step 5: Write the smoke test `frontend/src/App.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react"
import { ProjectsPage } from "./pages/ProjectsPage"

test("projects page renders heading", () => {
  render(<ProjectsPage />)
  expect(screen.getByText("Projects")).toBeDefined()
})
```

- [ ] **Step 6: Install, build, test**

Run: `cd frontend && npm install && npm run build && npm test`
Expected: build succeeds; the smoke test passes.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/index.html frontend/.env.example frontend/src
git commit -m "feat(frontend-bff): scaffold Vite React SPA with three routes"
```

---

## Task 11: API client + types

**Files:**
- Create: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `getProjects()`, `getGraph(projectId)`, `getRunningRuns()` returning typed responses matching the backend JSON from Tasks 6, 7, 9.

- [ ] **Step 1: Write the failing test** (mock `fetch`)

```typescript
// frontend/src/api/client.test.ts
import { getProjects } from "./client"

test("getProjects unwraps the projects array", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ projects: [{ project_id: "p1", name: "x", created_at: "t" }] }),
      { status: 200 })) as typeof fetch
  const out = await getProjects()
  expect(out[0].project_id).toBe("p1")
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test -- client`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `frontend/src/api/types.ts`**

```typescript
export interface Project { project_id: string; name: string; created_at: string }
export interface GraphNode { id: string; name: string; type: string; properties: Record<string, unknown> }
export interface GraphLink { source: string; target: string; type: string }
export interface GraphData { project_id: string; nodes: GraphNode[]; links: GraphLink[] }
export interface JobCounts {
  total: number; in_progress: number; success: number; degraded: number; skipped: number; failed: number
}
export interface RunningRun {
  run_id: string; project_id: string; project_name: string; status: string
  liveness: "live" | "stalled"; current_phase: number | null
  started_at: string | null; last_heartbeat_at: string | null; jobs: JobCounts
}
export interface RunsResponse { runs: RunningRun[]; liveness_ttl_seconds: number }
```

- [ ] **Step 4: Implement `frontend/src/api/client.ts`**

```typescript
import type { Project, GraphData, RunsResponse } from "./types"

const BASE = import.meta.env.VITE_AGENT_BASE_URL ?? ""

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${path} -> ${res.status}`)
  return res.json() as Promise<T>
}

export async function getProjects(): Promise<Project[]> {
  return (await getJSON<{ projects: Project[] }>("/projects")).projects
}
export async function getGraph(projectId: string): Promise<GraphData> {
  return getJSON<GraphData>(`/projects/${projectId}/graph`)
}
export async function getRunningRuns(): Promise<RunsResponse> {
  return getJSON<RunsResponse>("/runs?status=running")
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npm test -- client`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api
git commit -m "feat(frontend-bff): typed API client for the three read endpoints"
```

---

## Task 12: Lift the force-graph render + adapt

**Files:**
- Create: `frontend/src/graph/colors.ts`, `frontend/src/graph/GraphCanvas.tsx`, `frontend/src/graph/useGraphData.ts`
- Test: `frontend/src/graph/useGraphData.test.tsx`

**Interfaces:**
- Produces: `<GraphCanvas nodes links />` rendering react-force-graph-2d; `useGraphData(projectId)` returning `{ data, loading, error }`.
- Consumes: `getGraph` (Task 11).

- [ ] **Step 1: Create `frontend/src/graph/colors.ts`** - define a `NODE_COLORS` map covering only polymerhus's labels, plus an `Observation` entry:

```typescript
export const NODE_COLORS: Record<string, string> = {
  Domain: "#1e3a8a", Subdomain: "#2563eb",
  IP: "#0d9488", Port: "#0e7490", Service: "#06b6d4", DNSRecord: "#164e63",
  BaseURL: "#6366f1", Endpoint: "#8b5cf6", Parameter: "#c026d3",
  Technology: "#22c55e", Certificate: "#d97706", Header: "#78716c",
  Secret: "#e11d48", ExternalDomain: "#8b8178", Traceroute: "#164e63",
  Observation: "#f59e0b",
  Default: "#6b7280",
}

export function nodeColor(type: string): string {
  return NODE_COLORS[type] ?? NODE_COLORS.Default
}
```

- [ ] **Step 2: Write the failing test for `useGraphData`**

```tsx
// frontend/src/graph/useGraphData.test.tsx
import { renderHook, waitFor } from "@testing-library/react"
import { useGraphData } from "./useGraphData"

test("useGraphData loads and exposes data", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ project_id: "p1", nodes: [{ id: "a", name: "acme", type: "Domain", properties: {} }], links: [] }),
      { status: 200 })) as typeof fetch
  const { result } = renderHook(() => useGraphData("p1"))
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.data?.nodes[0].id).toBe("a")
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npm test -- useGraphData`
Expected: FAIL (module missing).

- [ ] **Step 4: Implement `frontend/src/graph/useGraphData.ts`**

```tsx
import { useEffect, useState } from "react"
import { getGraph } from "../api/client"
import type { GraphData } from "../api/types"

export function useGraphData(projectId: string) {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setLoading(true)
    getGraph(projectId)
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e) => { if (alive) setError(String(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [projectId])
  return { data, loading, error }
}
```

- [ ] **Step 5: Implement `frontend/src/graph/GraphCanvas.tsx`**

A thin wrapper over `react-force-graph-2d` (the heavy render is the library; we only map colors and names). Keep node-label/color wiring minimal:

```tsx
import ForceGraph2D from "react-force-graph-2d"
import type { GraphNode, GraphLink } from "../api/types"
import { nodeColor } from "./colors"

export function GraphCanvas({ nodes, links }: { nodes: GraphNode[]; links: GraphLink[] }) {
  return (
    <ForceGraph2D
      graphData={{ nodes: nodes as object[], links: links as object[] }}
      nodeId="id"
      nodeLabel={(n: object) => `${(n as GraphNode).type}: ${(n as GraphNode).name}`}
      nodeColor={(n: object) => nodeColor((n as GraphNode).type)}
      linkLabel={(l: object) => (l as GraphLink).type}
    />
  )
}
```

- [ ] **Step 6: Run to verify the hook test passes**

Run: `cd frontend && npm test -- useGraphData`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/graph
git commit -m "feat(frontend-bff): lift force-graph render + graph data hook"
```

---

## Task 13: The three pages

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`, `frontend/src/pages/GraphPage.tsx`, `frontend/src/pages/RunsPage.tsx`
- Test: `frontend/src/pages/RunsPage.test.tsx`

**Interfaces:**
- Consumes: `getProjects`, `getRunningRuns` (Task 11), `useGraphData`, `GraphCanvas` (Task 12).
- Produces: project-select list linking to `/p/:id`; graph page rendering the canvas; runs page polling every 2500ms and rendering a live/stalled badge per run.

- [ ] **Step 1: Write the failing test for the runs page** (liveness badge + polling render)

```tsx
// frontend/src/pages/RunsPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Routes, Route } from "react-router-dom"
import { RunsPage } from "./RunsPage"

test("runs page shows a stalled badge", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ liveness_ttl_seconds: 30, runs: [
      { run_id: "r1", project_id: "p1", project_name: "acme", status: "running",
        liveness: "stalled", current_phase: 1, started_at: null, last_heartbeat_at: null,
        jobs: { total: 2, in_progress: 0, success: 1, degraded: 1, skipped: 0, failed: 0 } }] }),
      { status: 200 })) as typeof fetch
  render(<MemoryRouter initialEntries={["/p/p1/runs"]}>
    <Routes><Route path="/p/:id/runs" element={<RunsPage />} /></Routes></MemoryRouter>)
  await waitFor(() => expect(screen.getByText(/stalled/i)).toBeDefined())
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test -- RunsPage`
Expected: FAIL (placeholder page has no such content).

- [ ] **Step 3: Implement `ProjectsPage.tsx`**

```tsx
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getProjects } from "../api/client"
import type { Project } from "../api/types"

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getProjects().then(setProjects).catch((e) => setError(String(e))) }, [])
  if (error) return <p role="alert">Failed to load projects: {error}</p>
  return (
    <main>
      <h1>Projects</h1>
      <ul>{projects.map((p) => (
        <li key={p.project_id}><Link to={`/p/${p.project_id}`}>{p.name}</Link></li>
      ))}</ul>
    </main>
  )
}
```

- [ ] **Step 4: Implement `GraphPage.tsx`**

```tsx
import { Link, useParams } from "react-router-dom"
import { useGraphData } from "../graph/useGraphData"
import { GraphCanvas } from "../graph/GraphCanvas"

export function GraphPage() {
  const { id = "" } = useParams()
  const { data, loading, error } = useGraphData(id)
  return (
    <main>
      <header><Link to="/">back</Link> <Link to={`/p/${id}/runs`}>running runs</Link></header>
      {loading && <p>Loading graph...</p>}
      {error && <p role="alert">Graph error: {error}</p>}
      {data && data.nodes.length === 0 && <p>No assets yet for this project.</p>}
      {data && data.nodes.length > 0 && <GraphCanvas nodes={data.nodes} links={data.links} />}
    </main>
  )
}
```

- [ ] **Step 5: Implement `RunsPage.tsx`** (polls every 2500ms)

```tsx
import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getRunningRuns } from "../api/client"
import type { RunningRun } from "../api/types"

export function RunsPage() {
  const { id = "" } = useParams()
  const [runs, setRuns] = useState<RunningRun[]>([])
  useEffect(() => {
    let alive = true
    const tick = () => getRunningRuns().then((r) => { if (alive) setRuns(r.runs) }).catch(() => {})
    tick()
    const h = setInterval(tick, 2500)
    return () => { alive = false; clearInterval(h) }
  }, [])
  const mine = runs.filter((r) => r.project_id === id)
  return (
    <main>
      <header><Link to={`/p/${id}`}>back to graph</Link></header>
      <h1>Running recon runs</h1>
      {mine.length === 0 && <p>No running runs.</p>}
      <ul>{mine.map((r) => (
        <li key={r.run_id}>
          <span>{r.run_id.slice(0, 8)}</span>
          <span data-liveness={r.liveness}> [{r.liveness}]</span>
          <span> phase {r.current_phase ?? "-"} - {r.jobs.success}/{r.jobs.total} jobs</span>
        </li>
      ))}</ul>
    </main>
  )
}
```

- [ ] **Step 6: Run to verify the test passes + full frontend suite + build**

Run: `cd frontend && npm test && npm run build`
Expected: PASS + successful build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages
git commit -m "feat(frontend-bff): three pages (projects, graph, runs) with live polling"
```

---

## Task 14: Backend integration suite - interface agreements + exceptions

**Files:**
- Create: `tests/integration/test_frontend_bff_integration.py`
- Test: itself (live-infra gated: `POSTGRES_DSN` + `NEO4J_URI`)

**Interfaces:**
- Consumes: the full app via `TestClient` + real PG + real Neo4j. Verifies every endpoint's contract and every exception case in one place.

- [ ] **Step 1: Write the integration suite** (exhaustive, per the loop's mandate)

```python
# tests/integration/test_frontend_bff_integration.py
import os, uuid, psycopg, pytest
from fastapi.testclient import TestClient

DSN, NEO = os.environ.get("POSTGRES_DSN"), os.environ.get("NEO4J_URI")
pytestmark = pytest.mark.skipif(not (DSN and NEO), reason="live PG+Neo4j required")


@pytest.fixture(scope="module")
def client():
    from agent.app.main import app
    return TestClient(app)


def _seed_project(client):
    r = client.post("/projects", json={"name": "int-" + uuid.uuid4().hex[:6]})
    return r.json()["project_id"]


# --- GET /projects ---
def test_projects_contract(client):
    pid = _seed_project(client)
    body = client.get("/projects").json()
    assert "projects" in body
    p = next(p for p in body["projects"] if p["project_id"] == pid)
    assert set(p) == {"project_id", "name", "created_at"}


# --- GET /projects/{id}/graph ---
def test_graph_contract_and_isolated_node(client):
    pid = _seed_project(client)
    from agent.app.clients import neo4j_client
    neo4j_client.merge("MERGE (n:Domain {name:$n, project_id:$p})", {"n": "seed.example", "p": pid})
    body = client.get(f"/projects/{pid}/graph").json()
    assert body["project_id"] == pid
    for n in body["nodes"]:
        assert set(n) == {"id", "name", "type", "properties"}
    for l in body["links"]:
        assert set(l) == {"source", "target", "type"}
    assert any(n["type"] == "Domain" and n["name"] == "seed.example" for n in body["nodes"])


def test_graph_unknown_project_404(client):
    assert client.get("/projects/nope/graph").status_code == 404


# --- GET /runs ---
def test_runs_only_running(client):
    assert client.get("/runs").status_code == 400
    assert client.get("/runs?status=complete").status_code == 400
    ok = client.get("/runs?status=running")
    assert ok.status_code == 200 and "liveness_ttl_seconds" in ok.json()


def test_runs_live_then_stalled_then_reaped(client):
    from agent.app.clients import pg
    pid = _seed_project(client)
    rid = str(uuid.uuid4()); pg.create_run(rid, pid)
    live = next(r for r in client.get("/runs?status=running").json()["runs"] if r["run_id"] == rid)
    assert live["liveness"] == "live"
    assert set(live["jobs"]) == {"total", "in_progress", "success", "degraded", "skipped", "failed"}
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,)); conn.commit()
    stalled = next(r for r in client.get("/runs?status=running").json()["runs"] if r["run_id"] == rid)
    assert stalled["liveness"] == "stalled"
    assert pg.reap_stale_runs(30) >= 1
    assert all(r["run_id"] != rid for r in client.get("/runs?status=running").json()["runs"])
```

- [ ] **Step 2: Run the suite**

Run: `POSTGRES_DSN="$(grep '^POSTGRES_DSN=' .env | cut -d= -f2-)" NEO4J_URI="$(grep '^NEO4J_URI=' .env | cut -d= -f2-)" NEO4J_USER="$(grep '^NEO4J_USER=' .env | cut -d= -f2-)" NEO4J_PASSWORD="$(grep '^NEO4J_PASSWORD=' .env | cut -d= -f2-)" .venv/bin/python -m pytest tests/integration/test_frontend_bff_integration.py -v`
Expected: all PASS.

- [ ] **Step 3: Confirm the whole offline suite still green**

Run: `.venv/bin/python -m pytest tests/recon tests/app -q`
Expected: pass/skip, no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_frontend_bff_integration.py
git commit -m "test(frontend-bff): live integration suite - contracts + exception cases"
```

---

## Task 15: Serve the built SPA + CORS + docs

**Files:**
- Modify: `agent/app/main.py` (CORS for dev), `docs/design/frontend-bff-mvp-design.md` (resolve the §9 open items), `frontend/README.md` (new)
- Test: `tests/app/test_read_endpoints.py` (CORS preflight)

**Interfaces:**
- Produces: dev CORS allowing the SPA origin; a documented run recipe. Resolves the design doc's open items (static-serving strategy, Cypher helper home = `agent/recon/graph_read.py`, TTL config location).

- [ ] **Step 1: Write the failing CORS test**

```python
def test_cors_allows_spa_origin(client):
    r = client.options("/projects", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") in ("*", "http://localhost:5173")
```

- [ ] **Step 2: Run to verify it fails**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py -k cors -v`
Expected: FAIL (no CORS header).

- [ ] **Step 3: Add CORS to `agent/app/main.py`**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: Run to verify it passes**

Run: `POSTGRES_DSN=... .venv/bin/python -m pytest tests/app/test_read_endpoints.py -k cors -v`
Expected: PASS.

- [ ] **Step 5: Write `frontend/README.md`** documenting: `npm install`, `cp .env.example .env`, `npm run dev` (serves on :5173 against the agent on :8000), `npm run build` (static assets in `frontend/dist/`), and that production static-serving is deferred (dev uses the Vite server; a later task can add a FastAPI static mount).

- [ ] **Step 6: Update `docs/design/frontend-bff-mvp-design.md` §9** - mark resolved: Cypher helper home is `agent/recon/graph_read.py`; TTL/tick constants live in `agent/app/config.py`; migration is an idempotent `ALTER ... IF NOT EXISTS` in `db/postgres/init.sql` plus a one-off live-DB `ALTER`; static-serving stays dev-mode Vite for the MVP.

- [ ] **Step 7: Commit**

```bash
git add agent/app/main.py frontend/README.md docs/design/frontend-bff-mvp-design.md tests/app/test_read_endpoints.py
git commit -m "feat(frontend-bff): dev CORS + run docs + resolve design open items"
```

---

## Self-Review

**Spec coverage** (against `docs/design/frontend-bff-mvp-design.md`):
- 3 pages -> Tasks 10, 13. 3 endpoints -> Tasks 6, 7, 9. Graph adapter + Observation color -> Tasks 8, 12. `last_heartbeat_at` + write-points -> Tasks 1, 2. Periodic tick -> Task 3. Liveness derivation -> Task 7. Reaper -> Task 5. Polling -> Task 13. Isolated-node fix (controller addition) -> Task 8. CORS/static/docs (§9) -> Task 15. All design sections map to a task.

**Placeholder scan:** no TBD/TODO; every code step carries real code; file-lift steps name exact source paths and the exact adaptations.

**Type consistency:** the node/link shape `{id,name,type,properties}` / `{source,target,type}` is identical across `graph_read.format_graph_records` (Task 8), the endpoint (Task 9), the TS types (Task 11), and the render (Task 12). `list_running_runs` keys (Task 4) match the `RunningRun` TS type (Task 11) and the integration assertions (Task 14). Constants (`LIVENESS_TTL_SECONDS`, `HEARTBEAT_TICK_SECONDS`, `REAP_TTL_SECONDS`, `REAPER_SWEEP_SECONDS`) are defined once in `config.py` and referenced by Tasks 3, 5, 7.

**Known deferrals (not MVP-blocking):** production static-serving of `frontend/dist` behind the agent; a Langfuse per-run deep-link (needs a persisted trace id); tightening CORS for a real deployment origin.
