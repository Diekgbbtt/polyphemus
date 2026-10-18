"""The per-project shared auth store (#220): record shapes (T1), the bucket store (T2), the agent tool (T3)."""

from polymerhus.app.auth.records import (
    AuthInvalidError,
    select_recent_usable_account,
    validate_account,
    validate_overview,
)
from polymerhus.app.auth.store import (
    AuthStore,
    DuplicateAuthError,
    StoreUnavailableError,
)
from polymerhus.app.auth.tool import (
    AUTH_STORE_CONTRACT,
    AUTH_STORE_READ_CONTRACT,
    REDACTED,
    build_auth_store_tool,
    redact_auth_state,
)

__all__ = [
    "AUTH_STORE_CONTRACT",
    "AUTH_STORE_READ_CONTRACT",
    "AuthInvalidError",
    "AuthStore",
    "DuplicateAuthError",
    "REDACTED",
    "StoreUnavailableError",
    "build_auth_store_tool",
    "redact_auth_state",
    "select_recent_usable_account",
    "validate_account",
    "validate_overview",
]
