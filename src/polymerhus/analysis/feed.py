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

    async def advance(self, cursor: AnalysisCursor) -> None:
        self._advanced += 1
        try:
            await self._run_pass(cursor)
            self._passes += 1
        except Exception:  # best-effort: analysis never aborts recon
            logger.warning("inline analysis pass raised for run %s job %s (recon continues)",
                           self._run_id, cursor.job, exc_info=True)

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
        return FeedStats(mode=self.mode, advanced=self._advanced, passes=self._passes)


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

    def start(self) -> "QueuedAnalysisFeed":
        self._task = asyncio.create_task(self._consume(), name=f"analysis-consumer-{self._run_id}")
        return self

    async def advance(self, cursor: AnalysisCursor) -> None:
        """Non-blocking. On a full queue the PENDING cursor is replaced rather than
        the caller waiting: cursors are cumulative, so the newer one subsumes the
        older, and the collapse is counted so it is observable rather than silent."""
        self._advanced += 1
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

    async def _consume(self) -> None:
        while True:
            cursor = await self._queue.get()
            try:
                async with self._sem:
                    result = await self._run_pass(cursor)
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
    """`queued` only when the async consumer is enabled AND streaming analysis is on.

    The terminal pass stays gated on `streaming_analysis` (#34 DQ5a): off means off,
    byte-for-byte as today, so this flag cannot introduce post-recon batch analysis
    as a side effect of a scheduling change."""
    s = settings or {}
    if not s.get("streaming_analysis"):
        return "inline"
    return "queued" if s.get("async_analysis_consumer") else "inline"
