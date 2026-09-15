"""Delivery barrier for Langfuse observations (H1).

Finished observations queue in the SDK background exporter; a process that
dies first loses them (loop-proven: control LOST / barrier LANDED).
`flush_observation_delivery` is the forced, bounded, typed drain:
the turn calls it with exactly the callback list it borrowed, teardown
sweeps the cached handler. Fail-open, never raises.

These tests use FAKE handlers/clients only - no network, no live Langfuse.
"""
from types import SimpleNamespace

from langchain_core.callbacks import BaseCallbackHandler

from polymerhus.app.observability import langfuse_tracing as lt


class _FakeClient:
    def __init__(self):
        self.flush_calls = 0

    def flush(self):
        self.flush_calls += 1


def _handler(client):
    return SimpleNamespace(_langfuse_client=client)


def test_barrier_flushes_each_borrowed_handlers_own_client():
    c1, c2 = _FakeClient(), _FakeClient()
    result = lt.flush_observation_delivery([_handler(c1), _handler(c2)])
    assert (c1.flush_calls, c2.flush_calls) == (1, 1)
    assert result.delivered == 2
    assert result.dropped == 0
    assert result.cause == "ok"


def test_empty_borrow_list_is_an_inert_unconfigured_result():
    result = lt.flush_observation_delivery([])
    assert result.to_dict() == {"delivered": 0, "pending": 0, "dropped": 0,
                                "cause": "unconfigured"}


def test_handler_without_a_flushable_client_is_pending_never_attempted():
    result = lt.flush_observation_delivery([SimpleNamespace()])
    assert result.pending == 1
    assert result.delivered == 0
    assert result.cause == "no-client"


class _RaisingClient:
    def flush(self):
        raise RuntimeError("backend down")


def test_raising_client_is_a_loud_dropped_result_never_a_raise():
    result = lt.flush_observation_delivery([_handler(_RaisingClient())])
    assert result.dropped == 1
    assert result.delivered == 0
    assert result.cause == "flush-raised"


def test_one_bad_handler_does_not_abort_the_remaining_flushes():
    good = _FakeClient()
    result = lt.flush_observation_delivery(
        [_handler(_RaisingClient()), _handler(good)])
    assert good.flush_calls == 1
    assert result.delivered == 1
    assert result.dropped == 1


class _NoopCallbacks(BaseCallbackHandler):
    """Stand-in for a borrowed Langfuse handler: satisfies the callback
    manager without emitting anything."""


class _FakeTurnModel:
    """Scripted turn model: one plain reply, no tools requested."""

    def __init__(self):
        from langchain_core.language_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        class _M(BaseChatModel):
            @property
            def _llm_type(self):
                return "fake"

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return ChatResult(generations=[ChatGeneration(
                    message=AIMessage(content="turn reply"))])

            def bind_tools(self, tools, **kwargs):
                return self

        self.impl = _M()

    def __getattr__(self, name):
        return getattr(self.impl, name)


def _run_turn(monkeypatch, borrowed, turn_fn, **kw):
    import polymerhus.app.llm.session as S
    from langgraph.checkpoint.memory import InMemorySaver

    seen = {}

    def fake_barrier(callbacks):
        seen["callbacks"] = callbacks
        return lt.DeliveryResult(delivered=len(callbacks or []), pending=0,
                                 dropped=0, cause="ok")

    monkeypatch.setattr(lt, "flush_observation_delivery", fake_barrier)
    monkeypatch.setattr("polymerhus.app.observability.get_langfuse_callbacks",
                        lambda: borrowed)
    saver = InMemorySaver()
    factory = lambda role_id: _FakeTurnModel()  # noqa: E731
    from langchain_core.messages import HumanMessage
    out = turn_fn("triager", "run1:triager", [HumanMessage(content="hi")],
                  checkpointer=saver, model_factory=factory, observe=True, **kw)
    assert out.content == "turn reply"
    return seen


def test_sync_turn_flushes_exactly_the_borrowed_callback_list(monkeypatch):
    import polymerhus.app.llm.session as S

    borrowed = [_NoopCallbacks()]
    seen = _run_turn(monkeypatch, borrowed, S.run_session_turn)
    assert seen["callbacks"] == borrowed


def test_async_turn_flushes_exactly_the_borrowed_callback_list(monkeypatch):
    import asyncio

    import polymerhus.app.llm.session as S

    borrowed = [_NoopCallbacks()]
    seen = _run_turn(monkeypatch, borrowed,
                     lambda *a, **k: asyncio.run(S.arun_session_turn(*a, **k)))
    assert seen["callbacks"] == borrowed


def test_shutdown_sweeps_observation_delivery_after_pool_close(monkeypatch):
    import asyncio

    import polymerhus.app.llm as llm_pkg
    from polymerhus.app import main as app_main

    calls = []

    class _Runtime:
        def shutdown(self):
            calls.append("runtime")

    app_main.app.state.runtime = _Runtime()
    try:
        del app_main.app.state.reaper_task
    except (AttributeError, KeyError):
        pass
    monkeypatch.setattr(llm_pkg, "close_session_checkpointer",
                        lambda: calls.append("pool"))

    def fake_sweep(callbacks):
        calls.append(("sweep", callbacks))
        return lt.DeliveryResult(delivered=0, pending=0, dropped=0,
                                 cause="unconfigured")

    monkeypatch.setattr(lt, "flush_observation_delivery", fake_sweep)
    asyncio.run(app_main._shutdown())
    assert calls[0] == "runtime"
    assert calls[1] == "pool"
    assert ("sweep", None) in calls[2:]
