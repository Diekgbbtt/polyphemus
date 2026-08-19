import asyncio
import json

from polymerhus.lightrag.query_spec import QuerySpecV1
from polymerhus.lightrag.tool import LightRagQueryTool


class _FakeClient:
    def query_data(self, payload):
        return {
            "status": "success",
            "message": "ok",
            "data": {
                "entities": [],
                "relationships": [],
                "chunks": [
                    {
                        "reference_id": "doc-1",
                        "file_path": "WSTG-ATHZ/x.md",
                        "content": "Methodology text about object id tampering.",
                    }
                ],
                "references": [
                    {"reference_id": "doc-1", "file_path": "WSTG-ATHZ/x.md"}
                ],
            },
            "metadata": {"processing_info": {"final_chunks_count": 1}},
        }


class _FakeLlm:
    def stream(self, prompt):
        yield {"type": "delta", "text": '{"scenario_id": "SIM-01", "summary": "ok",'}
        yield {
            "type": "delta",
            "text": (
                '"ontology_explanations": [{"entity_type": "AttackTechnique", '
                '"entity_name": "Object-level authorization comparison", '
                '"explanation": "Compare authorization behavior for adjacent ids."}],'
            ),
        }
        yield {"type": "delta", "text": '"knowledge_gaps": ["g"]}'}
        yield {"type": "finish", "finish_reason": "stop"}


class _RaisingLlm:
    def stream(self, prompt):
        raise RuntimeError("llm down")
        yield  # pragma: no cover - unreachable, keeps this a generator


class _RaisingClient:
    def query_data(self, payload):
        raise RuntimeError("lightrag down")


def _spec():
    return QuerySpecV1(
        scenario_id="SIM-01",
        attack_goal="Identify a bounded comparison hypothesis",
        concern="object-level authorization",
        acceptable_technique_families=["Object-level authorization comparison"],
    )


def test_stream_ends_with_validated_answer():
    tool = LightRagQueryTool(client=_FakeClient(), llm=_FakeLlm())
    events = list(tool.stream(_spec()))
    assert events[-1]["type"] == "answer"
    assert events[-1]["accepted"] is True
    assert events[-1]["answer"]["schema_version"] == "lightrag-answer/v2"


def test_arun_returns_answer_json():
    tool = LightRagQueryTool(client=_FakeClient(), llm=_FakeLlm())
    text = asyncio.run(tool._arun(**_spec().model_dump()))
    parsed = json.loads(text)
    assert parsed["schema_version"] == "lightrag-answer/v2"


def test_stream_fails_open_on_llm_error():
    """An LLM outage must NOT raise through the tool: the author lane degrades
    to the deterministic fallback (accepted False) so the agent can continue
    with the available grounding, per the D4 tool guidance."""
    tool = LightRagQueryTool(client=_FakeClient(), llm=_RaisingLlm())
    events = list(tool.stream(_spec()))
    assert events[-1]["type"] == "answer"
    assert events[-1]["accepted"] is False
    assert events[-1]["answer"]["ontology_explanations"]
    assert events[-1]["answer"]["schema_version"] == "lightrag-answer/v2"


def test_arun_returns_fallback_json_on_llm_error():
    tool = LightRagQueryTool(client=_FakeClient(), llm=_RaisingLlm())
    text = asyncio.run(tool._arun(**_spec().model_dump()))
    parsed = json.loads(text)
    assert parsed["schema_version"] == "lightrag-answer/v2"
    assert not parsed["ontology_explanations"][0]["evidence_references"]


def test_stream_fails_open_on_retrieval_error():
    tool = LightRagQueryTool(client=_RaisingClient(), llm=_FakeLlm())
    events = list(tool.stream(_spec()))
    assert events[-1]["type"] == "answer"
    assert events[-1]["accepted"] is False
