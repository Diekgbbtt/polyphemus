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
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from polymerhus.project_management import repository
from polymerhus.project_management.repository import (
    BootstrapBlocked,
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


class BootstrapLaunch(BaseModel):
    """Ingest the operator's knowledge base and bootstrap. `operator_kb` is optional:
    supply it to ingest-and-bootstrap in one call (the frontend's flow), or omit it to
    bootstrap from the KB already stored in the project's settings."""

    operator_kb: str | None = None


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


@router.put("/projects/{project_id}/settings")
def update_settings(project_id: str, body: SettingsUpdate) -> dict:
    try:
        repository.save_project_settings(project_id, body.recon)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="unknown project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


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

    async def _run() -> None:
        try:
            await run_pipeline(project_id, run_id=run_id, job_subset=jobs,
                               with_analysis=with_analysis)
        except Exception:  # noqa: BLE001 - best-effort launch, must not crash the loop
            logger.exception("recon pipeline run %s (project %s) failed", run_id, project_id)

    # #121: recon is a registered run of the recon module on the runtime's
    # worker loop; pause/drain/cancel of the recon module reach it here.
    # A paused/draining/stopped recon module refuses admission (#118) - map
    # that to a clean 503 so the caller reads *why* the launch was refused.
    try:
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
    output suppression is #76.)"""
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
    return {"run_id": run_id, "stopping": True}


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

class _HuntingCandidateIn(BaseModel):
    """The wire shape of one candidate: a `(unit_id, fault_class)` pair with the
    match verdict + applicability witnesses. The orchestrator's normalize stage
    still drops malformed / de-duplicates downstream (O7/O10)."""
    unit_id: str
    fault_class: str
    verdict: str = "applies"
    deterministic_witness: str | None = None
    llm_witness: str | None = None


def _hunting_candidates(body_candidates) -> list:
    """Build the typed `DeliveredCandidate` batch from the wire shape, used by
    the whole-pipeline and orchestrator-only launches. The verdict is coerced
    onto the three-valued match-verdict Literal (a foreign value survives the
    orchestrator's normalize-stage degrade, O7/O10)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (
        DeliveredCandidate,
        Witness,
    )

    verdicts = {"applies", "does-not-apply", "insufficient-evidence"}
    return [
        DeliveredCandidate(
            unit_id=c.unit_id,
            fault_class=c.fault_class,
            applies_witnesses=Witness(
                deterministic=c.deterministic_witness, llm=c.llm_witness,
            ),
            match_verdict=c.verdict if c.verdict in verdicts else "applies",
        )
        for c in body_candidates
    ]


class HuntingLaunch(BaseModel):
    """The hunting launch body (#110): the optional initial candidate batch. An
    omitted/empty batch launches an empty pass (O1) to be fed later."""
    candidates: list[_HuntingCandidateIn] = []


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

    candidates = _hunting_candidates(body.candidates)

    hunting_run_id = await asyncio.to_thread(pg.create_hunting_run, project_id)
    try:
        hunting_runtime.schedule_hunting(
            hunting_runtime.start_hunting(
                project_id, run_id=hunting_run_id, candidates=candidates,
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


async def _hunting_live_run_guard(project_id: str) -> None:
    """The API-tier ONE-live-run-per-project guard (T5, spec #169 US10 / ticket
    ruling point 2): refuse a launch while the project already holds a
    `running` hunting run - the per-project produced/consumed memory
    directories are single-owner, so two concurrent runs must never race them.

    The `hunting_runs` row read (`list_hunting_runs`) is the authority the API
    tier owns, checked BEFORE the new row opens so a refusal never leaves an
    orphan. The bootstrap's own guard is belt-and-braces (it excludes the
    run's own pinned row); this check prevents the orphan in the first place.
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
        if row.get("status") == "running":
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
    return {"hunting_run_id": hunting_run_id, "stopping": True}


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
# chained-dependency error: the enqueue succeeds with or without a live run /
# orchestrator and the component consumes its inbox asynchronously (a queued
# item stays in produced until admitted - the at-least-once protocol). The
# storage-layer novelty gates (`DuplicateConfigError` / `DuplicateSpecError`,
# ADR G4) are the server-side at-most-once marker for a replayed enqueue (409).

class HuntingOrchestratorLaunch(BaseModel):
    """Orchestrator-only launch body: the candidate batch the pass consumes.
    The pass itself writes the ratified configs into the project's HuntStore -
    this endpoint schedules the pass, it never fakes the orchestrator's output
    (the produced/consumed topology has no orchestrator INPUT family; the
    candidate batch is in-memory at schedule, so the minimal faithful reading
    of the orchestrator's "enqueue" is scheduling its pass)."""

    candidates: list[_HuntingCandidateIn] = []


class HuntingHuntLaunch(BaseModel):
    """Hunter-only launch body: ONE produced RATIFIED hunt config to enqueue
    into the project's HuntStore produced family (the mover's hunter-dispatch
    input). The essential identity fields surface; the rest of the
    `HuntConfig` parameter set (surface context, target caveats, prior-hunt
    insights, tool registry) keeps its defaults."""

    unit_id: str
    fault_class: str
    vulnerability_class: str = ""
    hunt_id: str | None = None
    research_direction: str = ""
    rationale: str = ""
    adversarial_capabilities: list[str] = []
    assumptions: list[str] = []
    technique_primitives: list[str] = []


class HuntingPodLaunch(BaseModel):
    """Pod-only launch body: ONE produced SPECIFIED test spec to enqueue into
    the project's HunterMemoryStore produced family (the mover's pod-dispatch
    input). `fault_key` is the 3-part config key the spec lives under; the
    `<fault>_<strategy>` keywords name the spec file; `spec` is the
    TestImplementationSpec wire shape (status forced to `specified`)."""

    fault_key: str
    fault_keyword: str
    strategy_keyword: str
    spec: dict = {}


@router.post("/projects/{project_id}/hunting/orchestrator", status_code=202)
async def launch_orchestrator_only(project_id: str, body: HuntingOrchestratorLaunch) -> dict:
    """'Orchestrator only': schedule ONE orchestration pass through the
    launcher seam - no surfer, no dispatch, no run (T5). The pass consumes
    the candidate batch and writes its ratified configs into the project's
    HuntStore for a later run to dispatch. The outcome is asynchronous; the
    response carries the pass's run id for observability. 404 unknown project;
    503 fail-closed on the control plane (a real LLM pass must never ride the
    uvicorn request loop); admission refusal maps to 503."""
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime

    if not await asyncio.to_thread(pg.project_exists, project_id):
        raise HTTPException(status_code=404, detail="unknown project")
    if not hunting_runtime.hunting_control_plane_available():
        raise HTTPException(
            status_code=503,
            detail="hunting control-plane runtime has not landed",
        )

    candidates = _hunting_candidates(body.candidates)
    run_id = str(uuid.uuid4())
    try:
        hunting_runtime.schedule_hunting(
            hunting_runtime.launch_orchestrator(
                project_id, run_id=run_id, candidates=candidates,
            ),
            name=f"hunting:{run_id}:orchestrator",
        )
    except Exception as exc:  # noqa: BLE001 - map admission refusal, re-raise the rest
        _admission_refused_503(exc)
    return {
        "component": "orchestrator",
        "run_id": run_id,
        "dispatched_asynchronously": True,
    }


@router.post("/projects/{project_id}/hunting/hunt", status_code=202)
async def launch_hunt_only(project_id: str, body: HuntingHuntLaunch) -> dict:
    """'Hunter only': enqueue ONE produced RATIFIED hunt config into the
    project's HuntStore produced family so the run's inbox surfer dispatches
    one hunter on the next tick (T5). The enqueue is a store write - it
    succeeds with or without a live run or orchestrator (the config waits in
    produced, at-least-once), so a chained-dependency error is never
    fabricated. A REPLAYED enqueue whose config identity already exists (a
    duplicate file in produced/ or consumed/) is refused 409 - the storage
    novelty gate is the server-side at-most-once marker. 404 unknown project."""
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from polymerhus.attack.hunting.hunt_orchestrator import (
        HuntConfig,
        HuntPromptTemplate,
    )
    from polymerhus.attack.hunting.hunt_store import DuplicateConfigError

    if not await asyncio.to_thread(pg.project_exists, project_id):
        raise HTTPException(status_code=404, detail="unknown project")

    config = HuntConfig(
        hunt_id=body.hunt_id or (
            f"{body.unit_id}::{body.fault_class}::{body.vulnerability_class}"
        ),
        unit_id=body.unit_id,
        fault_class=body.fault_class,
        vulnerability_class=body.vulnerability_class,
        prompt_template=HuntPromptTemplate(
            rationale=body.rationale, research_direction=body.research_direction,
        ),
        adversarial_capabilities=body.adversarial_capabilities,
        assumptions=body.assumptions,
        technique_primitives=body.technique_primitives,
    )
    try:
        key = await asyncio.to_thread(
            hunting_runtime.enqueue_hunt_config, project_id, config
        )
    except DuplicateConfigError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"this hunt config is already enqueued (at-most-once): {exc}",
        ) from exc
    return {
        "component": "hunt",
        "enqueued": True,
        "enqueued_key": key,
        "dispatched_asynchronously": True,
    }


@router.post("/projects/{project_id}/hunting/pod", status_code=202)
async def launch_pod_only(project_id: str, body: HuntingPodLaunch) -> dict:
    """'Pod only': enqueue ONE produced SPECIFIED test spec into the project's
    HunterMemoryStore produced family so the run's inbox surfer dispatches one
    pod on the next tick (T5). A spec whose parent hunter was never dispatched
    stays in produced (at-least-once), never an error - the mover refuses and
    retries. A REPLAYED enqueue whose `<fault>_<strategy>` file already exists
    is refused 409 - the storage novelty gate, the at-most-once marker. 404
    unknown project."""
    from polymerhus.app.clients import pg
    from polymerhus.attack.hunting import runtime as hunting_runtime
    from polymerhus.attack.hunting.hunter_memory import DuplicateSpecError

    if not await asyncio.to_thread(pg.project_exists, project_id):
        raise HTTPException(status_code=404, detail="unknown project")

    try:
        spec_file = await asyncio.to_thread(
            hunting_runtime.enqueue_test_spec,
            project_id,
            fault_key=body.fault_key,
            fault_keyword=body.fault_keyword,
            strategy_keyword=body.strategy_keyword,
            spec=body.spec,
        )
    except DuplicateSpecError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"this test spec is already enqueued (at-most-once): {exc}",
        ) from exc
    return {
        "component": "pod",
        "enqueued": True,
        "spec_file": spec_file,
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
    while a module is paused/draining/stopped) onto a clean HTTP status instead
    of an unhandled 500 - the operator-intent surface must say *why* the launch
    was not admitted."""
    from polymerhus.app.runtime import ModuleAdmissionRefused

    if isinstance(exc, ModuleAdmissionRefused):
        raise HTTPException(
            status_code=503,
            detail=f"module not accepting new work: {exc}",
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
    state durably."""
    runtime = _runtime_or_503()
    handle = _module_handle(runtime, module)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown module")
    runtime.drain(module)
    return {"module": module, "state": handle.state.value}
