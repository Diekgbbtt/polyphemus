"""Per-job orchestrator agent: LLM preprocess -> Send fan-out -> pod subgraph.

Two-level nesting (design §3): `build_job_agent` compiles a
`StateGraph(JobState)` with two nodes - `preprocess` (distributes a job's
`input_assets` into <= MAX_PODS `pod_inputs`) and `pod_runner` (invokes the
Foundation pod subgraph once per pod_input, fanned out via `Send`). Results
accumulate into `pod_exports` through an `operator.add` reducer so the
parallel `pod_runner` Sends don't clobber each other.

`pod_invoke` and `preprocess_fn` are injected - production wires
`default_pod_invoke` (wraps Foundation `agent.recon.pod.pod_graph`) and
`default_preprocess_fn` (deterministic 1:1 asset->pod_input mapping capped
at MAX_PODS; the LLM-cleaning path via chat_model_for("job_orchestrator")
is a structured seam for a future enhancement, not exercised by the MVP
default). Importing this module performs no I/O: building the module-level
`job_agent` only wires function references, it does not call them.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from agent.recon.config import MAX_PODS
from agent.recon.types import JobSpec, PodExport


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
    """Deterministic fallback: 1:1 map input_assets -> pod_inputs, capped at
    MAX_PODS. `extra.auth_context` is threaded through ONLY for `use_auth`
    jobs - non-auth pods must never see it, even if the caller passed it in.

    This is the seam an LLM-driven cleaning/dedup pass (chat_model_for
    ("job_orchestrator")) would replace for `configurator_mode == "agent"`
    jobs; kept deterministic for the MVP per the plan's design notes.
    """
    capped = list(input_assets or [])[:MAX_PODS]
    base_extra = dict(extra or {})
    if not job.use_auth:
        base_extra.pop("auth_context", None)

    return [
        {
            "input_asset": asset,
            "asset_context": asset_context or "",
            "extra": dict(base_extra),
        }
        for asset in capped
    ]


def default_pod_invoke(pod_input: dict, job: JobSpec, run_id: str, phase: int) -> PodExport:
    """Real collaborator: invoke the Foundation pod subgraph for a single
    pod_input and return its terminal export. Builds nothing at import time
    - `agent.recon.pod.pod_graph` is already import-safe (no I/O).

    Jobs with `configurator_mode == "agent"` (e.g. `steel_crawl`) route to
    the crawl-pod variant instead - imported lazily here (not at module
    top) to avoid a heavy import / circular import at `job_agent` import
    time, mirroring how the template `pod_graph` is imported lazily below.
    """
    if job.configurator_mode == "agent":
        from agent.recon.crawl.crawl_pod import crawl_pod_invoke

        return crawl_pod_invoke(pod_input, job, run_id, phase)

    import uuid

    from agent.recon.pod import pod_graph

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
    }
    # Langfuse tracing: the pod subgraph tree (configurator/execute/parser/
    # triager/curator) becomes the per-pod span tree. Empty list (unconfigured)
    # is inert. See agent/app/observability/langfuse_tracing.py.
    from agent.app.observability import get_langfuse_callbacks

    result = pod_graph.invoke(
        pod_state, config={"callbacks": get_langfuse_callbacks()}
    )
    return result["export"]


def build_job_agent(*, pod_invoke, preprocess_fn):
    """Compile the per-job orchestrator graph, injecting the two
    side-effecting collaborators: pod_invoke(pod_input, job, run_id, phase)
    -> PodExport, preprocess_fn(input_assets, job, extra, asset_context) ->
    list[pod_input]."""

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
        return {"pod_exports": [export]}

    g = StateGraph(JobState)
    g.add_node("preprocess", preprocess_node)
    g.add_node("pod_runner", pod_runner_node)
    g.add_edge(START, "preprocess")
    g.add_conditional_edges("preprocess", fan_out, ["pod_runner"])
    g.add_edge("pod_runner", END)
    return g.compile()


job_agent = build_job_agent(pod_invoke=default_pod_invoke, preprocess_fn=default_preprocess_fn)


async def run_job(
    job: JobSpec,
    input_assets: list[dict],
    *,
    run_id: str,
    phase: int,
    extra: dict,
    agent=None,
) -> list[PodExport]:
    """Convenience async wrapper: invoke the compiled job agent and return
    its collected pod_exports. The Foundation pod subgraph is sync-invokable
    (no async collaborators in the default wiring), so this simply calls
    the compiled graph's sync `.invoke` - kept `async def` for the pipeline
    orchestrator's benefit (it awaits per-job runs concurrently)."""
    graph = agent or job_agent
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
    from agent.app.observability import get_langfuse_callbacks

    result = graph.invoke(initial, config={"callbacks": get_langfuse_callbacks()})
    return result["pod_exports"]
