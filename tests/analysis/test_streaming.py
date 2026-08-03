"""FR-STREAM (NM-7) unit tier - the streaming analyser step + the pipeline hook.

Since #74 the analyser is chunk-fed: `start_analysis_feed` consumes curated
`L0Chunk` payloads exactly once, in push order; the batch adapter
`run_analyser_chunked` remains for callers without a chunk (L1D-23). These tests
pin the contract WITHOUT a live LLM/Neo4j: the steps are exercised with injected
passes, and the pipeline hook with the existing injected-fakes style.
"""
import asyncio

from polymerhus.recon.control import pipeline
from polymerhus.analysis import streaming
from polymerhus.analysis.pod import AnalyserExport
from polymerhus.recon.domain.types import PodExport


# --- stream_analyser_step (the batch invocatiaon, kept for non-feed callers) ---

def test_stream_step_uses_stable_stream_id_and_autodelivers():
    """A step runs the analyser under a STABLE stream-<run_id> id (so repeated
    steps MERGE idempotently) and lets it AUTO-DELIVER the current observations
    (observations arg left None -> run_analyser pulls the cumulative set)."""
    calls = []

    def fake_analyse(project_id, run_id, observations=None):
        calls.append((project_id, run_id, observations))
        return AnalyserExport(aggregates_written=3)

    out1 = streaming.stream_analyser_step("proj1", "runX", analyse_fn=fake_analyse)
    out2 = streaming.stream_analyser_step("proj1", "runX", analyse_fn=fake_analyse)

    assert out1.aggregates_written == 3
    # both steps use the SAME stable analyser id derived from the recon run_id
    assert calls[0][:2] == ("proj1", "stream-runX")
    assert calls[1][:2] == ("proj1", "stream-runX")
    # auto-deliver: the step does not pin an explicit observation list
    assert calls[0][2] is None
    assert out2 is not None


def test_stream_step_fail_open():
    """An analyser error degrades the step to None and never raises into recon."""
    def boom(project_id, run_id, observations=None):
        raise RuntimeError("analyser exploded")

    out = streaming.stream_analyser_step("proj1", "runX", analyse_fn=boom)
    assert out is None  # degraded, not raised


# --- pipeline hook (per-job streaming during recon) ---------------------------

class FakeRegistry:
    def __init__(self):
        self.set_run_status_calls = []
        self.upsert_job_calls = []

    def create_run(self, run_id, project_id):
        pass

    def set_run_status(self, run_id, status, current_phase=None):
        self.set_run_status_calls.append((run_id, status, current_phase))

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.upsert_job_calls.append({"phase": phase, "job": job, "status": status})


def _run(settings, pass_calls):
    async def _run_job(job, input_assets, *, run_id, phase, extra):
        # a producing pod: one asset merged so the streaming gate fires
        return [PodExport(input_asset={}, verdict="success", assets_merged=1,
                          observations_merged=1)]

    def pass_fn(chunk):
        pass_calls.append((chunk.project_id, chunk.run_id, chunk.job))

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "dnsx"],  # 2 jobs across 2 phases
            run_job=_run_job,
            load_settings=lambda project_id: settings,
            registry=FakeRegistry(),
            read_assets=lambda node_type, project_id, where=None: [{"name": "seed"}],
            pass_fn=pass_fn,
        )
    )


def test_pipeline_streams_after_each_producing_job_when_enabled():
    """With streaming on and the INLINE feed (async_analysis_consumer=False), one
    pass per producing job is entered INLINE on the job loop (a chunk per job that
    merged surface). Queued is the default; inline is opted into."""
    pass_calls = []
    _run({"target_domain": "*.t.com", "streaming_analysis": True,
          "async_analysis_consumer": False}, pass_calls)
    assert len(pass_calls) == 2  # one per producing job (subfinder, dnsx)
    assert all(c[:2] == ("proj1", "run1") for c in pass_calls)


def test_pipeline_does_not_stream_when_disabled():
    """Default (flag absent) = batch: the pipeline never invokes the analyser."""
    pass_calls = []
    _run({"target_domain": "*.t.com"}, pass_calls)
    assert pass_calls == []


# --- #34: the decoupled feed at the pipeline call site ------------------------

class _StatsRegistry(FakeRegistry):
    def __init__(self):
        super().__init__()
        self.run_stats = {}

    def set_run_stats(self, run_id, stats):
        self.run_stats[run_id] = stats


def _run_queued(settings, pass_fn, registry=None):
    """Drive run_pipeline with the QUEUED feed and an injected pass."""
    async def _run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success", assets_merged=1,
                          observations_merged=1)]

    reg = registry or _StatsRegistry()
    asyncio.run(pipeline.run_pipeline(
        "proj1", run_id="run1", job_subset=["subfinder", "dnsx"],
        run_job=_run_job, load_settings=lambda project_id: settings,
        registry=reg,
        read_assets=lambda node_type, project_id, where=None: [{"name": "seed"}],
        feed_mode="queued", pass_fn=pass_fn,
    ))
    return reg


_QUEUED_SETTINGS = {"target_domain": "*.t.com", "streaming_analysis": True,
                    "async_analysis_consumer": True}


async def _ok_census(chunk):
    from polymerhus.analysis.supervisor import PassCensus, PassResult
    return PassResult(export=None, census=PassCensus(
        l0_assets_read=len(chunk.assets), chunks_built=1, dispatches_scheduled=1,
        dispatches_entered=1, aggregates_written=2, terminal=chunk.terminal,
        unprocessed_after=0))


