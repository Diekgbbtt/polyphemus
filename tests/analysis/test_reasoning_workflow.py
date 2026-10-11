"""Unit tier for the reasoning-workflow core (`reasoning_workflow.py`, T2).

The three proposer roles run a decomposed chain of sub-problems, one LLM turn
each, every turn speaking the ONE structured envelope `AnalysisTurn`. These tests
pin the value objects, the `AnalysisTurn` -> `L1DeltaBatch` mapper, the workflow
validation, and the verbatim-injection contract - all without a live model,
mirroring the rest of the analysis unit tier.
"""
from __future__ import annotations

import pytest

from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    L1DeltaBatch,
    ServiceProposal,
)
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.reasoning_workflow import (
    AnalysisTurn,
    Claim,
    ReasoningWorkflow,
    SubProblem,
    run_workflow,
    to_delta_batch,
)


# --- the envelope -------------------------------------------------------------

def test_analysis_turn_is_a_superset_of_the_delta_batch():
    """`AnalysisTurn` is the LLM-facing envelope; `L1DeltaBatch` stays the pure
    curator input. The superset relation is structural, not a copy: every delta
    field is present, plus `claims`."""
    turn = AnalysisTurn()
    assert set(L1DeltaBatch.model_fields) <= set(AnalysisTurn.model_fields)
    assert "claims" in AnalysisTurn.model_fields
    assert "claims" not in L1DeltaBatch.model_fields
    assert turn.claims == []


def test_mapper_drops_claims_and_keeps_the_delta_lists():
    turn = AnalysisTurn(
        services=[ServiceProposal(business_function_slug="checkout")],
        aggregates=[AggregatesProposal(
            service_slug="checkout", l0=L0Ref(label="Endpoint", identity={"path": "/x"}),
            confidence=0.9, evidence_refs=["path segment /x"],
        )],
        claims=[Claim(subject="checkout", assertion="owns /x", evidence="/x", verdict="0.9")],
    )
    batch = to_delta_batch(turn)
    assert isinstance(batch, L1DeltaBatch)
    assert not hasattr(batch, "claims")
    assert [s.business_function_slug for s in batch.services] == ["checkout"]
    assert [a.service_slug for a in batch.aggregates] == ["checkout"]
    assert batch.aggregates[0].confidence == 0.9


# --- the workflow validation --------------------------------------------------

def _sp(id, *, emit=("claims",), depends_on=(), inject=()):
    return SubProblem(id=id, name=id, prompt=f"do {id}", emit=emit,
                      depends_on=depends_on, inject=inject)


def test_workflow_rejects_a_duplicate_id():
    with pytest.raises(ValueError, match="duplicate"):
        ReasoningWorkflow(role_id="r", sub_problems=(_sp("a"), _sp("a")))


def test_workflow_rejects_a_depends_on_naming_a_non_earlier_subproblem():
    with pytest.raises(ValueError, match="earlier"):
        ReasoningWorkflow(role_id="r", sub_problems=(
            _sp("a", depends_on=("b",)),
            _sp("b"),
        ))


def test_workflow_rejects_an_undeclared_emit():
    with pytest.raises(ValueError, match="emit"):
        ReasoningWorkflow(role_id="r", sub_problems=(_sp("a", emit=("nonsense",)),))


def test_a_valid_workflow_accepts_ordered_dependencies():
    wf = ReasoningWorkflow(role_id="r", sub_problems=(
        _sp("a"),
        _sp("b", depends_on=("a",), emit=("aggregates",)),
    ))
    assert [sp.id for sp in wf.sub_problems] == ["a", "b"]


# --- the executor: verbatim dependency injection ------------------------------

