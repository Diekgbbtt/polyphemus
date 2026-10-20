"""REST API for the operator-intent surface (design §10.5): project/settings
CRUD, non-blocking recon-run launch, and run-status polling.

This module is a thin HTTP adapter: every handler delegates to the
`repository` use-case layer and maps its domain errors onto status codes
(ProjectNotFound/RunNotFound -> 404, ValueError -> 400). The one piece of
orchestration that stays here is `_schedule_pipeline` - the fire-and-forget
seam that schedules `run_pipeline` through the module runtime and returns
immediately. It is a module-level seam so tests can monkeypatch it with a
recorder instead of exercising the real pipeline/DB/Kali/Neo4j stack.
"""
from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from polymerhus.analysis.scaffold import ScaffoldError
from polymerhus.app.auth.store import (
    AuthInvalidError,
    DuplicateIdentityError,
    StoreUnavailableError as AuthStoreUnavailableError,
)
from polymerhus.app.llm.skills import (
    SkillInvalidError,
    SkillTargetError,
    StoreUnavailableError as SkillStoreUnavailableError,
)
from polymerhus.project_management import repository
from polymerhus.project_management.data_dependencies import DataDependencyError
from polymerhus.project_management.repository import (
    BootstrapBlocked,
    L1PersistBlocked,
    ProjectNotFound,
    RunNotFound,
)
from polymerhus.recon.control.pipeline import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


def _runtime():
    """The active module control plane, if any (#121). When active, recon runs
    are registered runs of the recon module (schedule/cancel go through the
    runtime); the fallback path below is the pre-#121 behavior, preserved."""
    from polymerhus.app.runtime import get_active_runtime

    return get_active_runtime()


class ProjectCreate(BaseModel):
    name: str


class SettingsUpdate(BaseModel):
    recon: dict = {}


class ReconLaunch(BaseModel):
    jobs: list[str] | None = None
    settings: dict | None = None
    # #75: the recon endpoint is the COMBINED dispatch by default (recon + an
    # independent analysis consumer for the same run). Set false for the recon-ONLY
    # dispatch: recon pushes chunks to the run's FIFO and a later `POST /analysis`
    # drains them.
    with_analysis: bool = True


class AnalysisLaunch(BaseModel):
    """#75: start the analysis-only dispatch - a consumer that drains an existing
    run's FIFO. `run_id` is the recon run whose queue to drain."""

    run_id: str


class AuthSeed(BaseModel):
    """#220 T4: the operator seed body. Both sections are optional; each
    present section replaces the operator-owned state wholesale, absent
    sections are untouched. Fields stay `Any` so every shape violation flows
    to the use-case/store T1 seam and maps onto the 400 `auth_invalid`
    envelope (a `dict`-typed field would 422 at the FastAPI parse layer)."""

    overview: Any = None
    accounts: Any = None


class BootstrapLaunch(BaseModel):
    """Ingest the operator's knowledge base and bootstrap. `operator_kb` is optional:
    supply it to ingest-and-bootstrap in one call (the frontend's flow), or omit it to
    bootstrap from the KB already stored in the project's settings."""

    operator_kb: str | None = None


# The eval data-dependency placement endpoints are multipart/form-data: the
# `file` part (required, binary) carries the raw bytes; `fileName` is an
# optional multipart attribute carried for a natural content-type and NEVER used
# to build a path (the canonical destination is hardcoded server-side).


@router.post("/projects")
def create_project(body: ProjectCreate) -> dict:
    return {"project_id": repository.create_project(body.name)}


@router.get("/projects")
def list_projects() -> dict:
    return {"projects": repository.list_projects()}


@router.get("/projects/{project_id}/graph")
def project_graph(project_id: str) -> dict:
    try:
        return repository.project_graph(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")


@router.get("/runs")
def list_runs(status: str | None = None) -> dict:
    if status != "running":
        raise HTTPException(status_code=400, detail="only status=running is supported")
    return repository.running_runs()


@router.get("/app-state")
def get_app_state(project_id: str | None = None) -> dict:
    """Instance-wide running state: per-project in-flight runs plus the
    top-level idle flag. Read-only - no mutation surface. `project_id`
    narrows the scope (unknown -> 404); `idle` reflects the returned scope.

    Postgres fallback (same rows, for when this API is unreachable):

        SELECT 'recon' AS kind, run_id AS id, project_id
          FROM recon_runs WHERE status = 'running'
        UNION ALL
        SELECT 'analysis', analysis_run_id, project_id
          FROM analysis_runs WHERE status = 'draining'
        UNION ALL
        SELECT 'hunting', hunting_run_id, project_id
          FROM hunting_runs WHERE status = 'running';

    Idle iff the fallback returns no rows.
    """
    try:
        return repository.app_state(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")


@router.get("/projects/{project_id}/usage")
def get_project_usage(project_id: str) -> dict:
    """The project's cumulative token spend as a two-axis typed surface, read
    from the process-wide usage ledger: `context_tokens` (`cached` +
    `uncached`) and `generated_tokens` (`reasoning` + `visible`), plus the raw
    scalar `total_tokens`, the trial-budget scalar `capped_tokens` (generated +
    uncached = `total_tokens - cached`), the count of calls whose cache detail
    the provider never reported (`cache_detail_omitted`, N5 - it is what keeps a
    reported 0% cached share readable as "the provider did not say" rather than
    as "the provider measured a miss"), and a per-agent breakdown. Read-only, NO
    database access: the ledger read-throughs its durable per-project record
    (#326), so a stopped, restarted, or drained project still reports its spend,
    while an unknown/empty project returns zeros/empty and is never validated
    into a 404 - the eval harness queries only its own project and the ledger is
    the single source."""
    from polymerhus.app.llm.usage import usage_ledger

    return usage_ledger().snapshot(project_id)


@router.put("/projects/{project_id}/settings")
def update_settings(project_id: str, body: SettingsUpdate) -> dict:
    try:
        repository.save_project_settings(project_id, body.recon)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.put("/projects/{project_id}/auth")
def seed_auth(project_id: str, body: AuthSeed) -> dict:
    """#220 T4: the operator seed-replace face. Thin adapter: the use-case
    raises the domain errors, this maps them (unknown project -> 404, shape
    violation -> the 400 `auth_invalid` envelope naming the field). A shape
    violation lands nothing - the store validates both sections BEFORE any
    write. No conflict path exists: reseed replaces, never 409.
    A credential-identity collision (D220-11) is a HARD contract breach, not a
    recoverable shape violation: a seed re-using an existing account's
    credential username is the agent misunderstanding role assignment, so it
    refuses with 500 `duplicate_identity` and lands nothing."""
    try:
        repository.seed_project_auth(
            project_id, overview=body.overview, accounts=body.accounts
        )
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except DuplicateIdentityError as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "duplicate_identity", "detail": str(exc)},
        )
    except AuthInvalidError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "auth_invalid", "detail": str(exc)},
        )
    return {"ok": True}


