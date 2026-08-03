import importlib


def test_lightrag_config_defaults(monkeypatch):
    import agent.app.config as config_module

    with monkeypatch.context() as m:
        m.delenv("LIGHTRAG_APPROVED_SOURCES", raising=False)
        m.delenv("LIGHTRAG_WORK_DIR", raising=False)
        m.delenv("LIGHTRAG_MAX_CANDIDATES", raising=False)
        m.delenv("LIGHTRAG_API_URL", raising=False)
        m.delenv("LIGHTRAG_BASE_API_URL", raising=False)
        m.delenv("LIGHTRAG_WRITEUP_API_URL", raising=False)
        module = importlib.reload(config_module)

        assert module.config.LIGHTRAG_APPROVED_SOURCES == (
            "data/lightrag/inputs",
            "docs/design/lightrag",
        )
        assert module.config.LIGHTRAG_WORK_DIR == "/tmp/polyphemus-lightrag"
        assert module.config.LIGHTRAG_MAX_CANDIDATES == 5
        assert module.config.LIGHTRAG_API_URL == "http://lightrag:9621"
        assert module.config.LIGHTRAG_BASE_API_URL == "http://lightrag:9621"
        assert module.config.LIGHTRAG_WRITEUP_API_URL == "http://lightrag-writeups:9621"
        assert module.config.LIGHTRAG_API_KEY == ""
        assert module.config.LIGHTRAG_TIMEOUT_SECONDS == 30.0

    importlib.reload(config_module)


def test_lightrag_config_env_overrides(monkeypatch):
    import agent.app.config as config_module

    with monkeypatch.context() as m:
        m.setenv("LIGHTRAG_APPROVED_SOURCES", "docs/a, /opt/methodology ,,docs/b")
        m.setenv("LIGHTRAG_WORK_DIR", "/tmp/custom-lightrag")
        m.setenv("LIGHTRAG_MAX_CANDIDATES", "9")
        m.setenv("LIGHTRAG_API_URL", "http://localhost:9621")
        m.setenv("LIGHTRAG_BASE_API_URL", "http://base.local:9621")
        m.setenv("LIGHTRAG_WRITEUP_API_URL", "http://writeups.local:9621")
        m.setenv("LIGHTRAG_API_KEY", "secret")
        m.setenv("LIGHTRAG_TIMEOUT_SECONDS", "12.5")
        module = importlib.reload(config_module)

        assert module.config.LIGHTRAG_APPROVED_SOURCES == ("docs/a", "/opt/methodology", "docs/b")
        assert module.config.LIGHTRAG_WORK_DIR == "/tmp/custom-lightrag"
        assert module.config.LIGHTRAG_MAX_CANDIDATES == 9
        assert module.config.LIGHTRAG_API_URL == "http://localhost:9621"
        assert module.config.LIGHTRAG_BASE_API_URL == "http://base.local:9621"
        assert module.config.LIGHTRAG_WRITEUP_API_URL == "http://writeups.local:9621"
        assert module.config.LIGHTRAG_API_KEY == "secret"
        assert module.config.LIGHTRAG_TIMEOUT_SECONDS == 12.5

    importlib.reload(config_module)
