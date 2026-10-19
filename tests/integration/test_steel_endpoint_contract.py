"""One deployment value reaches every Steel consumer (#359, T5, D359-8).

Integration tier: compose the resolver, the CLI gateway, and the SDK provider
over one environment value. No network, no live Steel, no database - the
assertion is that every consumer reads the same name and the same form.
"""
from __future__ import annotations

import pytest

import kali.mcp_server as gateway
from polymerhus.app.steel_endpoint import ENV_VAR, steel_browser_api_url
from polymerhus.recon.crawl import steel_provider

VALUE = "http://192.0.2.10:3000/v1"


@pytest.fixture(autouse=True)
def _endpoint(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_unset_keeps_every_consumer_on_its_default(monkeypatch):
    assert steel_browser_api_url() is None
    assert steel_provider.SteelCrawlProvider(api_key="k")._base_url is None
    assert gateway._local_mode("steel browser sessions --json") == "steel browser sessions --json"


def test_one_value_reaches_the_resolver(monkeypatch):
    monkeypatch.setenv(ENV_VAR, VALUE)
    # The SDK-native origin: the Python SDK appends /v1 itself.
    assert steel_browser_api_url() == "http://192.0.2.10:3000"


def test_one_value_reaches_the_cli_gateway(monkeypatch):
    monkeypatch.setenv(ENV_VAR, VALUE)
    # The CLI reads the variable natively; the gateway adds only the mode flag.
    assert gateway._local_mode("steel browser sessions --json") == (
        "steel --local browser sessions --json"
    )


def test_one_value_reaches_the_sdk_provider(monkeypatch):
    monkeypatch.setenv(ENV_VAR, VALUE)
    assert steel_provider.SteelCrawlProvider(api_key="k")._base_url == (
        "http://192.0.2.10:3000"
    )
    assert steel_provider._steel_client_kwargs("k", steel_browser_api_url()) == {
        "steel_api_key": "k",
        "base_url": "http://192.0.2.10:3000",
    }
