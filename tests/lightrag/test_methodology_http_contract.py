import pytest

from lightrag.types import MethodologyBundle


class FakeRoutedRetriever:
    def retrieve_methodology(self, query):
        return {
            "query_id": query.query_id,
            "summary": "Evidence-backed BOLA methodology for API object boundaries.",
            "candidates": [
                {
                    "technique": {"canonical_name": "Object ID Tampering"},
                    "relevance": {
                        "relation_path": [],
                        "rationale": "Checks object-level authorization boundaries.",
                    },
                    "applicability": {
                        "satisfied_conditions": ["Authenticated low-privilege API session"],
                        "missing_conditions": ["Second user object identifier"],
                    },
                    "expected_effect": {
                        "produces_condition": "Unauthorized object access is denied"
                    },
                    "confidence": "medium",
                    "evidence_refs": [
                        {
                            "source_id": "wstg-apit-02-methodology.md",
                            "locator": "WSTG-APIT-02",
                        }
                    ],
                    "observables": ["Denied cross-user object response"],
                    "mitigation_checks": ["Server-side object ownership check"],
                    "source_tier": "validated_base",
                }
            ],
            "knowledge_gaps": [],
            "source_tier": "validated_base",
        }


@pytest.mark.xfail(
    strict=True,
    reason="Agent-facing /methodology/query wiring is pending; this is the HTTP contract.",
)
def test_http_methodology_query_returns_methodology_bundle_not_raw_lightrag(monkeypatch):
    """Catches a missing agent-facing route or a route returning raw LightRAG prose."""
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    TestClient = fastapi_testclient.TestClient

    from polymerhus.app.clients import pg
    from polymerhus.app.main import app
    import lightrag.retriever as retriever_module

    monkeypatch.setattr(
        retriever_module.RoutedMethodologyRetriever,
        "from_config",
        classmethod(lambda cls: FakeRoutedRetriever()),
    )
    monkeypatch.setattr(pg, "save_methodology_bundle", lambda run_id, query, bundle: 1)

    client = TestClient(app)
    response = client.post(
        "/methodology/query",
        json={
            "run_id": "run-http-contract",
            "query": {
                "query_id": "http-contract-bola",
                "pattern": "bypass",
                "objective": "Retrieve BOLA methodology for API object authorization.",
                "fault_context": {
                    "blocked_technique": "Direct object identifier substitution",
                    "defenses_present": ["Object ownership authorization"],
                },
                "taxonomy_tags": ["bola", "idor", "api"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    bundle = MethodologyBundle.model_validate(body)
    assert bundle.query_id == "http-contract-bola"
    assert bundle.candidates[0].technique.canonical_name == "Object ID Tampering"
    assert len(bundle.candidates) <= 3
    assert "response" not in body
    assert "answer" not in body
    assert "raw_lightrag_context" not in body
