"""The target-front availability contract for hunting probes (#323).

The shared target front (`ph-eval-front`) is an nginx reverse proxy in front of
a target's published port. When the upstream is unavailable - down, restarting,
or overloaded - nginx answers `502 Bad Gateway` (and `503` / `504` for the
related gateway conditions). That is EXPECTED front behaviour, not a verdict
about any route: a `502` says "the backend is not answering right now", never
"this path does not exist".

A live comfyui hunt proved the cost of conflating the two. A hunter probe hit
ComfyUI-Manager's `/api/manager/reboot`, which `os.execv`s the ComfyUI process;
the front then returned `502` for the ~2-minute restart window. The hunter read
the `502` as route-absence and LOOPED, re-probing `/users`, `/queue`, `/`,
`/system_stats` and more, burning turns against a target that was simply down.
Recon's own L0 `httpx` probe had recorded the identical 502 page and interpreted
it correctly ("a reverse proxy whose upstream backend is currently unreachable").

This module is the ENV-FREE single home of the rule (the `conciseness.py`
pattern, #292): the hunter's `exec` tool description and the hunting role
prompts embed `TARGET_UNAVAILABLE_DIRECTIVE` verbatim, and the pod's defence
classifier reuses `TARGET_UNAVAILABLE_STATUSES`, so the classification of a
target-front `5xx` can never drift between the tool, the prompts, and the pod.
"""
from __future__ import annotations

# The gateway-family statuses that mean "the upstream is not answering", not
# "the route is absent": 502 Bad Gateway, 503 Service Unavailable, 504 Gateway
# Timeout. A persistent front returns one of these while a target is down or
# restarting.
TARGET_UNAVAILABLE_STATUSES = frozenset({502, 503, 504})

# Single-sourced directive. The `exec` tool description and the hunting role
# prompts embed this text verbatim; the drift guards in
# `tests/attack/test_hunting_status.py` assert the exact string at every site.
TARGET_UNAVAILABLE_DIRECTIVE = (
    "Target-front availability (binding): a 5xx from the target front - "
    "502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout - means the "
    "target's upstream is currently unavailable (down, restarting, or "
    "overloaded), NOT that the route is absent. A restart can be self-inflicted: "
    "probing a destructive control route (for example a manager `reboot` / "
    "`restart` operation) makes the target restart, and the front then answers "
    "502 for the whole restart window. Do NOT loop or retry on a 5xx and do not "
    "read it as 404-style route-absence: record that the target is temporarily "
    "unavailable, stop probing, and let a later check resume once it is back. A "
    "404 (or any 4xx) is the real route-absence signal; a 5xx is not."
)


def is_target_unavailable(status: object) -> bool:
    """True when an HTTP status is the transient upstream-unavailable family.

    Only a real `int` in `TARGET_UNAVAILABLE_STATUSES` matches; a string, a
    missing status (`None`), or any other code is False, so the check never
    misfires on a non-numeric or lookalike value.
    """
    return isinstance(status, int) and not isinstance(status, bool) and (
        status in TARGET_UNAVAILABLE_STATUSES
    )


__all__ = [
    "TARGET_UNAVAILABLE_STATUSES",
    "TARGET_UNAVAILABLE_DIRECTIVE",
    "is_target_unavailable",
]
