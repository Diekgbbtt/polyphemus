from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from lightrag.client import LightRAGHttpClient
from lightrag.ontology import ENTITY_TYPES
from lightrag.packager import package_methodology
from lightrag.retriever import RoutedMethodologyRetriever
from lightrag.types import FaultContext, KnowledgeQuery, RetrievalOptions


DEFAULT_OUTPUT_DIR = Path("data/lightrag/benchmarks")
DEFAULT_BASE_URL = "http://127.0.0.1:9621"
DEFAULT_WRITEUP_URL = "http://127.0.0.1:9622"
CANONICAL_ENTITY_TYPES = tuple(ENTITY_TYPES)


@dataclass(frozen=True)
class OntologyBenchmarkConfig:
    label: str
    mode: str
    top_k: int
    only_need_context: bool = True

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    def to_query_extra(self) -> dict[str, Any]:
        return {
            "top_k": self.top_k,
            "only_need_context": self.only_need_context,
            "stream": False,
        }


@dataclass(frozen=True)
class OntologyBenchmarkCase:
    test_id: str
    question: str
    expected_sources: tuple[str, ...]
    expected_trigger_reason: str | None
    min_base_candidates: int
    pattern: str
    objective: str
    symptom: str
    taxonomy_tags: tuple[str, ...]
    fault_context: FaultContext
    ontology_mapping: Mapping[str, Sequence[str]]


DEFAULT_CONFIGS = (
    OntologyBenchmarkConfig(
        label="standard",
        mode="mix",
        top_k=10,
        only_need_context=True,
    ),
    OntologyBenchmarkConfig(
        label="deep_graph_retrieval",
        mode="mix",
        top_k=20,
        only_need_context=True,
    ),
    OntologyBenchmarkConfig(
        label="hybrid_search",
        mode="hybrid",
        top_k=15,
        only_need_context=True,
    ),
)