@router.get("/projects/{project_id}/auth")
def read_auth(project_id: str) -> dict:
    """#220 T4: the operator state-read face - the full `{"overview",
    "accounts"}` state. An unseeded project reads back a valid empty state,
    never an error."""
    try:
        return repository.read_project_auth(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")


def _data_dependency_result(callable_, project_id: str, data: bytes):
    """Shared error mapping for the four data-dependency placement endpoints:
    unknown project -> 404; a malformed upload or a shape refusal -> 400 with the
    reported code; a credential-identity collision -> 500 `duplicate_identity`
    (the seed-face contract); an unavailable store -> 500. Every refusal lands
    nothing (the stores validate before writing)."""
    try:
        return callable_(project_id, data)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except DataDependencyError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": exc.code, "detail": exc.detail},
        )
    except DuplicateIdentityError as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "duplicate_identity", "detail": str(exc)},
        )
    except AuthInvalidError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "auth_invalid", "detail": str(exc)},
        )
    except SkillInvalidError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "skill_invalid", "detail": str(exc)},
        )
    except SkillTargetError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "skill_target", "detail": str(exc)},
        )
    except (AuthStoreUnavailableError, SkillStoreUnavailableError) as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "store_unavailable", "detail": str(exc)},
        )
    except ScaffoldError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "scaffold_invalid", "detail": str(exc)},
        )
    except L1PersistBlocked as exc:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "l1_persist_blocked", "detail": str(exc)},
        )


@router.post("/projects/{project_id}/data-dependencies/authn-skill")
def place_authn_skill(
    project_id: str,
    fileName: str = Form(""),
    file: UploadFile = File(...),
):
    """Place the pre-built project `authn` skill bundle by direct file write.

    `file` is a single `.tar.gz`/`.zip` archive of the bundle; it is unpacked
    into the canonical `<data_root>/<project_id>/skills/authn/` (SKILL.md plus
    its canonical references) - the exact path `SkillStore` resolves and the eval
    trial reads (`eval/orchestrator/files.py:authn_skill_path`). Traversal,
    absolute, and symlink members are refused. Non-idempotent: a re-post
    overwrites. `fileName` is ignored for path building. Replaces the obsolete
    inline-`TargetConfig.auth` delivery."""
    return _data_dependency_result(
        repository.write_authn_skill, project_id, file.file.read()
    )


@router.post("/projects/{project_id}/data-dependencies/auth-overview")
def place_auth_overview(
    project_id: str,
    fileName: str = Form(""),
    file: UploadFile = File(...),
):
    """Place the pre-built `auth/overview.yaml` (the AuthContext header) by direct
    file write. Validates through `records.validate_overview` and replaces the
    file wholesale - never a merge. `fileName` is ignored for path building.
    Replaces the obsolete `PUT /auth` seed of the operator section."""
    return _data_dependency_result(
        repository.write_auth_overview, project_id, file.file.read()
    )


@router.post("/projects/{project_id}/data-dependencies/auth-credentials")
def place_auth_credentials(
    project_id: str,
    fileName: str = Form(""),
    file: UploadFile = File(...),
):
    """Place the pre-built `auth/credentials.yaml` (the AuthContext accounts) by
    direct file write. Each account validates through `records.validate_account`
    and the file is replaced wholesale - never a merge. `fileName` is ignored for
    path building. Replaces the obsolete `PUT /auth` seed of the operator
    accounts."""
    return _data_dependency_result(
        repository.write_auth_credentials, project_id, file.file.read()
    )


@router.post("/projects/{project_id}/data-dependencies/l1")
def place_l1_surface(
    project_id: str,
    fileName: str = Form(""),
    file: UploadFile = File(...),
):
    """Persist the pre-built L1 surface directly into the knowledge graph.

    `file` carries the deterministic `operator_kb.md` content; it is projected
    through the SAME scaffold the eval already runs (`analysis/scaffold.py` ->
    `shells_to_batch` -> `l1_curate`), so no LLM call runs and no file is
    written. `fileName` is ignored for path building. Replaces the obsolete
    trial-side scaffold step."""
    return _data_dependency_result(
        repository.write_project_l1, project_id, file.file.read()
    )


# Strong references to in-flight pipeline tasks: the module runtime manager's
# per-module run registry (ModuleHandle._runs) holds them for the run's lifetime
# and unregisters at the terminal (`runtime.schedule` -> `_tracked` -> `finally`),
# so the API layer needs no task registry of its own (#122 full cut).


def _schedule_pipeline(project_id: str, run_id: str, jobs: list[str] | None,
                     *, with_analysis: bool = True) -> None:
    """Schedule `run_pipeline` as a fire-and-forget run of the recon module.

    The pipeline itself is best-effort for job/pod failures (design §10.6),
    but a launch/setup error (e.g. the task raising before it even reaches
    the first `await`) must still be logged rather than vanish silently.

    Since #122 every launch routes through the module runtime: the manager's
    per-module registry holds the strong task reference and gives the stop
    handler per-run_id cancellation. There is no create_task fallback.
    """
    if (runtime := _runtime()) is None:
        raise RuntimeError(
            "recon launch requires the module runtime; no manager is active"
        )

    # #328: a drain settles the recon module to `stopped` (terminal), which
    # `schedule` refuses. A launch is the operator's intent to run recon, so ask
    # the runtime to revive a stopped module before scheduling instead of
    # failing the trial on an admission refusal. A deliberate pause is left
    # alone (only the terminal `stopped` state is revived).
    #
    # #121: recon is a registered run of the recon module on the runtime's
    # worker loop; pause/drain/cancel of the recon module reach it here.
    # A paused/draining recon module refuses admission (#118) - map that to a
    # clean 503 so the caller reads *why* the launch was refused.
    #
    # The revive sits INSIDE the guard: `ensure_running` can itself raise
    # `RuntimeLoopNotRunning` in the shutdown window (the active runtime is
    # still published while its worker loop is already cleared), and that must
    # map to a 503, never escape as a 500.

    async def _run() -> None:
        try:
            await run_pipeline(project_id, run_id=run_id, job_subset=jobs,
                               with_analysis=with_analysis)
        except Exception:  # noqa: BLE001 - best-effort launch, must not crash the loop
            logger.exception("recon pipeline run %s (project %s) failed", run_id, project_id)

    try:
        runtime.ensure_running("recon")
        runtime.schedule("recon", _run(), name=run_id)
    except Exception as exc:  # noqa: BLE001 - re-raise non-admission via the helper
        _admission_refused_503(exc)


