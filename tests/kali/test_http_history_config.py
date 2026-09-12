"""Environment-driven capture configuration."""
from __future__ import annotations

import os

from kali.http_history.config import load_config


def test_defaults_are_production_sane(monkeypatch):
    for key in list(os.environ):
        if key.startswith("KALI_HTTP_"):
            monkeypatch.delenv(key)
    cfg = load_config()
    assert cfg.store_root == "/data"
    assert cfg.enabled is True
    assert cfg.max_body_bytes > 0
    assert 1 <= cfg.pool_size <= 256


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("KALI_HTTP_HISTORY_ROOT", "/tmp/x")
    monkeypatch.setenv("KALI_HTTP_CAPTURE_ENABLED", "false")
    monkeypatch.setenv("KALI_HTTP_MAX_BODY_BYTES", "1234")
    monkeypatch.setenv("KALI_HTTP_NAMESPACE_POOL", "3")
    monkeypatch.setenv("KALI_HTTP_LEASE_TTL_S", "42")
    cfg = load_config()
    assert cfg.store_root == "/tmp/x"
    assert cfg.enabled is False
    assert cfg.max_body_bytes == 1234
    assert cfg.pool_size == 3
    assert cfg.ttl_s == 42
