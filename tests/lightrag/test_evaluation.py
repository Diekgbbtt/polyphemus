import json
from pathlib import Path

from lightrag.evaluation import GoldenSetV1, evaluate_answer
from lightrag.generation import AnswerBundleV1


def _golden() -> GoldenSetV1:
    path = Path("lightrag/examples/evaluation/golden-answers.v1.json")
    return GoldenSetV1.model_validate_json(path.read_text(encoding="utf-8"))


def _bundle() -> AnswerBundleV1:
    return AnswerBundleV1(
        scenario_id="SIM-01",
        summary="Bounded comparison hypothesis.",
        ontology_explanations=[
            {
                "entity_type": "AttackTechnique",
                "entity_name": "Object-level authorization comparison",
                "explanation": (
                    "Compare authorization behavior using Object ID Tampering, "
                    "looking for Adjacent Account ID Accessible signals."
                ),
                "evidence_references": ["2"],
                "confidence": "high",
            },
            {
                "entity_type": "VulnerabilityClass",
                "entity_name": "Broken Object-Level Authorization",
                "explanation": "The hypothesis does not confirm the vulnerability.",
                "evidence_references": ["2"],
                "confidence": "high",
            },
            {
                "entity_type": "AttackGoal",
                "entity_name": "Bounded comparison hypothesis",
                "explanation": "The goal is a bounded comparison.",
                "evidence_references": ["2"],
                "confidence": "medium",
            },
            {
                "entity_type": "ObservableSignal",
                "entity_name": "Adjacent Account ID Accessible",
                "explanation": "The signal is adjacent account access.",
                "evidence_references": ["2"],
                "confidence": "high",
            },
            {
                "entity_type": "TechnologyStack",
                "entity_name": "GraphQL and REST API",
                "explanation": "Two comparable surfaces.",
                "evidence_references": ["2"],
                "confidence": "high",
            },
            {
                "entity_type": "PreconditionEnvironment",
                "entity_name": "Tenant Scoped Object IDs",
                "explanation": "Client-supplied object ids.",
                "evidence_references": ["2"],
                "confidence": "high",
            },
        ],
        provenance_references=["2"],
        knowledge_gaps=["Resolver implementation unknown"],
        notes="",
    )


def test_golden_set_loads_four_entries():
    assert len(_golden().entries) == 4


def test_full_score_on_well_formed_answer():
    entry = _golden().by_scenario("SIM-01")
    result = evaluate_answer(
        _bundle(), entry=entry, allowed_reference_ids=["2", "l0:SIM-01:1"]
    )
    assert result.metrics.composite == 1.0
    assert result.metrics.forbidden_claim_violations == 0
    assert result.metrics.fabricated_references == []
    assert result.metrics.knowledge_gaps_satisfied is True


def test_negated_unsupported_claim_is_not_a_violation():
    entry = _golden().by_scenario("SIM-01")
    bundle = _bundle()
    bundle.summary = "We avoid confirmed BOLA claims."
    result = evaluate_answer(
        bundle, entry=entry, allowed_reference_ids=["2", "l0:SIM-01:1"]
    )
    assert result.metrics.forbidden_claim_violations == 0


def test_fabricated_reference_penalizes_citation_discipline():
    entry = _golden().by_scenario("SIM-01")
    bundle = _bundle()
    bundle.ontology_explanations[0].evidence_references = ["invented-42"]
    result = evaluate_answer(
        bundle, entry=entry, allowed_reference_ids=["2", "l0:SIM-01:1"]
    )
    assert "invented-42" in result.metrics.fabricated_references
    assert result.metrics.citation_discipline < 1.0


def test_negative_control_requires_empty_explanations():
    entry = _golden().by_scenario("SIM-04")
    bundle = AnswerBundleV1(
        scenario_id="SIM-04",
        summary="No hypothesis applies.",
        ontology_explanations=[
            {
                "entity_type": "AttackTechnique",
                "entity_name": "Object ID Tampering",
                "explanation": "should not exist",
                "evidence_references": [],
                "confidence": "low",
            }
        ],
        provenance_references=[],
        knowledge_gaps=["Inert data"],
        notes="",
    )
    result = evaluate_answer(bundle, entry=entry, allowed_reference_ids=[])
    assert result.metrics.no_hypothesis_compliant is False