@router.post("/projects/{project_id}/recon")
async def launch_recon(project_id: str, body: ReconLaunch) -> dict:
    """The dispatcher's recon entrypoint (#75). COMBINED by default
    (`with_analysis=True`): starts recon AND the independent analysis consumer for
    the run. `with_analysis=false` is the recon-ONLY dispatch."""
    try:
        repository.validate_launch(project_id, body.jobs)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = repository.open_run(project_id)
    _schedule_pipeline(project_id, run_id, body.jobs, with_analysis=body.with_analysis)
    return {"run_id": run_id}


@router.post("/projects/{project_id}/recon/{run_id}/stop")
async def stop_recon(project_id: str, run_id: str) -> dict:
    """Stop recon ONLY (#75 D6): cancel the recon task. Its `finally` enqueues the
    terminal marker so the independent analysis consumer can still drain what was
    already pushed; analysis is never touched here. (The instant per-job kill +
    output suppression is #76.)

    The response acknowledges the cancel; the run row reaches its first-class
    `stopped` terminal promptly on the pipeline's cancellation path (#287), not
    after the reaper's TTL - so a deliberate stop is distinguishable from a crash
    and `GET /app-state` stops reporting the run as in-flight."""
    runtime = _runtime()
    if runtime is None:
        raise HTTPException(
            status_code=503, detail="module runtime is not active"
        )
    # #121: the recon module's registered run is hard-cancelled via the
    # runtime (call_soon_threadsafe(task.cancel) - the API thread never calls
    # task.cancel() directly on the worker loop's tasks).
    try:
        runtime.cancel_run("recon", run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="no running recon for that run_id") from exc
    # #326: flush the project's durable usage record at the stop boundary.
    from polymerhus.app.llm.usage import usage_ledger  # noqa: PLC0415

    await asyncio.to_thread(usage_ledger().flush, project_id)
    return {"run_id": run_id, "stopping": True}


@router.post("/projects/{project_id}/execution/stop")
async def stop_project_execution(project_id: str) -> dict:
    """Stop the WHOLE project execution: EVERY live run of the project, all run
    kinds at once.

    This is the ONE stop a token-budget or deadline monitor calls. It exists so the
    monitor never has to know which run kinds are live (a streamed or a batched
    analysis, a hunting run, or any combination) nor address each module's run id
    separately: the project's execution is the unit, exactly as its cumulative token
    spend is. It removes the per-kind stop branching from the monitor.

    Order is deliberate: the analysis leg runs FIRST, because a genuinely DRAINED
    analysis chains a new hunting run (`hunt_after_analysis`), so stopping it before
    it can drain is what prevents a fresh hunt from spawning behind the stop; the
    recon and hunting legs are hard cancels that follow.

    Idempotent and best-effort per leg: a project with nothing live returns empty
    `stopped` lists, and one already-terminal run never masks another (each stopped
    run id is reported in `stopped`, each leg failure in `errors`). The run rows
    reach their own first-class terminal (`stopped`) on each pipeline's cancellation
    path, never here."""
    from polymerhus.app.clients import pg

    stopped: dict[str, list[str]] = {"analysis": [], "recon": [], "hunting": []}
    errors: list[str] = []
    runtime = _runtime()

    for row in pg.list_running_analysis_runs():
        if row.get("project_id") != project_id:
            continue
        run_id = row["run_id"]
        try:
            from polymerhus.analysis.lifecycle import stop_analysis

            await stop_analysis(run_id)
            stopped["analysis"].append(run_id)
        except Exception as exc:  # noqa: BLE001 - one leg never masks another
            errors.append(f"analysis {run_id}: {exc}")

    for row in pg.list_running_runs():
        if row.get("project_id") != project_id:
            continue
        run_id = row["run_id"]
        try:
            if runtime is None:
                raise RuntimeError("module runtime is not active")
            runtime.cancel_run("recon", run_id)
            stopped["recon"].append(run_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"recon {run_id}: {exc}")

    for row in pg.list_running_hunting_runs():
        if row.get("project_id") != project_id:
            continue
        hunting_run_id = row["hunting_run_id"]
        try:
            from polymerhus.attack.hunting import runtime as hunting_runtime

            await hunting_runtime.stop_hunting(hunting_run_id)
            stopped["hunting"].append(hunting_run_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"hunting {hunting_run_id}: {exc}")

    return {"project_id": project_id, "stopped": stopped, "errors": errors}


