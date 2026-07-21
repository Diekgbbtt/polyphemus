from __future__ import annotations

from typing import Any

from agent.lightrag.types import KnowledgeQuery, MethodologyBundle

_NO_EVIDENCE_GAP = "No supported methodology evidence was retrieved."


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _coerce_candidate(candidate: Any) -> dict:
    payload = _jsonable(candidate)
    if not isinstance(payload, dict):
        raise ValueError("retriever candidates must be mappings")
    payload = dict(payload)
    technique = payload.get("technique")
    if isinstance(technique, str):
        payload["technique"] = {"canonical_name": technique, "aliases": []}
    if "relevance" not in payload:
        rationale = payload.pop(
            "rationale",
            "Retriever matched this candidate to the query context.",
        )
        payload["relevance"] = {
            "relation_path": payload.pop("relation_path", []),
            "rationale": rationale,
        }
    return payload


def _bundle_payload_from_mapping(query: KnowledgeQuery, output: dict) -> dict:
    payload = dict(output)
    output_query_id = payload.get("query_id")
    if output_query_id and output_query_id != query.query_id:
        raise ValueError(
            f"retriever output query_id {output_query_id!r} does not match {query.query_id!r}"
        )
    candidates = [_coerce_candidate(candidate) for candidate in payload.get("candidates", [])]
    payload["query_id"] = query.query_id
    payload["candidates"] = candidates
    if not payload.get("summary"):
        if candidates:
            payload["summary"] = f"Retrieved methodology candidates for {query.pattern}."
        else:
            payload["summary"] = _NO_EVIDENCE_GAP
    if not candidates and not payload.get("knowledge_gaps"):
        payload["knowledge_gaps"] = [_NO_EVIDENCE_GAP]
    payload.setdefault("knowledge_gaps", [])
    payload.setdefault("source_chunks", [])
    payload.setdefault("retrieval_metadata", {})
    return payload


def package_methodology(query: KnowledgeQuery, retriever_output: Any) -> MethodologyBundle:
    """Convert a retriever response into the public MethodologyBundle contract."""
    if isinstance(retriever_output, MethodologyBundle):
        if retriever_output.query_id != query.query_id:
            raise ValueError(
                "retriever output query_id "
                f"{retriever_output.query_id!r} does not match {query.query_id!r}"
            )
        return retriever_output

    output = _jsonable(retriever_output)
    if output is None:
        output = {}
    if isinstance(output, list):
        output = {"candidates": output}
    if isinstance(output, str):
        output = {"summary": output, "knowledge_gaps": [_NO_EVIDENCE_GAP]}
    if not isinstance(output, dict):
        raise ValueError("retriever output must be a bundle mapping, candidate list, or summary string")

    return MethodologyBundle(**_bundle_payload_from_mapping(query, output))
