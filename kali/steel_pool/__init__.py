"""The Steel browser pool package.

The package lives in the Kali image beside the Steel CLI and the guard.
It is stdlib-only so the MCP process can import it without side effects.
"""
try:
    from kali.steel_pool.api import WorkerAPI, WorkerAPIError
    from kali.steel_pool.cli import (
        DEFAULT_INACTIVITY_TIMEOUT_MS,
        DEFAULT_SESSION_TIMEOUT_MS,
        CaptureError,
        CapturedContext,
        CliError,
        CliSession,
        RestoreError,
        RestoreReport,
        SteelCli,
    )
    from kali.steel_pool.docker_api import DockerAPIError, DockerUnixClient
    from kali.steel_pool.lease import (
        DEFAULT_HEARTBEAT_S,
        DEFAULT_LEASE_TTL_S,
        DEFAULT_POOL_WAIT_S,
        EndReport,
        LeaseError,
        LeaseManager,
        LeaseView,
        PoolExhausted,
    )
    from kali.steel_pool.pool import (
        HEALTH_PATH,
        PUBLIC_PORT_BASE,
        STEEL_API_PRIVATE_PORT,
        PoolReport,
        Worker,
        WorkerRegistry,
        check_worker_health,
        discover_workers,
        parse_worker,
    )
    from kali.steel_pool.proxy import ProxyError, WorkerProxy
    from kali.steel_pool.store import (
        BrowserSessionRecord,
        CorruptSessionRecord,
        InvalidSessionName,
        SessionStore,
        SessionStoreError,
        validate_name,
    )
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.api import WorkerAPI, WorkerAPIError  # type: ignore[no-redef]
    from steel_pool.cli import (  # type: ignore[no-redef]
        DEFAULT_INACTIVITY_TIMEOUT_MS,
        DEFAULT_SESSION_TIMEOUT_MS,
        CaptureError,
        CapturedContext,
        CliError,
        CliSession,
        RestoreError,
        RestoreReport,
        SteelCli,
    )
    from steel_pool.docker_api import (  # type: ignore[no-redef]
        DockerAPIError,
        DockerUnixClient,
    )
    from steel_pool.lease import (  # type: ignore[no-redef]
        DEFAULT_HEARTBEAT_S,
        DEFAULT_LEASE_TTL_S,
        DEFAULT_POOL_WAIT_S,
        EndReport,
        LeaseError,
        LeaseManager,
        LeaseView,
        PoolExhausted,
    )
    from steel_pool.pool import (  # type: ignore[no-redef]
        HEALTH_PATH,
        PUBLIC_PORT_BASE,
        STEEL_API_PRIVATE_PORT,
        PoolReport,
        Worker,
        WorkerRegistry,
        check_worker_health,
        discover_workers,
        parse_worker,
    )
    from steel_pool.proxy import ProxyError, WorkerProxy  # type: ignore[no-redef]
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
    "CaptureError",
    "CapturedContext",
    "CliError",
    "CliSession",
    "CorruptSessionRecord",
    "DEFAULT_HEARTBEAT_S",
    "DEFAULT_INACTIVITY_TIMEOUT_MS",
    "DEFAULT_LEASE_TTL_S",
    "DEFAULT_POOL_WAIT_S",
    "DEFAULT_SESSION_TIMEOUT_MS",
    "DockerAPIError",
    "DockerUnixClient",
    "EndReport",
    "HEALTH_PATH",
    "InvalidSessionName",
    "LeaseError",
    "LeaseManager",
    "LeaseView",
    "PoolExhausted",
    "PoolReport",
    "ProxyError",
    "PUBLIC_PORT_BASE",
    "RestoreError",
    "RestoreReport",
    "STEEL_API_PRIVATE_PORT",
    "SessionStore",
    "SessionStoreError",
    "SteelCli",
    "Worker",
    "WorkerAPI",
    "WorkerAPIError",
    "WorkerProxy",
    "WorkerRegistry",
    "check_worker_health",
    "discover_workers",
    "parse_worker",
    "validate_name",
]
