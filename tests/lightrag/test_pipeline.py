from lightrag.pipeline import MockMode, run_query_pipeline
from lightrag.query_spec import QuerySpecV1, R_A


def _spec() -> QuerySpecV1:
    return QuerySpecV1(
        scenario_id="SIM-01",
        attack_goal="Identify a bounded authorization-boundary comparison hypothesis",
        concern="GraphQL and REST object-level authorization",
        technology_stack=["HTTP JSON API", "GraphQL"],
        acceptable_technique_families=["Object-level authorization comparison"],
    )


def test_mock_pipeline_accepts_and_normalizes_answer():
    result = run_query_pipeline(_spec(), retrieval_config=R_A, mock=MockMode())
    assert result.accepted is True
    assert result.retrieval.mock is True
    assert result.generation.mock is True
    assert result.bundle.provenance_references == ["doc-mock-01"]
    assert result.rejected_citations == []
    assert result.retrieval.query_hash


def test_invalid_generation_falls_back_deterministically():
    mock = MockMode()
    mock.raw_generation["content"] = "not json at all"
    result = run_query_pipeline(_spec(), retrieval_config=R_A, mock=mock)
    assert result.accepted is False
    assert "not_json" in result.validation_errors
    assert result.bundle is not None
    assert result.bundle.provenance_references == []
    assert "Deterministic checklist fallback" in result.bundle.summary
