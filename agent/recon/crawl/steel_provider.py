"""In-process Steel cloud-browser crawl-tool provider (async port).

This is the concrete provider `steel_client._default_client_factory()` returns.
It is the polymerhus port of Redamon's `mcp/servers/playwright_server.py` steel
section, adapted from a FastMCP-in-a-subprocess server (SYNC Playwright API) to
an IN-PROCESS provider driven from the crawl ReAct loop's asyncio event loop
(ASYNC Playwright API - the sync API cannot run inside a running event loop).

Architecture (operator correction, SP4): steel.dev is the authenticated CLOUD
BROWSER. The provider opens a steel.dev session with the Steel SDK and drives it
with Playwright connected over CDP at

    wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<session id>

The only credential is `config.STEEL_API_KEY`; there is no MCP host URL.

Contract: `SteelCrawlProvider.get_tools()` returns a list of LangChain
`StructuredTool`s, one per name in `steel_client.CRAWL_TOOL_NAMES`. Each tool is
`await tool.ainvoke(dict)`-able and returns a plain dict (normalized downstream
by `crawl_agentic._payload_from_tool_result`), and the list is
`llm.bind_tools(...)`-able.

De-coupled from Redamon: no DinD, no `WEBAPP_API_URL`/`INTERNAL_API_KEY` key
resolution, no webapp Resume-flag polling, no `user_id` -> key lookup (the
`user_id` arg is kept on `steel_crawl_start` only because the ReAct loop injects
it; it is ignored). The crawl-session registry is INSTANCE-scoped (one provider
per crawl job) rather than a module global, so concurrent jobs never share state.

Runtime dependency: `playwright` and `steel-sdk` must be importable in the agent
image (the `redamon-agent` base provides both). They are imported LAZILY inside
the tool coroutines so importing this module never requires them - a build
without them degrades to `SteelProviderUnavailable` at the factory seam, not an
import crash.
"""
from __future__ import annotations

import asyncio
import random
import re
import threading
import time
import uuid
from urllib.parse import parse_qsl, urlparse

from agent.recon import config

# ---------------------------------------------------------------------------
# Auth-detection predicates (used by steel_await_auth) - ported verbatim
# ---------------------------------------------------------------------------

_SESSION_COOKIE_RE = re.compile(r"(session|sess|sid|auth|token|jwt|__secure|csrf)", re.I)
_LOGIN_PATH_RE = re.compile(r"/(login|signin|sign-in|sso|oauth|account/login|session)", re.I)


def _registrable_in_scope(host: str, scope: list) -> bool:
    """Return True if host is equal to or a subdomain of any entry in scope."""
    host = (host or "").lower()
    return any(host == s.lower() or host.endswith("." + s.lower()) for s in scope)


def _is_session_like_cookie(c: dict) -> bool:
    """A cookie that plausibly represents an authenticated session."""
    return bool(_SESSION_COOKIE_RE.search(c.get("name", "") or "")) or bool(c.get("httpOnly"))


def _cookie_domain_in_scope(c: dict, scope: list) -> bool:
    dom = (c.get("domain") or "").lstrip(".").lower()
    if not scope:
        return True
    return any(dom == s.lower() or dom.endswith("." + s.lower()) for s in scope)


def _has_new_session_cookie(baseline_names: set, current: list, scope: list) -> bool:
    """True if an in-scope session-like cookie appeared that wasn't in the baseline set."""
    for c in current or []:
        if c.get("name") in baseline_names:
            continue
        if _cookie_domain_in_scope(c, scope) and _is_session_like_cookie(c):
            return True
    return False


def _url_is_authenticated_app(url: str, scope: list) -> bool:
    """In-scope app page that is NOT a login/SSO route (so we wait for the SSO return)."""
    p = urlparse(url or "")
    if not _registrable_in_scope(p.netloc, scope):
        return False
    return not _LOGIN_PATH_RE.search(p.path or "/")


def login_succeeded(baseline_names: set, current_cookies: list, url: str, scope: list) -> bool:
    """D23 hardened success test: an autonomous login counts as authenticated
    ONLY when BOTH hold - a NEW in-scope session-like cookie appeared vs the
    pre-login baseline AND the browser navigated to an in-scope non-login page.
    Either alone is a false positive (a CSRF/visitor cookie on the login page,
    or an off-login bounce with no session), which unattended login cannot
    afford. Pure; composes the existing steel_await_auth predicates."""
    return _has_new_session_cookie(baseline_names, current_cookies, scope) and \
        _url_is_authenticated_app(url, scope)


