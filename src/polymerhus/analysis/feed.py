"""The analysis feed - recon's one touchpoint on analysis, and the seam that takes
the analyser off recon's critical path.

This module replaces the old inline `stream_analyser_step` call site with a
handle carrying two methods, so the pipeline keeps exactly one analysis
touchpoint plus one drain, and the mode is a settings flag rather than a branch
at the call site:

  - `InlineAnalysisFeed`  - today's blocking behaviour, the rollback path.
  - `QueuedAnalysisFeed`  - one consumer task per run, fed by an UNBOUNDED
    in-memory FIFO of curated `L0Chunk` payloads.

WHAT THE QUEUE CARRIES, AND WHY IT MATTERS (#74). A chunk is a curated slice of
surface, never a signal: recon pushes each freshly-curated job's `AssetDelta`s
+ observations (the payload the job's pods merged into the graph), and the
consumer pops ONE chunk per pass and consumes EXACTLY that chunk - no graph
re-read, no cumulative-surface pass, no coalescing. Each pushed chunk is
consumed exactly once, in order, so the union over consumed chunks is
by construction the run's settled surface (L1D-23 as a union over chunks, not
over re-read passes).

THE GUARANTEE (#74, inheriting #34 DQ1a/DQ2b). At-least-once OBSERVATION of
surface: every chunk pushed during the run is consumed by the analyser before
the run reaches its terminal state. Nothing is claimed about what the analyser
concluded. Because every layer beneath this one is fail-open, `drain` decides
`analysis_drained` from the TERMINAL chunk's CENSUS - what the consumer
actually entered - never from the fact that a coroutine returned.

MEMORY. The FIFO is unbounded BY OPERATOR DECISION: chunks are KB-scale (the
historical OOM was analyser residency, not queue payload), and a bound would
reintroduce exactly the recon<->analysis coupling this redesign removes. The
process-wide `ANALYSER_PASS_SEMAPHORE` of one in-flight pass remains the memory
guard that makes a concurrent consumer admissible at all.

Back-pressure is ABSENT on purpose: recon's push is best-effort and
non-blocking, and analysis never fails a healthy recon run.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.domain.types import AssetDelta, Observation

logger = logging.getLogger(__name__)

# ONE analyser pass in flight process-wide, across concurrent runs. This is the
# memory guard that makes a concurrent consumer admissible at all: the FR-STREAM /
# NM-7 ledger rejected a long-lived consumer as memory-unsafe on the constrained
# host, and a bounded one is only safe because N runs still cost one pass of
# residency. It is a MEMORY guard, not an availability guard - nothing that awaits
# a live tool run may be held inside it.
ANALYSER_PASS_SEMAPHORE = asyncio.Semaphore(1)

# How long `drain` waits for the terminal chunk's pass. On expiry the run completes
# with `analysis_drained: false` - an honest hole rather than an unbounded wait, and
# never a failed run.
ANALYSIS_DRAIN_DEADLINE_S = float(os.environ.get("ANALYSIS_DRAIN_DEADLINE_S", "600"))

# The BOUNDED grace the graceful stop (Fix 4) grants the in-flight pass after the
# deadline: long enough that a pass a little slower than the deadline still finishes
# and its work + Langfuse traces survive, but FINITE so a pass that HANGS cannot hold
# the run open forever. This closes the live wedge on run 27386f9c: the graceful path
# used to `await self._idle.wait()` with NO timeout, so a terminal pass blocked on a
# wedged provider socket (a dead half-open connection whose per-read timeout never
# trips) kept the run `running` indefinitely. On grace expiry the in-flight pass is
# cancelled and the run completes with the claim withheld - the deadline's original
# "honest hole, never an unbounded wait" contract, now honoured on the graceful path
# too. The total ceiling drain can spend is therefore `deadline + grace`.
ANALYSIS_DRAIN_GRACE_S = float(os.environ.get("ANALYSIS_DRAIN_GRACE_S", "300"))


class L0Chunk(BaseModel):
    """The queue element: a curated slice of L0 surface a recon job produced.

    Carries the job's curated `AssetDelta`s + triager `Observation`s - the exact
    payload the analyser consumes, exactly once - plus the provenance of the
    push. `terminal` marks the drain's end-marker (a property of the run, never
    of a job's payload)."""

    project_id: str
    run_id: str
    job: str = ""
    phase: int = -1
    assets: list[AssetDelta] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    terminal: bool = False


