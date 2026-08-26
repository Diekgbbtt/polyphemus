from lightrag.formatter import format_methodology_context
from lightrag.types import CompactMethodologyBundle, KnowledgeQuery


SOURCE_CHUNK = {
    "chunk_id": "chunk-1",
    "source_id": "wstg-sess-10",
    "locator": "Testing JSON Web Tokens",
    "text": "JWT signature validation rejects modified claims and unsupported algorithms.",
}


def _query():
    return KnowledgeQuery(
        query_id="q-jwt",
        pattern="target_state",
        objective="Retrieve JWT validation methodology.",
        symptom="Modified role claims are accepted.",
        taxonomy_tags=["jwt"],
        fault_context={
            "vulnerability_hypothesis": "JWT validation weakness",
            "observed_conditions": ["Role claim change persists"],
            "defenses_present": ["Request filter"],
        },
    )


class FakeStructuredLLM:
    def __init__(self, payload):
        self.payload = payload

    def with_structured_output(self, schema, *, method):
        self.schema = schema
        self.method = method
        return self

    def invoke(self, messages):
        assert self.schema is CompactMethodologyBundle
        assert self.method == "function_calling"
        assert "Retrieved context:" in messages[-1].content
        return self.payload


class FailingStructuredLLM(FakeStructuredLLM):
    def invoke(self, messages):
        raise RuntimeError("formatter unavailable")


def test_format_methodology_context_returns_valid_ontology_bundle_from_compact_output():
    compact = CompactMethodologyBundle(
        query_id="q-jwt",
        summary="JWT evidence supports signature and claim validation checks.",
        candidates=[
            {
                "technique": "JWT claim tampering",
                "relevance": "Matches accepted modified-token behavior.",
                "satisfied_conditions": ["JWT bearer flow is present"],
                "missing_conditions": ["Specific signing algorithm is unknown"],
                "observables": ["Accepted modified JWT"],
                "mitigation_checks": ["Reject mismatched JWT algorithms"],
                "confidence": "medium",
                "evidence_refs": ["wstg-sess-10"],
            }
        ],
        source_tier="validated_base",
    )

    bundle = format_methodology_context(
        _query(),
        raw_lightrag_context="JWT signature validation context.",
        source_tier="validated_base",
        source_chunks=[SOURCE_CHUNK],
        llm=FakeStructuredLLM(compact),
    )

    assert bundle.query_id == "q-jwt"
    assert bundle.candidates[0].technique.canonical_name == "JWT claim tampering"
    assert bundle.candidates[0].observables == ["Accepted modified JWT"]
    assert bundle.candidates[0].mitigation_checks == ["Reject mismatched JWT algorithms"]
    assert bundle.candidates[0].source_tier == "validated_base"
    assert bundle.source_chunks[0].source_id == "wstg-sess-10"
    assert bundle.retrieval_metadata["formatter"] == "structured_methodology_bundle"


def test_format_methodology_context_accepts_bracketed_evidence_ref_labels():
    compact = CompactMethodologyBundle(
        query_id="q-jwt",
        summary="JWT evidence supports signature and claim validation checks.",
        candidates=[
            {
                "technique": "JWT claim tampering",
                "relevance": "Matches accepted modified-token behavior.",
                "satisfied_conditions": ["JWT bearer flow is present"],
                "missing_conditions": [],
                "observables": ["Accepted modified JWT"],
                "mitigation_checks": ["Reject mismatched JWT algorithms"],
                "confidence": "medium",
                "evidence_refs": [
                    "[chunk-1] Testing JSON Web Tokens",
                    "Testing JSON Web Tokens",
                ],
            }
        ],
        source_tier="validated_base",
    )

    bundle = format_methodology_context(
        _query(),
        raw_lightrag_context="JWT signature validation context.",
        source_tier="validated_base",
        source_chunks=[SOURCE_CHUNK],
        llm=FakeStructuredLLM(compact),
    )

    assert bundle.candidates[0].evidence_refs[0].source_id == "wstg-sess-10"
    assert len(bundle.candidates[0].evidence_refs) == 1


