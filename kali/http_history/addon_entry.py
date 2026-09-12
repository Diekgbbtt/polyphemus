"""``mitmdump -s`` entry point: build the capture addon from the environment."""
from __future__ import annotations

from kali.http_history.addon import HttpHistoryAddon
from kali.http_history.config import load_config
from kali.http_history.registry import SourceRegistry


def build_addons() -> list:
    config = load_config()
    if not config.enabled:
        return []
    registry = SourceRegistry(config.registry_path)
    return [
        HttpHistoryAddon(
            root=config.store_root,
            resolver=registry,
            max_body_bytes=config.max_body_bytes,
        )
    ]


addons = build_addons()
