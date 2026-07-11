"""Shared steering primitives for the recon agents (pure, dependency-free).

This module owns only what is genuinely SHARED and decision-free: the WAF
signal vocabulary, job-kind descriptors, the shared domain reasoning
(`STEERING_PRIMITIVES`), and two thin helpers (signal formatting + model
resolution). It makes NO steering decisions.

The decisions themselves live with their OWNING agent per the responsibility
taxonomy: macro cross-job routing in the recon-orchestrator agent
(`orchestrator_agent.py`), per-asset run/skip/throttle in the recon-job agent
(`job_agent.py`). Each agent frames `STEERING_PRIMITIVES` for its own scope.
Moving that framing into dedicated per-agent skills is forward-decision D22.
"""
from __future__ import annotations

WAF_MACRO_KINDS = frozenset({"waf_protected", "waf_detection"})
REQUEST_CRAWLER_JOBS = frozenset({"katana", "ffuf", "kiterunner", "graphql-cop"})
AGENTIC_CRAWLER_JOBS = frozenset({"steel_crawl"})

# Shared domain reasoning both steering agents weigh. Each agent embeds this in
# its own decision-framed system prompt (see orchestrator_agent / job_agent);
# the facts are shared reference, the decision framing is per-agent.
STEERING_PRIMITIVES = """\
Domain primitives:
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
"""


def is_waf_signal(macro_kind: str) -> bool:
    """True if an Observation macro_kind marks its anchor host as WAF-protected."""
    return macro_kind in WAF_MACRO_KINDS


def describe_job_kind(job_name: str) -> str:
    """One-line descriptor of a job's crawl kind, for LLM steering context."""
    if job_name in REQUEST_CRAWLER_JOBS:
        return "request-based crawler (many direct HTTP requests from the pipeline egress IP)"
    if job_name in AGENTIC_CRAWLER_JOBS:
        return "agentic browser crawler (drives a real cloud browser from separate egress infrastructure)"
    return "other recon tool"


def format_signals(signals: list[dict]) -> str:
    """Render steering signals into a prompt block, one line per flagged host."""
    return "\n".join(
        f"- {s['url']} [{s['macro_kind']}] {s.get('evidence', '')}" for s in signals
    )


def resolve_model(role: str, llm=None):
    """Return the injected `llm`, else the chat model for `role`.

    The import is lazy (no network/provider at import time). Taking `role` as a
    parameter is the seam that lets the orchestrator and job agents diverge onto
    distinct model roles later (D22); both pass "job_orchestrator" for now.
    """
    if llm is not None:
        return llm
    from agent.app.llm.roles import chat_model_for  # noqa: PLC0415
    return chat_model_for(role)
