"""Hunting module runtime entry points (seam contract 3; #110).

The hunting side of the app-module seam (`docs/design/hunting-module-runtime-seam.md`,
ratified 2026-08-11). This module owns the lifecycle entry points the control
plane drives and the tear-down hooks it calls:

  start_hunting            - the bootstrap coroutine: sets the hunting module
                             context for its full duration, enforces ONE live
                             hunting run per project (the pg row is the
                             enforcement point - the per-project produced/
                             consumed directories are single-owner), opens a
                             `hunting_runs` row (`running`), schedules the
                             orchestrator pass AND the run-scoped inbox surfer
                             as sessions on the shared runtime manager (ADR
                             #169 Q2a/Q12), waits for quiesce (the pass done,
                             produced dirs drained, every dispatched session
                             settled), and persists the terminal status.
                             Fail-open: a collaborator failure never raises
                             through the control plane - it lands a terminal
                             status. The blocking-sync-pg calls
                             (`create_hunting_run`, `set_hunting_run_status`,
                             `list_hunting_runs`) offload via
                             `asyncio.to_thread` onto the shared executor,
                             never the worker loop.
  stop_hunting             - the run stop (ADR #169 "Run lifecycle"): cancels
                             EVERY session of the run by session id through the
                             shared control plane (the orchestrator pass, the
                             surfer - itself a session - every hunter and pod),
                             reaps the run's actor, persists `stopped` (the
                             per-project store already preserves the partial
                             config/notes trail).
  flush_hunting_checkpointer - the tear-down flush hook (#123): archive the
                             hunting module in-memory checkpointer index into the
                             still-open pooled saver via the shared
                             `flush_module_index("hunting")` seam, fail-open.
  schedule_hunting / cancel_hunting - the marshalling harness: drive the
                             control plane's `runtime.schedule` /
                             `runtime.cancel_run`. Since #122 there is no
                             in-process fallback - `hunting_control_plane_available()`
                             is the fail-closed gate the launch endpoint checks
                             before any real run may boot.

Per CODING_STANDARD section 6 this module performs no I/O and opens no
connection at import: the orchestration symbols and the runtime manager are
imported lazily inside the functions that need them.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Coroutine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def hunting_module_context():
    """Set the hunting module context for the entry point's full duration.

    Delegates to the SHARED `module_context("hunting")` seam
    (`polymerhus.app.llm.checkpoints`), never a private hunting-only var: while
    it is set, `get_session_checkpointer()` resolves the hunting module's
    in-memory index, and `copy_context` carries the var into `asyncio.to_thread`
    and executor work, so offloaded hunting turns resolve the same index."""
    from polymerhus.app.llm.checkpoints import module_context  # noqa: PLC0415

    with module_context("hunting"):
        yield


def _app_runtime():
    """The ACTIVE control-plane runtime manager, or None when it has not landed
    (the module import still fails) or is not active (no manager running).

    The module existing is not enough: `schedule`/`cancel_run` raise when no
    manager is active, so a caller must fail closed unless `get_active_runtime()`
    returns a live manager (#121 regression guard)."""
    try:
        from polymerhus.app.runtime import get_active_runtime
        return get_active_runtime()
    except ImportError:
        return None


def _require_runtime():
    runtime = _app_runtime()
    if runtime is None:
        raise RuntimeError(
            "hunting control-plane runtime is not active; "
            "hunting_control_plane_available() must gate the launch"
        )
    return runtime


def hunting_control_plane_available() -> bool:
    """True once the control plane's `polymerhus.app.runtime` has landed (the
    hunting LOOP exists to schedule real runs). The API's fail-closed gate: a
    real orchestration pass (LLM turns) must never be smuggled onto the uvicorn
    request loop by an in-process fallback, so the launch surface 503s until
    the control plane is present."""
    return _app_runtime() is not None


def schedule_hunting(coro: Coroutine[Any, Any, Any], *, name: str) -> Any:
    """Schedule a hunting-run coroutine onto the worker loop (seam 2.2):
    `runtime.schedule("hunting", coro, name=name)`. No in-process fallback
    since #122 - the launch endpoint's `hunting_control_plane_available()`
    gate already failed closed when no manager is active."""
    return _require_runtime().schedule("hunting", coro, name=name)


def enqueue_hunt_config(project_id: str, config, *, hunt_store=None) -> str:
    """The hunter-ONLY launch seam (T5, ADR #169 Q4/Q6): enqueue ONE produced
    RATIFIED hunt config into the project's HuntStore `produced/` family - the
    inbox-surfer mover's hunter-dispatch input. The run-scoped surfer picks it
    up on the next tick and dispatches one hunter; a config waits in produced
    (at-least-once) until a run's live surfer admits it, so the enqueue NEVER
    fabricates a chained-dependency error (no orchestrator, no live run
    required). `status` is forced to `ratified` - the enqueue injects a
    dispatchable config, and the mover only dispatches ratified configs. A
    config whose file-name identity already exists in produced/ or consumed/
    raises `DuplicateConfigError` - the storage-layer novelty gate is the
    server-side at-most-once marker for the item (a replayed enqueue is the
    API's 409). Returns the config's semantic key.

    Blocking file I/O: the API offloads via `asyncio.to_thread`. Write failure
    raises to the caller (O3 - warned and counted), never a silent drop.
    `hunt_store` injectable per s6 (tests use a temp-root store)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        HuntConfig,
    )
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415

    payload = (
        config.model_dump() if isinstance(config, HuntConfig) else dict(config)
    )
    payload = {**payload, "status": "ratified"}
    store = hunt_store if hunt_store is not None else HuntStore()
    return store.write_config(project_id, payload, directory="produced")


def resume_pod_session(runtime, session_id: str) -> None:
    """The pod-ONLY launch seam (T5, ADR #169 Q4/Q6, identity-based refactor
    2026-08-25 operator ruling): RESUME ONE held/paused pod session by posting
    its coroutine id - NEVER fabricating a produced `specified` spec into the
    HunterMemoryStore produced family (a fabricated `specified` dispatch input
    was the reviewer's scope/ambiguity finding and the wedge's entry point).

    `session_id` is the pod's ADR Q13 session id
    (`hunting:<run_id>:pod:<config_id>:<spec_id>` - session id = coroutine id
    = registry run name, Q12). The seam asks the SHARED control plane to
    release the held session (`RuntimeManager.resume_session`, module
    "hunting"): a held session's next unit boundary at the hunting dispatch
    gate proceeds again. A registered-but-not-held session is already running,
    so its resume is the runtime verb's own safe no-op (idempotent - a
    replayed resume never double-runs, preserving at-most-once).

    FAIL-CLOSED when there is no stored/paused pod session to resume: it raises
    `RunNotRegistered` (the shared runtime's own signal) when no session is
    registered by that id - the launch endpoint maps it to 404 rather than
    fabricating dispatch input. The registration check is the seam's own
    (verified against the live control plane 2026-08-25): the shared
    `RuntimeManager.resume_session` verb is a documented no-op for a
    never-registered run and NEVER raises, so an unregistered session id would
    otherwise be silently treated as resumed (a fabricated success). Only a
    REGISTERED pod session resumes (its hold clears); a registered-but-not-held
    session is already running and its resume is the runtime verb's safe no-op.
    `runtime` is the shared control plane (injected by the API tier; the
    endpoint's `_runtime_or_503` guarantees one)."""
    if not session_id:
        raise ValueError("a pod session_id is required to resume")
    from polymerhus.app.runtime import RunNotRegistered  # noqa: PLC0415
    if session_id not in runtime.run_ids("hunting"):
        raise RunNotRegistered(session_id)
    runtime.resume_session("hunting", session_id)


async def launch_orchestrator(
    project_id: str,
    *,
    run_id: str,
    candidates: list | tuple | None = None,
    tools=None,
    hunt_store=None,
    orchestrator_fn=None,
    fault_entries=None,
    read_fn=None,
    match_fn=None,
    unit_ids_fn=None,
    **orchestration_kwargs,
) -> Any:
    """The orchestrator-ONLY launch coroutine (T5, spec #169 "Singular
    component launches"): ONE orchestration pass and NOTHING else - no
    run-scoped surfer, no dispatch, no `hunting_runs` row. The pass is exactly
    the one the whole-pipeline bootstrap would schedule (same tool/toolkit
    construction, same `arun_orchestration` entry): it consumes the candidate
    batch and writes its ratified configs into the project's HuntStore
    produced family, where a later run's surfer (or a hunter-only launch)
    dispatches them. The control plane schedules THIS coroutine under the ADR
    Q13 orchestrator session id (`hunting:<run_id>:orchestrator`), so the
    per-session verbs (hold/resume/cancel, ADR Q13/Q17) address it like any
    orchestrator session.

    #200 selection wiring (shared with `start_hunting`): an EMPTY candidate
    batch triggers the platform's OWN FaultSource selection over the live L1
    (`materialize_candidates`, the deterministic stage + pass-through match);
    a non-empty caller batch is the override. The selection summary is
    recorded via `trace_gate_step` + a log line.

    The produced/consumed topology carries the orchestrator's OUTPUT (hunt
    configs) but never its INPUT (the candidate batch is in-memory at
    schedule), so the minimal faithful reading of "enqueues into the
    component's handoff family" for the orchestrator is scheduling its pass;
    the component consumes its candidate inbox asynchronously. Fail-open: an
    orchestrator failure never raises through the control plane (logged).
    Injectable seams (s6): `orchestrator_fn` and `orchestration_kwargs`
    substitute the pass body for tests."""

    async with hunting_module_context():
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            OrchestratorTools,
            ReadOnlyGraphView,
        )
        from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415

        if hunt_store is None:
            hunt_store = HuntStore()
        if tools is None:
            try:
                tools = OrchestratorTools(
                    store_reads=hunt_store,
                    graph_view=ReadOnlyGraphView(project_id),
                )
            except Exception:  # noqa: BLE001 - fail-open tools default
                logger.warning(
                    "launch_orchestrator: default tools unavailable; the pass "
                    "grounds on the candidate set alone (fail-open)"
                )
                tools = OrchestratorTools(store_reads=hunt_store, graph_view=None)
        try:
            from polymerhus.attack.hunting.fault_source import (  # noqa: PLC0415
                materialize_candidates,
            )
            from polymerhus.attack.hunting.orchestrator_tracing import (  # noqa: PLC0415
                orchestrator_gate_span,
                trace_gate_step,
            )

            with orchestrator_gate_span(run_id):
                selected, summary = await asyncio.to_thread(
                    materialize_candidates,
                    project_id, candidates,
                    fault_entries=fault_entries, read_fn=read_fn,
                    match_fn=match_fn, unit_ids_fn=unit_ids_fn,
                )
                trace_gate_step(
                    "selection",
                    input={"project_id": project_id,
                           "caller_supplied": summary.caller_supplied},
                    output={
                        "faults_evaluated": summary.faults_evaluated,
                        "units_minted": summary.units_minted,
                        "pruned_by_predicate": summary.pruned_by_predicate,
                        "pruned_by_tag": summary.pruned_by_tag,
                        "passed": summary.passed,
                    },
                )
            if orchestrator_fn is not None:
                return await orchestrator_fn(
                    project_id, run_id, selected, tools,
                    **orchestration_kwargs,
                )
            from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
                arun_orchestration,
            )
            return await arun_orchestration(
                project_id, run_id, selected, tools,
                **orchestration_kwargs,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - fail-open into the run
            logger.exception(
                "launch_orchestrator: pass %s for project %s degraded (fail-open)",
                run_id, project_id,
            )


def cancel_hunting(hunting_run_id: str) -> None:
    """The phase-1 cancellation seam (seam 2.2):
    `runtime.cancel_run("hunting", hunting_run_id)`. Fail-open: with no active
    runtime, or a run that has already left the registry (completed, or never
    scheduled), cancellation is a safe no-op - so `stop_hunting`'s teardown
    never raises through the control plane."""
    runtime = _app_runtime()
    if runtime is None:
        logger.warning(
            "cancel_hunting: no active runtime; run %s left as-is (fail-open)",
            hunting_run_id,
        )
        return
    try:
        runtime.cancel_run("hunting", hunting_run_id)
    except Exception:  # noqa: BLE001 - already gone is fine
        logger.warning(
            "cancel_hunting: no registered hunting run %s to cancel (no-op)",
            hunting_run_id,
        )


async def _project_has_live_hunting_run(project_id: str, *, run_id: str | None) -> bool:
    """The ONE-live-run-per-project guard (spec US10): True when the project
    already holds a `running` hunting run OTHER than `run_id`. Enforcement
    point: the pg `hunting_runs` row - the produced/consumed memory
    directories are single-owner, so a second concurrent run must be refused,
    never raced (the run's own row - the API opens it before scheduling the
    bootstrap - never trips the guard). Fail-open: with pg unavailable the
    guard cannot fire and the run proceeds (the row open would have failed
    too)."""
    from polymerhus.app.clients import pg  # noqa: PLC0415

    try:
        rows = await asyncio.to_thread(pg.list_hunting_runs, project_id)
    except Exception as exc:  # noqa: BLE001 - fail-open: no pg, no guard
        logger.warning(
            "start_hunting: live-run guard unavailable (%s); proceeding (fail-open)",
            exc,
        )
        return False
    return any(
        r.get("status") == "running" and r.get("hunting_run_id") != run_id
        for r in rows
    )


def _cancel_run_sessions(run_id: str) -> None:
    """Cancel EVERY session of the run by session id through the shared
    control plane (ADR "Run lifecycle": stop cancels every session - the
    orchestrator, the run-scoped surfer - itself a session - and every hunter
    and pod, keyed by the Q13 ids). The outer bootstrap task (registered
    under `hunting:<run_id>` or the bare `run_id` by the launch surface) is a
    session of the run too and is cancelled with the rest. Fail-open: no
    active runtime or an already-settled session is a safe no-op."""
    runtime = _app_runtime()
    if runtime is None:
        return
    from polymerhus.attack.hunting.surfer import is_run_session_id  # noqa: PLC0415

    for session_id in list(runtime.run_ids("hunting")):
        if is_run_session_id(session_id, run_id):
            try:
                runtime.cancel_run("hunting", session_id)
            except Exception:  # noqa: BLE001 - already settled is a no-op
                logger.warning(
                    "cancel_run_sessions: no live session %s to cancel (no-op)",
                    session_id,
                )


async def _await_session_outcome(outcome) -> None:
    """Await one session's outcome regardless of its kind: an asyncio task or
    future is awaited directly; a `concurrent.futures.Future` (the real
    `RuntimeManager.schedule` return) is wrapped onto the loop. `None` (the
    session was not admitted) awaits to nothing."""
    if outcome is None:
        return
    if not hasattr(outcome, "result"):
        # an asyncio task/future - awaits natively
        await outcome
        return
    import concurrent.futures

    if isinstance(outcome, concurrent.futures.Future):
        await asyncio.wrap_future(outcome)
    else:
        await outcome


async def _wait_no_run_sessions(control, run_id: str, interval: float) -> None:
    """Wait until NO COMPONENT session of the run remains live in the control
    plane's registry - the "all its component sessions have settled" state the
    run terminal requires (ADR "Run lifecycle"). Cancellation-aware: a stop
    cancels every session, and the sleeps here surface the cancellation.

    The wait targets the ADR Q13 component sessions ONLY
    (`hunting:<run_id>:orchestrator|surfer|hunt:...|pod:...`), never the run's
    OUTER BOOTSTRAP markers (`run_id` / `hunting:<run_id>`): the bootstrap task
    that CALLS this wait is itself registered under `hunting:<run_id>`, so
    counting it would make the run wait on its OWN registry entry forever
    (a live-stack deadlock the contract fakes never exposed - real-runtime
    finding, 2026-08-25)."""
    from polymerhus.attack.hunting.surfer import is_run_session_id  # noqa: PLC0415

    prefix = f"hunting:{run_id}:"
    while any(
        is_run_session_id(sid, run_id) and sid.startswith(prefix)
        for sid in control.live_session_ids()
    ):
        await asyncio.sleep(interval)


def _resolve_gate(control, gate_seam) -> object:
    """The hunting dispatch gate (Q15) for the run's session coroutines: an
    explicitly injected gate wins (tests); otherwise the control plane's own
    gate resolves from its bound runtime (the SAME gate its admission uses);
    no gate degrades to None (sessions run ungated - with a fake control the
    fake owns its own pacing)."""
    if gate_seam is not None:
        return gate_seam
    resolver = getattr(control, "gate", None)
    if resolver is None:
        return None
    try:  # noqa: BLE001 - a failing gate read degrades to ungated
        return resolver()
    except Exception as exc:
        logger.warning(
            "start_hunting: gate resolution failed (%s); sessions run "
            "ungated (fail-open)", exc,
        )
        return None


def _default_hunter_builder(*, run_id, project_id, hunt_store, hunter_store, **kw):
    """The production hunt-session builder seam (T4): the #164 W5 harness
    (`build_actor_hunting_agent`'s dispatch) with the real memory store, the
    project's live read-only graph view, the real Kali-container exec seam
    (the pod's `default_exec_fn`, reused verbatim), and the config-gated
    `query_lightrag` KB tool (binds inside when `HUNTING_LIGHTRAG_TOOL` is
    on). Returns `(dispatch_fn, registry)`; the caller reaps the registry at
    the session's end."""
    from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphView
    from polymerhus.attack.hunting.pod.tools import default_exec_fn

    return build_production_hunting_agent(
        store=hunt_store, run_id=run_id, project_id=project_id,
        memory_store=hunter_store,
        graph_view_fn=ReadOnlyGraphView(project_id).read,
        exec_fn=default_exec_fn,
    )


async def _default_pod_builder(spec, *, run_id, project_id, memory_store, spec_id):
    """The production pod-session builder seam (T4): `arun_pod` with the
    run's pod memory store and the semantic `<fault>_<strategy>` spec id (ADR
    Q13). The pod never raises into the run (IA-4); the surfer's wrapper adds
    the export-delivery ring on top."""
    from polymerhus.attack.hunting.pod.pod import arun_pod  # noqa: PLC0415

    return await arun_pod(
        spec, run_id=run_id, memory_store=memory_store,
        project_id=project_id, spec_id=spec_id,
    )


async def start_hunting(
    project_id: str,
    *,
    run_id: str | None = None,
    candidates: list | tuple | None = None,
    tools=None,
    control=None,
    gate=None,
    tick_interval: float | None = None,
    hunt_store=None,
    hunter_store=None,
    pod_store=None,
    hunter_builder=None,
    pod_builder=None,
    orchestrator_fn=None,
    fault_entries=None,
    read_fn=None,
    match_fn=None,
    unit_ids_fn=None,
    **orchestration_kwargs,
) -> str | None:
    """The hunting bootstrap entry point (seam 3.1) - rewired by T4 (#173).

    Schedules nothing itself - the control plane (or the marshalling harness)
    drives it onto the hunting loop. Sets the hunting module context for its
    full duration, enforces ONE live hunting run per project (refused with a
    `None` return on a second concurrent run), opens the `hunting_runs` row
    (`running`), schedules TWO sessions on the shared control plane - the
    orchestrator pass (ADR Q13 id `hunting:<run_id>:orchestrator`) and the
    run-scoped inbox surfer (id `hunting:<run_id>:surfer`, ADR Q2a) - and then
    waits for quiesce: the pass has settled, the surfer has proven the
    produced dirs drained and every dispatched session (hunter, pod) settled,
    the remaining idle hunters are settled, and ONLY then is `complete`
    persisted. `failed` persists when a session was not admitted or a
    collaborator degrades. The run-scoped surfer dispatches one hunter per
    ratified config and one pod per specified spec through the mover, and the
    hunt sessions idle-loop over their inboxes (verdict handling stubbed,
    ADR Q16) - the whole pipeline is observable through this coroutine.

    Fail-open: a collaborator failure (PG row, default tools, a session's
    admission, the run itself) degrades to a terminal status - this coroutine
    never raises through the control plane. An EXTERNAL cancellation (stop)
    is re-raised after teardown so `stop_hunting` can stamp `stopped`.

    Injectable seams (CODING_STANDARD s6): `control` is the session-capable
    control plane (`RuntimeControlPlane` default), `gate` the hunting dispatch
    gate (Q15), `hunt_store` / `hunter_store` / `pod_store` the memory stores,
    `hunter_builder` / `pod_builder` / `orchestrator_fn` the produce seams,
    `fault_entries` / `read_fn` / `match_fn` / `unit_ids_fn` the #200
    selection seams (injected by tests; the production defaults load the
    real fault-KB and read the live L1), and `tick_interval` the surfer's lap
    period - the contract-tier tests inject fakes for all of them and never
    touch a live driver.

    #200 selection wiring: an EMPTY `candidates` batch (the `POST /hunting`
    default) triggers the platform's OWN FaultSource selection over the live
    L1 - `materialize_candidates` enumerates the project's kind-qualified
    units, loads the fault-KB matching facet, runs the deterministic stage
    with the pass-through match, and translates the survivors into the pass's
    intake. A non-empty caller batch is the override, never re-selected. The
    selection summary is recorded via `trace_gate_step` + a log line, so an
    all-pruned empty launch is a MEANINGFUL empty pass - never a vacuous one.

    Returns the `hunting_run_id`, or `None` when the ONE-live-run-per-project
    guard refused the launch. The run id keys both the `hunting_runs` row and
    the project's memory-store folders."""
    async with hunting_module_context():
        from polymerhus.app.clients import pg  # noqa: PLC0415
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            OrchestratorTools,
            ReadOnlyGraphView,
            _reap_orchestrator,
        )
        from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
        from polymerhus.attack.hunting.hunter_memory import (  # noqa: PLC0415
            HunterMemoryStore,
        )
        from polymerhus.attack.hunting.mover import (  # noqa: PLC0415
            RuntimeControlPlane,
            orchestrator_session_id,
        )
        from polymerhus.attack.hunting import surfer as surfer_mod  # noqa: PLC0415
        from polymerhus.attack.hunting.surfer import (  # noqa: PLC0415
            RunDispatchState,
            build_run_dispatch,
            post_settle,
            run_surfer_loop,
            surfer_session_id,
        )

        hunting_run_id = run_id

        # ONE live hunting run per project (spec US10): the pg `hunting_runs`
        # row is the enforcement point (the produced/consumed directories are
        # single-owner). The current run's own row (the API opens it before
        # scheduling) never trips the guard.
        if await _project_has_live_hunting_run(project_id, run_id=hunting_run_id):
            logger.warning(
                "start_hunting: a live hunting run already exists for project "
                "%s; launch refused (one live run per project)",
                project_id,
            )
            # The launch surface opened the run's row BEFORE scheduling (the
            # creation marker, ADR Q6 "at-most-once"): a refusal here must not
            # leave that `running` row behind as an orphan, so close it to a
            # terminal status in-band (T5 orphan resolution). No row was
            # opened when `run_id` is None (the row-open fail-open path never
            # had one to refuse).
            if hunting_run_id is not None:
                try:
                    await asyncio.to_thread(
                        pg.set_hunting_run_status, hunting_run_id, "failed"
                    )
                except Exception:  # noqa: BLE001 - best-effort orphan close
                    logger.warning(
                        "start_hunting: could not close the refused run row %s "
                        "(fail-open)", hunting_run_id,
                    )
            return None

        if hunting_run_id is None:
            try:
                # Blocking-sync-PG offloads onto the shared executor (#123): the
                # accessor opens/connects a psycopg connection, so it must never
                # block the worker loop.
                hunting_run_id = await asyncio.to_thread(
                    pg.create_hunting_run, project_id
                )
            except Exception:  # noqa: BLE001 - fail-open when PG is down
                logger.warning(
                    "start_hunting: could not open the hunting_runs row; "
                    "running unlogged (fail-open)"
                )
                hunting_run_id = str(uuid.uuid4())

        # The stores (s6: injectable, real defaults). The pod store is the
        # per-project root (D84-33); the explicit-root constructors are kept
        # for the tests.
        if hunt_store is None:
            hunt_store = HuntStore()
        if hunter_store is None:
            hunter_store = HunterMemoryStore()
        if pod_store is None:
            try:
                from polymerhus.attack.hunting.pod.pod_memory import (  # noqa: PLC0415
                    PodMemoryStore,
                )
                pod_store = PodMemoryStore(project_id=project_id)
            except Exception as exc:  # noqa: BLE001 - fail-open: no pod memory
                logger.warning(
                    "start_hunting: pod memory store unavailable (%s); "
                    "pods run without one (fail-open)", exc,
                )
                pod_store = None

        if tools is None:
            try:
                tools = OrchestratorTools(
                    store_reads=hunt_store,
                    graph_view=ReadOnlyGraphView(project_id),
                )
            except Exception:  # noqa: BLE001 - fail-open tools default
                logger.warning(
                    "start_hunting: default tools unavailable; the gate will "
                    "ground on the candidate set alone (fail-open)"
                )
                tools = OrchestratorTools(store_reads=hunt_store, graph_view=None)

        # The shared control plane + the hunting dispatch gate (Q12/Q15).
        control = control if control is not None else RuntimeControlPlane()
        gate = _resolve_gate(control, gate)
        tick_interval = (
            surfer_mod.DEFAULT_SURFER_TICK_INTERVAL
            if tick_interval is None else tick_interval
        )

        state = RunDispatchState()
        coro_for = build_run_dispatch(
            project_id=project_id,
            run_id=hunting_run_id,
            hunt_store=hunt_store,
            hunter_store=hunter_store,
            pod_store=pod_store,
            state=state,
            gate=gate,
            hunter_builder=hunter_builder or _default_hunter_builder,
            pod_builder=pod_builder if pod_builder is not None else _default_pod_builder,
        )

        async def _orchestrator_pass():
            from polymerhus.attack.hunting.fault_source import (  # noqa: PLC0415
                materialize_candidates,
            )
            from polymerhus.attack.hunting.orchestrator_tracing import (  # noqa: PLC0415
                orchestrator_gate_span,
                trace_gate_step,
            )

            with orchestrator_gate_span(hunting_run_id):
                selected, summary = await asyncio.to_thread(
                    materialize_candidates,
                    project_id, candidates,
                    fault_entries=fault_entries, read_fn=read_fn,
                    match_fn=match_fn, unit_ids_fn=unit_ids_fn,
                )
                trace_gate_step(
                    "selection",
                    input={"project_id": project_id,
                           "caller_supplied": summary.caller_supplied},
                    output={
                        "faults_evaluated": summary.faults_evaluated,
                        "units_minted": summary.units_minted,
                        "pruned_by_predicate": summary.pruned_by_predicate,
                        "pruned_by_tag": summary.pruned_by_tag,
                        "passed": summary.passed,
                    },
                )
            if orchestrator_fn is not None:
                return await orchestrator_fn(
                    project_id, hunting_run_id, selected, tools,
                    **orchestration_kwargs,
                )
            from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
                arun_orchestration,
            )
            return await arun_orchestration(
                project_id, hunting_run_id, selected, tools,
                **orchestration_kwargs,
            )

        async def _surfer_loop():
            return await run_surfer_loop(
                project_id, hunting_run_id,
                hunt_store=hunt_store,
                hunter_store=hunter_store,
                control=control,
                coro_for=coro_for,
                state=state,
                tick_interval=tick_interval,
            )

        status = None
        try:
            orchestrator_id = orchestrator_session_id(hunting_run_id)
            surfer_id = surfer_session_id(hunting_run_id)
            orchestrator_outcome = control.start_session(
                orchestrator_id, _orchestrator_pass())
            if orchestrator_outcome is None:
                logger.warning(
                    "start_hunting: orchestrator session %s not admitted; "
                    "run degrades to 'failed'", orchestrator_id,
                )
                status = "failed"
            else:
                surfer_outcome = control.start_session(surfer_id, _surfer_loop())
                if surfer_outcome is None:
                    # Without the surfer no dispatch can ever happen: the run
                    # can never reach quiesce, so it must fail now.
                    logger.warning(
                        "start_hunting: surfer session %s not admitted; "
                        "run degrades to 'failed'", surfer_id,
                    )
                    control.cancel_session(orchestrator_id)
                    status = "failed"
                else:
                    await _await_session_outcome(orchestrator_outcome)
                    await _await_session_outcome(surfer_outcome)
                    # Quiesce is proven: the surfer settled only when the
                    # orchestrator was done, produced held no dispatchable
                    # item, no pod was live, and no hunter was mid-graph.
                    # Settle the remaining idle hunters and wait for every
                    # run session to leave the registry (ADR "Run lifecycle":
                    # terminal only when ALL component sessions have settled).
                    post_settle(state)
                    await _wait_no_run_sessions(control, hunting_run_id,
                                                tick_interval)
                    status = "complete"
        except asyncio.CancelledError:
            status = None  # external stop: stop_hunting stamps 'stopped'
            raise
        except Exception:  # noqa: BLE001 - fail-open: land a terminal status
            logger.exception(
                "start_hunting: run %s degraded; persisting 'failed'",
                hunting_run_id,
            )
            status = "failed"
        finally:
            try:
                await _reap_orchestrator(hunting_run_id)
            except Exception:  # noqa: BLE001 - teardown must never raise
                logger.warning(
                    "start_hunting: actor reap failed for %s (fail-open)",
                    hunting_run_id,
                )
            flush_hunting_checkpointer()
            if status is not None:
                try:
                    await asyncio.to_thread(
                        pg.set_hunting_run_status, hunting_run_id, status
                    )
                except Exception:  # noqa: BLE001 - fail-open
                    logger.warning(
                        "start_hunting: could not persist %r for %s (fail-open)",
                        status,
                        hunting_run_id,
                    )
        return hunting_run_id


