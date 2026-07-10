import logging


def test_log_tracing_status_warns_when_disabled(monkeypatch, caplog):
    from agent.app import main
    monkeypatch.setattr(main, "get_langfuse_callbacks", lambda: [])
    with caplog.at_level(logging.WARNING):
        main.log_tracing_status()
    assert any("Langfuse tracing disabled" in r.message for r in caplog.records)


def test_log_tracing_status_info_when_enabled(monkeypatch, caplog):
    from agent.app import main
    monkeypatch.setattr(main, "get_langfuse_callbacks", lambda: [object()])
    with caplog.at_level(logging.INFO):
        main.log_tracing_status()
    assert any("Langfuse tracing enabled" in r.message for r in caplog.records)
