"""The analysis-run lifecycle module (#75): analysis as its own runtime unit,
independent of the recon run.

This is the seam the dispatcher and the recon pipeline call to run analysis. It
owns:

  - the analysis supervisor run, registered on the analysis module of the module
    runtime (`#121`) so a consumer OUTLIVES the recon pipeline task and is not
    garbage-collected - the runtime's per-module registry holds the task (#122
    full cut; no process-level `_SUPERVISORS` dict remains);
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
import time
import uuid

from polymerhus.analysis.feed import drop_feed, get_feed, get_or_create_feed
from polymerhus.app.runtime import ModuleAdmissionRefused

logger = logging.getLogger(__name__)

# run_id -> the fresh surrogate analysis_run_id minted per start (D5). This is a
# pure id map (status/resume bookkeeping), NOT a task registry - the supervisor
# task itself lives in the module runtime's analysis registry.
_ANALYSIS_RUN_IDS: dict[str, str] = {}


def _runtime():
    """The active module control plane (#121). Since #122 the lifecycle requires
    it: the supervisor is a registered run of the analysis module, so
    pause/drain/cancel reach it like any other analysis run. There is no
    create_task fallback."""
    from polymerhus.app.runtime import get_active_runtime

    return get_active_runtime()


def _require_runtime():
    runtime = _runtime()
    if runtime is None:
        raise RuntimeError(
            "analysis lifecycle requires the module runtime; no manager is active"
        )
    return runtime


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
    runtime = _require_runtime()
    return runtime.has_run("analysis", run_id)


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

    runtime = _require_runtime()
    if not runtime.thread_is_worker():
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

    runtime = _require_runtime()
    try:
        runtime.schedule("analysis", _supervise(), name=run_id)
    except ModuleAdmissionRefused:
        # #118 contract: a paused/draining/stopped analysis module refuses new
        # runs. Propagate so the operator-intent surface maps it to a clean 503
        # instead of degrading it to a "already running" 409 (that masks the
        # real cause - the module is not accepting work, not that a consumer
        # is live).
        raise
    except Exception:  # noqa: BLE001
        logger.warning("analysis module refused run %s (supervisor not started)", run_id, exc_info=True)
        return None
    _ANALYSIS_RUN_IDS[run_id] = analysis_run_id
    return analysis_run_id


async def stop_analysis(run_id: str) -> None:
    """Graceful stop (D7): let the in-flight chunk finish, consume no further, and
    preserve the queue for a resume. Awaits the supervisor so the `stopped` status
    is persisted before returning. No-op if nothing is analysing this run."""
    runtime = _require_runtime()
    if not runtime.thread_is_worker():
        await _marshalled_await(runtime, _stop_analysis_impl(run_id))
        return
    await _stop_analysis_impl(run_id)


async def _stop_analysis_impl(run_id: str) -> None:
    feed = get_feed(run_id)
    if feed is not None:
        await feed.stop()  # sets the stop event; the consumer settles to `stopped`
    await _await_registered_run(run_id)


async def _await_registered_run(run_id: str) -> None:
    """Wait for the analysis run to leave the module registry (the supervisor's
    `_tracked` `finally` unregisters it once it has persisted its status)."""
    runtime = _require_runtime()
    deadline = time.monotonic() + 30
    while runtime.has_run("analysis", run_id) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


async def cancel_analysis(run_id: str) -> None:
    """Hard cancel (process shutdown only): drop the in-flight chunk. Prefer
    `stop_analysis` everywhere else."""
    runtime = _require_runtime()
    if not runtime.thread_is_worker():
        await _marshalled_await(runtime, _cancel_analysis_impl(run_id))
        return
    await _cancel_analysis_impl(run_id)


async def _cancel_analysis_impl(run_id: str) -> None:
    feed = get_feed(run_id)
    if feed is not None:
        await feed.cancel()
    runtime = _require_runtime()
    try:
        runtime.cancel_run("analysis", run_id)
    except Exception:  # noqa: BLE001 - already gone is fine
        pass
    drop_feed(run_id)
