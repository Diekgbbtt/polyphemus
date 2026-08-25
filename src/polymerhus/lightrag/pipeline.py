"""End-to-end query pipeline: QuerySpec -> /query/data -> DeepSeek -> answer.

Simulation boundary. The final Polyphemus receiver endpoint does not exist
yet, so the pipeline returns the validated bundle plus provenance/runtime
metadata; callers may forward it to whatever endpoint lands later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from polymerhus.lightrag.client import LightRAGHttpClient
from polymerhus.lightrag.context import (
    RetrievedContextV1,
    build_reference_registry,
    from_raw_response,
    provenance_completeness,
    serialize_context,
)
from polymerhus.lightrag.generation import (
    AnswerBundleV1,
    BundleValidationResult,
    DeepSeekClient,
    build_generation_prompt,
    extract_json_object,
    validate_bundle,
)
from polymerhus.lightrag.query_spec import (
    QuerySpecV1,
    RetrievalConfigV1,
    build_retrieval_payload,
    sha256_hex,
)


class RetrievalRecordV1(BaseModel):
    mode: str
    query: str
    query_hash: str
    payload_hash: str
    latency_ms: float
    status: str
    entities: int = 0
    relationships: int = 0
    chunks: int = 0
    references: int = 0
    provenance_completeness: float = 0.0
    mock: bool = False


class GenerationRecordV1(BaseModel):
    latency_ms: float
    model: str | None = None
    finish_reason: str | None = None
    truncated: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    mock: bool = False


class QueryPipelineResultV1(BaseModel):
    scenario_id: str
    accepted: bool
    bundle: AnswerBundleV1 | None = None
    validation_errors: list[str] = Field(default_factory=list)
    rejected_citations: list[str] = Field(default_factory=list)
    retrieval: RetrievalRecordV1 | None = None
    generation: GenerationRecordV1 | None = None
    allowed_reference_ids: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


def _deterministic_fallback(
    spec: QuerySpecV1,
    errors: list[str],
) -> AnswerBundleV1:
    """Deterministic checklist fallback - never raw model output."""
    explanations = [
        {
            "entity_type": "AttackTechnique",
            "entity_name": family,
            "explanation": (
                f"Deterministic fallback: '{family}' was supplied as an "
                "acceptable technique family but no validated model answer "
                "is available."
            ),
            "evidence_references": [],
            "confidence": "low",
        }
        for family in spec.acceptable_technique_families
    ]
    return AnswerBundleV1(
        scenario_id=spec.scenario_id,
        summary="Deterministic checklist fallback; model answer unavailable.",
        ontology_explanations=explanations,
        provenance_references=[],
        knowledge_gaps=list(errors),
        notes="Fallback: no fabricated provenance is allowed.",
    )


@dataclass
class MockMode:
    """Deterministic stand-ins so the full flow runs without live services."""

    raw_retrieval: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "success",
            "message": "mock /query/data response",
            "data": {
                "entities": [],
                "relationships": [],
                "chunks": [
                    {
                        "reference_id": "doc-mock-01",
                        "file_path": "WSTG-ATHZ/mock.md",
                        "content": (
                            "Synthetic methodology text about object-level "
                            "authorization comparisons over client-supplied ids."
                        ),
                    }
                ],
                "references": [
                    {
                        "reference_id": "doc-mock-01",
                        "file_path": "WSTG-ATHZ/mock.md",
                    }
                ],
            },
            "metadata": {"processing_info": {"final_chunks_count": 1}},
        }
    )
    raw_generation: dict[str, Any] = field(
        default_factory=lambda: {
            "content": (
                '{"schema_version":"lightrag-answer/v2",'
                '"scenario_id":"SIM-01",'
                '"summary":"Mock answer",'
                '"ontology_explanations":[{"entity_type":"AttackTechnique",'
                '"entity_name":"Object-level authorization comparison",'
                '"explanation":"Compare authorization behaviour for adjacent '
                'object ids using boundary-controlled requests.",'
                '"evidence_references":["[1]"],'
                '"confidence":"medium"}],'
                '"provenance_references":["[1]"],'
                '"knowledge_gaps":[],"notes":"mock"}'
            ),
            "finish_reason": "stop",
            "model": "mock-deepseek",
            "prompt_tokens": 100,
            "completion_tokens": 80,
            "reasoning_present": True,
            "truncated": False,
        }
    )


def run_query_pipeline(
    spec: QuerySpecV1,
    *,
    retrieval_config: RetrievalConfigV1 | None = None,
    client: LightRAGHttpClient | None = None,
    llm: DeepSeekClient | None = None,
    mock: MockMode | None = None,
    audit: bool = False,
) -> QueryPipelineResultV1:
    """Run retrieval -> normalization -> generation -> strict admission."""
    retrieval_config = retrieval_config or spec.retrieval
    payload = build_retrieval_payload(spec, retrieval_config)
    query_hash = sha256_hex(
        {"scenario_id": spec.scenario_id, "query": payload["query"]}
    )
    payload_hash = sha256_hex(payload)
    mock_ctx = mock if mock is not None else None

    started = time.perf_counter()
    if mock_ctx is not None:
        raw = mock_ctx.raw_retrieval
        is_mock = True
    else:
        if client is None:
            client = LightRAGHttpClient()
        raw = client.query_data(payload)
        is_mock = False
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    context = from_raw_response(raw)
    registry = build_reference_registry(
        context,
        evidence_refs=[item.ref for item in spec.evidence],
    )
    retrieval_record = RetrievalRecordV1(
        mode=retrieval_config.mode,
        query=payload["query"],
        query_hash=query_hash,
        payload_hash=payload_hash,
        latency_ms=latency_ms,
        status=context.status,
        entities=len(context.entities),
        relationships=len(context.relationships),
        chunks=len(context.chunks),
        references=len(context.references),
        provenance_completeness=round(provenance_completeness(context), 4),
        mock=is_mock,
    )

    if context.is_empty:
        bundle = _deterministic_fallback(
            spec, ["empty_retrieval_result"]
        )
        audit_data = {
            "retrieval_payload": payload,
            "reference_registry": registry.allowed_ids,
        } if audit else {}
        return QueryPipelineResultV1(
            scenario_id=spec.scenario_id,
            accepted=False,
            bundle=bundle,
            validation_errors=["empty_retrieval_result"],
            retrieval=retrieval_record,
            allowed_reference_ids=registry.allowed_ids,
            audit=audit_data,
        )

    context_text = serialize_context(context)
    prompt = build_generation_prompt(spec, context_text, registry)
    audit_data: dict[str, Any] = {}
    if audit:
        audit_data = {
            "retrieval_payload": payload,
            "retrieved_context_text": context_text,
            "reference_registry": [
                f"{index}. {reference.reference_id} ({reference.file_path})"
                for index, reference in enumerate(registry.references, start=1)
            ],
            "generation_prompt": prompt,
        }

    started = time.perf_counter()
    if mock_ctx is not None:
        outcome = mock_ctx.raw_generation
        is_mock_gen = True
    else:
        if llm is None:
            raise ValueError("llm client is required when mock mode is off")
        outcome = llm.complete(prompt)
        is_mock_gen = False
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    payload_obj = extract_json_object(outcome.get("content") or "")
    if audit:
        audit_data["raw_model_response"] = {
            "content": outcome.get("content"),
            "finish_reason": outcome.get("finish_reason"),
            "model": outcome.get("model"),
            "prompt_tokens": outcome.get("prompt_tokens"),
            "completion_tokens": outcome.get("completion_tokens"),
            "reasoning_present": outcome.get("reasoning_present"),
        }
    validation: BundleValidationResult = validate_bundle(
        payload_obj, spec=spec, registry=registry
    )
    generation_record = GenerationRecordV1(
        latency_ms=latency_ms,
        model=outcome.get("model"),
        finish_reason=outcome.get("finish_reason"),
        truncated=bool(outcome.get("truncated")),
        prompt_tokens=outcome.get("prompt_tokens"),
        completion_tokens=outcome.get("completion_tokens"),
        mock=is_mock_gen,
    )

    if not validation.is_valid or validation.bundle is None:
        bundle = _deterministic_fallback(spec, validation.errors)
        return QueryPipelineResultV1(
            scenario_id=spec.scenario_id,
            accepted=False,
            bundle=bundle,
            validation_errors=validation.errors,
            rejected_citations=validation.rejected_citations,
            retrieval=retrieval_record,
            generation=generation_record,
            allowed_reference_ids=registry.allowed_ids,
            audit=audit_data,
        )

    return QueryPipelineResultV1(
        scenario_id=spec.scenario_id,
        accepted=True,
        bundle=validation.bundle,
        validation_errors=validation.errors,
        rejected_citations=validation.rejected_citations,
        retrieval=retrieval_record,
        generation=generation_record,
        allowed_reference_ids=registry.allowed_ids,
        audit=audit_data,
    )