# ---------------------------------------------------------------------------
# Per-session fingerprint randomisation - ported verbatim
# ---------------------------------------------------------------------------

# scl/fra/nrt are deprecated and 400 at create; only lax/ord/iad accept sessions.
_REGIONS = ["lax", "ord", "iad"]
# Linux-only UAs ON PURPOSE: Steel runs on Linux and does not override
# navigator.platform, so a Windows/Mac UA would mismatch the platform (a bot tell).
_UAS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
]
_VIEWPORTS = [(1920, 1080), (1536, 864), (1440, 900), (1366, 768), (1600, 900)]


def _random_session_opts(use_proxy: bool) -> dict:
    """Return a randomised set of Steel sessions.create kwargs for fingerprint diversity."""
    w, h = random.choice(_VIEWPORTS)
    return {
        "use_proxy": use_proxy,
        "region": random.choice(_REGIONS),
        "user_agent": random.choice(_UAS),
        "dimensions": {"width": w, "height": h},
        "headless": False,
        "stealth_config": {"humanize_interactions": True},
    }


def _extract_links_expr() -> str:
    return "els => els.map(a => a.href)"


def _to_playwright_cookies(cookies, default_url: str) -> list:
    """Map auth_context cookies ({name, value, [domain], [path]}) to the
    Playwright `context.add_cookies` shape.

    With a domain -> {name, value, domain, path} (path defaults to "/").
    Without a domain -> {name, value, url} so Playwright infers domain/path
    from `default_url` (the crawl target's URL). Entries lacking a string
    name/value are skipped so one malformed fixture entry never aborts the set.
    """
    out = []
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        name, value = c.get("name"), c.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        pc = {"name": name, "value": value}
        if c.get("domain"):
            pc["domain"] = c["domain"]
            pc["path"] = c.get("path", "/")
        else:
            pc["url"] = default_url
        out.append(pc)
    return out


# ---------------------------------------------------------------------------

class _Crawl:
    """Holds all mutable state for a single Steel crawl session (async page)."""

    def __init__(self, crawl_id, scope, max_depth, max_pages, session, browser, page, pw, api_key):
        self.id = crawl_id
        self.scope = scope
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.session = session
        self.browser = browser
        self.page = page
        self.pw = pw
        self.api_key = api_key
        self.started = time.time()
        self.last_active = time.time()
        self.current_depth = 0
        self.visited: set = set()
        self.queued: set = set()
        self.frontier: list = []
        self.pages_done = 0
        self.requests: list = []
        self.responses: dict = {}
        self._req_lock = threading.Lock()
        self.baseline_cookies: list = []
        self._attach_listeners()

    def _attach_listeners(self):
        def _on_request(req):
            try:
                entry = {
                    "url": req.url,
                    "type": req.resource_type,
                    "method": req.method,
                    "post": req.post_data,
                }
                with self._req_lock:
                    self.requests.append(entry)
            except Exception:
                pass

        def _on_response(resp):
            try:
                with self._req_lock:
                    self.responses[resp.url] = resp.status
            except Exception:
                pass

        self.page.on("request", _on_request)
        self.page.on("response", _on_response)

    def enqueue(self, urls: list, depth: int):
        """Add URLs to the frontier, enforcing scope, dedup, and depth cap."""
        if depth > self.max_depth:
            return
        for u in urls:
            if not _registrable_in_scope(urlparse(u).netloc, self.scope):
                continue
            if u in self.visited or u in self.queued:
                continue
            self.queued.add(u)
            self.frontier.append({"url": u, "depth": depth})
        self.frontier.sort(key=lambda x: x["depth"])

    def frontier_view(self) -> dict:
        return {
            "frontier": list(self.frontier),
            "visited_count": len(self.visited),
            "pages_remaining": max(0, self.max_pages - self.pages_done),
        }


