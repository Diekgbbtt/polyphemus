from polymerhus.lightrag.service import retrieve_methodology
from polymerhus.lightrag.types import KnowledgeQuery


class FakeRetriever:
    def retrieve(self, query):
        return {
            "summary": "Use a documented prerequisite-establishing technique.",
            "candidates": [
                {
                    "technique": {"canonical_name": "Identifier enumeration"},
                    "relevance": {
                        "relation_path": [],
                        "rationale": "It can establish the desired object identifier condition.",
                    },
                    "applicability": {
                        "satisfied_conditions": ["Authenticated low-privilege session"],
                        "missing_conditions": ["Object identifier format unknown"],
                    },
                    "expected_effect": {
                        "produces_condition": "Object identifier belonging to another account"
                    },
                    "confidence": "medium",
                    "evidence_refs": [{"source_id": "guide", "locator": "section: chaining"}],
                }
            ],
            "knowledge_gaps": ["Confirm identifier format before planning execution"],
        }


class FakeArtifactStore:
    def __init__(self):
        self.rows = []

    def save_methodology_bundle(self, run_id, query, bundle):
        self.rows.append({"run_id": run_id, "query_id": query.query_id, "bundle": bundle})
        return len(self.rows)


def test_independent_knowledge_query_to_persisted_methodology_bundle():
    query = KnowledgeQuery(
        query_id="q-e2e",
        pattern="chaining",
        objective="Find a methodology step that establishes the missing identifier condition.",
        fault_context={
            "desired_condition": "Object identifier belonging to another account",
            "available_capabilities": ["Authenticated low-privilege session"],
        },
    )
    store = FakeArtifactStore()

    bundle = retrieve_methodology(
        query,
        run_id="run-e2e",
        retriever=FakeRetriever(),
        artifact_store=store,
    )

    assert bundle.query_id == "q-e2e"
    assert bundle.candidates[0].technique.canonical_name == "Identifier enumeration"
    assert store.rows == [{"run_id": "run-e2e", "query_id": "q-e2e", "bundle": bundle}]