DEFAULT_CASES = (
    OntologyBenchmarkCase(
        test_id="A",
        question=(
            "Describe the testing strategy and validation methodology for verifying "
            "broken access control and session handling in enterprise OAuth2/OIDC "
            "implementations."
        ),
        expected_sources=("base",),
        expected_trigger_reason=None,
        min_base_candidates=0,
        pattern="target_state",
        objective=(
            "Retrieve WSTG-backed validation methodology for enterprise OAuth2/OIDC "
            "broken access control and session handling."
        ),
        symptom=(
            "Session state, authorization code flow, token storage, and role boundary "
            "behavior must be validated without 0xdf overlay-specific triggers."
        ),
        taxonomy_tags=("oauth2", "oidc", "broken-access-control", "session-handling"),
        fault_context=FaultContext(
            vulnerability_hypothesis=(
                "Broken access control or session handling weakness in OAuth2/OIDC."
            ),
            observed_conditions=[
                "enterprise OAuth2/OIDC implementation",
                "session management and authorization flow boundaries",
                "role or tenant authorization checks",
            ],
            defenses_present=[
                "OIDC token validation",
                "session cookies",
                "authorization server controls",
            ],
        ),
        ontology_mapping={
            "Target": [
                "TechnologyStack: OAuth2/OIDC",
                "PreconditionEnvironment: enterprise authorization flow",
            ],
            "Symptom": [
                "VulnerabilityClass/Fault: broken access control",
                "ObservableSignal: inconsistent role/session boundary behavior",
            ],
            "AttackTechnique": [
                "authorization bypass validation",
                "session handling test methodology",
            ],
            "PayloadPattern": [
                "tampered authorization/session parameters",
            ],
            "TestingStrategy/Mitigation": [
                "negative controls",
                "scope and role boundary validation",
            ],
        },
    ),
    OntologyBenchmarkCase(
        test_id="B",
        question=(
            "Given a JWT authentication flow accepting weak signatures, what attack "
            "techniques and payload patterns allow token forgery and role claim "
            "escalation to bypass request filters?"
        ),
        expected_sources=("base", "writeups"),
        expected_trigger_reason="concept:jwt",
        min_base_candidates=0,
        pattern="target_state",
        objective=(
            "Retrieve JWT token forgery techniques, role-claim escalation payloads, "
            "and bypass-aware validation methodology."
        ),
        symptom=(
            "JWT authentication flow accepts weak signatures and modified role claims "
            "while request filters are present."
        ),
        taxonomy_tags=("jwt", "bypass", "request-filter"),
        fault_context=FaultContext(
            vulnerability_hypothesis="JWT signature validation weakness.",
            observed_conditions=[
                "weak JWT signature accepted",
                "role claim escalation changes authorization behavior",
                "request filter or WAF is present",
            ],
            defenses_present=["request filter", "WAF Or Request Filter"],
        ),
        ontology_mapping={
            "Target": [
                "PreconditionEnvironment: JWT Authentication Flow",
                "DefensiveControl: WAF Or Request Filter",
            ],
            "Symptom": [
                "VulnerabilityClass/Fault: JWT Secret Weakness",
                "ObservableSignal: role claim behavior changes",
            ],
            "AttackTechnique": ["JWT Token Forgery"],
            "PayloadPattern": [
                "weak signature token",
                "role claim escalation payload",
            ],
            "TestingStrategy/Mitigation": [
                "signature verification controls",
                "request filter bypass validation",
            ],
        },
    ),
    OntologyBenchmarkCase(
        test_id="C",
        question=(
            "How to exploit Java deserialization gadget chains via custom RMI/JRMP "
            "listeners when standard payload filters are active?"
        ),
        expected_sources=("base", "writeups"),
        expected_trigger_reason="base_candidates_below_threshold",
        min_base_candidates=1,
        pattern="target_state",
        objective=(
            "Retrieve methodology for Java deserialization gadget chains with custom "
            "RMI/JRMP listener constraints and payload filters."
        ),
        symptom=(
            "Serialized Java object input suggests gadget-chain execution through "
            "custom RMI/JRMP listeners while standard payload filters are active."
        ),
        taxonomy_tags=("java", "rmi", "jrmp", "payload-filter"),
        fault_context=FaultContext(
            vulnerability_hypothesis="Java insecure deserialization gadget chain.",
            observed_conditions=[
                "serialized object input",
                "custom RMI/JRMP listener requirement",
                "standard payload filters active",
            ],
            defenses_present=["payload filter"],
        ),
        ontology_mapping={
            "Target": [
                "TechnologyStack: Java RMI/JRMP",
                "PreconditionEnvironment: serialized object input",
            ],
            "Symptom": [
                "VulnerabilityClass/Fault: Insecure Deserialization",
                "ObservableSignal: gadget-like behavior",
            ],
            "AttackTechnique": [
                "Insecure Deserialization Gadget Execution",
                "custom RMI/JRMP listener exploitation",
            ],
            "PayloadPattern": [
                "serialized gadget chain payload",
                "listener callback payload",
            ],
            "TestingStrategy/Mitigation": [
                "payload filter bypass review",
                "manual-review safe validation",
            ],
        },
    ),
)


