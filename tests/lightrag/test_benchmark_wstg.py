from polymerhus.lightrag.benchmark_wstg import (
    LightRAGBenchmarkConfig,
    build_query_prompt,
    compute_context_anchor_score,
    compute_metrics,
    extract_bare_wstg_ids,
    extract_malformed_wstg_ids,
    extract_retrieved_subgraph,
    extract_response_text,
    extract_wstg_ids,
    load_wstg_catalog,
    load_test_cases,
    ontology_projection_for_profile,
    run_benchmark,
    summarize_results,
)
from polymerhus.lightrag.experiment_tracker import ExperimentTracker


class FakeLightRAGClient:
    def __init__(self):
        self.calls = []

    def query(self, query, *, mode, extra=None):
        self.calls.append({"query": query, "mode": mode, "extra": extra or {}})
        return {
            "response": (
                "Prioritize WSTG-APIT-01 and WSTG-ATHZ-05. "
                "GraphQL introspection and object authorization should be tested."
            ),
            "entities": [{"name": "WSTG-APIT-01"}],
            "relations": [{"source": "GraphQL", "target": "Authorization"}],
        }


class FailingLightRAGClient:
    def query(self, query, *, mode, extra=None):
        raise RuntimeError("query failed")


def _case():
    return {
        "test_case_id": "graphql-bola",
        "title": "GraphQL BOLA",
        "phase2_abstracted_profile": {
            "api_styles": ["GraphQL"],
            "security_signals": ["introspection enabled", "sequential IDs"],
        },
        "expected_wstg_ids": ["WSTG-APIT-01", "WSTG-ATHZ-05"],
        "evaluation_terms": ["GraphQL", "introspection", "authorization"],
    }


def test_build_query_prompt_does_not_leak_expected_ids():
    prompt = build_query_prompt(_case(), "feature_to_threat")

    assert "GraphQL" in prompt
    assert "introspection enabled" in prompt
    assert "WSTG-APIT-01" not in prompt


def test_build_ontology_query_prompt_projects_profile_without_expected_ids():
    prompt = build_query_prompt(_case(), "ontology_feature_to_wstg")

    assert "Query strategy: use the methodology ontology" in prompt
    assert "TechnologyStack" in prompt
    assert "GraphQL Introspection Enabled" in prompt
    assert "WSTG-APIT-01" not in prompt
    assert "WSTG-ATHZ-05" not in prompt


def test_build_diagnostic_prompt_uses_expected_ids_for_exact_id_checks():
    prompt = build_query_prompt(_case(), "diagnostic_exact_id")

    assert "Diagnostic retrieval check" in prompt
    assert "WSTG-APIT-01" in prompt
    assert "WSTG-ATHZ-05" in prompt


def test_compute_metrics_scores_recall_precision_and_keywords():
    metrics = compute_metrics(
        _case(),
        raw_response=(
            "GraphQL introspection maps to WSTG-APIT-01. "
            "Authorization checks map to WSTG-ATHZ-05. "
            "WSTG-INPV-05 is unrelated here."
        ),
        latency_ms=20.1234,
    )

    assert metrics["wstg_code_recall"] == 1.0
    assert metrics["wstg_code_precision"] == 0.6667
    assert metrics["valid_wstg_code_precision"] == 0.6667
    assert metrics["hallucination_precision_rating"] == 0.6667
    assert metrics["matched_wstg_ids"] == ["WSTG-APIT-01", "WSTG-ATHZ-05"]
    assert metrics["unexpected_wstg_ids"] == ["WSTG-INPV-05"]
    assert metrics["keyword_coverage"] == 1.0
    assert metrics["latency_ms"] == 20.123


def test_compute_metrics_reports_id_quality_and_context_anchors():
    catalog = {
        "WSTG-APIT-01": {
            "title": "Testing GraphQL",
            "category": "API Testing",
        },
        "WSTG-ATHZ-05": {
            "title": "Testing for Insecure Direct Object References",
            "category": "Authorization Testing",
        },
    }

    metrics = compute_metrics(
        _case(),
        raw_response=(
            "WSTG-APIT-01 Testing GraphQL in API Testing. "
            "Use CLNT-07 carefully. Ignore WSTG-INPVAL-05 and WSTG-FAKE-99."
        ),
        wstg_catalog=catalog,
    )

    assert metrics["matched_wstg_ids"] == ["WSTG-APIT-01"]
    assert metrics["invalid_mentioned_wstg_ids"] == ["WSTG-FAKE-99"]
    assert metrics["malformed_wstg_ids"] == ["WSTG-INPVAL-05"]
    assert metrics["bare_wstg_ids"] == ["CLNT-07"]
    assert metrics["context_anchor_components"]["expected_id_coverage"] == 0.5
    assert metrics["context_anchor_score"] > 0


