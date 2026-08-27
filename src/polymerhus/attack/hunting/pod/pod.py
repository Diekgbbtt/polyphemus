"""The test-executor pod's public entry (IA-3 in, IA-4 out).

`arun_pod(spec)` is the ASYNC typed handoff (spec section 5, delivery canon,
D84-15): it takes the D4 `TestImplementationSpec` and returns the D5 + D6
`{verdict, evidence}` envelope. The pod is async-ONLY - the sync `run_pod`
wrapper is DELETED (Q7 VERDICTED): the parent HuntingAgent awaits `arun_pod`
natively through its `_await_seam` (async seams are awaited, sync seams are
to_thread-ed), so no sync wrapper remains a public entry. It NEVER raises into
the parent HuntingAgent (IA-4): any collaborator failure degrades to
`unsuccessful` with the error in the evidence trail, mirroring the recon
degrade-to-failed-export pattern (`recon/control/job_agent.py`). The pod
touches no store and no graph (spec 1.5); the parent persists the returned
envelope (operator, 2026-08-06).

Observability is the shared fail-open recipe (D67-05): one trace per pod run,
Langfuse optional and never a gate (C12).
"""
from __future__ import annotations

import logging
from typing import Callable, Sequence

from polymerhus.attack.hunting.pod.graph import RECURSION_LIMIT, build_pod_graph
from polymerhus.attack.hunting.pod.llm import POD_DEFAULT_RUN_ID
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


def _pod_session_address(run_id: str, hunt_id: str, spec_id: str, role_id: str):
    """The typed session address of one pod agent (#94, D84-2/Q13): rehomed to
    the session seam (`pod/llm.py::pod_session_address`), which owns the
    derivation on the semantic `<fault>_<strategy>` spec id; this thin alias
    keeps the contract tier's import target stable."""
    from polymerhus.attack.hunting.pod.llm import pod_session_address

    return pod_session_address(run_id, hunt_id, spec_id, role_id=role_id)


async def arun_pod(spec: dict, *, run_id: str = POD_DEFAULT_RUN_ID,
                   exec_fn: Callable | None = None,
                   runner_step_fn: Callable | None = None,
                   triager_fn: Callable | None = None,
                   trace_fn: Callable | None = None,
                   runner_middleware: Sequence = (),
                   triager_middleware: Sequence = (),
                   memory_store=None,
                   model_factory: Callable | None = None,
                   project_id: str | None = None,
                   spec_id: str | None = None,
                   target_url: str | None = None) -> dict:
    """Execute `spec` against the live target and return the IA-4 envelope.

    Async-only (D84-15): the graph is driven with `ainvoke`, and every injected
    seam - `exec_fn`, `runner_step_fn`, `triager_fn` - rides the `_await_seam`
    pattern inside the nodes (async seams awaited natively, sync seams offloaded
    via `asyncio.to_thread`), so both the production async terminals and the
    contract-tier sync fakes are injectable. The whole run is wrapped fail-open:
    a raise anywhere degrades to `unsuccessful` / `technical-infeasibility` with
    the error in the trail - the pod never raises into the parent.

    `runner_middleware` / `triager_middleware` are the per-role #95 compaction
    middleware sets (T5, D9 wiring): threaded into the graph's pod-session
    bindings (D84-7), where T7's stateful default seams pass them to
    `stateful_turn` verbatim. Default `()` = compaction disabled - the pod runs
    exactly as before, nothing breaks.

    `memory_store` is the pod-owned experiment-memory store (D84-33; default =
    the per-project root `data/<project_id>/test-executor-pod/` when a PRODUCTION
    seam is in play and `project_id` is provided, else `None` fail-open); the
    `model_factory(role) -> chat model` seam lets a harness or test inject a fake
    model for the production stateful turns (default None = the role's real
    model). `project_id` is the store's scoping axis (D84-33); `spec_id` is the
    #164 hunter's `<fault>_<strategy>` crossed through the typed handoff -
    REQUIRED when a memory store is bound (no fallback; a missing spec_id is the
    dispatch's failure mode, never a hash key). `target_url` is the resolved
    target base (``#197``; ``http://<domain>/``) the pod must probe; when
    present it is rendered into the Runner's filtered context so the LLM
    probes the seeded domain and never guesses ``localhost:8080``. When
    ``None`` the dispatch seam (``_default_pod_builder``) short-circuits to the
    INIT-rejection envelope - ``arun_pod`` itself keeps the spec-only C1 gate
    to avoid breaking the contract tier's symbolic runner, but surfaces the
    target when it is wired."""
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
            triager_fn=triager_fn,
            runner_middleware=runner_middleware, triager_middleware=triager_middleware,
            memory_store=memory_store, model_factory=model_factory,
            project_id=project_id, spec_id=spec_id, target_url=target_url)
        final = await graph.ainvoke(
            {"spec": dict(spec or {}), "run_id": run_id},
            config={"recursion_limit": RECURSION_LIMIT, "callbacks": callbacks})
        export = final.get("export")
        if not export:
            raise RuntimeError("pod produced no export")
        return export
    except Exception as exc:  # noqa: BLE001 - IA-4: degrade, never raise into the parent
        logger.warning("pod run degraded to unsuccessful (%s)", exc)
        export = PodExport(
            verdict="unsuccessful", terminal_reason=TECHNICAL_INFEASIBILITY,
            iterations=0, clean=False, error=str(exc)).to_envelope()
        # T7 (#183): the degrade path is a REAL terminal result - persist it too
        # (idempotent overwrite, GP1). The fail-closed spec_id gate is respected:
        # no spec_id means no export is persisted (the graph's init already
        # failed on it), and a write failure degrades fail-open (O3/IA-4), never
        # raising into the parent.
        if memory_store is not None and spec_id:
            try:
                memory_store.write_pod_export(spec_id, run_id, export)
            except Exception:  # noqa: BLE001 - fail-open (O3/IA-4)
                logger.warning("pod export persistence failed on the degrade "
                               "path (%s)", exc)
        return export