class CapturingLightRAGClient:
    """LightRAG client wrapper that records raw responses per routed source."""

    def __init__(
        self,
        source_name: str,
        inner: LightRAGHttpClient,
        *,
        query_extra: Mapping[str, Any],
    ):
        self.source_name = source_name
        self.inner = inner
        self.query_extra = dict(query_extra)
        self.calls: list[dict[str, Any]] = []

    def query(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        include_references: bool = True,
        include_chunk_content: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        merged_extra = {
            **self.query_extra,
            **(extra or {}),
        }
        call = {
            "source": self.source_name,
            "mode": mode,
            "extra": merged_extra,
            "prompt": query,
            "kwargs": {
                "mode": mode,
                "include_references": include_references,
                "include_chunk_content": include_chunk_content,
                "extra": merged_extra,
            },
            "request_payload": {
                "query": query,
                "mode": mode,
                "include_references": include_references,
                "include_chunk_content": include_chunk_content,
                **merged_extra,
            },
        }
        try:
            response = self.inner.query(
                query,
                mode=mode,
                include_references=include_references,
                include_chunk_content=include_chunk_content,
                extra=merged_extra,
            )
        except Exception as exc:
            call["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            self.calls.append(call)
            raise
        call["response"] = response
        self.calls.append(call)
        return response


def build_ontology_prompt(test_id: str) -> str:
    case = _case_by_id(test_id)
    return _prompt_for_case(case)


def run_benchmark_grid(
    *,
    retriever: Any | None = None,
    answer_retriever: Any | None = None,
    configs: Sequence[OntologyBenchmarkConfig] = DEFAULT_CONFIGS,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    timestamp: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    writeup_url: str = DEFAULT_WRITEUP_URL,
    api_key: str | None = None,
    timeout: float = 120.0,
    include_answers: bool = False,
) -> Path:
    timestamp = timestamp or _timestamp()
    output_path = Path(output_dir) / f"ontology_query_benchmark_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for case in DEFAULT_CASES:
        for config in configs:
            try:
                result = _run_case_config(
                    case=case,
                    config=config,
                    retriever=retriever,
                    base_url=base_url,
                    writeup_url=writeup_url,
                    api_key=api_key,
                    timeout=timeout,
                    include_answers=include_answers,
                    answer_retriever=answer_retriever,
                )
            except Exception as exc:
                result = _error_result(case=case, config=config, error=exc)
            results.append(result)

    expected_run_ids = [
        _run_id(case.test_id, config.label)
        for case in DEFAULT_CASES
        for config in configs
    ]

    payload = {
        "schema_version": 1,
        "generated_at": timestamp,
        "base_url": base_url,
        "writeup_url": writeup_url,
        "canonical_entity_types": list(CANONICAL_ENTITY_TYPES),
        "query_matrix": [_case_record(case) for case in DEFAULT_CASES],
        "hyperparameter_grid": [config.to_record() for config in configs],
        "results": results,
        "summary": _summarize_results(results, expected_run_ids=expected_run_ids),
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def extract_context_payload(response: Any) -> dict[str, Any]:
    raw_context = extract_response_text(response)
    graph_objects = _graph_objects_from_response(response)
    entities_by_type = _entities_by_type(graph_objects)
    relations = _relations_from_objects(graph_objects)
    source_chunks = _source_chunks_from_response(response)
    return {
        "retrieved_entities_by_type": entities_by_type,
        "ontology_role_projection": _ontology_role_projection(entities_by_type),
        "extracted_relations": relations,
        "source_chunks": source_chunks,
        "raw_context": raw_context,
        "raw_context_bytes": len(raw_context.encode("utf-8")),
    }


def extract_response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if hasattr(response, "model_dump"):
        response = response.model_dump(mode="json")
    if isinstance(response, Mapping):
        for key in ("response", "summary", "answer", "result", "text", "content"):
            value = response.get(key)
            if isinstance(value, str):
                return value
        nested = response.get("data")
        if isinstance(nested, Mapping):
            return extract_response_text(nested)
        return json.dumps(response, sort_keys=True)
    return str(response)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run canonical ontology query benchmarks across routed LightRAG KBs."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--writeup-url", default=DEFAULT_WRITEUP_URL)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timestamp", default=None)
    parser.add_argument(
        "--include-answers",
        dest="include_answers",
        action="store_true",
        help=(
            "Deprecated alias for --include-structured-bundles; records validated "
            "MethodologyBundle payloads instead of free-form answers."
        ),
    )
    parser.add_argument(
        "--include-structured-bundles",
        dest="include_answers",
        action="store_true",
        help="Also run and save validated structured MethodologyBundle payloads.",
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit non-zero when routing or canonical-entity verification fails.",
    )
    args = parser.parse_args(argv)

    output_path = run_benchmark_grid(
        output_dir=args.output_dir,
        timestamp=args.timestamp,
        base_url=args.base_url,
        writeup_url=args.writeup_url,
        api_key=args.api_key,
        timeout=args.timeout,
        include_answers=args.include_answers,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    print(json.dumps({"output_path": str(output_path), **summary}, indent=2, sort_keys=True))
    if args.fail_on_gate and (
        summary["expected_route_mismatches"]
        or summary["runs_without_canonical_entities"]
        or summary["runs_without_canonical_source_context"]
        or summary["missing_runs"]
        or summary["error_count"]
    ):
        return 1
    return 0


def _run_case_config(
    *,
    case: OntologyBenchmarkCase,
    config: OntologyBenchmarkConfig,
    retriever: Any | None,
    base_url: str,
    writeup_url: str,
    api_key: str | None,
    timeout: float,
    include_answers: bool,
    answer_retriever: Any | None,
) -> dict[str, Any]:
    _ = include_answers, answer_retriever
    query = _knowledge_query_for_case(case, config)
    captures: list[dict[str, Any]] = []
    active_retriever = retriever
    if active_retriever is None:
        base_client = CapturingLightRAGClient(
            "base",
            LightRAGHttpClient(base_url, api_key=api_key, timeout=timeout),
            query_extra=config.to_query_extra(),
        )
        writeup_client = CapturingLightRAGClient(
            "writeups",
            LightRAGHttpClient(writeup_url, api_key=api_key, timeout=timeout),
            query_extra=config.to_query_extra(),
        )
        active_retriever = RoutedMethodologyRetriever(
            base_client=base_client,
            writeup_client=writeup_client,
            min_base_candidates=case.min_base_candidates,
            overlay_mode=config.mode,
        )
        captures = [*base_client.calls, *writeup_client.calls]

    try:
        bundle = active_retriever.retrieve_methodology(query)
    except Exception as exc:
        captures = _capture_calls(active_retriever, captures)
        return _error_result(case=case, config=config, error=exc, query=query, captures=captures)
    captures = _capture_calls(active_retriever, captures)
    bundle_payload = _jsonable(bundle)
    if not isinstance(bundle_payload, Mapping):
        bundle_payload = {"summary": extract_response_text(bundle_payload)}

    if not captures:
        captures = [
            {
                "source": "bundle",
                "mode": config.mode,
                "extra": config.to_query_extra(),
                "prompt": query.to_retrieval_prompt(),
                "kwargs": {
                    "mode": config.mode,
                    "include_references": True,
                    "include_chunk_content": True,
                    "extra": config.to_query_extra(),
                },
                "request_payload": {
                    "query": query.to_retrieval_prompt(),
                    "mode": config.mode,
                    "include_references": True,
                    "include_chunk_content": True,
                    **config.to_query_extra(),
                },
                "response": bundle_payload,
            }
        ]

    merged_context = _merged_capture_context(captures, bundle_payload)
    context_payload = extract_context_payload(merged_context)
    metadata = dict(bundle_payload.get("retrieval_metadata") or {})
    routing = {
        "sources_queried": metadata.get("sources_queried", []),
        "trigger_reason": metadata.get("overlay_trigger_reason", []),
        "expected_sources": list(case.expected_sources),
        "expected_trigger_reason": case.expected_trigger_reason,
    }
    routing["matches_expected_sources"] = (
        routing["sources_queried"] == list(case.expected_sources)
    )
    routing["matches_expected_trigger"] = _trigger_matches(
        routing["trigger_reason"],
        case.expected_trigger_reason,
    )
    structured_bundle = _structured_bundle_record(query, bundle_payload, captures)
    result = {
        "test_id": case.test_id,
        "query": case.question,
        "exact_retriever_input": _exact_retriever_input(query),
        "exact_lightrag_calls": [_exact_lightrag_call_record(capture) for capture in captures],
        "ontology_mapping": dict(case.ontology_mapping),
        "prompt": _prompt_for_case(case),
        "routing_decision": routing,
        "hyperparameters": config.to_record(),
        "retrieved_entities_by_type": context_payload["retrieved_entities_by_type"],
        "ontology_role_projection": context_payload["ontology_role_projection"],
        "extracted_relations": context_payload["extracted_relations"],
        "source_chunks": context_payload["source_chunks"],
        "raw_context": context_payload["raw_context"],
        "raw_context_bytes": context_payload["raw_context_bytes"],
        "raw_source_contexts": [_capture_record(capture) for capture in captures],
        "structured_methodology_bundle": structured_bundle,
        "canonical_entity_type_coverage": [
            entity_type
            for entity_type, values in context_payload["retrieved_entities_by_type"].items()
            if values
        ],
    }
    return result


def _structured_bundle_record(
    query: KnowledgeQuery,
    bundle_payload: Mapping[str, Any],
    captures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        metadata = dict(bundle_payload.get("retrieval_metadata") or {})
        packaged = package_methodology(query, bundle_payload)
        structured = packaged.model_dump(mode="json")
        structured["retrieval_metadata"] = {
            **structured.get("retrieval_metadata", {}),
            "sources_queried": metadata.get("sources_queried", []),
            "overlay_trigger_reason": metadata.get("overlay_trigger_reason", []),
            "raw_source_contexts": [_structured_capture_record(capture) for capture in captures],
        }
        return structured
    except Exception as exc:
        return {
            "query_id": query.query_id,
            "summary": "No evidence-backed methodology bundle could be produced.",
            "candidates": [],
            "knowledge_gaps": ["Structured methodology bundle generation failed."],
            "source_tier": "validated_base",
            "source_chunks": [],
            "retrieval_metadata": {
                "sources_queried": [],
                "overlay_trigger_reason": [],
            },
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


def _error_result(
    *,
    case: OntologyBenchmarkCase,
    config: OntologyBenchmarkConfig,
    error: Exception,
    query: KnowledgeQuery | None = None,
    captures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    query = query or _knowledge_query_for_case(case, config)
    return {
        "test_id": case.test_id,
        "query": case.question,
        "exact_retriever_input": _exact_retriever_input(query),
        "exact_lightrag_calls": [_exact_lightrag_call_record(capture) for capture in captures],
        "ontology_mapping": dict(case.ontology_mapping),
        "prompt": _prompt_for_case(case),
        "routing_decision": {
            "sources_queried": [],
            "trigger_reason": [],
            "expected_sources": list(case.expected_sources),
            "expected_trigger_reason": case.expected_trigger_reason,
            "matches_expected_sources": False,
            "matches_expected_trigger": case.expected_trigger_reason is None,
        },
        "hyperparameters": config.to_record(),
        "retrieved_entities_by_type": {},
        "ontology_role_projection": {
            "Target": [],
            "Symptom": [],
            "AttackTechnique": [],
            "PayloadPattern": [],
            "Artifact": [],
            "TestingStrategy/Mitigation": [],
        },
        "extracted_relations": [],
        "source_chunks": [],
        "raw_context": "",
        "raw_context_bytes": 0,
        "raw_source_contexts": [],
        "canonical_entity_type_coverage": [],
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }


def _knowledge_query_for_case(
    case: OntologyBenchmarkCase,
    config: OntologyBenchmarkConfig,
) -> KnowledgeQuery:
    return KnowledgeQuery(
        query_id=f"ontology-benchmark-{case.test_id}",
        pattern=case.pattern,  # type: ignore[arg-type]
        objective=_prompt_for_case(case),
        symptom=case.symptom,
        taxonomy_tags=list(case.taxonomy_tags),
        fault_context=case.fault_context,
        retrieval=RetrievalOptions(mode=config.mode, max_candidates=config.top_k),  # type: ignore[arg-type]
    )


def _prompt_for_case(case: OntologyBenchmarkCase) -> str:
    mapping_json = json.dumps(case.ontology_mapping, indent=2, sort_keys=True)
    return (
        "Given Symptom -> Retrieve Testing Techniques using the canonical security "
        "methodology ontology.\n\n"
        f"Question: {case.question}\n\n"
        "Weave the answer through these ontology roles:\n"
        "- Target (TechnologyStack/PreconditionEnvironment)\n"
        "- VulnerabilityClass/Fault\n"
        "- AttackTechnique\n"
        "- PayloadPattern\n"
        "- ObservableSignal\n"
        "- TestingStrategy/Mitigation\n\n"
        f"Ontology mapping anchors:\n{mapping_json}\n\n"
        "Return retrieved graph context, concrete testing methodology, relevant "
        "payload patterns, expected observable signals, and mitigation/validation "
        "checks. Prefer canonical entity names and relation paths."
    )


def _case_by_id(test_id: str) -> OntologyBenchmarkCase:
    normalized = test_id.strip().upper()
    for case in DEFAULT_CASES:
        if case.test_id == normalized:
            return case
    raise ValueError(f"unknown ontology benchmark test_id: {test_id}")


def _case_record(case: OntologyBenchmarkCase) -> dict[str, Any]:
    return {
        "test_id": case.test_id,
        "question": case.question,
        "expected_sources": list(case.expected_sources),
        "expected_trigger_reason": case.expected_trigger_reason,
        "min_base_candidates": case.min_base_candidates,
        "ontology_mapping": dict(case.ontology_mapping),
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _exact_retriever_input(query: KnowledgeQuery) -> dict[str, Any]:
    return {
        "method": "RoutedMethodologyRetriever.retrieve_methodology",
        "args": [query.model_dump(mode="json")],
        "kwargs": {},
        "retrieval_prompt": query.to_retrieval_prompt(),
    }


def _exact_lightrag_call_record(capture: Mapping[str, Any]) -> dict[str, Any]:
    raw_response = _jsonable(capture.get("response"))
    record = {
        "source": capture.get("source"),
        "prompt": capture.get("prompt", ""),
        "kwargs": capture.get("kwargs", {}),
        "request_payload": capture.get("request_payload", {}),
        "raw_response": raw_response,
        "raw_lightrag_context": extract_response_text(raw_response)
        if raw_response is not None
        else "",
    }
    if capture.get("error"):
        record["error"] = capture["error"]
    return record


def _capture_calls(
    retriever: Any,
    initial_captures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    captures = list(initial_captures)
    for attr in ("base_client", "writeup_client"):
        client = getattr(retriever, attr, None)
        calls = getattr(client, "calls", None)
        if isinstance(calls, list):
            for call in calls:
                if call not in captures:
                    captures.append(call)
    return captures


def _merged_capture_context(
    captures: Sequence[Mapping[str, Any]],
    bundle_payload: Mapping[str, Any],
) -> dict[str, Any]:
    raw_parts = []
    references = []
    for capture in captures:
        response = capture.get("response")
        text = extract_response_text(response)
        raw_parts.append(f"## SOURCE: {capture.get('source', 'unknown')}\n{text}")
        extracted = extract_context_payload(response)
        references.extend(extracted.get("source_chunks", []))
    if bundle_payload:
        raw_parts.append(f"## BUNDLE\n{extract_response_text(bundle_payload)}")
        references.extend(_source_chunks_from_response(bundle_payload))
    return {
        "response": "\n\n".join(raw_parts),
        "references": references,
    }


def _capture_record(capture: Mapping[str, Any]) -> dict[str, Any]:
    response = capture.get("response")
    raw_context = extract_response_text(response) if response is not None else ""
    payload = extract_context_payload(response)
    record = {
        "source": capture.get("source"),
        "mode": capture.get("mode"),
        "extra": capture.get("extra", {}),
        "prompt": capture.get("prompt", ""),
        "kwargs": capture.get("kwargs", {}),
        "request_payload": capture.get("request_payload", {}),
        "raw_response": _jsonable(response),
        "raw_context": raw_context,
        "raw_context_bytes": len(raw_context.encode("utf-8")),
        "retrieved_entities_by_type": payload["retrieved_entities_by_type"],
        "extracted_relations": payload["extracted_relations"],
    }
    if capture.get("error"):
        record["error"] = capture["error"]
    return record


def _structured_capture_record(capture: Mapping[str, Any]) -> dict[str, Any]:
    response = capture.get("response")
    raw_context = extract_response_text(response) if response is not None else ""
    record = {
        "source": capture.get("source"),
        "mode": capture.get("mode"),
        "extra": capture.get("extra", {}),
        "prompt": capture.get("prompt", ""),
        "kwargs": capture.get("kwargs", {}),
        "request_payload": capture.get("request_payload", {}),
        "raw_response": _jsonable(response),
        "raw_context": raw_context,
        "raw_context_bytes": len(raw_context.encode("utf-8")),
    }
    if capture.get("error"):
        record["error"] = capture["error"]
    return record


def _graph_objects_from_response(response: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    payload = _jsonable(response)
    if isinstance(payload, Mapping):
        _collect_structured_graph_objects(payload, objects)
    text = extract_response_text(payload)
    objects.extend(_json_objects_from_text(text))
    return objects


def _collect_structured_graph_objects(
    payload: Mapping[str, Any],
    objects: list[dict[str, Any]],
) -> None:
    for key in ("entities", "relations", "relationships", "source_chunks", "chunks"):
        value = payload.get(key)
        if isinstance(value, list):
            objects.extend(item for item in value if isinstance(item, dict))
    nested = payload.get("data")
    if isinstance(nested, Mapping):
        _collect_structured_graph_objects(nested, objects)


def _json_objects_from_text(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def _entities_by_type(objects: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {entity_type: [] for entity_type in CANONICAL_ENTITY_TYPES}
    for item in objects:
        entity_type = item.get("type") or item.get("entity_type")
        name = item.get("entity") or item.get("entity_name") or item.get("name")
        if entity_type not in grouped or not isinstance(name, str) or not name.strip():
            continue
        _append_unique(grouped[str(entity_type)], name.strip())
    return {key: value for key, value in grouped.items() if value}


def _relations_from_objects(objects: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    relations: list[dict[str, str]] = []
    seen = set()
    for item in objects:
        subject = (
            item.get("src_id")
            or item.get("source")
            or item.get("subject")
            or item.get("entity1")
        )
        obj = (
            item.get("tgt_id")
            or item.get("target")
            or item.get("object")
            or item.get("entity2")
        )
        predicate = (
            item.get("keywords")
            or item.get("relation")
            or item.get("predicate")
            or item.get("description")
        )
        if not all(isinstance(value, str) and value.strip() for value in (subject, obj, predicate)):
            continue
        relation = {
            "subject": subject.strip(),
            "predicate": predicate.strip(),
            "object": obj.strip(),
        }
        key = (relation["subject"], relation["predicate"], relation["object"])
        if key in seen:
            continue
        seen.add(key)
        relations.append(relation)
    return relations


def _source_chunks_from_response(response: Any) -> list[dict[str, Any]]:
    payload = _jsonable(response)
    if not isinstance(payload, Mapping):
        return []
    chunks = []
    for key in ("source_chunks", "references", "chunks"):
        value = payload.get(key)
        if isinstance(value, list):
            chunks.extend(item for item in value if isinstance(item, dict))
    nested = payload.get("data")
    if isinstance(nested, Mapping):
        chunks.extend(_source_chunks_from_response(nested))
    return chunks


def _ontology_role_projection(
    entities_by_type: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    return {
        "Target": [
            *entities_by_type.get("TechnologyStack", []),
            *entities_by_type.get("PreconditionEnvironment", []),
        ],
        "Symptom": [
            *entities_by_type.get("VulnerabilityClass", []),
            *entities_by_type.get("ObservableSignal", []),
        ],
        "AttackTechnique": list(entities_by_type.get("AttackTechnique", [])),
        "PayloadPattern": list(entities_by_type.get("PayloadPattern", [])),
        "Artifact": list(entities_by_type.get("Artifact", [])),
        "TestingStrategy/Mitigation": list(entities_by_type.get("DefensiveControl", [])),
    }


def _trigger_matches(actual: Sequence[str], expected: str | None) -> bool:
    if expected is None:
        return not actual
    return expected in actual


def _summarize_results(
    results: Sequence[Mapping[str, Any]],
    *,
    expected_run_ids: Sequence[str],
) -> dict[str, Any]:
    route_mismatches = []
    trigger_mismatches = []
    without_canonical = []
    without_canonical_source = []
    without_relations = []
    observed_run_ids = []
    error_count = 0
    structured_bundle_run_count = 0
    structured_bundle_error_count = 0
    for result in results:
        route = result["routing_decision"]
        run_id = _run_id(result["test_id"], result["hyperparameters"]["label"])
        observed_run_ids.append(run_id)
        if result.get("error"):
            error_count += 1
        if not route["matches_expected_sources"]:
            route_mismatches.append(
                {
                    "run_id": run_id,
                    "expected": route["expected_sources"],
                    "actual": route["sources_queried"],
                }
            )
        if not route["matches_expected_trigger"]:
            trigger_mismatches.append(
                {
                    "run_id": run_id,
                    "expected": route["expected_trigger_reason"],
                    "actual": route["trigger_reason"],
                }
            )
        if not result["canonical_entity_type_coverage"]:
            without_canonical.append(run_id)
        source_records = {
            source_context.get("source"): source_context
            for source_context in result.get("raw_source_contexts", [])
        }
        for source in route.get("sources_queried", []):
            source_record = source_records.get(source)
            if source_record is None:
                continue
            if not source_record.get("retrieved_entities_by_type"):
                without_canonical_source.append(f"{run_id}:{source}")
        if not result["extracted_relations"]:
            without_relations.append(run_id)
        structured_bundle = result.get("structured_methodology_bundle")
        if isinstance(structured_bundle, Mapping):
            structured_bundle_run_count += 1
            if structured_bundle.get("error"):
                structured_bundle_error_count += 1
    return {
        "run_count": len(results),
        "expected_run_count": len(expected_run_ids),
        "observed_run_ids": observed_run_ids,
        "missing_runs": [
            run_id for run_id in expected_run_ids if run_id not in observed_run_ids
        ],
        "error_count": error_count,
        "expected_route_mismatches": route_mismatches,
        "expected_trigger_mismatches": trigger_mismatches,
        "runs_without_canonical_entities": without_canonical,
        "runs_without_canonical_source_context": without_canonical_source,
        "runs_without_extracted_relations": without_relations,
        "total_raw_context_bytes": sum(int(result["raw_context_bytes"]) for result in results),
        "structured_bundle_run_count": structured_bundle_run_count,
        "structured_bundle_error_count": structured_bundle_error_count,
    }


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _run_id(test_id: Any, config_label: Any) -> str:
    return f"{test_id}:{config_label}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
