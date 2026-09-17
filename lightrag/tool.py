"""LangChain tool exposing the LightRAG query pipeline, with a streamed answer.

The tool deliberately re-implements the retrieval -> prompt -> validation
sequence instead of calling `pipeline.run_query_pipeline`: that function is a
BATCH seam (it returns one aggregated `QueryPipelineResultV1` and generates
via `DeepSeekClient.complete`, the non-streaming path), while this tool must
yield incremental SSE `delta` events and a final validated `answer` event.
Reusing the pipeline would drop the streaming contract or force a breaking
signature change; the shared normalization helpers (`build_retrieval_payload`,
`from_raw_response`, `build_reference_registry`, `build_generation_prompt`)
remain the single source of truth for the sequence itself.
"""

from __future__ import annotations

from typing import Any, Iterator

from langchain_core.tools import BaseTool

from lightrag.context import (
    build_reference_registry,
    from_raw_response,
    serialize_context,
)
from lightrag.generation import (
    AnswerBundleV1,
    BundleValidationResult,
    extract_json_object,
    validate_bundle,
)
from lightrag.query_spec import QuerySpecV1, RetrievalConfigV1, R_A

# The SINGLE canonical description of the KB tool (#207). The KB is a
# web-application testing-methodology knowledge base (WSTG + writeup overlays),
# NOT a "fault knowledge base": agents must never use it to verify or adjudicate
# a bug - only to retrieve methodology. This constant is imported verbatim by
# the pod and hunter tool surfaces (pod/tools.py, hunter_tools.py) so the
# description cannot drift between sites. The ontology list must match the real
# `lightrag.ontology.ENTITY_TYPES`.
QUERY_LIGHTRAG_DESCRIPTION = (
    "Retrieve web-application testing methodology from the LightRAG knowledge "
    "base when specific knowledge is missing from your reasoning. Query it for "
    "the target stack's mechanisms or shape, for payloads and their vectors, "
    "for a technique or methodology gap, or for verification-symptom shape. It "
    "covers the ontology's concepts: technology stack, attack technique, "
    "payload pattern, artifact, observable signal, vulnerability class, attack "
    "goal, attacker capability, precondition environment, and defensive "
    "control. Returns a structured answer: a summary plus per-concept "
    "explanations (type, canonical name, prose) with provenance references and "
    "knowledge gaps. Answers may enrich beyond the retrieved context - confirm "
    "concrete target parameters on the target. An empty or degraded result "
    "means the KB has nothing further - continue on your own grounding."
)


