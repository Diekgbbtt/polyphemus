"""Unit tests for non-interactive cookie injection into the Steel provider.

Covers the pure auth-context-cookie -> Playwright-cookie mapping and the
provider's constructor storage of the injected cookies. No live Steel, no
network I/O: the mapping is a pure function and the constructor performs none.

Secret handling: these tests use fabricated placeholder values only; cookie
NAMES mirror the real peoplecert fixture (`.AspNet.Cookies`, `ASP.NET_SessionId`,
`__RequestVerificationToken`) but every value here is a dummy.
"""
from polymerhus.recon.crawl.steel_provider import _to_playwright_cookies, SteelCrawlProvider


def test_cookie_with_domain_maps_to_domain_path():
    out = _to_playwright_cookies(
        [{"name": ".AspNet.Cookies", "value": "TOKENVAL", "domain": ".peoplecert.org"}],
        "https://www.peoplecert.org/x",
    )
    assert out == [{"name": ".AspNet.Cookies", "value": "TOKENVAL", "domain": ".peoplecert.org", "path": "/"}]


def test_cookie_with_explicit_path_preserved():
    out = _to_playwright_cookies(
        [{"name": "ASP.NET_SessionId", "value": "SID", "domain": "www.peoplecert.org", "path": "/app"}],
        "https://www.peoplecert.org/x",
    )
    assert out == [{"name": "ASP.NET_SessionId", "value": "SID", "domain": "www.peoplecert.org", "path": "/app"}]


def test_cookie_without_domain_falls_back_to_url():
    out = _to_playwright_cookies(
        [{"name": "__RequestVerificationToken", "value": "CSRF"}],
        "https://www.peoplecert.org/certifications-and-memberships",
    )
    assert out == [{"name": "__RequestVerificationToken", "value": "CSRF", "url": "https://www.peoplecert.org/certifications-and-memberships"}]


def test_malformed_entries_are_skipped():
    out = _to_playwright_cookies(
        [
            {"name": "ok", "value": "v"},
            {"value": "no-name"},
            {"name": "no-value"},
            {"name": 123, "value": "x"},
            "not-a-dict",
        ],
        "https://example.com",
    )
    assert out == [{"name": "ok", "value": "v", "url": "https://example.com"}]


def test_empty_input_maps_to_empty_list():
    assert _to_playwright_cookies([], "https://example.com") == []
    assert _to_playwright_cookies(None, "https://example.com") == []


def test_provider_stores_auth_cookies(monkeypatch):
    from polymerhus.recon import config
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    provider = SteelCrawlProvider(auth_cookies=[{"name": "a", "value": "b"}])
    assert provider._auth_cookies == [{"name": "a", "value": "b"}]


def test_provider_defaults_auth_cookies_to_empty(monkeypatch):
    from polymerhus.recon import config
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    provider = SteelCrawlProvider()
    assert provider._auth_cookies == []


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


def test_regions_include_eu_datacenters():
    from polymerhus.recon.crawl.steel_provider import _REGIONS
    assert {"eu-west", "eu-central"} <= set(_REGIONS)
    # The US datacenters must not be dropped.
    assert {"lax", "ord", "iad"} <= set(_REGIONS)


def test_random_session_opts_region_is_a_known_region():
    from polymerhus.recon.crawl.steel_provider import _REGIONS, _random_session_opts
    for _ in range(20):
        assert _random_session_opts(False)["region"] in _REGIONS


def test_login_succeeded_requires_both_cookie_and_off_login_nav():
    from polymerhus.recon.crawl.steel_provider import login_succeeded
    scope = ["example.com"]
    baseline = {"visitor"}
    new_session = [{"name": "sessionid", "value": "x", "domain": "example.com", "httpOnly": True}]

    # both conditions -> success
    assert login_succeeded(baseline, new_session, "https://app.example.com/dashboard", scope) is True
    # new cookie but still on the login path -> NOT success (failed submit)
    assert login_succeeded(baseline, new_session, "https://login.example.com/login", scope) is False
    # off-login page but no new session cookie -> NOT success
    assert login_succeeded(baseline, [{"name": "visitor", "value": "x", "domain": "example.com"}],
                           "https://app.example.com/home", scope) is False
    # new cookie scoped to the wrong (out-of-scope) domain -> NOT success
    assert login_succeeded(baseline, [{"name": "sessionid", "value": "x", "domain": "idp.other.com",
                                       "httpOnly": True}], "https://app.example.com/home", scope) is False
