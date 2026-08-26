import lightrag as lightrag

from lightrag.packager import package_methodology
from lightrag.types import KnowledgeQuery


EVIDENCE = {
    "source_id": "source-1",
    "locator": "section-1",
    "document_title": "Methodology Source",
}


class FakeLightRAGClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.queries = []

    def query(self, query, **kwargs):
        self.queries.append({"query": query, **kwargs})
        if self.responses:
            return self.responses.pop(0)
        return {
            "summary": "No response.",
            "candidates": [],
            "knowledge_gaps": ["No match."],
        }


def _candidate(name):
    return {
        "technique": {"canonical_name": name},
        "relevance": {
            "relation_path": [],
            "rationale": "Matches the supplied symptom.",
        },
        "evidence_refs": [EVIDENCE],
    }


def _target_query(**overrides):
    payload = {
        "query_id": "q-target",
        "pattern": "target_state",
        "objective": "Map the observed behavior to testing techniques.",
        "fault_context": {
            "vulnerability_hypothesis": "Injection weakness",
            "observed_conditions": ["User-controlled input changes the response"],
        },
    }
    payload.update(overrides)
    return KnowledgeQuery(**payload)


def _retriever_class():
    assert hasattr(lightrag, "RoutedMethodologyRetriever")
    return lightrag.RoutedMethodologyRetriever


def _test_formatter(query, *, raw_output, source_tier, source_chunks, **_kwargs):
    payload = dict(raw_output)
    payload["source_tier"] = source_tier
    payload["candidates"] = [
        {**candidate, "source_tier": source_tier}
        for candidate in payload.get("candidates", [])
    ]
    return package_methodology(query, payload)


def test_routed_retriever_queries_base_only_for_generic_target_state():
    retriever_cls = _retriever_class()
    base = FakeLightRAGClient(
        {"summary": "Base match.", "candidates": [_candidate("Error-Based Probe")]}
    )
    writeups = FakeLightRAGClient(
        {"summary": "Overlay match.", "candidates": [_candidate("JWT Token Forgery")]}
    )
    query = _target_query(
        symptom="Search returns a generic validation error.",
        taxonomy_tags=["input-validation"],
    )

    bundle = retriever_cls(
        base_client=base,
        writeup_client=writeups,
        min_base_candidates=1,
        formatter=_test_formatter,
    ).retrieve_methodology(query)

    assert len(base.queries) == 1
    assert writeups.queries == []
    assert "Given Symptom -> Retrieve Testing Techniques" in base.queries[0]["query"]
    assert "Search returns a generic validation error." in base.queries[0]["query"]
    assert base.queries[0]["extra"]["only_need_context"] is True
    assert bundle.candidates[0].source_tier == "validated_base"
    assert bundle.retrieval_metadata["sources_queried"] == ["base"]


def test_routed_retriever_queries_overlay_for_matching_symptom_or_taxonomy_tag():
    retriever_cls = _retriever_class()
    base = FakeLightRAGClient(
        {"summary": "Base match.", "candidates": [_candidate("JWT Claim Inspection")]}
    )
    writeups = FakeLightRAGClient(
        {"summary": "Overlay match.", "candidates": [_candidate("JWT Token Forgery")]}
    )
    query = _target_query(
        symptom="A modified JWT is still accepted after changing the role claim.",
        taxonomy_tags=["jwt"],
    )

    bundle = retriever_cls(
        base_client=base,
        writeup_client=writeups,
        min_base_candidates=1,
        formatter=_test_formatter,
    ).retrieve_methodology(query)

    assert len(writeups.queries) == 1
    assert writeups.queries[0]["extra"]["only_need_context"] is True
    assert [candidate.source_tier for candidate in bundle.candidates] == [
        "validated_base",
        "review_overlay",
    ]
    assert bundle.retrieval_metadata["overlay_trigger_reason"] == ["concept:jwt"]


def test_routed_retriever_queries_overlay_for_bypass_pattern_even_with_base_candidates():
    retriever_cls = _retriever_class()
    base = FakeLightRAGClient(
        {"summary": "Base match.", "candidates": [_candidate("Alternate Encoding Probe")]}
    )
    writeups = FakeLightRAGClient(
        {"summary": "Overlay match.", "candidates": [_candidate("Filter Bypass Variant")]}
    )
    query = KnowledgeQuery(
        query_id="q-bypass",
        pattern="bypass",
        objective="Find a bypass for the blocked probe.",
        fault_context={
            "blocked_technique": "Initial injection probe",
            "defenses_present": ["Request filtering defense"],
        },
    )

    bundle = retriever_cls(
        base_client=base,
        writeup_client=writeups,
        min_base_candidates=1,
        formatter=_test_formatter,
    ).retrieve_methodology(query)

    assert len(writeups.queries) == 1
    assert bundle.retrieval_metadata["overlay_trigger_reason"] == ["pattern:bypass"]


def test_routed_retriever_merges_with_base_precedence_and_threshold_trigger():
    retriever_cls = _retriever_class()
    base = FakeLightRAGClient(
        {"summary": "Thin base match.", "candidates": [_candidate("SSRF URL Probe")]}
    )
    writeups = FakeLightRAGClient(
        {
            "summary": "Overlay match.",
            "candidates": [
                _candidate("SSRF URL Probe"),
                _candidate("SSRF Localhost Probing"),
            ],
        }
    )
    query = _target_query(
        symptom="Server fetches a supplied URL and returns a timing difference."
    )

    bundle = retriever_cls(
        base_client=base,
        writeup_client=writeups,
        min_base_candidates=2,
        formatter=_test_formatter,
    ).retrieve_methodology(query)

    assert [candidate.technique.canonical_name for candidate in bundle.candidates] == [
        "SSRF URL Probe",
        "SSRF Localhost Probing",
    ]
    assert [candidate.source_tier for candidate in bundle.candidates] == [
        "validated_base",
        "review_overlay",
    ]
    assert bundle.retrieval_metadata["overlay_trigger_reason"] == [
        "base_candidates_below_threshold"
    ]


def test_routed_retriever_caps_merged_candidates_to_three_with_base_precedence():
    retriever_cls = _retriever_class()
    base = FakeLightRAGClient(
        {
            "summary": "Base match.",
            "candidates": [
                _candidate("Base Technique One"),
                _candidate("Base Technique Two"),
            ],
        }
    )
    writeups = FakeLightRAGClient(
        {
            "summary": "Overlay match.",
            "candidates": [
                _candidate("Overlay Technique One"),
                _candidate("Overlay Technique Two"),
            ],
        }
    )
    query = _target_query(symptom="A modified JWT is accepted.", taxonomy_tags=["jwt"])

    bundle = retriever_cls(
        base_client=base,
        writeup_client=writeups,
        min_base_candidates=1,
        formatter=_test_formatter,
    ).retrieve_methodology(query)

    assert [candidate.technique.canonical_name for candidate in bundle.candidates] == [
        "Base Technique One",
        "Base Technique Two",
        "Overlay Technique One",
    ]
    assert bundle.source_tier == "review_overlay"