def test_format_methodology_context_accepts_prefixed_evidence_ref_labels():
    compact = CompactMethodologyBundle(
        query_id="q-jwt",
        summary="JWT evidence supports signature and claim validation checks.",
        candidates=[
            {
                "technique": "JWT claim tampering",
                "relevance": "Matches accepted modified-token behavior.",
                "satisfied_conditions": ["JWT bearer flow is present"],
                "missing_conditions": [],
                "observables": ["Accepted modified JWT"],
                "mitigation_checks": ["Reject mismatched JWT algorithms"],
                "confidence": "medium",
                "evidence_refs": ["reference_id: chunk-1"],
            }
        ],
        source_tier="validated_base",
    )

    bundle = format_methodology_context(
        _query(),
        raw_lightrag_context="JWT signature validation context.",
        source_tier="validated_base",
        source_chunks=[SOURCE_CHUNK],
        llm=FakeStructuredLLM(compact),
    )

    assert bundle.candidates[0].evidence_refs[0].source_id == "wstg-sess-10"


def test_format_methodology_context_falls_back_to_knowledge_gap_on_formatter_failure():
    bundle = format_methodology_context(
        _query(),
        raw_lightrag_context="JWT signature validation context.",
        source_tier="review_overlay",
        source_chunks=[SOURCE_CHUNK],
        llm=FailingStructuredLLM(None),
    )

    assert bundle.candidates == []
    assert bundle.source_tier == "review_overlay"
    assert bundle.source_chunks[0].source_id == "wstg-sess-10"
    assert bundle.knowledge_gaps == [
        "Formatter could not produce a validated compact MethodologyBundle."
    ]
    assert bundle.retrieval_metadata["formatter_error"]["type"] == "RuntimeError"


def test_format_methodology_context_rejects_unresolved_evidence_refs():
    compact = CompactMethodologyBundle(
        query_id="q-jwt",
        summary="JWT evidence supports signature validation checks.",
        candidates=[
            {
                "technique": "JWT claim tampering",
                "relevance": "Matches accepted modified-token behavior.",
                "satisfied_conditions": ["JWT bearer flow is present"],
                "missing_conditions": [],
                "observables": ["Accepted modified JWT"],
                "mitigation_checks": ["Reject mismatched JWT algorithms"],
                "confidence": "medium",
                "evidence_refs": ["missing-ref"],
            }
        ],
        source_tier="validated_base",
    )

    bundle = format_methodology_context(
        _query(),
        raw_lightrag_context="JWT signature validation context.",
        source_tier="validated_base",
        source_chunks=[SOURCE_CHUNK],
        llm=FakeStructuredLLM(compact),
    )

    assert bundle.candidates == []
    assert bundle.knowledge_gaps == [
        "Formatter could not produce a validated compact MethodologyBundle."
    ]
    assert bundle.retrieval_metadata["formatter_error"]["type"] == "ValueError"


def test_format_methodology_context_does_not_accept_raw_candidates_as_structured_output():
    legacy_raw = {
        "summary": "Legacy structured output.",
        "candidates": [
            {
                "technique": "JWT claim tampering",
                "relevance": "Matches accepted modified-token behavior.",
                "evidence_refs": ["wstg-sess-10"],
            }
        ],
    }

    bundle = format_methodology_context(
        _query(),
        raw_lightrag_context="JWT signature validation context.",
        source_tier="validated_base",
        source_chunks=[SOURCE_CHUNK],
        raw_output=legacy_raw,
        llm=FailingStructuredLLM(None),
    )

    assert bundle.candidates == []
    assert bundle.knowledge_gaps == [
        "Formatter could not produce a validated compact MethodologyBundle."
    ]
    assert bundle.retrieval_metadata["formatter_error"]["type"] == "RuntimeError"
