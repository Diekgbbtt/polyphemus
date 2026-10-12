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
    # Fuzzing/param-mining capture gate (0 disables that half). A flow whose
    # request shape trips either bound is NOT recorded: it is scanner noise,
    # never the navigational surface, and its URL is what blows up context.
    fuzz_max_query_params: int = 30
    fuzz_max_path_segment: int = 80
    # The recon toolchain's own hosts (comma-separated suffixes). Traffic to
    # these inside a lease is the container's own tooling, never the target's
    # scope, so it is not recorded.
    exclude_host_suffixes: tuple[str, ...] = ("pdtm.sh",)
    pool_size: int = 8
    ttl_s: int = 900
    acquire_timeout_s: float = 30.0
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8080
    registry_path: str = "/run/kali-http/registry.sqlite3"
    retention_s: int = 0  # 0 disables age-based retention
    # 0 disables the cap. Non-zero by default (see docker-compose.yml): with
    # capture ON for every recon pod the store would otherwise grow forever.
    project_max_bytes: int = 1024 * 1024 * 1024
    # The trim runs on the exec path, so it must not pay a full store scan per
    # command: at most one `enforce_limits` per project per this many seconds.
    enforce_interval_s: int = 60


def load_config() -> HttpHistoryConfig:
    return HttpHistoryConfig(
        store_root=os.environ.get("KALI_HTTP_HISTORY_ROOT", "/data"),
        enabled=_env_bool("KALI_HTTP_CAPTURE_ENABLED", True),
        max_body_bytes=_env_int("KALI_HTTP_MAX_BODY_BYTES", 5 * 1024 * 1024),
        fuzz_max_query_params=_env_int("KALI_HTTP_FUZZ_MAX_QUERY_PARAMS", 30),
        fuzz_max_path_segment=_env_int("KALI_HTTP_FUZZ_MAX_PATH_SEGMENT", 80),
        exclude_host_suffixes=tuple(
            s.strip().lower()
            for s in os.environ.get("KALI_HTTP_EXCLUDE_HOSTS", "pdtm.sh").split(",")
            if s.strip()
        ),
        pool_size=max(1, min(256, _env_int("KALI_HTTP_NAMESPACE_POOL", 8))),
        ttl_s=_env_int("KALI_HTTP_LEASE_TTL_S", 900),
        acquire_timeout_s=_env_float("KALI_HTTP_ACQUIRE_TIMEOUT_S", 30.0),
        proxy_host=os.environ.get("KALI_HTTP_PROXY_HOST", "127.0.0.1"),
        proxy_port=_env_int("KALI_HTTP_PROXY_PORT", 8080),
        registry_path=os.environ.get(
            "KALI_HTTP_REGISTRY_PATH", "/run/kali-http/registry.sqlite3"
        ),
        retention_s=_env_int("KALI_HTTP_RETENTION_S", 0),
        project_max_bytes=_env_int("KALI_HTTP_PROJECT_MAX_BYTES", 1024 * 1024 * 1024),
        enforce_interval_s=max(0, _env_int("KALI_HTTP_LIMIT_ENFORCE_INTERVAL_S", 60)),
    )
