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
from opentelemetry.sdk.trace.export import SpanExportResult

from polymerhus.app.observability import langfuse_tracing as lt
from polymerhus.app.observability.langfuse_tracing import RetryingSpanExporter


class _FakeClient:
    def __init__(self):
        self.flush_calls = 0

    def flush(self):
        self.flush_calls += 1


def _handler(client):
    return SimpleNamespace(_langfuse_client=client)


class _FakeResources:
    def __init__(self, exporter):
        self.span_exporter = exporter


class _OutcomeClient(_FakeClient):
    """A fake client whose resource manager exposes the in-effect exporter,
    exactly the seam `_active_span_exporter` reads, plus a hook that simulates
    the batch processor exporting queued spans during `flush()`."""

    def __init__(self, exporter, *, on_flush=None):
        super().__init__()
        self._resources = _FakeResources(exporter)
        self._on_flush = on_flush

    def flush(self):
        self.flush_calls += 1
        if self._on_flush is not None:
            self._on_flush()


class _OutcomeExporter:
    """Minimal inner exporter for the real `RetryingSpanExporter` wrapper."""

    def __init__(self, result):
        self._result = result
        self.calls = 0

    def export(self, spans):
        self.calls += 1
        return self._result


def _wrapped_exporter(result):
    return RetryingSpanExporter(
        _OutcomeExporter(result), max_retries=0, backoff_base_s=0.0,
        sleep=lambda _s: None,
    )


def test_success_arm_reports_delivered_when_the_exporter_records_no_drop():
    # The client's exporter is the real wrapper; the batch exports cleanly.
    exporter = _wrapped_exporter(SpanExportResult.SUCCESS)
    client = _OutcomeClient(
        exporter, on_flush=lambda: exporter.export(["span-1"]))

    result = lt.flush_observation_delivery([_handler(client)])

    assert result.delivered == 1
    assert result.dropped == 0
    assert result.cause == "ok"


def test_failure_arm_reports_dropped_when_the_exporter_drops_the_batch():
    # The exporter's retry budget is exhausted -> the batch is gone for good.
    # A queue-drain-only result would (wrongly) call this `delivered`; #235
    # sources the result from the exporter outcome instead.
    exporter = _wrapped_exporter(SpanExportResult.FAILURE)
    client = _OutcomeClient(
        exporter, on_flush=lambda: exporter.export(["a", "b", "c"]))

    result = lt.flush_observation_delivery([_handler(client)])

    assert result.dropped == 1
    assert result.delivered == 0
    assert result.cause == "exporter-failed"


def test_multi_batch_flush_window_reports_a_drop_among_clean_batches():
    # One flush drains several queued batches; the drop of ANY of them must
    # surface. The wrapper applies its retry budget per batch.
    class _SequenceExporter:
        def __init__(self, results):
            self._results = list(results)

        def export(self, spans):
            return self._results.pop(0)

    exporter = RetryingSpanExporter(
        _SequenceExporter([SpanExportResult.SUCCESS, SpanExportResult.FAILURE]),
        max_retries=0, backoff_base_s=0.0, sleep=lambda _s: None,
    )

    def _drain_two_batches():
        exporter.export(["ok-batch"])
        exporter.export(["dropped-batch"])

    client = _OutcomeClient(exporter, on_flush=_drain_two_batches)

    result = lt.flush_observation_delivery([_handler(client)])

    assert result.dropped == 1
    assert result.delivered == 0
    assert result.cause == "exporter-failed"


def test_exporter_drop_counter_is_reset_after_the_delivery_read():
    # The counter is read-and-reset: once a drop is reported it is not
    # re-reported by a later clean flush.
    exporter = _wrapped_exporter(SpanExportResult.FAILURE)
    client = _OutcomeClient(
        exporter, on_flush=lambda: exporter.export(["span-1"]))

    first = lt.flush_observation_delivery([_handler(client)])
    client._on_flush = lambda: None
    second = lt.flush_observation_delivery([_handler(client)])

    assert (first.dropped, first.cause) == (1, "exporter-failed")
    assert (second.delivered, second.dropped, second.cause) == (1, 0, "ok")


def test_raising_exporter_outcome_read_degrades_to_delivered_never_raises():
    class _RaisingRead:
        def take_dropped_spans(self):
            raise RuntimeError("counter unavailable")

    exporter = _wrapped_exporter(SpanExportResult.SUCCESS)
    client = _OutcomeClient(exporter, on_flush=lambda: None)
    client._resources = _FakeResources(_RaisingRead())

    result = lt.flush_observation_delivery([_handler(client)])

    assert result.delivered == 1
    assert result.dropped == 0
    assert result.cause == "ok"


class _RaisingClient:
    def flush(self):
        raise RuntimeError("backend down")


def test_raising_client_is_a_loud_dropped_result_never_a_raise():
    result = lt.flush_observation_delivery([_handler(_RaisingClient())])
    assert result.dropped == 1
    assert result.delivered == 0
    assert result.cause == "flush-raised"


class _RaisingOutcomeExporter:
    def export(self, spans):
        raise RuntimeError("export blew up")


def test_fail_open_when_both_the_flush_and_the_exporter_raise():
    # The wrapper must not raise out of export(), and even if the exporter
    # read is broken, the delivery result degrades instead of raising.
    inner = _RaisingOutcomeExporter()
    exporter = RetryingSpanExporter(
        inner, max_retries=1, backoff_base_s=0.0, sleep=lambda _s: None)

    class _BothBadClient(_OutcomeClient):
        def flush(self):
            exporter.export(["span-1"])  # wrapper swallows the inner raise
            raise RuntimeError("and the flush raises too")

    client = _BothBadClient(exporter)

    result = lt.flush_observation_delivery([_handler(client)])

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