def test_dependency_artifacts_are_injected_verbatim_and_every_turn_is_structured():
    """The ADR D24 contract: a sub-problem's injected inputs are the prior turns'
    artifacts rendered VERBATIM into its human message, and every turn speaks the
    one structured envelope."""
    wf = ReasoningWorkflow(role_id="test", sub_problems=(
        SubProblem(id="a", name="a", prompt="FIRST", emit=("claims",)),
        SubProblem(id="b", name="b", prompt="SECOND", inject=("a",),
                   emit=("aggregates",), depends_on=("a",)),
    ))
    seen: list[tuple[str, object]] = []

    def invoke(messages, *, schema=None, system_prompt=None):
        seen.append((messages[0].content, schema))
        if len(seen) == 1:
            return AnalysisTurn(claims=[Claim(
                subject="GET /x", assertion="owned by checkout",
                evidence="path segment /x", verdict="checkout 0.9")])
        return AnalysisTurn()

    run = run_workflow(wf, invoke_fn=invoke, system_prompt="SYS")

    # every turn binds the SAME structured envelope
    assert [s for _c, s in seen] == [AnalysisTurn, AnalysisTurn]
    second = seen[1][0]
    assert "SECOND" in second
    # the first turn's claims are re-injected verbatim into the second turn
    for fragment in ("GET /x", "owned by checkout", "path segment /x", "checkout 0.9"):
        assert fragment in second, fragment
    assert run.turns["a"].claims[0].verdict == "checkout 0.9"


def test_a_none_turn_still_runs_the_chain_and_records_none():
    wf = ReasoningWorkflow(role_id="test", sub_problems=(
        _sp("a"),
        _sp("b", depends_on=("a",), emit=("aggregates",)),
    ))
    calls = {"n": 0}

    def invoke(messages, *, schema=None, system_prompt=None):
        calls["n"] += 1
        return None

    run = run_workflow(wf, invoke_fn=invoke, system_prompt="SYS")
    assert calls["n"] == 2
    assert run.turns == {"a": None, "b": None}


def test_base_artifacts_are_seeded_and_injected():
    wf = ReasoningWorkflow(role_id="test", sub_problems=(
        SubProblem(id="a", name="a", prompt="FIRST", inject=("service_slice",),
                   emit=("claims",)),
    ))

    def invoke(messages, *, schema=None, system_prompt=None):
        return AnalysisTurn()

    run = run_workflow(wf, invoke_fn=invoke, system_prompt="SYS",
                       base_artifacts={"service_slice": "THE SERVICE SLICE"})
    assert run.artifacts["service_slice"] == "THE SERVICE SLICE"


# --- the per-role chains (spec section 3.3) -----------------------------------

def test_assigner_workflow_matches_the_spec_table():
    from polymerhus.analysis.assigner import WORKFLOW

    by_id = {sp.id: sp for sp in WORKFLOW.sub_problems}
    assert [sp.id for sp in WORKFLOW.sub_problems] == ["candidate_owners", "assign"]
    assert by_id["candidate_owners"].emit == ("claims",)
    assert by_id["assign"].emit == ("aggregates",)
    assert by_id["assign"].depends_on == ("candidate_owners",)


def test_mechanism_typist_workflow_matches_the_spec_table():
    from polymerhus.analysis.mechanism_typist import WORKFLOW

    by_id = {sp.id: sp for sp in WORKFLOW.sub_problems}
    assert [sp.id for sp in WORKFLOW.sub_problems] == [
        "mechanism_hypotheses", "page_clusters", "systems_extract", "link"]
    assert by_id["mechanism_hypotheses"].emit == ("claims",)
    assert by_id["page_clusters"].emit == ("claims",)
    assert by_id["systems_extract"].emit == ("systems",)
    assert by_id["link"].emit == ("system_edges",)
    assert by_id["systems_extract"].depends_on == ("mechanism_hypotheses", "page_clusters")
    assert by_id["link"].depends_on == ("systems_extract",)


def test_data_modeller_workflow_matches_the_spec_table():
    from polymerhus.analysis.data_modeller import WORKFLOW

    by_id = {sp.id: sp for sp in WORKFLOW.sub_problems}
    assert [sp.id for sp in WORKFLOW.sub_problems] == [
        "record_hypotheses", "data_extract", "flow_shape", "flow_extract"]
    assert by_id["record_hypotheses"].emit == ("claims",)
    assert by_id["data_extract"].emit == ("data_items", "surfaces_at")
    assert by_id["flow_shape"].emit == ("claims",)
    assert by_id["flow_extract"].emit == ("data_flows", "data_relationships")
    assert by_id["data_extract"].depends_on == ("record_hypotheses",)
    assert by_id["flow_shape"].depends_on == ("data_extract",)
    assert by_id["flow_extract"].depends_on == ("flow_shape", "data_extract")