class LightRagQueryTool(BaseTool):
    """Query LightRAG for methodology evidence and return a validated answer."""

    name: str = "query_lightrag"
    description: str = QUERY_LIGHTRAG_DESCRIPTION
    args_schema: type[QuerySpecV1] = QuerySpecV1
    client: Any
    llm: Any
    retrieval_config: RetrievalConfigV1 = R_A

    def _build_prompt(self, spec: QuerySpecV1, raw: dict) -> tuple[str, Any]:
        from lightrag.generation import build_generation_prompt
        from lightrag.query_spec import build_retrieval_payload

        payload = build_retrieval_payload(spec, self.retrieval_config)
        context = from_raw_response(raw)
        registry = build_reference_registry(
            context, evidence_refs=[item.ref for item in spec.evidence]
        )
        prompt = build_generation_prompt(spec, serialize_context(context), registry)
        return prompt, registry

    def _validate_text(
        self, spec: QuerySpecV1, registry: Any, text: str
    ) -> tuple[BundleValidationResult, AnswerBundleV1 | None, bool]:
        payload_obj = extract_json_object(text)
        result = validate_bundle(payload_obj, spec=spec, registry=registry)
        if result.is_valid and result.bundle is not None:
            return result, result.bundle, True
        from lightrag.pipeline import _deterministic_fallback

        return result, _deterministic_fallback(spec, result.errors), False

    def stream(self, spec: QuerySpecV1) -> Iterator[dict]:
        from lightrag.observability import registry_metadata, stage_span

        collected: list[str] = []
        bundle = None
        accepted = False
        try:
            with stage_span("retrieval", input={
                "query": _q3(spec),
                "mode": self.retrieval_config.mode,
                "top_k": self.retrieval_config.chunk_top_k,
            }) as retrieval:
                raw = self.client.query_data(
                    {
                        "query": _q3(spec),
                        "mode": self.retrieval_config.mode,
                        "chunk_top_k": self.retrieval_config.chunk_top_k,
                        "max_total_tokens": self.retrieval_config.max_total_tokens,
                    }
                )
                prompt, registry = self._build_prompt(spec, raw)
                context = from_raw_response(raw)
                retrieval.record(
                    status=raw.get("status"),
                    chunk_ids=[c.reference_id for c in context.chunks],
                    chunk_scores=_chunk_scores(raw),
                    registry=registry_metadata(registry),
                )
            with stage_span("generation", input={"prompt": prompt}) as generation:
                reasoning: list[str] = []
                for event in self.llm.stream(prompt):
                    if event.get("type") == "reasoning":
                        reasoning.append(event["text"])
                        continue
                    if event.get("type") == "delta":
                        collected.append(event["text"])
                    yield event
                generation.record(
                    reasoning_content="".join(reasoning),
                    output="".join(collected),
                )
            text = "".join(collected)
            with stage_span("validation", input={
                "scenario_id": spec.scenario_id,
            }) as validation:
                result, bundle, accepted = self._validate_text(spec, registry, text)
                self._record_validation(validation, result, bundle, accepted)
        except Exception as exc:  # noqa: BLE001 - fail-open: the author lane keeps going
            from lightrag.pipeline import _deterministic_fallback  # noqa: PLC0415
            bundle = _deterministic_fallback(
                spec, [f"tool_failed: {type(exc).__name__}"]
            )
            accepted = False
        yield {
            "type": "answer",
            "answer": bundle.model_dump() if bundle else {},
            "accepted": accepted,
        }

    def _record_validation(
        self,
        validation: Any,
        result: BundleValidationResult,
        bundle: AnswerBundleV1 | None,
        accepted: bool,
    ) -> None:
        """Surface the validation outcome as structured observation metadata + scores.

        #207 defect 1, points E and F: an accepted-but-empty-provenance bundle
        (``PROV []``) and the entity-count contract drift are surfaced, not
        swallowed. ``degraded`` marks a validation that fell back to the
        deterministic fallback. Fail-open: recording never raises into the
        turn.
        """
        provenance = bundle.provenance_references if bundle else []
        entity_count = float(len(bundle.ontology_explanations)) if bundle else 0.0
        validation.record(
            accepted=accepted,
            degraded=not accepted,
            errors=result.errors,
            rejected_citations=result.rejected_citations,
            provenance_references=provenance,
        )
        validation.metric("provenance_empty", 1.0 if not provenance else 0.0)
        validation.metric("entity_count", entity_count)

    def _run(self, **kwargs: Any) -> str:
        spec = QuerySpecV1(**kwargs)
        events = list(self.stream(spec))
        return json_dump(events[-1]["answer"])

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def _q3(spec: QuerySpecV1) -> str:
    from lightrag.query_spec import build_q3

    return build_q3(spec)


def _chunk_scores(raw: dict) -> list[float]:
    """Best-effort chunk scores from the raw ``/query/data`` response.

    LightRAG does not consistently surface a score per chunk, so this reads
    whatever the response carries (``score`` / ``order`` fields under each
    chunk) and returns an empty list when absent - the span then records the
    ids without scores (observability must never crash the pipeline).
    """
    scores: list[float] = []
    data = raw.get("data") or {}
    for item in data.get("chunks") or []:
        if not isinstance(item, dict):
            continue
        for key in ("score", "order"):
            value = item.get(key)
            if value is None:
                continue
            try:
                scores.append(float(value))
                break
            except (TypeError, ValueError):
                continue
    return scores


def json_dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def build_lightrag_tool(
    *, retrieval_config: RetrievalConfigV1 = R_A
) -> LightRagQueryTool:
    """Construct the production tool from app config (lazy, no I/O here)."""
    from polymerhus.app.config import config
    from lightrag.client import LightRAGHttpClient
    from lightrag.generation import DeepSeekClient

    client = LightRAGHttpClient(
        base_url=config.LIGHTRAG_BASE_API_URL,
        api_key=config.LIGHTRAG_API_KEY,
    )
    llm = DeepSeekClient(
        base_url=config.QUERY_LLM_BASE_URL,
        api_key=config.QUERY_LLM_API_KEY,
        model=config.QUERY_LLM_MODEL,
        max_tokens=config.QUERY_LLM_MAX_TOKENS,
        timeout=config.QUERY_LLM_TIMEOUT_SECONDS,
    )
    return LightRagQueryTool(
        client=client, llm=llm, retrieval_config=retrieval_config
    )
