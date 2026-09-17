"""Unit tier: per-stage Langfuse observations for the query_lightrag pipeline (#207).

Drives the pure mechanics (observation lifecycle, input/output/metadata/scores,
the reference-registry persistence mapping, fail-open) by faking the `langfuse`
module - the helpers import it lazily - exactly like
`tests/test_analyser_tracing.py`. No live Langfuse, no live gateway, no DB.

The SDK client-layer canon (`docs/design/observability-recipe.md`) requires
the SDK primitives (`start_as_current_observation` / `span.update` /
`score_current_span`): raw OTel tracer scopes are silently dropped by the SDK
processor's export filter (verified live 2026-09-09), so the OTel recording
path must never come back.
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from lightrag.observability import kb_observation_span, registry_metadata, stage_span
from lightrag.context import (
    ReferenceRegistryV1,
    RetrievedReferenceV1,
)


def _fake_langfuse(monkeypatch):
    """Install a fake `langfuse` module capturing SDK calls; return the log."""
    calls: list = []
    mod = types.ModuleType("langfuse")

    @contextmanager
    def _observation(name=None, as_type=None, input=None):
        calls.append(
            ("observation", {"name": name, "as_type": as_type, "input": input})
        )
        span = MagicMock()

        def _update(**kw):
            calls.append(("update", {"observation": name, **kw}))

        span.update.side_effect = _update
        yield span

    client = MagicMock()
    client.start_as_current_observation.side_effect = _observation
    client.score_current_span.side_effect = (
        lambda name, value: calls.append(("score", {"name": name, "value": value}))
    )
    client.flush.side_effect = lambda: calls.append(("flush", {}))

    mod.get_client = lambda: client
    monkeypatch.setitem(sys.modules, "langfuse", mod)
    return calls


def _observations(calls, name: str) -> list:
    return [c[1] for c in calls if c[0] == "observation" and c[1]["name"] == name]


def _updates(calls, name: str) -> list:
    return [c[1] for c in calls if c[0] == "update" and c[1]["observation"] == name]


# --- observation lifecycle + input/output/metadata/scores --------------------


def test_stage_span_opens_sdk_observation_with_input(monkeypatch):
    calls = _fake_langfuse(monkeypatch)
    with stage_span("retrieval", input={"query": "q", "mode": "hybrid"}) as sink:
        sink.record(status="success", chunk_ids=["a", "b"])
        sink.metric("chunk_count", 2.0)

    obs = _observations(calls, "retrieval")
    assert len(obs) == 1
    assert obs[0]["as_type"] == "span"  # the canon observation type for steps
    assert obs[0]["input"] == {"query": "q", "mode": "hybrid"}

    updates = _updates(calls, "retrieval")
    assert updates, "record must reach the observation"
    metadata = updates[-1]["metadata"]
    assert metadata["status"] == "success"
    assert metadata["chunk_ids"] == ["a", "b"]

    scores = [c[1] for c in calls if c[0] == "score"]
    assert {"name": "chunk_count", "value": 2.0} in scores


def test_stage_span_routes_output_to_output_field(monkeypatch):
    calls = _fake_langfuse(monkeypatch)
    with stage_span("generation", input={"prompt": "p"}) as sink:
        sink.record(output="Hello world", reasoning_content="think hard")

    updates = _updates(calls, "generation")
    outputs = [u["output"] for u in updates if "output" in u]
    assert outputs == ["Hello world"]
    metas = [u["metadata"] for u in updates if "metadata" in u]
    assert metas[-1]["reasoning_content"] == "think hard"


def test_stage_span_nests_generation_under_retrieval(monkeypatch):
    calls = _fake_langfuse(monkeypatch)
    with stage_span("retrieval", input={"q": 1}):
        with stage_span("generation", input={"p": 2}):
            pass
    names = [c[1]["name"] for c in calls if c[0] == "observation"]
    assert names == ["retrieval", "generation"]


def test_stage_span_fails_open_without_langfuse(monkeypatch):
    """With langfuse unavailable, the sink is a null no-op - never raises."""
    monkeypatch.setattr("lightrag.observability._client", lambda: None)
    with stage_span("retrieval", input={"q": 1}) as sink:
        sink.record(status="success")
        sink.metric("n", 1.0)
    # Nothing to assert except that it did not raise.


def test_stage_span_fails_open_when_client_raises(monkeypatch):
    """A raising SDK client degrades to the null sink - never into the turn."""
    import sys as _sys
    import types as _types

    mod = _types.ModuleType("langfuse")

    def _boom():
        raise RuntimeError("langfuse down")

    mod.get_client = _boom
    monkeypatch.setitem(_sys.modules, "langfuse", mod)
    with stage_span("retrieval", input={"q": 1}) as sink:
        sink.record(status="success")
        sink.metric("n", 1.0)


# --- reference-registry persistence mapping (grey pt 7) -----------------------


def test_registry_metadata_maps_index_to_reference_and_path():
    registry = ReferenceRegistryV1(
        references=[
            RetrievedReferenceV1(reference_id="doc-1", file_path="WSTG/x.md"),
            RetrievedReferenceV1(reference_id="doc-2", file_path="writeups/y.md"),
        ],
        allowed_ids=["doc-1", "doc-2"],
    )
    metadata = registry_metadata(registry)
    assert metadata == {
        "1": {"reference_id": "doc-1", "file_path": "WSTG/x.md"},
        "2": {"reference_id": "doc-2", "file_path": "writeups/y.md"},
    }


def test_registry_metadata_empty_registry():
    registry = ReferenceRegistryV1(references=[], allowed_ids=[])
    assert registry_metadata(registry) == {}


# --- the tool stream records per-stage observations (#207 defect 1) -----------


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
        yield {"type": "reasoning", "text": "think about object-level authz"}
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


def test_tool_stream_records_retrieval_generation_validation(monkeypatch):
    from lightrag.query_spec import QuerySpecV1
    from lightrag.tool import LightRagQueryTool

    calls = _fake_langfuse(monkeypatch)
    tool = LightRagQueryTool(client=_FakeClient(), llm=_FakeLlm())
    spec = QuerySpecV1(
        scenario_id="SIM-01",
        attack_goal="Identify a bounded comparison hypothesis",
        concern="object-level authorization",
        acceptable_technique_families=["Object-level authorization comparison"],
    )
    events = list(tool.stream(spec))
    assert events[-1]["type"] == "answer"
    assert events[-1]["accepted"] is True

    names = sorted(
        c[1]["name"] for c in calls if c[0] == "observation"
    )
    assert names == ["generation", "retrieval", "validation"]

    retrieval_obs = _observations(calls, "retrieval")[0]
    assert "object-level authorization" in str(retrieval_obs["input"])
    retrieval_meta = _updates(calls, "retrieval")[-1]["metadata"]
    assert "doc-1" in str(retrieval_meta["chunk_ids"])
    # registry mapping is persisted: index -> reference_id -> file_path
    assert retrieval_meta["registry"]["1"]["reference_id"] == "doc-1"
    assert retrieval_meta["registry"]["1"]["file_path"] == "WSTG-ATHZ/x.md"

    generation_obs = _observations(calls, "generation")[0]
    assert "REFERENCE REGISTRY" in str(generation_obs["input"])
    generation_updates = _updates(calls, "generation")
    generation_outputs = [u["output"] for u in generation_updates if "output" in u]
    assert any(
        "Object-level authorization comparison" in o for o in generation_outputs
    )
    generation_metas = [u["metadata"] for u in generation_updates if "metadata" in u]
    assert any(
        "think about object-level authz" in m.get("reasoning_content", "")
        for m in generation_metas
    )

    validation_meta = _updates(calls, "validation")[-1]["metadata"]
    assert validation_meta["accepted"] is True
    scores = {c[1]["name"]: c[1]["value"] for c in calls if c[0] == "score"}
    assert scores["provenance_empty"] == 1.0  # the fake emits no provenance refs
    assert scores["entity_count"] == 1.0


def test_hunter_kb_query_records_author_lane_observation(monkeypatch):
    """#207 defect 1, point D: the hunter's author-lane `kb_query` records a
    KbObservation-equivalent artifact as observation I/O (the hunter has no D6
    log; grey pt 8 = observation metadata only)."""
    import json as _json

    from polymerhus.attack.hunting.hunter_tools import KbQueryTool

    class _FakeRealTool:
        args_schema = None

        def invoke(self, kwargs):
            return _json.dumps({
                "schema_version": "lightrag-answer/v2",
                "scenario_id": "HUNT-1",
                "summary": "CSRF methodology",
                "ontology_explanations": [
                    {"entity_type": "AttackTechnique", "entity_name": "CSRF"},
                ],
                "provenance_references": ["doc-9"],
                "knowledge_gaps": [],
            })

    calls = _fake_langfuse(monkeypatch)
    monkeypatch.setattr(KbQueryTool, "_lightrag_tool", lambda self: _FakeRealTool())
    tool = KbQueryTool()
    out = tool._run(
        scenario_id="HUNT-1",
        attack_goal="CSRF",
        concern="cross-site request forgery",
    )
    assert "CSRF methodology" in out

    obs = _observations(calls, "kb_observation")
    assert len(obs) == 1
    assert obs[0]["input"]["scenario_id"] == "HUNT-1"
    assert "cross-site request forgery" in obs[0]["input"]["query"]
    meta = _updates(calls, "kb_observation")[-1]["metadata"]
    assert "doc-9" in meta["provenance_references"]
    assert "CSRF" in meta["entity_names"]


def test_kb_observation_span_fails_open_without_langfuse(monkeypatch):
    monkeypatch.setattr("lightrag.observability._client", lambda: None)
    with kb_observation_span(query="q", scenario_id="s") as sink:
        sink.record(entity_names=["e"])
    # Nothing to assert except that it did not raise.
