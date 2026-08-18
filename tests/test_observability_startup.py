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
    # Reproduces the operator incident: PUBLIC_KEY + SECRET_KEY set, HOST missing.
    # The reason must name LANGFUSE_HOST specifically, not blame all three.
    from polymerhus.app.observability import langfuse_tracing as lt
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    lt.reset_cache()
    try:
        reason = lt.disabled_reason()
        assert reason is not None
        assert "LANGFUSE_HOST" in reason
        assert "LANGFUSE_PUBLIC_KEY" not in reason  # only the missing one is named
    finally:
        lt.reset_cache()  # do not leak the cached reason into other tests
