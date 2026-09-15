"""Handler attribution for worker-thread observations (#226).

LangGraph merges the run config metadata (including `langfuse_session_id` /
`langfuse_tags`) into every child run, on every thread. The stock Langfuse
`CallbackHandler` only reads those keys at the root run and otherwise relies
on OTel context (contextvars), which does not cross the worker threads used
for parallel Send fan-out - so worker-thread children lose session/tags.

These tests pin the client-side enrichment contract. No network, no live
Langfuse; the SDK is only imported lazily inside the factory under test.
"""
from polymerhus.app.observability import langfuse_tracing as lt


def test_metadata_maps_langfuse_keys_to_propagate_kwargs():
    attrs = lt.trace_attributes_from_metadata(
        {
            "langfuse_session_id": "sess-1",
            "langfuse_tags": ["recon", "pod"],
            "langfuse_user_id": "user-1",
            "langfuse_trace_name": "trace-1",
            "run_id": "run-1",
        }
    )
    assert attrs == {
        "session_id": "sess-1",
        "tags": ["recon", "pod"],
        "user_id": "user-1",
        "trace_name": "trace-1",
    }


def test_metadata_without_langfuse_keys_yields_no_attributes():
    assert lt.trace_attributes_from_metadata(None) == {}
    assert lt.trace_attributes_from_metadata({}) == {}
    assert lt.trace_attributes_from_metadata({"run_id": "run-1"}) == {}


def test_metadata_ignores_invalid_langfuse_value_shapes():
    attrs = lt.trace_attributes_from_metadata(
        {
            "langfuse_session_id": 123,
            "langfuse_tags": "recon",
            "langfuse_user_id": "",
            "langfuse_trace_name": None,
        }
    )
    assert attrs == {}


class _RecordingPropagate:
    """Stand-in for the SDK `propagate_attributes`: records kwargs and marks
    whether the wrapped start ran inside its context."""

    def __init__(self):
        self.calls = []
        self.active = False

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        recorder = self

        class _Ctx:
            def __enter__(self):
                recorder.active = True
                return None

            def __exit__(self, *exc):
                recorder.active = False
                return False

        return _Ctx()


class _FakeBase:
    """Stand-in base handler: records each start and whether the propagate
    context was active while the span would have been created."""

    def __init__(self, propagate):
        self._propagate = propagate
        self.starts = []

    def _record(self, kind, run_id, parent_run_id):
        self.starts.append(
            {
                "kind": kind,
                "active": self._propagate.active,
                "root": parent_run_id is None,
            }
        )
        return kind

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None,
                       tags=None, metadata=None, **kwargs):
        return self._record("chain", run_id, parent_run_id)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None,
                      tags=None, metadata=None, **kwargs):
        return self._record("tool", run_id, parent_run_id)

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None,
                     tags=None, metadata=None, **kwargs):
        return self._record("llm", run_id, parent_run_id)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None,
                            tags=None, metadata=None, **kwargs):
        return self._record("chat_model", run_id, parent_run_id)

    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None,
                           tags=None, metadata=None, **kwargs):
        return self._record("retriever", run_id, parent_run_id)


def _drive_non_root(handler, metadata):
    import uuid

    run_id = uuid.uuid4()
    parent = uuid.uuid4()
    handler.on_chain_start({"name": "child"}, {"in": 1}, run_id=run_id,
                           parent_run_id=parent, metadata=metadata)
    handler.on_tool_start({"name": "tool"}, "in", run_id=uuid.uuid4(),
                          parent_run_id=parent, metadata=metadata)
    handler.on_llm_start({"name": "llm"}, ["p"], run_id=uuid.uuid4(),
                         parent_run_id=parent, metadata=metadata)
    handler.on_chat_model_start({"name": "chat"}, [[{"role": "user"}]],
                                run_id=uuid.uuid4(), parent_run_id=parent,
                                metadata=metadata)
    handler.on_retriever_start({"name": "ret"}, "q", run_id=uuid.uuid4(),
                               parent_run_id=parent, metadata=metadata)


def test_non_root_starts_reestablish_attributes_inside_span_creation():
    import uuid

    propagate = _RecordingPropagate()
    cls = lt.attributing_handler_class(_FakeBase, propagate)
    handler = cls(propagate)
    metadata = {"langfuse_session_id": "sess-1", "langfuse_tags": ["recon"]}

    _drive_non_root(handler, metadata)

    assert len(propagate.calls) == 5
    assert all(c == {"session_id": "sess-1", "tags": ["recon"]}
               for c in propagate.calls)
    assert len(handler.starts) == 5
    assert all(s["active"] is True and s["root"] is False
               for s in handler.starts)
    assert propagate.active is False


def test_root_start_never_reenters_propagation():
    import uuid

    propagate = _RecordingPropagate()
    cls = lt.attributing_handler_class(_FakeBase, propagate)
    handler = cls(propagate)
    run_id = uuid.uuid4()
    handler.on_chain_start({"name": "root"}, {"in": 1}, run_id=run_id,
                           parent_run_id=None,
                           metadata={"langfuse_session_id": "sess-1"})

    assert propagate.calls == []
    assert handler.starts == [{"kind": "chain", "active": False, "root": True}]


def test_non_root_without_langfuse_metadata_leaves_context_alone():
    import uuid

    propagate = _RecordingPropagate()
    cls = lt.attributing_handler_class(_FakeBase, propagate)
    handler = cls(propagate)
    handler.on_tool_start({"name": "tool"}, "in", run_id=uuid.uuid4(),
                          parent_run_id=uuid.uuid4(),
                          metadata={"run_id": "run-1"})

    assert propagate.calls == []
    assert handler.starts[0]["active"] is False


def test_build_attributing_handler_returns_enriching_subclass(monkeypatch):
    import sys
    import types

    seen = {}

    class _FakeSDKBase:
        def __init__(self, public_key=None, **kwargs):
            seen["public_key"] = public_key

    def _fake_propagate(**kwargs):
        import contextlib
        seen.setdefault("propagate_calls", []).append(kwargs)
        return contextlib.nullcontext()

    fake_langfuse = types.ModuleType("langfuse")
    fake_langfuse.propagate_attributes = _fake_propagate
    fake_langchain_mod = types.ModuleType("langfuse.langchain")
    fake_langchain_mod.CallbackHandler = _FakeSDKBase
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain_mod)

    handler = lt.build_attributing_handler("pk-test-only")

    assert isinstance(handler, _FakeSDKBase)
    assert seen["public_key"] == "pk-test-only"
    assert hasattr(handler, "_attribution_scope")


def test_resolve_base_url_strips_quotes_and_whitespace(monkeypatch):
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.setenv("LANGFUSE_HOST", '  "https://example.invalid"  ')
    assert lt._resolve_base_url() == "https://example.invalid"


def test_resolve_base_url_prefers_base_url_and_strips_it(monkeypatch):
    monkeypatch.setenv("LANGFUSE_BASE_URL", "'https://otel.example.invalid/'")
    monkeypatch.setenv("LANGFUSE_HOST", "https://example.invalid")
    assert lt._resolve_base_url() == "https://otel.example.invalid/"


def test_build_wrapped_span_exporter_strips_quoted_host(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-only")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-only")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.setenv("LANGFUSE_HOST", '"https://example.invalid"')
    exporter = lt._build_wrapped_span_exporter(timeout_s=30.0)
    assert exporter._exporter._endpoint == (
        "https://example.invalid/api/public/otel/v1/traces"
    )