@router.post("/projects/{project_id}/analysis")
async def launch_analysis(project_id: str, body: AnalysisLaunch) -> dict:
    """The dispatcher's analysis-ONLY entrypoint (#75): start a consumer that drains
    an existing run's FIFO. Also the RESUME path after a graceful stop (D7).

    The run must exist: starting a consumer for an unknown run_id would create a
    `draining` analysis run whose queue no recon will ever end - a zombie."""
    from polymerhus.app.clients import pg
    from polymerhus.analysis.lifecycle import start_analysis

    run = await asyncio.to_thread(pg.get_run, body.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run_id")

    try:
        analysis_run_id = start_analysis(project_id, body.run_id)
    except Exception as exc:  # noqa: BLE001 - map admission refusal, re-raise the rest
        _admission_refused_503(exc)
    if analysis_run_id is None:
        raise HTTPException(status_code=409, detail="analysis already running for that run_id")
    return {"run_id": body.run_id, "analysis_run_id": analysis_run_id}


@router.post("/projects/{project_id}/analysis/{run_id}/stop")
async def stop_analysis_run(project_id: str, run_id: str) -> dict:
    """Graceful stop of the analysis consumer (#75 D7): finish the in-flight chunk,
    consume no further, preserve the queue for a resume."""
    from polymerhus.analysis.lifecycle import stop_analysis

    await stop_analysis(run_id)
    # #326: flush the project's durable usage record at the stop boundary.
    from polymerhus.app.llm.usage import usage_ledger  # noqa: PLC0415

    await asyncio.to_thread(usage_ledger().flush, project_id)
    return {"run_id": run_id, "stopped": True}


@router.get("/projects/{project_id}/analysis/{run_id}")
async def get_analysis_status(project_id: str, run_id: str) -> dict:
    """The analysis run's own status row (#75), independent of the recon run."""
    from polymerhus.app.clients import pg

    row = await asyncio.to_thread(pg.get_analysis_run, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no analysis run for that run_id")
    return row


@router.post("/projects/{project_id}/bootstrap")
async def bootstrap_project(project_id: str, body: BootstrapLaunch) -> dict:
    """Ingest the operator KB and project it into the L1 Service skeleton.

    SYNCHRONOUS, unlike the recon launch: a bootstrap is two LLM calls whose RESULT
    (the skeleton counts, or the fail-closed block) is what the caller needs, and it
    has no per-job progress worth polling - so there is nothing a run row and a
    status endpoint would add over simply returning the outcome. The blocking work is
    offloaded to a worker thread so it never stalls the event loop.

    A fail-closed block is a 503, NOT a 200 with zero counts: the whole point of the
    signal is that the caller must not proceed to the analysis, and a success status
    would invite exactly that."""
    try:
        return await asyncio.to_thread(
            repository.bootstrap_project, project_id, body.operator_kb
        )
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BootstrapBlocked as exc:
        logger.warning("bootstrap blocked for project %s: %s", project_id, exc.reason)
        raise HTTPException(
            status_code=503,
            detail=f"bootstrap blocked, analysis must not proceed: {exc.reason}",
        ) from exc


@router.get("/projects/{project_id}/recon/{run_id}")
def get_recon_status(project_id: str, run_id: str) -> dict:
    try:
        return repository.recon_status(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="unknown run")


# --- #110: the three hunting seam endpoints (seam contract 3.3) -----------------

class HuntingLaunch(BaseModel):
    """The hunting launch body (#110).

    The caller-supplied candidate batch is RETIRED (T3 #376): a run's unit set is
    its INTAKE - the L1 inventory read at run start, ordered by live L1 edge
    count / aggregated endpoints / unit id and frozen for the run (S1 7.1-7.2) -
    so the pass has no wire input. The body stays as the endpoint's typed request
    shape (today it carries nothing) instead of being dropped: the launch
    contract is T5's, and what retired is the candidate path, not the launch.
    """


@router.post("/projects/{project_id}/hunting", status_code=201)
async def launch_hunting(project_id: str, body: HuntingLaunch) -> dict:
    """Launch a hunting run (seam 3.3): open the `hunting_runs` row `running`,
    schedule `start_hunting` onto the hunting loop via the marshalling harness,
    return `{hunting_run_id}`. The row opens HERE so the id exists the instant
    the POST returns and a follow-up GET never 404-races.

    At-most-once / one-live-run-per-project (spec #169 US10/13, ADR Q6; T5):
    the `hunting_runs` row IS the creation marker. The API-tier guard
    (`list_hunting_runs` for a live `running` row, point 2 of the ticket
    ruling) refuses a second/replayed launch with 409 Conflict BEFORE the new
    row opens - the per-project produced/consumed directories are single-owner
    (a terminal row never holds the guard; a relaunch is not a replay). A
    post-open refusal closes the orphan row to `failed` synchronously so no
    `running` row is ever left behind: an admission 503 closes HERE, and the
    bootstrap's own guard-refusal (a concurrent launch that slipped past) is
    closed in-band inside `start_hunting`.

    Fail-closed on the control plane: while `polymerhus.app.runtime` has not
    landed the launch is a 503, NOT an in-process run - a real orchestration
    pass (LLM turns) must never ride the uvicorn request loop."""
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime

    if not await asyncio.to_thread(pg.project_exists, project_id):
        raise HTTPException(status_code=404, detail="unknown project")
    if not hunting_runtime.hunting_control_plane_available():
        raise HTTPException(
            status_code=503,
            detail="hunting control-plane runtime has not landed",
        )
    await _hunting_live_run_guard(project_id)

    hunting_run_id = await asyncio.to_thread(pg.create_hunting_run, project_id)
    try:
        hunting_runtime.schedule_hunting(
            hunting_runtime.start_hunting(
                project_id, run_id=hunting_run_id,
            ),
            name=f"hunting:{hunting_run_id}",
        )
    except Exception as exc:  # noqa: BLE001 - map admission refusal, re-raise the rest
        # An admission refusal is a POST-OPEN refusal: the just-opened
        # `running` row must not be left behind as an orphan (at-most-once,
        # T5 ruling point 3). Close it to `failed` synchronously, then map.
        try:
            await asyncio.to_thread(
                pg.set_hunting_run_status, hunting_run_id, "failed"
            )
        except Exception:  # noqa: BLE001 - best-effort orphan close
            logger.warning(
                "launch_hunting: could not close the refused run row %s "
                "(fail-open)", hunting_run_id,
            )
        _admission_refused_503(exc)
    return {"hunting_run_id": hunting_run_id}


async def _hunting_live_run_guard(
    project_id: str, *, exclude_run_id: str | None = None
) -> None:
    """The API-tier ONE-live-run-per-project guard (T5, spec #169 US10 / ticket
    ruling point 2): refuse a launch while the project already holds a
    `running` hunting run - the per-project produced/consumed memory
    directories are single-owner, so two concurrent runs must never race them.

    The `hunting_runs` row read (`list_hunting_runs`) is the authority the API
    tier owns, checked BEFORE the new row opens so a refusal never leaves an
    orphan. The bootstrap's own guard is belt-and-braces (it excludes the
    run's own pinned row); this check prevents the orphan in the first place.
    `exclude_run_id` is the resume verb's own row: a claimed resume is `running`
    by construction, and only ANOTHER live run must refuse it.
    Fail-open: with pg unavailable the guard cannot fire and the launch
    proceeds (the row open would have failed too)."""
    from polymerhus.app.clients import pg

    try:
        rows = await asyncio.to_thread(pg.list_hunting_runs, project_id)
    except Exception as exc:  # noqa: BLE001 - fail-open: no pg, no guard
        logger.warning(
            "launch_hunting: live-run guard unavailable (%s); proceeding (fail-open)",
            exc,
        )
        return
    for row in rows:
        if (row.get("status") == "running"
                and row.get("hunting_run_id") != exclude_run_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    "a hunting run is already live for this project; "
                    "one live hunting run per project (the produced/consumed "
                    "directories are single-owner)"
                ),
            )


@router.post("/projects/{project_id}/hunting/{hunting_run_id}/stop")
async def stop_hunting_run(project_id: str, hunting_run_id: str) -> dict:
    """Phase-1 hard stop (seam 3.3): cancel the run's task on the hunting loop,
    reap the run's actor, persist `stopped`. The append-only store preserves the
    partial trail. A run that was never opened 404s."""
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime

    row = await asyncio.to_thread(pg.get_hunting_run, hunting_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no hunting run for that hunting_run_id")

    await hunting_runtime.stop_hunting(hunting_run_id)
    # #326: flush the project's durable usage record at the stop boundary.
    from polymerhus.app.llm.usage import usage_ledger  # noqa: PLC0415

    await asyncio.to_thread(usage_ledger().flush, project_id)
    return {"hunting_run_id": hunting_run_id, "stopping": True}


@router.post("/projects/{project_id}/hunting/{hunting_run_id}/resume",
             status_code=202)
async def resume_hunting_run(project_id: str, hunting_run_id: str) -> dict:
    """Resume ONE stopped or `interrupted` hunting run in place (T11 #398).

    The OPERATOR VERB is the ratified floor (#331 ESCALATED item 2; D-3 leaves
    the auto-resume health checker to a follow-up). It reads the run row and
    applies the decision table (`attack/hunting/resume.py`):

    - `stopped` -> resumable immediately;
    - `interrupted` and `stats.quota_exhausted == false` -> resumable after
      `retry_after_s`, or the default 60s backoff when the hint is null (a 409
      with a `Retry-After` hint inside the window);
    - `interrupted` and `quota_exhausted == true` -> terminal (409);
    - `interrupted` with missing/unknown stats -> do-not-resume (409). This is
      the process-restart orphan disposition: the startup reconcile stamps a
      restart reason and no provider class, so the verb never guesses;
    - `running` -> already live (409);
    - `complete` / `failed` -> terminal (409).

    Admission is a CONDITIONAL claim: only the exact row the decision read
    transitions back to `running`, so two concurrent resumes yield one 202 and
    one 409. The resumed run re-enters `start_hunting` with the EXISTING run id:
    it re-enters at the recorded `intake_position`, adopts the committed models,
    recomputes `risk_total`, and resumes dispatch; a halted run resumes dispatch
    only. An admission refusal restores the prior status (and leaves the stats
    intact) so the operator can retry - no `running` row is left behind."""
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from polymerhus.attack.hunting.resume import resume_decision

    if not await asyncio.to_thread(pg.project_exists, project_id):
        raise HTTPException(status_code=404, detail="unknown project")
    if not hunting_runtime.hunting_control_plane_available():
        raise HTTPException(
            status_code=503,
            detail="hunting control-plane runtime has not landed",
        )
    row = await asyncio.to_thread(pg.get_hunting_run, hunting_run_id)
    if row is None or row.get("project_id") != project_id:
        # the run namespace is project-scoped: a run of another project is an
        # unknown run through THIS path, never resumable by id alone
        raise HTTPException(
            status_code=404,
            detail="no hunting run for that hunting_run_id",
        )
    decision = resume_decision(
        str(row.get("status") or ""),
        row.get("stats"),
        row.get("finished_at"),
        now=datetime.now(timezone.utc),
    )
    if not decision.resumable:
        headers = None
        if decision.wait_s is not None:
            headers = {
                "Retry-After": str(max(1, math.ceil(decision.wait_s))),
            }
        raise HTTPException(
            status_code=409, detail=decision.reason, headers=headers)

    await _hunting_live_run_guard(project_id, exclude_run_id=hunting_run_id)
    prior_status = str(row.get("status"))
    claimed = await asyncio.to_thread(
        pg.claim_hunting_run_for_resume,
        hunting_run_id,
        project_id=project_id,
        expected_status=prior_status,
    )
    if claimed is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "the resume claim was lost: another resume of this run "
                "already claimed it"
            ),
        )
    coro = None
    try:
        coro = hunting_runtime.start_hunting(project_id, run_id=hunting_run_id)
        hunting_runtime.schedule_hunting(
            coro,
            name=f"hunting:{hunting_run_id}",
        )
    except Exception as exc:  # noqa: BLE001 - map admission refusal, restore
        # A post-claim admission refusal must not leave the claimed `running`
        # row behind: restore the exact prior status. The stats (the run record
        # and the interrupt cause) are untouched, so the operator can retry. The
        # terminal write stamps a NEW finished_at, which restarts the wait window
        # for a throttle - a conservative extension, never an early resume.
        # The un-admitted coroutine is closed: a refusal happens before the
        # runtime schedules it, so it must not sit until GC warns.
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        try:
            await asyncio.to_thread(
                pg.set_hunting_run_status, hunting_run_id, prior_status)
        except Exception:  # noqa: BLE001 - best-effort restore
            logger.warning(
                "resume_hunting_run: could not restore %r for %s "
                "(fail-open)", prior_status, hunting_run_id,
            )
        _admission_refused_503(exc)
    return {"hunting_run_id": hunting_run_id, "resumed": True}


