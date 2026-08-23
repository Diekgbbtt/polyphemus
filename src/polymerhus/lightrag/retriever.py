from __future__ import annotations

from typing import Any

from polymerhus.lightrag.client import build_lightrag_clients
from polymerhus.lightrag.formatter import format_methodology_context
from polymerhus.lightrag.types import KnowledgeQuery, MethodologyBundle, SourceTier


OVERLAY_CONCEPT_TRIGGERS: dict[str, tuple[str, ...]] = {
    "sqli": ("sqli", "sql injection", "sql syntax", "union select", "sqlmap"),
    "ssrf": ("ssrf", "server-side request forgery", "localhost", "127.0.0.1"),
    "jwt": ("jwt", "json web token", "bearer token", "role claim"),
    "ad": ("active directory", "kerberos", "ldap", "ntlm", "bloodhound", "winrm"),
    "git": (".git", "git repo", "git repository", "gitlab", "source code"),
    "deserialization": ("deserialization", "pickle", "unserialize", "gadget"),
}


class RoutedMethodologyRetriever:
    """Base-first LightRAG retriever with a conditional 0xdf write-up overlay."""

    def __init__(
        self,
        *,
        base_client,
        writeup_client,
        min_base_candidates: int = 1,
        overlay_mode: str = "mix",
        formatter=None,
    ):
        if min_base_candidates < 0:
            raise ValueError("min_base_candidates must not be negative")
        self.base_client = base_client
        self.writeup_client = writeup_client
        self.min_base_candidates = min_base_candidates
        self.overlay_mode = overlay_mode
        self.formatter = formatter or format_methodology_context

    @classmethod
    def from_config(cls, *, min_base_candidates: int = 1, overlay_mode: str = "mix"):
        clients = build_lightrag_clients()
        return cls(
            base_client=clients["base"],
            writeup_client=clients["writeups"],
            min_base_candidates=min_base_candidates,
            overlay_mode=overlay_mode,
        )

    def retrieve(self, query: KnowledgeQuery) -> MethodologyBundle:
        return self.retrieve_methodology(query)

    def retrieve_methodology(self, query: KnowledgeQuery) -> MethodologyBundle:
        prompt = query.to_retrieval_prompt()
        base_raw = self.base_client.query(
            prompt,
            mode=query.retrieval.mode,
            extra={"top_k": query.retrieval.max_candidates, "only_need_context": True},
        )
        base_bundle = _bundle_from_source(
            query,
            base_raw,
            source_tier="validated_base",
            formatter=self.formatter,
        )

        overlay_reasons = _overlay_trigger_reasons(
            query,
            base_candidate_count=len(base_bundle.candidates),
            min_base_candidates=self.min_base_candidates,
        )
        overlay_bundle = None
        if overlay_reasons:
            overlay_raw = self.writeup_client.query(
                prompt,
                mode=self.overlay_mode,
                extra={"top_k": query.retrieval.max_candidates, "only_need_context": True},
            )
            overlay_bundle = _bundle_from_source(
                query,
                overlay_raw,
                source_tier="review_overlay",
                formatter=self.formatter,
            )

        return _merge_bundles(query, base_bundle, overlay_bundle, overlay_reasons)


def _bundle_from_source(
    query: KnowledgeQuery,
    raw_output: Any,
    *,
    source_tier: SourceTier,
    formatter,
) -> MethodologyBundle:
    raw_context = _response_text(raw_output)
    source_chunks = _source_chunks_from_raw(raw_output)
    return formatter(
        query,
        raw_lightrag_context=raw_context,
        source_tier=source_tier,
        source_chunks=source_chunks,
        raw_output=raw_output,
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _response_text(raw_output: Any) -> str:
    payload = _jsonable(raw_output)
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("response", "summary", "answer", "result", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        nested = payload.get("data")
        if isinstance(nested, dict):
            return _response_text(nested)
        return str(payload)
    return str(payload)


def _source_chunks_from_raw(raw_output: Any) -> list[dict[str, Any]]:
    payload = _jsonable(raw_output)
    if not isinstance(payload, dict):
        return []
    chunks: list[dict[str, Any]] = []
    for key in ("source_chunks", "references", "chunks"):
        value = payload.get(key)
        if isinstance(value, list):
            chunks.extend(item for item in value if isinstance(item, dict))
    nested = payload.get("data")
    if isinstance(nested, dict):
        chunks.extend(_source_chunks_from_raw(nested))
    return chunks


def _overlay_trigger_reasons(
    query: KnowledgeQuery,
    *,
    base_candidate_count: int,
    min_base_candidates: int,
) -> list[str]:
    reasons: list[str] = []
    if query.pattern in {"bypass", "chaining"}:
        reasons.append(f"pattern:{query.pattern}")

    matched_concept = _matched_overlay_concept(query)
    if matched_concept:
        reasons.append(f"concept:{matched_concept}")

    if base_candidate_count < min_base_candidates:
        reasons.append("base_candidates_below_threshold")

    return list(dict.fromkeys(reasons))


def _matched_overlay_concept(query: KnowledgeQuery) -> str | None:
    haystack = " ".join(_query_terms(query)).lower()
    tags = {tag.lower() for tag in query.taxonomy_tags}
    for concept, markers in OVERLAY_CONCEPT_TRIGGERS.items():
        if concept in tags:
            return concept
        if any(marker in haystack for marker in markers):
            return concept
    return None


def _query_terms(query: KnowledgeQuery) -> list[str]:
    context = query.fault_context
    terms = [
        query.objective,
        query.symptom or "",
        context.symptom or "",
        context.vulnerability_hypothesis or "",
        context.blocked_technique or "",
        context.desired_condition or "",
    ]
    terms.extend(query.taxonomy_tags)
    terms.extend(context.symptoms)
    terms.extend(context.observed_conditions)
    terms.extend(context.defenses_present)
    terms.extend(context.available_capabilities)
    return [term for term in terms if term]


def _merge_bundles(
    query: KnowledgeQuery,
    base_bundle: MethodologyBundle,
    overlay_bundle: MethodologyBundle | None,
    overlay_reasons: list[str],
) -> MethodologyBundle:
    candidates = []
    seen_techniques = set()
    for bundle in [base_bundle, overlay_bundle]:
        if bundle is None:
            continue
        for candidate in bundle.candidates:
            if len(candidates) >= 3:
                break
            key = candidate.technique.canonical_name.strip().casefold()
            if key in seen_techniques:
                continue
            seen_techniques.add(key)
            candidates.append(candidate)

    knowledge_gaps = list(
        dict.fromkeys(
            [
                *base_bundle.knowledge_gaps,
                *((overlay_bundle.knowledge_gaps if overlay_bundle else [])),
            ]
        )
    )
    sources_queried = ["base"]
    if overlay_bundle is not None:
        sources_queried.append("writeups")

    return MethodologyBundle(
        query_id=query.query_id,
        summary=base_bundle.summary,
        candidates=candidates,
        knowledge_gaps=knowledge_gaps,
        source_tier="review_overlay" if overlay_bundle is not None else "validated_base",
        source_chunks=[
            *base_bundle.source_chunks,
            *((overlay_bundle.source_chunks if overlay_bundle else [])),
        ],
        retrieval_metadata={
            **base_bundle.retrieval_metadata,
            "sources_queried": sources_queried,
            "overlay_trigger_reason": overlay_reasons,
            "base_candidate_count": len(base_bundle.candidates),
            "overlay_candidate_count": len(overlay_bundle.candidates) if overlay_bundle else 0,
        },
    )
