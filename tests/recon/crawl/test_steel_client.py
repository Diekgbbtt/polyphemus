import asyncio

import pytest

from polymerhus.app.llm import providers as P
from polymerhus.recon import config
from polymerhus.recon.crawl import steel_client as SC


class _FakeTool:
    def __init__(self, name):
        self.name = name


class _FakeClient:
    def __init__(self, tools):
        self._tools = tools

    async def get_tools(self):
        return self._tools


def test_steel_configured_false_when_key_and_endpoint_are_unset(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "")
    monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)
    assert SC.steel_configured() is False


def test_steel_configured_true_when_key_set(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    assert SC.steel_configured() is True


def test_steel_configured_true_when_only_the_local_endpoint_is_set(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "")
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://steel.test:3000/v1")
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
    monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)
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


def test_default_factory_returns_six_steel_tools_when_deps_present(monkeypatch):
    # With the provider deps installed, the real default factory returns the
    # six steel_* StructuredTools WITHOUT any network I/O (a steel.dev session
    # is opened lazily only when steel_crawl_start is invoked - the retired
    # interactive await_auth tool is no longer bound). This exercises
    # the real _default_client_factory -> SteelCrawlProvider.get_tools() path.
    pytest.importorskip("playwright")
    pytest.importorskip("steel")

    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    tools = asyncio.run(SC.get_crawl_tools())
    names = {t.name for t in tools}
    assert names == set(SC.CRAWL_TOOL_NAMES)
    # each tool must be ainvoke-able (LangChain StructuredTool contract)
    assert all(hasattr(t, "ainvoke") and callable(t.ainvoke) for t in tools)


def test_default_factory_passes_state_and_browser_auth_to_provider(monkeypatch):
    # The real factory raises SteelProviderUnavailable when the provider
    # deps are absent, so skip there (same discipline as the six-tools test).
    pytest.importorskip("playwright")
    pytest.importorskip("steel")
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    captured = {}

    class _FakeProvider:
        def __init__(self, steel_state=None, browser_auth=None):
            captured["steel_state"] = steel_state
            captured["browser_auth"] = browser_auth

        async def get_tools(self):
            return []

    import polymerhus.recon.crawl.steel_provider as SP
    monkeypatch.setattr(SP, "SteelCrawlProvider", _FakeProvider)

    material = {"cookies": [{"name": "a", "value": "b"}],
                "headers": {"X-Api-Key": "K"}}
    SC._default_client_factory(steel_state="/state/alice.json",
                               browser_auth=material)
    assert captured["steel_state"] == "/state/alice.json"
    assert captured["browser_auth"] == material


def test_get_crawl_tools_threads_state_and_browser_auth_through_default_factory(monkeypatch):
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    seen = {}

    def fake_default_factory(steel_state=None, browser_auth=None):
        seen["steel_state"] = steel_state
        seen["browser_auth"] = browser_auth
        return _FakeClient([_FakeTool("steel_crawl_start")])

    monkeypatch.setattr(SC, "_default_client_factory", fake_default_factory)
    material = {"cookies": [{"name": "x", "value": "y"}]}
    asyncio.run(SC.get_crawl_tools(steel_state="/state/alice.json",
                                   browser_auth=material))
    assert seen["steel_state"] == "/state/alice.json"
    assert seen["browser_auth"] == material


def test_crawler_role_present():
    assert "crawler" in {r.role_id for r in P.ROLES}
