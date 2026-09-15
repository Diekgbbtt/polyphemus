"""Run-tag passthrough on session turns (convergence migration).

Session turns are sessionized by per-instance thread id, so concurrent
instances never collide - but the RUN-level join that the hand-written SDK
agent spans used to provide must survive their deletion.
Callers pass the bare `run_id` as an extra turn tag; it rides the
`langfuse_tags` the handler records, so turn traces stay run-joinable by tag.
Default (no extra tags) leaves the config exactly as today.
"""
import polymerhus.app.llm.session as S


def test_observe_config_appends_extra_tags(monkeypatch):
    monkeypatch.setattr("polymerhus.app.observability.get_langfuse_callbacks",
                        lambda: ["cb"])
    config = S._observe_config({}, "triager", "thread-1",
                               extra_tags=["run-1"])
    assert config["callbacks"] == ["cb"]
    assert config["metadata"]["langfuse_session_id"] == "thread-1"
    assert config["metadata"]["langfuse_tags"] == ["session", "triager", "run-1"]


def test_observe_config_without_extra_tags_is_unchanged(monkeypatch):
    monkeypatch.setattr("polymerhus.app.observability.get_langfuse_callbacks",
                        lambda: [])
    config = S._observe_config({}, "triager", "thread-1")
    assert config["metadata"]["langfuse_tags"] == ["session", "triager"]


def _drive_turn(monkeypatch, turn_fn, **kwargs):
    import asyncio

    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from tests.test_llm_session import _factory

    seen = {}
    real_turn_config = S._turn_config

    def recording_turn_config(role_id, thread_id, observe, extra_tags=None):
        seen["extra_tags"] = extra_tags
        return real_turn_config(role_id, thread_id, observe,
                                extra_tags=extra_tags)

    monkeypatch.setattr(S, "_turn_config", recording_turn_config)
    saver = InMemorySaver()
    factory = _factory(AIMessage(content="hi"))
    out = turn_fn("triager", "run1:triager", [HumanMessage(content="hi")],
                  checkpointer=saver, model_factory=factory, observe=True,
                  **kwargs)
    if asyncio.iscoroutine(out):
        out = asyncio.run(out)
    content = out.content if hasattr(out, "content") else out
    assert content == "hi"
    return seen


def test_run_session_turn_forwards_extra_tags(monkeypatch):
    seen = _drive_turn(monkeypatch, S.run_session_turn, extra_tags=["run-1"])
    assert seen["extra_tags"] == ["run-1"]


def test_arun_session_turn_forwards_extra_tags(monkeypatch):
    import asyncio

    seen = _drive_turn(monkeypatch,
                       lambda *a, **k: asyncio.run(S.arun_session_turn(*a, **k)),
                       extra_tags=["run-1"])
    assert seen["extra_tags"] == ["run-1"]


def test_stateful_turn_forwards_extra_tags(monkeypatch):
    seen = _drive_turn(monkeypatch, S.stateful_turn, extra_tags=["run-1"])
    assert seen["extra_tags"] == ["run-1"]


def test_run_session_agent_forwards_extra_tags(monkeypatch):
    import asyncio

    import polymerhus.app.llm.actor as actor_pkg
    from langchain_core.messages import HumanMessage

    seen = {}

    async def fake_turn(role_id, thread_id, messages, **kwargs):
        seen["extra_tags"] = kwargs.get("extra_tags")
        from polymerhus.app.llm.session import SessionTurn
        return SessionTurn(content="done", messages=[], thread_id=thread_id)

    monkeypatch.setattr(actor_pkg, "arun_session_turn", fake_turn)
    result = asyncio.run(actor_pkg.run_session_agent(
        "triager", "thread-1", [HumanMessage(content="hi")],
        checkpointer=None, extra_tags=["run-1"],
        on_message=lambda m, t: None, idle_timeout=0.05))
    assert result.thread_id == "thread-1"
    assert seen["extra_tags"] == ["run-1"]