def _build_manifest(crawl: _Crawl) -> dict:
    """Build the endpoint/js_urls manifest from the crawl's captured requests.

    Manifest shape: {endpoints: [{method, url, query, body, status}], js_urls: []}
    """
    with crawl._req_lock:
        requests_snapshot = list(crawl.requests)
        responses_snapshot = dict(crawl.responses)

    endpoints, js_urls, seen = [], set(), set()
    for r in requests_snapshot:
        rt, url, method = r["type"], r["url"], r["method"]
        if rt == "script" or url.split("?")[0].endswith(".js"):
            js_urls.add(url)
            continue
        if rt in ("xhr", "fetch", "document"):
            p = urlparse(url)
            key = (method, p.scheme, p.netloc, p.path)
            if key in seen:
                continue
            seen.add(key)
            query = [k for k, _ in parse_qsl(p.query)]
            body: list = []
            if r.get("post"):
                body = [k for k, _ in parse_qsl(r["post"])] or ["<raw-body>"]
            status = responses_snapshot.get(url, 0)
            endpoints.append({
                "method": method,
                "url": url,
                "query": query,
                "body": body,
                "status": status,
            })
    return {"endpoints": endpoints, "js_urls": sorted(js_urls)}


def _create_steel_session(api_key: str, use_proxy: bool):
    """Create a Steel session (SYNC SDK), with the reference's opts fallback ladder.

    Runs off the event loop via `asyncio.to_thread`. Returns the session object.
    """
    from steel import Steel  # noqa: PLC0415

    client = Steel(steel_api_key=api_key)
    opts = _random_session_opts(use_proxy)
    try:
        return client, client.sessions.create(**opts)
    except Exception:
        try:
            return client, client.sessions.create(
                use_proxy=use_proxy,
                user_agent=opts["user_agent"],
                dimensions=opts["dimensions"],
            )
        except Exception:
            return client, client.sessions.create()


