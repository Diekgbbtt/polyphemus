"""The service-sourced analysis pass (T6, ADR D1-D6, D41-D44).

This is the `pass_fn` the `service_sourced` mode selects (ADR D1). Recon pushes
no per-job chunk in this mode and still calls `signal_end`, so the terminal
marker is the ONLY push and the only trigger: when the queued consumer reaches
it, this pass runs.

The pass has two sequential stages (ADR D6):

  1. the GLOBAL ASSIGN pass - `assign_global` over the whole settled L0 surface
     (T4), a plain awaited call, NOT a supervisor dispatch (ADR D9);
  2. the PER-SERVICE LOOP - `run_service_loop` (T5), mechanism_typist then
     data_modeller per Service unit.

It is gated on recon reaching `complete` (ADR D4) and guarded once per run (ADR
D5). It returns a terminal `PassResult` whose drained signal is WRITE-BASED (ADR
D41): `wrote` is true only when something was actually written, so a run where
every Service degraded is reported `withheld`, not `drained`. A mid-pass stop is
carried on the census as `stopped`, so the feed classifies it `stopped`, never
`drained` (ADR D42).

Importing this module performs no I/O and reads no env var (CODING_STANDARD 6).
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# A recon run is settled once it reaches one of these; a `running` run has simply
# not written its terminal status yet. `signal_end` fires in recon's `finally`
# BEFORE the terminal status write, so a brief bounded wait for the status to
# settle keeps the `complete` gate faithful without withholding a clean run
# (ADR D4).
_TERMINAL_RECON_STATUSES = frozenset({"complete", "stopped", "failed", "interrupted"})
_STATUS_WAIT_S = 30.0
_STATUS_POLL_S = 0.25

# The once-per-run guard (ADR D5): a second terminal marker over the same run id
# must not re-run the whole pipeline. Process-scoped, which is exactly the scope
# of the per-run in-memory FIFO the consumer drains.
_PASSED: set[str] = set()


def reset_pass_guard() -> None:
    """Clear the once-per-run guard (tests; a fresh process starts empty)."""
    _PASSED.clear()


def _default_recon_status(run_id: str) -> str | None:
    """The recon run's status, fail-open to None (unknown)."""
    from polymerhus.app.clients import pg

    row = pg.get_run(run_id)
    return (row or {}).get("status")


async def _await_terminal_status(status_fn, run_id: str, *, budget_s: float,
                                 poll_s: float) -> str | None:
    """Read the recon status until it settles into a terminal state, bounded.

    `signal_end` fires in recon's teardown before the terminal status write, so a
    marker can reach this pass while the recon row still says `running`. Waiting
    briefly for the status to settle makes the `complete` gate truthful in the
    clean case and still lets a `stopped`/`failed` run be recognised (ADR D4)."""
    deadline = time.monotonic() + max(0.0, budget_s)
    while True:
        status = await asyncio.to_thread(status_fn, run_id)
        if status in _TERMINAL_RECON_STATUSES:
            return status
        if time.monotonic() >= deadline:
            return status
        await asyncio.sleep(poll_s)


def _resolve_analysis_run_id(recon_run_id: str) -> str | None:
    """The live analysis_run_id for a recon run (the census persistence key, ADR
    D11): the in-process lifecycle map first, then the persisted row. Fail-open to
    None (the caller falls back to the recon run id)."""
    try:
        from polymerhus.analysis.lifecycle import current_analysis_run_id

        live = current_analysis_run_id(recon_run_id)
        if live:
            return live
    except Exception:  # noqa: BLE001 - the map is an optimisation, never required
        pass
    try:
        from polymerhus.app.clients import pg

        row = pg.get_analysis_run(recon_run_id)
        if row:
            return row.get("analysis_run_id")
    except Exception:  # noqa: BLE001 - fall back to the recon run id
        pass
    return None


def _default_memory():
    try:
        from polymerhus.analysis.memory import AnalysisMemoryStore

        return AnalysisMemoryStore()
    except Exception:  # noqa: BLE001 - no store -> the backstop is inert, never fatal
        return None


