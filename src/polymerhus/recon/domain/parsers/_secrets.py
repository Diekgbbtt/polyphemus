"""Legacy jsluice secret canonicalization; raw values remain transient."""
import json


def extract_secret_value(entry: dict) -> str | None:
    """The sensitive value to hash for identity. Real jsluice nests it under a
    `data` OBJECT (e.g. `{"key": "...", "secret": "..."}`) - NOT a top-level
    `secret` string, which the tool never emits (the old code read the latter and
    so dropped every real finding). Prefer `data.secret`, then `data.key`, then a
    canonical serialisation of the whole `data` object; fall back to a legacy
    top-level `secret` string for backward compatibility. The value is only ever
    HASHED (below), never stored, so serialising `data` here does not leak it."""
    data = entry.get("data")
    if isinstance(data, dict) and data:
        for key in ("secret", "key", "value", "token"):
            v = data.get(key)
            if isinstance(v, str) and v:
                return v
        # No known sub-field: hash a stable serialisation so distinct findings
        # still get distinct identities (never store the object itself).
        return json.dumps(data, sort_keys=True)
    if isinstance(data, str) and data:
        return data
    legacy = entry.get("secret")  # backward-compat with the pre-`data` shape
    return legacy if isinstance(legacy, str) and legacy else None
