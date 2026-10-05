import logging


def test_log_tracing_status_warns_when_disabled(monkeypatch, caplog):
    from polymerhus.app import main
    monkeypatch.setattr(main, "get_langfuse_callbacks", lambda: [])
    with caplog.at_level(logging.WARNING):
        main.log_tracing_status()
    assert any("Langfuse tracing disabled" in r.message for r in caplog.records)


def test_log_tracing_status_info_when_enabled(monkeypatch, caplog):
    from polymerhus.app import main
    monkeypatch.setattr(main, "get_langfuse_callbacks", lambda: [object()])
    with caplog.at_level(logging.INFO):
        main.log_tracing_status()
    assert any("Langfuse tracing enabled" in r.message for r in caplog.records)


def test_disabled_reason_names_only_the_missing_env_var(monkeypatch):
    # Reproduces the operator incident: PUBLIC_KEY + SECRET_KEY set, no base URL.
    # The reason must name the missing base-URL vars specifically, not blame the keys.
    from polymerhus.app.observability import langfuse_tracing as lt
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    lt.reset_cache()
    try:
        reason = lt.disabled_reason()
        assert reason is not None
        assert "LANGFUSE_HOST" in reason
        assert "LANGFUSE_PUBLIC_KEY" not in reason  # only the missing one is named
    finally:
        lt.reset_cache()  # do not leak the cached reason into other tests


def test_base_url_alone_satisfies_the_gate(monkeypatch):
    # #327: PUBLIC + SECRET + BASE_URL (no HOST) must enable tracing and resolve
    # the BASE_URL, because the resolver already accepts it as a HOST alias.
    from polymerhus.app.observability import langfuse_tracing as lt
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://otel.example.invalid")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    assert lt._is_configured() is True
    assert lt._resolve_base_url() == "https://otel.example.invalid"


def test_whitespace_only_key_fails_the_gate(monkeypatch):
    # A whitespace-only key cleans to empty at construction; the gate must use
    # the same `_clean_env` reading so it cannot pass and then fail to build.
    from polymerhus.app.observability import langfuse_tracing as lt
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "   ")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://otel.example.invalid")

    assert lt._is_configured() is False
    assert "LANGFUSE_PUBLIC_KEY" in lt._missing_env()


def test_base_url_alone_enables_tracing_end_to_end(monkeypatch):
    # Drives the real factory with a faked SDK so no network I/O happens; proves
    # a BASE_URL-only environment yields a handler bound to the resolved base URL.
    import contextlib
    import sys
    import types

    from polymerhus.app.observability import langfuse_tracing as lt

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-only")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-only")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://otel.example.invalid")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_EXPORT_TIMEOUT", "1")

    seen: dict = {}

    class _FakeLangfuse:
        def __init__(self, **kwargs):
            seen["client_kwargs"] = kwargs
            self._resources = types.SimpleNamespace(
                span_exporter=kwargs.get("span_exporter"))

        def auth_check(self):
            return True

    class _FakeCallbackHandler:
        def __init__(self, *args, **kwargs):
            seen["handler_public_key"] = kwargs.get("public_key")

    class _FakeOtlpSpanExporter:
        def __init__(self, endpoint=None, headers=None, timeout=None):
            seen["exporter_kwargs"] = {
                "endpoint": endpoint, "headers": headers, "timeout": timeout,
            }

        def export(self, spans):  # pragma: no cover - never called here
            raise AssertionError("no export in this test")

        def shutdown(self):  # pragma: no cover
            pass

        def force_flush(self, timeout_millis=30000):  # pragma: no cover
            return True

    fake = types.ModuleType("langfuse")
    fake.Langfuse = _FakeLangfuse
    fake.get_client = lambda: _FakeLangfuse()
    fake.propagate_attributes = lambda **kwargs: contextlib.nullcontext()
    fake_version = types.ModuleType("langfuse._version")
    fake_version.__version__ = "4.test"
    fake_langchain = types.ModuleType("langfuse.langchain")
    fake_langchain.CallbackHandler = _FakeCallbackHandler
    fake_otel = types.ModuleType(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter")
    fake_otel.OTLPSpanExporter = _FakeOtlpSpanExporter
    monkeypatch.setitem(sys.modules, "langfuse", fake)
    monkeypatch.setitem(sys.modules, "langfuse._version", fake_version)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain)
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        fake_otel,
    )

    lt.reset_cache()
    try:
        callbacks = lt.get_langfuse_callbacks()
        assert lt.disabled_reason() is None
    finally:
        lt.reset_cache()

    assert len(callbacks) == 1
    assert seen["client_kwargs"]["base_url"] == "https://otel.example.invalid"
    assert seen["handler_public_key"] == "pk-test-only"
    # The custom exporter must carry the SDK-identifying headers the default
    # SDK exporter sets, or Langfuse flags the project's SDK config as stale.
    exporter_headers = seen["exporter_kwargs"]["headers"]
    assert exporter_headers["x-langfuse-sdk-version"] == "4.test"
    assert exporter_headers["x-langfuse-ingestion-version"] == "4"


def test_neither_base_url_var_names_the_alias_accurately(monkeypatch):
    from polymerhus.app.observability import langfuse_tracing as lt
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    lt.reset_cache()
    try:
        reason = lt.disabled_reason()
        assert reason is not None
        assert "LANGFUSE_BASE_URL" in reason
        assert "LANGFUSE_HOST" in reason
    finally:
        lt.reset_cache()