def build_production_hunting_agent(*, store, run_id, project_id="",
                                   target_url=None, graph_view_fn=None,
                                   memory_store=None, checkpointer=None,
                                   model_factory=None, observe: bool = True,
                                   exec_fn=None):
    """The production default hunting-agent dispatch seam (as of #164 W5): the
    turn-by-turn ReAct harness wired to the real `query_lightrag` KB tool (the
    lightrag branch's single KB tool, config-gated by `HUNTING_LIGHTRAG_TOOL`),
    the real Kali-container exec seam, and the per-project hunter memory store.
    Construction performs no I/O (everything heavy resolves on first use).

    Returns `(dispatch_fn, registry)`; the caller must reap the registry
    (`stop_all`) when the run's orchestration finishes."""
    from polymerhus.attack.hunting.llm import build_actor_hunting_agent  # noqa: PLC0415

    return build_actor_hunting_agent(
        run_id=run_id,
        project_id=project_id,
        memory_store=memory_store,
        graph_view_fn=graph_view_fn,
        kb_fn=None,  # the KB seam: the harness binds the config-gated query_lightrag tool
        exec_fn=exec_fn,  # None -> the harness's default fail-open exec seam (the Kali container is a sibling workstream)
        checkpointer=checkpointer,
        model_factory=model_factory,
        observe=observe,
    )


