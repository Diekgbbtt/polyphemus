import json

from agent.lightrag.benchmark_ontology_queries import (
    OntologyBenchmarkConfig,
    build_ontology_prompt,
    extract_context_payload,
    run_benchmark_grid,
)


class FakeRoutedRetriever:
    def __init__(self):
        self.calls = []

    def retrieve_methodology(self, query):
        self.calls.append(query)
        if query.query_id.endswith("-A"):
            sources = ["base"]
            reasons = []
        elif query.query_id.endswith("-B"):
            sources = ["base", "writeups"]
            reasons = ["concept:jwt"]
        else:
            sources = ["base", "writeups"]
            reasons = ["base_candidates_below_threshold"]
        return {
            "summary": (
                "\nKnowledge Graph Data (Entity):\n\n```json\n"
                '{"entity": "JWT Authentication Flow", "type": "PreconditionEnvironment"}\n'
                '{"entity": "JWT Token Forgery", "type": "AttackTechnique"}\n'
                '{"entity": "None Algorithm Token", "type": "PayloadPattern"}\n'
                '{"entity": "Boolean Response Delta", "type": "ObservableSignal"}\n'
                "```\n\nKnowledge Graph Data (Relationship):\n\n```json\n"
                '{"src_id": "JWT Token Forgery", "tgt_id": "JWT Authentication Flow", "keywords": "requires"}\n'
                '{"source": "JWT Token Forgery", "target": "None Algorithm Token", "relation": "uses"}\n'
                "```"
            ),
            "candidates": [],
            "knowledge_gaps": ["No structured candidates returned."],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "JWT role claim escalation"}],
            "retrieval_metadata": {
                "sources_queried": sources,
                "overlay_trigger_reason": reasons,
            },
        }


class FakeAnsweringRetriever(FakeRoutedRetriever):
    def retrieve_methodology(self, query):
        result = super().retrieve_methodology(query)
        result["summary"] = f"Generated methodology answer for {query.query_id}"
        return result


class FailingOnBRetrier(FakeRoutedRetriever):
    def retrieve_methodology(self, query):
        if query.query_id.endswith("-B"):
            raise RuntimeError("overlay query failed")
        return super().retrieve_methodology(query)


def test_build_ontology_prompt_weaves_required_entity_roles():
    prompt = build_ontology_prompt("B")

    assert "TechnologyStack/PreconditionEnvironment" in prompt
    assert "VulnerabilityClass/Fault" in prompt
    assert "AttackTechnique" in prompt
    assert "PayloadPattern" in prompt
    assert "ObservableSignal" in prompt
    assert "TestingStrategy/Mitigation" in prompt
    assert "weak signatures" in prompt


def test_extract_context_payload_groups_entities_and_relations_from_lightrag_context():
    payload = extract_context_payload(
        {
            "response": (
                "```json\n"
                '{"entity": "OAuth2 Authorization Server", "type": "TechnologyStack"}\n'
                '{"entity": "Broken Access Control", "type": "VulnerabilityClass"}\n'
                '{"src_id": "Broken Access Control", "tgt_id": "OAuth2 Authorization Server", "keywords": "targets"}\n'
                '{"entity1": "Access Control Validation", "entity2": "Authenticated User", "description": "checks authorization boundaries"}\n'
                "```"
            ),
            "references": [{"id": "ref-1"}],
        }
    )

    assert payload["retrieved_entities_by_type"]["TechnologyStack"] == [
        "OAuth2 Authorization Server"
    ]
    assert payload["retrieved_entities_by_type"]["VulnerabilityClass"] == [
        "Broken Access Control"
    ]
    assert payload["ontology_role_projection"]["Target"] == [
        "OAuth2 Authorization Server"
    ]
    assert payload["ontology_role_projection"]["Symptom"] == [
        "Broken Access Control"
    ]
    assert payload["extracted_relations"] == [
        {
            "subject": "Broken Access Control",
            "predicate": "targets",
            "object": "OAuth2 Authorization Server",
        },
        {
            "subject": "Access Control Validation",
            "predicate": "checks authorization boundaries",
            "object": "Authenticated User",
        },
    ]
    assert payload["raw_context_bytes"] > 0
    assert payload["source_chunks"] == [{"id": "ref-1"}]