def test_run_benchmark_logs_each_template_and_config(tmp_path):
    client = FakeLightRAGClient()
    configs = [
        LightRAGBenchmarkConfig(mode="local", top_k=10, only_need_context=True),
        LightRAGBenchmarkConfig(mode="hybrid", top_k=20),
    ]

    with ExperimentTracker(tmp_path / "history.sqlite3") as tracker:
        results = run_benchmark(
            test_cases=[_case()],
            client=client,
            tracker=tracker,
            configs=configs,
            template_types=["feature_to_threat", "step_by_step_methodology"],
            run_label="baseline",
        )
        records = list(tracker.iter_runs())

    assert len(results) == 4
    assert len(records) == 4
    assert [call["mode"] for call in client.calls] == [
        "local",
        "hybrid",
        "local",
        "hybrid",
    ]
    assert client.calls[0]["extra"]["top_k"] == 10
    assert client.calls[0]["extra"]["only_need_context"] is True
    assert client.calls[1]["extra"]["only_need_context"] is False
    assert records[0].query_payload["include_references"] is True
    assert records[0].run_label == "baseline"
    assert records[0].metrics["wstg_code_recall"] == 1.0
    assert records[0].retrieved_subgraph["entities"][0]["name"] == "WSTG-APIT-01"
    assert summarize_results(results)["run_count"] == 4


def test_run_benchmark_logs_errors_and_continues(tmp_path):
    with ExperimentTracker(tmp_path / "history.sqlite3") as tracker:
        results = run_benchmark(
            test_cases=[_case()],
            client=FailingLightRAGClient(),
            tracker=tracker,
            configs=[LightRAGBenchmarkConfig(mode="local")],
            template_types=["feature_to_threat"],
        )
        records = list(tracker.iter_runs())

    assert len(results) == 1
    assert records[0].metrics["error"] is True
    assert records[0].metrics["error_type"] == "RuntimeError"
    assert records[0].retrieved_subgraph["error"]["message"] == "query failed"


def test_load_test_cases_accepts_top_level_cases(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        '{"schema_version": 1, "cases": [{"test_case_id": "case-1", "profile": {}}]}',
        encoding="utf-8",
    )

    assert load_test_cases(path)[0]["test_case_id"] == "case-1"


def test_load_wstg_catalog_reads_manifest_categories_and_aliases(tmp_path):
    path = tmp_path / ".manifest.json"
    path.write_text(
        """
        {
          "scenarios": [
            {
              "wstg_id": "WSTG-APIT-01",
              "title": "Testing GraphQL",
              "category_code": "APIT",
              "category": "API Testing",
              "canonical_aliases": ["WSTG-APIT-01", "Testing GraphQL"],
              "ontology_query_anchors": {"TechnologyStack": ["GraphQL"]},
              "ontology_query_anchor_terms": ["GraphQL"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    catalog = load_wstg_catalog(path)

    assert catalog["WSTG-APIT-01"]["category"] == "API Testing"
    assert catalog["WSTG-APIT-01"]["canonical_aliases"] == [
        "WSTG-APIT-01",
        "Testing GraphQL",
    ]
    assert catalog["WSTG-APIT-01"]["ontology_query_anchors"] == {
        "TechnologyStack": ["GraphQL"]
    }


def test_ontology_projection_for_profile_maps_phase2_fields():
    projection = ontology_projection_for_profile(_case()["phase2_abstracted_profile"])

    assert "GraphQL" in projection["TechnologyStack"]
    assert "GraphQL Introspection Enabled" in projection["PreconditionEnvironment"]
    assert "Broken Object-Level Authorization" in projection["VulnerabilityClass"]
    assert "introspection enabled" in projection["ObservableSignal"]


def test_response_extractors_are_tolerant():
    response = {
        "data": {
            "answer": "Use WSTG-CLNT-12.",
            "source_chunks": [{"id": "chunk-1"}],
        }
    }

    assert extract_response_text(response) == "Use WSTG-CLNT-12."
    assert extract_retrieved_subgraph(response) == {
        "source_chunks": [{"id": "chunk-1"}]
    }
    assert extract_wstg_ids("wstg-clnt-12 and WSTG-INPV-05-6") == [
        "WSTG-CLNT-12",
        "WSTG-INPV-05-6",
    ]
    assert extract_malformed_wstg_ids("WSTG-INPVAL-05 and WSTG-INPV-05") == [
        "WSTG-INPVAL-05"
    ]
    assert extract_bare_wstg_ids("Use CLNT-07 but not WSTG-CLNT-07") == ["CLNT-07"]
    assert compute_context_anchor_score(
        "WSTG-CLNT-12 Testing Browser Storage Client-side Testing methodology",
        {"expected_wstg_ids": ["WSTG-CLNT-12"]},
        wstg_catalog={
            "WSTG-CLNT-12": {
                "title": "Testing Browser Storage",
                "category": "Client-side Testing",
            }
        },
    )["score"] == 1.0