async def stop_hunting(hunting_run_id: str) -> None:
    """Run stop (seam 3.1, ADR "Run lifecycle"): cancel EVERY session of the
    run through the shared control plane - per-session cancel by id (the
    orchestrator pass, the run-scoped surfer - itself a session - and every
    hunter and pod, plus the outer bootstrap task) - then reap the run's
    actor and persist `stopped`. The per-project store preserves the partial
    config/notes trail. Fail-open: never raises through the control plane.

    Cancellation is ASYNC (a session receives `CancelledError` only at its
    next `await` point), so BEFORE persisting `stopped` the run must WAIT for
    its component sessions to leave the registry - the same drain the normal
    terminal path performs (`_wait_no_run_sessions`). Otherwise the run row
    is stamped `stopped` while a mid-graph hunter is still registered, and a
    per-session verb on that namespace still answers (live-stack finding,
    2026-08-26)."""
    async with hunting_module_context():
        from polymerhus.app.clients import pg  # noqa: PLC0415
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            _reap_orchestrator,
        )
        from polymerhus.attack.hunting.mover import (  # noqa: PLC0415
            RuntimeControlPlane,
        )

        _cancel_run_sessions(hunting_run_id)
        try:
            await asyncio.wait_for(
                _wait_no_run_sessions(
                    RuntimeControlPlane(), hunting_run_id, interval=0.5),
                timeout=30.0,
            )
        except Exception:  # noqa: BLE001 - fail-open: the drain is best-effort
            logger.warning(
                "stop_hunting: session-drain wait for %s did not settle within "
                "30s (fail-open)", hunting_run_id,
            )
        try:
            await _reap_orchestrator(hunting_run_id)
        except Exception:  # noqa: BLE001 - fail-open
            logger.warning(
                "stop_hunting: actor reap failed for %s (fail-open)", hunting_run_id
            )
        try:
            await asyncio.to_thread(pg.set_hunting_run_status, hunting_run_id, "stopped")
        except Exception:  # noqa: BLE001 - fail-open
            logger.warning(
                "stop_hunting: could not persist 'stopped' for %s (fail-open)",
                hunting_run_id,
            )


def flush_hunting_checkpointer() -> None:
    """The tear-down flush hook (seam 3.1, #123): archive the hunting module's
    in-memory checkpointer index into the still-open #94 pooled saver via the
    SHARED `flush_module_index("hunting")` seam (`polymerhus.app.llm.checkpoints`),
    never a private hunting-only path. Fail-open: never raises."""
    try:
        from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
            flush_module_index,
        )
        flush_module_index("hunting")
    except Exception as exc:  # noqa: BLE001 - fail-open hook, never raises
        logger.warning("flush_hunting_checkpointer: flush failed (fail-open): %s", exc)
