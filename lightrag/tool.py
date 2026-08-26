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

from polymerhus.lightrag.context import (
    build_reference_registry,
    from_raw_response,
    serialize_context,
)
from polymerhus.lightrag.generation import (
    AnswerBundleV1,
    extract_json_object,
    validate_bundle,
)
from polymerhus.lightrag.query_spec import QuerySpecV1, RetrievalConfigV1, R_A


class LightRagQueryTool(BaseTool):
    """Query LightRAG for methodology evidence and return a validated answer."""

    name: str = "query_lightrag"
    description: str = (
        "Retrieve reusable web-application testing methodology from LightRAG "
        "for one bounded testing concern, then return a structured answer: one "
        "ontology entity (type + canonical name) with a detailed prose "
        "explanation, grounded only in the returned references."
    )
    args_schema: type[QuerySpecV1] = QuerySpecV1
    client: Any
    llm: Any
    retrieval_config: RetrievalConfigV1 = R_A

    def _build_prompt(self, spec: QuerySpecV1, raw: dict) -> tuple[str, Any]:
        from polymerhus.lightrag.generation import build_generation_prompt
        from polymerhus.lightrag.query_spec import build_retrieval_payload

        payload = build_retrieval_payload(spec, self.retrieval_config)
        context = from_raw_response(raw)
        registry = build_reference_registry(
            context, evidence_refs=[item.ref for item in spec.evidence]
        )
        prompt = build_generation_prompt(spec, serialize_context(context), registry)
        return prompt, registry

    def _validate_text(
        self, spec: QuerySpecV1, registry: Any, text: str
    ) -> tuple[AnswerBundleV1 | None, bool]:
        payload_obj = extract_json_object(text)
        result = validate_bundle(payload_obj, spec=spec, registry=registry)
        if result.is_valid and result.bundle is not None:
            return result.bundle, True
        from polymerhus.lightrag.pipeline import _deterministic_fallback

        return _deterministic_fallback(spec, result.errors), False

    def stream(self, spec: QuerySpecV1) -> Iterator[dict]:
        try:
            raw = self.client.query_data(
                {
                    "query": _q3(spec),
                    "mode": self.retrieval_config.mode,
                    "chunk_top_k": self.retrieval_config.chunk_top_k,
                    "max_total_tokens": self.retrieval_config.max_total_tokens,
                }
            )
            prompt, registry = self._build_prompt(spec, raw)
            collected: list[str] = []
            for event in self.llm.stream(prompt):
                if event.get("type") == "delta":
                    collected.append(event["text"])
                yield event
            bundle, accepted = self._validate_text(spec, registry, "".join(collected))
        except Exception as exc:  # noqa: BLE001 - fail-open: the author lane keeps going
            from polymerhus.lightrag.pipeline import _deterministic_fallback  # noqa: PLC0415
            bundle = _deterministic_fallback(
                spec, [f"tool_failed: {type(exc).__name__}"]
            )
            accepted = False
        yield {
            "type": "answer",
            "answer": bundle.model_dump() if bundle else {},
            "accepted": accepted,
        }

    def _run(self, **kwargs: Any) -> str:
        spec = QuerySpecV1(**kwargs)
        events = list(self.stream(spec))
        return json_dump(events[-1]["answer"])

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def _q3(spec: QuerySpecV1) -> str:
    from polymerhus.lightrag.query_spec import build_q3

    return build_q3(spec)


def json_dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def build_lightrag_tool(
    *, retrieval_config: RetrievalConfigV1 = R_A
) -> LightRagQueryTool:
    """Construct the production tool from app config (lazy, no I/O here)."""
    from polymerhus.app.config import config
    from polymerhus.lightrag.client import LightRAGHttpClient
    from polymerhus.lightrag.generation import DeepSeekClient

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
