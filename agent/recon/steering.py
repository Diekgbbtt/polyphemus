"""Steering-signal vocabulary + job-kind descriptors (pure, dependency-free).

Names the Observation macro_kinds that steer the run and describes each job's
crawl kind so the LLM steering agents (steering_agent.py) can reason about
routing. This module makes NO decisions - it only labels signals and jobs.
"""
from __future__ import annotations

WAF_MACRO_KINDS = frozenset({"waf_protected", "waf_detection"})
REQUEST_CRAWLER_JOBS = frozenset({"katana", "ffuf", "kiterunner", "graphql-cop"})
AGENTIC_CRAWLER_JOBS = frozenset({"steel_crawl"})


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
