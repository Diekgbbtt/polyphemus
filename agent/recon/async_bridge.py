"""Bridge for running an async coroutine to completion from a SYNC context,
whether or not an event loop is already running on this thread.

Recon-pod nodes (`agent.recon.pod.default_exec_fn`,
`agent.recon.crawl.crawl_pod.default_run_crawl_fn`) are plain sync functions
so that `langgraph`'s compiled pod graph can be invoked synchronously
(`graph.invoke(...)`) from `job_agent`. But those nodes need to call async
collaborators (the kali MCP client, the Steel crawl agent).

In production, the call path is async all the way down: `routes.py POST
/recon` -> `asyncio.create_task` -> `pipeline.run_pipeline` -> `asyncio.
gather` -> `run_job` (awaited) -> sync `graph.invoke()` -> pod node. By the
time a pod node runs, there is already a running event loop on this thread,
so a naive `asyncio.run(coro)` inside the node raises `RuntimeError:
asyncio.run() cannot be called from a running event loop` - which then gets
swallowed by the node's `except Exception` and silently degrades the job.

`run_coro_blocking` handles both cases: no running loop -> `asyncio.run`
directly; a running loop -> run the coroutine to completion on a separate
thread with its own fresh loop, so we never call `asyncio.run()`
re-entrantly on the calling thread.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_coro_blocking(coro: "Coroutine[Any, Any, T]") -> T:
    """Run `coro` to completion from a sync context and return its result.

    If no event loop is running on this thread, this is equivalent to
    `asyncio.run(coro)`. If a loop IS running (we're a sync node inside an
    async pipeline), the coroutine is run to completion on a separate
    thread with its own loop, so we never call `asyncio.run()`
    re-entrantly on the calling thread.

    `coro` must be a coroutine object that has not yet been awaited/run -
    it is consumed exactly once, on whichever path is taken.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()
