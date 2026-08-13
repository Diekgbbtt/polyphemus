"""Unit tier: the module runtime manager + per-module lifecycle + feed gate (#121).

The CORE ticket of the module-runtime-independence workstream. These tests pin the
ratified topology on a REAL asyncio.Runner worker thread (never a mocked loop):

- ONE shared worker loop; modules are plain registry entries driven from the API
  thread via run_coroutine_threadsafe / call_soon_threadsafe only.
- runtime.schedule boots a run on the worker loop and refuses admission while the
  module is paused/draining/stopped.
- runtime.cancel_run hard-cancels via call_soon_threadsafe(task.cancel).
- the per-module lifecycle state machine with cooperative PAUSE: the gate holds
  the next unit at the dispatch point until RESUME; DRAIN settles to stopped and
  archives via the flush hook; PAUSE flushes nothing.
- the mandatory high-risk concurrency tests (a) recon + streamed analysis
  progressing concurrently, (b) pausing one module while the others keep
  progressing, (c) no permit/handle leak on pause+resume and cancel-while-waiting,
  (d) worst-case checkpoint retention bounded (#120).
- the feed's queued AND inline passes acquire the SAME per-analysis-module gate;
  the producer side (put_nowait) is untouched.
- module context reaches to_thread executor work scheduled through the runtime.

No live LLM / graph / database: feed passes are injected fakes and the pg
lifecycle writes are monkeypatched (unit tier, CODING_STANDARD sections 6, 10).
"""
import asyncio
import concurrent.futures
import threading
import time

import pytest

import polymerhus.analysis.lifecycle as lifecycle
import polymerhus.project_management.api as api_mod
from polymerhus.analysis.feed import (
    InlineAnalysisFeed,
    L0Chunk,
    QueuedAnalysisFeed,
    get_or_create_feed,
)
from polymerhus.analysis.supervisor import PassCensus, PassResult
from polymerhus.app.runtime import (
    ModuleAdmissionRefused,
    ModuleState,
    RunNotRegistered,
    RuntimeManager,
)


# --- helpers -----------------------------------------------------------------

def _chunk(project_id="p1", run_id="r1", job="katana", terminal=False):
    return L0Chunk(project_id=project_id, run_id=run_id, job=job,
                   assets=[], observations=[], terminal=terminal)


def _census(dispatches_entered=0, aggregates_written=0, **kw):
    base = dict(l0_assets_read=10, chunks_built=1, dispatches_scheduled=1,
                dispatches_entered=dispatches_entered,
                aggregates_written=aggregates_written)
    base.update(kw)
    return PassResult(export=None, census=PassCensus(**base))


async def _noop():
    return None


def _stub_pg(monkeypatch):
    from polymerhus.app.clients import pg
    monkeypatch.setattr(pg, "create_analysis_run", lambda *a, **k: None)
    monkeypatch.setattr(pg, "set_analysis_run_status", lambda *a, **k: None)


