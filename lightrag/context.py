"""Typed normalization of LightRAG ``/query/data`` responses.

Every transformation here is deterministic and auditable. Invented or
ambiguous references are never silently repaired.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RetrievedChunkV1(BaseModel):
    reference_id: str
    file_path: str
    content: str


class RetrievedReferenceV1(BaseModel):
    reference_id: str
    file_path: str


class RetrievedContextV1(BaseModel):
    status: str
    message: str = ""
    entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    chunks: list[RetrievedChunkV1] = []
    references: list[RetrievedReferenceV1] = []
    final_chunks_count: int | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.entities or self.relationships or self.chunks)

    @property
    def context_item_count(self) -> int:
        return len(self.entities) + len(self.relationships) + len(self.chunks)


class ReferenceRegistryV1(BaseModel):
    """Ordered registry built from the returned reference list plus chunk ids.

    Order is significant: ``[n]`` citations from the model resolve against the
    exact order of ``references``.
    """

    references: list[RetrievedReferenceV1]
    allowed_ids: list[str]
    alias_to_id: dict[str, str] = {}


def _string(value: Any) -> str:
    return str(value or "").strip()


def from_raw_response(raw: dict[str, Any]) -> RetrievedContextV1:
    """Parse the ``/query/data`` body; tolerate missing sections."""
    data = raw.get("data") or {}
    metadata = raw.get("metadata") or {}
    processing = metadata.get("processing_info") or {}
    chunks = []
    for item in data.get("chunks") or []:
        if not isinstance(item, dict):
            continue
        chunks.append(
            RetrievedChunkV1(
                reference_id=_string(item.get("reference_id")),
                file_path=_string(item.get("file_path")),
                content=_string(item.get("content")),
            )
        )
    references = []
    for item in data.get("references") or []:
        if not isinstance(item, dict):
            continue
        references.append(
            RetrievedReferenceV1(
                reference_id=_string(item.get("reference_id")),
                file_path=_string(item.get("file_path")),
            )
        )
    return RetrievedContextV1(
        status=_string(raw.get("status")),
        message=_string(raw.get("message")),
        entities=list(data.get("entities") or []),
        relationships=list(data.get("relationships") or []),
        chunks=chunks,
        references=references,
        final_chunks_count=processing.get("final_chunks_count"),
    )


def build_reference_registry(
    context: RetrievedContextV1,
    *,
    evidence_refs: list[str] | None = None,
) -> ReferenceRegistryV1:
    """Registry = ordered returned references + canonical L0/L1 evidence aliases."""
    registry = ReferenceRegistryV1(references=context.references, allowed_ids=[])
    allowed: list[str] = []
    aliases: dict[str, str] = {}

    for index, reference in enumerate(context.references, start=1):
        reference_id = reference.reference_id
        if reference_id:
            allowed.append(reference_id)
        # Unambiguous bracket index maps 1:1 onto the returned list order.
        aliases[f"[{index}]"] = reference_id

    for chunk in context.chunks:
        if chunk.reference_id and chunk.reference_id not in allowed:
            allowed.append(chunk.reference_id)

    for evidence_ref in evidence_refs or []:
        alias = evidence_ref.strip()
        if alias and alias not in allowed:
            allowed.append(alias)

    registry.allowed_ids = list(dict.fromkeys(allowed))
    registry.alias_to_id = aliases
    return registry


def serialize_context(context: RetrievedContextV1) -> str:
    """Render retrieved evidence as ``[reference_id] file_path: content`` lines."""
    lines = []
    for chunk in context.chunks:
        reference = chunk.reference_id or "no-ref"
        path = chunk.file_path or "unknown"
        lines.append(f"[{reference}] {path}: {chunk.content}")
    return "\n".join(lines)


def normalize_citations(
    citations: list[str],
    registry: ReferenceRegistryV1,
) -> tuple[list[str], list[str]]:
    """Resolve unambiguous ``[n]`` indices and aliases; reject everything else.

    Returns (resolved canonical ids, rejected citations).
    """
    resolved: list[str] = []
    rejected: list[str] = []
    for citation in citations:
        token = citation.strip()
        if not token:
            continue
        if token in registry.allowed_ids:
            resolved.append(token)
            continue
        mapped = registry.alias_to_id.get(token)
        if mapped:
            resolved.append(mapped)
            continue
        if token in registry.allowed_ids:
            resolved.append(token)
            continue
        rejected.append(token)
    return list(dict.fromkeys(resolved)), list(dict.fromkeys(rejected))


def provenance_completeness(context: RetrievedContextV1) -> float:
    """Share of returned items carrying a resolvable reference id (0..1)."""
    items = [
        *context.entities,
        *context.relationships,
        *[chunk.model_dump() for chunk in context.chunks],
    ]
    if not items:
        return 1.0
    referenced = sum(
        1 for item in items if _string(item.get("reference_id"))
    )
    return referenced / len(items)
