"""Unit-tier assertions for the analysis feed (#34 decoupling).

Mechanises AST-DEC-01..05 from `docs/design/recon-analysis-decoupling.md` §6, over
the pure feed seam with an injected `pass_fn` - no LLM, no graph, no database.

These are the red/green loop's tests: the feed is a pure scheduling component and
its whole contract (non-blocking advance, conflation, fail-open, the drain's
evidence bar, the process-wide bound) is observable without any live collaborator.
"""
import asyncio

import pytest

from polymerhus.analysis.feed import (
    AnalysisCursor,
    InlineAnalysisFeed,
    QueuedAnalysisFeed,
    resolve_feed_mode,
    start_analysis_feed,
)
from polymerhus.analysis.supervisor import PassCensus, PassResult


def _run(coro):
    return asyncio.run(coro)


def _cursor(job="katana", terminal=False):
    return AnalysisCursor(project_id="p1", run_id="r1", job=job, terminal=terminal)


def _census(**kw):
    base = dict(l0_assets_read=10, chunks_built=1, dispatches_scheduled=1,
                dispatches_entered=1, aggregates_written=2)
    base.update(kw)
    return PassResult(export=None, census=PassCensus(**base))


# --- AST-DEC-01: advance does not run the pass on the caller's task -----------

def test_AST_DEC_01_advance_returns_before_the_pass_is_entered():
    entered = asyncio.Event()
    order = []

    async def slow_pass(cursor):
        order.append("pass-entered")
        entered.set()
        await asyncio.sleep(0.05)
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=slow_pass).start()
        await feed.advance(_cursor())
        order.append("advance-returned")     # must precede the pass entry
        await entered.wait()
        stats = await feed.drain(deadline=5)
        return stats

    stats = _run(scenario())
    assert order[0] == "advance-returned"    # the caller was never blocked
    assert stats.advanced >= 1               # non-vacuity: a cursor WAS enqueued
    assert stats.passes >= 1


# --- AST-DEC-02: cursors coalesce, and the collapse is counted ----------------

def test_AST_DEC_02_five_signals_during_one_pass_yield_one_further_pass():
    gate = asyncio.Event()
    passes = []

    async def gated_pass(cursor):
        passes.append(cursor.job)
        if len(passes) == 1:
            await gate.wait()               # hold the first pass open
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=gated_pass).start()
        await feed.advance(_cursor("job0"))
        while not passes:                    # ensure pass 1 is genuinely in flight
            await asyncio.sleep(0)
        for i in range(5):
            await feed.advance(_cursor(f"job{i + 1}"))
        gate.set()
        return await feed.drain(deadline=5)

    stats = _run(scenario())
    # 6 advances + 1 terminal = 7 signals, but only TWO passes run: the first, held
    # open, and one more that subsumes everything raised while it was in flight -
    # including the terminal cursor, because cursors are cumulative and the later
    # one carries the earlier one's work. That is the whole point of conflation.
    assert stats.advanced == 7
    assert stats.passes == 2
    assert stats.coalesced == 5
    assert passes[0] == "job0"      # non-vacuity: the gated pass really ran first


# --- AST-DEC-03: analysis never fails recon ----------------------------------

def test_AST_DEC_03_a_pass_that_always_raises_never_escapes():
    async def boom(cursor):
        raise RuntimeError("provider down")

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=boom).start()
        for i in range(3):
            await feed.advance(_cursor(f"job{i}"))
        return await feed.drain(deadline=5)

    stats = _run(scenario())            # no exception escapes
    assert stats.analysis_drained is False   # and it makes NO convergence claim
    assert stats.passes == 0


def test_AST_DEC_03b_inline_feed_also_swallows_a_raising_pass():
    async def boom(cursor):
        raise RuntimeError("provider down")

    async def scenario():
        feed = InlineAnalysisFeed("p1", "r1", pass_fn=boom)
        await feed.advance(_cursor())
        return await feed.drain()

    stats = _run(scenario())
    assert stats.passes == 0


# --- AST-DEC-04: the terminal pass, and its evidence bar (DQ2b) --------------

def test_AST_DEC_04_drain_runs_a_terminal_pass_after_the_last_advance():
    seen = []

    async def record(cursor):
        seen.append(cursor.terminal)
        return _census(terminal=cursor.terminal)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=record).start()
        await feed.advance(_cursor("katana"))
        return await feed.drain(deadline=5)

    stats = _run(scenario())
    assert seen[-1] is True                  # the LAST pass is the terminal one
    assert stats.analysis_drained is True


def test_AST_DEC_04b_a_terminal_pass_that_observed_nothing_does_not_claim_drained():
    """The bar that makes the guarantee falsifiable: every layer beneath the feed is
    fail-open, so a pass that read an empty surface must not claim convergence."""
    async def empty_pass(cursor):
        return _census(terminal=cursor.terminal, l0_assets_read=0,
                       chunks_built=0, dispatches_scheduled=0, dispatches_entered=0)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=empty_pass).start()
        await feed.advance(_cursor())
        return await feed.drain(deadline=5)

    stats = _run(scenario())
    assert stats.passes >= 1                 # a pass DID run...
    assert stats.analysis_drained is False   # ...and still claims nothing


