import pytest
from fastapi import HTTPException

from polymerhus.lightrag.api import query_lightrag
from polymerhus.lightrag.query_spec import QuerySpecV1


def _spec() -> QuerySpecV1:
    return QuerySpecV1(
        scenario_id="SIM-01",
        attack_goal="Identify a bounded authorization-boundary comparison hypothesis",
        concern="object-level authorization",
        acceptable_technique_families=["Object-level authorization comparison"],
    )


def test_query_endpoint_rejects_unknown_config():
    with pytest.raises(HTTPException) as excinfo:
        query_lightrag(_spec(), config="R-C")
    assert excinfo.value.status_code == 422


def test_query_endpoint_runs_mock_pipeline(monkeypatch):
    import polymerhus.app.config as config_module

    monkeypatch.setattr(config_module.config, "QUERY_PIPELINE_MOCK", True)
    result = query_lightrag(_spec(), config="R-A")
    assert result.accepted is True
    assert result.retrieval.mock is True
    assert result.bundle.provenance_references == ["doc-mock-01"]
