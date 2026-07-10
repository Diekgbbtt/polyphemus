"""LLM steering agents: the recon-orchestrator and recon-job agents reason over
surfaced steering signals (currently WAF detections) to decide routing and
per-asset execution, instead of a hardcoded Python router.

The reasoning guidance lives TEMPORARILY in STEERING_DECISIONS below (a
system-prompt section). It is slated to move into dedicated per-agent skills
(forward-decision D22); until those skills exist this inline section is the
single source of the thought process, shared by both agents.

Both decision functions are fail-open: any LLM/parse error returns the neutral
decision (no exclusions / run-all), so a steering blip degrades adaptivity,
never the run. They are only invoked with a non-empty signal list.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from agent.recon.steering import describe_job_kind

logger = logging.getLogger(__name__)

STEERING_DECISIONS = """\
## STEERING DECISIONS

You are steering an authorized reconnaissance pipeline in response to signals
the pipeline has already observed. Reason about the signals; do not restate them.

Domain primitives you must weigh:
- A BaseURL flagged `waf_protected` / `waf_detection` sits behind a WAF (e.g.
  Imperva/Incapsula) whose bot-blocking is IP-based. Direct requests from the
  pipeline's egress IP keep returning 403 regardless of rate, so pointing
  request-based crawlers at that host wastes the run and yields no new surface.
- A request-based crawler (katana/ffuf/kiterunner/graphql-cop) egresses from
  the pipeline IP; the agentic browser crawler (steel_crawl) egresses from
  separate cloud-browser infrastructure and presents a real browser, so it is
  the recovery path for a WAF-flagged host.
- Throttling a NOT-yet-flagged host is a preventive lever only; it cannot
  un-flag an already-flagged IP.

Decide the minimal intervention that keeps coverage high: route WAF-flagged
hosts away from request-based crawlers and toward the agentic crawler; leave
un-flagged hosts alone; throttle only as a deliberate preventive choice.
"""


class _JobExclusion(BaseModel):
    job: str
    exclude_urls: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    exclusions: list[_JobExclusion] = Field(default_factory=list)
    rationale: str = ""


class _AssetPlan(BaseModel):
    url: str
    run: bool = True
    throttle: bool = False


class PodSelection(BaseModel):
    plan: list[_AssetPlan] = Field(default_factory=list)
    rationale: str = ""


def _model(llm):
    if llm is not None:
        return llm
    from agent.app.llm.roles import chat_model_for  # noqa: PLC0415
    return chat_model_for("job_orchestrator")


def _signals_block(signals: list[dict]) -> str:
    return "\n".join(
        f"- {s['url']} [{s['macro_kind']}] {s.get('evidence', '')}" for s in signals
    )


def decide_routing(signals: list[dict], phase_jobs: list[str], *, llm=None) -> dict[str, list[str]]:
    """Recon-orchestrator agent: given live signals and the upcoming phase's
    jobs, return {job_name: [urls to exclude from that job]}. Fail-open to {}."""
    if not signals or not phase_jobs:
        return {}
    try:
        from langchain_core.messages import SystemMessage, HumanMessage  # noqa: PLC0415
        model = _model(llm).with_structured_output(RoutingDecision, method="function_calling")
        jobs_desc = "\n".join(f"- {j}: {describe_job_kind(j)}" for j in phase_jobs)
        human = (
            f"Signals (flagged BaseURLs):\n{_signals_block(signals)}\n\n"
            f"Upcoming phase jobs:\n{jobs_desc}\n\n"
            "Return, per job that should NOT receive a flagged host, the urls to exclude."
        )
        decision = model.invoke([SystemMessage(content=STEERING_DECISIONS), HumanMessage(content=human)])
        return {e.job: e.exclude_urls for e in decision.exclusions if e.job in phase_jobs}
    except Exception:
        logger.warning("decide_routing failed; no routing adaptation", exc_info=True)
        return {}


def decide_pod_selection(signals: list[dict], job_name: str, assets: list[dict], *, llm=None):
    """Recon-job agent: given the job's candidate assets and live signals,
    return (assets_to_run, throttle_urls). Fail-open to (assets, set())."""
    urls = [a.get("url") for a in assets if a.get("url")]
    if not signals or not urls:
        return assets, set()
    try:
        from langchain_core.messages import SystemMessage, HumanMessage  # noqa: PLC0415
        model = _model(llm).with_structured_output(PodSelection, method="function_calling")
        human = (
            f"Job: {job_name} ({describe_job_kind(job_name)}).\n"
            "Candidate BaseURLs:\n" + "\n".join(f"- {u}" for u in urls) + "\n\n"
            f"Signals (flagged BaseURLs):\n{_signals_block(signals)}\n\n"
            "For each candidate, decide run/skip and whether to throttle."
        )
        decision = model.invoke([SystemMessage(content=STEERING_DECISIONS), HumanMessage(content=human)])
        planned = {p.url: p for p in decision.plan}
        selected = [a for a in assets if planned.get(a.get("url"), _AssetPlan(url=a.get("url", ""))).run]
        throttle = {u for u, p in planned.items() if p.throttle}
        return selected, throttle
    except Exception:
        logger.warning("decide_pod_selection failed; running all assets", exc_info=True)
        return assets, set()
