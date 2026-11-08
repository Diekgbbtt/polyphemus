"""Pod-internal fixed caps (D67-09).

Budget and timeout are the pod's OWN caps, set by the pod, env-overridable, and
NEVER carried in the `TestImplementationSpec` nor inherited from the
hunter's threat payload. Three families:

  * The per-exec caps reused from the recon pod (spec section 3 "reuses"):
    `MAX_POD_ITERS` retries on a non-zero exit and `EXEC_TIMEOUT_S` per exec.
  * The OUTER threat cap `HUNT_POD_MAX_ITERS` - the pod's own probe/variant
    budget. It bounds the actor-critic threat so the critic can never mine
    variants forever (the load-bearing halt guarantee). It is checked at the
    DECIDE -> PROBE edge (after the triager, before the next runner step) so a
    loop lap always completes - no mid-loop stop - and, when hit, it terminates
    ONLY the pod (`budget-timeout`), never the whole hunt.
  * The pod graph's node and tool bounds (`PodTimeouts`): the LangGraph
    `TimeoutPolicy` applied by `build_pod_graph`. The idle timeout is the
    liveness bound; the optional run timeout is a tighter pod-owned ceiling;
    the surfer's one-hour pod backstop is the last-resort hard wall clock.

This module reads env at import but performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Per-exec caps, reused from the recon pod's execution surface (recon/config.py).
from polymerhus.recon.config import EXEC_TIMEOUT_S, MAX_POD_ITERS  # noqa: F401  (re-exported)


def _timeout_env(name: str, default: float | None) -> float | None:
    """A positive timeout from the environment, or None to disable it."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    return value if value > 0 else None


# The pod graph's own node bounds. The idle timeout is the liveness bound: it
# resets on model tokens, tool results, state writes, and child-task starts. The
# hard wall clock is the surfer's one-hour pod backstop; a node run timeout is
# opt-in for a deployment that wants a tighter pod-owned ceiling.
POD_NODE_IDLE_TIMEOUT_S = _timeout_env("POD_NODE_IDLE_TIMEOUT_S", 600.0)
POD_NODE_RUN_TIMEOUT_S = _timeout_env("POD_NODE_RUN_TIMEOUT_S", None)
POD_TOOL_IDLE_TIMEOUT_S = _timeout_env("POD_TOOL_IDLE_TIMEOUT_S", 300.0)
POD_TOOL_RUN_TIMEOUT_S = _timeout_env("POD_TOOL_RUN_TIMEOUT_S", 900.0)


@dataclass(frozen=True)
class PodTimeouts:
    """The pod graph's node and tool timeouts.

    `None` disables that bound. The defaults keep the pod's idle and run bounds
    below the surfer's last-resort pod backstop.
    """

    node_idle_s: float | None = POD_NODE_IDLE_TIMEOUT_S
    node_run_s: float | None = POD_NODE_RUN_TIMEOUT_S
    tool_idle_s: float | None = POD_TOOL_IDLE_TIMEOUT_S
    tool_run_s: float | None = POD_TOOL_RUN_TIMEOUT_S


DEFAULT_POD_TIMEOUTS = PodTimeouts()

# The outer actor-critic threat budget: the max number of probe/variant laps the
# pod runs before it terminates itself with `budget-timeout`. Checked at the
# DECIDE -> RUNNER boundary so every lap completes atomically (operator, 2026-08-06).
HUNT_POD_MAX_ITERS = int(os.environ.get("HUNT_POD_MAX_ITERS", "8"))

# The INNER stretch cap: the max tool calls the runner may drive within ONE probe
# stretch before the harness forces it to conclude. This is the structural
# termination guarantee for the runner's agentic loop - the runner is the control
# plane of the stretch (it chooses the tool sequence and branches), but the
# harness owns the threat and can never let it run unbounded (G1). As of D84-22
# (T7) the default is 200 (not the legacy 6): in the ReAct production lane the
# harness middleware enforces this cap inside `create_agent`.
HUNT_POD_MAX_TOOL_CALLS = int(os.environ.get("HUNT_POD_MAX_TOOL_CALLS", "200"))