def test_AST_DEC_01_queued_feed_never_runs_a_pass_inside_the_job_loop():
    """The stall this design removes: with the queued feed the pipeline's per-job
    hook returns before any pass is entered."""
    events = []

    async def slow_pass(chunk):
        events.append(("pass", chunk.job))
        await asyncio.sleep(0.02)
        return await _ok_census(chunk)

    reg = _run_queued(_QUEUED_SETTINGS, slow_pass)

    # every recon job reached a terminal status, and a terminal pass ran
    assert [c["status"] for c in reg.upsert_job_calls if c["status"] != "in_progress"] == \
        ["success", "success"]
    assert any(e[0] == "pass" for e in events)          # non-vacuity: passes ran
    assert reg.run_stats["run1"]["mode"] == "queued"


def test_AST_DEC_03_a_failing_analysis_leaves_every_recon_job_untouched():
    async def boom(chunk):
        raise RuntimeError("provider down")

    reg = _run_queued(_QUEUED_SETTINGS, boom)
    assert [c["status"] for c in reg.upsert_job_calls if c["status"] != "in_progress"] == \
        ["success", "success"]
    assert ("run1", "complete", None) in reg.set_run_status_calls   # run still completes
    assert reg.run_stats["run1"]["analysis_drained"] is False       # claims nothing


def test_AST_DEC_04_run_stats_record_the_terminal_pass_census():
    reg = _run_queued(_QUEUED_SETTINGS, _ok_census)
    stats = reg.run_stats["run1"]
    assert stats["analysis_drained"] is True
    assert stats["l0_assets_read"] == 0  # the pushed chunks carried no payload
    assert stats["dispatches_entered"] == 1
    assert stats["passes"] >= 1


def test_inline_mode_consumes_each_chunk_inline():
    """The rollback path: with the consumer flag explicitly FALSE, each pushed
    chunk runs a pass on the caller's task, exactly as before #34's queuing."""
    pass_calls = []
    _run({"target_domain": "*.t.com", "streaming_analysis": True,
          "async_analysis_consumer": False}, pass_calls)
    assert len(pass_calls) == 2


def test_analyse_chunked_threads_delivered_observations_into_the_chunk_builder(monkeypatch):
    """L1 of the silent-empty-insight fix: the pass must thread the triager
    observations from the CHUNK into the chunk builder. Spy on chunks_for_job
    (returning [] short-circuits the pass before the graph/DB) to capture what it
    got."""
    from polymerhus.analysis import chunking, supervisor
    from polymerhus.analysis.feed import AssetDelta, L0Chunk
    from polymerhus.recon.domain.types import Observation

    monkeypatch.setenv("LLM_MODEL_ANALYSER", "openai:gpt-4o-mini")
    monkeypatch.setenv("API_KEY_OPENAI", "sk-test-not-used")
    captured = {}

    def spy_chunks_for_job(job, assets, observations=None, **kw):
        captured["observations"] = observations
        return []

    monkeypatch.setattr(chunking, "chunks_for_job", spy_chunks_for_job)
    obs = Observation(macro_kind="cors", severity="high", evidence="acao *",
                      rationale="wide-open CORS", anchor={"type": "BaseURL", "identity": {"url": "https://a"}},
                      source_job="triager", source_tool="triager")
    chunk = L0Chunk(project_id="p", run_id="run1",
                    assets=[AssetDelta(type="Endpoint", identity={"path": "/x", "baseurl": "https://a"})],
                    observations=[obs])
    result = asyncio.run(supervisor.analyse_chunked(
        chunk,
        invoke_fn=lambda messages: None,
        observe=False,
    ))
    assert captured["observations"] == [obs]
    assert result.census.unprocessed_after == 0


# --- #9: the phase-6 endpoint-reprofile pass is NOT re-streamed to proposers ---

class _RecordingFeed:
    """Captures every chunk the pipeline hands to `push`, without a queue - so the
    assertion is on WHICH jobs triggered an analyser signal, deterministically (no
    conflation)."""

    mode = "queued"

    def __init__(self):
        self.pushed_jobs = []

    async def push(self, chunk):
        self.pushed_jobs.append(chunk.job)

    async def drain(self, *a, **k):
        from polymerhus.analysis.feed import FeedStats
        return FeedStats(mode=self.mode)

    async def stop(self):
        pass


def test_endpoint_reprofile_job_does_not_advance_the_analyser(monkeypatch):
    """The httpx_reprofile pass (phase 6, `endpoint_profiling=True`) re-emits Endpoints
    already streamed, adding only a per-endpoint `profile`. Streaming those endpoints
    to the proposers again is redundant analysis - so a reprofile job that merges
    surface must NOT push a chunk, while ordinary producing jobs still do."""
    from polymerhus.analysis import feed as feed_mod

    recording = _RecordingFeed()
    monkeypatch.setattr(feed_mod, "start_analysis_feed", lambda *a, **k: recording)

    async def _run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success", assets_merged=1,
                          observations_merged=1)]

    asyncio.run(pipeline.run_pipeline(
        "proj1", run_id="run1",
        job_subset=["httpx", "httpx_reprofile"],  # producer then its reprofile
        run_job=_run_job,
        load_settings=lambda project_id: {
            "target_domain": "*.t.com", "streaming_analysis": True,
            "async_analysis_consumer": True},
        registry=_StatsRegistry(),
        read_assets=lambda node_type, project_id, where=None: [{"name": "seed"}],
    ))

    assert "httpx" in recording.pushed_jobs                 # ordinary producer still signals
    assert "httpx_reprofile" not in recording.pushed_jobs   # the reprofile pass does not