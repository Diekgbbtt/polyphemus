from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from polymerhus.lightrag.types import (
    CompactMethodologyBundle,
    KnowledgeQuery,
    MethodologyBundle,
    SourceChunk,
    SourceTier,
)


FORMATTER_SYSTEM_PROMPT = """You convert retrieved security methodology context into a compact MethodologyBundle.

Rules:
- Return only the structured schema.
- Max 3 candidates.
- Each text field must be 1-2 short lines.
- Do not include preambles, meta reasoning, markdown essays, or procedural exploit walkthroughs.
- Use only evidence present in the retrieved context.
- If evidence is weak, omit candidates and populate knowledge_gaps.
- Separate satisfied_conditions from missing_conditions.
- Every candidate needs evidence_refs.
- Prefer validated_base evidence. Use review_overlay only when explicitly routed.
"""

_FORMATTER_GAP = "Formatter could not produce a validated compact MethodologyBundle."


def format_methodology_context(
    query: KnowledgeQuery,
    *,
    raw_lightrag_context: str,
    source_tier: SourceTier,
    source_chunks: Sequence[Any] | None = None,
    raw_output: Any | None = None,
    llm: Any | None = None,
) -> MethodologyBundle:
    """Build the strict public MethodologyBundle from retrieved LightRAG context."""
    normalized_chunks = normalize_source_chunks(source_chunks or [])
    try:
        compact = _invoke_formatter_llm(
            query,
            raw_lightrag_context=raw_lightrag_context,
            source_tier=source_tier,
            source_chunks=normalized_chunks,
            llm=llm,
        )
        if compact.query_id != query.query_id:
            raise ValueError(
                f"formatter output query_id {compact.query_id!r} "
                f"does not match {query.query_id!r}"
            )
        return compact_to_methodology_bundle(
            query,
            compact,
            source_tier=source_tier,
            source_chunks=normalized_chunks,
            raw_lightrag_context=raw_lightrag_context,
        )
    except Exception as exc:
        return _fallback_bundle(
            query,
            source_tier=source_tier,
            source_chunks=normalized_chunks,
            raw_lightrag_context=raw_lightrag_context,
            error=exc,
        )


def compact_to_methodology_bundle(
    query: KnowledgeQuery,
    compact: CompactMethodologyBundle,
    *,
    source_tier: SourceTier,
    source_chunks: Sequence[SourceChunk],
    raw_lightrag_context: str,
) -> MethodologyBundle:
    candidates = []
    for candidate in compact.candidates[:3]:
        evidence_refs = _dedupe_evidence_refs(
            _evidence_ref_from_label(label, source_chunks)
            for label in candidate.evidence_refs
        )
        candidates.append(
            {
                "technique": {"canonical_name": candidate.technique, "aliases": []},
                "relevance": {
                    "relation_path": [],
                    "rationale": candidate.relevance,
                },
                "applicability": {
                    "satisfied_conditions": candidate.satisfied_conditions,
                    "missing_conditions": candidate.missing_conditions,
                    "conflicting_conditions": [],
                },
                "expected_effect": {
                    "produces_condition": candidate.observables[0]
                    if candidate.observables
                    else None,
                    "enables_next_action": candidate.mitigation_checks[0]
                    if candidate.mitigation_checks
                    else None,
                },
                "observables": candidate.observables,
                "mitigation_checks": candidate.mitigation_checks,
                "confidence": candidate.confidence,
                "evidence_refs": evidence_refs,
                "source_tier": source_tier,
            }
        )
    return MethodologyBundle(
        query_id=query.query_id,
        summary=compact.summary,
        candidates=candidates,
        knowledge_gaps=compact.knowledge_gaps,
        source_tier=source_tier,
        source_chunks=list(source_chunks),
        retrieval_metadata={
            "formatter": "structured_methodology_bundle",
            "source_tier": source_tier,
            "raw_lightrag_context": raw_lightrag_context,
            "raw_lightrag_context_bytes": len(raw_lightrag_context.encode("utf-8")),
        },
    )


