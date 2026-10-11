"""The analysis feed - the in-memory seam between the recon module and the
independent analysis module (#75, building on #74's payload FIFO).

Recon and analysis are two independent runtime units (asyncio tasks) that share
ONLY a per-run in-memory FIFO of curated `L0Chunk` payloads. This module owns:

  - `L0Chunk`            - the queue element (curated AssetDeltas + observations).
  - a PROCESS-LEVEL REGISTRY of one feed per run, keyed by `run_id`, so recon can
    push before analysis starts and analysis can attach to the same queue - and so
    the feed OUTLIVES the recon pipeline task (recon no longer owns it).
  - `QueuedAnalysisFeed` - the consumer engine: one task drains the FIFO, one chunk
    per pass, each consumed exactly once in push order, holding
    `ANALYSER_PASS_SEMAPHORE` per pass.
  - `InlineAnalysisFeed` - the rollback path (analysis on recon's task).

WHAT THE QUEUE CARRIES (#74). A chunk is a curated slice of surface, never a
signal: recon pushes each freshly-curated job's `AssetDelta`s + observations, and
the consumer pops ONE chunk per pass and consumes EXACTLY that chunk - no graph
re-read, no coalescing. Each pushed chunk is consumed exactly once, in order.

THE END-OF-STREAM SIGNAL (#75 D4). For the consumer to ever claim it drained the
run, it must know recon will push no more chunks. Recon signals this by enqueuing
a TERMINAL `L0Chunk` (via `signal_end`) on BOTH its complete and its stop/kill
paths - fire-and-forget, never waiting for analysis. The consumer consumes the
marker LAST (FIFO) and only then classifies the run `drained` (marker consumed AND
a pass entered a dispatch) or `withheld` (marker consumed but vacuous).

GRACEFUL STOP (#75 D7). Stopping the consumer lets the CURRENTLY-RUNNING chunk
finish; only FURTHER chunks are not consumed. The queue and its un-consumed chunks
are preserved (stop is "stop pulling new chunks", never "cancel the in-flight one"
and never "discard the queue"), so a fresh consumer can resume where it left off.

NO INTERNAL LENGTH GATE (#75 D8). There is no drain deadline or grace: with every
LLM call bounded by the escalating per-call budget (#73), a chunk pass always
self-terminates, so the consumer drains the queue naturally. Total wall-clock
gating lives in the e2e scripts, not here.

MEMORY. The FIFO is unbounded by operator decision (chunks are KB-scale); process
memory is bounded by run lifetime - a feed is dropped from the registry on
teardown. `ANALYSER_PASS_SEMAPHORE` (one pass in flight process-wide) is the
residency guard that makes a concurrent consumer admissible.
"""
from __future__ import annotations

import asyncio
import logging
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


def _default_sem():
    """Resolve the analysis pass gate (#121). When the module runtime is active
    (and the analysis module is registered), passes acquire the per-analysis-
    module gate so analysis can pause/resume independently; otherwise the legacy
    process-wide semaphore (the pre-#121 behavior, byte-for-byte)."""
    from polymerhus.app.runtime import get_active_runtime

    runtime = get_active_runtime()
    if runtime is not None:
        gate = runtime.gate("analysis")
        if gate is not None:
            return gate
    return ANALYSER_PASS_SEMAPHORE


def _census_observed(census) -> bool:
    """Whether a pass OBSERVED surface, for the drained claim (D4/DQ2b).

    A pass that carries an explicit write-based signal (`wrote`, ADR D41) is
    authoritative: the service-sourced pass writes only when it actually wrote, so
    a run where every Service degraded is not falsely reported drained. A pass with
    no such signal (the streamed chunked pass) falls back to the dispatch-entry
    count, byte-for-byte as before."""
    if census is None:
        return False
    wrote = getattr(census, "wrote", None)
    if wrote is not None:
        return bool(wrote)
    return bool(getattr(census, "dispatches_entered", 0) or 0)


class L0Chunk(BaseModel):
    """The queue element: a curated slice of L0 surface a recon job produced.

    Carries the job's curated `AssetDelta`s + triager `Observation`s - the exact
    payload the analyser consumes, exactly once - plus the provenance of the
    push. `terminal` marks the end-of-stream marker (a property of the run, never
    of a job's payload)."""

    project_id: str
    run_id: str
    job: str = ""
    phase: int = -1
    assets: list[AssetDelta] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    terminal: bool = False


