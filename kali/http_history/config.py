"""Environment-driven configuration for the capture plane and store."""
from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be a boolean, got {raw!r}")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else float(raw)


@dataclass(frozen=True)
class HttpHistoryConfig:
    store_root: str = "/data"
    enabled: bool = True
    max_body_bytes: int = 5 * 1024 * 1024
    pool_size: int = 8
    ttl_s: int = 900
    acquire_timeout_s: float = 30.0
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8080
    registry_path: str = "/run/kali-http/registry.sqlite3"
    retention_s: int = 0  # 0 disables age-based retention
    project_max_bytes: int = 0  # 0 disables the per-project byte cap


def load_config() -> HttpHistoryConfig:
    return HttpHistoryConfig(
        store_root=os.environ.get("KALI_HTTP_HISTORY_ROOT", "/data"),
        enabled=_env_bool("KALI_HTTP_CAPTURE_ENABLED", True),
        max_body_bytes=_env_int("KALI_HTTP_MAX_BODY_BYTES", 5 * 1024 * 1024),
        pool_size=max(1, min(256, _env_int("KALI_HTTP_NAMESPACE_POOL", 8))),
        ttl_s=_env_int("KALI_HTTP_LEASE_TTL_S", 900),
        acquire_timeout_s=_env_float("KALI_HTTP_ACQUIRE_TIMEOUT_S", 30.0),
        proxy_host=os.environ.get("KALI_HTTP_PROXY_HOST", "127.0.0.1"),
        proxy_port=_env_int("KALI_HTTP_PROXY_PORT", 8080),
        registry_path=os.environ.get(
            "KALI_HTTP_REGISTRY_PATH", "/run/kali-http/registry.sqlite3"
        ),
        retention_s=_env_int("KALI_HTTP_RETENTION_S", 0),
        project_max_bytes=_env_int("KALI_HTTP_PROJECT_MAX_BYTES", 0),
    )
