import polymerhus.app.config as config_module
from polymerhus.lightrag.tool import build_lightrag_tool


def test_factory_uses_configured_endpoints(monkeypatch):
    monkeypatch.setattr(config_module.config, "LIGHTRAG_BASE_API_URL", "http://lr:1")
    monkeypatch.setattr(config_module.config, "LIGHTRAG_API_KEY", "k")
    monkeypatch.setattr(config_module.config, "QUERY_LLM_BASE_URL", "http://llm:2/v1")
    monkeypatch.setattr(config_module.config, "QUERY_LLM_API_KEY", "kk")
    monkeypatch.setattr(config_module.config, "QUERY_LLM_MODEL", "m")
    tool = build_lightrag_tool()
    assert tool.name == "query_lightrag"
    assert tool.client.base_url == "http://lr:1"
    assert tool.llm.model == "m"
