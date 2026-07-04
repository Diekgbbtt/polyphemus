"""Tests for `agent.recon.async_bridge.run_coro_blocking` - the fix for the
platform-wide bug where a sync pod node (`default_exec_fn`/
`default_run_crawl_fn`) called `asyncio.run(...)` while already running
inside the pipeline's event loop (routes.py -> asyncio.create_task ->
pipeline.run_pipeline -> asyncio.gather -> run_job (awaited) -> sync
graph.invoke() -> pod node -> asyncio.run(coro)), which raises
`RuntimeError: asyncio.run() cannot be called from a running event loop`
and gets silently swallowed by the node's except-clause, degrading every
real recon job.
"""
from __future__ import annotations

import asyncio

import pytest

from agent.recon.async_bridge import run_coro_blocking


async def _return_value(value):
    await asyncio.sleep(0)
    return value


def test_run_coro_blocking_from_no_running_loop():
    """Plain sync call site, no event loop running on this thread - must
    behave like a simple `asyncio.run` and return the coroutine's result."""
    result = run_coro_blocking(_return_value("ok"))
    assert result == "ok"


def test_run_coro_blocking_from_within_running_loop():
    """The exact sync-within-async shape that bites production: a sync
    function is called from within a coroutine that is itself being driven
    by a running event loop (`asyncio.run(outer())`), and that sync function
    needs to run another coroutine to completion. Must NOT raise
    `RuntimeError: asyncio.run() cannot be called from a running event
    loop` - must return the inner coroutine's result instead."""

    def sync_node():
        return run_coro_blocking(_return_value("nested-ok"))

    async def outer():
        return sync_node()

    result = asyncio.run(outer())
    assert result == "nested-ok"


def test_run_coro_blocking_propagates_exceptions_from_no_running_loop():
    async def _boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_coro_blocking(_boom())


def test_run_coro_blocking_propagates_exceptions_from_within_running_loop():
    async def _boom():
        raise ValueError("boom-nested")

    def sync_node():
        return run_coro_blocking(_boom())

    async def outer():
        return sync_node()

    with pytest.raises(ValueError, match="boom-nested"):
        asyncio.run(outer())


def test_default_exec_fn_works_when_called_from_within_running_loop(monkeypatch):
    """Mirrors the exact production nesting that triggered the bug:
    `routes.py POST /recon` -> `asyncio.create_task` -> `run_pipeline` ->
    `asyncio.gather` -> `run_job` (awaited) -> sync `graph.invoke()` -> pod
    node -> `default_exec_fn`. Before the fix, `default_exec_fn`'s internal
    `asyncio.run(_run())` raised `RuntimeError: asyncio.run() cannot be
    called from a running event loop` here, which the pod's `execute` node
    does not catch itself, but production code paths further up did swallow
    it, silently degrading the job. Here we assert the call surfaces a
    normal `ExecResult` instead of raising."""
    import agent.recon.pod as pod_module

    class _FakeToolMessage:
        def __init__(self, artifact):
            self.artifact = artifact
            self.content = "unused"

    class _FakeTool:
        name = "execute_command"

        async def ainvoke(self, tool_call):
            await asyncio.sleep(0)
            return _FakeToolMessage(
                {
                    "stdout": "fake output\n",
                    "stderr": "",
                    "returncode": 0,
                    "duration_ms": 5,
                }
            )

    class _FakeMCPClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_tools(self):
            await asyncio.sleep(0)
            return [_FakeTool()]

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _FakeMCPClient
    )

    def sync_node():
        return pod_module.default_exec_fn("echo hi", "session-1", 30)

    async def outer():
        return sync_node()

    result = asyncio.run(outer())

    from agent.recon.types import ExecResult

    assert isinstance(result, ExecResult)
    assert result.returncode == 0
    assert result.stdout == "fake output\n"
