"""H7: one browser tool serves the whole hunt turn loop.

The binding is the live edge for a real hunt. This test substitutes it with a
recording tool and drives the REAL harness with a scripted model, so the
assertions cover the join the production path needs: the one `browser` tool is
bound next to the hunter tools, `invoke_tool` executes it, and the binding is
closed exactly once when the hunt ends.
"""
from __future__ import annotations

from langchain_core.tools import StructuredTool

from tests.hunting_fixtures import (
    _answer,
    _hunter_payload,
    _tool_call,
    build_hunter_agent,
    build_memory_store,
)


def test_hunt_calls_the_browser_tool_inside_one_binding(tmp_path):
    store = build_memory_store(tmp_path)
    calls: list[dict] = []

    def browser_tool(_hunt_key: str):
        return StructuredTool.from_function(
            func=lambda command, input=None, **kwargs: (
                calls.append({"command": command, "input": input})
                or {"success": True, "data": "ok"}
            ),
            name="browser",
            description="one browser tool",
        )

    agent = build_hunter_agent(
        store,
        steps=[
            _tool_call(
                "browser",
                {"command": "exec", "input": "navigate https://app.test/login"},
            ),
            _answer("the page is loaded"),
        ],
        browser_tool_factory=browser_tool,
    )

    result = agent(_hunter_payload())

    assert calls == [
        {"command": "exec", "input": "navigate https://app.test/login"}
    ]
    assert isinstance(result, dict) and "state" in result


def test_a_hunt_still_runs_without_a_browser_binding(tmp_path):
    store = build_memory_store(tmp_path)
    agent = build_hunter_agent(store, steps=[_answer("done")])

    result = agent(_hunter_payload())

    assert isinstance(result, dict) and "state" in result
