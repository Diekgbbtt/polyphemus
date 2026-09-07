"""Unit tier: per-stage OTel observability for the query_lightrag pipeline (#207).

Drives the pure mechanics (span lifecycle, attribute/metric attachment, the
reference-registry persistence mapping, fail-open) with the real OTel SDK
behind an in-memory exporter - no live Langfuse, no live gateway, no DB. The
test sets a process-local tracer provider so spans are captured, then restores
a fresh no-op provider so later unit tests are unaffected.
"""
from __future__ import annotations

import pytest

from lightrag.observability import registry_metadata, stage_span
from lightrag.context import (
    ReferenceRegistryV1,
    RetrievedReferenceV1,
)


@pytest.fixture(scope="session", autouse=True)
def _configure_otel():
    """Set the process global OTel tracer provider ONCE (a session-level, one-time
    action - the SDK forbids re-overriding it). An in-memory exporter captures the
    spans; each test clears it so isolation is by clear, not by re-set."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        trace.set_tracer_provider(provider)
    except Exception:  # noqa: BLE001 - a pre-existing provider keeps serving
        pass
    _SESSION_EXPORTER["exporter"] = exporter


_SESSION_EXPORTER: dict = {}


@pytest.fixture()
def otel_capture():
    """Clear the session exporter so each test captures only its own spans."""
    exporter = _SESSION_EXPORTER["exporter"]
    exporter.clear()
    yield exporter


def _span_attrs(otel_capture, name: str) -> dict:
    for span in otel_capture.get_finished_spans():
        if span.name == name:
            return dict(span.attributes)
    raise AssertionError(f"no finished span named {name!r}: "
                         f"{[s.name for s in otel_capture.get_finished_spans()]}")


# --- span lifecycle + attribute/metric attachment -----------------------------


def test_stage_span_records_input_and_output_attributes(otel_capture):
    with stage_span("retrieval", input={"query": "q", "mode": "hybrid"}) as sink:
        sink.record(status="success", chunk_ids=["a", "b"])
        sink.metric("chunk_count", 2.0)

    attrs = _span_attrs(otel_capture, "retrieval")
    assert attrs["input"] == '{"query": "q", "mode": "hybrid"}'
    assert attrs["status"] == "success"
    assert attrs["chunk_ids"] == '["a", "b"]'
    assert attrs["metric.chunk_count"] == 2.0


def test_stage_span_creates_one_child_span(otel_capture):
    with stage_span("retrieval", input={"q": 1}):
        with stage_span("generation", input={"prompt": "p"}):
            pass
    spans = otel_capture.get_finished_spans()
    names = sorted(s.name for s in spans)
    assert names == ["generation", "retrieval"]


def test_stage_span_nests_generation_under_retrieval(otel_capture):
    with stage_span("retrieval", input={"q": 1}) as outer:
        with stage_span("generation", input={"p": 2}):
            pass
        outer.record(done=True)
    spans = otel_capture.get_finished_spans()
    by_name = {s.name: s for s in spans}
    gen = by_name["generation"]
    ret = by_name["retrieval"]
    assert gen.parent is not None
    assert gen.parent.span_id == ret.context.span_id


def test_stage_span_fails_open_without_otel(monkeypatch):
    """With opentelemetry unavailable, the sink is a null no-op - never raises."""
    monkeypatch.setattr(
        "lightrag.observability._tracer", lambda: None
    )
    with stage_span("retrieval", input={"q": 1}) as sink:
        sink.record(status="success")
        sink.metric("n", 1.0)
    # Nothing to assert except that it did not raise.


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


# --- the tool stream records per-stage spans (#207 defect 1) ------------------

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


def test_tool_stream_records_retrieval_generation_validation_spans(otel_capture):
    from lightrag.query_spec import QuerySpecV1
    from lightrag.tool import LightRagQueryTool

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

    spans = otel_capture.get_finished_spans()
    names = sorted(s.name for s in spans)
    assert names == ["generation", "retrieval", "validation"]

    retrieval = _span_attrs(otel_capture, "retrieval")
    # retrieval records the query + mode + chunk ids + the persisted registry
    assert "object-level authorization" in retrieval["input"]
    assert "doc-1" in retrieval["chunk_ids"]
    # registry mapping is persisted: index -> reference_id -> file_path
    assert "1" in retrieval["registry"]
    assert "WSTG-ATHZ/x.md" in retrieval["registry"]

    generation = _span_attrs(otel_capture, "generation")
    assert "REFERENCE REGISTRY" in generation["input"]
    assert "Object-level authorization comparison" in generation["output"]

    validation = _span_attrs(otel_capture, "validation")
    assert validation["accepted"] is True
    assert "metric.provenance_empty" in validation
    assert "metric.entity_count" in validation
    assert validation["metric.entity_count"] == 1.0


def test_hunter_kb_query_records_author_lane_observation_span(otel_capture, monkeypatch):
    """#207 defect 1, point D: the hunter's author-lane `kb_query` records a
    KbObservation-equivalent artifact as span metadata (the hunter has no D6
    log; grey pt 8 = span metadata only)."""
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

    monkeypatch.setattr(KbQueryTool, "_lightrag_tool", lambda self: _FakeRealTool())
    tool = KbQueryTool()
    out = tool._run(
        scenario_id="HUNT-1",
        attack_goal="CSRF",
        concern="cross-site request forgery",
    )
    assert "CSRF methodology" in out

    attrs = _span_attrs(otel_capture, "kb_observation")
    assert attrs["scenario_id"] == "HUNT-1"
    assert "cross-site request forgery" in attrs["query"]
    assert "doc-9" in attrs["provenance_references"]
    assert "CSRF" in attrs["entity_names"]