@router.get("/projects/{project_id}/hunting/{hunting_run_id}")
async def get_hunting_status(project_id: str, hunting_run_id: str) -> dict:
    """The hunting run's status row (seam 3.3): `running` -> terminal."""
    from polymerhus.app.clients import pg

    row = await asyncio.to_thread(pg.get_hunting_run, hunting_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no hunting run for that hunting_run_id")
    return row


# --- T5: singular component launches (spec #169 "Singular component launches",
# ADR #169 Q4/Q6) -----------------------------------------------------------
#
# One endpoint per component that ENQUEUES into the component's handoff family
# so the run-scoped inbox surfer's mover dispatches it on the next tick - a
# singular launch never BOOTS a component directly and never fabricates a
# chained-dependency error. T4b (#387) retired the HUNT config enqueue with the
# config family: the loop file is the dispatch record, so `/hunting/hunt` is a
# loud 410 tombstone. The pod resume keeps its fail-closed 404 (no fabricated
# `ratified` spec), and the modeller pass schedules its own input.

class HuntingModellerLaunch(BaseModel):
    """Modeller-only launch body. The pass reads the L1 inventory itself (T3
    #376 retired the caller-supplied candidate batch), freezes and orders it,
    and writes its models and loop files into the project's threat model store -
    this endpoint schedules the pass, it never fakes the pass's output.
    """


class HuntingPodLaunch(BaseModel):
    """Pod-only launch body (identity-based refactor, 2026-08-25 operator
    ruling): the pod's ADR Q13 session id (`hunting:<run_id>:pod:<dispatch_id>:
    <spec_id>`) to RESUME. The endpoint NEVER fabricates a produced `ratified`
    test spec into the HunterMemoryStore produced family - it resumes ONE
    held/paused pod session by posting its coroutine id; the whole-pod-component
    path remains the whole-pipeline run. No stored/paused pod session to resume
    is a FAIL-CLOSED refusal (404), never a fabricated dispatch input."""

    session_id: str = Field(min_length=1)


@router.post("/projects/{project_id}/hunting/modeller", status_code=202)
async def launch_modeller_only(project_id: str, body: HuntingModellerLaunch) -> dict:
    """The modeller-only launch: schedule ONE modelling pass through the
    launcher seam - no surfer, no dispatch, no run (T5). The pass models the
    selected units into the project's threat model store, where a later run's
    surfer dispatches the produced loops. The outcome is asynchronous; the
    response carries the pass's run id for observability. 404 unknown project;
    503 fail-closed on the control plane (a real LLM pass must never ride the
    uvicorn request loop); admission refusal maps to 503.

    T10 renamed the planner-era path (`/hunting/orchestrator`) and the
    `component: "orchestrator"` label to the modeller vocabulary; the old names
    are removed, with no alias."""
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from polymerhus.attack.hunting.mover import threat_modeller_session_id

    if not await asyncio.to_thread(pg.project_exists, project_id):
        raise HTTPException(status_code=404, detail="unknown project")
    if not hunting_runtime.hunting_control_plane_available():
        raise HTTPException(
            status_code=503,
            detail="hunting control-plane runtime has not landed",
        )

    run_id = str(uuid.uuid4())
    try:
        hunting_runtime.schedule_hunting(
            hunting_runtime.launch_modeller(project_id, run_id=run_id),
            name=threat_modeller_session_id(run_id),
        )
    except Exception as exc:  # noqa: BLE001 - map admission refusal, re-raise the rest
        _admission_refused_503(exc)
    return {
        "component": "threat_modeller",
        "run_id": run_id,
        "dispatched_asynchronously": True,
    }


@router.post("/projects/{project_id}/hunting/hunt", status_code=410)
async def launch_hunt_only(project_id: str) -> dict:
    """RETIRED (T4b #387): the hunter-only hunt-config enqueue.

    A hunter is no longer dispatched from an enqueued `HuntConfig`: the dispatch
    grain is the produced LOOP FILE (S2 8.4), which the modeller writes from the
    unit's threat model, and a live run's surfer dispatches it. There is nothing
    an API caller can enqueue into that topology, so accepting the old body
    would be a silent write into a family nothing reads - the handler therefore
    refuses LOUDLY (410 Gone) and names the replacement.

    The eval translation is T10b (#397): `eval/orchestrator/api.py` and
    `eval/ph.py` never call this path; the eval's pre-mined hunt-config
    artifacts move to the loop vocabulary there."""
    raise HTTPException(
        status_code=410,
        detail=(
            "the hunt-config enqueue is retired (T4b #387): the loop file is "
            "the dispatch record (S2 8.4) and a live run's surfer dispatches "
            "it; launch the whole run (POST /projects/{project_id}/hunting) "
            "and the modeller produces the loop files. The eval translation "
            "is T10b (#397)"
        ),
    )


@router.post("/projects/{project_id}/hunting/pod", status_code=202)
async def launch_pod_only(project_id: str, body: HuntingPodLaunch) -> dict:
    """'Pod only' (identity-based refactor, 2026-08-25 operator ruling): resume
    ONE held/paused pod session by posting its coroutine id - NEVER fabricating
    a produced `ratified` spec (the reviewer's ambiguity; the whole-pod-component
    path remains the whole-pipeline run). The endpoint routes through the
    `resume_pod_session` launcher seam to the SHARED control plane's per-session
    `resume_session` (module "hunting", keyed by the ADR Q13 session id).

    FAIL-CLOSED: 503 while the control plane has not landed; 404 unknown
    project; 404 when there is no stored/paused pod session by that id
    (`RunNotRegistered` - nothing to resume, never a fabricated dispatch
    input); a registered-but-not-held session resumes as the runtime verb's own
    safe no-op (at-most-once - a replayed resume never double-runs)."""
    from polymerhus.app.clients import pg
    from polymerhus.app.runtime import RunNotRegistered
    from polymerhus.attack.hunting import runtime as hunting_runtime

    if not await asyncio.to_thread(pg.project_exists, project_id):
        raise HTTPException(status_code=404, detail="unknown project")
    if not hunting_runtime.hunting_control_plane_available():
        raise HTTPException(
            status_code=503,
            detail="hunting control-plane runtime has not landed",
        )
    runtime = _runtime_or_503()
    try:
        hunting_runtime.resume_pod_session(runtime, body.session_id)
    except RunNotRegistered as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no stored/paused pod session {body.session_id!r} to resume "
                f"for project {project_id} (fail-closed: nothing fabricated)"
            ),
        ) from exc
    return {
        "component": "pod",
        "resumed": True,
        "session_id": body.session_id,
        "dispatched_asynchronously": True,
    }


