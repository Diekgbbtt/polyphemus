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
                             modeller pass AND the run-scoped inbox surfer
                             as sessions on the shared runtime manager (ADR
                             #169 Q2a/Q12), waits for quiesce (the pass done,
                             produced dirs drained, every dispatched session
                             settled), and persists the terminal status.
                             As of T3 (#376) the pass runs over the run's OWN
                             INTAKE: the L1 inventory read and frozen at run
                             start, ordered by live L1 edge count, with the
                             completed/in-flight exclusions applied - and the
                             run's symbolic accumulator, halt and resume state
                             land on the run row's `stats` (the run record,
                             S2 9.2) after every unit. A run row that already
                             carries a run record RESUMES it (S1 7.5). It is
                             the only place the intake, the halt and the record
                             meet: the store never reads it and the surfer
                             never writes it.
                             Fail-open: a collaborator failure never raises
                             through the control plane - it lands a terminal
                             status. The blocking-sync-pg calls
                             (`create_hunting_run`, `set_hunting_run_status`,
                             `set_hunting_run_stats`, `get_hunting_run`,
                             `list_hunting_runs`) offload via
                             `asyncio.to_thread` onto the shared executor,
                             never the worker loop.
  stop_hunting             - the run stop (ADR #169 "Run lifecycle"): cancels
                             EVERY session of the run by session id through the
                             shared control plane (the modeller pass, the
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

from collections.abc import Mapping

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from typing import Any, Coroutine

    from polymerhus.app.llm.checkpoints import FlushResult
    from polymerhus.attack.hunting.run_lifecycle import ThreatModelRun
    from polymerhus.attack.hunting.unit_intake import (
        IntakePlan,
        IntakeUnit,
        L1ReadFn,
    )

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
    gate already failed closed when no manager is active.

    #332 (same class as #328): a drain settles the hunting module to `stopped`
    (terminal), which `schedule` refuses. A launch is the operator's intent to
    hunt, so the SHARED `ensure_running` precondition revives a stopped module
    before scheduling instead of failing on an admission refusal; a deliberate
    pause is left alone (only the terminal `stopped` state is revived). The
    revive sits inside the launch adapter's guard, so a `RuntimeLoopNotRunning`
    raised in the shutdown window (the active runtime is still published while
    its worker loop is already cleared) maps to a 503, never an unhandled 500."""
    runtime = _require_runtime()
    runtime.ensure_running("hunting")
    return runtime.schedule("hunting", coro, name=name)


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


# The provider-pause keys the run row's stats carry (#331). The stats merge is
# ADDITIVE, so nothing ever clears them: a resumed run that completes must NULL
# them explicitly, or the eval keeps reading a stale `interrupt_reason` for a run
# that finished (M7).
CLEARED_INTERRUPT_STATS: dict[str, None] = {
    "interrupted": None,
    "interrupt_reason": None,
    "provider_status": None,
    "quota_exhausted": None,
    "retry_after_s": None,
}


def _provider_interrupt_stats(err) -> dict:
    """The run-row `stats` recorded when a provider failure pauses the run. It
    serves both a provider-caused pass abort (#331) and a dispatched
    hunter/pod child-session provider failure (#312). It carries the
    classifier's own cause (`interrupt_reason`) plus the machine-readable fields
    the resume policy consumes - the HTTP status and the `quota_exhausted` flag -
    so a transient throttle (429, resumable) is distinguishable from consumed
    credits (terminal) after the process that saw the failure is gone. A
    provider caused abort from a fake/test seam without a typed error still
    records an honest generic reason."""
    if err is not None:
        return {
            "interrupted": True,
            "interrupt_reason": err.interrupt_reason(),
            "provider_status": err.status_code,
            "quota_exhausted": err.quota_exhausted,
            "retry_after_s": err.retry_after_s,
        }
    return {
        "interrupted": True,
        "interrupt_reason": "hunting pass aborted on a provider failure",
        "provider_status": None,
        "quota_exhausted": None,
        "retry_after_s": None,
    }


async def stop_hunting_for_provider_failure(
    control,
    hunting_run_id: str,
    *,
    error=None,
    tick_interval: float | None = None,
    drain_timeout: float = 30.0,
) -> None:
    """The ONE app-layer provider-failure handler for a hunting run (#331,
    stop-only).

    On a provider failure this handler STOPS the run's affected sessions with
    the shared runtime's per-session `cancel_run` primitive (reached through the
    control plane's `cancel_session`), FLUSHES their threads through the shared
    run-scoped chokepoint (`flush_run_scoped`), and stamps the run the resumable
    terminal `interrupted` - never `failed` - with the accurate cause
    (`_provider_interrupt_stats`: `interrupt_reason` + `provider_status` +
    `quota_exhausted` + `retry_after_s`).

    Per agent type (ADR Q13 session id): the modeller pass, every hunter and
    every pod are RUNNING LLM agents and are hard-cancelled. The surfer mover has
    no LLM, but it WOULD keep dispatching hunters and pods, so it is cancelled
    with them - the whole run stops rather than leaving a live dispatcher behind
    (the first #331 slice stamped `interrupted` and raced the still-live surfer).
    `hold_session` is the runtime's PAUSE verb, used by the per-session API for a
    resumable in-process pause; the stop-only path deliberately does not hold,
    because it terminalizes the run. The resume ticket reintroduces the hold for
    the types it keeps (see `docs/design/331-stop-only-resume-assessment-adr.md`).

    DRAIN before stamping: cancellation is delivered only at a session's next
    await, so the handler waits until no component session of the run remains
    live before the terminal lands. Fail-open: every leg (cancel, drain, reap,
    flush, stamp) is guarded, so a provider failure always lands a terminal and
    never raises through the control plane.
    """
    from polymerhus.app.clients import pg  # noqa: PLC0415
    from polymerhus.attack.hunting.threat_modeller import (  # noqa: PLC0415
        _reap_modeller,
    )
    from polymerhus.attack.hunting import surfer as surfer_mod  # noqa: PLC0415
    from polymerhus.attack.hunting.surfer import is_run_session_id  # noqa: PLC0415
    from polymerhus.app.llm.checkpoints import flush_run_scoped  # noqa: PLC0415

    interval = (
        surfer_mod.DEFAULT_SURFER_TICK_INTERVAL
        if tick_interval is None else tick_interval
    )

    # STOP: per-session cancel on every live COMPONENT session of the run. The
    # filter mirrors `_wait_no_run_sessions`: only the ADR Q13 component sessions
    # (`hunting:<run_id>:threat-modeller|surfer|hunt:...|pod:...`, plus the
    # legacy `orchestrator` segment for one window) are cancelled - never the
    # run's outer bootstrap marker (`run_id` / `hunting:<run_id>`), which is the
    # task RUNNING this handler (cancelling it would abort mid-stamp).
    component_prefix = f"hunting:{hunting_run_id}:"
    for session_id in list(control.live_session_ids()):
        if not (
            is_run_session_id(session_id, hunting_run_id)
            and session_id.startswith(component_prefix)
        ):
            continue
        try:
            control.cancel_session(session_id)
        except Exception:  # noqa: BLE001 - already settled is a safe no-op
            logger.warning(
                "stop_hunting_for_provider_failure: no live session %s to "
                "cancel (no-op)", session_id,
            )

    # DRAIN: cancellation is async, so wait until the run's sessions settle.
    try:
        await asyncio.wait_for(
            _wait_no_run_sessions(control, hunting_run_id, interval),
            timeout=drain_timeout,
        )
    except Exception:  # noqa: BLE001 - fail-open: the drain is best-effort
        logger.warning(
            "stop_hunting_for_provider_failure: session drain for %s did not "
            "settle within %ss (fail-open)", hunting_run_id, drain_timeout,
        )

    # Reap the run's modeller actor so it cannot hot-loop after the pause.
    # BOUNDED by the same `drain_timeout` as the drain: the actor's task
    # finishes only after its in-flight turn does, so an unbounded await would
    # delay the resumable terminal behind a stalled probe/model turn. A
    # timed-out reap cancels the actor's task (`_reap_modeller`'s finally), so
    # no live turn outlives the pause.
    try:
        await asyncio.wait_for(
            _reap_modeller(hunting_run_id), timeout=drain_timeout)
    except TimeoutError:
        logger.warning(
            "stop_hunting_for_provider_failure: actor reap for %s did not "
            "settle within %ss; the actor task was cancelled (fail-open)",
            hunting_run_id, drain_timeout,
        )
    except Exception:  # noqa: BLE001 - teardown must never raise
        logger.warning(
            "stop_hunting_for_provider_failure: actor reap failed for %s "
            "(fail-open)", hunting_run_id,
        )

    # FLUSH: archive the run's committed threads before the terminal lands, so
    # the pre-failure checkpoint is durable for the (future) resume.
    try:
        await flush_run_scoped("hunting", hunting_run_id)
    except Exception:  # noqa: BLE001 - fail-open: never block the terminal
        logger.warning(
            "stop_hunting_for_provider_failure: flush failed for %s (fail-open)",
            hunting_run_id,
        )

    # STAMP the resumable terminal with the accurate provider cause.
    try:
        await asyncio.to_thread(
            pg.set_hunting_run_status, hunting_run_id, "interrupted",
            stats=_provider_interrupt_stats(error),
        )
    except Exception:  # noqa: BLE001 - fail-open
        logger.warning(
            "stop_hunting_for_provider_failure: could not persist 'interrupted' "
            "for %s (fail-open)", hunting_run_id,
        )


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


def _read_only_l1_read(project_id: str) -> "L1ReadFn | None":
    """The read-only L1 graph read seam (never a write-capable client).

    Shared by the modeller's grounding provider and the run's INTAKE read (S1
    7.1: the runtime reads the L1 inventory at run start); a failed construction
    leaves the seam None and its consumer degrades fail-open."""
    try:
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            ReadOnlyGraphView,
        )

        return ReadOnlyGraphView(project_id).read
    except Exception:  # noqa: BLE001 - fail-open: the read degrades
        logger.warning(
            "start_hunting: L1 read seam unavailable for project %s; the "
            "grounding and the intake degrade (fail-open)", project_id,
        )
        return None


def _read_model_document(store: Any, project_id: str, unit_id: str) -> dict | None:
    """The persisted model for `unit_id`, fail-open to None (a degraded read is
    an unknown model, never a raise into the run)."""
    read = getattr(store, "read_model", None) if store is not None else None
    if not callable(read):
        return None
    try:
        return read(project_id, unit_id)
    except Exception as exc:  # noqa: BLE001 - fail-open is the read contract
        logger.warning(
            "hunting: threat model read for %s degraded (%s)", unit_id, exc)
        return None


def _produced_run_statuses(
    project_id: str, produced: Sequence[Mapping[str, str]],
) -> dict[str, str]:
    """The producing runs' statuses for the intake freeze (S2 9.3).

    Blocking pg read (the caller offloads). Fail-open: with no readable row the
    status map stays empty, and the freeze then treats the produced model as
    in-flight - it never destroys a model it cannot attribute. A run id with no
    row (the modeller-only launch writes models under a run that never opened a
    row) is therefore never mistaken for a stale one.
    """
    run_ids = {str(entry.get("run_id") or "") for entry in produced}
    run_ids.discard("")
    if not run_ids:
        return {}
    try:
        from polymerhus.app.clients import pg  # noqa: PLC0415

        rows = pg.list_hunting_runs(project_id)
    except Exception as exc:  # noqa: BLE001 - fail-open: unknown stays in-flight
        logger.warning(
            "hunting: run-status read for project %s degraded (%s); produced "
            "models are treated as in-flight (fail-open)", project_id, exc,
        )
        return {}
    return {
        str(row.get("hunting_run_id")): str(row.get("status"))
        for row in rows
        if row.get("hunting_run_id") in run_ids
    }


def _freeze_intake(
    store: Any, project_id: str, units: Sequence[IntakeUnit],
) -> IntakePlan:
    """The intake freeze (S1 7.1, S2 9.3): the exclusions from the store's
    consumed/produced families and the producing runs' statuses.

    Blocking store/pg reads: the caller offloads. Fail-open per source - a
    degraded read contributes no exclusion, so the run degrades to modelling the
    unit rather than silently skipping it (S1 5.7)."""
    from polymerhus.attack.hunting.unit_intake import (  # noqa: PLC0415
        freeze_intake,
    )

    completed: list[str] = []
    produced: list[dict] = []
    if store is not None:
        try:
            completed = store.read_completed_units(project_id)
        except Exception as exc:  # noqa: BLE001 - fail-open: no exclusion
            logger.warning(
                "hunting: completed-model read for project %s degraded (%s); "
                "no completed exclusion (fail-open)", project_id, exc)
        try:
            produced = store.read_produced_units(project_id)
        except Exception as exc:  # noqa: BLE001 - fail-open: no exclusion
            logger.warning(
                "hunting: produced-model read for project %s degraded (%s); "
                "no in-flight exclusion (fail-open)", project_id, exc)
    archive = getattr(store, "archive_unit", None) if store is not None else None

    def archive_fn(unit_id: str, reason: str):
        """Move the stale produced directory to `abandoned/` (S2 9.3)."""
        return archive(project_id, unit_id, reason) if callable(archive) else None

    return freeze_intake(
        units,
        completed_ids=completed,
        produced=produced,
        run_statuses=_produced_run_statuses(project_id, produced),
        archive_fn=archive_fn if produced else None,
    )


def _resume_intake(
    store: Any, project_id: str, record: Mapping[str, Any],
) -> ThreatModelRun:
    """The resumed run from its persisted record (S1 7.5).

    Blocking store reads: the caller offloads. `risk_total` is recomputed from
    `model_sums` and the models on disk, and every unit at or after the recorded
    position whose model is already complete is adopted rather than re-modelled
    - the crash window between the model commit and the run-record write."""
    from polymerhus.attack.hunting.run_lifecycle import resume_run  # noqa: PLC0415

    order = tuple(str(unit) for unit in record.get("intake_order") or ())
    position = int(record.get("intake_position") or 0)
    models = {
        unit_id: _read_model_document(store, project_id, unit_id)
        for unit_id in order[position:]
    }
    return resume_run(record, models=models)


async def _run_intake(
    project_id: str,
    run_id: str,
    *,
    tools,
    pass_fn,
    pass_kwargs: dict,
    intake_units: Sequence[IntakeUnit] | None = None,
    intake_read_fn: L1ReadFn | None = None,
    record: Mapping[str, Any] | None = None,
    record_fn: Callable[[dict], Awaitable[None]] | None = None,
) -> tuple[list, ThreatModelRun]:
    """Freeze the intake, order it, and model it ONE UNIT AT A TIME (S1 7.1-7.5).

    The run reads the L1 inventory and freezes the unit set (or resumes a
    persisted run record), orders it once, applies the exclusions, and models
    each admitted unit through `pass_fn`. After every unit the run record is
    updated: the model document commits first (inside the pass, through the
    store) and the run record follows, so a crash between the two leaves a
    complete model the resume adopts - never a stale risk total.

    Returns `(outcomes, run)`. A raising pass propagates: the run terminal
    classifies it (the degradation breaker's typed abort, or fail-open
    `failed`)."""
    from polymerhus.attack.hunting import run_lifecycle as lifecycle  # noqa: PLC0415
    from polymerhus.attack.hunting.unit_intake import read_intake  # noqa: PLC0415

    store = getattr(tools, "threat_store", None)
    persisted: dict = dict(record or {})

    async def _write_record() -> None:
        nonlocal persisted
        if record_fn is None:
            return
        current = run.record()
        try:
            await record_fn(current)
            persisted = current
        except Exception as exc:  # noqa: BLE001 - fail-open: the run continues
            logger.warning(
                "hunting run %s: run-record write failed (%s); the total stays "
                "re-derivable from the models on disk", run_id, exc,
            )

    async def _write_record_if_changed() -> None:
        """Persist the record only when a fixed key moved (S2 9.2).

        The unit loop writes the record after every unit, but a RESUME can
        advance the state without a single loop iteration: its adoption may
        recompute the total, adopt a model sum, cross the halt, or find the
        intake already exhausted. Without this write the row would keep the
        pre-crash record for a run that has moved on."""
        current = run.record()
        if any(current.get(key) != persisted.get(key)
               for key in lifecycle.RUN_RECORD_KEYS):
            await _write_record()

    threshold, basis = lifecycle.threshold_config()
    if record:
        run = await asyncio.to_thread(
            _resume_intake, store, project_id, record)
        logger.info(
            "hunting run %s: resumed the intake at position %d of %d "
            "(halt=%s, risk_total=%d)",
            run_id, run.intake_position, len(run.intake_order), run.halt,
            run.accumulator.total,
        )
        await _write_record_if_changed()
    else:
        units = (
            tuple(intake_units) if intake_units is not None
            else await asyncio.to_thread(
                read_intake, project_id, read_fn=intake_read_fn)
        )
        plan = await asyncio.to_thread(
            _freeze_intake, store, project_id, units)
        run = lifecycle.ThreatModelRun.start(
            plan.order, excluded=plan.excluded,
            threshold=threshold, basis=basis,
        )
        logger.info(
            "hunting run %s: froze %d unit(s) (excluded %d, archived %d); "
            "intake order %s",
            run_id, len(plan.order), len(plan.excluded), len(plan.archived),
            list(plan.order),
        )
        await _write_record()

    outcomes: list = []
    while (unit_id := run.next_unit) is not None:
        outcome = await pass_fn(project_id, run_id, unit_id, tools, **pass_kwargs)
        outcomes.append(outcome)
        model = await asyncio.to_thread(
            _read_model_document, store, project_id, unit_id)
        status = getattr(outcome, "status", "")
        if status == "completed" and model is not None:
            run.complete_unit(unit_id, lifecycle.model_sum(unit_id, model))
        else:
            reason = (getattr(outcome, "reason", "")
                      or f"the pass returned {status!r} for this unit")
            run.degrade_unit(unit_id, reason)
        run.keep_trajectory(
            lifecycle.trajectory_entry(unit_id, entry)
            for entry in getattr(outcome, "trail", ())
        )
        await _write_record()
        logger.info(
            "hunting run %s: modelled unit %s (%s); risk_total %d/%d%s",
            run_id, unit_id, status, run.accumulator.total,
            run.accumulator.threshold,
            " HALTED" if run.halt else "",
        )
        if run.halt:
            logger.info(
                "hunting run %s: the risk budget halted the intake at %s; the "
                "blocked unit %s is never modelled",
                run_id, run.crossing_unit, run.blocked_unit,
            )
            break
    # The loop's last iteration already wrote the record; this covers the run
    # that never entered it (an intake already exhausted, or a resume that
    # halted on adoption) and any post-loop state change.
    await _write_record_if_changed()
    return outcomes, run


def _default_modeller_tools(
    project_id: str,
    run_id: str,
    *,
    threat_store: Any = None,
    graph_read_fn: L1ReadFn | None = None,
):
    """The production modeller tool seams (S1 5).

    The per-project `ThreatModelStore`, the RUN-scoped unit cell (the run's ONE
    actor captures its tool surface once, so the cell is what retargets it unit
    by unit), the live unit-projection grounding provider, and the live Kali
    `exec` probe and HTTP-history reads. Every LIVE seam is best-effort: a failed
    import or construction leaves that seam None and its tool degrades fail-open
    in the turn, never a boot failure.

    `graph_read_fn` overrides the grounding read (tests); the default is the
    read-only L1 graph view (`ReadOnlyGraphView`), never a write-capable client."""
    from polymerhus.attack.hunting.threat_modeller import ModellerUnit  # noqa: PLC0415
    from polymerhus.attack.hunting.threat_modeller_tools import (  # noqa: PLC0415
        ModellerTools,
        build_grounding_provider,
    )

    if threat_store is None:
        try:
            from polymerhus.attack.hunting.threat_model_store import (  # noqa: PLC0415
                ThreatModelStore,
            )

            threat_store = ThreatModelStore()
        except Exception:  # noqa: BLE001 - fail-open: the tools degrade
            logger.warning(
                "start_hunting: threat model store unavailable; the modeller "
                "runs with its gate writes degraded (fail-open)"
            )
    if graph_read_fn is None:
        graph_read_fn = _read_only_l1_read(project_id)
    tools = ModellerTools(
        threat_store=threat_store, project_id=project_id, run_id=run_id,
        unit_cell=ModellerUnit(),
        context_provider=build_grounding_provider(project_id, read_fn=graph_read_fn),
    )
    try:
        from polymerhus.attack.hunting.pod.tools import default_exec_fn  # noqa: PLC0415

        tools.exec_fn = default_exec_fn
    except Exception:  # noqa: BLE001 - fail-open: the probe degrades
        logger.warning(
            "start_hunting: Kali exec seam unavailable; `exec` degrades "
            "(fail-open)"
        )
    try:
        from polymerhus.app.clients.kali_http_history import (  # noqa: PLC0415
            default_http_get_fn,
            default_http_search_fn,
        )

        tools.http_search_fn = default_http_search_fn
        tools.http_get_fn = default_http_get_fn
    except Exception:  # noqa: BLE001 - fail-open: the history reads degrade
        logger.warning(
            "start_hunting: HTTP-history seams unavailable; the history reads "
            "degrade (fail-open)"
        )
    return tools


def report_dispatch_gap(
    project_id: str,
    run_id: str,
    outcomes,
    *,
    state,
    threat_store=None,
    hunt_store,
    hunter_store,
    hunter_payload_capable: bool = True,
) -> str | None:
    """Log and return the one-line reason a run that PRODUCED models dispatched
    nothing, or None when there is no gap.

    designed-not-built -> T6 (#379): the per-loop dispatch (a produced loop file
    -> a hunter session) is BUILT (T4 #377), so a produced model's loops
    dispatch. The hunter HARNESS cannot consume the loop payload yet (its
    config consumption is T6's rework), so a loop admitted through the
    production hunter builder degrades instead of hunting. The line names that
    state, so an operator never reads the run's `complete` as "the modeller
    found nothing to hunt".

    The two suppressors are the run's own facts: a hunter dispatch recorded on
    the run state (`state.hunter_inboxes` - an item the mover admitted), and a
    still-dispatchable produced item (`run_work_remaining`, the surfer's own
    predicate). Either one means the gap did not bite.

    `run_work_remaining` is a blocking store read and it is a best-effort READ:
    a transient read failure must not turn the run's terminal path into a raise
    (the caller awaits this inside the quiesce hand-off), so a failed read is
    treated as "no pending work" and the gap line is logged - never silently."""
    from polymerhus.attack.hunting.surfer import (  # noqa: PLC0415
        run_work_remaining,
    )

    completed = [outcome for outcome in outcomes
                 if getattr(outcome, "status", "") == "completed"]
    if not completed or state.hunter_inboxes:
        return None
    try:
        pending = run_work_remaining(
            project_id, run_id, threat_store=threat_store,
            hunt_store=hunt_store, hunter_store=hunter_store,
            hunter_payload_capable=hunter_payload_capable)
    except Exception as exc:  # noqa: BLE001 - a read failure is not a run failure
        logger.warning(
            "hunting run %s: the pending-work read degraded (%s); reporting the "
            "dispatch gap (fail-open)", run_id, exc,
        )
        pending = False
    if pending:
        return None
    loops = _produced_loop_count(threat_store, project_id, run_id)
    if loops and not hunter_payload_capable:
        # C1 (T4a review): the per-loop dispatch is BUILT and inert by design
        # between T4a and T6 - the operator line must say exactly that, so a
        # `complete` with zero hunts is never read as "the modeller found nothing".
        reason = (
            f"{len(completed)} unit model(s) produced and NOTHING is "
            f"dispatchable: {loops} produced loop file(s) await the per-loop "
            "hunter harness, which cannot consume the loop payload yet "
            "(designed-not-built -> T6 #379); this run dispatches zero hunts"
        )
    elif loops:
        reason = (
            f"{len(completed)} unit model(s) produced and NOTHING is "
            f"dispatchable: {loops} produced loop file(s) stayed undispatched "
            "(a stopped role or a refused admission left them produced); this "
            "run dispatches zero hunts"
        )
    else:
        reason = (
            f"{len(completed)} unit model(s) produced and NOTHING is "
            "dispatchable: no dispatchable loop file was produced, and every "
            "model is decided; this run dispatches zero hunts"
        )
    logger.warning("hunting run %s: %s", run_id, reason)
    return reason


def _produced_loop_count(threat_store: Any, project_id: str, run_id: str) -> int:
    """The run's produced loop files, for the dispatch-gap line. Best-effort (a
    read failure counts zero): the terminal path must never raise."""
    if threat_store is None:
        return 0
    try:
        return sum(
            len(entry.get("loops") or ())
            for entry in threat_store.read_produced_loops(project_id)
            if entry.get("run_id") == run_id
        )
    except Exception as exc:  # noqa: BLE001 - a read failure is not a run failure
        logger.warning(
            "hunting run %s: the produced-loop count degraded (%s); reporting "
            "zero (fail-open)", run_id, exc,
        )
        return 0


async def launch_modeller(
    project_id: str,
    *,
    run_id: str,
    intake_units: Sequence[IntakeUnit] | None = None,
    intake_read_fn: L1ReadFn | None = None,
    tools: Any = None,
    threat_store: Any = None,
    graph_read_fn: L1ReadFn | None = None,
    modeller_pass_fn: Callable[..., Awaitable[Any]] | None = None,
    modeller_kwargs: Mapping[str, Any] | None = None,
) -> Any:
    """The modeller-ONLY launch coroutine (spec #169 "Singular component
    launches"): ONE modelling pass over the run's INTAKE and NOTHING else - no
    run-scoped surfer, no dispatch, no `hunting_runs` row. It is the same pass
    body the whole-pipeline bootstrap schedules: the frozen intake's units are
    modelled in order to COMPLETED and their produced loop files land in the
    per-project threat model store. designed-not-built - T4 (#377): no
    production path translates a loop file into a dispatchable item yet, so the
    launch (like the whole-pipeline run) produces models and dispatches nothing.
    The control plane schedules THIS coroutine under the ADR Q13 modeller
    session id (`hunting:<run_id>:threat-modeller`), so the per-session verbs
    (hold/resume/cancel, ADR Q13/Q17) address it like any modeller session.

    designed-for-removal - the launch surface's modeller-only vocabulary (the
    `hunting/orchestrator` endpoint path and the `orchestrator` component label
    it acks with) retires with the component-name hygiene sweep (T10). The
    runtime entry point itself is the modeller pass.

    #376 intake wiring (shared with `start_hunting`): with no injected intake the
    runtime reads the project's L1 inventory (`unit_intake.read_intake` over the
    read-only graph view), freezes the unit set, orders it (live L1 edge count,
    aggregated endpoints, unit id) and excludes the units whose models already
    exist. The retired FaultSource selection path is gone: the intake order IS
    the modelling order.

    This launch has no run row, so it writes NO run record: the run record is the
    `hunting_runs` row's `stats`, and a modeller-only launch has none.

    Fail-open: a modeller failure never raises through the control plane
    (logged). The ONE-live-run-per-project guard (spec #169 US10) covers this
    launch like the whole-pipeline one: with a live run in the project the pass
    is REFUSED with a `None` return, because the per-project produced/consumed
    directories are single-owner and a second pass would race the live run on one
    unit's model. Injectable seams (s6): `modeller_pass_fn` and `modeller_kwargs`
    substitute the pass body / its kwargs for tests."""

    async with hunting_module_context():
        from polymerhus.attack.hunting.threat_modeller import (  # noqa: PLC0415
            arun_modeller_pass,
        )

        # the guard reads pg itself (`_project_has_live_hunting_run`), so this
        # module needs no pg import here
        if await _project_has_live_hunting_run(project_id, run_id=run_id):
            logger.warning(
                "launch_modeller: a live hunting run already exists for project "
                "%s; the modeller-only launch is refused (one live run per "
                "project)", project_id,
            )
            return None
        if tools is None:
            tools = _default_modeller_tools(
                project_id, run_id, threat_store=threat_store,
                graph_read_fn=graph_read_fn)
        try:
            outcomes, _run = await _run_intake(
                project_id, run_id, tools=tools,
                pass_fn=modeller_pass_fn or arun_modeller_pass,
                pass_kwargs=dict(modeller_kwargs or {}),
                intake_units=intake_units,
                intake_read_fn=intake_read_fn,
            )
            return outcomes
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - fail-open into the launch
            logger.exception(
                "launch_modeller: pass %s for project %s degraded (fail-open)",
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


class HunterPayloadNotBuiltError(RuntimeError):
    """The production hunter seam was handed a loop payload it cannot consume
    yet (T4 #377).

    designed-not-built -> T6 (#379): the #164 harness's dispatch seam still
    consumes the retired `HuntConfig` (its grounding render, its tool binding and
    its spec-set store are T6's rework). The per-loop dispatch itself - the
    payload, the session id, the admission move - is complete; until the harness
    is reworked the session DEGRADES on this marker, loudly, instead of the
    launcher fabricating a config from the payload."""


def _default_hunter_builder(*, run_id, project_id, hunter_store, **kw):
    """The production hunt-session builder seam (T4): the #164 W5 harness
    (`build_actor_hunting_agent`'s dispatch) with the real memory store, the
    project's live read-only graph view, the real Kali-container exec seam
    (the pod's `default_exec_fn`, reused verbatim), and the always-bound
    `query_lightrag` KB tool (binds inside; as of #197 the
    `HUNTING_LIGHTRAG_TOOL` gate is REMOVED). Returns `(dispatch_fn, registry)`;
    the caller reaps the registry at the session's end.

    A loop PAYLOAD is refused with `HunterPayloadNotBuiltError` (the T6 marker
    above): the harness still consumes a `HuntConfig`, so passing a payload
    through would dispatch a hunt against the wrong shape. The retiring config
    family passes its config object verbatim and runs as before."""
    from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphView
    from polymerhus.attack.hunting.pod.tools import default_exec_fn
    from polymerhus.app.clients.kali_http_history import (  # noqa: PLC0415
        default_http_get_fn,
        default_http_search_fn,
    )

    dispatch_fn, registry = build_production_hunting_agent(
        run_id=run_id, project_id=project_id,
        memory_store=hunter_store,
        graph_view_fn=ReadOnlyGraphView(project_id).read,
        exec_fn=default_exec_fn,
        http_search_fn=default_http_search_fn,
        http_get_fn=default_http_get_fn,
    )

    async def _dispatch(payload):
        if isinstance(payload, Mapping):
            raise HunterPayloadNotBuiltError(
                "the production hunter harness cannot consume the loop payload "
                "yet (designed-not-built, T6 #379): its dispatch seam still "
                "consumes the retired `HuntConfig`"
            )
        return await dispatch_fn(payload)

    return _dispatch, registry


# The production builder cannot consume the loop payload (T6 #379 reworks the
# harness): `start_hunting` reads this flag and makes the run INERT for the loop
# family (C1) - the loop files stay produced, nothing moves and no model is
# consumed, so no dispatchable work is lost before T6 lands.
_default_hunter_builder.consumes_loop_payload = False  # type: ignore[attr-defined]


async def _default_pod_builder(spec, *, run_id, project_id, memory_store, spec_id):
    """The production pod-session builder seam (T4): `arun_pod` with the
    run's pod memory store and the semantic `<fault>_<strategy>` spec id (ADR
    Q13). The pod never raises a DOMAIN failure into the run (IA-4); a provider
    failure propagates as the typed `ProviderUnavailableError` (#329). The
    surfer's wrapper adds the export-delivery ring on top."""
    from polymerhus.attack.hunting.pod.pod import arun_pod  # noqa: PLC0415
    from polymerhus.app.clients.kali_http_history import default_replay_fn  # noqa: PLC0415

    return await arun_pod(
        spec, run_id=run_id, memory_store=memory_store,
        project_id=project_id, spec_id=spec_id,
        replay_fn=default_replay_fn,
    )


async def start_hunting(
    project_id: str,
    *,
    run_id: str | None = None,
    intake_units: Sequence[IntakeUnit] | None = None,
    intake_read_fn: L1ReadFn | None = None,
    tools: Any = None,
    control: Any = None,
    gate: Any = None,
    tick_interval: float | None = None,
    hunt_store: Any = None,
    hunter_store: Any = None,
    pod_store: Any = None,
    hunter_builder: Callable[..., Any] | None = None,
    pod_builder: Callable[..., Awaitable[Any]] | None = None,
    modeller_pass_fn: Callable[..., Awaitable[Any]] | None = None,
    modeller_kwargs: Mapping[str, Any] | None = None,
    threat_store: Any = None,
    graph_read_fn: L1ReadFn | None = None,
) -> str | None:
    """The hunting bootstrap entry point (seam 3.1) - rewired by T4 (#173),
    then by T2b (#386), then by T3 (#376): the run's pass is the MODELLER's, over
    the run's OWN intake.

    Schedules nothing itself - the control plane (or the marshalling harness)
    drives it onto the hunting loop. Sets the hunting module context for its
    full duration, enforces ONE live hunting run per project (refused with a
    `None` return on a second concurrent run), opens the `hunting_runs` row
    (`running`), schedules TWO sessions on the shared control plane - the
    modeller pass (ADR Q13 id `hunting:<run_id>:threat-modeller`, the legacy
    `orchestrator` segment still accepted as a resume alias for one window) and
    the run-scoped inbox surfer (id `hunting:<run_id>:surfer`, ADR Q2a) - and
    then waits for quiesce: the pass has settled, the surfer has proven the
    produced dirs drained and every dispatched session (hunter, pod) settled,
    the remaining idle hunters are settled, and ONLY then is `complete`
    persisted. The pass models the intake's units ONE AT A TIME (S1 7.1-7.4:
    the freeze, the order, the exclusions, the symbolic accumulator and the
    progressive halt), writing each unit's threat model through the store and
    the run record onto the run row. `failed` persists when a session was not
    admitted or a collaborator degrades. The run-scoped surfer dispatches one
    hunter per ratified config and one pod per specified spec through the mover,
    and the hunt sessions idle-loop over their inboxes (verdict handling
    stubbed, ADR Q16) - the whole pipeline is observable through this coroutine.

    The INTERLEAVE (S1 7.3): the pass and the surfer are independent sessions,
    so the surfer moves and dispatches produced loop files while the pass models
    the next unit. The pass never waits for dispatch: `_run_intake` awaits only
    the pass body, the model read and the run-record write.

    RESUME (S1 7.5): when the run row already carries a run record with an
    `intake_order`, the run RESUMES it - it re-enters at the recorded
    `intake_position`, adopts the models already committed, recomputes
    `risk_total`, and never re-sorts or re-freezes the intake. A halted record
    resumes as halted, so a resumed halted run dispatches and models nothing.

    designed-not-built - T4 (#377): the modeller's produced LOOP FILES are not
    dispatchable yet (no path translates a loop into a hunt config), so a run
    with no pre-produced config models its units and dispatches zero hunts.
    `report_dispatch_gap` logs that state as one run-level line instead of
    letting it pass as a silent `complete`.

    Fail-open: a collaborator failure (PG row, default tools, a session's
    admission, the run itself) degrades to a terminal status - this coroutine
    never raises through the control plane. An EXTERNAL cancellation (stop)
    is re-raised after teardown so `stop_hunting` can stamp `stopped`.

    Injectable seams (CODING_STANDARD s6): `control` is the session-capable
    control plane (`RuntimeControlPlane` default), `gate` the hunting dispatch
    gate (Q15), `hunt_store` / `hunter_store` / `pod_store` the memory stores,
    `threat_store` / `graph_read_fn` the modeller's store and its grounding read
    seam, `tools` the whole modeller tool seam, `modeller_pass_fn` /
    `modeller_kwargs` the pass body and its turn seam, `hunter_builder` /
    `pod_builder` the produce seams, `intake_units` the frozen unit snapshot
    (tests; the production path reads the L1 inventory through `intake_read_fn`,
    which defaults to the same read-only seam as the grounding read), and
    `tick_interval` the surfer's lap period - the contract-tier tests inject
    fakes for all of them and never touch a live driver.

    Returns the `hunting_run_id`, or `None` when the ONE-live-run-per-project
    guard refused the launch. The run id keys both the `hunting_runs` row and
    the project's memory-store folders."""
    async with hunting_module_context():
        from polymerhus.app.clients import pg  # noqa: PLC0415
        from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
        from polymerhus.attack.hunting.hunter_memory import (  # noqa: PLC0415
            HunterMemoryStore,
        )
        from polymerhus.attack.hunting.mover import (  # noqa: PLC0415
            RuntimeControlPlane,
            threat_modeller_session_id,
        )
        from polymerhus.attack.hunting.threat_modeller import (  # noqa: PLC0415
            ThreatModellerDegradedError,
            _reap_modeller,
            arun_modeller_pass,
        )
        from polymerhus.attack.hunting import surfer as surfer_mod  # noqa: PLC0415
        from polymerhus.attack.hunting.surfer import (  # noqa: PLC0415
            RunDispatchState,
            build_run_dispatch,
            post_settle,
            run_surfer_loop,
            surfer_session_id,
        )
        from polymerhus.app.llm.provider_failure import (  # noqa: PLC0415
            ProviderUnavailableError,
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
            tools = _default_modeller_tools(
                project_id, hunting_run_id, threat_store=threat_store,
                graph_read_fn=graph_read_fn)
        if intake_read_fn is None:
            # the intake reads the SAME read-only L1 view as the grounding read
            # unless a caller injects its own seam (never the write-capable
            # client, and never a second live read of its own)
            intake_read_fn = graph_read_fn or _read_only_l1_read(project_id)

        # The shared control plane + the hunting dispatch gate (Q12/Q15).
        control = control if control is not None else RuntimeControlPlane()
        gate = _resolve_gate(control, gate)
        tick_interval = (
            surfer_mod.DEFAULT_SURFER_TICK_INTERVAL
            if tick_interval is None else tick_interval
        )

        # Register the run's agent sub-modules (#317) on the shared manager -
        # each declared role with its own state + gate, keyed per run. The role
        # vocabulary is read from the single source (the module handle's
        # declared `agent_roles`, seeded from `app.runtime`), never re-listed
        # here. Idempotent and state-preserving: an operator stop that landed
        # before the boot is not reset. Fail-open when no manager is active (the
        # module-runtime-only production path always has one).
        manager = _app_runtime()
        if manager is not None:
            try:
                declared_roles = manager.handle("hunting").agent_roles
            except Exception as exc:  # noqa: BLE001 - fail-open: no role handles
                logger.warning(
                    "start_hunting: could not resolve the declared hunting roles "
                    "(%s); no role handles registered (fail-open)", exc,
                )
                declared_roles = ()
            for role in declared_roles:
                try:
                    manager.register_agent_submodule(
                        "hunting", hunting_run_id, role)
                except Exception as exc:  # noqa: BLE001 - fail-open: no role handle
                    logger.warning(
                        "start_hunting: could not register role %s for run %s "
                        "(%s); role ungated (fail-open)",
                        role, hunting_run_id, exc,
                    )

        run_threat_store = getattr(tools, "threat_store", None) or threat_store
        resolved_hunter_builder = hunter_builder or _default_hunter_builder
        # C1: whether the run's hunter can consume the loop payload decides the
        # loop family's dispatchability - a builder that cannot (the production
        # harness until T6) leaves the run inert rather than consuming the work.
        hunter_payload_capable = bool(
            getattr(resolved_hunter_builder, "consumes_loop_payload", True))
        state = RunDispatchState(hunter_payload_capable=hunter_payload_capable)
        coro_for = build_run_dispatch(
            project_id=project_id,
            run_id=hunting_run_id,
            hunt_store=hunt_store,
            threat_store=run_threat_store,
            hunter_store=hunter_store,
            pod_store=pod_store,
            state=state,
            gate=gate,
            hunter_builder=resolved_hunter_builder,
            pod_builder=pod_builder if pod_builder is not None else _default_pod_builder,
            control=control,
            hunter_payload_capable=hunter_payload_capable,
        )

        pass_outcomes: list = []

        # RESUME (S1 7.5): the run row's stats ARE the run record. A row that
        # already carries an intake order is a stopped run resuming: it re-enters
        # at the recorded position, adopts the models already committed, and
        # never re-freezes or re-sorts the intake. Fail-open: an unreadable row
        # leaves the run fresh (its models are on disk, so nothing is lost).
        try:
            row = await asyncio.to_thread(pg.get_hunting_run, hunting_run_id)
        except Exception as exc:  # noqa: BLE001 - fail-open: no resume state
            logger.warning(
                "start_hunting: run-record read for %s failed (%s); the run "
                "starts fresh (fail-open)", hunting_run_id, exc,
            )
            row = None
        resume_record = dict((row or {}).get("stats") or {})
        if not resume_record.get("intake_order"):
            resume_record = None

        async def _write_run_record(record: dict) -> None:
            """Persist the run record onto the run row (S1 9.4, S2 9.2).

            Blocking pg write, offloaded like every other pg call here. Fail-open:
            a failed record write warns and the run continues - the total stays
            re-derivable from the models on disk, and the resume recomputes it."""
            try:
                await asyncio.to_thread(
                    pg.set_hunting_run_stats, hunting_run_id, record)
            except Exception as exc:  # noqa: BLE001 - fail-open
                logger.warning(
                    "start_hunting: run record write for %s failed (%s); "
                    "continuing (fail-open)", hunting_run_id, exc,
                )

        async def _modeller_units_pass():
            """The run's ONE pass session: freeze the intake (or resume the run
            record), order it, and model the units one at a time (see
            `_run_intake`). The outcomes are kept for the run terminal's
            dispatch-gap report (T4 #377)."""
            outcomes, _run = await _run_intake(
                project_id, hunting_run_id, tools=tools,
                pass_fn=modeller_pass_fn or arun_modeller_pass,
                pass_kwargs=dict(modeller_kwargs or {}),
                intake_units=intake_units,
                intake_read_fn=intake_read_fn,
                record=resume_record,
                record_fn=_write_run_record,
            )
            pass_outcomes.append(outcomes)
            return outcomes

        async def _surfer_loop():
            return await run_surfer_loop(
                project_id, hunting_run_id,
                hunt_store=hunt_store,
                threat_store=run_threat_store,
                hunter_store=hunter_store,
                control=control,
                coro_for=coro_for,
                state=state,
                hunter_payload_capable=hunter_payload_capable,
                tick_interval=tick_interval,
            )

        status = None

        def _role_running(role: str) -> bool:
            """True when the run's agent sub-module for `role` is `RUNNING`
            (#317); fail-open True with no manager bound."""
            if manager is None:
                return True
            try:
                return manager.agent_submodule_running(
                    "hunting", hunting_run_id, role)
            except Exception:  # noqa: BLE001 - fail-open: treat the role as up
                return True


        try:
            # The new-run session id (S1 4.1, swapped by T2b #386): the pass is
            # registered under `hunting:<run_id>:threat-modeller`. The legacy
            # `orchestrator` segment stays ACCEPTED (the quiesce predicate and
            # the stop filter take both), so an interrupted old run resumes
            # under its recorded id.
            modeller_id = threat_modeller_session_id(hunting_run_id)
            surfer_id = surfer_session_id(hunting_run_id)
            # #317: the modeller pass is gated on the modeller role state. A
            # stopped role does not launch the pass (the run still runs its
            # surfer, so pre-produced configs can dispatch).
            # A pass session REFUSED by admission is different: the pre-change
            # rule holds - the run fails and the surfer is NOT started (a
            # surfer with no pass is never spun up).
            modeller_outcome = None
            if _role_running("threat_modeller"):
                modeller_outcome = control.start_session(
                    modeller_id, _modeller_units_pass())
                if modeller_outcome is None:
                    logger.warning(
                        "start_hunting: modeller session %s not admitted; "
                        "run degrades to 'failed'", modeller_id,
                    )
                    status = "failed"
            else:
                logger.warning(
                    "start_hunting: modeller role paused; pass for run %s "
                    "not scheduled", hunting_run_id,
                )
            if status is None:
                surfer_outcome = control.start_session(surfer_id, _surfer_loop())
                if surfer_outcome is None:
                    # Without the surfer no dispatch can ever happen: the run
                    # can never reach quiesce, so it must fail now.
                    logger.warning(
                        "start_hunting: surfer session %s not admitted; "
                        "run degrades to 'failed'", surfer_id,
                    )
                    if modeller_outcome is not None:
                        control.cancel_session(modeller_id)
                    status = "failed"
                else:
                    await _await_session_outcome(modeller_outcome)
                    await _await_session_outcome(surfer_outcome)
                    # Quiesce is proven: the surfer settled only when the
                    # modeller pass was done, produced held no dispatchable
                    # item, no pod was live, and no hunter was mid-graph.
                    # Settle the remaining idle hunters and wait for every
                    # run session to leave the registry (ADR "Run lifecycle":
                    # terminal only when ALL component sessions have settled).
                    post_settle(state)
                    await _wait_no_run_sessions(control, hunting_run_id,
                                                tick_interval)
                    # Say WHY a run that produced models dispatched nothing:
                    # the pending-work read is blocking file I/O (the surfer's
                    # own predicate), so offload it like every other read here.
                    await asyncio.to_thread(
                        report_dispatch_gap, project_id, hunting_run_id,
                        [outcome for batch in pass_outcomes for outcome in batch],
                        state=state,
                        threat_store=run_threat_store,
                        hunt_store=hunt_store,
                        hunter_store=hunter_store,
                        hunter_payload_capable=hunter_payload_capable,
                    )
                    status = "complete"
        except asyncio.CancelledError:
            status = None  # external stop: stop_hunting stamps 'stopped'
            raise
        except ThreatModellerDegradedError as exc:
            # #329: a provider-caused pass abort is an INFRASTRUCTURE pause, not
            # a domain failure - land the resumable terminal `interrupted` so a
            # throttle does not fail the run outright. A non-provider degradation
            # (a poisoned actor thread) stays a genuine `failed`.
            if exc.provider_cause:
                logger.warning(
                    "start_hunting: run %s aborted on provider degradation; "
                    "persisting 'interrupted'", hunting_run_id,
                )
                # #331 stop-only: the ONE app-layer handler stops the run's
                # sessions (the surfer included) and drains them BEFORE the
                # terminal lands, flushes the threads, and stamps `interrupted`
                # with the recorded cause. `status` stays None so the `finally`
                # does not re-stamp over it.
                await stop_hunting_for_provider_failure(
                    control, hunting_run_id,
                    error=exc.provider_error, tick_interval=tick_interval,
                )
                status = None
            else:
                logger.exception(
                    "start_hunting: run %s degraded; persisting 'failed'",
                    hunting_run_id,
                )
                status = "failed"
        except ProviderUnavailableError as exc:
            # #312/#329: a provider failure in a dispatched HUNTER or POD session
            # surfaces through the surfer's outcome - the same stop/flush/stamp
            # handler pauses the run as the resumable `interrupted` with the
            # provider cause. A throttle pauses the run; it never fails it and
            # never lets it quiesce `complete` with zero specs and no typed reason
            # (the trial-2 outcome).
            logger.warning(
                "start_hunting: run %s paused on a child-session provider "
                "failure; persisting 'interrupted'", hunting_run_id,
            )
            await stop_hunting_for_provider_failure(
                control, hunting_run_id, error=exc, tick_interval=tick_interval,
            )
            status = None
        except Exception:  # noqa: BLE001 - fail-open: land a terminal status
            logger.exception(
                "start_hunting: run %s degraded; persisting 'failed'",
                hunting_run_id,
            )
            status = "failed"
        finally:
            try:
                await _reap_modeller(hunting_run_id)
            except Exception:  # noqa: BLE001 - teardown must never raise
                logger.warning(
                    "start_hunting: actor reap failed for %s (fail-open)",
                    hunting_run_id,
                )
            # The dispatch plane's refuse-once log is run-scoped (T4a review F3):
            # the terminal clears it, so a later run re-logs the malformed file it
            # still finds instead of inheriting this run's silence.
            try:
                from polymerhus.attack.hunting.mover import (  # noqa: PLC0415
                    clear_refusal_log,
                )

                clear_refusal_log(project_id, hunting_run_id)
            except Exception:  # noqa: BLE001 - teardown must never raise
                logger.warning(
                    "start_hunting: refusal-log clear failed for %s (fail-open)",
                    hunting_run_id,
                )
            # #317: the run terminal reaps the run's agent sub-modules, so no
            # role handle outlives its run.
            if manager is not None:
                try:
                    manager.reap_agent_submodules("hunting", hunting_run_id)
                except Exception:  # noqa: BLE001 - teardown must never raise
                    logger.warning(
                        "start_hunting: role reap failed for %s (fail-open)",
                        hunting_run_id,
                    )
            # Run-terminal flush through the SHARED run-scoped chokepoint (#211,
            # TD-1/TD-6, C12): the whole-index hook stays registered for the module
            # drain/shutdown walk; this terminal archives ONLY this run's threads
            # (bounded, siblings untouched) via `flush_run_scoped`, which logs a
            # drop loudly and never raises.
            from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
                flush_run_scoped,
            )
            await flush_run_scoped("hunting", hunting_run_id)
            if status is not None:
                terminal_stats = None
                if status == "complete" and resume_record is not None \
                        and resume_record.get("interrupted"):
                    # the run RESUMED a provider pause and finished: the pause's
                    # cause keys are nulled (M7), so a completed run is never
                    # read as interrupted
                    terminal_stats = dict(CLEARED_INTERRUPT_STATS)
                try:
                    await asyncio.to_thread(
                        pg.set_hunting_run_status, hunting_run_id, status,
                        stats=terminal_stats,
                    )
                except Exception:  # noqa: BLE001 - fail-open
                    logger.warning(
                        "start_hunting: could not persist %r for %s (fail-open)",
                        status,
                        hunting_run_id,
                    )
        return hunting_run_id


def build_production_hunting_agent(*, run_id, project_id="",
                                   graph_view_fn=None,
                                   memory_store=None, checkpointer=None,
                                   model_factory=None, observe: bool = True,
                                   exec_fn=None,
                                   http_search_fn=None, http_get_fn=None):
    """The production default hunting-agent dispatch seam (as of #164 W5): the
    turn-by-turn ReAct harness wired to the real `query_lightrag` KB tool (the
    lightrag branch's single KB tool, always-bound as of #197 - the
    `HUNTING_LIGHTRAG_TOOL` gate is REMOVED),
    the real Kali-container exec seam, and the per-project hunter memory store.
    Construction performs no I/O (everything heavy resolves on first use).

    Returns `(dispatch_fn, registry)`; the caller must reap the registry
    (`stop_all`) when the run's modelling pass finishes."""
    from polymerhus.attack.hunting.llm import build_actor_hunting_agent  # noqa: PLC0415

    return build_actor_hunting_agent(
        run_id=run_id,
        project_id=project_id,
        memory_store=memory_store,
        graph_view_fn=graph_view_fn,
        kb_fn=None,  # the KB seam: the harness binds the always-bound query_lightrag tool (#197)
        exec_fn=exec_fn,  # None -> the harness's default fail-open exec seam (the Kali container is a sibling workstream)
        http_search_fn=http_search_fn,  # #196: None -> the seam degrades fail-open
        http_get_fn=http_get_fn,
        checkpointer=checkpointer,
        model_factory=model_factory,
        observe=observe,
    )


async def stop_hunting(hunting_run_id: str) -> None:
    """Run stop (seam 3.1, ADR "Run lifecycle"): cancel EVERY session of the
    run through the shared control plane - per-session cancel by id (the
    modeller pass, the run-scoped surfer - itself a session - and every
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
        from polymerhus.attack.hunting.threat_modeller import (  # noqa: PLC0415
            _reap_modeller,
        )
        from polymerhus.attack.hunting.mover import (  # noqa: PLC0415
            RuntimeControlPlane,
        )

        _cancel_run_sessions(hunting_run_id)
        drain_timeout = 30.0
        try:
            await asyncio.wait_for(
                _wait_no_run_sessions(
                    RuntimeControlPlane(), hunting_run_id, interval=0.5),
                timeout=drain_timeout,
            )
        except Exception:  # noqa: BLE001 - fail-open: the drain is best-effort
            logger.warning(
                "stop_hunting: session-drain wait for %s did not settle within "
                "%ss (fail-open)", hunting_run_id, drain_timeout,
            )
        # The reap is BOUNDED by the same drain timeout as the provider-failure
        # path: the actor's task finishes only after its in-flight turn does, so
        # an unbounded await would delay the `stopped` terminal behind a stalled
        # probe/model turn. A timed-out reap cancels the actor's task
        # (`_reap_modeller`'s finally), so no live turn outlives the stop.
        try:
            await asyncio.wait_for(
                _reap_modeller(hunting_run_id), timeout=drain_timeout)
        except TimeoutError:
            logger.warning(
                "stop_hunting: actor reap for %s did not settle within %ss; the "
                "actor task was cancelled (fail-open)", hunting_run_id,
                drain_timeout,
            )
        except Exception:  # noqa: BLE001 - fail-open
            logger.warning(
                "stop_hunting: actor reap failed for %s (fail-open)", hunting_run_id
            )
        # #317: the run stop reaps the run's agent sub-modules with it.
        stop_manager = _app_runtime()
        if stop_manager is not None:
            try:
                stop_manager.reap_agent_submodules("hunting", hunting_run_id)
            except Exception:  # noqa: BLE001 - fail-open
                logger.warning(
                    "stop_hunting: role reap failed for %s (fail-open)",
                    hunting_run_id,
                )
        try:
            await asyncio.to_thread(pg.set_hunting_run_status, hunting_run_id, "stopped")
        except Exception:  # noqa: BLE001 - fail-open
            logger.warning(
                "stop_hunting: could not persist 'stopped' for %s (fail-open)",
                hunting_run_id,
            )


def flush_hunting_checkpointer() -> "FlushResult":
    """The tear-down flush hook (seam 3.1, #123): archive the hunting module's
    in-memory checkpointer index into the still-open #94 pooled saver via the
    SHARED `flush_module_index("hunting")` seam (`polymerhus.app.llm.checkpoints`),
    never a private hunting-only path. Routed through the shared `flush_seam_result`
    boundary (fail-open): a raise or a result-less seam degrades to a typed `cause`,
    never a bare None. Returns the typed `FlushResult` the module-runtime settle
    asserts on (#211, TD-2)."""
    from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
        flush_module_index,
        flush_seam_result,
    )
    return flush_seam_result(lambda: flush_module_index("hunting"), module="hunting")
