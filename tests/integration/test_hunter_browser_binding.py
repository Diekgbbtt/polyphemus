"""H7: one browser binding serves the whole hunt turn loop (#359, W8).

The binding is the live edge for a real hunt. This test substitutes it with a
recording async tool and drives the REAL harness with a scripted model, so the
assertions cover the join the production path needs: the tool is bound next to
the hunter tools, `invoke_tool` awaits its async `ainvoke`, and the binding is
closed exactly once when the hunt ends.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from langchain_core.tools import StructuredTool

from tests.hunting_fixtures import (
    _answer,
    _hunter_payload,
    _tool_call,
    build_hunter_agent,
    build_memory_store,
)


def _browser_tool(calls: list[dict]) -> StructuredTool:
    """A real LangChain tool with an async-only body, like an MCP tool."""

    async def run(command: str) -> dict:
        calls.append({"command": command})
        return {"success": True, "data": "ok"}

    return StructuredTool.from_function(
        coroutine=run,
        name="browser_exec",
        description="run one browser command on the mounted session",
    )


def test_hunt_calls_the_browser_tool_inside_one_binding(tmp_path):
    store = build_memory_store(tmp_path)
    calls: list[dict] = []
    tool = _browser_tool(calls)
    lifecycle = {"opened": 0, "closed": 0}

    @asynccontextmanager
    async def browser_tools():
        lifecycle["opened"] += 1
        try:
            yield [tool]
        finally:
            lifecycle["closed"] += 1

    agent = build_hunter_agent(
        store,
        steps=[
            _tool_call(
                "browser_exec",
                {"command": "navigate https://app.test/login"},
            ),
            _answer("the page is loaded"),
        ],
        browser_tools_fn=browser_tools,
    )

    result = agent(_hunter_payload())

    assert calls == [{"command": "navigate https://app.test/login"}]
    assert lifecycle == {"opened": 1, "closed": 1}
    assert isinstance(result, dict) and "state" in result


def test_a_hunt_still_runs_without_a_browser_binding(tmp_path):
    store = build_memory_store(tmp_path)
    agent = build_hunter_agent(store, steps=[_answer("done")])

    result = agent(_hunter_payload())

    assert isinstance(result, dict) and "state" in result
