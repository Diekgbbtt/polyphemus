"""Unit-tier assertions for the analysis feed (#74 payload FIFO).

Mechanises the redesign's contract over the pure feed seam with an injected
`pass_fn` - no LLM, no graph, no database:

- `push` is non-blocking; each pushed `L0Chunk` is consumed EXACTLY ONCE, in
  FIFO order, by the per-run consumer.
- `drain` enqueues a terminal marker and waits for the queue to empty, bounded
  by the deadline/grace; `analysis_drained` is the honest-hole claim: the
  terminal marker was consumed AND some pass actually entered dispatches.
- One chunk in flight process-wide across concurrent runs (the memory guard).
- The stall observable (AST-DEC-09): queued push never holds the recon job
  loop, inline push does (the rollback contract).
"""
import asyncio

import pytest

from polymerhus.analysis.feed import (
    InlineAnalysisFeed,
    L0Chunk,
    QueuedAnalysisFeed,
    resolve_feed_mode,
)
from polymerhus.analysis.supervisor import PassCensus, PassResult
from polymerhus.recon.domain.types import AssetDelta, Observation


def _run(coro):
    return asyncio.run(coro)


async def _drain(feed):
    """Recon's end-of-stream + the natural wait, the two steps that replaced the
    old `drain(deadline)` (#75): enqueue the terminal marker, then await the
    consumer's natural end. No deadline - every pass self-terminates (#73)."""
    await feed.signal_end()
    return await feed.wait_until_done()


def _chunk(job="katana", assets=None, observations=None, terminal=False, phase=0):
    return L0Chunk(project_id="p1", run_id="r1", job=job, phase=phase,
                   assets=assets or [], observations=observations or [],
                   terminal=terminal)


def _asset(path):
    return AssetDelta(type="Endpoint", identity={"path": path, "baseurl": "https://a"})


def _census(**kw):
    base = dict(l0_assets_read=10, chunks_built=1, dispatches_scheduled=1,
                dispatches_entered=1, aggregates_written=2)
    base.update(kw)
    return PassResult(export=None, census=PassCensus(**base))


# --- push does not run the pass on the caller's task --------------------------

def test_push_returns_before_the_chunk_is_consumed():
    entered = asyncio.Event()
    order = []

    async def slow_pass(chunk):
        order.append("pass-entered")
        entered.set()
        await asyncio.sleep(0.05)
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=slow_pass).start()
        await feed.push(_chunk())
        order.append("push-returned")       # must precede the pass entry
        await entered.wait()
        stats = await _drain(feed)
        return stats

    stats = _run(scenario())
    assert order[0] == "push-returned"      # the caller was never blocked
    assert stats.advanced >= 1              # non-vacuity: a chunk WAS enqueued
    assert stats.passes >= 1


# --- the FIFO: exactly-once, in order -----------------------------------------

def test_each_pushed_chunk_is_consumed_exactly_once_in_fifo_order():
    """The core #74 guarantee: no coalescing, no re-read - every pushed chunk is
    consumed exactly once, in push order, and the terminal marker is consumed
    LAST (after every pushed chunk)."""
    consumed: list[tuple[str, list]] = []

    async def record(chunk):
        consumed.append((chunk.job, sorted(a.identity["path"] for a in chunk.assets)))
        return _census(terminal=chunk.terminal)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=record).start()
        for path in ("/a", "/b", "/c"):
            await feed.push(_chunk(job=f"job-{path}", assets=[_asset(path)]))
        return await _drain(feed)

    stats = _run(scenario())
    # order: exactly the push order, then the terminal marker; each exactly once
    assert [c[0] for c in consumed] == ["job-/a", "job-/b", "job-/c", ""]
    assert [c[1] for c in consumed[:-1]] == [["/a"], ["/b"], ["/c"]]
    assert consumed[-1][1] == []                       # the marker carries no assets
    assert stats.passes == 4                           # 3 chunks + the terminal marker
    assert stats.analysis_drained is True              # marker consumed + work observed


