from agent.lightrag.service import retrieve_methodology
from agent.lightrag.types import KnowledgeQuery, MethodologyBundle


EVIDENCE = {"source_id": "guide", "locator": "section 1"}


def make_query(pattern):
    context_by_pattern = {
        "target_state": {
            "vulnerability_hypothesis": "Injection weakness",
            "observed_conditions": ["User-controlled input reaches a query"],
        },
        "bypass": {
            "blocked_technique": "Initial injection probe",
            "defenses_present": ["Request filtering defense"],
        },
        "chaining": {
            "desired_condition": "Object identifier available",
            "available_capabilities": ["Authenticated low-privilege session"],
        },
    }
    return KnowledgeQuery(
        query_id=f"q-{pattern}",
        pattern=pattern,
        objective=f"Retrieve {pattern} methodology.",
        fault_context=context_by_pattern[pattern],
    )


class FakeRetriever:
    def __init__(self):
        self.seen_patterns = []

    def retrieve(self, query):
        self.seen_patterns.append(query.pattern)
        return {
            "summary": f"Methodology for {query.pattern}",
            "candidates": [
                {
                    "technique": {"canonical_name": f"{query.pattern} technique"},
                    "relevance": {"relation_path": [], "rationale": "Matches query context."},
                    "applicability": {"satisfied_conditions": ["Context supplied"]},
                    "confidence": "medium",
                    "evidence_refs": [EVIDENCE],
                }
            ],
        }


class FakeStore:
    def __init__(self):
        self.saved = []

    def save_methodology_bundle(self, run_id, query, bundle):
        self.saved.append((run_id, query, bundle))
        return len(self.saved)


def test_all_supported_patterns_use_one_generic_service_path():
    retriever = FakeRetriever()
    store = FakeStore()

    bundles = [
        retrieve_methodology(
            make_query(pattern),
            run_id="run-1",
            retriever=retriever,
            artifact_store=store,
        )
        for pattern in ("target_state", "bypass", "chaining")
    ]

    assert [bundle.query_id for bundle in bundles] == ["q-target_state", "q-bypass", "q-chaining"]
    assert retriever.seen_patterns == ["target_state", "bypass", "chaining"]
    assert len(store.saved) == 3
    assert all(isinstance(saved[2], MethodologyBundle) for saved in store.saved)


def test_service_accepts_mapping_query_and_persists_packaged_bundle():
    store = FakeStore()
    bundle = retrieve_methodology(
        {
            "query_id": "q-map",
            "pattern": "bypass",
            "objective": "Find bypass methodology.",
            "fault_context": {
                "blocked_technique": "Initial probe",
                "defenses_present": ["Request filtering defense"],
            },
        },
        run_id="run-map",
        retriever=lambda query: [
            {
                "technique": "Alternate encoding probe",
                "rationale": "It targets the observed filtering behavior.",
                "evidence_refs": [EVIDENCE],
            }
        ],
        artifact_store=store,
    )

    assert bundle.query_id == "q-map"
    assert bundle.candidates[0].technique.canonical_name == "Alternate encoding probe"
    assert store.saved[0][0] == "run-map"
