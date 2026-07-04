import asyncio

import pytest

from agent.app.llm import providers as P
from agent.recon import config
from agent.recon.crawl import steel_client as SC


class _FakeTool:
    def __init__(self, name):
        self.name = name


class _FakeClient:
    def __init__(self, tools):
        self._tools = tools

    async def get_tools(self):
        return self._tools


def test_steel_configured_false_when_env_unset(monkeypatch):
    monkeypatch.setattr(config, "STEEL_MCP_URL", "")
    monkeypatch.setattr(config, "STEEL_API_KEY", "")
    assert SC.steel_configured() is False


def test_steel_configured_false_when_only_url_set(monkeypatch):
    monkeypatch.setattr(config, "STEEL_MCP_URL", "http://steel:1234")
    monkeypatch.setattr(config, "STEEL_API_KEY", "")
    assert SC.steel_configured() is False


def test_steel_configured_true_when_both_set(monkeypatch):
    monkeypatch.setattr(config, "STEEL_MCP_URL", "http://steel:1234")
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    assert SC.steel_configured() is True


def test_get_crawl_tools_filters_to_crawl_tool_names(monkeypatch):
    monkeypatch.setattr(config, "STEEL_MCP_URL", "http://steel:1234")
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    tools = [
        _FakeTool("steel_crawl_start"),
        _FakeTool("steel_navigate"),
        _FakeTool("some_other_tool"),
    ]
    fake_client = _FakeClient(tools)

    def factory():
        return fake_client

    result = asyncio.run(SC.get_crawl_tools(client_factory=factory))
    names = {t.name for t in result}
    assert names == {"steel_crawl_start", "steel_navigate"}


def test_get_crawl_tools_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "STEEL_MCP_URL", "")
    monkeypatch.setattr(config, "STEEL_API_KEY", "")
    with pytest.raises(SC.SteelNotConfigured):
        asyncio.run(SC.get_crawl_tools())


def test_crawler_role_present():
    assert "crawler" in P.ROLES
