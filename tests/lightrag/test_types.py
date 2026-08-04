import pytest

from agent.lightrag.types import CompactMethodologyBundle, KnowledgeQuery, MethodologyBundle


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
        "entity_type": "DefensiveControl",
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


def test_knowledge_query_retrieval_prompt_preserves_fault_symptom_and_taxonomy_tags():
    query = KnowledgeQuery(
        query_id="q-symptom",
        pattern="target_state",
        objective="Map observed runtime behavior to testing techniques.",
        symptom="Login returns a SQL syntax error when a single quote is submitted.",
        taxonomy_tags=["sqli", "authentication"],
        fault_context={
            "vulnerability_hypothesis": "Injection weakness",
            "observed_conditions": ["Differentiated error response on login form"],
            "symptom": "Stack trace includes SQL parser details.",
            "symptoms": ["Response timing changes with boolean predicates."],
        },
    )

    prompt = query.to_retrieval_prompt()

    assert "Given Symptom -> Retrieve Testing Techniques" in prompt
    assert "fault_symptoms:" in prompt
    assert "Login returns a SQL syntax error when a single quote is submitted." in prompt
    assert "Stack trace includes SQL parser details." in prompt
    assert "Response timing changes with boolean predicates." in prompt
    assert "taxonomy_tags: ['sqli', 'authentication']" in prompt


def test_retrieval_mode_matches_lightrag_api_modes():
    query = KnowledgeQuery(
        query_id="q-naive",
        pattern="target_state",
        objective="Find applicable methodology with the best observed retrieval mode.",
        fault_context={
            "vulnerability_hypothesis": "Injection weakness",
            "observed_conditions": ["User-controlled input reaches a server-side operation"],
        },
        retrieval={"mode": "naive"},
    )

    assert query.retrieval.mode == "naive"

    mix_query = KnowledgeQuery(
        query_id="q-mix",
        pattern="target_state",
        objective="Find applicable methodology with the mix retrieval mode.",
        fault_context={
            "vulnerability_hypothesis": "Injection weakness",
            "observed_conditions": ["User-controlled input reaches a server-side operation"],
        },
        retrieval={"mode": "mix"},
    )
    assert mix_query.retrieval.mode == "mix"

    with pytest.raises(Exception):
        KnowledgeQuery(
            query_id="q-vector",
            pattern="target_state",
            objective="Reject non-API retrieval modes.",
            fault_context={
                "vulnerability_hypothesis": "Injection weakness",
                "observed_conditions": [
                    "User-controlled input reaches a server-side operation"
                ],
            },
            retrieval={"mode": "vector"},
        )


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


def test_invalid_pattern_entity_and_evidence_shapes_fail():
    with pytest.raises(Exception):
        KnowledgeQuery(
            query_id="q-bad",
            pattern="planner_choice",
            objective="Find methodology.",
            fault_context={"vulnerability_hypothesis": "x", "observed_conditions": ["y"]},
        )

    invalid_entity = dict(RELATION_STEP)
    invalid_entity["target"] = {
        "entity_type": "Service",
        "canonical_name": "Request filtering defense",
    }
    with pytest.raises(Exception):
        MethodologyBundle(
            query_id="q-1",
            summary="Candidate with invalid entity.",
            candidates=[
                {
                    "technique": {"canonical_name": "Alternate encoding probe"},
                    "relevance": {"relation_path": [invalid_entity], "rationale": "Matches."},
                    "evidence_refs": [EVIDENCE],
                }
            ],
        )

    blank_relation = dict(RELATION_STEP)
    blank_relation["relation"] = " "
    with pytest.raises(Exception):
        MethodologyBundle(
            query_id="q-1",
            summary="Candidate with blank relation.",
            candidates=[
                {
                    "technique": {"canonical_name": "Alternate encoding probe"},
                    "relevance": {"relation_path": [blank_relation], "rationale": "Matches."},
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


def test_compact_methodology_bundle_rejects_prose_and_more_than_three_candidates():
    candidate = {
        "technique": "JWT claim tampering",
        "relevance": "Matches accepted modified-token behavior.",
        "satisfied_conditions": ["JWT bearer flow is present"],
        "missing_conditions": ["Specific signing algorithm is unknown"],
        "observables": ["Accepted modified JWT"],
        "mitigation_checks": ["Reject mismatched JWT algorithms"],
        "confidence": "medium",
        "evidence_refs": ["wstg-sess-10:jwt-validation"],
    }

    bundle = CompactMethodologyBundle(
        query_id="q-jwt",
        summary="JWT validation evidence supports compact signature checks.",
        candidates=[candidate],
        source_tier="validated_base",
    )

    assert bundle.candidates[0].technique == "JWT claim tampering"

    with pytest.raises(Exception):
        CompactMethodologyBundle(
            query_id="q-long",
            summary="I need to synthesize a comprehensive answer from the graph.",
            candidates=[candidate],
        )

    with pytest.raises(Exception):
        CompactMethodologyBundle(
            query_id="q-many",
            summary="Too many candidates should be rejected.",
            candidates=[candidate, candidate, candidate, candidate],
        )

    verbose_candidate = dict(candidate)
    verbose_candidate["relevance"] = "x" * 281
    with pytest.raises(Exception):
        CompactMethodologyBundle(
            query_id="q-verbose",
            summary="Candidate fields must stay compact.",
            candidates=[verbose_candidate],
        )
