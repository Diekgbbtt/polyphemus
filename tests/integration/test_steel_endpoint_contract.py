"""One deployment value reaches every Steel consumer (#359, T5, D359-8).

Integration tier: compose the resolver, the CLI gateway, and the SDK provider
over one environment value. No network, no live Steel, no database - the
assertion is that every consumer reads the same name and the same form.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import kali.mcp_server as gateway
from polymerhus.app.steel_endpoint import ENV_VAR, steel_browser_api_url
from polymerhus.recon.crawl import steel_provider

VALUE = "http://192.0.2.10:3000/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _endpoint(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_unset_keeps_every_consumer_on_its_default(monkeypatch):
    assert steel_browser_api_url() is None
    assert steel_provider.SteelCrawlProvider(api_key="k")._base_url is None
    # Runtime selection belongs to the wrapper, not the gateway.
    assert not hasattr(gateway, "_local_mode")


def test_one_value_reaches_the_resolver(monkeypatch):
    monkeypatch.setenv(ENV_VAR, VALUE)
    # The SDK-native origin: the Python SDK appends /v1 itself.
    assert steel_browser_api_url() == "http://192.0.2.10:3000"


def test_the_wrapper_owns_cli_runtime_selection(monkeypatch):
    monkeypatch.setenv(ENV_VAR, VALUE)
    # The wrapper reads the same value and injects `--local`; the gateway
    # passes the command through byte-for-byte (#395, D359-13).
    wrapper = (REPO_ROOT / "kali" / "steel_wrapper.sh").read_text(encoding="utf-8")
    assert "STEEL_BROWSER_API_URL" in wrapper
    assert "--local" in wrapper
    assert "browser|scrape" in wrapper
    assert not hasattr(gateway, "_local_mode")


def test_one_value_reaches_the_sdk_provider(monkeypatch):
    monkeypatch.setenv(ENV_VAR, VALUE)
    assert steel_provider.SteelCrawlProvider(api_key="k")._base_url == (
        "http://192.0.2.10:3000"
    )
    assert steel_provider._steel_client_kwargs("k", steel_browser_api_url()) == {
        "steel_api_key": "k",
        "base_url": "http://192.0.2.10:3000",
    }
