"""LangChain tool exposing the LightRAG query pipeline, with a streamed answer."""

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