def test_chunk_payload_rides_the_fifo_unchanged():
    """Payload fidelity: the exact curated assets + observations a recon job
    pushed arrive at the consumer untouched (no graph re-read in between)."""
    seen = {}
    assets = [_asset("/x"), _asset("/y")]
    obs = Observation(macro_kind="cors", severity="high", evidence="acao *",
                      rationale="wide-open CORS",
                      anchor={"type": "BaseURL", "identity": {"url": "https://a"}},
                      source_job="triager", source_tool="triager")

    async def record(chunk):
        if chunk.terminal:          # the drain's marker rides the same queue; ignore it
            return _census(terminal=True)
        seen["assets"] = list(chunk.assets)
        seen["observations"] = list(chunk.observations)
        seen["job"] = chunk.job
        seen["phase"] = chunk.phase
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=record).start()
        await feed.push(_chunk(job="katana", assets=assets, observations=[obs], phase=3))
        return await _drain(feed)

    _run(scenario())
    assert seen["job"] == "katana" and seen["phase"] == 3
    assert [a.identity for a in seen["assets"]] == [a.identity for a in assets]
    assert [o.evidence for o in seen["observations"]] == ["acao *"]


# --- analysis never fails recon ----------------------------------------------

def test_a_pass_that_always_raises_never_escapes():
    async def boom(chunk):
        raise RuntimeError("provider down")

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=boom).start()
        for i in range(3):
            await feed.push(_chunk(job=f"job{i}"))
        return await _drain(feed)

    stats = _run(scenario())                # no exception escapes
    assert stats.analysis_drained is False  # and it makes NO convergence claim
    assert stats.passes == 0


def test_inline_feed_also_swallows_a_raising_pass():
    async def boom(chunk):
        raise RuntimeError("provider down")

    async def scenario():
        feed = InlineAnalysisFeed("p1", "r1", pass_fn=boom)
        await feed.push(_chunk())
        return await feed.drain()

    stats = _run(scenario())
    assert stats.passes == 0


# --- the terminal marker, and its evidence bar (DQ2b) -------------------------

def test_drain_runs_a_terminal_pass_after_the_last_push():
    seen = []

    async def record(chunk):
        seen.append(chunk.terminal)
        return _census(terminal=chunk.terminal)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=record).start()
        await feed.push(_chunk("katana"))
        return await _drain(feed)

    stats = _run(scenario())
    assert seen[-1] is True                 # the LAST consume is the terminal one
    assert stats.analysis_drained is True


def test_a_run_that_observed_nothing_does_not_claim_drained():
    """The bar that makes the guarantee falsifiable: every layer beneath the
    feed is fail-open, so a run whose passes entered no dispatch must not claim
    convergence."""
    async def empty_pass(chunk):
        return _census(terminal=chunk.terminal, l0_assets_read=0, chunks_built=0,
                       dispatches_scheduled=0, dispatches_entered=0)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=empty_pass).start()
        await feed.push(_chunk())
        return await _drain(feed)

    stats = _run(scenario())
    assert stats.passes >= 1                # a pass DID run...
    assert stats.analysis_drained is False  # ...and still claims nothing


def test_scheduled_but_never_entered_does_not_claim_drained():
    """`dispatches_entered` is counted at the proposer body, not from the
    schedule: a dispatch scheduled but never entered is exactly the silent case."""
    async def never_entered(chunk):
        return _census(terminal=chunk.terminal, dispatches_scheduled=7, dispatches_entered=0)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=never_entered).start()
        await feed.push(_chunk())
        return await _drain(feed)

    assert _run(scenario()).analysis_drained is False


