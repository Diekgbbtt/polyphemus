"""The shared Steel browser endpoint resolver (#390, D359-4).

One deployment-level value, ``STEEL_BROWSER_API_URL``, names the Steel runtime
the browser capability addresses. Unset (the default) means the remote Steel
cloud servers, byte-identical to an unconfigured deployment. Set means a
self-hosted runtime (for example the deployment on the operator's server).

The value carries the CLI's canonical form, with the ``/v1`` path:
``http://<host>:<port>/v1``. The CLI appends the operation path to the value
(``{base_url}{path}``) and the API mounts every route under ``/v1``.

The Python SDK appends ``/v1`` to ``base_url`` itself, so this resolver returns
the SDK-native origin form: one terminal ``/v1`` and any trailing slash removed.
The resolver is therefore the one place the form is adapted and the single
construction point for the SDK side. No consumer owns the address; the CLI
reads the same variable name natively and ``steel_exec`` injects the global
``--local`` flag when the variable is set.

This module performs no I/O at import (CODING_STANDARD section 6); the value is
read at call time, so a container recreate with a new value is picked up.
"""
from __future__ import annotations

import os

ENV_VAR = "STEEL_BROWSER_API_URL"


def steel_browser_api_url() -> str | None:
    """Return the SDK-native Steel base URL, or ``None`` for the remote cloud.

    Unset or blank returns ``None``. Otherwise the value is stripped, one
    terminal ``/v1`` (the CLI form) is removed, and any trailing slash is
    trimmed, leaving the origin the Python SDK expects.
    """
    value = os.environ.get(ENV_VAR, "").strip().rstrip("/")
    if not value:
        return None
    if value.endswith("/v1"):
        value = value[: -len("/v1")].rstrip("/")
    return value or None


__all__ = ["ENV_VAR", "steel_browser_api_url"]