class FeedStats(BaseModel):
    """What the consumer reports about a run's drain. `analysis_drained` is the
    load-bearing field and is FALSE unless the terminal marker was consumed AND a
    pass actually entered dispatches (#34 DQ2b). `status` is the analysis-run
    terminal status the analysis module persists (#75)."""

    model_config = ConfigDict(frozen=True)

    mode: str = "inline"
    status: str = ""            # drained | withheld | stopped (analysis-run status, #75)
    advanced: int = 0
    passes: int = 0
    analysis_drained: bool = False
    consumer: str = "none"
    l0_assets_read: int = 0
    dispatches_entered: int = 0

    # THE stall predicate (#34 AST-DEC-09). `advance_blocked_s_max` is the longest
    # any single `push` held the recon job loop, measured at the seam itself.
    advance_blocked_s_max: float = 0.0
    advance_blocked_s_total: float = 0.0
    pass_seconds_max: float = 0.0
    pass_seconds_total: float = 0.0


class _Timings:
    """Max/total accumulators for the two durations that decide AST-DEC-09."""

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
    no analysis code is forked. It is fully COUPLED (no independent analysis run):
    it exists only for `async_analysis_consumer=False`."""

    mode = "inline"

    def __init__(self, project_id: str, run_id: str, *, pass_fn=None):
        self._project_id, self._run_id = project_id, run_id
        self._pass_fn = pass_fn
        self._sem = _default_sem()
        self._advanced = 0
        self._passes = 0
        self._timings = _Timings()

    @property
    def stopping(self) -> bool:
        """The inline feed runs each pass to completion on the caller's task, so
        there is no in-flight boundary to stop at: never stopping."""
        return False

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
            self._timings.record_blocked(time.monotonic() - started)

    async def signal_end(self) -> None:  # no-op: inline has nothing outstanding
        return None

    async def _run_pass(self, chunk: L0Chunk):
        from polymerhus.app.llm.checkpoints import module_context

        async with self._sem:
            with module_context("analysis"):
                if self._pass_fn is not None:
                    return await self._pass_fn(chunk)
                from polymerhus.analysis.supervisor import analyse_chunked

                return await analyse_chunked(chunk)

    async def drain(self) -> FeedStats:
        """No-op: every inline `push` already ran to completion. Makes no drained
        claim (`analysis_drained` stays false)."""
        return FeedStats(mode=self.mode, advanced=self._advanced, passes=self._passes,
                         **self._timings.as_stats())

    async def stop(self) -> None:
        return None


class QueuedAnalysisFeed:
    """The decoupled consumer engine (#74/#75): recon pushes chunks, the analysis
    module runs the consumer.

    ONE consumer task per run drains an UNBOUNDED per-run FIFO, one chunk per pass,
    each consumed exactly once in push order, holding `ANALYSER_PASS_SEMAPHORE` per
    pass. The consumer ENDS NATURALLY when it consumes the terminal marker (D4) or
    is gracefully STOPPED (D7): there is no drain deadline (D8)."""

    mode = "queued"

    def __init__(self, project_id: str, run_id: str, *, pass_fn=None, semaphore=None):
        self._project_id, self._run_id = project_id, run_id
        self._pass_fn = pass_fn
        self._sem = semaphore if semaphore is not None else _default_sem()
        self._queue: asyncio.Queue[L0Chunk] = asyncio.Queue()
        self._advanced = 0
        self._passes = 0
        self._last_census = None
        self._task: asyncio.Task | None = None
        self._timings = _Timings()
        # Non-vacuity across the run: did ANY pass enter a dispatch? The drained claim
        # needs this because the terminal marker is a no-op by construction.
        self._observed_any = False
        self._l0_assets_read = 0
        self._stopped_any = False
        # Dispatches entered across ALL passes. Accumulated (not read from the last
        # census) because the terminal marker is itself a final pass whose census
        # carries zero dispatches - reading only `_last_census` would report 0 for a
        # run that did real work, since the terminal pass always lands last (FIFO).
        self._dispatches_entered = 0
        # Lifecycle events. `_done` is set when the consumer reaches a terminal state
        # (marker consumed, or graceful stop); `_stop_event` requests a graceful stop.
        self._done = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._status = ""  # drained | withheld | stopped, set when the consumer ends

    # --- producer side (recon) ------------------------------------------------

    async def push(self, chunk: L0Chunk) -> None:
        """Non-blocking, best-effort: enqueue a curated chunk. No back-pressure -
        the FIFO is unbounded by operator decision (a bound would reintroduce the
        recon<->analysis coupling this redesign removes). Async only to match the
        inline feed's signature; it never awaits."""
        self._advanced += 1
        started = time.monotonic()
        self._queue.put_nowait(chunk)
        # Measured on EVERY path: the claim is about the caller (the recon loop).
        self._timings.record_blocked(time.monotonic() - started)

    async def signal_end(self) -> None:
        """Enqueue the terminal marker: recon telling analysis "no more chunks"
        (D4). Fire-and-forget, on BOTH recon-complete and recon-stop. Idempotent
        enough - a second marker is just consumed as another no-op terminal pass."""
        self._queue.put_nowait(L0Chunk(
            project_id=self._project_id, run_id=self._run_id, terminal=True,
        ))

    # --- consumer side (analysis) ---------------------------------------------

    @property
    def stopping(self) -> bool:
        """Whether a graceful stop has been requested (D7). The service-sourced
        pass reads this between Service units so a long pass stops at a unit
        boundary (ADR D42)."""
        return self._stop_event.is_set()

    def start(self) -> "QueuedAnalysisFeed":
        self._done.clear()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._consume(), name=f"analysis-consumer-{self._run_id}")
        return self

    async def _consume(self) -> None:
        """Drain the FIFO one chunk per pass. Ends on the terminal marker (natural
        drain) or a graceful stop. The stop race NEVER cancels a get that already
        returned a chunk (that would lose it); it only cancels a still-pending get,
        which has removed nothing from the queue - so a stop leaves un-consumed
        chunks intact and in order for a resume."""
        pending_get: asyncio.Task | None = None
        try:
            while True:
                if self._stop_event.is_set():
                    self._status = "stopped"
                    break
                if pending_get is None:
                    pending_get = asyncio.ensure_future(self._queue.get())
                stop_wait = asyncio.ensure_future(self._stop_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        {pending_get, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    if not stop_wait.done():
                        stop_wait.cancel()
                if pending_get not in done:
                    # Stop won while we were waiting for a chunk: no pass is in flight
                    # and `pending_get` has dequeued nothing, so it is safe to abandon.
                    self._status = "stopped"
                    break
                chunk = pending_get.result()
                pending_get = None
                # Process this chunk FULLY - it is the in-flight pass a graceful stop
                # must let finish (D7). A pass failure degrades that chunk, not the run.
                try:
                    async with self._sem:
                        started = time.monotonic()
                        result = await self._run_pass(chunk)
                        self._timings.record_pass(time.monotonic() - started)
                    self._passes += 1
                    if result is not None:
                        self._last_census = getattr(result, "census", None)
                        entered = getattr(self._last_census, "dispatches_entered", 0) or 0
                        self._dispatches_entered += entered
                        if _census_observed(self._last_census):
                            self._observed_any = True
                        if getattr(self._last_census, "stopped", False):
                            self._stopped_any = True
                        self._l0_assets_read += len(chunk.assets)
                except asyncio.CancelledError:
                    self._queue.task_done()
                    raise
                except Exception:
                    logger.warning("analysis pass raised for run %s job %s (drain continues)",
                                   self._run_id, chunk.job, exc_info=True)
                finally:
                    self._queue.task_done()
                if chunk.terminal:
                    # The marker is consumed LAST (FIFO), so every pushed chunk has been
                    # consumed. Classify the run (D4): a MID-PASS stop is `stopped`, never
                    # `drained` (ADR D42); otherwise drained iff a pass observed surface
                    # (write-based where the pass says so, ADR D41).
                    if self._stopped_any:
                        self._status = "stopped"
                    else:
                        self._status = "drained" if self._observed_any else "withheld"
                    break
        finally:
            if pending_get is not None and not pending_get.done():
                pending_get.cancel()  # still-pending get dequeued nothing - safe
            self._done.set()

    async def _run_pass(self, chunk: L0Chunk):
        from polymerhus.app.llm.checkpoints import module_context

        with module_context("analysis"):
            if self._pass_fn is not None:
                return await self._pass_fn(chunk)
            from polymerhus.analysis.supervisor import analyse_chunked

            return await analyse_chunked(chunk)

    async def wait_until_done(self) -> FeedStats:
        """Await the consumer's natural end (terminal marker) or graceful stop.
        NO deadline (D8): a slow drain settles naturally because every pass
        self-terminates (#73). Returns the run's FeedStats."""
        await self._done.wait()
        return self._stats()

    async def stop(self) -> FeedStats:
        """Graceful stop (D7): request the consumer to finish its in-flight chunk
        and consume no further chunk. Preserves the queue for a resume. Awaits the
        consumer to settle, then returns its stats."""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: B014 - stop must not raise
                pass
        return self._stats()

    async def cancel(self) -> None:
        """Hard cancel (process shutdown / abnormal only). Unlike `stop`, this does
        not wait for the in-flight chunk - use only when the process is going away."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: B014
            pass

    def _stats(self) -> FeedStats:
        census = self._last_census
        # A drained claim is only made from the DRAINED terminal path: a mid-pass
        # stop (ADR D42) consumed a marker too, but the pass was interrupted, so it
        # must not read as convergence.
        drained = bool(
            self._status == "drained"
            and census is not None
            and getattr(census, "terminal", False)
            and getattr(census, "unprocessed_after", 0) == 0
            and self._observed_any
        )
        return FeedStats(
            mode=self.mode, status=self._status,
            advanced=self._advanced, passes=self._passes,
            analysis_drained=drained, consumer=self._consumer_state(),
            l0_assets_read=self._l0_assets_read,
            dispatches_entered=self._dispatches_entered,
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


# --- process-level per-run feed registry (#75 D1) -----------------------------
#
# One feed per run, keyed by run_id, so recon (producer) and analysis (consumer)
# reference the SAME queue and the feed OUTLIVES the recon pipeline task. The
# registry is the seam that decouples the two modules' lifecycles.

_FEEDS: dict[str, QueuedAnalysisFeed] = {}


def get_or_create_feed(project_id: str, run_id: str, *, pass_fn=None) -> QueuedAnalysisFeed:
    """Return the run's feed, creating (and registering) it on first touch. Recon
    calls this to push; the analysis module calls it to start the consumer - both
    get the same instance for a run_id."""
    feed = _FEEDS.get(run_id)
    if feed is None:
        feed = QueuedAnalysisFeed(project_id, run_id, pass_fn=pass_fn)
        _FEEDS[run_id] = feed
    return feed


def get_feed(run_id: str) -> QueuedAnalysisFeed | None:
    return _FEEDS.get(run_id)


def drop_feed(run_id: str) -> None:
    """Discard a run's feed (and its queue) on teardown - the memory bound (D12)."""
    _FEEDS.pop(run_id, None)


# The analysis modes (ADR D2): `streamed` is the untouched default; `service_sourced`
# promotes the business Service to the pipeline unit.
ANALYSIS_MODES: tuple[str, ...] = ("streamed", "service_sourced")


def resolve_analysis_mode(settings: dict | None) -> str:
    """The project's analysis mode (ADR D2), read at ONE seam.

    Defaults to `streamed`; an absent or unknown value coerces to `streamed` (the
    fail-safe direction: the new mode is only ever entered on an explicit,
    recognised value). `service_sourced` is the flag the whole service-sourced
    pipeline hangs off - see `resolve_feed_mode` (it fires the queued feed on its
    own, no `streaming_analysis` needed) and `resolve_analysis_pass_fn`."""
    s = settings or {}
    mode = str(s.get("analysis_mode") or "streamed").strip()
    if mode not in ANALYSIS_MODES:
        logger.warning(
            "analysis_mode=%r is unknown (known: %s); using %r",
            mode, ", ".join(ANALYSIS_MODES), "streamed",
        )
        return "streamed"
    return mode


def resolve_hunt_after_analysis(settings: dict | None) -> bool:
    """Whether a genuinely drained analysis chains ONE hunting run.

    Opt-in and default-OFF (`settings.recon.hunt_after_analysis`): the eval trial
    sequences the recon -> analysis -> hunting chain explicitly, so an implicit
    app-side launch would collide with the trial's own hunting launch (the
    one-live-run-per-project guard 409s). An internal caller enables the flag to
    get the ordering without sequencing it. A missing/absent value is False - the
    fail-safe direction, so the automatic chain is only entered on an explicit
    true."""
    s = settings or {}
    return bool(s.get("hunt_after_analysis"))


def resolve_analysis_pass_fn(settings: dict | None):
    """The `pass_fn` the mode selects (ADR D1): `service_sourced` gets the
    service-sourced pass; `streamed` gets None (the feed's own `analyse_chunked`
    default, byte-for-byte as today). Import is lazy so this module carries no
    pipeline dependency at import time."""
    if resolve_analysis_mode(settings) != "service_sourced":
        return None
    from polymerhus.analysis.service_sourced import service_sourced_pass

    return service_sourced_pass


def resolve_feed_mode(settings: dict | None) -> str:
    """`queued` is the DEFAULT whenever streaming analysis is on; `inline` only when
    explicitly opted back into (`async_analysis_consumer=False`).

    `service_sourced` fires the QUEUED feed on its own and does NOT require
    `streaming_analysis` (ADR D2): the terminal marker is the only trigger, so the
    decoupled consumer is the only admissible shape. For every other case the
    terminal pass stays gated on `streaming_analysis` (#34 DQ5a): off means off,
    byte-for-byte as today, so no scheduling change sneaks post-recon batch
    analysis in as a side effect."""
    s = settings or {}
    if resolve_analysis_mode(s) == "service_sourced":
        return "queued"
    if not s.get("streaming_analysis"):
        return "inline"
    return "inline" if s.get("async_analysis_consumer") is False else "queued"
