"""Live guard: a Steel session reaches the internal target (#359, T5, D359-8).

E2E tier. This test talks to the deployed local Steel runtime and the internal
`comfyui` target behind the eval front. It is deliberately NOT gated on a
`skipif`: a live-tier run without the endpoint FAILS with a clear message, so a
missing deployment can never masquerade as green coverage.

Run on a host that reaches the runtime and is on its allowlist:

    STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1 \
    STEEL_LOCAL_TARGET_URL=http://t-1fc05262.target/ \
    STEEL_API_KEY=<key> \
    .venv/bin/python -m pytest tests/e2e/test_steel_local_reachability.py -q -s
"""
from __future__ import annotations

import asyncio
import os

import pytest

ENDPOINT_ENV = "STEEL_BROWSER_API_URL"
TARGET_ENV = "STEEL_LOCAL_TARGET_URL"
# A marker the rendered ComfyUI document carries; not a timing detail.
RENDERED_MARKER = "ComfyUI"


def test_local_steel_session_reaches_the_internal_target():
    endpoint = os.environ.get(ENDPOINT_ENV, "").strip()
    target = os.environ.get(TARGET_ENV, "").strip()
    if not endpoint:
        pytest.fail(
            f"{ENDPOINT_ENV} is required for the local reachability guard. "
            "Set it to the deployed runtime (the CLI form, http://<host>:<port>/v1). "
            "This live test never skips: a missing endpoint is a coverage failure."
        )
    if not target:
        pytest.fail(
            f"{TARGET_ENV} is required for the local reachability guard. "
            "Set it to the internal target URL the Steel browser can resolve "
            "(for example http://t-1fc05262.target/)."
        )
    asyncio.run(_walk(endpoint, target))


async def _walk(endpoint: str, target: str) -> None:
    from playwright.async_api import async_playwright  # noqa: PLC0415
    from steel import Steel  # noqa: PLC0415

    from polymerhus.app.steel_endpoint import steel_browser_api_url  # noqa: PLC0415

    base_url = steel_browser_api_url()
    assert base_url, f"{ENDPOINT_ENV} did not resolve to an SDK base URL"
    # The local runtime ignores the key; the cloud path needs a real one.
    api_key = os.environ.get("STEEL_API_KEY", "").strip() or "local"
    client = Steel(steel_api_key=api_key, base_url=base_url)
    session = client.sessions.create()
    assert session.websocket_url, "the session carries no websocket_url"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(session.websocket_url)
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(target, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_function(
                    "document.title.includes('ComfyUI')", timeout=45000
                )
                assert page.url.rstrip("/") == target.rstrip("/"), (
                    f"final URL {page.url!r} != target {target!r}"
                )
                assert RENDERED_MARKER in await page.title()
            finally:
                await browser.close()
    finally:
        client.sessions.release(session.id)
