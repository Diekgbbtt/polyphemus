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
MAX_JOB_ASSETS budget; the LLM-cleaning path via chat_model_for("job_orchestrator")
is a structured seam for a future enhancement, not exercised by the MVP
default). Importing this module performs no I/O: building the module-level
`job_agent` only wires function references, it does not call them.
"""
from __future__ import annotations

import asyncio
import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from pydantic import BaseModel, Field

from polymerhus.recon.config import MAX_JOB_ASSETS, MAX_PODS
from polymerhus.recon.control.steering import (
    STEERING_PRIMITIVES,
    describe_job_kind,
    format_signals,
    resolve_model,
)
from polymerhus.recon.domain.types import JobSpec, PodExport

logger = logging.getLogger(__name__)


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


# The recon-job agent's steering responsibility: per-asset THROTTLING within one
# job. It NEVER selects which assets run - that is the recon-orchestrator's
# concern (`orchestrator_agent.decide_routing`); every candidate asset always
# becomes a pod. The JOB_STEERING prompt is the TEMPORARY inline home for this
# agent's thought process (dedicated skill = D22); it frames the shared
# STEERING_PRIMITIVES for the job agent's throttle-only scope.
JOB_STEERING = (
    "## STEERING DECISIONS (recon-job agent)\n\n"
    "You are the recon-job agent configuring one job's pods. Every candidate\n"
    "asset WILL run - which assets a job processes is not your decision. Your\n"
    "only decision is throttling: given this job, its candidate assets, and the\n"
    "signals the pipeline has already observed, decide which assets to throttle.\n"
    "Reason about the signals; do not restate them.\n\n"
    + STEERING_PRIMITIVES
    + "\nThrottle only as a deliberate preventive choice against a not-yet-flagged\n"
    "host; leave every other asset at its default rate. Never skip an asset.\n"
)


class _AssetPlan(BaseModel):
    url: str
    throttle: bool = False


class PodThrottlePlan(BaseModel):
    plan: list[_AssetPlan] = Field(default_factory=list)
    rationale: str = ""


def decide_pod_selection(signals: list[dict], job_name: str, assets: list[dict], *, llm=None) -> set[str]:
    """Given the job's candidate assets and live signals, return the set of
    BaseURLs to THROTTLE. This agent NEVER drops an asset - asset selection is
    the recon-orchestrator's concern (`decide_routing`); every candidate always
    runs. Fail-open to `set()` (nothing throttled)."""
    urls = [a.get("url") for a in assets if a.get("url")]
    if not signals or not urls:
        return set()
    try:
        from langchain_core.messages import SystemMessage, HumanMessage  # noqa: PLC0415
        model = resolve_model("job_orchestrator", llm).with_structured_output(
            PodThrottlePlan, method="function_calling"
        )
        human = (
            f"Job: {job_name} ({describe_job_kind(job_name)}).\n"
            "Candidate BaseURLs:\n" + "\n".join(f"- {u}" for u in urls) + "\n\n"
            f"Signals (flagged BaseURLs):\n{format_signals(signals)}\n\n"
            "For each candidate, decide whether to throttle it."
        )
        decision = model.invoke([SystemMessage(content=JOB_STEERING), HumanMessage(content=human)])
        return {p.url for p in decision.plan if p.throttle}
    except Exception:
        logger.warning("decide_pod_selection failed; throttling nothing", exc_info=True)
        return set()


def steering_preprocess_fn(
    input_assets: list[dict], job: JobSpec, extra: dict, asset_context: str
) -> list[dict]:
    """Recon-job agent steering: when live steering signals are present in
    `extra["steering"]`, ask the job-orchestrator LLM which of this job's
    candidate assets to THROTTLE (STEERING DECISIONS), then build one pod per
    (budget-capped) candidate - EVERY asset always runs; only throttled ones
    carry `extra["rate_profile"] = "throttle"`. Asset selection is the
    recon-orchestrator's concern (`decide_routing`), never this agent's.
    Otherwise fall back to the deterministic default. Fail-open: any error ->
    default_preprocess_fn.

    `extra["steering"]` is orchestration-only and is stripped from the pod's
    own extra; a throttled asset instead carries `extra["rate_profile"]`."""
    signals = (extra or {}).get("steering") or []
    # A batched job (jsluice) has no per-asset url to throttle and needs the
    # reduce+pack path; an endpoint-profiling job (httpx_reprofile) needs its
    # dedup+root-materialisation prep. Both delegate to the deterministic default
    # so their input-prep always runs, even under steering.
    if not signals or job.batch or job.endpoint_profiling or job.api_scope:
        return default_preprocess_fn(input_assets, job, extra, asset_context)
    try:
        throttle_urls = decide_pod_selection(signals, job.tool, input_assets or [])
    except Exception:
        return default_preprocess_fn(input_assets, job, extra, asset_context)

    capped = list(input_assets or [])[:MAX_JOB_ASSETS]
    base_extra = dict(extra or {})
    base_extra.pop("steering", None)  # orchestration-only, never reaches a pod
    base_extra.pop("apex_registrable", None)  # orchestration-only, never reaches a pod

    pod_inputs = []
    for asset in capped:
        pod_extra = dict(base_extra)
        if asset.get("url") in throttle_urls:
            pod_extra["rate_profile"] = "throttle"
        pod_inputs.append(
            {"input_asset": asset, "asset_context": asset_context or "", "extra": pod_extra}
        )
    return pod_inputs


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
    }
    # Langfuse tracing: the pod subgraph tree (configurator/execute/parser/
    # triager/curator) becomes the per-pod span tree. Empty list (unconfigured)
    # is inert. See src/polymerhus/app/observability/langfuse_tracing.py.
    from polymerhus.app.observability import get_langfuse_callbacks

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


job_agent = build_job_agent(pod_invoke=default_pod_invoke, preprocess_fn=steering_preprocess_fn)


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
    (no async collaborators in the default wiring), but its work (LLM triage,
    the sync Neo4j curate, the exec bridge) is blocking. Calling `.invoke`
    directly on the event loop would stall the whole API and serialize the
    pipeline's `asyncio.gather` fan-out, so we offload it to a worker thread
    via `asyncio.to_thread`. Inside that thread there is no running loop, so
    `run_coro_blocking` (pod exec) cleanly takes its `asyncio.run` path."""
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