class FeedStats(BaseModel):
    """What the feed reports back into the run's stats. `analysis_drained` is the
    load-bearing field and is FALSE unless the terminal marker was consumed AND a
    pass actually entered dispatches (#34 DQ2b)."""

    model_config = ConfigDict(frozen=True)

    mode: str = "inline"
    advanced: int = 0
    passes: int = 0
    analysis_drained: bool = False
    consumer: str = "none"
    l0_assets_read: int = 0
    dispatches_entered: int = 0

    # THE stall predicate (#34 AST-DEC-09). `advance_blocked_s_max` is the longest
    # any single `push` held the recon job loop, measured at the seam itself -
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
    """The rollback path: `push` runs the chunk's pass on the caller's task and
    returns only when it is done. Kept so the flag is a genuine two-way door and
    no analysis code is forked."""

    mode = "inline"

    def __init__(self, project_id: str, run_id: str, *, pass_fn=None):
        self._project_id, self._run_id = project_id, run_id
        self._pass_fn = pass_fn
        self._advanced = 0
        self._passes = 0
        self._timings = _Timings()

    async def push(self, chunk: L0Chunk) -> None:
        self._advanced += 1
        started = time.monotonic()
        try:
            await self._run_pass(chunk)
            self._passes += 1
            self._timings.record_pass(time.monotonic() - started)
        except Exception:  # best-effort: analysis never aborts recon
            logger.warning("inline analysis pass raised for run %s job %s (recon continues)",
                           self._run_id, chunk.job, exc_info=True)
        finally:
            # For the inline feed the blocked time IS the pass time - which is
            # exactly the fact the assertion needs to be able to state.
            self._timings.record_blocked(time.monotonic() - started)

    async def _run_pass(self, chunk: L0Chunk):
        if self._pass_fn is not None:
            return await self._pass_fn(chunk)
        from polymerhus.analysis.supervisor import analyse_chunked
        return await analyse_chunked(chunk)

    async def drain(self, deadline: float = ANALYSIS_DRAIN_DEADLINE_S) -> FeedStats:
        """No-op: the inline feed has nothing outstanding by construction, because
        every `push` already ran to completion. It makes NO drained claim -
        `analysis_drained` stays false, because no terminal chunk pass was
        engineered (the last inline pass ran before the run's end)."""
        return FeedStats(mode=self.mode, advanced=self._advanced, passes=self._passes,
                         **self._timings.as_stats())


