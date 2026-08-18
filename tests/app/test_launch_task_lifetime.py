"""Task lifetime and log visibility for the fire-and-forget recon launch (unit tier).

Written while diagnosing live run 6b9358a0, which stopped 65s into katana leaving no
exception and no log line, in a `recon_runs` row still marked `running` with a frozen
heartbeat that the reaper flipped to `failed` six minutes later.

WHAT THE INVESTIGATION ACTUALLY FOUND, recorded because the wrong answer is
instructive: the first hypothesis was a garbage-collected task, since
`_schedule_pipeline` kept no reference to it. That hypothesis is WRONG, and the
assertion written to prove it passed without the fix - a task suspended on an await
is still referenced by the handle that will resume it, so it is not collectable
there. The real cause was outside the process: the container was recreated
underneath the run (`StartedAt` 43s after the last heartbeat, with a different
command and no bind mounts).

So the reference-keeping below is defensive correctness per the asyncio docs, and is
NOT claimed to fix that incident. What genuinely was a defect is the second half of
this file: the application's logs went nowhere, which is why the failure had to be
reconstructed from Postgres timestamps instead of read off a traceback.
"""
import asyncio
import logging
import time

import pytest

from polymerhus.app.logging_config import configure_logging


def _wait_until(pred, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


@pytest.fixture
def runtime():
    from polymerhus.app.runtime import RuntimeManager

    rm = RuntimeManager()
    rm.start()
    rm.register_module("recon")
    try:
        yield rm
    finally:
        rm.shutdown()


# --- 1. the launched task's lifetime ------------------------------------------

def test_the_launched_task_is_referenced_while_it_runs(runtime):
    """Since #122 the strong reference lives in the module runtime's per-module
    registry (ModuleHandle._runs) for the run's lifetime, not in an API-layer
    task set. The run must be registered while it runs and identifiable by name."""
    from polymerhus.project_management import api

    async def quick(project_id, *, run_id, job_subset=None, with_analysis=True):
        await asyncio.sleep(0.02)

    async def scenario():
        original = api.run_pipeline
        api.run_pipeline = quick
        try:
            api._schedule_pipeline("proj1", "run1", None)
            _wait_until(lambda: runtime.has_run("recon", "run1"), 5)
            await asyncio.sleep(0.1)
            _wait_until(lambda: not runtime.has_run("recon", "run1"), 5)
        finally:
            api.run_pipeline = original

    asyncio.run(scenario())


def test_the_runtime_registry_does_not_leak_after_completion(runtime):
    """The strong reference must not turn into an unbounded registry: the
    runtime's run registry unregisters at the terminal (`_tracked`'s `finally`),
    so a long-lived process launching runs all day retains nothing it finished."""
    from polymerhus.project_management import api

    async def quick(project_id, *, run_id, job_subset=None, with_analysis=True):
        await asyncio.sleep(0.02)
        return None

    async def scenario():
        original = api.run_pipeline
        api.run_pipeline = quick
        try:
            api._schedule_pipeline("proj1", "run1", None)
            _wait_until(lambda: runtime.has_run("recon", "run1"), 5)
        finally:
            api.run_pipeline = original

    asyncio.run(scenario())
    _wait_until(lambda: not runtime.has_run("recon", "run1"), 5)


def test_a_raising_pipeline_is_logged_not_swallowed(caplog, runtime):
    """The other half of why the failure was silent: if the task DOES raise, the
    traceback must reach a handler."""
    from polymerhus.project_management import api

    async def boom(project_id, *, run_id, job_subset=None, with_analysis=True):
        raise RuntimeError("pipeline exploded")

    async def scenario():
        original = api.run_pipeline
        api.run_pipeline = boom
        try:
            with caplog.at_level(logging.ERROR):
                api._schedule_pipeline("proj1", "run-boom", None)
                await asyncio.sleep(0.05)
        finally:
            api.run_pipeline = original

    asyncio.run(scenario())
    assert any("run-boom" in r.message and r.exc_info for r in caplog.records)


# --- 2. the logs that went nowhere --------------------------------------------

def test_configure_logging_gives_application_loggers_a_handler():
    """Uvicorn configures only `uvicorn*`, so `polymerhus.*` loggers had none: the
    analyser census, the feed's warnings and the pipeline's degradation lines were
    all discarded in production."""
    import io

    root = logging.getLogger()
    before = list(root.handlers)
    try:
        root.handlers = []
        buf = io.StringIO()
        configure_logging(stream=buf)
        logging.getLogger("polymerhus.analysis.feed").info("census: entered=3")
        out = buf.getvalue()
        assert "census: entered=3" in out
        assert "polymerhus.analysis.feed" in out      # the logger names itself
        assert "INFO" in out
    finally:
        root.handlers = before


def test_configure_logging_is_idempotent():
    """Applied at import AND potentially by a caller; a duplicated handler prints
    every line twice, which is its own kind of unreadable."""
    import io

    root = logging.getLogger()
    before = list(root.handlers)
    try:
        root.handlers = []
        buf = io.StringIO()
        configure_logging(stream=buf)
        configure_logging(stream=buf)
        logging.getLogger("polymerhus.x").warning("once")
        assert buf.getvalue().count("once") == 1
    finally:
        root.handlers = before


def test_configure_logging_silences_mcp_client_transport_noise():
    """Regression for the /health session-churn misdiagnosis (2026-07-29):
    `configure_logging` attaching a root handler made the MCP SDK's own INFO-level
    "GET stream disconnected, reconnecting" chatter visible for the first time -
    it fires once per session because kali's FastMCP server doesn't hold the
    streamable-http GET stream open, and every `/health` poll opens a fresh
    session. That noise looked like a new regression but was pre-existing and
    benign; `mcp` belongs in `_NOISY` alongside the other chatty transports so it
    doesn't bury real application log lines."""
    import io

    root = logging.getLogger()
    before = list(root.handlers)
    before_levels = {name: logging.getLogger(name).level for name in ("mcp", "polymerhus.x")}
    try:
        root.handlers = []
        buf = io.StringIO()
        configure_logging(stream=buf)
        logging.getLogger("mcp.client.streamable_http").info(
            "GET stream disconnected, reconnecting in 1000ms..."
        )
        logging.getLogger("polymerhus.x").info("a real application line")
        out = buf.getvalue()
        assert "reconnecting" not in out
        assert "a real application line" in out
    finally:
        root.handlers = before
        for name, level in before_levels.items():
            logging.getLogger(name).setLevel(level)


def test_a_bad_log_level_does_not_crash_the_process(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "BANANA")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        root.handlers = []
        assert configure_logging() is not None
    finally:
        root.handlers = before
