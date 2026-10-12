"""W-b: the Assigner's absent-surface degradation.

When a Service's contract finds no related surface after a BOUNDED harvest
(surgical `graph_view` probes, url-path-filtered `search_http_history`), the
chain halts at `falsify_harvest` and records `no_surface`, rather than running
`candidate_owners`/`assign` on an empty premise - and the model never escalates
to the HTTP firehose.
"""
from __future__ import annotations

from polymerhus.analysis.assigner import (
    WORKFLOW,
    AssignmentOutcome,
    _halt_without_surface,
    _survivor_count,
    assign,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.reasoning_workflow import AnalysisTurn, Claim, run_workflow
from polymerhus.recon.domain.types import AssetDelta

BU = "https://shop"
INVENTORY = {
    "services": ["checkout"],
    "systems": [],
    "data_items": [],
    "service_contracts": {"checkout": "Take a basket to a paid order."},
}
_FALSIFY = next(sp for sp in WORKFLOW.sub_problems if sp.id == "falsify_harvest")


def _chunk():
    return Chunk(
        chunk_id="checkout",
        source_job="service:checkout",
        assets=(AssetDelta(type="Endpoint",
                           identity={"path": "/x", "method": "GET", "baseurl": BU}),),
    )


def test_survivor_count_counts_only_survive_verdicts():
    turn = AnalysisTurn(claims=[
        Claim(subject="a", assertion="", verdict="survive"),
        Claim(subject="b", assertion="", verdict="reject"),
        Claim(subject="c", assertion="", verdict="survive"),
    ])
    assert _survivor_count(turn) == 2
    assert _survivor_count(AnalysisTurn()) == 0
    assert _survivor_count(None) == 0


def test_halt_predicate_only_fires_on_falsify_with_no_survivors():
    rejected = AnalysisTurn(claims=[Claim(subject="a", assertion="", verdict="reject")])
    survived = AnalysisTurn(claims=[Claim(subject="a", assertion="", verdict="survive")])
    harvest = next(sp for sp in WORKFLOW.sub_problems if sp.id == "harvest_surface")
    assert _halt_without_surface(_FALSIFY, rejected) is True
    assert _halt_without_surface(_FALSIFY, survived) is False
    assert _halt_without_surface(harvest, rejected) is False


def test_workflow_halts_before_candidate_owners_without_survivors():
    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[0].content
        if "FALSIFY" in content:
            return AnalysisTurn(claims=[Claim(subject="GET /x", assertion="topical",
                                              verdict="reject")])
        return AnalysisTurn()

    run = run_workflow(WORKFLOW, invoke_fn=invoke, system_prompt="SYS",
                       halt_when=_halt_without_surface)
    assert "falsify_harvest" in run.turns
    assert "candidate_owners" not in run.turns
    assert "assign" not in run.turns


def test_workflow_proceeds_past_falsify_when_something_survives():
    seen: list[str] = []

    def invoke(messages, *, schema=None, system_prompt=None):
        content = messages[0].content
        for marker in ("HARVEST THE SURFACE", "FALSIFY THE HARVEST",
                       "CANDIDATE OWNERS", "EXTRACTION - assign"):
            if marker in content and marker not in seen:
                seen.append(marker)
        if "FALSIFY" in content:
            return AnalysisTurn(claims=[Claim(subject="GET /x", assertion="matches",
                                              verdict="survive")])
        return AnalysisTurn()

    run = run_workflow(WORKFLOW, invoke_fn=invoke, system_prompt="SYS",
                       halt_when=_halt_without_surface)
    assert "candidate_owners" in run.turns
    assert "assign" in run.turns


def test_assign_body_reports_no_surface_when_nothing_survives():
    def invoke(messages, *, schema=None, system_prompt=None):
        if "FALSIFY" in messages[0].content:
            return AnalysisTurn(claims=[Claim(subject="GET /x", assertion="topical",
                                              verdict="reject")])
        return AnalysisTurn()

    outcome = assign(_chunk(), invoke_fn=invoke, inventory=INVENTORY,
                     existing_slugs=frozenset({"checkout"}))
    assert isinstance(outcome, AssignmentOutcome)
    assert outcome.no_surface is True
    assert outcome.stats.kept == 0


def test_assign_body_is_not_no_surface_when_something_survives():
    def invoke(messages, *, schema=None, system_prompt=None):
        if "FALSIFY" in messages[0].content:
            return AnalysisTurn(claims=[Claim(subject="GET /x", assertion="matches",
                                              verdict="survive")])
        return AnalysisTurn()

    outcome = assign(_chunk(), invoke_fn=invoke, inventory=INVENTORY,
                     existing_slugs=frozenset({"checkout"}))
    assert outcome.no_surface is False
