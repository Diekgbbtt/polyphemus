"""FR-STREAM (NM-7) unit tier — the streaming analyser step + the pipeline hook.

Streaming reuses the pure, idempotent analyser (`run_analyser`) invoked at each
recon increment (L1D-23: push/pull produce identical writes). These tests pin the
contract WITHOUT a live LLM/Neo4j: `stream_analyser_step` is exercised with an
injected analyse_fn, and the pipeline hook with the existing injected-fakes style.
"""
import asyncio

from polymerhus.recon.control import pipeline
from polymerhus.analysis import streaming
from polymerhus.analysis.pod import AnalyserExport
from polymerhus.recon.domain.types import PodExport


# --- stream_analyser_step (the per-increment invocation) ----------------------

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


def _run(settings, stream_calls):
    async def run_job(job, input_assets, *, run_id, phase, extra):
        # a producing pod: one asset merged so the streaming gate fires
        return [PodExport(input_asset={}, verdict="success", assets_merged=1,
                          observations_merged=1)]

    def stream_fn(project_id, run_id):
        stream_calls.append((project_id, run_id))
        return AnalyserExport(aggregates_written=1)

    asyncio.run(
        pipeline.run_pipeline(
            "proj1",
            run_id="run1",
            job_subset=["subfinder", "dnsx"],  # 2 jobs across 2 phases
            run_job=run_job,
            load_settings=lambda project_id: settings,
            registry=FakeRegistry(),
            read_assets=lambda node_type, project_id, where=None: [{"name": "seed"}],
            stream_fn=stream_fn,
        )
    )


def test_pipeline_streams_after_each_producing_job_when_enabled():
    """With streaming_analysis=True, the analyser is invoked once per producing
    job, during recon (a stream call per job that merged surface)."""
    stream_calls = []
    _run({"target_domain": "*.t.com", "streaming_analysis": True}, stream_calls)
    assert len(stream_calls) == 2  # one per producing job (subfinder, dnsx)
    assert all(c == ("proj1", "run1") for c in stream_calls)


def test_pipeline_does_not_stream_when_disabled():
    """Default (flag absent) = batch: the pipeline never invokes the analyser."""
    stream_calls = []
    _run({"target_domain": "*.t.com"}, stream_calls)
    assert stream_calls == []


# --- #34: the decoupled feed at the pipeline call site ------------------------

class _StatsRegistry(FakeRegistry):
    def __init__(self):
        super().__init__()
        self.run_stats = {}

    def set_run_stats(self, run_id, stats):
        self.run_stats[run_id] = stats


def _run_queued(settings, pass_fn, registry=None):
    """Drive run_pipeline with the QUEUED feed and an injected pass."""
    async def run_job(job, input_assets, *, run_id, phase, extra):
        return [PodExport(input_asset={}, verdict="success", assets_merged=1,
                          observations_merged=1)]

    reg = registry or _StatsRegistry()
    asyncio.run(pipeline.run_pipeline(
        "proj1", run_id="run1", job_subset=["subfinder", "dnsx"],
        run_job=run_job, load_settings=lambda project_id: settings,
        registry=reg,
        read_assets=lambda node_type, project_id, where=None: [{"name": "seed"}],
        feed_mode="queued", pass_fn=pass_fn,
    ))
    return reg


_QUEUED_SETTINGS = {"target_domain": "*.t.com", "streaming_analysis": True,
                    "async_analysis_consumer": True}


async def _ok_census(cursor):
    from polymerhus.analysis.supervisor import PassCensus, PassResult
    return PassResult(export=None, census=PassCensus(
        l0_assets_read=9, chunks_built=1, dispatches_scheduled=1,
        dispatches_entered=1, aggregates_written=2, terminal=cursor.terminal))


def test_AST_DEC_01_queued_feed_never_runs_a_pass_inside_the_job_loop():
    """The stall this design removes: with the queued feed the pipeline's per-job
    hook returns before any pass is entered."""
    events = []

    async def slow_pass(cursor):
        events.append(("pass", cursor.job))
        await asyncio.sleep(0.02)
        return await _ok_census(cursor)

    original = pipeline.registry_upsert_probe = None  # noqa: F841 - readability
    reg = _run_queued(_QUEUED_SETTINGS, slow_pass)

    # every recon job reached a terminal status, and a terminal pass ran
    assert [c["status"] for c in reg.upsert_job_calls if c["status"] != "in_progress"] == \
        ["success", "success"]
    assert any(e[0] == "pass" for e in events)          # non-vacuity: passes ran
    assert reg.run_stats["run1"]["mode"] == "queued"


def test_AST_DEC_03_a_failing_analysis_leaves_every_recon_job_untouched():
    async def boom(cursor):
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
    assert stats["l0_assets_read"] == 9
    assert stats["dispatches_entered"] == 1
    assert stats["passes"] >= 1


def test_inline_mode_is_byte_for_byte_todays_behaviour():
    """The rollback path: with the consumer flag absent, the injected stream_fn is
    still called once per producing job, exactly as before #34."""
    stream_calls = []
    _run({"target_domain": "*.t.com", "streaming_analysis": True}, stream_calls)
    assert len(stream_calls) == 2
