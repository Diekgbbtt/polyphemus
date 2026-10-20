"""Unit tests for the Steel provider's session-only wiring (#395).

Covers the deterministic create options, auth-material merge, constructor
storage, and non-HTML filtering. No live Steel, no network I/O.
"""
import pytest

from polymerhus.recon.crawl.steel_provider import (
    SteelCrawlProvider,
    _merge_browser_auth,
    _session_opts,
)


def test_session_opts_are_deterministic_and_profile_free():
    opts = _session_opts(True)
    assert opts == {"use_proxy": True, "headless": False}
    assert "profile_id" not in opts
    assert "persist_profile" not in opts
    assert "user_agent" not in opts
    assert "dimensions" not in opts
    assert "region" not in opts
    assert "stealth_config" not in opts


def test_session_opts_restore_the_sdk_state_shape():
    opts = _session_opts(False, {
        "cookies": [{"name": "sid", "value": "S"}],
        "localStorage": {"https://x.example": {"token": "T"}},
        "sessionStorage": {},
        "indexedDB": {},
        "extra": "dropped",
    })
    assert opts["session_context"] == {
        "cookies": [{"name": "sid", "value": "S"}],
        "local_storage": {"https://x.example": {"token": "T"}},
        "session_storage": {},
        "indexed_db": {},
    }


def test_merge_browser_auth_replaces_cookies_and_merges_storage():
    state = {
        "cookies": [{"name": "sid", "value": "OLD", "domain": "x.example"}],
        "localStorage": {"https://x.example": {"keep": "1", "token": "OLD"}},
    }
    merged = _merge_browser_auth(state, {
        "cookies": [
            {"name": "sid", "value": "NEW", "domain": "x.example"},
            {"name": "csrf", "value": "C"},
        ],
        "headers": {"X-Api-Key": "K"},
        "storage": {"https://x.example": {"token": "T", "fresh": "2"}},
    }, "https://x.example/dashboard")
    assert merged["cookies"] == [
        {"name": "sid", "value": "NEW", "domain": "x.example"},
        {"name": "csrf", "value": "C", "url": "https://x.example/dashboard"},
    ]
    assert merged["localStorage"] == {
        "https://x.example": {"keep": "1", "token": "T", "fresh": "2"},
    }
    assert "headers" not in merged


def test_merge_browser_auth_without_state_still_replicates_material():
    assert _merge_browser_auth(None, {
        "cookies": [{"name": "sid", "value": "S"}],
        "storage": {"https://x.example": {"token": "T"}},
    }) == {
        "cookies": [{"name": "sid", "value": "S"}],
        "localStorage": {"https://x.example": {"token": "T"}},
    }


def test_provider_stores_state_and_browser_auth(monkeypatch):
    from polymerhus.recon import config
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    material = {"cookies": [{"name": "a", "value": "b"}]}
    provider = SteelCrawlProvider(steel_state="/state/alice.json",
                                  browser_auth=material)
    assert provider._steel_state == "/state/alice.json"
    assert provider._browser_auth == material


def test_provider_defaults_to_empty_state_and_material(monkeypatch):
    from polymerhus.recon import config
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    provider = SteelCrawlProvider()
    assert provider._steel_state is None
    assert provider._browser_auth == {}


def test_looks_non_html_detects_asset_extensions():
    from polymerhus.recon.crawl.steel_provider import _looks_non_html
    assert _looks_non_html("https://x.daytona.io/a/app.js") is True
    assert _looks_non_html("https://x.daytona.io/dashboard/keys") is False
    assert _looks_non_html("https://x.daytona.io/api/config?x=1") is False


def test_is_html_content_type_fails_open():
    from polymerhus.recon.crawl.steel_provider import _is_html_content_type
    assert _is_html_content_type("text/html; charset=utf-8") is True
    assert _is_html_content_type("application/javascript") is False
    assert _is_html_content_type(None) is True


def test_enqueue_skips_non_html_but_keeps_html(monkeypatch):
    from polymerhus.recon.crawl.steel_provider import _Crawl

    # Construct a bare _Crawl without running __init__ (which attaches page
    # listeners to a live Playwright page); set only the fields enqueue reads.
    crawl = _Crawl.__new__(_Crawl)
    crawl.scope = ["daytona.io"]
    crawl.max_depth = 3
    crawl.visited = set()
    crawl.queued = set()
    crawl.frontier = []

    crawl.enqueue(
        [
            "https://app.daytona.io/static/app.js",
            "https://app.daytona.io/dashboard/keys",
        ],
        depth=1,
    )
    queued_urls = {f["url"] for f in crawl.frontier}
    assert "https://app.daytona.io/dashboard/keys" in queued_urls
    assert "https://app.daytona.io/static/app.js" not in queued_urls
