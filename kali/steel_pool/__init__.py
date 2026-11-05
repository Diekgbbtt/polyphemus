"""The Steel browser pool package.

The package lives in the Kali image beside the Steel CLI and the guard.
It is stdlib-only so the MCP process can import it without side effects.
"""
try:
    from kali.steel_pool.docker_api import DockerAPIError, DockerUnixClient
    from kali.steel_pool.pool import (
        HEALTH_PATH,
        STEEL_API_PRIVATE_PORT,
        PoolReport,
        Worker,
        WorkerRegistry,
        check_worker_health,
        discover_workers,
        parse_worker,
    )
    from kali.steel_pool.store import (
        BrowserSessionRecord,
        CorruptSessionRecord,
        InvalidSessionName,
        SessionStore,
        SessionStoreError,
        validate_name,
    )
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.docker_api import (  # type: ignore[no-redef]
        DockerAPIError,
        DockerUnixClient,
    )
    from steel_pool.pool import (  # type: ignore[no-redef]
        HEALTH_PATH,
        STEEL_API_PRIVATE_PORT,
        PoolReport,
        Worker,
        WorkerRegistry,
        check_worker_health,
        discover_workers,
        parse_worker,
    )
    from steel_pool.store import (  # type: ignore[no-redef]
        BrowserSessionRecord,
        CorruptSessionRecord,
        InvalidSessionName,
        SessionStore,
        SessionStoreError,
        validate_name,
    )

__all__ = [
    "BrowserSessionRecord",
    "CorruptSessionRecord",
    "DockerAPIError",
    "DockerUnixClient",
    "HEALTH_PATH",
    "InvalidSessionName",
    "PoolReport",
    "STEEL_API_PRIVATE_PORT",
    "SessionStore",
    "SessionStoreError",
    "Worker",
    "WorkerRegistry",
    "check_worker_health",
    "discover_workers",
    "parse_worker",
    "validate_name",
]
