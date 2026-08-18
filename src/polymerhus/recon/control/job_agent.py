"""Per-job orchestrator agent: LLM preprocess -> Send fan-out -> pod subgraph.

Two-level nesting (design §3): `build_job_agent` compiles a
`StateGraph(JobState)` with two nodes - `preprocess` (maps a job's
`input_assets` 1:1 into `pod_inputs`, up to the MAX_JOB_ASSETS budget) and
`pod_runner` (invokes the Foundation pod subgraph once per pod_input, fanned
out via `Send`). `run_job` invokes the graph with `max_concurrency=MAX_PODS`,
so ALL assets are covered but only MAX_PODS pods run at once (MAX_PODS is a
concurrency ceiling, not an asset cap). Results accumulate into `pod_exports`
through an `operator.add` reducer so the parallel `pod_runner` Sends don't
clobber each other.

`pod_invoke` and `preprocess_fn` are injected - production wires
`default_pod_invoke` (wraps Foundation `polymerhus.recon.domain.pod.pod_graph`) and
`default_preprocess_fn` (deterministic 1:1 asset->pod_input mapping up to the
MAX_JOB_ASSETS budget; `extra` - including the orchestration-level
`extra["steering"]` signals - is threaded through verbatim). The per-asset
throttling decision that once lived here (`decide_pod_selection`, #81) moved into
the pod graph's configurator node (#94): each pod consults a stateful per-pod
`configurator` role turn and sets its own `rate_profile`. `notify_fn` (optional)
is the #94 delivery seam: fired after each pod completes so a parent actor can be
told a pod finished and go READ that pod's session memory; `pod_completion_notify`
builds it from a parent `inbox`. Importing this module performs no I/O: building
the module-level `job_agent` only wires function references, it does not call them.
"""
from __future__ import annotations

import asyncio
import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from polymerhus.recon.config import MAX_JOB_ASSETS, MAX_PODS
from polymerhus.recon.domain.types import JobSpec, PodExport

logger = logging.getLogger(__name__)


def pod_trace_metadata(run_id: str, phase: int, tool: str) -> dict:
    """Correlation metadata for a recon pod's Langfuse trace.

    Recon spans carried NO metadata at all: no session, no run, no job. So a recon
    trace could not be attributed to a run, and the analyser's spans - which DO set
    `langfuse_session_id` (`analysis/supervisor.py`) - sat in a session no recon
    span shared. That made the two modules' traces unjoinable, which is why the
    proposal to derive the stall delta from trace timestamps could not be executed
    against today's data at all.

    This closes the gap for DIAGNOSIS - a human can now open one session and see
    recon jobs and analyser passes interleaved on one timeline. It deliberately
    does NOT make Langfuse the gate: tracing is optional, fail-open, and drops span
    batches under exactly the latency stress a stall creates, so the pass/fail
    predicate is decided from Postgres instead (see `_exec_window` in
    `recon/control/pipeline.py` and §12 of the decoupling design doc).

    The session id is the bare `run_id`, matching the recon run; the analyser's own
    passes run under `stream-<run_id>`, and the shared `run_id` tag is what joins
    the two."""
    return {
        "langfuse_session_id": run_id,
        "langfuse_tags": ["recon", "pod", tool],
        "run_id": run_id,
        "phase": phase,
        "job": tool,
    }


class JobState(TypedDict, total=False):
    job: JobSpec
    input_assets: list[dict]
    asset_context: str
    extra: dict
    run_id: str
    phase: int
    pod_inputs: list[dict]
    pod_exports: Annotated[list[PodExport], operator.add]


