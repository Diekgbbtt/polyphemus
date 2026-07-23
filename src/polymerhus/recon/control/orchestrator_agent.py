"""Recon-orchestrator agent: macro pipeline management.

The orchestrator's steering responsibility is CROSS-JOB routing - given the WAF
signals the pipeline has already observed, decide which downstream job should
not receive which flagged host (route WAF-flagged hosts away from request-based
crawlers, toward the agentic crawler). `run_pipeline` is the driver that calls
`decide_routing` between phases; the reasoning lives here, with the agent that
owns it, not bolted onto the driver function.

Fail-open: any LLM/parse error returns the neutral decision ({} = no
exclusions), so a steering blip degrades adaptivity, never the run. Only invoked
with a non-empty signal list.

The `ORCHESTRATOR_STEERING` prompt is the TEMPORARY inline home for this agent's
thought process; it is slated to move into a dedicated recon-pipeline-agent
skill (forward-decision D22). It frames the shared `STEERING_PRIMITIVES` for the
orchestrator's macro-routing scope.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from polymerhus.recon.control.steering import (
    STEERING_PRIMITIVES,
    describe_job_kind,
    format_signals,
    resolve_model,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_STEERING = (
    "## STEERING DECISIONS (recon-orchestrator agent)\n\n"
    "You are the recon-orchestrator agent managing the macro reconnaissance\n"
    "pipeline. Given the signals the pipeline has already observed and the jobs\n"
    "about to run in the next phase, decide cross-job routing: which downstream\n"
    "job should NOT receive which flagged host. Reason about the signals; do not\n"
    "restate them.\n\n"
    + STEERING_PRIMITIVES
    + "\nRoute WAF-flagged hosts away from request-based crawlers and toward the\n"
    "agentic crawler; leave un-flagged hosts alone. Return the minimal set of\n"
    "exclusions needed.\n"
)


class _JobExclusion(BaseModel):
    job: str
    exclude_urls: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    exclusions: list[_JobExclusion] = Field(default_factory=list)
    rationale: str = ""


def decide_routing(signals: list[dict], phase_jobs: list[str], *, llm=None) -> dict[str, list[str]]:
    """Given live signals and the upcoming phase's jobs, return
    {job_name: [urls to exclude from that job]}. Fail-open to {}."""
    if not signals or not phase_jobs:
        return {}
    try:
        from langchain_core.messages import SystemMessage, HumanMessage  # noqa: PLC0415
        model = resolve_model("job_orchestrator", llm).with_structured_output(
            RoutingDecision, method="function_calling"
        )
        jobs_desc = "\n".join(f"- {j}: {describe_job_kind(j)}" for j in phase_jobs)
        human = (
            f"Signals (flagged BaseURLs):\n{format_signals(signals)}\n\n"
            f"Upcoming phase jobs:\n{jobs_desc}\n\n"
            "Return, per job that should NOT receive a flagged host, the urls to exclude."
        )
        decision = model.invoke(
            [SystemMessage(content=ORCHESTRATOR_STEERING), HumanMessage(content=human)]
        )
        return {e.job: e.exclude_urls for e in decision.exclusions if e.job in phase_jobs}
    except Exception:
        logger.warning("decide_routing failed; no routing adaptation", exc_info=True)
        return {}