def test_dispatches_entered_accumulates_across_passes_not_just_the_terminal_one():
    """Regression: `dispatches_entered` is the SUM over every pass, not the value
    of the last census. The terminal marker is itself a final pass whose real
    census carries dispatches_entered=0 (it processes no surface), and it always
    lands last (FIFO) - so reading only `_last_census` reported 0 for a run that
    did real work (the live juice-shop-remote run: assigner entered 3 dispatches,
    stats said 0). Here a single working chunk enters 3 dispatches and the terminal
    pass enters 0; the run must report 3."""
    async def graded(chunk):
        if chunk.terminal:
            # the REAL terminal pass does no dispatch work
            return _census(terminal=True, dispatches_scheduled=0, dispatches_entered=0)
        return _census(dispatches_scheduled=3, dispatches_entered=3)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=graded).start()
        await feed.push(_chunk("httpx"))
        return await _drain(feed)

    stats = _run(scenario())
    assert stats.dispatches_entered == 3        # accumulated, not the terminal 0
    assert stats.analysis_drained is True       # and the run still drained
    assert stats.passes == 2                     # chunk + terminal marker


def test_a_slow_pass_drains_naturally_with_no_deadline(monkeypatch):
    """#75 D8: the internal drain deadline/grace is GONE. A pass slower than the
    old 600s deadline is NOT cancelled - the consumer drains naturally because
    every pass self-terminates (#73). Wrapped in a `wait_for` so a regression to
    an unbounded HANG fails the test instead of hanging the suite; the pass itself
    is a bounded sleep standing in for a legitimately slow reasoning pass."""
    async def slow(chunk):
        await asyncio.sleep(0.2)               # would have blown a sub-second deadline
        return _census(terminal=chunk.terminal)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=slow).start()
        await feed.push(_chunk())
        return await asyncio.wait_for(_drain(feed), timeout=5)

    stats = _run(scenario())
    assert stats.analysis_drained is True       # the slow pass was allowed to finish
    assert stats.pass_seconds_max >= 0.2        # non-vacuity: it really was slow


def test_graceful_stop_finishes_the_in_flight_chunk_and_preserves_the_rest():
    """#75 D7: stop lets the CURRENTLY-RUNNING chunk finish, consumes no FURTHER
    chunk, and leaves the remainder in the queue for a resume. `stop` NEVER cancels
    the in-flight pass (that would lose its work - the cc29fd4a failure)."""
    entered = asyncio.Event()
    release = asyncio.Event()
    consumed: list[str] = []

    async def gated(chunk):
        consumed.append(chunk.job)
        if chunk.job == "j0":
            entered.set()
            await release.wait()               # hold j0 in flight until we stop
        return _census(terminal=chunk.terminal)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=gated).start()
        for i in range(3):
            await feed.push(_chunk(job=f"j{i}"))   # j0 (in flight), j1, j2 (queued)
        await asyncio.wait_for(entered.wait(), timeout=5)
        stop_task = asyncio.ensure_future(feed.stop())
        await asyncio.sleep(0.02)              # let the stop request register
        release.set()                          # now let the in-flight j0 finish
        stats = await asyncio.wait_for(stop_task, timeout=5)
        return stats, feed

    stats, feed = _run(scenario())
    assert consumed == ["j0"]                  # j0 finished; j1,j2 were NOT consumed
    assert stats.status == "stopped"
    assert stats.analysis_drained is False     # no terminal marker -> no claim
    assert feed._queue.qsize() == 2            # j1,j2 preserved for a resume


# --- one chunk in flight process-wide -----------------------------------------

def test_one_analyser_chunk_in_flight_across_concurrent_runs():
    concurrent = {"now": 0, "max": 0}
    sem = asyncio.Semaphore(1)

    async def counting_pass(chunk):
        concurrent["now"] += 1
        concurrent["max"] = max(concurrent["max"], concurrent["now"])
        await asyncio.sleep(0.02)
        concurrent["now"] -= 1
        return _census()

    async def one_run(run_id):
        feed = QueuedAnalysisFeed("p1", run_id, pass_fn=counting_pass, semaphore=sem).start()
        await feed.push(L0Chunk(project_id="p1", run_id=run_id, job="katana"))
        await asyncio.sleep(0.01)
        return await _drain(feed)

    async def scenario():
        return await asyncio.gather(one_run("rA"), one_run("rB"))

    results = _run(scenario())
    assert concurrent["max"] == 1                       # never two at once
    assert sum(r.passes for r in results) >= 2          # non-vacuity: passes ran