def test_AST_DEC_04c_scheduled_but_never_entered_does_not_claim_drained():
    """`dispatches_entered` is counted at the proposer body, not from the schedule:
    a dispatch scheduled but never entered is exactly the silent case."""
    async def never_entered(cursor):
        return _census(terminal=cursor.terminal, dispatches_scheduled=7, dispatches_entered=0)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=never_entered).start()
        await feed.advance(_cursor())
        return await feed.drain(deadline=5)

    assert _run(scenario()).analysis_drained is False


def test_AST_DEC_04d_deadline_expiry_completes_without_the_claim():
    async def hang(cursor):
        await asyncio.sleep(30)
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=hang).start()
        await feed.advance(_cursor())
        return await feed.drain(deadline=0.1)   # forced expiry

    stats = _run(scenario())                    # returns rather than hanging
    assert stats.analysis_drained is False


# --- AST-DEC-05: one pass in flight process-wide ------------------------------

def test_AST_DEC_02b_coalescing_never_demotes_a_pending_terminal_cursor():
    """`terminal` is a property of the RUN, not of the signal: once the run has
    stopped producing surface, a later cursor must not turn the terminal pass back
    into an ordinary one, or the drain waits for a pass that cannot arrive."""
    seen = []

    async def record(cursor):
        seen.append(cursor.terminal)
        return _census(terminal=cursor.terminal)

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=record)   # NOT started
        await feed.advance(_cursor(terminal=True))              # pending, unconsumed
        await feed.advance(_cursor("late-job"))                 # would demote it
        feed.start()
        return await feed.drain(deadline=5)

    stats = _run(scenario())
    assert seen[0] is True          # the surviving cursor kept terminal
    assert stats.analysis_drained is True


def test_AST_DEC_05_one_analyser_pass_in_flight_across_concurrent_runs():
    concurrent = {"now": 0, "max": 0}
    sem = asyncio.Semaphore(1)

    async def counting_pass(cursor):
        concurrent["now"] += 1
        concurrent["max"] = max(concurrent["max"], concurrent["now"])
        await asyncio.sleep(0.02)
        concurrent["now"] -= 1
        return _census()

    async def one_run(run_id):
        feed = QueuedAnalysisFeed("p1", run_id, pass_fn=counting_pass, semaphore=sem).start()
        await feed.advance(AnalysisCursor(project_id="p1", run_id=run_id, job="katana"))
        await asyncio.sleep(0.01)
        return await feed.drain(deadline=5)

    async def scenario():
        return await asyncio.gather(one_run("rA"), one_run("rB"))

    results = _run(scenario())
    assert concurrent["max"] == 1                       # never two at once
    assert sum(r.passes for r in results) >= 2          # non-vacuity: passes ran


# --- AST-DEC-09: the stall observable, measured at the seam -------------------

def test_AST_DEC_09_queued_advance_does_not_block_while_inline_advance_does():
    """The stall predicate, stated as a COMPARISON between the two modes over the
    same slow pass - which is what makes it non-vacuous. A fast machine could make
    any single absolute threshold pass; only the contrast between the modes shows
    the blocking actually moved off the caller.

    This replaces the originally specified observable (the gap between a job's
    `finished_at` and the next job's `started_at`), which cannot be computed:
    `upsert_job` never updates `started_at` ON CONFLICT and the pipeline inserts
    every job of a phase during phase setup, so that column times phase setup."""
    PASS_S = 0.15

    async def slow_pass(cursor):
        await asyncio.sleep(PASS_S)
        return _census()

    async def queued():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=slow_pass).start()
        for i in range(3):
            await feed.advance(_cursor(f"job{i}"))
        return await feed.drain(deadline=5)

    async def inline():
        feed = InlineAnalysisFeed("p1", "r1", pass_fn=slow_pass)
        for i in range(3):
            await feed.advance(_cursor(f"job{i}"))
        return await feed.drain()

    q, i = _run(queued()), _run(inline())

    # non-vacuity: the SAME slow pass really ran under both modes, so the
    # difference below is about scheduling and not about doing less work.
    assert q.pass_seconds_max >= PASS_S
    assert i.pass_seconds_max >= PASS_S

    assert i.advance_blocked_s_max >= PASS_S      # inline: blocked IS the pass
    assert q.advance_blocked_s_max < PASS_S / 2   # queued: the caller walked away
    assert q.advance_blocked_s_total < i.advance_blocked_s_total


def test_advance_blocking_is_measured_even_when_the_cursor_coalesces():
    """The claim is about the CALLER, so every path through advance is timed -
    including the one that drops a pending cursor rather than enqueuing."""
    async def gated(cursor):
        await asyncio.sleep(0.05)
        return _census()

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=gated).start()
        for i in range(6):
            await feed.advance(_cursor(f"job{i}"))
        return await feed.drain(deadline=5)

    stats = _run(scenario())
    assert stats.coalesced > 0                    # non-vacuity: cursors DID collapse
    assert stats.advance_blocked_s_total >= 0.0   # and every advance was timed
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