def default_preprocess_fn(
    input_assets: list[dict], job: JobSpec, extra: dict, asset_context: str
) -> list[dict]:
    """Deterministic fallback: 1:1 map input_assets -> pod_inputs, capped at the
    MAX_JOB_ASSETS total-work budget (NOT MAX_PODS, which is the concurrency
    ceiling applied at fan-out time). All assets up to the budget become pods and
    are processed MAX_PODS at a time. `extra.auth_context` is threaded through
    ONLY for `use_auth` jobs - non-auth pods must never see it, even if the
    caller passed it in.

    This is the seam an LLM-driven cleaning/dedup pass (chat_model_for
    ("job_orchestrator")) would replace for `configurator_mode == "agent"`
    jobs; kept deterministic for the MVP per the plan's design notes.
    """
    # Auth-eligibility is the pipeline's single concern (C1): it injects
    # auth_context into extra ONLY for use_auth jobs, so this preprocess trusts
    # extra as-is and never re-strips.
    base_extra = dict(extra or {})
    # C3: pod DISTRIBUTION is this agent's concern. For a batched job (jsluice),
    # reduce (first-party filter + url/basename dedup) and pack the bundles into
    # <= MAX_PODS batch-pods here - not in the pipeline. `apex_registrable` is the
    # orchestration datum the pipeline supplied for the first-party filter; it is
    # popped so it never reaches a pod.
    apex_registrable = base_extra.pop("apex_registrable", None)
    if job.batch:
        from polymerhus.recon.control.batching import build_batch_assets

        input_assets = build_batch_assets(
            input_assets or [], apex_registrable=apex_registrable, max_pods=MAX_PODS
        )
    elif job.endpoint_profiling:
        # D16 per-endpoint split: dedup the Endpoint population to one probe per
        # (baseurl, method, path-template) and materialise a root `/` per BaseURL,
        # so the active re-probe stays bounded on the constrained host and every
        # host still gets its root-mirror profile.
        from polymerhus.recon.control.batching import prepare_endpoint_profile_assets

        input_assets = prepare_endpoint_profile_assets(input_assets or [])
    elif job.api_scope:
        # D16 per-endpoint split: collapse a host's `restapi` Endpoints into
        # evidence-derived API-root scan-target prefixes (one pod per target).
        from polymerhus.recon.control.batching import build_api_scope_assets

        input_assets = build_api_scope_assets(input_assets or [])

    capped = list(input_assets or [])[:MAX_JOB_ASSETS]

    return [
        {
            "input_asset": asset,
            "asset_context": asset_context or "",
            "extra": dict(base_extra),
        }
        for asset in capped
    ]


# Per-asset throttling (#94) is now the POD CONFIGURATOR's decision, exactly
# like the triager: the pod graph's configurator node consults a stateful,
# per-pod `configurator` role turn over the job's STEERING signals and sets the
# pod's `rate_profile`. The recon-job agent is purely deterministic again -
# `default_preprocess_fn` simply threads `extra["steering"]` through to every
# pod_input, and the pod itself decides how to run.


def default_pod_invoke(pod_input: dict, job: JobSpec, run_id: str, phase: int) -> PodExport:
    """Real collaborator: invoke the Foundation pod subgraph for a single
    pod_input and return its terminal export. Builds nothing at import time
    - `polymerhus.recon.domain.pod.pod_graph` is already import-safe (no I/O).

    Jobs with `configurator_mode == "agent"` (e.g. `steel_crawl`) route to
    the crawl-pod variant instead - imported lazily here (not at module
    top) to avoid a heavy import / circular import at `job_agent` import
    time, mirroring how the template `pod_graph` is imported lazily below.
    """
    if job.configurator_mode == "agent":
        from polymerhus.recon.crawl.crawl_pod import crawl_pod_invoke

        return crawl_pod_invoke(pod_input, job, run_id, phase)
    import uuid

    from polymerhus.recon.domain.pod import pod_graph

    extra = pod_input.get("extra") or {}
    project_id = extra.get("project_id", run_id)
    session_id = f"{run_id}-{phase}-{job.tool}-{uuid.uuid4().hex[:8]}"

    pod_state = {
        "job": job,
        "input_asset": pod_input.get("input_asset", {}),
        "asset_context": pod_input.get("asset_context", ""),
        "extra": extra,
        "session_id": session_id,
        "project_id": project_id,
        # #94: the pod's run + phase, so the triager node can address its STATEFUL
        # session per concurrent pod instance (PodSession). Absent in tests
        # that invoke the pod graph directly -> the triager stays stateless there.
        "run_id": run_id,
        "phase": phase,
    }
    # Langfuse tracing: the pod subgraph tree (configurator/execute/parser/
    # triager/curator) becomes the per-pod span tree. Empty list (unconfigured)
    # is inert. See src/polymerhus/app/observability/langfuse_tracing.py.
    from polymerhus.app.observability import get_langfuse_callbacks

    result = pod_graph.invoke(
        pod_state,
        config={"callbacks": get_langfuse_callbacks(),
                "metadata": pod_trace_metadata(run_id, phase, job.tool)},
    )
    return result["export"]


