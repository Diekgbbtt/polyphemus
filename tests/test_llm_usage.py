"""Unit tier: the app-side token-usage tracking (`app/llm/usage.py`).

The usage ledger is the process-wide, per-project, per-agent token accumulator
the session seam records into on every model call. These tests exercise the
observable contract only: what `record` accumulates, what `snapshot` returns
(the unscoped bucket is never exposed), and that the langchain middleware
actually records a real `create_agent` run.
"""
from __future__ import annotations

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from polymerhus.app.llm.usage import UsageLedger, usage_ledger, usage_middleware

_USAGE = {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}


class _UsageFakeChatModel(BaseChatModel):
    """A scripted chat model whose reply carries fixed `usage_metadata`, so a
    real `create_agent` run observable to the middleware records tokens."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = AIMessage(content="hello", usage_metadata=dict(_USAGE))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="hello", usage_metadata=dict(_USAGE)))

    @property
    def _llm_type(self) -> str:
        return "usage-fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _usage_agent():
    return create_agent(_UsageFakeChatModel(), tools=[],
                        middleware=[usage_middleware()])


@pytest.fixture(autouse=True)
def _clean_ledger():
    usage_ledger().reset()
    yield
    usage_ledger().reset()


def test_record_accumulates_across_calls_for_one_agent():
    ledger = UsageLedger()
    ledger.record("proj-1", "assigner", {"input_tokens": 10, "output_tokens": 5,
                                         "total_tokens": 15})
    ledger.record("proj-1", "assigner", {"input_tokens": 3, "output_tokens": 2,
                                         "total_tokens": 5})
    snap = ledger.snapshot("proj-1")
    assert snap["project_id"] == "proj-1"
    assert snap["total_tokens"] == 20
    assert snap["calls"] == 2
    assert snap["by_agent"] == {
        "assigner": {"input_tokens": 13, "output_tokens": 7,
                     "total_tokens": 20, "calls": 2},
    }


def test_two_agents_in_one_project_are_broken_out():
    ledger = UsageLedger()
    ledger.record("proj-1", "assigner", {"input_tokens": 10, "output_tokens": 0,
                                         "total_tokens": 10})
    ledger.record("proj-1", "triager", {"input_tokens": 1, "output_tokens": 4,
                                        "total_tokens": 5})
    snap = ledger.snapshot("proj-1")
    assert snap["total_tokens"] == 15
    assert snap["calls"] == 2
    assert snap["by_agent"]["assigner"]["total_tokens"] == 10
    assert snap["by_agent"]["triager"]["output_tokens"] == 4


def test_unscoped_bucket_is_excluded_from_a_project_snapshot():
    ledger = UsageLedger()
    ledger.record(None, "assigner", {"input_tokens": 7, "output_tokens": 1,
                                     "total_tokens": 8})
    ledger.record("", "cli", {"input_tokens": 2, "output_tokens": 2,
                              "total_tokens": 4})
    ledger.record("proj-1", "assigner", {"input_tokens": 1, "output_tokens": 1,
                                         "total_tokens": 2})
    snap = ledger.snapshot("proj-1")
    assert snap["total_tokens"] == 2
    assert snap["calls"] == 1
    assert set(snap["by_agent"]) == {"assigner"}


def test_unknown_project_returns_zeros_and_empty_breakdown():
    ledger = UsageLedger()
    snap = ledger.snapshot("never-seen")
    assert snap == {"project_id": "never-seen", "total_tokens": 0, "calls": 0,
                    "by_agent": {}}


def test_none_or_empty_usage_is_a_no_op():
    ledger = UsageLedger()
    ledger.record("proj-1", "assigner", None)
    ledger.record("proj-1", "assigner", {})
    snap = ledger.snapshot("proj-1")
    assert snap["total_tokens"] == 0
    assert snap["calls"] == 0
    assert snap["by_agent"] == {}


def test_reset_clears_all_state():
    ledger = UsageLedger()
    ledger.record("proj-1", "assigner", {"input_tokens": 4, "output_tokens": 4,
                                         "total_tokens": 8})
    ledger.reset()
    assert ledger.snapshot("proj-1") == {
        "project_id": "proj-1", "total_tokens": 0, "calls": 0, "by_agent": {}}


# --- TokenUsageMiddleware: records a real create_agent run's usage -----------

def _config(scope: str | None = "proj-1", role: str | None = "assigner"):
    metadata: dict = {}
    if scope is not None:
        metadata["usage_scope"] = scope
    if role is not None:
        metadata["role_id"] = role
    return {"configurable": {"thread_id": "t1"}, "metadata": metadata}


def test_middleware_records_usage_for_an_invoked_agent_run():
    agent = _usage_agent()
    agent.invoke({"messages": [HumanMessage(content="hi")]}, _config())
    snap = usage_ledger().snapshot("proj-1")
    assert snap["calls"] == 1
    assert snap["total_tokens"] == 18
    assert snap["by_agent"] == {
        "assigner": {"input_tokens": 11, "output_tokens": 7,
                     "total_tokens": 18, "calls": 1},
    }


def test_middleware_records_usage_for_a_streamed_agent_run():
    agent = _usage_agent()
    for _mode, _payload in agent.stream(
            {"messages": [HumanMessage(content="hi")]}, _config(),
            stream_mode=["messages", "values"]):
        pass
    snap = usage_ledger().snapshot("proj-1")
    assert snap["calls"] == 1
    assert snap["by_agent"]["assigner"]["total_tokens"] == 18


def test_middleware_without_config_metadata_does_not_raise():
    agent = _usage_agent()
    # No metadata at all: the record lands in the unscoped bucket, never raises.
    agent.invoke({"messages": [HumanMessage(content="hi")]})
    assert usage_ledger().snapshot("proj-1")["total_tokens"] == 0


def test_middleware_missing_role_id_records_unknown():
    agent = _usage_agent()
    agent.invoke({"messages": [HumanMessage(content="hi")]}, _config(role=None))
    assert "unknown" in usage_ledger().snapshot("proj-1")["by_agent"]


def test_usage_middleware_factory_returns_a_fresh_instance():
    assert usage_middleware() is not usage_middleware()


def test_middleware_only_records_on_success_and_propagates_the_error():
    middleware = usage_middleware()

    def handler(_request):
        raise RuntimeError("model call failed")

    with pytest.raises(RuntimeError, match="model call failed"):
        middleware.wrap_model_call(object(), handler)
    assert usage_ledger().snapshot("proj-1")["total_tokens"] == 0


# --- W3: the session seam attaches the middleware, decoupled from observe -----

def test_session_turn_records_usage_even_when_observe_is_false():
    from langgraph.checkpoint.memory import InMemorySaver

    from polymerhus.app.llm.session import run_session_turn

    run_session_turn(
        "assigner", "thread-1", [HumanMessage(content="hi")],
        checkpointer=InMemorySaver(),
        model_factory=lambda role_id: _UsageFakeChatModel(),
        observe=False, usage_scope="proj-1",
    )
    snap = usage_ledger().snapshot("proj-1")
    assert snap["total_tokens"] == 18
    assert snap["by_agent"] == {
        "assigner": {"input_tokens": 11, "output_tokens": 7,
                     "total_tokens": 18, "calls": 1},
    }


def test_stateful_turn_threads_usage_scope_to_the_session_turn(monkeypatch):
    import polymerhus.app.llm.session as S

    seen = {}

    def fake_run(role_id, thread_id, msgs, *, usage_scope=None, **kw):
        seen["usage_scope"] = usage_scope
        return S.SessionTurn(content="ok", messages=[], thread_id=thread_id)

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    S.stateful_turn("assigner", "t", [HumanMessage(content="x")],
                    checkpointer=None, observe=False, usage_scope="proj-1")
    assert seen["usage_scope"] == "proj-1"
