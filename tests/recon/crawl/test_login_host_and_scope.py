"""Navigation gate removal + Bug B (upstream scope normalization).

Navigation gate: `_steel_navigate` no longer refuses off-frontier URLs. The
operator prefers to trust the agent's reasoning for navigation; scope is
enforced on RECORDED assets (the `enqueue` scope filter on discovered links plus
the curator's out-of-scope BaseURL drop), not by refusing navigations. This also
removed the exact-string-match fragility that rejected semantically-in-scope URL
variants and left the anonymous crawl stuck on about:blank. The credentialed
login flow no longer needs a login-host frontier exception: the agent simply
navigates to the login_url directly.

Bug B: the crawl scope is normalized to bare hosts at its authoritative
resolution point (`crawl_pod.py`'s `scope = extra.get("scope") or [target]`),
so a scheme-prefixed target (e.g. `https://stage-ifr.peoplecert.org`) can never
filter the target host out of its own frontier. This still feeds the enqueue
scope filter on discovered links.

No live Steel/LLM: the navigate tests drive `_steel_navigate` against a fake
page; Bug B captures the values threaded through the collaborators.
"""
import asyncio

import pytest


# ---------------------------------------------------------------------------
# Fake Playwright page (enough surface for _steel_navigate's happy path)
# ---------------------------------------------------------------------------


class _FakeMouse:
    async def move(self, *a, **k):
        pass

    async def wheel(self, *a, **k):
        pass


class _FakeResp:
    def __init__(self, status):
        self.status = status


class _FakeCtx:
    async def cookies(self):
        return []


class _FakePage:
    def __init__(self, status=200, links=None):
        self._url = "about:blank"
        self._status = status
        self._links = links or []
        self.mouse = _FakeMouse()
        self.context = _FakeCtx()

    def on(self, event, cb):
        pass

    async def goto(self, url, wait_until=None, timeout=None):
        self._url = url
        return _FakeResp(self._status)

    @property
    def url(self):
        return self._url

    async def wait_for_timeout(self, ms):
        pass

    async def eval_on_selector_all(self, selector, expr):
        return list(self._links)


def _make_crawl(scope=None, page=None):
    from polymerhus.recon.crawl.steel_provider import _Crawl

    crawl = _Crawl(
        "cid", scope or ["app.example.com"], 3, 50,
        session=None, browser=None, page=page or _FakePage(), pw=None, api_key="k",
    )
    crawl.enqueue(["https://app.example.com"], depth=0)  # target seeded in frontier
    return crawl


def _provider_with(crawl):
    from polymerhus.recon.crawl.steel_provider import SteelCrawlProvider

    p = SteelCrawlProvider(api_key="k")
    p._crawls[crawl.id] = crawl
    return p


# ---------------------------------------------------------------------------
# Navigation gate removed: the agent may navigate anywhere it reasons to
# ---------------------------------------------------------------------------


def test_in_frontier_target_still_navigable():
    crawl = _make_crawl()
    p = _provider_with(crawl)
    out = asyncio.run(p._steel_navigate("cid", "https://app.example.com", wait_ms=0))
    assert "error" not in out
    assert out["status"] == 200
    assert "https://app.example.com" in crawl.visited


def test_off_frontier_url_is_now_allowed():
    # The exact-string-match frontier gate is gone: a URL that is not literally
    # in the frontier (e.g. a trailing-slash / path variant of the target) is no
    # longer rejected with `url_not_in_frontier`. This is the anonymous
    # about:blank fix - the first navigate is never refused.
    crawl = _make_crawl()
    p = _provider_with(crawl)
    out = asyncio.run(p._steel_navigate("cid", "https://app.example.com/dashboard", wait_ms=0))
    assert "error" not in out
    assert out["status"] == 200
    assert "https://app.example.com/dashboard" in crawl.visited


def test_credentialed_login_url_navigable_without_frontier_exception():
    # The credentialed agent navigates straight to an off-target login host; no
    # login-host frontier exception is needed anymore.
    crawl = _make_crawl()
    p = _provider_with(crawl)
    out = asyncio.run(p._steel_navigate("cid", "https://login.example.com/login", wait_ms=0))
    assert "error" not in out
    assert "https://login.example.com/login" in crawl.visited


# ---------------------------------------------------------------------------
# Scope safety on RECORDED assets: discovered links are still scope-filtered
# ---------------------------------------------------------------------------


def test_out_of_scope_discovered_links_are_not_enqueued():
    # Navigation is unrestricted, but discovered links from a visited page are
    # still scope-filtered before they enter the frontier/queued sets - so
    # out-of-scope hosts the agent touches are never recorded as in-scope assets.
    page = _FakePage(links=[
        "https://app.example.com/settings",   # in scope -> enqueued
        "https://evil.example.com/x",          # out of scope -> dropped
    ])
    crawl = _make_crawl(page=page)
    p = _provider_with(crawl)
    out = asyncio.run(p._steel_navigate("cid", "https://app.example.com", wait_ms=0))
    assert "error" not in out
    frontier_urls = {f["url"] for f in out["frontier"]}
    assert "https://app.example.com/settings" in frontier_urls
    assert "https://evil.example.com/x" not in frontier_urls
    assert "https://evil.example.com/x" not in crawl.queued


# ---------------------------------------------------------------------------
# Bug B: upstream scope normalization (crawl_pod resolution point)
# ---------------------------------------------------------------------------


def _build_pod(run_crawl_fn):
    from polymerhus.recon.crawl import crawl_pod

    return crawl_pod.build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=lambda a, o, p, **k: (len(a), len(o), a, o),
    )


def _pod_state(url, extra=None):
    from polymerhus.recon.domain.types import JobSpec

    job = JobSpec(
        tool="steel_crawl", skill="agentic_crawl", command_template="",
        produces=["BaseURL"], consumes="BaseURL", configurator_mode="agent",
    )
    return {
        "job": job,
        "input_asset": {"url": url},
        "asset_context": "",
        "extra": extra or {},
        "session_id": "s", "project_id": "p",
    }


def test_scheme_prefixed_target_folds_to_registrable_domain_scope():
    seen = {}

    def run_crawl_fn(target, *, scope, auth_cookies=None):
        seen["scope"] = scope
        return {"endpoints": [{"url": "x"}], "js_urls": []}

    pod = _build_pod(run_crawl_fn)
    pod.invoke(_pod_state("https://stage-ifr.peoplecert.org"))
    # Change A: scope folds to the registrable domain, so _registrable_in_scope
    # admits the target host and any sibling subdomain.
    assert seen["scope"] == ["peoplecert.org"]


def test_scheme_prefixed_extra_scope_entries_fold_and_dedup():
    seen = {}

    def run_crawl_fn(target, *, scope, auth_cookies=None):
        seen["scope"] = scope
        return {"endpoints": [{"url": "x"}], "js_urls": []}

    pod = _build_pod(run_crawl_fn)
    pod.invoke(_pod_state(
        "https://ebook.peoplecert.org",
        extra={"scope": ["https://ebook.peoplecert.org", "www.peoplecert.org", "peoplecert.org"]},
    ))
    # Change A: every entry folds to the same registrable domain (dedup).
    assert seen["scope"] == ["peoplecert.org"]
