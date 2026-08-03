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
    start_analysis_feed,
)
from polymerhus.analysis.supervisor import PassCensus, PassResult
from polymerhus.recon.domain.types import AssetDelta, Observation


def _run(coro):
    return asyncio.run(coro)


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
        stats = await feed.drain(deadline=5)
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
        return await feed.drain(deadline=5)

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
        return await feed.drain(deadline=5)

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
        return await feed.drain(deadline=5)

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
        return await feed.drain(deadline=5)

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
        return await feed.drain(deadline=5)

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
        return await feed.drain(deadline=5)

    assert _run(scenario()).analysis_drained is False


def test_deadline_expiry_completes_without_the_claim():
    async def hang(chunk):
        await asyncio.sleep(30)
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=hang).start()
        await feed.push(_chunk())
        return await feed.drain(deadline=0.1, grace=0.1)   # forced expiry, then bounded grace

    stats = _run(scenario())                    # returns rather than hanging (no 30s wait)
    assert stats.analysis_drained is False


def test_terminal_pass_that_hangs_is_bounded_by_the_grace_not_awaited_forever():
    """Regression for the live wedge (run 27386f9c): the graceful stop granted
    the in-flight pass an UNCONDITIONAL wait, so a pass that HANGS - blocked on
    a wedged provider socket whose per-read timeout never trips - held the run
    `running` forever. The grace makes the graceful path bounded: the in-flight
    pass gets a finite window to finish, then it is abandoned and the run
    completes with the claim withheld. `drain` is wrapped in its own `wait_for`
    so a regression to the unbounded await FAILS the test instead of hanging."""
    started = asyncio.Event()
    cancelled = {"was": False}

    async def hang(chunk):
        started.set()
        try:
            await asyncio.Event().wait()       # never set: the pass never completes on its own
        except asyncio.CancelledError:
            cancelled["was"] = True            # the grace-expiry stop() must cancel it
            raise

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=hang).start()
        await feed.push(_chunk())
        await asyncio.wait_for(started.wait(), timeout=5)      # the pass is genuinely in flight
        return await asyncio.wait_for(feed.drain(deadline=0.05, grace=0.05), timeout=5)

    stats = _run(scenario())                    # MUST return - the bug was an unbounded await
    assert stats.analysis_drained is False      # ...claim withheld
    assert stats.consumer == "stopped"          # ...the hung pass was cancelled, not awaited forever
    assert cancelled["was"] is True


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
        return await feed.drain(deadline=5)

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
        return await feed.drain(deadline=5)

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
        return await feed.drain(deadline=5)

    stats = _run(scenario())
    assert stats.advanced == 7                   # 6 job pushes + the drain's terminal marker
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


def test_start_analysis_feed_returns_the_mode_it_was_asked_for():
    assert isinstance(start_analysis_feed("p", "r", mode="inline"), InlineAnalysisFeed)

    async def scenario():
        feed = start_analysis_feed("p", "r", mode="queued", pass_fn=lambda c: None)
        assert isinstance(feed, QueuedAnalysisFeed)
        await feed.stop()

    _run(scenario())
