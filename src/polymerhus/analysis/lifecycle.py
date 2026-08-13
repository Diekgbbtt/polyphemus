"""The analysis-run lifecycle module (#75): analysis as its own runtime unit,
independent of the recon run.

This is the seam the dispatcher and the recon pipeline call to run analysis. It
owns:

  - the process-level registry of analysis-consumer SUPERVISOR tasks, so a
    consumer OUTLIVES the recon pipeline task and is not garbage-collected;
  - the `analysis_runs` persistence (its own row, its own status), written by
    exactly ONE writer - the supervisor - when the consumer settles;
  - start / stop / resume of the consumer over a run's per-run FIFO (`feed.py`).

Recon and analysis never wait on each other: recon pushes chunks and a terminal
marker (`feed.signal_end`) and returns; the supervisor here independently drains
and records `drained | withheld | stopped`. `interrupted` is written only by the
startup reconcile (`pg.reconcile_orphaned_analysis_runs`), never from here.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import uuid

from polymerhus.analysis.feed import drop_feed, get_feed, get_or_create_feed

logger = logging.getLogger(__name__)

# Supervisor tasks, keyed by run_id. A strong reference the event loop needs so
# the task is not collected mid-drain (the same discipline as the API's _IN_FLIGHT).
_SUPERVISORS: dict[str, asyncio.Task] = {}
_ANALYSIS_RUN_IDS: dict[str, str] = {}


def _runtime():
    """The active module control plane, if any (#121). When active, the analysis
    lifecycle runs THROUGH the runtime: the supervisor is a registered run of the
    analysis module, so pause/drain/cancel reach it like any other analysis run."""
    from polymerhus.app.runtime import get_active_runtime

    return get_active_runtime()


def _sync_on_worker(runtime, fn, *args, **kwargs) -> concurrent.futures.Future:
    """Marshal a sync function onto the runtime's worker loop (it returns a
    future the API thread can `.result()` on - the ONLY cross-thread await)."""

    async def _run():
        return fn(*args, **kwargs)

    return runtime.call(_run())


async def _marshalled_await(runtime, coro):
    """Resolve a coroutine marshalled onto the worker loop on the CALLER's loop."""
    return await asyncio.wrap_future(runtime.call(coro))


def _new_analysis_run_id(run_id: str) -> str:
    """A fresh surrogate id per attempt (D5): a relaunch over the same recon
    run_id must never collide, so every start mints a new one."""
    return f"{run_id}:{uuid.uuid4().hex[:8]}"


def is_analysing(run_id: str) -> bool:
    runtime = _runtime()
    if runtime is not None:
        return runtime.has_run("analysis", run_id)
    task = _SUPERVISORS.get(run_id)
    return task is not None and not task.done()


def current_analysis_run_id(run_id: str) -> str | None:
    return _ANALYSIS_RUN_IDS.get(run_id)


def start_analysis(project_id: str, run_id: str, *, pass_fn=None) -> str | None:
    """Start (or resume) the analysis consumer for a run over its per-run FIFO.

    Creates a fresh `analysis_runs` row in `draining`, starts the consumer, and
    supervises it: when the consumer settles (terminal marker => drained/withheld,
    or a graceful stop => stopped) the supervisor writes that status ONCE. Returns
    the new analysis_run_id, or None if a consumer is already running for this run
    (idempotent guard - no double consumer over one queue)."""
    if is_analysing(run_id):
        return None

    runtime = _runtime()
    if runtime is not None and not runtime.thread_is_worker():
        # From the API thread: marshal the bootstrap onto the worker loop. NEVER
        # block the worker loop itself - `.result()` on the loop thread would
        # deadlock the marshalled coroutine behind it.
        try:
            return _sync_on_worker(
                runtime, _start_analysis_sync, project_id, run_id, pass_fn
            ).result(timeout=30)
        except concurrent.futures.TimeoutError:
            logger.error("start_analysis timed out marshalling for run %s", run_id)
            return None
    return _start_analysis_sync(project_id, run_id, pass_fn)


