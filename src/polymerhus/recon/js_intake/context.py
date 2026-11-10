"""Non-sensitive context metadata attached to JavaScript intake records."""

from __future__ import annotations

import hashlib
import json


def input_context_ref(input_asset: dict, asset_context: str) -> str:
    payload = json.dumps(
        {"input_asset": input_asset or {}, "asset_context": asset_context or ""},
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return f"ctx_{hashlib.sha256(payload).hexdigest()[:20]}"


def auth_scope(extra: dict) -> tuple[str, str | None]:
    auth_ref = (extra or {}).get("auth_account")
    authenticated = bool(
        auth_ref or extra.get("auth_context") or extra.get("steel_profile")
    )
    return (
        "authenticated" if authenticated else "anonymous",
        auth_ref if isinstance(auth_ref, str) else None,
    )
