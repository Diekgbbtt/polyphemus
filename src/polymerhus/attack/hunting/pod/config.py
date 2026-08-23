"""Pod-internal fixed caps (D67-09).

Budget and timeout are the pod's OWN caps, set by the pod, env-overridable, and
NEVER carried in the `TestImplementationSpec` nor inherited from the
`HuntConfig`. Two families:

  * The per-exec caps reused from the recon pod (spec section 3 "reuses"):
    `MAX_POD_ITERS` retries on a non-zero exit and `EXEC_TIMEOUT_S` per exec.
  * The OUTER loop cap `HUNT_POD_MAX_ITERS` - the pod's own probe/variant
    budget. It bounds the actor-critic loop so the critic can never mine
    variants forever (the load-bearing halt guarantee). It is checked at the
    DECIDE -> PROBE edge (after the triager, before the next runner step) so a
    loop lap always completes - no mid-loop stop - and, when hit, it terminates
    ONLY the pod (`budget-timeout`), never the whole hunt.

This module reads env at import but performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import os

# Per-exec caps, reused from the recon pod's execution surface (recon/config.py).
from polymerhus.recon.config import EXEC_TIMEOUT_S, MAX_POD_ITERS  # noqa: F401  (re-exported)

# The outer actor-critic loop budget: the max number of probe/variant laps the
# pod runs before it terminates itself with `budget-timeout`. Checked at the
# DECIDE -> RUNNER boundary so every lap completes atomically (operator, 2026-08-06).
HUNT_POD_MAX_ITERS = int(os.environ.get("HUNT_POD_MAX_ITERS", "8"))

# The INNER stretch cap: the max tool calls the runner may drive within ONE probe
# stretch before the harness forces it to conclude. This is the structural
# termination guarantee for the runner's agentic loop - the runner is the control
# plane of the stretch (it chooses the tool sequence and branches), but the
# harness owns the loop and can never let it run unbounded (G1). As of D84-22
# (T7) the default is 200 (not the legacy 6): in the ReAct production lane the
# harness middleware enforces this cap inside `create_agent`.
HUNT_POD_MAX_TOOL_CALLS = int(os.environ.get("HUNT_POD_MAX_TOOL_CALLS", "200"))
