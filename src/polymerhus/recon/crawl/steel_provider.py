"""In-process Steel browser crawl-tool provider (async port).

This is the concrete provider `steel_client._default_client_factory()` returns.
It is an IN-PROCESS provider driven from the crawl ReAct loop's asyncio event
loop (ASYNC Playwright API - the sync API cannot run inside a running event
loop).

Architecture (operator correction, SP4; session-only #395 D20): the provider
opens a Steel browser session through the SDK and drives it with Playwright
connected over CDP at the session's own `websocket_url`:

    ws://<runtime host>:<port>/

When the SDK session carries no `websocket_url`, it falls back to the SDK's
connect pattern, addressed by `STEEL_API_KEY`:

    wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<session id>

Configuration is either `config.STEEL_API_KEY` or `STEEL_BROWSER_API_URL`;
runtime selection belongs below this provider. There is no MCP host URL. The
address comes from the shared `STEEL_BROWSER_API_URL` resolver (#390, D359-4):
unset keeps the SDK default, set passes the resolver's SDK-native origin as
`base_url` on session create and release (D359-5).

The create options are deterministic: no random user agent, viewport, region,
or stealth bundle. The four durable state fields are restored from the account
state file. Auth material (cookies, scoped headers, storage tokens) is merged
into that state, and the first navigation runs the replication gate.
The provider captures the live state before release.

Contract: `SteelCrawlProvider.get_tools()` returns a list of LangChain
`StructuredTool`s, one per name in `steel_client.CRAWL_TOOL_NAMES`. Each tool is
`await tool.ainvoke(dict)`-able and returns a plain dict (normalized downstream
by `crawl_agentic._payload_from_tool_result`), and the list is
`llm.bind_tools(...)`-able.

No DinD, no `WEBAPP_API_URL`/`INTERNAL_API_KEY` key resolution, no webapp
Resume-flag polling, no `user_id` -> key lookup (the `user_id` arg is kept on
`steel_crawl_start` only because the ReAct loop injects it; it is ignored).
The crawl-session registry is INSTANCE-scoped (one provider per crawl job)
rather than a module global, so concurrent jobs never share state.

Runtime dependency: `playwright` and `steel-sdk` must be importable in the agent
image (the `redamon-agent` base provides both). They are imported LAZILY inside
the tool coroutines so importing this module never requires them - a build
without them degrades to `SteelProviderUnavailable` at the factory seam, not an
import crash.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
import uuid
from urllib.parse import parse_qsl, urlparse

from polymerhus.app.steel_endpoint import steel_browser_api_url
from polymerhus.app.steel_session_state import (
    SteelStateError,
    load_session_context,
    save_session_context,
    to_sdk_session_context,
)
from polymerhus.recon import config
from polymerhus.recon.crawl.auth_gate import evaluate_auth_gate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scope predicate (the crawl-frontier / recorded-asset scope filter)
# ---------------------------------------------------------------------------


def _registrable_in_scope(host: str, scope: list) -> bool:
    """Return True if host is equal to or a subdomain of any entry in scope."""
    host = (host or "").lower()
    return any(host == s.lower() or host.endswith("." + s.lower()) for s in scope)


# Non-HTML asset extensions the crawl frontier must never enqueue: only HTML
# documents belong in the navigation frontier (Change B, content-type fold).
_NON_HTML_EXTS = frozenset(
    {
        "js", "mjs", "cjs", "css", "map", "json", "xml",
        "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "avif", "bmp",
        "woff", "woff2", "ttf", "otf", "eot",
        "pdf", "zip", "gz", "tar",
        "mp4", "webm", "mp3", "wav",
        "wasm", "txt", "csv",
    }
)


def _looks_non_html(url: str) -> bool:
    """True when the URL path's final segment ends with a known non-HTML asset
    extension. Query/fragment are ignored (parsed off via urlparse)."""
    try:
        path = urlparse(url or "").path or ""
    except Exception:
        return False
    last = path.rsplit("/", 1)[-1]
    if "." not in last:
        return False
    ext = last.rsplit(".", 1)[-1].lower()
    return ext in _NON_HTML_EXTS


def _is_html_content_type(ct: str | None) -> bool:
    """True when the response Content-Type is HTML (or unknown). Fails OPEN: an
    absent/unparseable content-type is allowed so we never drop a real page."""
    if not ct:
        return True
    ct = ct.lower()
    return "text/html" in ct or "application/xhtml" in ct


# ---------------------------------------------------------------------------
# Session options and auth-material merge (sessions only, #395 D20)
# ---------------------------------------------------------------------------


def _session_opts(use_proxy: bool, session_context: dict | None = None) -> dict:
    """Return deterministic `sessions.create` kwargs.

    The tool never randomises the user agent, viewport, region, or stealth.
    The only variables are the caller's proxy choice and the restored
    application context. Runtime-native fingerprint jitter remains a platform
    behaviour."""
    opts: dict = {"use_proxy": use_proxy, "headless": False}
    if session_context:
        opts["session_context"] = to_sdk_session_context(session_context)
    return opts


def _cookie_key(cookie: dict) -> tuple:
    return (
        cookie.get("name"),
        cookie.get("domain") or "",
        cookie.get("path") or "",
        cookie.get("url") or "",
    )


def _merge_browser_auth(
    session_context: dict | None,
    browser_auth: dict | None,
    default_url: str | None = None,
) -> dict:
    """Merge auth material into the stored application context.

    Auth cookies replace a same-key state cookie. A cookieless domain/url is
    anchored to `default_url` so the runtime can place it. Storage-located
    tokens merge per origin and replace same-named state keys. Header material
    is not part of `sessionContext`; the provider scopes it at the browser
    context."""
    context = dict(session_context or {})
    material = browser_auth or {}

    cookies: list = []
    by_key: dict[tuple, int] = {}
    for cookie in list(context.get("cookies") or []) + list(material.get("cookies") or []):
        if not isinstance(cookie, dict):
            continue
        name, value = cookie.get("name"), cookie.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if default_url and not cookie.get("domain") and not cookie.get("url"):
            cookie = {**cookie, "url": default_url}
        key = _cookie_key(cookie)
        if key in by_key:
            cookies[by_key[key]] = cookie
        else:
            by_key[key] = len(cookies)
            cookies.append(cookie)
    if cookies:
        context["cookies"] = cookies

    storage = material.get("storage")
    if isinstance(storage, dict) and storage:
        local = dict(context.get("localStorage") or {})
        for origin, values in storage.items():
            if not isinstance(origin, str) or not isinstance(values, dict):
                continue
            bucket = dict(local.get(origin) or {})
            bucket.update(values)
            local[origin] = bucket
        context["localStorage"] = local

    return context


def _extract_links_expr() -> str:
    return "els => els.map(a => a.href)"


# ---------------------------------------------------------------------------

class _Crawl:
    """Holds all mutable state for a single Steel crawl session (async page)."""

    def __init__(self, crawl_id, scope, max_depth, max_pages, session, browser,
                 page, pw, api_key, client=None):
        self.id = crawl_id
        self.scope = scope
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.session = session
        self.browser = browser
        self.page = page
        self.pw = pw
        self.api_key = api_key
        self.client = client
        self.started = time.time()
        self.last_active = time.time()
        self.current_depth = 0
        self.visited: set = set()
        self.queued: set = set()
        self.frontier: list = []
        self.pages_done = 0
        self.requests: list = []
        self.responses: dict = {}
        self.auth_required = False
        self.auth_checked = False
        self.auth_result: dict | None = None
        self._req_lock = threading.Lock()
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
            if _looks_non_html(u):
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


def _steel_client_kwargs(api_key: str, base_url: str | None) -> dict:
    """Return the `Steel(...)` kwargs.

    An omitted `base_url` leaves the SDK default (the cloud) untouched. An
    empty key is omitted too: a local deployment is keyless and authenticated
    by its address (#395, D359-12).
    """
    kwargs: dict = {}
    if api_key:
        kwargs["steel_api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs


def _cdp_connect_url(session, api_key: str) -> str:
    """Return the CDP connect URL for one SDK session.

    The session's own `websocket_url` names the runtime the SDK just created,
    so it is correct for both the cloud and a self-hosted runtime. The cloud
    pattern is the fallback for an SDK response that omits the field.
    """
    return getattr(session, "websocket_url", None) or (
        f"wss://connect.steel.dev?apiKey={api_key}&sessionId={session.id}"
    )


def _create_steel_session(
    api_key: str,
    use_proxy: bool,
    base_url: str | None = None,
    session_context: dict | None = None,
):
    """Create a Steel session (SYNC SDK).

    Runs off the event loop via `asyncio.to_thread`. Returns the client and the
    session object. `base_url` addresses a self-hosted runtime; None keeps the
    SDK default (the cloud). A rejected restore fails loudly: silently
    dropping state would turn an authenticated crawl into an anonymous one
    while claiming otherwise."""
    from steel import Steel  # noqa: PLC0415

    client = Steel(**_steel_client_kwargs(api_key, base_url))
    return client, client.sessions.create(**_session_opts(use_proxy, session_context))


class SteelCrawlProvider:
    """In-process provider exposing the six `steel_*` crawl tools.

    One instance drives one crawl job. `get_tools()` returns LangChain
    `StructuredTool`s bound to this instance's crawl registry.

    The Steel runtime address is the shared `STEEL_BROWSER_API_URL` value,
    resolved once at construction. Unset leaves the SDK default (the steel.dev
    cloud). Set addresses a self-hosted runtime through the SDK `base_url`.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session_lifetime_s: int | None = None,
        steel_state: str | None = None,
        browser_auth: dict | None = None,
        base_url: str | None = None,
    ):
        self._api_key = api_key if api_key is not None else config.STEEL_API_KEY
        # Shared deployment address (#390, D359-5). None means "unset", which
        # leaves the SDK default (the cloud) in place; an explicit argument
        # exists for tests and for a future caller that resolves it elsewhere.
        self._base_url = base_url if base_url is not None else steel_browser_api_url()
        self._session_lifetime_s = (
            session_lifetime_s
            if session_lifetime_s is not None
            else int(getattr(config, "CRAWL_JOB_TIMEOUT_S", 480))
        )
        # The resolved per-account state file, and the feed-projected browser
        # material (cookies, scoped headers, storage-located tokens). Empty
        # for an anonymous crawl.
        self._steel_state = steel_state or None
        self._browser_auth = dict(browser_auth or {})
        self._crawls: dict[str, _Crawl] = {}
        self._lock = threading.Lock()

    # -- lifecycle helpers --------------------------------------------------

    async def _finish(self, crawl_id: str) -> dict:
        """Build manifest, close browser, stop Playwright, release Steel session."""
        with self._lock:
            crawl = self._crawls.pop(crawl_id, None)
        if not crawl:
            return {"endpoints": [], "js_urls": []}
        auth_failed = bool(
            crawl.auth_result is not None
            and not crawl.auth_result.get("authenticated"))
        manifest = {"endpoints": [], "js_urls": []} if auth_failed else _build_manifest(crawl)
        await self._capture_state(crawl)
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
                Steel(**_steel_client_kwargs(crawl.api_key, self._base_url)).sessions.release,
                crawl.session.id,
            )
        except Exception:
            pass
        return manifest

    async def _capture_state(self, crawl: _Crawl) -> None:
        """Capture the live context and write it to the account's state file.

        A capture failure never cancels the release. The state carries secrets,
        so neither the context nor the failure detail is logged."""
        if not self._steel_state or crawl.client is None:
            return
        if crawl.auth_required and not (
            crawl.auth_checked
            and crawl.auth_result is not None
            and crawl.auth_result.get("authenticated")
        ):
            # Never overwrite a good account state with an unauthenticated or
            # untested context.
            return
        try:
            context = await asyncio.to_thread(
                crawl.client.sessions.context, crawl.session.id)
            await asyncio.to_thread(
                save_session_context, self._steel_state, context)
        except Exception:  # noqa: BLE001 - release must still run
            logger.warning(
                "steel provider: state capture failed for session %s; "
                "releasing without a state update", crawl.session.id)

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
        if not self._api_key and not self._base_url:
            return {"error": "steel_runtime_unconfigured"}

        from playwright.async_api import async_playwright  # noqa: PLC0415

        await self._reap_expired()
        session_context = None
        if self._steel_state:
            try:
                session_context = load_session_context(self._steel_state)
            except SteelStateError:
                logger.warning(
                    "steel provider: state %s is unreadable; continuing with "
                    "auth material only", self._steel_state)
        session_context = _merge_browser_auth(
            session_context, self._browser_auth, target)
        client, session = await asyncio.to_thread(
            _create_steel_session,
            self._api_key,
            use_proxy,
            self._base_url,
            session_context or None,
        )
        p = await async_playwright().start()
        cdp_url = _cdp_connect_url(session, self._api_key)
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            ctx = browser.contexts[0]
            await self._install_scoped_headers(ctx, target)
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
        crawl = _Crawl(crawl_id, scope, max_depth, max_pages, session, browser,
                       page, p, self._api_key, client=client)
        crawl.auth_required = bool(self._browser_auth)
        crawl.enqueue([target], depth=0)
        with self._lock:
            self._crawls[crawl_id] = crawl
        return {
            "crawl_id": crawl_id,
            "frontier": list(crawl.frontier),
            "viewer_url": getattr(session, "session_viewer_url", ""),
            "auth_required": crawl.auth_required,
        }

    async def _install_scoped_headers(self, ctx, target: str) -> None:
        """Attach auth headers only to requests for the target origin.

        Global extra headers would leak token material to third-party
        origins the page contacts. The route interceptor leaves every other
        origin untouched."""
        headers = self._browser_auth.get("headers")
        if not isinstance(headers, dict) or not headers:
            return
        target_netloc = urlparse(target).netloc.lower()

        async def _add_headers(route):
            request = route.request
            if urlparse(request.url).netloc.lower() == target_netloc:
                merged = dict(request.headers)
                merged.update({str(k): str(v) for k, v in headers.items()})
                await route.continue_(headers=merged)
            else:
                await route.continue_()

        await ctx.route("**/*", _add_headers)

    async def _check_auth_gate(self, crawl: _Crawl, status: int) -> None:
        """Evaluate the gate once, on the first authenticated navigation."""
        if not crawl.auth_required or crawl.auth_checked:
            return
        crawl.auth_checked = True
        local_storage: dict = {}
        try:
            current = await crawl.page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))")
            parsed = urlparse(crawl.page.url or "")
            origin = f"{parsed.scheme}://{parsed.netloc}"
            local_storage = {origin: current if isinstance(current, dict) else {}}
        except Exception:
            local_storage = {}
        crawl.auth_result = evaluate_auth_gate(
            status=status,
            final_url=crawl.page.url,
            login_url=self._browser_auth.get("login_url"),
            storage=self._browser_auth.get("storage"),
            local_storage=local_storage,
        )

    async def _steel_navigate(self, crawl_id: str, url: str, wait_ms: int = 800) -> dict:
        with self._lock:
            crawl = self._crawls.get(crawl_id)
        if not crawl:
            return {"error": "unknown crawl_id"}
        if crawl.pages_done >= crawl.max_pages:
            return {"error": "page_cap_reached", **crawl.frontier_view()}
        if crawl.auth_checked and crawl.auth_result and not crawl.auth_result.get("authenticated"):
            return {"error": "auth_replication_failed",
                    "auth": crawl.auth_result, **crawl.frontier_view()}
        # No navigation allowlist: the agent may navigate to ANY url its
        # reasoning chooses, on or off the frontier. The operator prefers to
        # trust the agent's navigation judgment; scope is enforced on what gets
        # RECORDED (the `enqueue` scope filter on discovered links below, plus
        # the curator's out-of-scope BaseURL drop), never by refusing a
        # navigation. Dropping the old exact-string frontier gate also removes
        # the fragility where a semantically-in-scope URL variant (e.g. a
        # trailing-slash form of the target) was rejected as `url_not_in_frontier`
        # and left the anonymous crawl stuck on about:blank.
        crawl.last_active = time.time()
        depth = next((f["depth"] for f in crawl.frontier if f["url"] == url), 0)
        crawl.current_depth = depth
        crawl.frontier = [f for f in crawl.frontier if f["url"] != url]
        crawl.queued.discard(url)
        crawl.visited.add(url)
        crawl.pages_done += 1

        blocked, block_type, status = False, None, 0
        is_html = True
        try:
            resp = await crawl.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            status = resp.status if resp else 0
            if status in (401, 403, 404):
                blocked = status in (401, 403)
                block_type = str(status)
            if "captcha" in (crawl.page.url or "").lower():
                blocked, block_type = True, "captcha"
            # Content-Type fold: only extract/enqueue links from HTML responses.
            # Best-effort - a missing/odd header must never raise (fail open).
            if resp is not None:
                try:
                    headers = resp.headers
                    ct = None
                    if isinstance(headers, dict):
                        ct = next(
                            (v for k, v in headers.items() if str(k).lower() == "content-type"),
                            None,
                        )
                    is_html = _is_html_content_type(ct)
                except Exception:
                    is_html = True
        except Exception as e:
            return {"error": str(e), **crawl.frontier_view()}

        await self._check_auth_gate(crawl, status)
        if crawl.auth_result is not None and not crawl.auth_result.get("authenticated"):
            return {"error": "auth_replication_failed",
                    "auth": crawl.auth_result, **crawl.frontier_view()}

        new_links: list = []
        if status not in (401, 403, 404) and is_html:
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

    @staticmethod
    async def _extract_links(page) -> list:
        hrefs = await page.eval_on_selector_all("a[href]", _extract_links_expr())
        return list({h for h in hrefs if h.startswith("http")})

    # -- provider contract --------------------------------------------------

    async def get_tools(self) -> list:
        """Return the six `steel_*` tools as LangChain StructuredTools."""
        from langchain_core.tools import StructuredTool  # noqa: PLC0415

        specs = [
            (
                "steel_crawl_start",
                self._steel_crawl_start,
                "Start a Steel browser crawl session. Creates a browser, seeds "
                "the frontier with `target`, and returns "
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
        ]
        return [
            StructuredTool.from_function(coroutine=fn, name=name, description=desc)
            for name, fn, desc in specs
        ]
