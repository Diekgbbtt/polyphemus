"""The test-executor pod's public entry (IA-3 in, IA-4 out).

`run_pod(spec)` is the synchronous typed handoff (spec section 5, delivery
canon): it takes the D4 `TestImplementationSpec` and returns the D5 + D6
`{verdict, evidence}` envelope. It NEVER raises into the parent HuntingAgent
(IA-4): any collaborator failure degrades to `unsuccessful` with the error in
the evidence trail, mirroring the recon degrade-to-failed-export pattern
(`recon/control/job_agent.py`). The pod touches no store and no graph (spec
1.5); the parent persists the returned envelope (operator, 2026-08-06).

Observability is the shared fail-open recipe (D67-05): one trace per pod run,
Langfuse optional and never a gate (C12).
"""
from __future__ import annotations

import logging
from typing import Callable

from polymerhus.attack.hunting.pod.graph import RECURSION_LIMIT, build_pod_graph
from polymerhus.attack.hunting.pod.tools import default_exec_fn
from polymerhus.attack.hunting.pod.types import PodExport, TECHNICAL_INFEASIBILITY

logger = logging.getLogger(__name__)


def _default_trace_fn(run_id: str):
    """The Langfuse observability stub (D67-05): one trace per pod run, session
    = run id, fail-open. Returns an inert handle; a real Langfuse wiring is a
    later change. Kept a seam so C12 can inject a RAISING stub and prove the run
    completes unaffected."""
    from polymerhus.app.observability import get_langfuse_callbacks

    return get_langfuse_callbacks()


def run_pod(spec: dict, *, run_id: str = "hunt-pod",
            exec_fn: Callable | None = None,
            runner_step_fn: Callable | None = None,
            triager_fn: Callable | None = None,
            kb_fn: Callable | None = None,
            trace_fn: Callable | None = None) -> dict:
    """Execute `spec` against the live target and return the IA-4 envelope.

    Every collaborator is injectable (the contract tier passes fakes). The whole
    run is wrapped fail-open: a raise anywhere degrades to `unsuccessful` /
    `technical-infeasibility` with the error in the trail - the pod never raises
    into the parent."""
    exec_fn = exec_fn or default_exec_fn
    trace_fn = trace_fn if trace_fn is not None else _default_trace_fn

    # One trace per run; Langfuse never gates (C12 - a raising stub is swallowed).
    callbacks = []
    try:
        callbacks = trace_fn(run_id) or []
    except Exception as exc:  # noqa: BLE001 - observability is never a gate
        logger.warning("pod trace stub failed, continuing untraced (%s)", exc)

    try:
        graph = build_pod_graph(
            exec_fn=exec_fn, runner_step_fn=runner_step_fn,
            triager_fn=triager_fn, kb_fn=kb_fn)
        final = graph.invoke(
            {"spec": dict(spec or {}), "run_id": run_id},
            config={"recursion_limit": RECURSION_LIMIT, "callbacks": callbacks})
        export = final.get("export")
        if not export:
            raise RuntimeError("pod produced no export")
        return export
    except Exception as exc:  # noqa: BLE001 - IA-4: degrade, never raise into the parent
        logger.warning("pod run degraded to unsuccessful (%s)", exc)
        return PodExport(
            verdict="unsuccessful", terminal_reason=TECHNICAL_INFEASIBILITY,
            iterations=0, clean=False, error=str(exc)).to_envelope()