# --- AST-DEC-09: the stall observable, measured at the seam -------------------

def test_queued_push_does_not_block_while_inline_push_does():
    """The stall predicate, stated as a COMPARISON between the two modes over
    the same slow pass - which is what makes it non-vacuous. A fast machine
    could make any single absolute threshold pass; only the contrast between
    the modes shows the blocking actually moved off the caller."""
    PASS_S = 0.15

    async def slow_pass(chunk):
        await asyncio.sleep(PASS_S)
        return _census()

    async def queued():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=slow_pass).start()
        for i in range(3):
            await feed.push(_chunk(f"job{i}"))
        return await _drain(feed)

    async def inline():
        feed = InlineAnalysisFeed("p1", "r1", pass_fn=slow_pass)
        for i in range(3):
            await feed.push(_chunk(f"job{i}"))
        return await feed.drain()

    q, i = _run(queued()), _run(inline())

    # non-vacuity: the SAME slow pass really ran under both modes, so the
    # difference below is about scheduling and not about doing less work.
    assert q.pass_seconds_max >= PASS_S
    assert i.pass_seconds_max >= PASS_S

    assert i.advance_blocked_s_max >= PASS_S      # inline: blocked IS the pass
    assert q.advance_blocked_s_max < PASS_S / 2   # queued: the caller walked away
    assert q.advance_blocked_s_total < i.advance_blocked_s_total


def test_push_blocking_is_measured_on_every_push():
    """The claim is about the CALLER, so every push is timed."""
    async def gated(chunk):
        await asyncio.sleep(0.05)
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=gated).start()
        for i in range(6):
            await feed.push(_chunk(f"job{i}"))
        return await _drain(feed)

    stats = _run(scenario())
    assert stats.advanced == 6                   # 6 recon pushes; the terminal marker is NOT a push (#75)
    assert stats.passes == 7                      # 6 chunks + the terminal marker consumed
    assert stats.advance_blocked_s_total >= 0.0  # every push was timed
    assert stats.advance_blocked_s_max < 0.05


# --- the mode seam (DQ5a: off means off) --------------------------------------

@pytest.mark.parametrize("settings,expected", [
    ({}, "inline"),                                          # streaming OFF -> off
    ({"streaming_analysis": True}, "queued"),                # #9: queued is the default
    ({"async_analysis_consumer": True}, "inline"),           # streaming OFF wins
    ({"streaming_analysis": True, "async_analysis_consumer": True}, "queued"),
    # explicit opt-back-into-inline is the only way to put the pass back on the
    # recon critical path (the pre-#9 rollback path).
    ({"streaming_analysis": True, "async_analysis_consumer": False}, "inline"),
])
def test_feed_mode_is_gated_on_streaming_analysis(settings, expected):
    assert resolve_feed_mode(settings) == expected


def test_registry_returns_the_same_feed_for_a_run_and_drops_it():
    """#75 D1: one feed per run in the process registry, so recon (producer) and
    the analysis module (consumer) share the SAME queue - and it is dropped on
    teardown (the memory bound, D12)."""
    from polymerhus.analysis.feed import drop_feed, get_feed, get_or_create_feed

    drop_feed("run-reg")                              # clean slate
    a = get_or_create_feed("p", "run-reg")
    b = get_or_create_feed("p", "run-reg")
    assert a is b                                     # same instance for a run_id
    assert get_feed("run-reg") is a
    drop_feed("run-reg")
    assert get_feed("run-reg") is None                # discarded on teardown
