"""The Steel crawl provider reads the shared endpoint value (#391, D359-4/5).

Every SDK call is a fake: these tests never import the real `steel` package and
never reach the network.
"""
import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

from polymerhus.recon.crawl import steel_provider


class _FakeSessions:
    def __init__(self, session):
        self._session = session
        self.released = []

    def create(self, **kwargs):
        return self._session

    def release(self, session_id):
        self.released.append(session_id)


class _FakeSteel:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.sessions = _FakeSessions(SimpleNamespace(id="session-1"))
        _FakeSteel.instances.append(self)


@pytest.fixture
def fake_steel(monkeypatch):
    """Install a fake `steel` module and clear the recorded instances."""
    module = types.ModuleType("steel")
    module.Steel = _FakeSteel
    _FakeSteel.instances = []
    monkeypatch.setitem(sys.modules, "steel", module)
    return _FakeSteel


@pytest.fixture(autouse=True)
def _clear_endpoint(monkeypatch):
    monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)


def test_client_kwargs_omit_base_url_when_unset():
    assert steel_provider._steel_client_kwargs("k", None) == {"steel_api_key": "k"}


def test_client_kwargs_pass_base_url_when_set():
    assert steel_provider._steel_client_kwargs("k", "http://host:3000") == {
        "steel_api_key": "k",
        "base_url": "http://host:3000",
    }


def test_create_session_passes_no_base_url_when_unset(fake_steel):
    steel_provider._create_steel_session("k", False)
    assert fake_steel.instances[0].kwargs == {"steel_api_key": "k"}


def test_create_session_passes_the_resolved_origin(fake_steel):
    steel_provider._create_steel_session("k", False, None, "http://host:3000")
    assert fake_steel.instances[0].kwargs == {
        "steel_api_key": "k",
        "base_url": "http://host:3000",
    }


def test_provider_reads_the_shared_resolver(monkeypatch):
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://host:3000/v1")
    assert steel_provider.SteelCrawlProvider(api_key="k")._base_url == "http://host:3000"


def test_provider_leaves_the_default_when_the_value_is_unset():
    assert steel_provider.SteelCrawlProvider(api_key="k")._base_url is None


def test_provider_explicit_base_url_wins(monkeypatch):
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://other:3000/v1")
    provider = steel_provider.SteelCrawlProvider(api_key="k", base_url="http://host:3000")
    assert provider._base_url == "http://host:3000"


def test_release_uses_the_same_base_url(fake_steel):
    async def _close():
        return None

    async def _stop():
        return None

    page = SimpleNamespace(on=lambda *args: None, url="about:blank")
    crawl = steel_provider._Crawl(
        "crawl-1",
        [],
        1,
        1,
        SimpleNamespace(id="session-1"),
        SimpleNamespace(close=_close),
        page,
        SimpleNamespace(stop=_stop),
        "k",
    )
    provider = steel_provider.SteelCrawlProvider(api_key="k", base_url="http://host:3000")
    provider._crawls["crawl-1"] = crawl

    asyncio.run(provider._finish("crawl-1"))

    assert fake_steel.instances[0].kwargs["base_url"] == "http://host:3000"
    assert fake_steel.instances[0].sessions.released == ["session-1"]


def test_cdp_uses_the_session_websocket_url():
    session = SimpleNamespace(id="session-1", websocket_url="ws://host:3000/")
    assert steel_provider._cdp_connect_url(session, "k") == "ws://host:3000/"


def test_cdp_falls_back_to_the_cloud_only_without_the_field():
    assert steel_provider._cdp_connect_url(SimpleNamespace(id="session-1"), "k") == (
        "wss://connect.steel.dev?apiKey=k&sessionId=session-1"
    )
