"""Task lifetime and log visibility for the fire-and-forget recon launch (unit tier).

Written while diagnosing live run 6b9358a0, which stopped 65s into katana leaving no
exception and no log line, in a `recon_runs` row still marked `running` with a frozen
heartbeat that the reaper flipped to `failed` six minutes later.

WHAT THE INVESTIGATION ACTUALLY FOUND, recorded because the wrong answer is
instructive: the first hypothesis was a garbage-collected task, since
`_launch_pipeline` kept no reference to it. That hypothesis is WRONG, and the
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

from polymerhus.app.logging_config import configure_logging


# --- 1. the launched task's lifetime ------------------------------------------

def test_the_launched_task_is_referenced_while_it_runs():
    """The asyncio docs require the caller to retain a reference for the task's
    lifetime; the event loop keeps only a weak one."""
    from polymerhus.project_management import api

    async def quick(project_id, *, run_id, job_subset=None):
        await asyncio.sleep(0.02)

    async def scenario():
        original = api.run_pipeline
        api.run_pipeline = quick
        try:
            api._launch_pipeline("proj1", "run1", None)
            held = {t.get_name() for t in api._IN_FLIGHT}
            assert held == {"recon-pipeline-run1"}   # named, so it is identifiable
            await asyncio.sleep(0.1)
        finally:
            api.run_pipeline = original

    asyncio.run(scenario())


def test_the_in_flight_set_does_not_leak_after_completion():
    """Holding the reference must not turn into an unbounded set: a long-lived
    process launching runs all day would otherwise retain every task it ever ran."""
    from polymerhus.project_management import api

    async def quick(project_id, *, run_id, job_subset=None):
        return None

    async def scenario():
        original = api.run_pipeline
        api.run_pipeline = quick
        try:
            api._launch_pipeline("proj1", "run1", None)
            assert len(api._IN_FLIGHT) == 1      # held WHILE running
            await asyncio.sleep(0.05)
        finally:
            api.run_pipeline = original

    asyncio.run(scenario())
    assert api._IN_FLIGHT == set()               # released once done


def test_a_raising_pipeline_is_logged_not_swallowed(caplog):
    """The other half of why the failure was silent: if the task DOES raise, the
    traceback must reach a handler."""
    from polymerhus.project_management import api

    async def boom(project_id, *, run_id, job_subset=None):
        raise RuntimeError("pipeline exploded")

    async def scenario():
        original = api.run_pipeline
        api.run_pipeline = boom
        try:
            with caplog.at_level(logging.ERROR):
                api._launch_pipeline("proj1", "run-boom", None)
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


def test_a_bad_log_level_does_not_crash_the_process(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "BANANA")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        root.handlers = []
        assert configure_logging() is not None
    finally:
        root.handlers = before