async def service_sourced_pass(
    chunk,
    *,
    assign_fn=None,
    loop_fn=None,
    status_fn=None,
    memory=None,
    observe: bool = True,
    status_wait_s: float = _STATUS_WAIT_S,
    status_poll_s: float = _STATUS_POLL_S,
):
    """The service-sourced pass (the mode's `pass_fn`). See the module docstring.

    Every collaborator is injectable, so the pass is unit-testable with no Neo4j,
    no LLM and no database: `assign_fn(project_id, run_id, *, memory)` (stage
    1), `loop_fn(project_id, run_id, *, memory, stop_fn, observe)` (stage 2), and
    `status_fn(run_id) -> status`. The pass never raises: a degraded stage yields a
    terminal census that claims nothing."""
    from polymerhus.analysis.assigner import assign_global
    from polymerhus.analysis.pod import AnalyserExport
    from polymerhus.analysis.service_slice import run_service_loop
    from polymerhus.analysis.supervisor import PassCensus, PassResult, _utc_now_iso, _window

    t0 = time.monotonic()
    started_at = _utc_now_iso()
    project_id = getattr(chunk, "project_id", "") or ""
    recon_run_id = getattr(chunk, "run_id", "") or ""

    def _result(*, wrote, units=0, stopped=False, agg=0, systems=0, data_items=0,
                dispatches=0):
        return PassResult(
            export=AnalyserExport(aggregates_written=agg, systems_written=systems),
            census=PassCensus(
                terminal=True, unprocessed_after=0, wrote=wrote, stopped=stopped,
                units_processed=units, dispatches_entered=dispatches,
                aggregates_written=agg, systems_written=systems,
                data_items_written=data_items, **_window(t0, started_at),
            ),
        )

    # Only the terminal marker triggers the pass; any other chunk is a no-op.
    if not getattr(chunk, "terminal", False):
        return _result(wrote=False)
    # ADR D5: once per run - a second marker must not re-run the pipeline.
    if recon_run_id in _PASSED:
        logger.info("service_sourced: run %s already passed; ignoring the extra marker", recon_run_id)
        return _result(wrote=False)

    status_fn = status_fn or _default_recon_status
    try:
        status = await _await_terminal_status(
            status_fn, recon_run_id, budget_s=status_wait_s, poll_s=status_poll_s)
    except Exception:  # noqa: BLE001 - a status read failure withholds, never runs blind
        logger.warning("service_sourced: recon status read failed for %s; withholding",
                       recon_run_id, exc_info=True)
        status = None
    if status != "complete":
        # ADR D4: the most expensive pass never runs on the least complete surface.
        logger.info("service_sourced: run %s status=%r != complete; withholding the pass",
                    recon_run_id, status)
        _PASSED.add(recon_run_id)
        return _result(wrote=False)

    # From here the run is complete and this pass is the one. Mark BEFORE the work
    # so a concurrent second marker cannot double-run (the guard is the point).
    _PASSED.add(recon_run_id)

    analysis_run_id = _resolve_analysis_run_id(recon_run_id) or recon_run_id
    assign_fn = assign_fn or assign_global
    loop_fn = loop_fn or run_service_loop
    if memory is None:
        memory = _default_memory()

    # --- stage 1: the global assign pass (a plain awaited call, ADR D9) ---------
    try:
        census = await assign_fn(project_id, analysis_run_id, memory=memory)
    except Exception:  # noqa: BLE001 - a degraded stage 1 must not lose stage 2
        logger.warning("service_sourced: global assign pass failed for %s", recon_run_id,
                       exc_info=True)
        census = None
    written = int(getattr(census, "written", 0) or 0)

    # --- stage 2: the per-Service loop -----------------------------------------
    from polymerhus.analysis.feed import get_feed

    feed = get_feed(recon_run_id)
    stop_fn = (lambda: feed.stopping) if feed is not None else None
    try:
        loop_result = await loop_fn(
            project_id, recon_run_id, memory=memory, stop_fn=stop_fn, observe=observe)
    except Exception:  # noqa: BLE001 - a degraded stage 2 still returns a terminal census
        logger.warning("service_sourced: per-Service loop failed for %s", recon_run_id,
                       exc_info=True)
        loop_result = None

    if loop_result is None:
        wrote = written > 0
        return _result(wrote=wrote, agg=written)

    wrote = bool(loop_result.wrote or written > 0)
    # Dispatches actually ENTERED (a no-surface unit is deliberately not dispatched),
    # for observability only: the drained claim above is write-based (ADR D41).
    dispatches = sum(1 for o in loop_result.outcomes if o.status != "no_surface")
    result = _result(
        wrote=wrote, units=len(loop_result.units), stopped=loop_result.stopped,
        agg=written + loop_result.aggregates_written,
        systems=loop_result.systems_written, data_items=loop_result.data_items_written,
        dispatches=dispatches,
    )
    logger.info(
        "service_sourced pass run=%s units=%d wrote=%s stopped=%s "
        "(census_written=%d loop_aggregates=%d)",
        recon_run_id, len(loop_result.units), wrote, loop_result.stopped,
        written, loop_result.aggregates_written,
    )
    return result