def test_run_benchmark_grid_records_routing_hyperparameters_and_payloads(tmp_path):
    output_path = run_benchmark_grid(
        retriever=FakeRoutedRetriever(),
        configs=[OntologyBenchmarkConfig(label="standard", mode="mix", top_k=10)],
        output_dir=tmp_path,
        timestamp="20260803T120000Z",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.name == "ontology_query_benchmark_20260803T120000Z.json"
    assert payload["summary"]["run_count"] == 3
    assert payload["summary"]["expected_run_count"] == 3
    assert payload["summary"]["missing_runs"] == []
    assert payload["summary"]["expected_route_mismatches"] == []
    first = payload["results"][0]
    assert first["test_id"] == "A"
    assert first["hyperparameters"] == {
        "label": "standard",
        "mode": "mix",
        "top_k": 10,
        "only_need_context": True,
    }
    assert first["routing_decision"]["sources_queried"] == ["base"]
    assert "AttackTechnique" in first["retrieved_entities_by_type"]
    assert first["extracted_relations"][0]["subject"] == "JWT Token Forgery"


def test_run_benchmark_grid_can_record_generated_lightrag_answers(tmp_path):
    output_path = run_benchmark_grid(
        retriever=FakeRoutedRetriever(),
        answer_retriever=FakeAnsweringRetriever(),
        configs=[OntologyBenchmarkConfig(label="standard", mode="mix", top_k=10)],
        output_dir=tmp_path,
        timestamp="20260803T120003Z",
        include_answers=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["summary"]["answer_run_count"] == 3
    assert payload["summary"]["answer_error_count"] == 0
    first = payload["results"][0]
    assert first["lightrag_answer"] == {
        "text": "Generated methodology answer for ontology-benchmark-A",
        "bytes": 53,
        "routing_decision": {
            "sources_queried": ["base"],
            "trigger_reason": [],
        },
        "raw_source_answers": [
            {
                "source": "bundle",
                "mode": "mix",
                "extra": {
                    "top_k": 10,
                    "only_need_context": False,
                    "stream": False,
                },
                "answer": "Generated methodology answer for ontology-benchmark-A",
                "answer_bytes": 53,
            }
        ],
    }


def test_run_benchmark_grid_records_every_query_config_pair(tmp_path):
    output_path = run_benchmark_grid(
        retriever=FakeRoutedRetriever(),
        configs=[
            OntologyBenchmarkConfig(label="standard", mode="mix", top_k=10),
            OntologyBenchmarkConfig(label="hybrid", mode="hybrid", top_k=15),
        ],
        output_dir=tmp_path,
        timestamp="20260803T120001Z",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert [
        (result["test_id"], result["hyperparameters"]["label"])
        for result in payload["results"]
    ] == [
        ("A", "standard"),
        ("A", "hybrid"),
        ("B", "standard"),
        ("B", "hybrid"),
        ("C", "standard"),
        ("C", "hybrid"),
    ]
    assert payload["summary"]["expected_run_count"] == 6
    assert payload["summary"]["missing_runs"] == []


def test_run_benchmark_grid_logs_errors_without_dropping_matrix_entries(tmp_path):
    output_path = run_benchmark_grid(
        retriever=FailingOnBRetrier(),
        configs=[OntologyBenchmarkConfig(label="standard", mode="mix", top_k=10)],
        output_dir=tmp_path,
        timestamp="20260803T120002Z",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert [(result["test_id"], bool(result.get("error"))) for result in payload["results"]] == [
        ("A", False),
        ("B", True),
        ("C", False),
    ]
    assert payload["summary"]["expected_run_count"] == 3
    assert payload["summary"]["missing_runs"] == []
    assert payload["summary"]["error_count"] == 1
    error_result = payload["results"][1]
    assert error_result["error"] == {
        "type": "RuntimeError",
        "message": "overlay query failed",
    }
