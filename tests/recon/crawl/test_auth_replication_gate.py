"""Unit tests for the auth-replication gate (#395, Q6).

The gate is a pure predicate over the first authenticated-surface response and
the live application state. It never passes on a cookie name alone.
"""
import asyncio
from types import SimpleNamespace

from polymerhus.recon.crawl.auth_gate import evaluate_auth_gate


def test_login_redirect_fails_even_with_a_replicated_storage_marker():
    result = evaluate_auth_gate(
        status=200,
        final_url="https://app.example.com/login?next=/dashboard",
        login_url="https://app.example.com/login",
        storage={"https://app.example.com": {"token": "T"}},
        local_storage={"https://app.example.com": {"token": "T"}},
    )
    assert result == {"authenticated": False, "reason": "login_redirect"}


def test_401_and_403_fail_even_with_application_state():
    for status in (401, 403):
        result = evaluate_auth_gate(
            status=status,
            final_url="https://app.example.com/dashboard",
            storage={"https://app.example.com": {"token": "T"}},
            local_storage={"https://app.example.com": {"token": "T"}},
        )
        assert result == {"authenticated": False, "reason": f"http_{status}"}


def test_authenticated_surface_response_passes_without_storage():
    assert evaluate_auth_gate(
        status=200,
        final_url="https://app.example.com/dashboard",
        login_url="https://app.example.com/login",
    ) == {"authenticated": True, "signal": "authenticated_surface"}


def test_replicated_storage_marker_passes_application_state():
    assert evaluate_auth_gate(
        status=200,
        final_url="https://app.example.com/dashboard",
        storage={"https://app.example.com": {"token": "T"}},
        local_storage={"https://app.example.com": {"token": "T"}},
    ) == {"authenticated": True, "signal": "application_state"}


def test_storage_marker_must_match_the_replicated_value():
    assert evaluate_auth_gate(
        status=200,
        final_url="https://app.example.com/dashboard",
        storage={"https://app.example.com": {"token": "T"}},
        local_storage={"https://app.example.com": {"token": "stale"}},
    )["signal"] == "authenticated_surface"


def test_a_3xx_fails_the_legacy_surface_gate():
    """The oracle contract: a redirect is not an authenticated context, even
    when the browser follows it to a 200 page."""
    for status in (301, 302, 303, 307, 308):
        result = evaluate_auth_gate(
            status=status,
            final_url="https://app.example.com/dashboard",
        )
        assert result == {"authenticated": False, "reason": f"http_{status}"}


def test_none_or_server_error_fails():
    for status in (0, 500, 404):
        result = evaluate_auth_gate(
            status=status,
            final_url="https://app.example.com/dashboard",
        )
        assert result["authenticated"] is False


def test_login_url_comparison_ignores_query_and_trailing_slash():
    result = evaluate_auth_gate(
        status=200,
        final_url="https://app.example.com/login/?next=/dashboard",
        login_url="https://app.example.com/login",
    )
    assert result == {"authenticated": False, "reason": "login_redirect"}


def test_provider_navigation_fails_the_crawl_on_a_login_redirect():
    from polymerhus.recon.crawl.steel_provider import SteelCrawlProvider, _Crawl

    class _Page:
        url = "https://app.example.com/login"

        def on(self, *args):
            return None

        async def goto(self, url, **kwargs):
            return SimpleNamespace(status=200, headers={})

        async def evaluate(self, js):
            return {}

    page = _Page()
    crawl = _Crawl(
        "c1", ["app.example.com"], 1, 10,
        SimpleNamespace(id="s1"),
        SimpleNamespace(close=lambda: None),
        page,
        SimpleNamespace(stop=lambda: None),
        "k",
    )
    crawl.auth_required = True
    crawl.auth_checked = False
    provider = SteelCrawlProvider(
        api_key="k",
        browser_auth={
            "cookies": [{"name": "sid", "value": "S"}],
            "login_url": "https://app.example.com/login",
        },
    )
    provider._crawls["c1"] = crawl

    result = asyncio.run(provider._steel_navigate(
        "c1", "https://app.example.com/dashboard"))

    assert result["error"] == "auth_replication_failed"
    assert result["auth"]["reason"] == "login_redirect"


def _probe_provider(probe_result):
    from polymerhus.recon.crawl.steel_provider import SteelCrawlProvider, _Crawl

    class _Page:
        url = "https://app.example.com/"

        def on(self, *args):
            return None

        async def goto(self, url, **kwargs):
            return SimpleNamespace(status=200, headers={})

        async def evaluate(self, js, *args):
            if args:
                return probe_result
            return {}

    page = _Page()
    crawl = _Crawl(
        "c1", ["app.example.com"], 1, 10,
        SimpleNamespace(id="s1"),
        SimpleNamespace(close=lambda: None),
        page,
        SimpleNamespace(stop=lambda: None),
        "k",
    )
    crawl.auth_required = True
    crawl.auth_checked = False
    provider = SteelCrawlProvider(
        api_key="k",
        browser_auth={"auth_probe": "https://app.example.com/api/me"},
    )
    provider._crawls["c1"] = crawl
    return provider, crawl


def test_the_recorded_oracle_passes_a_2xx_with_no_redirect():
    provider, crawl = _probe_provider(
        {"status": 200, "redirected": False, "url": "https://app.example.com/api/me"})
    asyncio.run(provider._check_auth_gate(crawl, 200))
    assert crawl.auth_result == {"authenticated": True, "signal": "auth_probe"}


def test_the_recorded_oracle_fails_a_followed_redirect():
    provider, crawl = _probe_provider(
        {"status": 200, "redirected": True, "url": "https://app.example.com/login"})
    asyncio.run(provider._check_auth_gate(crawl, 200))
    assert crawl.auth_result["authenticated"] is False
    assert crawl.auth_result["reason"] == "auth_probe_unauthenticated"


def test_the_recorded_oracle_fails_an_indeterminate_status():
    provider, crawl = _probe_provider(
        {"status": 500, "redirected": False, "url": "https://app.example.com/api/me"})
    asyncio.run(provider._check_auth_gate(crawl, 200))
    assert crawl.auth_result["authenticated"] is False
    assert crawl.auth_result["reason"] == "auth_probe_indeterminate"
