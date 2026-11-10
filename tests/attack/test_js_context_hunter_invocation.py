"""A reusable dispatcher binds its reader once per invocation."""

import asyncio
import ast

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.attack.hunting import hunting_agent
from polymerhus.attack.hunting.js_context_admission import js_context_selection_scope
import polymerhus.app.js_context.tool as reader
import polymerhus.app.llm.session as session
from tests.attack.test_js_context_downstream_binding import published_root, _selection


@pytest.fixture(autouse=True)
def inline_sync_seams(monkeypatch):
    # Match the downstream contract test: keep the real reader/executor while
    # avoiding the environment's unrelated cross-thread sync bridge stall.
    async def inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


def test_reused_hunter_uses_each_invocations_selection_and_clears_it(published_root, monkeypatch):
    root, _ = published_root
    first = _selection(root, "project-a", "run-1")
    second = _selection(root, "project-a", "run-2")
    delivered = []
    declarations = []

    async def turn(role, thread, messages, *, tools=(), **kwargs):
        names = {t["function"]["name"] for t in tools}
        if messages and isinstance(messages[0], ToolMessage):
            delivered.append(ast.literal_eval(messages[0].content))
            reply = AIMessage(content="done")
        else:
            declarations.append(names)
            reply = AIMessage(content="") if "js_context" not in names else AIMessage(
                content="", tool_calls=[{"name": "js_context", "args": {"command": "list"},
                                         "id": "js-1", "type": "tool_call"}])
        return session.SessionTurn(content=str(reply.content), messages=[reply], thread_id=thread)

    monkeypatch.setattr(session, "arun_session_turn", turn)
    with js_context_selection_scope(first):
        dispatch = hunting_agent.build_hunting_agent(
            run_id="hunt", project_id="project-a", checkpointer=InMemorySaver(),
            middleware=[], observe=False, overview_fn=lambda _: "",
        )

    for i, selection in enumerate((first, second, None)):
        with js_context_selection_scope(selection):
            asyncio.run(dispatch({"dispatch_id": f"Service:a__threat-{i}", "target_context": {}}))
    assert ["js_context" in names for names in declarations] == [True, True, False]
    assert [r["js_context_binding"]["producing_run_id"] for r in delivered] == ["run-1", "run-2"]
    assert [{p["run_id"] for p in r["publications"]} for r in delivered] == [{"run-1"}, {"run-2"}]


def test_reader_binding_error_is_an_explicit_degraded_hunt(published_root, monkeypatch):
    selection = _selection(published_root[0], "project-a", "run-1")

    def broken(**kwargs):
        raise ValueError("js_reader_binding_failed")

    async def turn(role, thread, messages, **kwargs):
        return session.SessionTurn(content="done", messages=[AIMessage(content="done")], thread_id=thread)

    monkeypatch.setattr(reader, "build_js_context_tool", broken)
    monkeypatch.setattr(session, "arun_session_turn", turn)
    with js_context_selection_scope(selection):
        dispatch = hunting_agent.build_hunting_agent(
            run_id="hunt", project_id="project-a", checkpointer=InMemorySaver(),
            middleware=[], observe=False, overview_fn=lambda _: "",
        )
        result = asyncio.run(dispatch({"dispatch_id": "Service:a__threat-1", "target_context": {}}))
    assert result["state"] == "grounding"
    assert "js_reader_binding_failed" in result["feedback"]
    assert "concluded" not in result["feedback"]
