"""The pod's session seam: the graph-owned ContextVar binding (D84-7) and the
typed `HuntSession` address derivation (D84-2), mirroring the hunting
`llm.py::hunt_session` and recon `domain/pod.py::_pod_ctx` patterns.

The pod GRAPH owns the per-instance binding (D84-7): its `runner_agent` and
`triager` nodes wrap their injected seam calls in `bind_pod_session(...)`, which
resolves the pod role's typed session from the PARENT `hunt_session` ContextVar
when the pod runs inside a hunt; the DEFAULT seams (`agents.py`) then read the
bound typed session via the `pod_session()` getter, so the typed address reaches
`stateful_turn` (T7) without changing the injected seam contract (a test double
simply ignores the ContextVar). Fail-open: no parent hunt, a failed binding, or
a missing checkpointer yields the task-local default or a stateless call - never
a crash.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6): `contextvars`, the checkpointer, and the session_address types all
resolve lazily on call.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The pod's two roles (D84-1): single point of truth so neither the graph nor a
# caller hard-codes a role_id string.
POD_RUNNER_ROLE = "pod_runner"
POD_TRIAGER_ROLE = "pod_triager"

# The task-local run_id fallback: what `run_pod` uses by default, so a pod
# invoked directly (outside any hunt) still derives a stable session address.
POD_DEFAULT_RUN_ID = "hunt-pod"

# The per-pod-session context for the seams' STATEFUL turns: a typed
# `SessionContext(HuntSession(...), checkpointer)`, set by the pod graph's node
# right before the seam call and read by the default seam. Passed out-of-band
# through a ContextVar so the injected seam contract stays untouched. Set+read
# within ONE synchronous node execution, so concurrent pod runs never see each
# other's context. `None` => stateless (a directly-invoked pod graph in tests, or
# a binding that failed fail-open).
_pod_session_ctx: "ContextVar" = None  # lazily created below to keep imports light


def _pod_ctx():
    """The module ContextVar, created on first use (import stays free of contextvars)."""
    global _pod_session_ctx
    if _pod_session_ctx is None:
        from contextvars import ContextVar
        _pod_session_ctx = ContextVar("pod_session_ctx", default=None)
    return _pod_session_ctx


def pod_session():
    """The pod agent's currently bound session (a typed `SessionContext(address,
    checkpointer)`), or None when the pod runs stateless (tests, a direct graph
    invocation). The default seams read this so the typed `HuntSession` address -
    role_id included - rides out-of-band to `stateful_turn` (T7)."""
    return _pod_ctx().get()


def pod_session_address(run_id: str, hunt_id: str, spec: dict, *, role_id: str):
    """The typed session address of one pod agent (D84-2, rehomed from
    `pod.py::_pod_session_address`): the parent's canonical spec hash
    discriminates concurrent pod sessions on one hunt, so the checkpointer never
    routes one variant's memory into another; an absent hunt_id defaults to ""
    (empty discriminators are dropped, never shifting the address)."""
    from polymerhus.app.llm.session_address import HuntSession
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash

    return HuntSession(run_id=run_id, hunt_id=hunt_id or "",
                       role_id=role_id, spec=canonical_spec_hash(spec))


def _parent_hunt_session():
    """The parent's `hunt_session` context binding (a typed `SessionContext`) when
    the pod runs inside a hunt, else None. Fail-open: an import or read failure
    degrades to no parent, never raising into the node."""
    try:
        from polymerhus.attack.hunting.llm import hunt_session_context
        return hunt_session_context()
    except Exception:  # noqa: BLE001 - a parent-read failure stays fail-open
        logger.warning("pod could not read the parent hunt_session; running with "
                       "the task-local default", exc_info=True)
        return None


def bind_pod_session(run_id: str, hunt_id: str, spec: dict, *, role_id: str):
    """Context manager the pod graph's `runner_agent` / `triager` nodes wrap their
    seam calls in (D84-7): binds the pod role's typed session for the duration of
    the seam call.

    When the parent `hunt_session` ContextVar is present, the derived session
    takes its run_id/hunt_id; otherwise it falls back to the caller's `run_id`
    (the task-local default) and the given `hunt_id` (the graph passes "" - empty
    discriminators are dropped from the address, never shifting it). Fail-open:
    any binding failure runs the seam stateless (no session bound), mirroring the
    recon pod's never-fail-a-pod discipline."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        _token = None
        try:
            from polymerhus.app.llm.checkpoints import get_session_checkpointer
            from polymerhus.app.llm.session_address import SessionContext

            parent = _parent_hunt_session()
            eff_run_id, eff_hunt_id = run_id, hunt_id
            if parent is not None:
                eff_run_id = parent.address.run_id
                eff_hunt_id = parent.address.hunt_id
            _token = _pod_ctx().set(
                SessionContext(pod_session_address(eff_run_id, eff_hunt_id, spec,
                                                   role_id=role_id),
                               get_session_checkpointer()))
        except Exception:  # noqa: BLE001 - fail-open: bind, or run stateless
            logger.warning("pod session binding failed; the seam runs stateless", exc_info=True)
            _token = None
        try:
            yield
        finally:
            if _token is not None:
                _pod_ctx().reset(_token)

    return _cm()