def _start_analysis_sync(project_id: str, run_id: str, pass_fn=None) -> str | None:
    """The consumer bootstrap, executed on the worker loop when the runtime is
    active (the supervisor becomes a registered analysis run)."""
    from polymerhus.app.clients import pg

    analysis_run_id = _new_analysis_run_id(run_id)
    # Best-effort persistence: a pg hiccup must not prevent analysis from running.
    try:
        pg.create_analysis_run(analysis_run_id, run_id, project_id)
    except Exception:  # noqa: BLE001
        logger.warning("create_analysis_run failed for %s (analysis continues untracked)",
                       run_id, exc_info=True)

    feed = get_or_create_feed(project_id, run_id, pass_fn=pass_fn).start()

    async def _supervise() -> None:
        try:
            stats = await feed.wait_until_done()
        except Exception:  # noqa: BLE001 - a supervisor failure must not crash the loop
            logger.warning("analysis supervisor raised for run %s", run_id, exc_info=True)
            return
        status = stats.status or "withheld"
        try:
            await asyncio.to_thread(
                pg.set_analysis_run_status, analysis_run_id, status, stats.model_dump())
        except Exception:  # noqa: BLE001
            logger.warning("set_analysis_run_status failed for %s -> %s", run_id, status, exc_info=True)
        # Preserve the queue on a graceful STOP (D7: resumable); only a truly terminal
        # drain retires the feed and frees its memory (D12).
        if status in ("drained", "withheld"):
            drop_feed(run_id)

    runtime = _runtime()
    if runtime is not None:
        try:
            runtime.schedule("analysis", _supervise(), name=run_id)
        except Exception:  # noqa: BLE001
            logger.warning("analysis module refused run %s (supervisor not started)", run_id, exc_info=True)
            return None
    else:
        task = asyncio.create_task(_supervise(), name=f"analysis-supervisor-{run_id}")
        _SUPERVISORS[run_id] = task
        task.add_done_callback(lambda t: _SUPERVISORS.pop(run_id, None) if _SUPERVISORS.get(run_id) is t else None)
    _ANALYSIS_RUN_IDS[run_id] = analysis_run_id
    return analysis_run_id


async def stop_analysis(run_id: str) -> None:
    """Graceful stop (D7): let the in-flight chunk finish, consume no further, and
    preserve the queue for a resume. Awaits the supervisor so the `stopped` status
    is persisted before returning. No-op if nothing is analysing this run."""
    runtime = _runtime()
    if runtime is not None and not runtime.thread_is_worker():
        await _marshalled_await(runtime, _stop_analysis_impl(run_id))
        return
    await _stop_analysis_impl(run_id)


async def _stop_analysis_impl(run_id: str) -> None:
    feed = get_feed(run_id)
    if feed is not None:
        await feed.stop()  # sets the stop event; the consumer settles to `stopped`
    task = _SUPERVISORS.get(run_id)
    if task is not None:
        try:
            await task  # the supervisor writes `stopped` on the way out
        except (asyncio.CancelledError, Exception):  # noqa: B014
            pass


async def cancel_analysis(run_id: str) -> None:
    """Hard cancel (process shutdown only): drop the in-flight chunk. Prefer
    `stop_analysis` everywhere else."""
    runtime = _runtime()
    if runtime is not None and not runtime.thread_is_worker():
        await _marshalled_await(runtime, _cancel_analysis_impl(run_id))
        return
    await _cancel_analysis_impl(run_id)


async def _cancel_analysis_impl(run_id: str) -> None:
    feed = get_feed(run_id)
    if feed is not None:
        await feed.cancel()
    runtime = _runtime()
    if runtime is not None:
        try:
            runtime.cancel_run("analysis", run_id)
        except Exception:  # noqa: BLE001 - already gone is fine
            pass
    else:
        _SUPERVISORS.pop(run_id, None)
    drop_feed(run_id)