# --- T5: per-session lifecycle verbs (ADR #169 Q17, spec #169 "REST surface") ---
#
# Pause / resume / stop for ONE registered session of a run, under the project
# and hunting-run namespace. They route to the SHARED runtime's per-session
# lifecycle (`hold_session` / `resume_session` / `cancel_run`, module
# "hunting"), keyed by the ADR Q13 session id (session id = coroutine id =
# registry run name) - NOT the module-wide verbs, so one stuck or costly
# session never forces a whole-run stop. Map: 404 unknown run, 404 unknown /
# unregistered session (the runtime's own `RunNotRegistered` error), 503 no
# active runtime.

_SESSION_STATES = {"pause": "held", "resume": "resumed", "stop": "stopping"}


async def _session_verb(project_id: str, hunting_run_id: str, session_id: str,
                        verb: str) -> dict:
    """Route ONE per-session lifecycle verb to the shared control plane by the
    session's ADR Q13 id. The run's own row must exist (404 unknown run) and
    the session id must belong to the run (`is_run_session_id` - 404 unknown
    session); a session of a SIBLING run is never reachable through this
    namespace. `pause`/`stop` map the runtime's own `RunNotRegistered` onto
    404 (nothing live to hold/cancel); `resume` of a not-held session is the
    runtime verb's own safe no-op."""
    from polymerhus.app.clients import pg  # noqa: PLC0415
    from polymerhus.app.runtime import RunNotRegistered  # noqa: PLC0415
    from polymerhus.attack.hunting.surfer import is_run_session_id  # noqa: PLC0415

    row = await asyncio.to_thread(pg.get_hunting_run, hunting_run_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail="no hunting run for that hunting_run_id")
    if not is_run_session_id(session_id, hunting_run_id):
        raise HTTPException(
            status_code=404,
            detail=f"no session {session_id!r} of hunting run {hunting_run_id}",
        )
    runtime = _runtime_or_503()
    try:
        if verb == "pause":
            runtime.hold_session("hunting", session_id)
        elif verb == "resume":
            runtime.resume_session("hunting", session_id)
        else:  # stop
            runtime.cancel_run("hunting", session_id)
    except RunNotRegistered as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no live session {session_id!r} of hunting run "
                f"{hunting_run_id}"
            ),
        ) from exc
    return {
        "hunting_run_id": hunting_run_id,
        "session_id": session_id,
        "state": _SESSION_STATES[verb],
    }


