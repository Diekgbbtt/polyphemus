import pytest

from agent.lightrag.types import KnowledgeQuery, MethodologyBundle


EVIDENCE = {
    "source_id": "methodology-guide",
    "locator": "section: request filtering",
    "document_title": "Methodology Guide",
}

RELATION_STEP = {
    "source": {
        "entity_type": "AttackTechnique",
        "canonical_name": "Alternate encoding probe",
    },
    "relation": "bypasses",
    "target": {
        "entity_type": "DefensiveTechnology",
        "canonical_name": "Request filtering defense",
    },
    "applicability": ["Input reaches a request filter"],
    "limitations": ["Filter normalization may still reject the payload"],
    "evidence_refs": [EVIDENCE],
    "confidence": "medium",
}


def test_target_state_query_validates():
    query = KnowledgeQuery(
        query_id="q-target",
        pattern="target_state",
        objective="Find applicable methodology for the current hypothesis.",
        fault_context={
            "vulnerability_hypothesis": "Injection weakness",
            "observed_conditions": ["User-controlled input reaches a server-side operation"],
            "defenses_present": ["Web application firewall"],
        },
    )

    assert query.pattern == "target_state"
    assert query.retrieval.mode == "hybrid"


def test_pattern_specific_required_context_is_enforced():
    with pytest.raises(Exception):
        KnowledgeQuery(
            query_id="q-bad",
            pattern="target_state",
            objective="Find applicable methodology.",
            fault_context={"vulnerability_hypothesis": "Injection weakness"},
        )

    with pytest.raises(Exception):
        KnowledgeQuery(
            query_id="q-bad",
            pattern="bypass",
            objective="Find a bypass.",
            fault_context={"blocked_technique": "Initial probe"},
        )

    with pytest.raises(Exception):
        KnowledgeQuery(
            query_id="q-bad",
            pattern="chaining",
            objective="Find a chain.",
            fault_context={"desired_condition": "Object identifier available"},
        )


def test_invalid_pattern_entity_relation_and_evidence_shapes_fail():
    with pytest.raises(Exception):
        KnowledgeQuery(
            query_id="q-bad",
            pattern="planner_choice",
            objective="Find methodology.",
            fault_context={"vulnerability_hypothesis": "x", "observed_conditions": ["y"]},
        )

    invalid_relation = dict(RELATION_STEP)
    invalid_relation["source"] = {
        "entity_type": "DefensiveTechnology",
        "canonical_name": "Request filtering defense",
    }
    with pytest.raises(Exception):
        MethodologyBundle(
            query_id="q-1",
            summary="Candidate with invalid relation.",
            candidates=[
                {
                    "technique": {"canonical_name": "Alternate encoding probe"},
                    "relevance": {"relation_path": [invalid_relation], "rationale": "Matches."},
                    "evidence_refs": [EVIDENCE],
                }
            ],
        )

    with pytest.raises(Exception):
        MethodologyBundle(
            query_id="q-1",
            summary="Candidate without evidence.",
            candidates=[
                {
                    "technique": {"canonical_name": "Alternate encoding probe"},
                    "relevance": {"relation_path": [], "rationale": "Matches."},
                    "evidence_refs": [],
                }
            ],
        )


def test_methodology_bundle_validates_candidate_and_empty_gap_shapes():
    bundle = MethodologyBundle(
        query_id="q-1",
        summary="Use evidence-backed alternatives only.",
        candidates=[
            {
                "technique": {"canonical_name": "Alternate encoding probe", "aliases": ["Encoding"]},
                "relevance": {"relation_path": [RELATION_STEP], "rationale": "Bypasses filter."},
                "applicability": {
                    "satisfied_conditions": ["Input reaches a request filter"],
                    "missing_conditions": ["Origin behavior confirmed"],
                    "conflicting_conditions": [],
                },
                "expected_effect": {"produces_condition": "Filter bypass hypothesis"},
                "confidence": "medium",
                "evidence_refs": [EVIDENCE],
            }
        ],
        source_chunks=[
            {
                "chunk_id": "chunk-1",
                "source_id": "methodology-guide",
                "locator": "section: request filtering",
                "text": "Short source excerpt.",
            }
        ],
    )

    assert bundle.candidates[0].technique.canonical_name == "Alternate encoding probe"

    empty = MethodologyBundle(
        query_id="q-empty",
        summary="No evidence-backed candidate was found.",
        candidates=[],
        knowledge_gaps=["Need a confirmed target condition"],
    )
    assert empty.knowledge_gaps == ["Need a confirmed target condition"]

    with pytest.raises(Exception):
        MethodologyBundle(query_id="q-empty", summary="No candidates.", candidates=[])
