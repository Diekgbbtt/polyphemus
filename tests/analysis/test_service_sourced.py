"""Unit tier for the service-sourced pass, mode flag, trigger, terminal and stop
(T6, ADR D1-D5, D41-D44, D47).

Everything is injected (assign_fn / loop_fn / status_fn / pass_fn), so the whole
tier runs with no Neo4j, no LLM, no database and no module runtime.
"""
import asyncio

from polymerhus.analysis.assigner import AssignmentCensus
from polymerhus.analysis.feed import (
    L0Chunk,
    QueuedAnalysisFeed,
    resolve_analysis_mode,
    resolve_analysis_pass_fn,
    resolve_feed_mode,
)
from polymerhus.analysis.messages import StepReceipt, WriteCounts
from polymerhus.analysis.service_slice import ServiceLoopResult, UnitOutcome
from polymerhus.analysis.service_sourced import reset_pass_guard, service_sourced_pass
from polymerhus.analysis.supervisor import PassCensus, PassResult


def _run(coro):
    return asyncio.run(coro)


def _terminal_chunk(run_id="r1", project_id="p1"):
    return L0Chunk(project_id=project_id, run_id=run_id, terminal=True)


class _Assign:
    def __init__(self, census=None):
        self.census = census or AssignmentCensus(admitted=3, kept=2, written=2)
        self.calls = []
        self.persist_fn = None

    async def __call__(self, project_id, run_id, *, persist_fn=None, memory=None):
        self.calls.append((project_id, run_id))
        self.persist_fn = persist_fn
        self.memory = memory
        return self.census


class _Loop:
    def __init__(self, result=None):
        self.result = result or ServiceLoopResult(
            units=("checkout",),
            outcomes=(UnitOutcome(unit="checkout", role="mechanism_typist", status="written"),),
            receipts=(StepReceipt(dispatch_id="r1:checkout:mechanism_typist",
                                  role="mechanism_typist", phase="A1", status="written",
                                  written=WriteCounts(aggregates=1)),),
            aggregates_written=1,
        )
        self.calls = []

    async def __call__(self, project_id, run_id, *, memory=None, stop_fn=None, observe=True):
        self.calls.append({"project_id": project_id, "run_id": run_id, "stop_fn": stop_fn})
        return self.result


# --- the mode seam ------------------------------------------------------------

def test_resolve_analysis_mode_defaults_to_streamed_and_coerces_unknown():
    assert resolve_analysis_mode(None) == "streamed"
    assert resolve_analysis_mode({}) == "streamed"
    assert resolve_analysis_mode({"analysis_mode": "service_sourced"}) == "service_sourced"
    assert resolve_analysis_mode({"analysis_mode": "nonsense"}) == "streamed"


def test_service_sourced_does_not_require_streaming_analysis():
    """ADR D2: the incident must not recur as a silent no-op - the mode fires the
    queued feed on its own."""
    assert resolve_feed_mode({"analysis_mode": "service_sourced"}) == "queued"
    assert resolve_feed_mode({"streaming_analysis": False,
                              "analysis_mode": "service_sourced"}) == "queued"


def test_streamed_default_is_byte_unbroken_under_the_flag():
    """ADR D47: with the mode absent or streamed, every existing resolution is
    unchanged."""
    assert resolve_feed_mode(None) == "inline"
    assert resolve_feed_mode({}) == "inline"
    assert resolve_feed_mode({"streaming_analysis": True}) == "queued"
    assert resolve_feed_mode({"streaming_analysis": True,
                              "async_analysis_consumer": False}) == "inline"
    assert resolve_analysis_pass_fn(None) is None
    assert resolve_analysis_pass_fn({"analysis_mode": "streamed"}) is None


def test_service_sourced_selects_the_service_sourced_pass():
    from polymerhus.analysis.service_sourced import service_sourced_pass as expected

    assert resolve_analysis_pass_fn({"analysis_mode": "service_sourced"}) is expected


# --- the pass: trigger and gating ---------------------------------------------

def test_pass_withholds_when_recon_did_not_complete():
    assign, loop = _Assign(), _Loop()
    result = _run(service_sourced_pass(
        _terminal_chunk(), assign_fn=assign, loop_fn=loop,
        status_fn=lambda rid: "stopped", status_wait_s=0, observe=False,
    ))
    assert assign.calls == [] and loop.calls == []     # never runs on a stopped run
    assert result.census.terminal is True
    assert result.census.unprocessed_after == 0
    assert result.census.wrote is False                 # -> the feed says withheld


def test_pass_runs_assign_then_loop_once():
    reset_pass_guard()
    assign, loop = _Assign(), _Loop()
    result = _run(service_sourced_pass(
        _terminal_chunk(), assign_fn=assign, loop_fn=loop,
        status_fn=lambda rid: "complete", status_wait_s=0, observe=False,
    ))
    assert len(assign.calls) == 1 and len(loop.calls) == 1
    # stage 1 always precedes stage 2 (the barrier, ADR D6)
    assert loop.calls[0]["run_id"] == "r1"
    assert result.census.terminal is True
    assert result.census.unprocessed_after == 0
    assert result.census.wrote is True
    assert result.census.units_processed == 1
    assert result.census.aggregates_written == 3         # 2 written + 1 loop aggregate


def test_pass_is_guarded_once_per_run():
    reset_pass_guard()
    assign, loop = _Assign(), _Loop()
    args = dict(assign_fn=assign, loop_fn=loop,
                status_fn=lambda rid: "complete", status_wait_s=0, observe=False)
    _run(service_sourced_pass(_terminal_chunk("r-dup"), **args))
    _run(service_sourced_pass(_terminal_chunk("r-dup"), **args))
    assert len(assign.calls) == 1 and len(loop.calls) == 1   # the second marker is a no-op


