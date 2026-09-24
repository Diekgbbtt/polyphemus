"""``mitmdump -s`` entry point: build the capture addon from the environment."""
from __future__ import annotations

from typing import Callable

from mitmproxy import http

from kali.http_history.addon import HttpHistoryAddon
from kali.http_history.config import load_config
from kali.http_history.governor import TargetGovernor
from kali.http_history.registry import SourceRegistry


def mitmproxy_refuse_flow(flow, *, reason_code: str, detail: str) -> None:
    """The production local-refusal adapter: a 503 with the refusal header and NO
    upstream request. It lives here (not in `addon.py`) so unit imports of the
    addon never pull mitmproxy in."""
    flow.response = http.Response.make(
        503,
        b"traffic refused by the polyphemus governor",
        {"X-Polymerhus-Traffic-Refusal": reason_code, "Content-Type": "text/plain"},
    )


def build_addons(
    governor_factory: Callable[[], TargetGovernor] = TargetGovernor,
    refusal_factory: Callable[..., None] = mitmproxy_refuse_flow,
) -> list:
    """Build the addon list. The governor and refusal factories are injectable so
    the E2E-only entry point can inject a fault (or a recorder) without a
    production environment switch."""
    config = load_config()
    # Capture and governance are separate switches but share ONE proxy process:
    # mitmdump must come up when either is enabled, or a capture-off deployment
    # would have no governor at all (spec, Traffic enforcement).
    if not (config.enabled or config.governor_enabled):
        return []
    registry = SourceRegistry(config.registry_path)
    return [
        HttpHistoryAddon(
            root=config.store_root,
            resolver=registry,
            enabled=config.enabled,
            governor_enabled=config.governor_enabled,
            governor=governor_factory(),
            refuse_flow=refusal_factory,
            max_body_bytes=config.max_body_bytes,
        )
    ]


addons = build_addons()