def _dedupe_evidence_refs(evidence_refs: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    deduped = []
    seen = set()
    for ref in evidence_refs:
        key = (ref["source_id"], ref["locator"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def normalize_source_chunks(chunks: Sequence[Any]) -> list[SourceChunk]:
    normalized: list[SourceChunk] = []
    for index, chunk in enumerate(chunks, start=1):
        payload = _jsonable(chunk)
        if not isinstance(payload, Mapping):
            payload = {"text": str(payload)}
        chunk_id = _first_text(
            payload,
            "chunk_id",
            "id",
            "reference_id",
            default=f"chunk-{index}",
        )
        source_id = _first_text(
            payload,
            "source_id",
            "file_path",
            "document_title",
            "source",
            default=chunk_id,
        )
        locator = _first_text(
            payload,
            "locator",
            "file_path",
            "reference_id",
            "id",
            default=chunk_id,
        )
        text = _chunk_text(payload)
        normalized.append(
            SourceChunk(
                chunk_id=chunk_id,
                source_id=source_id,
                locator=locator,
                text=text,
            )
        )
    return normalized


def _invoke_formatter_llm(
    query: KnowledgeQuery,
    *,
    raw_lightrag_context: str,
    source_tier: SourceTier,
    source_chunks: Sequence[SourceChunk],
    llm: Any | None,
) -> CompactMethodologyBundle:
    if llm is None:
        from polymerhus.app.llm.roles import chat_model_for

        llm = chat_model_for("methodology_formatter")
    structured_llm = llm.with_structured_output(
        CompactMethodologyBundle,
        method="function_calling",
    )
    from langchain_core.messages import HumanMessage, SystemMessage

    result = structured_llm.invoke(
        [
            SystemMessage(content=FORMATTER_SYSTEM_PROMPT),
            HumanMessage(
                content=_formatter_human_prompt(
                    query,
                    raw_lightrag_context=raw_lightrag_context,
                    source_tier=source_tier,
                    source_chunks=source_chunks,
                )
            ),
        ]
    )
    if isinstance(result, CompactMethodologyBundle):
        return result
    payload = _jsonable(result)
    if not isinstance(payload, Mapping):
        raise ValueError("formatter output must be a compact methodology mapping")
    return CompactMethodologyBundle.model_validate(payload)


def _formatter_human_prompt(
    query: KnowledgeQuery,
    *,
    raw_lightrag_context: str,
    source_tier: SourceTier,
    source_chunks: Sequence[SourceChunk],
) -> str:
    chunk_table = [
        {
            "chunk_id": chunk.chunk_id,
            "source_id": chunk.source_id,
            "locator": chunk.locator,
        }
        for chunk in source_chunks
    ]
    return (
        f"query_id: {query.query_id}\n"
        f"pattern: {query.pattern}\n"
        f"objective: {query.objective}\n"
        f"fault_context: {query.fault_context.model_dump_json()}\n"
        f"taxonomy_tags: {query.taxonomy_tags}\n"
        f"source_tier: {source_tier}\n\n"
        f"Retrieved context:\n{raw_lightrag_context}\n\n"
        f"Available evidence refs:\n{chunk_table}"
    )


def _fallback_bundle(
    query: KnowledgeQuery,
    *,
    source_tier: SourceTier,
    source_chunks: Sequence[SourceChunk],
    raw_lightrag_context: str,
    error: Exception,
) -> MethodologyBundle:
    return MethodologyBundle(
        query_id=query.query_id,
        summary="No evidence-backed methodology bundle could be produced.",
        candidates=[],
        knowledge_gaps=[_FORMATTER_GAP],
        source_tier=source_tier,
        source_chunks=list(source_chunks),
        retrieval_metadata={
            "formatter": "structured_methodology_bundle",
            "source_tier": source_tier,
            "raw_lightrag_context": raw_lightrag_context,
            "raw_lightrag_context_bytes": len(raw_lightrag_context.encode("utf-8")),
            "formatter_error": {
                "type": type(error).__name__,
                "message": str(error),
            },
        },
    )


def _evidence_ref_from_label(label: str, source_chunks: Sequence[SourceChunk]) -> dict[str, str]:
    labels = _evidence_label_variants(label)
    for chunk in source_chunks:
        if labels & {chunk.chunk_id, chunk.source_id, chunk.locator}:
            return {
                "source_id": chunk.source_id,
                "locator": chunk.locator,
            }
    raise ValueError(f"evidence_ref {label!r} was not found in retrieved source_chunks")


def _evidence_label_variants(label: str) -> set[str]:
    cleaned = label.strip().strip("`'\"")
    variants = {label, cleaned}
    if cleaned.startswith("[") and "]" in cleaned:
        bracketed, _separator, trailing = cleaned[1:].partition("]")
        variants.add(bracketed.strip())
        variants.add(trailing.strip())
    if ":" in cleaned:
        prefix, _separator, suffix = cleaned.partition(":")
        if prefix.strip().casefold() in {
            "chunk_id",
            "reference_id",
            "source_id",
            "locator",
            "ref",
        }:
            variants.add(suffix.strip())
    return {variant for variant in variants if variant}


def _chunk_text(payload: Mapping[str, Any]) -> str:
    content = payload.get("text") or payload.get("content")
    if isinstance(content, list):
        content = "\n".join(str(item) for item in content)
    if isinstance(content, str) and content.strip():
        return content.strip()
    return _first_text(payload, "summary", "response", default="Source chunk text unavailable.")


def _first_text(payload: Mapping[str, Any], *keys: str, default: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    return default


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value