class SteelCrawlProvider:
    """In-process provider exposing the seven `steel_*` crawl tools.

    One instance drives one crawl job. `get_tools()` returns LangChain
    `StructuredTool`s bound to this instance's crawl registry.
    """

    def __init__(self, api_key: str | None = None, *, session_lifetime_s: int | None = None, auth_cookies=None):
        self._api_key = api_key if api_key is not None else config.STEEL_API_KEY
        self._session_lifetime_s = (
            session_lifetime_s
            if session_lifetime_s is not None
            else int(getattr(config, "CRAWL_JOB_TIMEOUT_S", 480))
        )
        # Non-interactive auth: session cookies to seed the browser context with
        # (via context.add_cookies) BEFORE the crawl, so it runs authenticated
        # without the human steel_await_auth step. Empty for an anonymous crawl.
        self._auth_cookies = list(auth_cookies or [])
        self._crawls: dict[str, _Crawl] = {}
        self._lock = threading.Lock()

    # -- lifecycle helpers --------------------------------------------------

    async def _finish(self, crawl_id: str) -> dict:
        """Build manifest, close browser, stop Playwright, release Steel session."""
        with self._lock:
            crawl = self._crawls.pop(crawl_id, None)
        if not crawl:
            return {"endpoints": [], "js_urls": []}
        manifest = _build_manifest(crawl)
        try:
            await crawl.browser.close()
        except Exception:
            pass
        try:
            await crawl.pw.stop()
        except Exception:
            pass
        try:
            from steel import Steel  # noqa: PLC0415

            await asyncio.to_thread(
                Steel(steel_api_key=crawl.api_key).sessions.release, crawl.session.id
            )
        except Exception:
            pass
        return manifest

    async def _reap_expired(self):
        """Release crawls idle longer than the session lifetime (inactivity-based)."""
        now = time.time()
        with self._lock:
            expired = [
                cid for cid, c in self._crawls.items()
                if now - c.last_active > self._session_lifetime_s
            ]
        for cid in expired:
            await self._finish(cid)

    async def aclose(self):
        """Release every live crawl session (best-effort cleanup hook)."""
        with self._lock:
            ids = list(self._crawls.keys())
        for cid in ids:
            await self._finish(cid)

    # -- tool implementations ----------------------------------------------

    async def _steel_crawl_start(
        self,
        target: str,
        scope: list,
        max_depth: int = 3,
        max_pages: int = 50,
        use_proxy: bool = False,
        user_id: str = "",
    ) -> dict:
        if not self._api_key:
            return {"error": "steel_api_key_unavailable"}

        from playwright.async_api import async_playwright  # noqa: PLC0415

        await self._reap_expired()
        client, session = await asyncio.to_thread(
            _create_steel_session, self._api_key, use_proxy
        )
        p = await async_playwright().start()
        cdp_url = f"wss://connect.steel.dev?apiKey={self._api_key}&sessionId={session.id}"
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            ctx = browser.contexts[0]
            if self._auth_cookies:
                # NON-INTERACTIVE AUTH: seed the browser context with the
                # project's session cookies BEFORE any navigation, so the crawl
                # runs authenticated without the human steel_await_auth step.
                # Best-effort: a malformed cookie must degrade to an
                # unauthenticated crawl, never crash the session.
                try:
                    await ctx.add_cookies(_to_playwright_cookies(self._auth_cookies, target))
                except Exception:
                    pass
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        except Exception:
            try:
                await p.stop()
            except Exception:
                pass
            try:
                await asyncio.to_thread(client.sessions.release, session.id)
            except Exception:
                pass
            raise
        crawl_id = uuid.uuid4().hex
        crawl = _Crawl(crawl_id, scope, max_depth, max_pages, session, browser, page, p, self._api_key)
        crawl.enqueue([target], depth=0)
        with self._lock:
            self._crawls[crawl_id] = crawl
        try:
            crawl.baseline_cookies = await crawl.page.context.cookies()
        except Exception:
            crawl.baseline_cookies = []
        return {
            "crawl_id": crawl_id,
            "frontier": list(crawl.frontier),
            "viewer_url": getattr(session, "session_viewer_url", ""),
        }

    async def _steel_navigate(self, crawl_id: str, url: str, wait_ms: int = 800) -> dict:
        with self._lock:
            crawl = self._crawls.get(crawl_id)
        if not crawl:
            return {"error": "unknown crawl_id"}
        if crawl.pages_done >= crawl.max_pages:
            return {"error": "page_cap_reached", **crawl.frontier_view()}
        if not any(f["url"] == url for f in crawl.frontier):
            return {"error": "url_not_in_frontier", **crawl.frontier_view()}

        crawl.last_active = time.time()
        depth = next((f["depth"] for f in crawl.frontier if f["url"] == url), 0)
        crawl.current_depth = depth
        crawl.frontier = [f for f in crawl.frontier if f["url"] != url]
        crawl.queued.discard(url)
        crawl.visited.add(url)
        crawl.pages_done += 1

        blocked, block_type, status = False, None, 0
        try:
            resp = await crawl.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            status = resp.status if resp else 0
            if status in (401, 403, 404):
                blocked = status in (401, 403)
                block_type = str(status)
            if "captcha" in (crawl.page.url or "").lower():
                blocked, block_type = True, "captcha"
        except Exception as e:
            return {"error": str(e), **crawl.frontier_view()}

        new_links: list = []
        if status not in (401, 403, 404):
            try:
                for _ in range(random.randint(2, 4)):
                    await crawl.page.mouse.move(
                        random.randint(0, 1200), random.randint(0, 700),
                        steps=random.randint(3, 8),
                    )
                await crawl.page.mouse.wheel(0, random.randint(200, 900))
                await crawl.page.wait_for_timeout(random.randint(150, 500))
            except Exception:
                pass
            new_links = await self._extract_links(crawl.page)
            crawl.enqueue(new_links, depth=depth + 1)

        with crawl._req_lock:
            recent_requests = list(crawl.requests[-50:])
        delta = [r["url"] for r in recent_requests]
        return {
            **crawl.frontier_view(),
            "new_links": new_links,
            "network_delta": delta,
            "status": status,
            "blocked": blocked,
            "block_type": block_type,
        }

    async def _steel_frontier(self, crawl_id: str) -> dict:
        with self._lock:
            crawl = self._crawls.get(crawl_id)
        return crawl.frontier_view() if crawl else {"error": "unknown crawl_id"}

    async def _steel_crawl_finish(self, crawl_id: str) -> dict:
        return await self._finish(crawl_id)

    async def _steel_click(self, crawl_id: str, selector: str, wait_ms: int = 800) -> dict:
        with self._lock:
            crawl = self._crawls.get(crawl_id)
        if not crawl:
            return {"error": "unknown crawl_id"}
        crawl.last_active = time.time()
        try:
            await crawl.page.click(selector, timeout=10000)
            await crawl.page.wait_for_timeout(wait_ms)
        except Exception as e:
            return {"error": f"click_failed: {e}", **crawl.frontier_view()}
        cur_url = crawl.page.url or ""
        with crawl._req_lock:
            status = crawl.responses.get(cur_url, 0)
            delta = [r["url"] for r in crawl.requests[-50:]]
        blocked, block_type = False, None
        if status in (401, 403, 404):
            blocked = status in (401, 403)
            block_type = str(status)
        if "captcha" in cur_url.lower():
            blocked, block_type = True, "captcha"
        new_links: list = []
        if status not in (401, 403, 404):
            new_links = await self._extract_links(crawl.page)
            crawl.enqueue(new_links, depth=crawl.current_depth + 1)
        return {
            **crawl.frontier_view(),
            "current_url": cur_url,
            "new_links": new_links,
            "network_delta": delta,
            "status": status,
            "blocked": blocked,
            "block_type": block_type,
        }

    async def _steel_eval(self, crawl_id: str, js: str) -> dict:
        with self._lock:
            crawl = self._crawls.get(crawl_id)
        if not crawl:
            return {"error": "unknown crawl_id"}
        try:
            return {"result": await crawl.page.evaluate(js)}
        except Exception as e:
            return {"error": str(e)}

    async def _steel_await_auth(self, crawl_id: str, timeout_s: int = 600, poll_ms: int = 2000) -> dict:
        with self._lock:
            crawl = self._crawls.get(crawl_id)
        if not crawl:
            return {"authenticated": False, "timed_out": False, "reason": "unknown crawl_id"}
        baseline = {c.get("name") for c in (getattr(crawl, "baseline_cookies", []) or [])}
        deadline = time.time() + timeout_s
        stable_since = None
        while time.time() < deadline:
            crawl.last_active = time.time()  # keepalive - prevents the reaper killing the idle session
            try:
                cookies = await crawl.page.context.cookies()
                url = crawl.page.url or ""
            except Exception:
                cookies, url = [], ""
            if _has_new_session_cookie(baseline, cookies, crawl.scope) and _url_is_authenticated_app(url, crawl.scope):
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= 2.0:
                    return {"authenticated": True, "timed_out": False, "reason": "cookie+url"}
            else:
                stable_since = None
            try:
                await crawl.page.wait_for_timeout(poll_ms)
            except Exception:
                await asyncio.sleep(poll_ms / 1000.0)
        return {"authenticated": False, "timed_out": True, "reason": "timeout"}

    @staticmethod
    async def _extract_links(page) -> list:
        hrefs = await page.eval_on_selector_all("a[href]", _extract_links_expr())
        return list({h for h in hrefs if h.startswith("http")})

    # -- provider contract --------------------------------------------------

    async def get_tools(self) -> list:
        """Return the seven `steel_*` tools as LangChain StructuredTools."""
        from langchain_core.tools import StructuredTool  # noqa: PLC0415

        specs = [
            (
                "steel_crawl_start",
                self._steel_crawl_start,
                "Start a Steel cloud-browser crawl session. Creates a remote Steel "
                "browser, seeds the frontier with `target`, and returns "
                "{crawl_id, frontier, viewer_url}. `scope` is a list of hostnames; "
                "only URLs whose host equals or is a subdomain of a scope entry are "
                "enqueued. Call steel_navigate/steel_frontier/steel_crawl_finish next.",
            ),
            (
                "steel_navigate",
                self._steel_navigate,
                "Navigate to a URL FROM THE CURRENT FRONTIER and auto-enqueue new "
                "in-scope links at depth+1. Only frontier URLs are accepted (use "
                "steel_eval for off-frontier interaction). Returns frontier_view + "
                "{new_links, network_delta, status, blocked, block_type}.",
            ),
            (
                "steel_frontier",
                self._steel_frontier,
                "Inspect the remaining crawl frontier without navigating. Returns "
                "{frontier, visited_count, pages_remaining}.",
            ),
            (
                "steel_crawl_finish",
                self._steel_crawl_finish,
                "Drain the captured network manifest and release the Steel session. "
                "Returns {endpoints:[{method,url,query,body,status}], js_urls:[...]}.",
            ),
            (
                "steel_click",
                self._steel_click,
                "Click an element by CSS selector with a real (trusted) browser event, "
                "then capture resulting links/requests. Use for form submissions and "
                "JS-driven navigation steel_eval cannot trigger.",
            ),
            (
                "steel_eval",
                self._steel_eval,
                "Escape hatch: evaluate arbitrary JavaScript in the current page "
                "context (sync expression that returns a value). Returns {result} or "
                "{error}.",
            ),
            (
                "steel_await_auth",
                self._steel_await_auth,
                "Block until the operator has authenticated in the live Steel session "
                "(a new in-scope session cookie on an in-scope non-login URL, debounced "
                "~2s) or until timeout. Polling keeps the session alive. Returns "
                "{authenticated, timed_out, reason}.",
            ),
        ]
        return [
            StructuredTool.from_function(coroutine=fn, name=name, description=desc)
            for name, fn, desc in specs
        ]
