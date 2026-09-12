"""Component health for the Kali container (#196).

Distinguishes the five failure domains the spec requires be reported apart:
MCP readiness, proxy readiness, transparent-routing readiness, namespace-pool
readiness and store writability. Exit 0 iff the domains required for the
configured mode are healthy.
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-capture", action="store_true")
    args = parser.parse_args(argv)

    from kali.http_history.config import load_config
    from kali.http_history.namespaces import NamespaceLeaseManager, SubprocessBackend
    from kali.http_history.registry import SourceRegistry
    from kali.http_history.service import HttpHistoryService

    config = load_config()
    registry = SourceRegistry(config.registry_path)
    manager = NamespaceLeaseManager(
        registry=registry,
        pool_size=config.pool_size,
        ttl_s=config.ttl_s,
        acquire_timeout_s=config.acquire_timeout_s,
        backend=SubprocessBackend(proxy_port=config.proxy_port),
    )
    status = HttpHistoryService(
        config=config, registry=registry, lease_manager=manager
    ).proxy_status()

    require_capture = args.require_capture or config.enabled
    ok = bool(status["mcp"]["ok"] and status["store"]["ok"])
    if require_capture:
        ok = ok and bool(status["proxy"]["ok"] and status["routing"]["ok"])
    status["ok"] = ok
    print(json.dumps(status))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
