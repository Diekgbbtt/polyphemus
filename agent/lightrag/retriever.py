from __future__ import annotations

from typing import Any

from agent.lightrag.client import build_lightrag_clients
from agent.lightrag.packager import package_methodology
from agent.lightrag.types import KnowledgeQuery, MethodologyBundle, SourceTier


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
    ):
        if min_base_candidates < 0:
            raise ValueError("min_base_candidates must not be negative")
        self.base_client = base_client
        self.writeup_client = writeup_client
        self.min_base_candidates = min_base_candidates
        self.overlay_mode = overlay_mode

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
            extra={"top_k": query.retrieval.max_candidates},
        )
        base_bundle = _bundle_from_source(query, base_raw, source_tier="validated_base")

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
                extra={"top_k": query.retrieval.max_candidates},
            )
            overlay_bundle = _bundle_from_source(query, overlay_raw, source_tier="review_overlay")

        return _merge_bundles(query, base_bundle, overlay_bundle, overlay_reasons)


def _bundle_from_source(
    query: KnowledgeQuery,
    raw_output: Any,
    *,
    source_tier: SourceTier,
) -> MethodologyBundle:
    payload = _response_payload(raw_output)
    candidates = []
    for candidate in payload.get("candidates", []):
        candidate_payload = _jsonable(candidate)
        if not isinstance(candidate_payload, dict):
            candidates.append(candidate)
            continue
        candidates.append({**candidate_payload, "source_tier": source_tier})
    payload["candidates"] = candidates
    if "summary" not in payload and "response" in payload:
        payload["summary"] = str(payload["response"])
    return package_methodology(query, payload)


def _response_payload(raw_output: Any) -> dict:
    payload = _jsonable(raw_output)
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, list):
        return {"candidates": payload}
    if isinstance(payload, str):
        return {"summary": payload}
    raise ValueError("LightRAG retriever output must be a mapping, candidate list, or summary string")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


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
