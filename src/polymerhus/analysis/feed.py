"""The analysis feed - recon's one touchpoint on analysis, and the seam that takes
the analyser off recon's critical path.

Today the pipeline `await`s a full analyser pass inside its per-job loop
(`pipeline.py`, the `stream_analyser_step` call), which is the ONLY runtime edge
from recon to analysis anywhere in the codebase and the sole reason a recon run
waits on an LLM. On a measured Juice Shop run that wait consumed roughly 1530 s of
a 2192 s run, entirely in dead gaps between jobs.

This module replaces that call site with a handle carrying two methods, so the
pipeline keeps exactly one analysis touchpoint plus one drain, and the mode is a
settings flag rather than a branch at the call site:

  - `InlineAnalysisFeed`  - today's behaviour verbatim, the rollback path.
  - `QueuedAnalysisFeed`  - one consumer task per run, fed by a depth-1 conflating
    queue of CURSORS.

WHAT THE QUEUE CARRIES, AND WHY IT MATTERS (#34 DQ1/DQ3). A cursor is a signal to
re-derive, never an increment of surface. The analyser re-reads the cumulative L0
surface every pass, so five signals raised while a pass is in flight mean exactly
one further pass is needed, not five - which is why conflating is correct here and
not merely convenient. A payload queue was considered and rejected: a per-job delta
is not obtainable without changing the L0 sole-writer, and a per-increment judgment
cannot re-open an earlier one in the light of later surface, so it would be more
machinery for a weaker guarantee.

THE GUARANTEE (#34 DQ1a/DQ2b). At-least-once OBSERVATION of surface: every L0
element curated during the run is read by at least one pass before the run reaches
its terminal state. Nothing is claimed about what the analyser concluded. Because
every layer beneath this one is fail-open, `drain` decides `analysis_drained` from
the terminal pass's CENSUS - what it actually read and entered - never from the
fact that a coroutine returned.

Back-pressure is conflating, NEVER blocking: blocking would reintroduce the stall
this module exists to remove.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ONE analyser pass in flight process-wide, across concurrent runs. This is the
# memory guard that makes a concurrent consumer admissible at all: the FR-STREAM /
# NM-7 ledger rejected a long-lived consumer as memory-unsafe on the constrained
# host, and a bounded one is only safe because N runs still cost one pass of
# residency. It is a MEMORY guard, not an availability guard - nothing that awaits
# a live tool run may be held inside it.
ANALYSER_PASS_SEMAPHORE = asyncio.Semaphore(1)

# How long `drain` waits for the terminal pass. On expiry the run completes with
# `analysis_drained: false` - an honest hole rather than an unbounded wait, and
# never a failed run.
ANALYSIS_DRAIN_DEADLINE_S = float(os.environ.get("ANALYSIS_DRAIN_DEADLINE_S", "600"))


class AnalysisCursor(BaseModel):
    """A signal to re-derive L1 over the CURRENT cumulative surface.

    Carries no assets, no chunks, no observations and no L1 context - only the
    provenance of the signal, so a coalesced collapse stays legible."""

    model_config = ConfigDict(frozen=True)

    project_id: str
    run_id: str
    job: str = ""
    phase: int = -1
    produced_assets: int = 0
    produced_observations: int = 0
    terminal: bool = False


class FeedStats(BaseModel):
    """What the feed reports back into the run's stats. `analysis_drained` is the
    load-bearing field and is FALSE unless a terminal pass actually observed the
    surface (#34 DQ2b)."""

    model_config = ConfigDict(frozen=True)

    mode: str = "inline"
    advanced: int = 0
    passes: int = 0
    coalesced: int = 0
    analysis_drained: bool = False
    consumer: str = "none"
    l0_assets_read: int = 0
    dispatches_entered: int = 0

    # THE stall predicate (#34 AST-DEC-09). `advance_blocked_s_max` is the longest
    # any single `advance` held the recon job loop, measured at the seam itself -
    # which is the quantity the decoupling exists to drive to zero, and is directly
    # comparable between the two modes: under `inline` it IS the pass duration
    # (on run 64f2ccb8, up to 1157 s), under `queued` it must stay near zero even
    # while `pass_seconds_max` remains large.
    #
    # This supersedes the originally specified observable, "the gap between a job's
    # finished_at and the next job's started_at", which is unimplementable:
    # `upsert_job` stamps `started_at` with `now()` on INSERT and does not touch it
    # ON CONFLICT (`app/clients/pg.py:207-212`), and the pipeline inserts the
    # `in_progress` row for EVERY job of a phase during phase setup, before any of
    # them runs. So `started_at` measures phase setup, not job start.
    advance_blocked_s_max: float = 0.0
    advance_blocked_s_total: float = 0.0
    pass_seconds_max: float = 0.0
    pass_seconds_total: float = 0.0


class _Timings:
    """Max/total accumulators for the two durations that decide AST-DEC-09.

    Kept as a tiny value holder rather than four loose attributes so both feeds
    measure the same two things the same way, and the assertion can compare
    inline against queued without knowing which class produced the numbers."""

    def __init__(self) -> None:
        self.blocked_max = 0.0
        self.blocked_total = 0.0
        self.pass_max = 0.0
        self.pass_total = 0.0

    def record_blocked(self, seconds: float) -> None:
        self.blocked_max = max(self.blocked_max, seconds)
        self.blocked_total += seconds

    def record_pass(self, seconds: float) -> None:
        self.pass_max = max(self.pass_max, seconds)
        self.pass_total += seconds

    def as_stats(self) -> dict:
        return {
            "advance_blocked_s_max": round(self.blocked_max, 3),
            "advance_blocked_s_total": round(self.blocked_total, 3),
            "pass_seconds_max": round(self.pass_max, 3),
            "pass_seconds_total": round(self.pass_total, 3),
        }


class InlineAnalysisFeed:
    """Today's behaviour, unchanged: `advance` runs a full pass on the caller's
    task and returns only when it is done. Kept as the rollback path so the flag
    is a genuine two-way door and no analysis code is forked."""

    mode = "inline"

    def __init__(self, project_id: str, run_id: str, *, pass_fn=None):
        self._project_id, self._run_id = project_id, run_id
        self._pass_fn = pass_fn
        self._advanced = 0
        self._passes = 0
        self._timings = _Timings()

    async def advance(self, cursor: AnalysisCursor) -> None:
        self._advanced += 1
        started = time.monotonic()
        try:
            await self._run_pass(cursor)
            self._passes += 1
            self._timings.record_pass(time.monotonic() - started)
        except Exception:  # best-effort: analysis never aborts recon
            logger.warning("inline analysis pass raised for run %s job %s (recon continues)",
                           self._run_id, cursor.job, exc_info=True)
        finally:
            # For the inline feed the blocked time IS the pass time - which is
            # exactly the fact the assertion needs to be able to state.
            self._timings.record_blocked(time.monotonic() - started)

    async def _run_pass(self, cursor: AnalysisCursor):
        if self._pass_fn is not None:
            return await self._pass_fn(cursor)
        from polymerhus.analysis.streaming import stream_analyser_step
        return await asyncio.to_thread(stream_analyser_step, cursor.project_id, cursor.run_id)

    async def drain(self, deadline: float = ANALYSIS_DRAIN_DEADLINE_S) -> FeedStats:
        """No-op: the inline feed has nothing outstanding by construction, because
        every `advance` already ran to completion. It makes NO drained claim -
        `analysis_drained` stays false, because no terminal pass over the settled
        surface was engineered (the last inline pass ran before the last job's
        surface may have landed)."""
        return FeedStats(mode=self.mode, advanced=self._advanced, passes=self._passes,
                         **self._timings.as_stats())


class QueuedAnalysisFeed:
    """The decoupled feed: `advance` enqueues a cursor and returns immediately.

    One consumer task per run drains a depth-1 conflating queue. The consumer holds
    `ANALYSER_PASS_SEMAPHORE` for the duration of each pass, so concurrency across
    runs never becomes accumulation."""

    mode = "queued"

    def __init__(self, project_id: str, run_id: str, *, pass_fn=None, semaphore=None):
        self._project_id, self._run_id = project_id, run_id
        self._pass_fn = pass_fn
        self._sem = semaphore if semaphore is not None else ANALYSER_PASS_SEMAPHORE
        self._queue: asyncio.Queue[AnalysisCursor] = asyncio.Queue(maxsize=1)
        self._advanced = 0
        self._passes = 0
        self._coalesced = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._last_census = None
        self._task: asyncio.Task | None = None
        self._timings = _Timings()

    def start(self) -> "QueuedAnalysisFeed":
        self._task = asyncio.create_task(self._consume(), name=f"analysis-consumer-{self._run_id}")
        return self

    async def advance(self, cursor: AnalysisCursor) -> None:
        """Non-blocking. On a full queue the PENDING cursor is replaced rather than
        the caller waiting: cursors are cumulative, so the newer one subsumes the
        older, and the collapse is counted so it is observable rather than silent."""
        self._advanced += 1
        started = time.monotonic()
        self._idle.clear()
        try:
            self._queue.put_nowait(cursor)
        except asyncio.QueueFull:
            try:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                self._coalesced += 1
                # `terminal` is a PROPERTY OF THE RUN, not of the signal: once a
                # terminal cursor is pending, the run has stopped producing surface
                # and the next pass must still be the terminal one. Coalescing must
                # therefore never demote it, or the drain would wait for a pass that
                # can no longer arrive.
                if dropped.terminal and not cursor.terminal:
                    cursor = cursor.model_copy(update={"terminal": True})
            except asyncio.QueueEmpty:  # consumer took it in between; nothing to drop
                pass
            try:
                self._queue.put_nowait(cursor)
            except asyncio.QueueFull:  # consumer re-filled it; its cursor is newer-equal
                self._coalesced += 1
        finally:
            # Measured on EVERY path, including the coalescing one, because the
            # claim being made is about the caller - the recon job loop - not about
            # the happy path through this method.
            self._timings.record_blocked(time.monotonic() - started)

    async def _consume(self) -> None:
        while True:
            cursor = await self._queue.get()
            try:
                async with self._sem:
                    # Timed INSIDE the semaphore: `pass_seconds` must mean the work
                    # a pass did, not how long it queued behind another run's pass,
                    # or the non-vacuity guard ("some pass took real time") could be
                    # satisfied by contention alone.
                    started = time.monotonic()
                    result = await self._run_pass(cursor)
                    self._timings.record_pass(time.monotonic() - started)
                self._passes += 1
                if result is not None:
                    self._last_census = getattr(result, "census", None)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception:  # a failed pass degrades that pass, never the run
                logger.warning("analysis pass raised for run %s job %s (recon continues)",
                               self._run_id, cursor.job, exc_info=True)
            finally:
                self._queue.task_done()
                if self._queue.empty():
                    self._idle.set()

    async def _run_pass(self, cursor: AnalysisCursor):
        if self._pass_fn is not None:
            return await self._pass_fn(cursor)
        from polymerhus.analysis.supervisor import analyse_chunked
        return await analyse_chunked(
            cursor.project_id, f"stream-{cursor.run_id}", terminal=cursor.terminal,
        )

    async def drain(self, deadline: float = ANALYSIS_DRAIN_DEADLINE_S) -> FeedStats:
        """Enqueue a TERMINAL cursor and wait for the consumer to go idle.

        The terminal pass is what makes the at-least-once-observation guarantee
        real: being cumulative, a pass that BEGINS after the last recon curate is by
        construction the batch pass over the settled surface. `analysis_drained` is
        decided from that pass's census, so a pass that read nothing cannot claim
        convergence. On deadline expiry the run still completes, with the claim
        explicitly withheld."""
        await self.advance(AnalysisCursor(
            project_id=self._project_id, run_id=self._run_id, terminal=True,
        ))
        drained = False
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=deadline)
            census = self._last_census
            # DQ2b: the pass must have OBSERVED something, not merely returned.
            drained = bool(
                census is not None
                and getattr(census, "terminal", False)
                and getattr(census, "l0_assets_read", 0) > 0
                and getattr(census, "dispatches_entered", 0) > 0
            )
        except asyncio.TimeoutError:
            logger.warning("analysis drain deadline (%.0fs) expired for run %s; "
                           "completing with analysis_drained=false", deadline, self._run_id)
        finally:
            await self.stop()
        census = self._last_census
        return FeedStats(
            mode=self.mode, advanced=self._advanced, passes=self._passes,
            coalesced=self._coalesced, analysis_drained=drained,
            consumer=self._consumer_state(),
            l0_assets_read=getattr(census, "l0_assets_read", 0) or 0,
            dispatches_entered=getattr(census, "dispatches_entered", 0) or 0,
            **self._timings.as_stats(),
        )

    def _consumer_state(self) -> str:
        if self._task is None:
            return "none"
        if not self._task.done():
            return "running"
        if self._task.cancelled():
            return "stopped"
        return "dead" if self._task.exception() is not None else "finished"

    async def stop(self) -> None:
        """Cancel the consumer. Called on the drain path AND on abnormal
        termination (#34 DQ4a): a cancelled or failed run finishes no outstanding
        pass and makes no convergence claim, because finishing analysis the operator
        asked to abandon serves nobody."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: B014 - shutdown must not raise
            pass


def start_analysis_feed(project_id: str, run_id: str, *, mode: str = "inline", pass_fn=None):
    """The ONE seam the pipeline calls. `mode` comes from settings, so the call site
    never branches and rollback is a flag flip."""
    if mode == "queued":
        return QueuedAnalysisFeed(project_id, run_id, pass_fn=pass_fn).start()
    return InlineAnalysisFeed(project_id, run_id, pass_fn=pass_fn)


def resolve_feed_mode(settings: dict | None) -> str:
    """`queued` is the DEFAULT whenever streaming analysis is on; `inline` only when
    explicitly opted back into (`async_analysis_consumer=False`).

    The default flipped (#9): with the mechanism_typist dispatched in the streaming
    schedule, an analyser pass is ~126 s/chunk (its 3 LLM calls), and the inline feed
    runs that pass ON the recon critical path - so recon stalls behind the typist.
    Queued hands each pass to a per-run consumer (depth-1 conflating), keeping recon
    off the analyser's latency. `inline` remains the rollback path (the pre-#9
    behaviour) for a caller that sets `async_analysis_consumer=False` explicitly.

    The terminal pass stays gated on `streaming_analysis` (#34 DQ5a): off means off,
    byte-for-byte as today, so this flag cannot introduce post-recon batch analysis
    as a side effect of a scheduling change."""
    s = settings or {}
    if not s.get("streaming_analysis"):
        return "inline"
    return "inline" if s.get("async_analysis_consumer") is False else "queued"