@router.post("/projects/{project_id}/hunting/{hunting_run_id}/sessions/{session_id}/pause")
async def pause_hunting_session(project_id: str, hunting_run_id: str,
                                session_id: str) -> dict:
    """Hold ONE session (ADR #169 Q14): its NEXT unit boundary at the module
    gate waits until resumed; sibling sessions of the run keep dispatching."""
    return await _session_verb(project_id, hunting_run_id, session_id, "pause")


@router.post("/projects/{project_id}/hunting/{hunting_run_id}/sessions/{session_id}/resume")
async def resume_hunting_session(project_id: str, hunting_run_id: str,
                                 session_id: str) -> dict:
    """Release a held session; resuming a not-held session is the runtime
    verb's own safe no-op."""
    return await _session_verb(project_id, hunting_run_id, session_id, "resume")


@router.post("/projects/{project_id}/hunting/{hunting_run_id}/sessions/{session_id}/stop")
async def stop_hunting_session(project_id: str, hunting_run_id: str,
                               session_id: str) -> dict:
    """Hard-cancel ONE session by its id (phase-1 per-session stop); a session
    that already settled maps the runtime's own `RunNotRegistered` onto 404."""
    return await _session_verb(project_id, hunting_run_id, session_id, "stop")


# --- #317: agent sub-modules and threads (app module REST surface) -----------
#
# The additive per-agent control surface over the hunting pipeline: each agent
# role of a run carries its own lifecycle state and gate (layered under the
# module gate). `start`/`stop` are idempotent; single-thread stop/resume reuse
# the existing per-session hold/resume verbs. Map: 404 unknown run / role /
# thread, 503 no active runtime.


async def _hunting_run_or_404(hunting_run_id: str) -> dict:
    from polymerhus.app.clients import pg  # noqa: PLC0415

    row = await asyncio.to_thread(pg.get_hunting_run, hunting_run_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail="no hunting run for that hunting_run_id")
    return row


@router.post(
    "/projects/{project_id}/hunting/{hunting_run_id}/agent-submodules/{role}/start"
)
async def start_agent_submodule(project_id: str, hunting_run_id: str, role: str) -> dict:
    """Start ONE agent sub-module role of the run (#317): move it to `RUNNING`
    and release its held threads. Idempotent (a no-op when already running). 404
    unknown run / unknown role; 503 no active runtime."""
    return await _agent_submodule_verb(project_id, hunting_run_id, role, start=True)


@router.post(
    "/projects/{project_id}/hunting/{hunting_run_id}/agent-submodules/{role}/stop"
)
async def stop_agent_submodule(project_id: str, hunting_run_id: str, role: str) -> dict:
    """Stop ONE agent sub-module role of the run (#317): move it to `PAUSED`,
    refuse new dispatch for the role AND hold its in-flight threads at their
    next unit boundary. Idempotent. 404 unknown run / unknown role; 503 no active
    runtime."""
    return await _agent_submodule_verb(project_id, hunting_run_id, role, start=False)


async def _agent_submodule_verb(project_id: str, hunting_run_id: str, role: str,
                                *, start: bool) -> dict:
    from polymerhus.app.runtime import UnknownAgentSubmoduleRole  # noqa: PLC0415

    await _hunting_run_or_404(hunting_run_id)
    runtime = _runtime_or_503()
    try:
        if start:
            state = runtime.start_agent_submodule("hunting", hunting_run_id, role)
        else:
            state = runtime.stop_agent_submodule("hunting", hunting_run_id, role)
    except UnknownAgentSubmoduleRole as exc:
        raise HTTPException(
            status_code=404,
            detail=f"unknown agent sub-module role {role!r}",
        ) from exc
    return {
        "hunting_run_id": hunting_run_id,
        "role": role,
        "state": state.value,
    }


@router.get("/projects/{project_id}/hunting/{hunting_run_id}/agent-submodules")
async def list_agent_submodules(project_id: str, hunting_run_id: str) -> list[dict]:
    """The run's agent sub-module roles with their states (#317): exactly the
    three roles `threat_modeller`, `hunter`, `pod`. 404 unknown run; 503 no
    active runtime."""
    await _hunting_run_or_404(hunting_run_id)
    runtime = _runtime_or_503()
    states = runtime.agent_submodule_states("hunting", hunting_run_id)
    return [{"role": r, "state": s.value} for r, s in states.items()]


@router.get("/projects/{project_id}/hunting/{hunting_run_id}/threads")
async def list_hunting_threads(project_id: str, hunting_run_id: str) -> list[dict]:
    """Every live thread of the run (#317) as `{thread_id, role, held}`, a read
    surface that includes the surfer and the bootstrap (role `infra`). 404
    unknown run; 503 no active runtime."""
    from polymerhus.attack.hunting.surfer import (  # noqa: PLC0415
        derive_thread_role,
        is_run_session_id,
    )

    await _hunting_run_or_404(hunting_run_id)
    runtime = _runtime_or_503()
    threads: list[dict] = []
    for session_id in runtime.run_ids("hunting"):
        if not is_run_session_id(session_id, hunting_run_id):
            continue
        threads.append({
            "thread_id": session_id,
            "role": derive_thread_role(session_id),
            "held": runtime.is_session_held("hunting", session_id),
        })
    return threads


