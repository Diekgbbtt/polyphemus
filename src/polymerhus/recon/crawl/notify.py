"""Best-effort out-of-band operator notification for interactive auth.

When an agentic crawl precreates a Steel session and blocks on a human login
(steel_await_auth), the operator has only the crawl session window to notice
and complete it. This module POSTs a "login required" message to a configured
Discord (or any Discord-compatible) webhook the instant that happens.

Env-driven and fail-open, exactly like the Langfuse tracing module: if
DISCORD_WEBHOOK_URL is unset, notify_awaiting_auth is a silent no-op, and any
error POSTing is swallowed so a notification blip never disturbs the crawl.
The webhook URL is a SECRET - it lives only in the environment, never in code.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_STEEL_DASHBOARD_URL = "https://app.steel.dev/sessions"


def notify_awaiting_auth(
    run_id: str,
    phase: int,
    job: str,
    viewer_url: str,
    *,
    webhook_url: str | None = None,
    urlopen=urllib.request.urlopen,
) -> bool:
    """POST a 'login required' notification to the configured webhook.

    `webhook_url` defaults to the DISCORD_WEBHOOK_URL env var. `urlopen` is
    injectable so tests assert the payload without live HTTP. Returns True iff
    a POST was attempted and returned 2xx; False if no webhook is configured or
    the POST failed. Never raises.
    """
    url = webhook_url if webhook_url is not None else os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        return False
    content = (
        f"\U0001F510 **Recon login required** - run `{run_id}` (phase {phase}, {job}).\n"
        f"Complete the interactive login in the Steel session viewer:\n{viewer_url}\n"
        f"Steel sessions dashboard: {_STEEL_DASHBOARD_URL}"
    )
    data = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310 - fixed, operator-configured webhook
            status = getattr(resp, "status", 200)
            return 200 <= status < 300
    except Exception as exc:  # noqa: BLE001 - notification is best-effort, never disturb the crawl
        # Log the exception TYPE only, never exc_info: a urllib HTTPError/URLError
        # can embed the (secret) webhook URL in its message/traceback.
        logger.warning("awaiting-auth webhook notify failed for run %s (%s)", run_id, type(exc).__name__)
        return False