class QueuedAnalysisFeed:
    """The decoupled feed: `push` enqueues a curated chunk and returns immediately.

    One consumer task per run drains an UNBOUNDED FIFO of `L0Chunk` payloads,
    one chunk per pass, each consumed exactly once in push order. The consumer
    holds `ANALYSER_PASS_SEMAPHORE` for the duration of each pass, so
    concurrency across runs never becomes accumulation."""

    mode = "queued"

    def __init__(self, project_id: str, run_id: str, *, pass_fn=None, semaphore=None):
        self._project_id, self._run_id = project_id, run_id
        self._pass_fn = pass_fn
        self._sem = semaphore if semaphore is not None else ANALYSER_PASS_SEMAPHORE
        self._queue: asyncio.Queue[L0Chunk] = asyncio.Queue()
        self._advanced = 0
        self._passes = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._last_census = None
        self._task: asyncio.Task | None = None
        self._timings = _Timings()
        # Cumulative non-vacuity: did ANY pass this run actually enter a dispatch? The drained
        # claim needs this because a terminal chunk is a no-op by construction (it carries no
        # assets), yet the surface WAS observed - just not by it.
        self._observed_any = False
        # Run-total surface read across consumed chunks (each chunk exactly once, so this
        # IS the run's settled-surface size).
        self._l0_assets_read = 0

    def start(self) -> "QueuedAnalysisFeed":
        self._task = asyncio.create_task(self._consume(), name=f"analysis-consumer-{self._run_id}")
        return self

    async def push(self, chunk: L0Chunk) -> None:
        """Non-blocking, best-effort: enqueue the curated chunk. There is no
        back-pressure - the FIFO is unbounded by operator decision, and a bound
        would reintroduce the recon<->analysis coupling this redesign removes."""
        self._advanced += 1
        started = time.monotonic()
        self._idle.clear()
        self._queue.put_nowait(chunk)
        # Measured on EVERY path: the claim being made is about the caller - the
        # recon job loop - not about the happy path through this method.
        self._timings.record_blocked(time.monotonic() - started)

    async def _consume(self) -> None:
        while True:
            chunk = await self._queue.get()
            try:
                async with self._sem:
                    # Timed INSIDE the semaphore: `pass_seconds` must mean the work
                    # a pass did, not how long it queued behind another run's pass,
                    # or the non-vacuity guard ("some pass took real time") could be
                    # satisfied by contention alone.
                    started = time.monotonic()
                    result = await self._run_pass(chunk)
                    self._timings.record_pass(time.monotonic() - started)
                self._passes += 1
                if result is not None:
                    self._last_census = getattr(result, "census", None)
                    if getattr(self._last_census, "dispatches_entered", 0):
                        self._observed_any = True
                    self._l0_assets_read += len(chunk.assets)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception:  # a failed pass degrades that chunk, never the run
                logger.warning("analysis pass raised for run %s job %s (recon continues)",
                               self._run_id, chunk.job, exc_info=True)
            finally:
                self._queue.task_done()
                if self._queue.empty():
                    self._idle.set()

    async def _run_pass(self, chunk: L0Chunk):
        if self._pass_fn is not None:
            return await self._pass_fn(chunk)
        from polymerhus.analysis.supervisor import analyse_chunked
        return await analyse_chunked(chunk)

    async def drain(self, deadline: float = ANALYSIS_DRAIN_DEADLINE_S,
                    grace: float = ANALYSIS_DRAIN_GRACE_S) -> FeedStats:
        """Enqueue a TERMINAL chunk and wait for the consumer to go idle.

        The terminal marker is what makes the at-least-once-observation guarantee
        real: being consumed LAST (FIFO), it is consumed only after every pushed
        chunk has been - so the queue being empty when it is done IS the run's
        settled surface having been consumed, exactly once each. `analysis_drained`
        is decided from the terminal pass's census plus run non-vacuity: a run
        whose passes entered no dispatch cannot claim convergence. On deadline
        expiry the run still completes within a BOUNDED grace, with the claim
        explicitly withheld - never an unbounded wait."""
        await self.push(L0Chunk(
            project_id=self._project_id, run_id=self._run_id, terminal=True,
        ))
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=deadline)
        except asyncio.TimeoutError:
            # Fix 4 - GRACEFUL, not a mid-pass hard cancel: a hard cancel discards the
            # in-flight chunk's work and its Langfuse traces (the moodique cc29fd4a failure -
            # the whole terminal pass was killed, losing the katana surface). Instead stop
            # consuming and let the in-flight one finish. The fixed deadline is a test knob
            # (operator): a real run is not time-bounded and waits for analysis to settle.
            #
            # But the graceful wait is itself BOUNDED (run 27386f9c): it used to be an
            # unconditional `await self._idle.wait()`, so a terminal pass that HANGS - blocked
            # on a wedged provider socket whose per-read timeout never trips - held the run
            # `running` forever. Grant the in-flight pass a finite grace to finish on its own
            # (preserving its work + traces); if even that expires, fall through to `stop()`
            # below, which cancels it, and complete with `analysis_drained: false`.
            logger.warning("analysis drain deadline (%.0fs) reached for run %s; stopping new "
                           "passes, awaiting the in-flight pass (grace %.0fs)",
                           deadline, self._run_id, grace)
            try:
                await asyncio.wait_for(self._idle.wait(), timeout=grace)
            except asyncio.TimeoutError:
                logger.warning("analysis drain grace (%.0fs) expired for run %s; abandoning the "
                               "in-flight pass, completing with analysis_drained=false",
                               grace, self._run_id)
        census = self._last_census
        # Drained iff the terminal pass was observed (FIFO order makes this mean every
        # pushed chunk was consumed) AND some pass this run actually entered dispatches.
        drained = bool(
            census is not None
            and getattr(census, "terminal", False)
            and getattr(census, "unprocessed_after", 0) == 0
            and self._observed_any
        )
        await self.stop()
        return FeedStats(
            mode=self.mode, advanced=self._advanced, passes=self._passes,
            analysis_drained=drained,
            consumer=self._consumer_state(),
            l0_assets_read=self._l0_assets_read,
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
    Queued hands each chunk's pass to a per-run consumer (unbounded FIFO), keeping
    recon off the analyser's latency. `inline` remains the rollback path (the pre-#9
    behaviour) for a caller that sets `async_analysis_consumer=False` explicitly.

    The terminal pass stays gated on `streaming_analysis` (#34 DQ5a): off means off,
    byte-for-byte as today, so this flag cannot introduce post-recon batch analysis
    as a side effect of a scheduling change."""
    s = settings or {}
    if not s.get("streaming_analysis"):
        return "inline"
    return "inline" if s.get("async_analysis_consumer") is False else "queued"