async def _thread_verb(project_id: str, hunting_run_id: str, thread_id: str,
                       *, stop: bool) -> dict:
    from polymerhus.app.runtime import RunNotRegistered  # noqa: PLC0415
    from polymerhus.attack.hunting.surfer import (  # noqa: PLC0415
        is_run_session_id,
    )

    await _hunting_run_or_404(hunting_run_id)
    if not is_run_session_id(thread_id, hunting_run_id):
        raise HTTPException(
            status_code=404,
            detail=f"no thread {thread_id!r} of hunting run {hunting_run_id}",
        )
    runtime = _runtime_or_503()
    # Registration is checked EXPLICITLY (as the pod-resume seam does): the
    # shared `resume_session` verb is a documented no-op for a never-registered
    # run and NEVER raises, so without this an unknown-unregistered thread would
    # be answered `200 resumed` (a fabricated success). Stop/`hold_session`
    # raises on its own, but both verbs must 404 an unknown-unregistered thread.
    if thread_id not in runtime.run_ids("hunting"):
        raise HTTPException(
            status_code=404,
            detail=(
                f"no live thread {thread_id!r} of hunting run {hunting_run_id}"
            ),
        )
    try:
        if stop:
            runtime.hold_session("hunting", thread_id)
        else:
            runtime.resume_session("hunting", thread_id)
    except RunNotRegistered as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no live thread {thread_id!r} of hunting run {hunting_run_id}"
            ),
        ) from exc
    return {
        "hunting_run_id": hunting_run_id,
        "thread_id": thread_id,
        "state": "held" if stop else "resumed",
    }


@router.post("/projects/{project_id}/hunting/{hunting_run_id}/threads/{thread_id}/stop")
async def stop_hunting_thread(project_id: str, hunting_run_id: str,
                              thread_id: str) -> dict:
    """Hold ONE live thread of the run (#317): its next unit boundary waits
    until resumed; the thread stays registered. Idempotent. 404 unknown run /
    unknown-unregistered thread; 503 no active runtime."""
    return await _thread_verb(project_id, hunting_run_id, thread_id, stop=True)


@router.post("/projects/{project_id}/hunting/{hunting_run_id}/threads/{thread_id}/resume")
async def resume_hunting_thread(project_id: str, hunting_run_id: str,
                                thread_id: str) -> dict:
    """Release a held thread of the run (#317): a resume of a not-held thread is
    the runtime verb's safe no-op. Idempotent. 404 unknown run / unknown
    thread; 503 no active runtime."""
    return await _thread_verb(project_id, hunting_run_id, thread_id, stop=False)


# --- module-lifecycle surface (#118/#121): drive the runtime plane ------------

_MODULES = ("recon", "analysis", "hunting")


def _module_handle(runtime, module: str):
    """The runtime's `ModuleHandle` for `module`, or None (the module registry
    only ever holds the three ratified modules)."""
    if module not in _MODULES:
        return None
    try:
        return runtime.handle(module)
    except KeyError:
        return None


def _runtime_or_503():
    runtime = _runtime()
    if runtime is None:
        raise HTTPException(
            status_code=503, detail="module runtime is not active"
        )
    return runtime


def _admission_refused_503(exc: Exception):
    """Map the runtime's admission refusal (#118 contract: `schedule` is refused
    while a module is paused or draining) onto a clean HTTP status instead
    of an unhandled 500 - the operator-intent surface must say *why* the launch
    was not admitted. `RuntimeLoopNotRunning` (a revive during the shutdown
    window, when the worker loop is already cleared) is likewise a clean 503."""
    from polymerhus.app.runtime import (
        ModuleAdmissionRefused,
        RuntimeLoopNotRunning,
    )

    if isinstance(exc, ModuleAdmissionRefused):
        raise HTTPException(
            status_code=503,
            detail=f"module not accepting new work: {exc}",
        ) from exc
    if isinstance(exc, RuntimeLoopNotRunning):
        raise HTTPException(
            status_code=503,
            detail="module runtime is not running",
        ) from exc
    raise exc


@router.post("/projects/{project_id}/modules/{module}/pause")
def pause_module(project_id: str, module: str) -> dict:
    """Pause a module (#118): stop admission and the dispatch of the NEXT unit
    after the in-flight one; run tasks, heartbeats, persistence stay alive. A
    pause of an already-stopped module is a safe no-op (the runtime verb's own
    semantics); the response always reports the current state."""
    runtime = _runtime_or_503()
    handle = _module_handle(runtime, module)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown module")
    runtime.pause(module)
    return {"module": module, "state": handle.state.value}


@router.post("/projects/{project_id}/modules/{module}/resume")
def resume_module(project_id: str, module: str) -> dict:
    """Resume a paused module (#118): return to `running`, dispatch continues
    from the next unit. Resuming a non-paused module is a safe no-op (the
    runtime verb's own semantics); the response reports the current state."""
    runtime = _runtime_or_503()
    handle = _module_handle(runtime, module)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown module")
    runtime.resume(module)
    return {"module": module, "state": handle.state.value}


@router.post("/projects/{project_id}/modules/{module}/drain")
def drain_module(project_id: str, module: str) -> dict:
    """Drain a module (#118): pause plus a graceful settle to `stopped` - finish
    the in-flight unit, dispatch no further, archive via the module's flush hook
    into the still-open pooled saver. The only lifecycle verb that changes run
    state durably.

    Returns the module's flush result (#211, TD-4) so a dropped flush is
    machine-readable: `{committed, archived, dropped, dropped_thread_ids, cause}` -
    the assert surface the eval harness / operator checks (`dropped == 0`). The
    flush is ALWAYS an object: a drain that settled no flush yet (an already
    stopped module that never flushed) reports the degraded `cause="never-flushed"`
    shape, never null - so the harness reads `body["flush"]["dropped"]` without a
    null branch. No prose report: the structural state (the store, the run rows)
    is the teardown state."""
    from polymerhus.app.llm.checkpoints import FlushResult  # noqa: PLC0415

    runtime = _runtime_or_503()
    handle = _module_handle(runtime, module)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown module")
    runtime.drain(module)
    # #326: flush every in-memory project's usage at the drain boundary.
    from polymerhus.app.llm.usage import usage_ledger  # noqa: PLC0415

    usage_ledger().flush_all()
    last = handle.last_flush
    if last is None:
        last = FlushResult.degraded("never-flushed")
    return {
        "module": module,
        "state": handle.state.value,
        "flush": last.to_dict(),
    }