def test_zero_units_yields_withheld():
    reset_pass_guard()
    assign = _Assign(census=AssignmentCensus())
    loop = _Loop(result=ServiceLoopResult())
    result = _run(service_sourced_pass(
        _terminal_chunk("r-zero"), assign_fn=assign, loop_fn=loop,
        status_fn=lambda rid: "complete", status_wait_s=0, observe=False,
    ))
    assert result.census.wrote is False
    assert result.census.units_processed == 0


def test_pass_resolves_the_analysis_run_id_for_the_census(monkeypatch):
    reset_pass_guard()
    import polymerhus.analysis.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "current_analysis_run_id", lambda rid: "ar-9")
    assign, loop = _Assign(), _Loop()
    _run(service_sourced_pass(
        _terminal_chunk("r-ar"), assign_fn=assign, loop_fn=loop,
        status_fn=lambda rid: "complete", status_wait_s=0, observe=False,
    ))
    # the census is keyed to the analysis run, not the recon run
    assert assign.calls == [("p1", "ar-9")]


# --- the feed classification (ADR D41, D42) -----------------------------------

def test_write_based_drain_ignores_dispatch_count():
    """A pass that entered dispatches but wrote nothing must NOT claim drained."""
    async def empty_pass(chunk):
        return PassResult(export=None, census=PassCensus(
            terminal=True, unprocessed_after=0, wrote=False, dispatches_entered=7))

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=empty_pass).start()
        await feed.signal_end()
        return await feed.wait_until_done()

    stats = _run(scenario())
    assert stats.dispatches_entered == 7          # the dispatches were entered...
    assert stats.status == "withheld"             # ...and still no drained claim
    assert stats.analysis_drained is False


def test_write_based_drain_claims_drained_when_something_was_written():
    async def wrote_pass(chunk):
        return PassResult(export=None, census=PassCensus(
            terminal=True, unprocessed_after=0, wrote=True, dispatches_entered=0))

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=wrote_pass).start()
        await feed.signal_end()
        return await feed.wait_until_done()

    stats = _run(scenario())
    assert stats.status == "drained"
    assert stats.analysis_drained is True


def test_mid_pass_stop_is_reported_stopped_not_drained():
    async def stopped_pass(chunk):
        return PassResult(export=None, census=PassCensus(
            terminal=True, unprocessed_after=0, wrote=True, stopped=True))

    async def scenario():
        feed = QueuedAnalysisFeed("p1", "r1", pass_fn=stopped_pass).start()
        await feed.signal_end()
        return await feed.wait_until_done()

    stats = _run(scenario())
    assert stats.status == "stopped"
    assert stats.analysis_drained is False


def test_feed_stopping_reflects_the_stop_event():
    feed = QueuedAnalysisFeed("p1", "r1")
    assert feed.stopping is False


# --- the pipeline push skip ---------------------------------------------------

class _RecordingFeed:
    mode = "queued"

    def __init__(self):
        self.pushed = 0
        self.signalled = 0
        self.pass_fn = None

    async def push(self, chunk):
        self.pushed += 1

    async def signal_end(self):
        self.signalled += 1

    async def stop(self):
        pass


def test_service_sourced_pipeline_pushes_no_chunk_and_still_signals_end(monkeypatch):
    from polymerhus.recon.control import pipeline
    from polymerhus.analysis import feed as feed_mod
    from polymerhus.recon.domain.types import PodExport

    recording = _RecordingFeed()

    def _get_or_create(project_id, run_id, *, pass_fn=None):
        recording.pass_fn = pass_fn
        return recording

    monkeypatch.setattr(feed_mod, "get_or_create_feed", _get_or_create)

    async def _run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success", assets_merged=1,
                          observations_merged=1)]

    asyncio.run(pipeline.run_pipeline(
        "proj1", run_id="run1",
        job_subset=["subfinder", "dnsx"],
        run_job=_run_job,
        load_settings=lambda project_id: {"target_domain": "*.t.com",
                                          "analysis_mode": "service_sourced"},
        registry=_FakeRegistry(),
        read_assets=lambda node_type, project_id, where=None: [{"name": "seed"}],
        with_analysis=False,
    ))

    assert recording.pushed == 0                 # no per-job chunk in service-sourced mode
    assert recording.signalled == 1              # the terminal marker still fires
    from polymerhus.analysis.service_sourced import service_sourced_pass

    assert recording.pass_fn is service_sourced_pass


def test_streamed_pipeline_keeps_pushing_chunks(monkeypatch):
    """ADR D47: the default path is untouched - one push per producing job."""
    from polymerhus.recon.control import pipeline
    from polymerhus.analysis import feed as feed_mod
    from polymerhus.recon.domain.types import PodExport

    recording = _RecordingFeed()
    monkeypatch.setattr(feed_mod, "get_or_create_feed",
                        lambda project_id, run_id, *, pass_fn=None: recording)

    async def _run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success", assets_merged=1,
                          observations_merged=1)]

    asyncio.run(pipeline.run_pipeline(
        "proj1", run_id="run1", job_subset=["subfinder", "dnsx"],
        run_job=_run_job,
        load_settings=lambda project_id: {"target_domain": "*.t.com",
                                          "streaming_analysis": True,
                                          "async_analysis_consumer": True},
        registry=_FakeRegistry(),
        read_assets=lambda node_type, project_id, where=None: [{"name": "seed"}],
        with_analysis=False,
    ))
    assert recording.pushed == 2


class _FakeRegistry:
    def __init__(self):
        self.set_run_status_calls = []

    def create_run(self, run_id, project_id):
        pass

    def set_run_status(self, run_id, status, current_phase=None):
        self.set_run_status_calls.append((run_id, status, current_phase))

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        pass
