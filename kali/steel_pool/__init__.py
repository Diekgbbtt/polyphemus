"""The Steel browser pool package.

The package lives in the Kali image beside the Steel CLI and the guard.
It is stdlib-only so the MCP process can import it without side effects.
"""
try:
    from kali.steel_pool.store import (
        BrowserSessionRecord,
        CorruptSessionRecord,
        InvalidSessionName,
        SessionStore,
        SessionStoreError,
        validate_name,
    )
except ImportError:  # flat deployment beside mcp_server.py
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
    "InvalidSessionName",
    "SessionStore",
    "SessionStoreError",
    "validate_name",
]