def build_job_agent(*, pod_invoke, preprocess_fn, notify_fn=None):
    """Compile the per-job orchestrator graph, injecting the two
    side-effecting collaborators: pod_invoke(pod_input, job, run_id, phase)
    -> PodExport, preprocess_fn(input_assets, job, extra, asset_context) ->
    list[pod_input]. `notify_fn(pod_input, job, run_id, phase, export) -> None`
    fires after EACH pod completes (success or failure) - the #94 delivery
    seam a parent wires (`pod_completion_notify`) to be told a pod finished
    so it can go READ that pod's session memory. Inert when not given."""

    def preprocess_node(state: JobState) -> dict:
        job = state["job"]
        input_assets = state.get("input_assets") or []
        extra = state.get("extra") or {}
        asset_context = state.get("asset_context", "")
        pod_inputs = preprocess_fn(input_assets, job, extra, asset_context)
        return {"pod_inputs": pod_inputs}

    def fan_out(state: JobState) -> list[Send]:
        return [
            Send(
                "pod_runner",
                {
                    "_pod_input": pi,
                    "job": state["job"],
                    "run_id": state.get("run_id"),
                    "phase": state.get("phase"),
                },
            )
            for pi in state.get("pod_inputs") or []
        ]

    def pod_runner_node(state) -> dict:
        pod_input = state["_pod_input"]
        job = state["job"]
        run_id = state.get("run_id")
        phase = state.get("phase")
        try:
            export = pod_invoke(pod_input, job, run_id, phase)
        except Exception as exc:  # best-effort: one pod's failure never
            # aborts the others (design §10.6) - degrade to a failed export.
            export = PodExport(
                input_asset=pod_input.get("input_asset", {}),
                verdict="failed",
                error=str(exc),
            )
        if notify_fn is not None:
            try:
                notify_fn(pod_input, job, run_id, phase, export)
            except Exception:  # noqa: BLE001 - a delivery failure never
                # degrades the pod result; the parent can still be told later
                logger.warning("pod completion notification failed", exc_info=True)
        return {"pod_exports": [export]}

    g = StateGraph(JobState)
    g.add_node("preprocess", preprocess_node)
    g.add_node("pod_runner", pod_runner_node)
    g.add_edge(START, "preprocess")
    g.add_conditional_edges("preprocess", fan_out, ["pod_runner"])
    g.add_edge("pod_runner", END)
    return g.compile()


def pod_completion_notify(inbox, *, kind: str = "pod_complete", source: str | None = None):
    """Build the `notify_fn` a recon run wires onto its job graphs (#94 delivery):
    when a pod finishes, post into the parent `inbox` the pod's SESSION thread id
    (its `PodSession` address - what the parent needs to go READ that pod's memory
    via `read_session_memory`) plus the pod's terminal export. Thread-safe (pods run
    in worker threads via `asyncio.to_thread`) and a no-op for a None inbox."""
    from polymerhus.app.llm.actor import subagent_completion_hook

    hook = subagent_completion_hook(inbox, kind=kind, source=source)

    def notify(pod_input, job, run_id, phase, export):
        if run_id is None:
            return  # no run context (test-invoked graphs): nothing addressable
        from polymerhus.recon.domain.pod import pod_session

        address = pod_session(run_id, phase, job,
                              pod_input.get("input_asset", {}), role_id="triager")
        hook(address.thread_id, export)

    return notify


job_agent = build_job_agent(pod_invoke=default_pod_invoke, preprocess_fn=default_preprocess_fn)


async def run_job(
    job: JobSpec,
    input_assets: list[dict],
    *,
    run_id: str,
    phase: int,
    extra: dict,
    agent=None,
    notify_fn=None,
) -> list[PodExport]:
    """Convenience async wrapper: invoke the compiled job agent and return
    its collected pod_exports. The Foundation pod subgraph is sync-invokable
    (no async collaborators in the default wiring), but its work (LLM triage,
    the sync Neo4j curate, the exec bridge) is blocking. Calling `.invoke`
    directly on the event loop would stall the whole API and serialise the
    pipeline's `asyncio.gather` fan-out, so we offload it to a worker thread
    via `asyncio.to_thread`. Inside that thread there is no running loop, so
    `run_coro_blocking` (pod exec) cleanly takes its `asyncio.run` path.
    `notify_fn` (a job graph's #94 delivery seam) is threaded into the
    compiled agent when `agent` is not supplied."""
    graph = agent or build_job_agent(
        pod_invoke=default_pod_invoke, preprocess_fn=default_preprocess_fn,
        notify_fn=notify_fn,
    )
    initial: JobState = {
        "job": job,
        "input_assets": input_assets,
        "asset_context": "",
        "extra": extra or {},
        "run_id": run_id,
        "phase": phase,
    }
    # Langfuse tracing: the job graph (preprocess -> pod fan-out) is the
    # top-level per-job trace; the pod subgraphs nest under it. Empty list
    # (Langfuse unconfigured) is inert.
    from polymerhus.app.observability import get_langfuse_callbacks

    # max_concurrency=MAX_PODS makes MAX_PODS a pure CONCURRENCY ceiling: the
    # graph fans out one pod per input asset (all of them, up to the
    # MAX_JOB_ASSETS budget) but LangGraph runs at most MAX_PODS pod_runner
    # Sends at a time, in waves. Verified against langgraph 1.2.7 sync .invoke.
    result = await asyncio.to_thread(
        graph.invoke,
        initial,
        config={"callbacks": get_langfuse_callbacks(), "max_concurrency": MAX_PODS},
    )
    return result["pod_exports"]
