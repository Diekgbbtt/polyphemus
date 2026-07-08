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


def test_steel_configured_false_when_key_unset(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "")
    assert SC.steel_configured() is False


def test_steel_configured_true_when_key_set(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    assert SC.steel_configured() is True


def test_get_crawl_tools_filters_to_crawl_tool_names(monkeypatch):
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
    monkeypatch.setattr(config, "STEEL_API_KEY", "")
    with pytest.raises(SC.SteelNotConfigured):
        asyncio.run(SC.get_crawl_tools())


def test_default_factory_raises_provider_unavailable_when_deps_missing(monkeypatch):
    # Credential present but the provider's runtime deps (playwright / steel-sdk)
    # are not importable: the seam raises SteelProviderUnavailable so the crawl
    # pod degrades to reduced coverage instead of crashing. Simulated by forcing
    # find_spec to report the packages missing, so this holds regardless of the
    # local install state.
    import importlib.util as _ilu

    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    real_find_spec = _ilu.find_spec

    def _fake_find_spec(name, *a, **k):
        if name in ("playwright", "steel"):
            return None
        return real_find_spec(name, *a, **k)

    monkeypatch.setattr(_ilu, "find_spec", _fake_find_spec)
    with pytest.raises(SC.SteelProviderUnavailable):
        asyncio.run(SC.get_crawl_tools())


def test_default_factory_returns_seven_steel_tools_when_deps_present(monkeypatch):
    # With the provider deps installed, the real default factory returns the
    # seven steel_* StructuredTools WITHOUT any network I/O (a steel.dev session
    # is opened lazily only when steel_crawl_start is invoked). This exercises
    # the real _default_client_factory -> SteelCrawlProvider.get_tools() path.
    pytest.importorskip("playwright")
    pytest.importorskip("steel")

    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    tools = asyncio.run(SC.get_crawl_tools())
    names = {t.name for t in tools}
    assert names == set(SC.CRAWL_TOOL_NAMES)
    # each tool must be ainvoke-able (LangChain StructuredTool contract)
    assert all(hasattr(t, "ainvoke") and callable(t.ainvoke) for t in tools)


def test_default_factory_passes_auth_cookies_to_provider(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    captured = {}

    class _FakeProvider:
        def __init__(self, auth_cookies=None):
            captured["auth_cookies"] = auth_cookies

        async def get_tools(self):
            return []

    import agent.recon.crawl.steel_provider as SP
    monkeypatch.setattr(SP, "SteelCrawlProvider", _FakeProvider)

    SC._default_client_factory(auth_cookies=[{"name": "a", "value": "b"}])
    assert captured["auth_cookies"] == [{"name": "a", "value": "b"}]


def test_get_crawl_tools_threads_auth_cookies_through_default_factory(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    seen = {}

    def fake_default_factory(auth_cookies=None):
        seen["auth_cookies"] = auth_cookies
        return _FakeClient([_FakeTool("steel_crawl_start")])

    monkeypatch.setattr(SC, "_default_client_factory", fake_default_factory)
    asyncio.run(SC.get_crawl_tools(auth_cookies=[{"name": "x", "value": "y"}]))
    assert seen["auth_cookies"] == [{"name": "x", "value": "y"}]


def test_crawler_role_present():
    assert "crawler" in P.ROLES