def _wait_until(pred, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def _wait_until_flat(seq, timeout):
    """Wait until `seq` stops growing across three samples (the in-flight unit
    finished and the next unit is blocked at the gate)."""
    deadline = time.monotonic() + timeout
    samples = []
    while time.monotonic() < deadline:
        samples.append(len(seq))
        if len(samples) >= 3 and samples[-1] == samples[-2] == samples[-3]:
            return
        time.sleep(0.02)
    raise AssertionError(f"sequence did not stabilise within {timeout}s")


class _CountState(dict):
    pass


def _compiled_graph(checkpointer):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    def node(state):
        return {"count": (state.get("count") or 0) + 1}

    builder = StateGraph(_CountState)
    builder.add_node("node", node)
    builder.add_edge(START, "node")
    builder.add_edge("node", END)
    return builder.compile(checkpointer=checkpointer)


# --- fixture ----------------------------------------------------------------

@pytest.fixture
def runtime():
    rm = RuntimeManager()
    rm.start()
    try:
        yield rm
    finally:
        rm.shutdown()


# --- topology: one loop, module registry, admission -------------------------

def test_constructs_registers_modules_on_one_worker_loop(runtime):
    recon = runtime.register_module("recon")
    analysis = runtime.register_module("analysis")
    hunting = runtime.register_module("hunting")

    assert runtime.state("recon") == ModuleState.RUNNING
    assert runtime.state("analysis") == ModuleState.RUNNING
    assert runtime.state("hunting") == ModuleState.RUNNING
    assert runtime.worker_thread is not None
    assert runtime.worker_thread.is_alive()
    assert runtime.loop is not None
    assert runtime.worker_thread.name.startswith("runtime-worker")
    assert recon.gate is not None
    assert analysis.gate is not None
    assert hunting.gate is not None
    assert analysis.gate is not recon.gate


def test_schedule_boots_a_run_on_the_worker_loop(runtime):
    runtime.register_module("recon")
    running_on = {}

    async def work():
        running_on["loop"] = asyncio.get_running_loop()
        running_on["thread"] = threading.current_thread()
        return "done"

    fut = runtime.schedule("recon", work(), name="run-1")
    assert fut.result(timeout=5) == "done"
    assert running_on["loop"] is runtime.loop
    assert running_on["thread"] is runtime.worker_thread


def test_call_marshals_a_coroutine_onto_the_worker_loop(runtime):
    seen = {}

    async def probe():
        seen["loop"] = asyncio.get_running_loop()
        return 42

    fut = runtime.call(probe())
    assert fut.result(timeout=5) == 42
    assert seen["loop"] is runtime.loop


def test_thread_is_worker_distinguishes_the_worker_thread(runtime):
    from_worker = {}

    async def probe():
        from_worker["worker"] = runtime.thread_is_worker()
        return None

    runtime.call(probe()).result(timeout=5)
    assert runtime.thread_is_worker() is False
    assert from_worker["worker"] is True


def test_schedule_refused_while_paused_draining_stopped(runtime):
    runtime.register_module("analysis")

    runtime.pause("analysis")
    coro = _noop()
    with pytest.raises(ModuleAdmissionRefused):
        runtime.schedule("analysis", coro, name="while-paused")
    coro.close()
    assert runtime.state("analysis") == ModuleState.PAUSED

    runtime.resume("analysis")
    assert runtime.schedule("analysis", _noop(), name="while-running").result(timeout=5) is None

    runtime.drain("analysis", timeout=5)
    assert runtime.state("analysis") == ModuleState.STOPPED
    coro = _noop()
    with pytest.raises(ModuleAdmissionRefused):
        runtime.schedule("analysis", coro, name="while-stopped")
    coro.close()


def test_cancel_run_hard_cancels_via_the_module_registry(runtime):
    runtime.register_module("recon")
    entered = threading.Event()
    cleaned_up = threading.Event()

    async def long_work():
        entered.set()
        try:
            await asyncio.sleep(30)
        finally:
            cleaned_up.set()

    fut = runtime.schedule("recon", long_work(), name="run-9")
    assert entered.wait(timeout=5)

    runtime.cancel_run("recon", "run-9")

    with pytest.raises(concurrent.futures.CancelledError):
        fut.result(timeout=5)
    assert cleaned_up.wait(timeout=5)
    assert runtime.run_ids("recon") == []


def test_cancel_run_unknown_run_raises(runtime):
    runtime.register_module("recon")
    with pytest.raises(RunNotRegistered):
        runtime.cancel_run("recon", "nope")


def test_run_ids_tracks_registered_runs(runtime):
    runtime.register_module("recon")
    runtime.schedule("recon", asyncio.sleep(5), name="r-a")
    runtime.schedule("recon", asyncio.sleep(5), name="r-b")
    _wait_until(lambda: set(runtime.run_ids("recon")) == {"r-a", "r-b"}, timeout=5)
    runtime.cancel_run("recon", "r-a")
    _wait_until(lambda: runtime.run_ids("recon") == ["r-b"], timeout=5)
    runtime.cancel_run("recon", "r-b")


# --- (a) recon + streamed analysis progress concurrently --------------------

def test_recon_and_streamed_analysis_progress_concurrently(runtime, monkeypatch):
    _stub_pg(monkeypatch)
    runtime.register_module("recon")
    runtime.register_module("analysis")

    events = []
    consumed = []

    async def analysis_pass(chunk):
        events.append(("pass", chunk.job))
        if chunk.job:
            consumed.append(chunk.job)
        if chunk.terminal:
            return _census(dispatches_entered=0, analysis_drained=True)
        return _census(dispatches_entered=1, aggregates_written=2,
                       analysis_drained=True)

    async def recon_work():
        feed = get_or_create_feed("p1", "run-abc", pass_fn=analysis_pass)
        lifecycle.start_analysis("p1", "run-abc", pass_fn=analysis_pass)
        for i in range(5):
            events.append(("push", i))
            await feed.push(_chunk("p1", "run-abc", job=f"job-{i}"))
            await asyncio.sleep(0.01)
        await feed.signal_end()

    fut = runtime.schedule("recon", recon_work(), name="run-abc")
    fut.result(timeout=10)

    assert runtime.wait_module_idle("analysis", timeout=10)
    assert consumed == ["job-0", "job-1", "job-2", "job-3", "job-4"]
    first_pass_at = next(i for i, ev in enumerate(events) if ev[0] == "pass")
    last_push_at = max(i for i, ev in enumerate(events) if ev[0] == "push")
    assert first_pass_at < last_push_at


# --- (b) pause one module while the others keep progressing -----------------

def test_pause_one_module_while_the_others_keep_progressing(runtime):
    runtime.register_module("recon")
    runtime.register_module("analysis")
    runtime.register_module("hunting")

    recon_progress = []
    analysis_progress = []
    hunting_progress = []

    async def recon_run():
        for i in range(200):
            recon_progress.append(i)
            await asyncio.sleep(0.002)

    async def analysis_run():
        gate = runtime.gate("analysis")
        for i in range(2000):
            async with gate:
                analysis_progress.append(i)
                await asyncio.sleep(0.001)

    async def hunting_run():
        for i in range(200):
            hunting_progress.append(i)
            await asyncio.sleep(0.002)

    fut_recon = runtime.schedule("recon", recon_run(), name="recon-1")
    fut_analysis = runtime.schedule("analysis", analysis_run(), name="analysis-1")
    fut_hunting = runtime.schedule("hunting", hunting_run(), name="hunting-1")

    _wait_until(
        lambda: len(recon_progress) > 0 and len(analysis_progress) > 0 and len(hunting_progress) > 0,
        timeout=5,
    )

    runtime.pause("analysis")
    _wait_until_flat(analysis_progress, timeout=5)
    time.sleep(0.05)
    frozen = len(analysis_progress)
    r0 = len(recon_progress)
    h0 = len(hunting_progress)
    time.sleep(0.15)
    assert len(analysis_progress) == frozen
    assert len(recon_progress) > r0
    assert len(hunting_progress) > h0

    runtime.resume("analysis")
    _wait_until(lambda: len(analysis_progress) > frozen, timeout=5)

    assert fut_recon.result(timeout=10) is None
    assert fut_hunting.result(timeout=10) is None
    assert fut_analysis.result(timeout=10) is None
    assert runtime.run_ids("analysis") == []


# --- (c) no permit/handle leak ---------------------------------------------

def test_no_permit_leak_on_pause_resume_cycles(runtime):
    runtime.register_module("analysis")
    gate = runtime.gate("analysis")

    async def gated_pass():
        async with gate:
            await asyncio.sleep(0.05)
        return "done"

    fut = runtime.schedule("analysis", gated_pass(), name="pass-1")
    for _ in range(5):
        runtime.pause("analysis")
        time.sleep(0.02)
        runtime.resume("analysis")
        time.sleep(0.02)
    assert fut.result(timeout=5) == "done"
    assert gate.available_permits() == gate.width
    assert runtime.run_ids("analysis") == []


def test_cancel_while_waiting_releases_the_permit_and_handle(runtime):
    runtime.register_module("analysis")
    gate = runtime.gate("analysis")
    entered = threading.Event()

    async def gated_loop():
        for _ in range(1000):
            async with gate:
                entered.set()
                await asyncio.sleep(0.005)
        return "done"

    fut = runtime.schedule("analysis", gated_loop(), name="waiter")
    assert entered.wait(timeout=5)
    runtime.pause("analysis")
    _wait_until(lambda: gate.available_permits() == 0, timeout=5)

    runtime.cancel_run("analysis", "waiter")
    with pytest.raises(concurrent.futures.CancelledError):
        fut.result(timeout=5)
    assert gate.available_permits() == gate.width
    assert runtime.run_ids("analysis") == []

    runtime.resume("analysis")

    async def quick_pass():
        async with gate:
            return "entered"

    ok = runtime.schedule("analysis", quick_pass(), name="after")
    assert ok.result(timeout=5) == "entered"
    assert gate.available_permits() == gate.width


def test_cancel_while_blocked_at_the_pause_event_leaks_no_permit(runtime):
    """The TRUE cancel-while-waiting case: a task that acquired the gate permit
    and is then BLOCKED at the pause event (not inside the gate body) is
    cancelled. `__aenter__` must release the acquired permit before re-raising,
    or the module loses a permit permanently (AC (c): no permit leak on
    cancel-while-waiting)."""
    runtime.register_module("analysis")
    gate = runtime.gate("analysis")
    first_body_exit = threading.Event()
    held = {"at_wait": False}

    async def gated_loop():
        for i in range(1000):
            async with gate:
                if i == 0:
                    first_body_exit.set()
                await asyncio.sleep(0.01)

    fut = runtime.schedule("analysis", gated_loop(), name="blocked")
    assert first_body_exit.wait(timeout=5)
    # The task is back in `__aenter__`: it has re-acquired the permit and is
    # blocked at `_running.wait()`. Pause clears the event so it stays blocked.
    runtime.pause("analysis")
    _wait_until(lambda: gate.available_permits() == 0, timeout=5)
    # Sanity: the task is NOT inside the gate body right now (its body sleeps
    # only 10ms, and we paused well after it re-entered the gate).
    time.sleep(0.05)
    held["at_wait"] = gate.available_permits() == 0

    runtime.cancel_run("analysis", "blocked")
    with pytest.raises(concurrent.futures.CancelledError):
        fut.result(timeout=5)
    assert gate.available_permits() == gate.width
    assert runtime.run_ids("analysis") == []

    runtime.resume("analysis")

    async def quick_pass():
        async with gate:
            return "entered"

    assert runtime.schedule("analysis", quick_pass(), name="after").result(timeout=5) == "entered"
    assert gate.available_permits() == gate.width


# --- (d) worst-case checkpoint retention bounded (#120) ---------------------

def test_runtime_scheduled_work_keeps_checkpoint_retention_bounded(runtime):
    from polymerhus.app.llm import checkpoints as C

    runtime.register_module("analysis")

    async def turn_burst():
        cp = C.get_session_checkpointer()
        graph = _compiled_graph(cp)
        tid = "run-abc:triager:single"
        for _ in range(5):
            graph.invoke({"count": 0}, config={"configurable": {"thread_id": tid}})
        retained = list(cp.list({"configurable": {"thread_id": tid}}))
        assert len(retained) == 1, f"retained {len(retained)} (must be latest-only)"
        return tid

    runtime.schedule("analysis", turn_burst(), name="burst").result(timeout=10)


# --- module context reaches to_thread executor work -------------------------

def test_module_context_reaches_to_thread_work_scheduled_through_the_runtime(runtime):
    from polymerhus.app.llm import checkpoints as C

    runtime.register_module("analysis")

    async def probe():
        loop_cp = C.get_session_checkpointer()
        offload_cp = await asyncio.to_thread(C.get_session_checkpointer)
        return loop_cp, offload_cp

    loop_cp, offload_cp = runtime.schedule("analysis", probe(), name="probe").result(timeout=5)

    fallback = C.get_session_checkpointer()
    assert loop_cp is not fallback
    assert offload_cp is loop_cp


# --- shutdown fan-out, pause vs drain semantics -----------------------------

def test_pause_flushes_nothing_and_shutdown_fans_out_flush_in_order(runtime):
    flushes = []

    def make_flush(name):
        def flush():
            flushes.append(name)
        return flush

    runtime.register_module("recon", hooks={"flush": make_flush("recon")})
    runtime.register_module("analysis", hooks={"flush": make_flush("analysis")})
    runtime.register_module("hunting", hooks={"flush": make_flush("hunting")})

    runtime.pause("analysis")
    time.sleep(0.05)
    assert flushes == []

    entered = threading.Event()

    async def forever():
        entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            pass

    fut = runtime.schedule("recon", forever(), name="live-1")
    assert entered.wait(timeout=5)

    runtime.shutdown()

    with pytest.raises(concurrent.futures.CancelledError):
        fut.result(timeout=5)
    assert flushes == ["recon", "analysis", "hunting"]
    assert runtime.state("recon") == ModuleState.STOPPED
    assert runtime.worker_thread is None
    assert runtime.loop is None


def test_drain_pauses_settles_flushes_and_reaches_stopped(runtime):
    flushes = []
    runtime.register_module("analysis", hooks={"flush": lambda: flushes.append("analysis")})
    started = threading.Event()
    finished = threading.Event()

    async def run_that_finishes():
        started.set()
        try:
            await asyncio.sleep(0.2)
        finally:
            finished.set()

    fut = runtime.schedule("analysis", run_that_finishes(), name="short")
    assert started.wait(timeout=5)

    runtime.drain("analysis", timeout=10)

    assert fut.result(timeout=5) is None
    assert finished.wait(timeout=5)
    assert flushes == ["analysis"]
    assert runtime.state("analysis") == ModuleState.STOPPED
    with pytest.raises(ModuleAdmissionRefused):
        runtime.schedule("analysis", _noop(), name="late")


def test_drain_invokes_the_registered_termination_hook(runtime):
    calls = []

    async def termination(module):
        calls.append(module)

    runtime.register_module("analysis", hooks={"termination": termination})
    runtime.drain("analysis", timeout=5)
    assert calls == ["analysis"]
    assert runtime.state("analysis") == ModuleState.STOPPED


def test_drain_times_out_and_hard_cancels_a_paused_run(runtime):
    runtime.register_module("analysis")
    gate = runtime.gate("analysis")

    async def gated_loop():
        for _ in range(1000):
            async with gate:
                await asyncio.sleep(0.01)

    fut = runtime.schedule("analysis", gated_loop(), name="loop")
    time.sleep(0.15)

    t0 = time.monotonic()
    runtime.drain("analysis", timeout=1.0)
    assert time.monotonic() - t0 < 10
    assert runtime.state("analysis") == ModuleState.STOPPED
    assert runtime.run_ids("analysis") == []
    with pytest.raises(concurrent.futures.CancelledError):
        fut.result(timeout=5)


# --- feed gate seam ---------------------------------------------------------

def test_feed_resolves_the_per_module_gate_when_runtime_is_active(runtime):
    runtime.register_module("analysis")
    feed = get_or_create_feed("p1", "r-gate")
    assert feed._sem is runtime.gate("analysis")


def test_inline_feed_acquires_the_same_per_module_gate(runtime):
    runtime.register_module("analysis")
    feed = InlineAnalysisFeed("p1", "r-gate", pass_fn=None)
    assert feed._sem is runtime.gate("analysis")


def test_queued_and_inline_passes_share_the_per_module_gate(runtime):
    runtime.register_module("analysis")
    concurrency = {"now": 0, "max": 0}

    async def pass_fn(chunk):
        concurrency["now"] += 1
        concurrency["max"] = max(concurrency["max"], concurrency["now"])
        await asyncio.sleep(0.03)
        concurrency["now"] -= 1
        if chunk.terminal:
            return _census(dispatches_entered=0, analysis_drained=True)
        return _census(dispatches_entered=1, aggregates_written=2,
                       analysis_drained=True)

    async def scenario():
        qfeed = QueuedAnalysisFeed("p1", "r-same", pass_fn=pass_fn)
        qfeed.start()
        ifeed = InlineAnalysisFeed("p1", "r-same", pass_fn=pass_fn)
        await asyncio.gather(
            qfeed.push(_chunk("p1", "r-same", job="q1")),
            ifeed.push(_chunk("p1", "r-same", job="i1")),
        )
        await qfeed.signal_end()
        await qfeed.wait_until_done()

    runtime.schedule("analysis", scenario(), name="gate-share").result(timeout=10)
    assert concurrency["max"] == 1
    assert concurrency["now"] == 0


def test_gate_width_defaults_to_config_for_analysis(runtime):
    from polymerhus.app.config import config as app_config
    assert app_config.ANALYSIS_PASS_GATE_WIDTH == 1
    handle = runtime.register_module("analysis")
    assert handle.gate.width == app_config.ANALYSIS_PASS_GATE_WIDTH


def test_gate_width_can_be_overridden_per_module(runtime):
    handle = runtime.register_module("recon", gate_width=2)
    assert handle.gate.width == 2


# --- lifecycle + api route through the runtime when active ------------------

def test_start_analysis_schedules_through_the_runtime_when_active(runtime, monkeypatch):
    _stub_pg(monkeypatch)
    runtime.register_module("analysis")

    arid = lifecycle.start_analysis("p1", "run-seam")

    assert arid is not None
    _wait_until(lambda: runtime.has_run("analysis", "run-seam"), timeout=5)
    assert lifecycle.is_analysing("run-seam") is True
    assert runtime.run_ids("analysis") == ["run-seam"]


def test_api_launch_pipeline_routes_through_the_runtime_when_active(runtime, monkeypatch):
    runtime.register_module("recon")

    async def fake_run_pipeline(project_id, *, run_id, job_subset=None, **kw):
        await asyncio.sleep(0.1)
        return "ran"

    monkeypatch.setattr(api_mod, "run_pipeline", fake_run_pipeline)

    api_mod._launch_pipeline("p1", "run-lp", None)
    _wait_until(lambda: runtime.has_run("recon", "run-lp"), timeout=5)
    runtime.cancel_run("recon", "run-lp")


# --- standalone fallback (no runtime): legacy path still works --------------

def test_lifecycle_works_without_an_active_runtime(monkeypatch):
    _stub_pg(monkeypatch)

    async def scenario():
        arid = lifecycle.start_analysis("p1", "run-standalone")
        assert arid is not None
        assert lifecycle.is_analysing("run-standalone") is True
        await lifecycle.stop_analysis("run-standalone")

    asyncio.run(scenario())
    assert lifecycle.is_analysing("run-standalone") is False


def test_api_launch_fallback_needs_a_loop_and_registers_the_task(monkeypatch):
    async def fake_run_pipeline(project_id, *, run_id, job_subset=None, **kw):
        await asyncio.sleep(0.05)
        return "ran"

    monkeypatch.setattr(api_mod, "run_pipeline", fake_run_pipeline)

    async def launch_scenario():
        api_mod._launch_pipeline("p1", "run-fallback", None)
        task = api_mod._RECON_TASKS.get("run-fallback")
        assert task is not None
        task.cancel()

    asyncio.run(launch_scenario())
