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


def test_provider_stores_steel_profile(monkeypatch):
    from polymerhus.recon import config
    from polymerhus.recon.crawl.steel_provider import SteelCrawlProvider
    monkeypatch.setattr(config, "STEEL_API_KEY", "secret")
    assert SteelCrawlProvider(steel_profile="p1-alice")._steel_profile == "p1-alice"
    assert SteelCrawlProvider()._steel_profile is None


def test_session_opts_mount_profile_read_only_when_bound():
    from polymerhus.recon.crawl.steel_provider import _random_session_opts
    opts = _random_session_opts(False, "p1-alice")
    assert opts["profile_id"] == "p1-alice"
    assert "persist_profile" not in opts  # read-only mount, never write-back


def test_session_opts_omit_profile_when_unbound():
    from polymerhus.recon.crawl.steel_provider import _random_session_opts
    assert "profile_id" not in _random_session_opts(False, None)
    assert "profile_id" not in _random_session_opts(False)


def test_create_session_forwards_profile_id_to_the_sdk(monkeypatch):
    import steel as steel_module
    from polymerhus.recon.crawl import steel_provider

    seen = {}

    class _Sessions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return object()

    class _Steel:
        def __init__(self, steel_api_key=None):
            self.sessions = _Sessions()

    monkeypatch.setattr(steel_module, "Steel", _Steel)
    steel_provider._create_steel_session("k", False, "p1-alice")
    assert seen["profile_id"] == "p1-alice"


def test_create_session_falls_back_unprofiled_when_profile_rejected(monkeypatch):
    import steel as steel_module
    from polymerhus.recon.crawl import steel_provider

    attempts = []

    class _Sessions:
        def create(self, **kwargs):
            attempts.append(kwargs)
            if "profile_id" in kwargs:
                raise RuntimeError("unknown profile")
            return object()

    class _Steel:
        def __init__(self, steel_api_key=None):
            self.sessions = _Sessions()

    monkeypatch.setattr(steel_module, "Steel", _Steel)
    steel_provider._create_steel_session("k", False, "p1-alice")
    assert attempts[0]["profile_id"] == "p1-alice"  # tried mounted first
    assert all("profile_id" not in a for a in attempts[1:])  # ladder retries bare
