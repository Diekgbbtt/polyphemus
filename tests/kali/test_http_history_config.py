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
    # Retention stays 0 (age-based deletion would drop evidence with no disk
    # pressure to justify it) but the byte cap is armed and the trimmer is
    # throttled rather than run on every single exec.
    assert cfg.retention_s == 0
    assert cfg.project_max_bytes > 0
    assert cfg.enforce_interval_s > 0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("KALI_HTTP_HISTORY_ROOT", "/tmp/x")
    monkeypatch.setenv("KALI_HTTP_CAPTURE_ENABLED", "false")
    monkeypatch.setenv("KALI_HTTP_MAX_BODY_BYTES", "1234")
    monkeypatch.setenv("KALI_HTTP_NAMESPACE_POOL", "3")
    monkeypatch.setenv("KALI_HTTP_LEASE_TTL_S", "42")
    monkeypatch.setenv("KALI_HTTP_PROJECT_MAX_BYTES", "999")
    monkeypatch.setenv("KALI_HTTP_LIMIT_ENFORCE_INTERVAL_S", "7")
    cfg = load_config()
    assert cfg.store_root == "/tmp/x"
    assert cfg.enabled is False
    assert cfg.max_body_bytes == 1234
    assert cfg.pool_size == 3
    assert cfg.ttl_s == 42
    assert cfg.project_max_bytes == 999
    assert cfg.enforce_interval_s == 7
