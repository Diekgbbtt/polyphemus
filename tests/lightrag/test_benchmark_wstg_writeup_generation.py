import json

from lightrag.benchmark_wstg_writeup_generation import (
    DEFAULT_LIGHTRAG_PARAMETERS,
    REQUIRED_OUTPUT_SECTIONS,
    build_final_llm_payload,
    default_datasets,
    default_use_cases,
    run_evaluation,
)
from lightrag.types import CompactMethodologyBundle, MethodologyBundle


class FakeSourceClient:
    def __init__(self, source_name):
        self.source_name = source_name
        self.calls = []

    def query(
        self,
        query,
        *,
        mode,
        include_references=True,
        include_chunk_content=True,
        extra=None,
    ):
        self.calls.append(
            {
                "query": query,
                "mode": mode,
                "include_references": include_references,
                "include_chunk_content": include_chunk_content,
                "extra": extra or {},
            }
        )
        return {
            "response": (
                "Knowledge Graph Data (Entity):\n"
                '{"entity": "Access Control Validation", "type": "AttackTechnique"}\n'
                '{"entity": "Broken Access Control", "type": "VulnerabilityClass"}\n'
                "Knowledge Graph Data (Relationship):\n"
                '{"src_id": "Access Control Validation", "tgt_id": "Broken Access Control", "keywords": "validates"}'
            ),
            "references": [
                {
                    "reference_id": f"{self.source_name}-1",
                    "file_path": f"{self.source_name}-methodology.md",
                    "content": f"{self.source_name} access control evidence",
                }
            ],
        }


class FakeStructuredLLM:
    def with_structured_output(self, schema, *, method):
        self.schema = schema
        self.method = method
        return self

    def invoke(self, messages):
        assert self.schema is CompactMethodologyBundle
        assert self.method == "function_calling"
        return {
            "query_id": "broken-access-control",
            "summary": "Access-control evidence supports authorization boundary checks.",
            "candidates": [
                {
                    "technique": "Access Control Validation",
                    "relevance": "Matches authorization boundary verification.",
                    "satisfied_conditions": ["Authenticated roles are available"],
                    "missing_conditions": [],
                    "observables": ["Cross-role response difference"],
                    "mitigation_checks": ["Enforce server-side authorization"],
                    "confidence": "medium",
                    "evidence_refs": ["wstg-1"],
                }
            ],
            "knowledge_gaps": [],
            "source_tier": "validated_base",
        }


def test_default_matrix_has_four_use_cases_and_two_datasets():
    assert [case.use_case_id for case in default_use_cases()] == [
        "broken-access-control",
        "oauth2-oidc-flows",
        "session-management-fixation",
        "bola-idor-apis",
    ]
    assert [dataset.dataset_id for dataset in default_datasets()] == [
        "wstg",
        "wstg+writeup",
    ]
    assert DEFAULT_LIGHTRAG_PARAMETERS.to_query_payload("q")["only_need_context"] is True


def test_build_final_llm_payload_contains_prompt_constraints_and_schema():
    case = default_use_cases()[0]
    source_chunks = [
        {
            "chunk_id": "wstg-1",
            "source_id": "wstg-methodology.md",
            "locator": "wstg-methodology.md",
            "text": "Access control validation evidence.",
        }
    ]

    payload = build_final_llm_payload(
        case.to_knowledge_query(DEFAULT_LIGHTRAG_PARAMETERS),
        raw_lightrag_context="Access control context",
        source_tier="validated_base",
        source_chunks=source_chunks,
    )

    assert payload["system_prompt"]
    assert "Retrieved context:" in payload["human_prompt"]
    assert "source_tier: validated_base" in payload["human_prompt"]
    assert payload["required_output_schema"]["title"] == "CompactMethodologyBundle"


def test_run_evaluation_writes_required_five_sections_with_constant_parameters(tmp_path):
    clients = {
        "wstg": FakeSourceClient("wstg"),
        "writeups": FakeSourceClient("writeups"),
    }
    output_path = tmp_path / "wstg_writeup_eval.json"

    result_path = run_evaluation(
        clients=clients,
        output_path=output_path,
        llm=FakeStructuredLLM(),
        use_cases=default_use_cases()[:1],
        datasets=default_datasets(),
        generated_at="20260804T120000Z",
    )

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["summary"]["execution_count"] == 2
    assert payload["summary"]["constant_parameters_enforced"] is True
    assert payload["summary"]["error_count"] == 0

    for execution in payload["executions"]:
        assert list(execution.keys()) == list(REQUIRED_OUTPUT_SECTIONS)
        assert execution["Parameters Used"]["LightRAG"] == DEFAULT_LIGHTRAG_PARAMETERS.to_record()
        assert execution["Context Retrieved from LightRAG"]["Entities"]
        assert execution["Context Retrieved from LightRAG"]["Relationships"]
        assert execution["Context Retrieved from LightRAG"]["Text Chunks"]
        assert "system_prompt" in execution["Complete Input Passed to LLM (Final Prompt)"]
        assert "execution_metadata" not in execution["Output Returned by LLM"]
        MethodologyBundle.model_validate(execution["Output Returned by LLM"])

    assert [call["extra"]["only_need_context"] for call in clients["wstg"].calls] == [
        True,
        True,
    ]
    assert [call["extra"]["top_k"] for call in clients["wstg"].calls] == [20, 20]
    assert [call["mode"] for call in clients["wstg"].calls] == ["mix", "mix"]
    assert [call["extra"]["only_need_context"] for call in clients["writeups"].calls] == [
        True
    ]
