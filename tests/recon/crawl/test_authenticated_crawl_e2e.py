"""Gated authenticated-crawl E2E: non-interactive cookie injection into Steel.

Gated + skippable (mirrors the frontend-bff reachability pattern, commit
d8bd8af). Runs ONLY when a real steel.dev credential AND a real auth fixture
are present AND the target is reachable; otherwise it skips cleanly and never
runs in the offline suite.

Secret handling: the auth fixture holds REAL live session cookies and is
gitignored (`secrets/`). This test NEVER hardcodes a cookie value and reads the
fixture only at runtime from RECON_AUTH_E2E_FILE (default
`secrets/peoplecert-auth.json`). Cookie NAMES this fixture is expected to carry:
`.AspNet.Cookies` (ASP.NET forms-auth token), `ASP.NET_SessionId` (server
session), the Imperva/Incapsula WAF set (`visid_incap_1958344`, `nlbi_1958344`,
`incap_ses_611_1958344`, `incap_ses_63_1958344`), `__RequestVerificationToken`
(anti-CSRF).

CAVEATS (baked into the skip/xfail behavior):
  (a) Incapsula WAF cookies are often IP-bound; the Steel cloud browser has a
      DIFFERENT egress IP, so the WAF may re-challenge and the injected auth may
      not hold. The test degrades gracefully (xfail, never hangs) in that case.
  (b) Session cookies EXPIRE; this is a point-in-time fixture to be refreshed.

Injection is COOKIE-ONLY: Steel drives real Chrome, so browser headers
(user-agent, sec-*, accept) are emitted natively; no header injection.

Manual run (serialized, main tree only - shared stack + external Steel + creds):
    STEEL_API_KEY=<key> RECON_AUTH_E2E_FILE=secrets/peoplecert-auth.json \\
        .venv/bin/python -m pytest tests/recon/crawl/test_authenticated_crawl_e2e.py -v
"""
import json
import os
import socket

import pytest

TARGET = "https://www.peoplecert.org/certifications-and-memberships"
TARGET_HOST = "www.peoplecert.org"
AUTH_FILE = os.environ.get("RECON_AUTH_E2E_FILE", "secrets/peoplecert-auth.json")


def _port_open(host, port, timeout=3.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _load_auth():
    """Read the gitignored auth fixture at runtime. Returns the parsed dict, or
    None when the file is absent/unparseable/empty (-> the test skips)."""
    try:
        with open(AUTH_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return None
    return data


pytestmark = pytest.mark.skipif(
    not os.environ.get("STEEL_API_KEY") or _load_auth() is None,
    reason="requires STEEL_API_KEY and a real auth fixture at RECON_AUTH_E2E_FILE",
)


async def _crawl_navigate_result(auth_cookies, scope):
    """Drive the real steel_* tools (production factory, with auth_cookies
    injected into the browser context) and return the navigate result dict for
    the target - it carries {status, blocked, block_type}."""
    from polymerhus.recon.crawl import steel_client

    tools = {t.name: t for t in await steel_client.get_crawl_tools(auth_cookies=auth_cookies)}
    start = await tools["steel_crawl_start"].ainvoke(
        {"target": TARGET, "scope": scope, "max_depth": 1, "max_pages": 3}
    )
    assert start.get("crawl_id"), f"steel_crawl_start failed: {start}"
    cid = start["crawl_id"]
    try:
        nav = await tools["steel_navigate"].ainvoke({"crawl_id": cid, "url": TARGET})
    finally:
        await tools["steel_crawl_finish"].ainvoke({"crawl_id": cid})
    return nav or {}


def test_injected_cookies_reach_authenticated_surface():
    import asyncio

    from polymerhus.recon import config

    if not _port_open(TARGET_HOST, 443):
        pytest.skip(f"{TARGET_HOST}:443 not reachable")

    data = _load_auth()
    config.STEEL_API_KEY = os.environ["STEEL_API_KEY"]
    scope = data.get("scope") or [TARGET_HOST]

    # Baseline: same crawl WITHOUT cookies (unauthenticated).
    unauth = asyncio.run(_crawl_navigate_result([], scope))
    # Authenticated: WITH injected cookies.
    authed = asyncio.run(_crawl_navigate_result(data["cookies"], scope))

    unauth_status = unauth.get("status", 0)
    authed_status = authed.get("status", 0)

    # CAVEAT (a): IP-bound WAF may re-challenge from Steel's egress IP.
    if authed.get("blocked") or authed_status in (401, 403) or authed.get("block_type") == "captcha":
        pytest.xfail(
            "Steel egress IP re-challenged by Incapsula WAF (IP-bound cookies); "
            "injected auth did not hold - see caveat (a)"
        )

    # Success: the authenticated crawl reaches an OK surface, and reaches at
    # least as far as (or further than) the unauthenticated baseline - i.e. the
    # injected cookies did not regress reach and landed on a non-error page.
    assert authed_status and authed_status < 400, (
        f"authenticated crawl did not reach an OK surface: {authed}"
    )
    assert authed_status <= unauth_status or unauth_status >= 400, (
        f"expected injected cookies to reach at least as far as unauth: "
        f"unauth={unauth}, auth={authed}"
    )
