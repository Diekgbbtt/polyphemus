"""``mitmdump -s`` entry point: build the capture addon from the environment."""
from __future__ import annotations

from kali.http_history.addon import HttpHistoryAddon
from kali.http_history.config import load_config
from kali.http_history.governor import TargetGovernor
from kali.http_history.registry import SourceRegistry


def build_addons() -> list:
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
            governor=TargetGovernor(),
            max_body_bytes=config.max_body_bytes,
        )
    ]


addons = build_addons()
