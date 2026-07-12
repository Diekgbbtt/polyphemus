"""Unit tests for non-interactive cookie injection into the Steel provider.

Covers the pure auth-context-cookie -> Playwright-cookie mapping and the
provider's constructor storage of the injected cookies. No live Steel, no
network I/O: the mapping is a pure function and the constructor performs none.

Secret handling: these tests use fabricated placeholder values only; cookie
NAMES mirror the real peoplecert fixture (`.AspNet.Cookies`, `ASP.NET_SessionId`,
`__RequestVerificationToken`) but every value here is a dummy.
"""
from agent.recon.crawl.steel_provider import _to_playwright_cookies, SteelCrawlProvider


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
    from agent.recon import config
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    provider = SteelCrawlProvider(auth_cookies=[{"name": "a", "value": "b"}])
    assert provider._auth_cookies == [{"name": "a", "value": "b"}]


def test_provider_defaults_auth_cookies_to_empty(monkeypatch):
    from agent.recon import config
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    provider = SteelCrawlProvider()
    assert provider._auth_cookies == []


def test_login_succeeded_requires_both_cookie_and_off_login_nav():
    from agent.recon.crawl.steel_provider import login_succeeded
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
