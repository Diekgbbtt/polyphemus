from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from polymerhus.lightrag.experiment_tracker import DEFAULT_HISTORY_DB, ExperimentTracker


DEFAULT_TEST_CASES = Path("data/lightrag/benchmarks/wstg_test_cases.json")
DEFAULT_WSTG_MANIFEST = Path("data/lightrag/inputs/wstg_preprocessed/.manifest.json")
DEFAULT_TEMPLATE_TYPES = (
    "ontology_feature_to_wstg",
    "feature_to_threat",
    "wstg_category_oriented",
    "step_by_step_methodology",
)
DEFAULT_DIAGNOSTIC_TEMPLATE_TYPES = (
    "diagnostic_exact_id",
    "diagnostic_title_category",
    "diagnostic_abstract_feature",
)
DEFAULT_MODES = ("naive", "local", "global", "hybrid", "mix")
WSTG_ID_RE = re.compile(r"\bWSTG-[A-Z0-9]{4}-\d{2}(?:-\d+)?\b", re.IGNORECASE)
WSTG_LOOSE_ID_RE = re.compile(r"\bWSTG-[A-Z0-9]+-\d{2}(?:-\d+)?\b", re.IGNORECASE)
WSTG_BARE_ID_RE = re.compile(
    r"(?<!WSTG-)\b(?:INFO|CONF|IDNT|ATHN|ATHZ|SESS|INPV|ERRH|CRYP|BUSL|CLNT|APIT)-\d{2}(?:-\d+)?\b",
    re.IGNORECASE,
)
WSTG_CATEGORY_NAMES = {
    "INFO": "Information Gathering",
    "CONF": "Configuration and Deployment Management Testing",
    "IDNT": "Identity Management Testing",
    "ATHN": "Authentication Testing",
    "ATHZ": "Authorization Testing",
    "SESS": "Session Management Testing",
    "INPV": "Input Validation Testing",
    "ERRH": "Error Handling",
    "CRYP": "Weak Cryptography",
    "BUSL": "Business Logic Testing",
    "CLNT": "Client-side Testing",
    "APIT": "API Testing",
}


@dataclass(frozen=True)
class LightRAGBenchmarkConfig:
    mode: str
    top_k: int = 40
    max_tokens: int = 12000
    temperature: float = 0.0
    community_level: int | None = None
    only_need_context: bool = False
    pass_optional_query_params: bool = False

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    def to_query_extra(self) -> dict[str, Any]:
        extra: dict[str, Any] = {
            "top_k": self.top_k,
            "max_total_tokens": self.max_tokens,
            "stream": False,
            "only_need_context": self.only_need_context,
        }
        if self.pass_optional_query_params:
            extra["temperature"] = self.temperature
            if self.community_level is not None:
                extra["community_level"] = self.community_level
        return extra

    def to_query_payload(self, query: str) -> dict[str, Any]:
        return {
            "query": query,
            "mode": self.mode,
            "include_references": True,
            "include_chunk_content": True,
            **self.to_query_extra(),
        }


@dataclass(frozen=True)
class BenchmarkResult:
    experiment_id: str
    run_label: str
    test_case_id: str
    query_template_type: str
    lightrag_config: dict[str, Any]
    retrieved_subgraph: dict[str, Any]
    raw_response: str
    metrics: dict[str, Any]


def load_test_cases(path: str | Path = DEFAULT_TEST_CASES) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"{path} must contain a top-level cases list")
    return cases


def load_wstg_catalog(
    path: str | Path = DEFAULT_WSTG_MANIFEST,
) -> dict[str, dict[str, Any]]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog: dict[str, dict[str, Any]] = {}
    for scenario in payload.get("scenarios", []):
        wstg_id = str(scenario.get("wstg_id", "")).upper()
        if not wstg_id:
            continue
        category_code = _category_code_for_wstg_id(wstg_id)
        catalog[wstg_id] = {
            "wstg_id": wstg_id,
            "title": scenario.get("title", ""),
            "primary_document": scenario.get("primary_document", ""),
            "category_code": scenario.get("category_code") or category_code,
            "category": scenario.get("category")
            or WSTG_CATEGORY_NAMES.get(category_code, category_code),
            "canonical_aliases": scenario.get("canonical_aliases", []),
            "canonical_vulnerability_classes": scenario.get(
                "canonical_vulnerability_classes",
                [],
            ),
            "ontology_query_anchors": scenario.get("ontology_query_anchors", {}),
            "ontology_query_anchor_terms": scenario.get(
                "ontology_query_anchor_terms",
                [],
            ),
        }
    return catalog


def build_configs(
    *,
    modes: Sequence[str] = DEFAULT_MODES,
    top_k_values: Sequence[int] = (40,),
    max_tokens: int = 12000,
    temperature: float = 0.0,
    community_level: int | None = None,
    pass_optional_query_params: bool = False,
    only_need_context: bool = False,
) -> list[LightRAGBenchmarkConfig]:
    return [
        LightRAGBenchmarkConfig(
            mode=mode,
            top_k=top_k,
            max_tokens=max_tokens,
            temperature=temperature,
            community_level=community_level,
            only_need_context=only_need_context,
            pass_optional_query_params=pass_optional_query_params,
        )
        for mode in modes
        for top_k in top_k_values
    ]


def build_query_prompt(test_case: Mapping[str, Any], template_type: str) -> str:
    profile = abstracted_profile_for_case(test_case)
    title = test_case.get("title", test_case_id_for_case(test_case))
    profile_json = json.dumps(profile, indent=2, sort_keys=True)
    ontology_projection = ontology_projection_for_profile(profile)
    ontology_projection_json = json.dumps(
        ontology_projection,
        indent=2,
        sort_keys=True,
    )

    shared = (
        "You are evaluating OWASP WSTG applicability for a Phase 2 web application profile. "
        "Use only the OWASP Web Security Testing Guide corpus retrieved by LightRAG. "
        "Do not invent WSTG IDs. If evidence is insufficient, state the gap.\n\n"
        f"Abstracted web application profile title: {title}\n"
        f"Phase 2 profile JSON:\n{profile_json}\n\n"
        "Return concise, actionable output with these fields:\n"
        "- Relevant WSTG test cases with WSTG IDs\n"
        "- Vulnerability hypotheses mapped to observed features\n"
        "- Testing methodology and concrete probes\n"
        "- Evidence to collect and negative controls\n"
        "- Preconditions, impact, and confidence\n"
    )

    if template_type == "ontology_feature_to_wstg":
        return (
            f"{shared}\n"
            "Query strategy: use the methodology ontology as the retrieval path. "
            "Treat the following projection as candidate ontology evidence, not "
            "as ground truth:\n"
            f"{ontology_projection_json}\n\n"
            "Resolve direct and multi-hop paths in this order: TechnologyStack, "
            "PreconditionEnvironment, Artifact, and ObservableSignal anchors; "
            "then map to VulnerabilityClass, AttackTechnique, PayloadPattern, "
            "DefensiveControl, and finally canonical WSTG IDs. Prefer WSTG "
            "scenario anchors and source-file evidence. Do not return a WSTG ID "
            "unless retrieved context contains that ID or its scenario anchor."
        )
    if template_type == "feature_to_threat":
        return (
            f"{shared}\n"
            "Query strategy: map each observed feature, technology, input vector, "
            "auth mechanism, and browser behavior to likely WSTG tests and attack hypotheses. "
            "Prioritize tests that directly explain the observed attack surface."
        )
    if template_type == "wstg_category_oriented":
        return (
            f"{shared}\n"
            "Query strategy: first infer the most relevant WSTG categories, then select "
            "specific WSTG test cases inside those categories. Explain why unrelated "
            "categories are lower priority."
        )
    if template_type == "step_by_step_methodology":
        return (
            f"{shared}\n"
            "Query strategy: produce a step-by-step test plan ordered by cheapest signal "
            "first. For each step, cite the WSTG ID, the request or browser action to run, "
            "the expected vulnerable signal, and the safe negative control."
        )
    if template_type == "diagnostic_exact_id":
        expected_ids = ", ".join(normalize_wstg_ids(test_case.get("expected_wstg_ids", [])))
        terms = ", ".join(str(term) for term in test_case.get("evaluation_terms", []))
        return (
            "Diagnostic retrieval check: exact WSTG ID anchoring.\n"
            "Use only retrieved OWASP WSTG context. Return the canonical WSTG IDs, "
            "titles, categories, and methodology snippets for these IDs.\n\n"
            f"Required WSTG IDs: {expected_ids}\n"
            f"Profile title: {title}\n"
            f"Relevant feature terms: {terms}\n"
        )
    if template_type == "diagnostic_title_category":
        categories = ", ".join(
            sorted(
                {
                    WSTG_CATEGORY_NAMES.get(_category_code_for_wstg_id(wstg_id), "")
                    for wstg_id in normalize_wstg_ids(test_case.get("expected_wstg_ids", []))
                }
                - {""}
            )
        )
        topics = ", ".join(str(topic) for topic in test_case.get("expected_topics", []))
        return (
            "Diagnostic retrieval check: WSTG title and category anchoring.\n"
            "Find OWASP WSTG test cases by category, title, and testing theme. "
            "Return canonical WSTG IDs, titles, and methodology snippets.\n\n"
            f"Profile title: {title}\n"
            f"Likely WSTG categories: {categories}\n"
            f"Testing themes: {topics}\n"
        )
    if template_type == "diagnostic_abstract_feature":
        feature_terms = _abstract_feature_terms(profile)
        return (
            "Diagnostic retrieval check: abstract feature to WSTG mapping.\n"
            "Map this abstracted web application footprint to the most applicable "
            "OWASP WSTG test cases. Return canonical WSTG IDs, titles, categories, "
            "and methodology snippets.\n\n"
            f"Profile title: {title}\n"
            f"Abstract feature terms: {', '.join(feature_terms)}\n"
        )
    raise ValueError(f"unknown query template type: {template_type}")


def run_benchmark(
    *,
    test_cases: Sequence[Mapping[str, Any]],
    client: Any,
    tracker: ExperimentTracker,
    configs: Sequence[LightRAGBenchmarkConfig],
    template_types: Sequence[str] = DEFAULT_TEMPLATE_TYPES,
    fail_fast: bool = False,
    run_label: str = "",
    wstg_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[BenchmarkResult]:
    results: list[BenchmarkResult] = []
    for test_case in test_cases:
        case_id = test_case_id_for_case(test_case)
        profile = abstracted_profile_for_case(test_case)
        for template_type in template_types:
            query = build_query_prompt(test_case, template_type)
            for config in configs:
                start = time.perf_counter()
                try:
                    response = _query_client(client, query=query, config=config)
                except Exception as exc:
                    if fail_fast:
                        raise
                    latency_ms = (time.perf_counter() - start) * 1000
                    raw_response = ""
                    retrieved_subgraph = {
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    }
                    metrics = compute_metrics(
                        test_case,
                        raw_response=raw_response,
                        retrieved_subgraph={},
                        latency_ms=latency_ms,
                        wstg_catalog=wstg_catalog,
                    )
                    metrics.update(
                        {
                            "error": True,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )
                else:
                    latency_ms = (time.perf_counter() - start) * 1000
                    raw_response = extract_response_text(response)
                    retrieved_subgraph = extract_retrieved_subgraph(response)
                    metrics = compute_metrics(
                        test_case,
                        raw_response=raw_response,
                        retrieved_subgraph=retrieved_subgraph,
                        latency_ms=latency_ms,
                        wstg_catalog=wstg_catalog,
                    )
                    metrics["error"] = False
                experiment_id = tracker.log_run(
                    test_case_id=case_id,
                    abstracted_profile=profile,
                    query_template_type=template_type,
                    query_payload=config.to_query_payload(query),
                    lightrag_config=config.to_record(),
                    retrieved_subgraph=retrieved_subgraph,
                    raw_response=raw_response,
                    metrics=metrics,
                    run_label=run_label,
                )
                results.append(
                    BenchmarkResult(
                        experiment_id=experiment_id,
                        run_label=run_label,
                        test_case_id=case_id,
                        query_template_type=template_type,
                        lightrag_config=config.to_record(),
                        retrieved_subgraph=retrieved_subgraph,
                        raw_response=raw_response,
                        metrics=metrics,
                    )
                )
    return results


def compute_metrics(
    test_case: Mapping[str, Any],
    *,
    raw_response: str,
    retrieved_subgraph: Mapping[str, Any] | None = None,
    latency_ms: float = 0.0,
    wstg_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    expected_ids = normalize_wstg_ids(test_case.get("expected_wstg_ids", []))
    searchable_text = raw_response
    if retrieved_subgraph:
        searchable_text += "\n" + json.dumps(retrieved_subgraph, sort_keys=True)
    mentioned_ids = extract_wstg_ids(searchable_text)
    malformed_ids = extract_malformed_wstg_ids(searchable_text)
    bare_ids = extract_bare_wstg_ids(searchable_text)
    matched_ids = sorted(set(expected_ids) & set(mentioned_ids))
    missing_ids = sorted(set(expected_ids) - set(mentioned_ids))
    unexpected_ids = sorted(set(mentioned_ids) - set(expected_ids))
    valid_catalog_ids = set(wstg_catalog or {})
    if valid_catalog_ids:
        valid_mentioned_ids = sorted(set(mentioned_ids) & valid_catalog_ids)
        invalid_mentioned_ids = sorted(set(mentioned_ids) - valid_catalog_ids)
    else:
        valid_mentioned_ids = mentioned_ids
        invalid_mentioned_ids = []

    recall = len(matched_ids) / len(expected_ids) if expected_ids else 0.0
    precision = len(matched_ids) / len(mentioned_ids) if mentioned_ids else 0.0
    valid_precision = (
        len(matched_ids) / len(valid_mentioned_ids) if valid_mentioned_ids else 0.0
    )
    keyword_coverage = _keyword_coverage(
        raw_response,
        test_case.get("evaluation_terms") or test_case.get("expected_topics") or [],
    )
    context_anchor = compute_context_anchor_score(
        searchable_text,
        test_case,
        wstg_catalog=wstg_catalog,
    )
    relevance_score = (0.7 * recall) + (0.3 * keyword_coverage)

    return {
        "latency_ms": round(latency_ms, 3),
        "estimated_token_count": estimate_token_count(raw_response),
        "wstg_code_recall": round(recall, 4),
        "wstg_code_precision": round(precision, 4),
        "valid_wstg_code_precision": round(valid_precision, 4),
        "hallucination_precision_rating": round(precision, 4),
        "relevance_score": round(relevance_score, 4),
        "keyword_coverage": round(keyword_coverage, 4),
        "context_anchor_score": context_anchor["score"],
        "context_anchor_components": context_anchor["components"],
        "expected_wstg_ids": expected_ids,
        "matched_wstg_ids": matched_ids,
        "missing_wstg_ids": missing_ids,
        "unexpected_wstg_ids": unexpected_ids,
        "mentioned_wstg_ids": mentioned_ids,
        "valid_mentioned_wstg_ids": valid_mentioned_ids,
        "invalid_mentioned_wstg_ids": invalid_mentioned_ids,
        "malformed_wstg_ids": malformed_ids,
        "malformed_wstg_id_count": len(malformed_ids),
        "bare_wstg_ids": bare_ids,
        "bare_wstg_id_count": len(bare_ids),
    }


def extract_response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        for key in ("response", "answer", "result", "text", "content"):
            value = response.get(key)
            if isinstance(value, str):
                return value
        nested = response.get("data")
        if isinstance(nested, Mapping):
            for key in ("response", "answer", "result", "text", "content"):
                value = nested.get(key)
                if isinstance(value, str):
                    return value
        return json.dumps(response, sort_keys=True)
    return str(response)


def extract_retrieved_subgraph(response: Any) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        return {}
    subgraph: dict[str, Any] = {}
    for source in _response_sources(response):
        for key in (
            "entities",
            "relations",
            "relationships",
            "subgraph",
            "references",
            "source_chunks",
            "chunks",
            "context",
        ):
            if key in source and key not in subgraph:
                subgraph[key] = source[key]
    return subgraph


def extract_wstg_ids(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in WSTG_ID_RE.finditer(text)})


def extract_malformed_wstg_ids(text: str) -> list[str]:
    strict_ids = set(extract_wstg_ids(text))
    loose_ids = {match.group(0).upper() for match in WSTG_LOOSE_ID_RE.finditer(text)}
    return sorted(loose_ids - strict_ids)


def extract_bare_wstg_ids(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in WSTG_BARE_ID_RE.finditer(text)})


def compute_context_anchor_score(
    text: str,
    test_case: Mapping[str, Any],
    *,
    wstg_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_text = text.lower()
    expected_ids = normalize_wstg_ids(test_case.get("expected_wstg_ids", []))
    expected_count = len(expected_ids)
    id_coverage = (
        sum(1 for wstg_id in expected_ids if wstg_id.lower() in normalized_text)
        / expected_count
        if expected_count
        else 0.0
    )
    title_hits = 0
    category_hits = 0
    for wstg_id in expected_ids:
        catalog_entry = (wstg_catalog or {}).get(wstg_id, {})
        title = str(catalog_entry.get("title") or "")
        if title and title.lower() in normalized_text:
            title_hits += 1
        category = str(catalog_entry.get("category") or "")
        if category and category.lower() in normalized_text:
            category_hits += 1
    title_coverage = title_hits / expected_count if expected_count else 0.0
    category_coverage = category_hits / expected_count if expected_count else 0.0
    methodology_marker = 1.0 if any(
        marker in normalized_text
        for marker in (
            "methodology",
            "how to test",
            "test objectives",
            "testing methodology",
            "concrete test",
            "probe",
        )
    ) else 0.0
    components = {
        "expected_id_coverage": round(id_coverage, 4),
        "expected_title_coverage": round(title_coverage, 4),
        "expected_category_coverage": round(category_coverage, 4),
        "methodology_marker": methodology_marker,
    }
    score = sum(components.values()) / len(components)
    return {"score": round(score, 4), "components": components}


def normalize_wstg_ids(values: Sequence[Any]) -> list[str]:
    return sorted({str(value).upper() for value in values})


def estimate_token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def abstracted_profile_for_case(test_case: Mapping[str, Any]) -> dict[str, Any]:
    profile = (
        test_case.get("phase2_abstracted_profile")
        or test_case.get("abstracted_profile")
        or test_case.get("profile")
    )
    if not isinstance(profile, Mapping):
        raise ValueError(f"test case {test_case_id_for_case(test_case)} has no profile")
    return dict(profile)


def test_case_id_for_case(test_case: Mapping[str, Any]) -> str:
    case_id = test_case.get("test_case_id") or test_case.get("id")
    if not case_id:
        raise ValueError("test case is missing test_case_id")
    return str(case_id)


def summarize_results(results: Sequence[BenchmarkResult]) -> dict[str, Any]:
    if not results:
        return {"run_count": 0}
    return {
        "run_count": len(results),
        "avg_wstg_code_recall": _average_metric(results, "wstg_code_recall"),
        "avg_wstg_code_precision": _average_metric(results, "wstg_code_precision"),
        "avg_valid_wstg_code_precision": _average_metric(
            results,
            "valid_wstg_code_precision",
        ),
        "avg_relevance_score": _average_metric(results, "relevance_score"),
        "avg_context_anchor_score": _average_metric(results, "context_anchor_score"),
        "avg_malformed_wstg_id_count": _average_metric(
            results,
            "malformed_wstg_id_count",
        ),
        "avg_bare_wstg_id_count": _average_metric(results, "bare_wstg_id_count"),
        "avg_latency_ms": _average_metric(results, "latency_ms"),
        "error_count": sum(1 for result in results if result.metrics.get("error")),
        "best_runs": [
            {
                "experiment_id": result.experiment_id,
                "run_label": result.run_label,
                "test_case_id": result.test_case_id,
                "query_template_type": result.query_template_type,
                "lightrag_config": result.lightrag_config,
                "metrics": result.metrics,
            }
            for result in sorted(
                results,
                key=lambda item: (
                    item.metrics.get("relevance_score", 0),
                    item.metrics.get("wstg_code_recall", 0),
                    item.metrics.get("wstg_code_precision", 0),
                ),
                reverse=True,
            )[:5]
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark LightRAG WSTG retrieval for attack hypothesis generation."
    )
    parser.add_argument("--cases", default=str(DEFAULT_TEST_CASES))
    parser.add_argument("--db", default=str(DEFAULT_HISTORY_DB))
    parser.add_argument("--run-label", default="")
    parser.add_argument("--wstg-manifest", default=str(DEFAULT_WSTG_MANIFEST))
    parser.add_argument("--base-url", default="http://127.0.0.1:9621")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--modes", nargs="+", default=list(DEFAULT_MODES))
    parser.add_argument("--top-k", nargs="+", type=int, default=[40])
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--community-level", type=int, default=None)
    parser.add_argument("--template-types", nargs="+", default=None)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Use exact-ID, title/category, and abstract-feature diagnostic query templates.",
    )
    parser.add_argument("--limit-cases", type=int, default=None)
    parser.add_argument(
        "--only-context",
        action="store_true",
        help="Ask LightRAG for retrieval context only, without answer generation.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first failed LightRAG query instead of logging the error.",
    )
    parser.add_argument(
        "--pass-optional-query-params",
        action="store_true",
        help="Forward temperature and community_level to LightRAG if the server supports them.",
    )
    args = parser.parse_args(argv)

    from polymerhus.lightrag.client import LightRAGHttpClient

    test_cases = load_test_cases(args.cases)
    if args.limit_cases is not None:
        test_cases = test_cases[: args.limit_cases]
    template_types = args.template_types
    if template_types is None:
        template_types = (
            list(DEFAULT_DIAGNOSTIC_TEMPLATE_TYPES)
            if args.diagnostic
            else list(DEFAULT_TEMPLATE_TYPES)
        )
    wstg_catalog = load_wstg_catalog(args.wstg_manifest)
    configs = build_configs(
        modes=args.modes,
        top_k_values=args.top_k,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        community_level=args.community_level,
        only_need_context=args.only_context,
        pass_optional_query_params=args.pass_optional_query_params,
    )
    client = LightRAGHttpClient(
        args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    with ExperimentTracker(args.db) as tracker:
        results = run_benchmark(
            test_cases=test_cases,
            client=client,
            tracker=tracker,
            configs=configs,
            template_types=template_types,
            fail_fast=args.fail_fast,
            run_label=args.run_label,
            wstg_catalog=wstg_catalog,
        )
    print(json.dumps(summarize_results(results), indent=2, sort_keys=True))
    return 0


def _query_client(
    client: Any,
    *,
    query: str,
    config: LightRAGBenchmarkConfig,
) -> Any:
    if hasattr(client, "query"):
        return client.query(query, mode=config.mode, extra=config.to_query_extra())
    if callable(client):
        return client(query=query, config=config)
    raise TypeError("client must expose query(...) or be callable")


def _response_sources(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = [response]
    nested = response.get("data")
    if isinstance(nested, Mapping):
        sources.append(nested)
    return sources


def _keyword_coverage(text: str, terms: Sequence[Any]) -> float:
    normalized_terms = [str(term).lower() for term in terms if str(term).strip()]
    if not normalized_terms:
        return 0.0
    normalized_text = text.lower()
    matched = sum(1 for term in normalized_terms if term in normalized_text)
    return matched / len(normalized_terms)


def _average_metric(results: Sequence[BenchmarkResult], metric_name: str) -> float:
    values = [float(result.metrics.get(metric_name, 0.0)) for result in results]
    return round(sum(values) / len(values), 4)


def _category_code_for_wstg_id(wstg_id: str) -> str:
    match = re.match(r"^WSTG-([A-Z0-9]{4})-\d{2}", wstg_id.upper())
    return match.group(1) if match else ""


def ontology_projection_for_profile(profile: Mapping[str, Any]) -> dict[str, list[str]]:
    projection: dict[str, list[str]] = {
        "TechnologyStack": [],
        "PreconditionEnvironment": [],
        "DefensiveControl": [],
        "VulnerabilityClass": [],
        "AttackTechnique": [],
        "PayloadPattern": [],
        "Artifact": [],
        "ObservableSignal": [],
    }

    def add(entity_type: str, value: Any) -> None:
        text = str(value).strip()
        if not text:
            return
        if text not in projection[entity_type]:
            projection[entity_type].append(text)

    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(item, (*path, str(key)))
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                visit(item, path)
            return
        if value is None:
            return

        text = str(value).strip()
        if not text:
            return
        key_path = ".".join(path).casefold()
        lowered = text.casefold()

        if any(marker in key_path for marker in _PROFILE_TECHNOLOGY_KEYS):
            add("TechnologyStack", text)
        if any(marker in key_path for marker in _PROFILE_PRECONDITION_KEYS):
            add("PreconditionEnvironment", text)
        if any(marker in key_path for marker in _PROFILE_ARTIFACT_KEYS):
            add("Artifact", text)
        if any(marker in key_path for marker in _PROFILE_SIGNAL_KEYS):
            add("ObservableSignal", text)
        if any(marker in key_path for marker in _PROFILE_CONTROL_KEYS):
            add("DefensiveControl", text)

        for marker, entity_type, canonical in _PROFILE_KEYWORD_ONTOLOGY_HINTS:
            if marker in lowered:
                add(entity_type, canonical)

    visit(profile)
    return {
        entity_type: values[:20]
        for entity_type, values in projection.items()
        if values
    }


_PROFILE_TECHNOLOGY_KEYS = (
    "application_type",
    "frontend",
    "backend",
    "backend_style",
    "api_styles",
    "data_stores",
    "parser_stack",
    "processing_stack",
)
_PROFILE_PRECONDITION_KEYS = (
    "auth_mechanisms",
    "authorization_model",
    "features",
    "observed_inputs",
    "observed_endpoints",
    "session_controls",
    "token_storage",
    "cross_origin_features",
    "network_behavior",
)
_PROFILE_SIGNAL_KEYS = (
    "security_signals",
    "cookie_observations",
    "network_behavior",
)
_PROFILE_CONTROL_KEYS = (
    "controls",
    "cookie_observations",
    "session_controls",
)
_PROFILE_ARTIFACT_KEYS = (
    "observed_endpoints",
    "token_storage",
)
_PROFILE_KEYWORD_ONTOLOGY_HINTS = (
    ("graphql", "TechnologyStack", "GraphQL"),
    ("rest", "TechnologyStack", "REST API"),
    ("jwt", "TechnologyStack", "JSON Web Token"),
    ("localstorage", "TechnologyStack", "Browser Storage"),
    ("mongo", "TechnologyStack", "MongoDB"),
    ("postgres", "TechnologyStack", "PostgreSQL"),
    ("cors", "TechnologyStack", "Cross-Origin Resource Sharing"),
    ("postmessage", "TechnologyStack", "Browser PostMessage"),
    ("iframe", "TechnologyStack", "Iframe Widget"),
    ("object storage", "TechnologyStack", "Object Storage"),
    ("cdn", "TechnologyStack", "CDN"),
    ("introspection", "PreconditionEnvironment", "GraphQL Introspection Enabled"),
    ("sequential", "PreconditionEnvironment", "Sequential Object Identifier"),
    ("sequential", "VulnerabilityClass", "Broken Object-Level Authorization"),
    ("adjacent account", "AttackTechnique", "Object ID Tampering"),
    ("nested json", "PreconditionEnvironment", "Nested JSON Request Body"),
    ("raw json operators", "PreconditionEnvironment", "Raw JSON Operators Preserved"),
    ("sort expression", "PreconditionEnvironment", "Sort Expression Accepted As String"),
    ("server performs outbound", "PreconditionEnvironment", "Server-Side URL Fetch Feature"),
    ("redirect", "PreconditionEnvironment", "Redirects Followed"),
    ("metadata endpoint", "PreconditionEnvironment", "Metadata Endpoint Reachable"),
    ("download by path", "PreconditionEnvironment", "Download By Path Parameter"),
    ("template preview", "PreconditionEnvironment", "Template Preview Parameter"),
    ("csrf", "VulnerabilityClass", "Cross-Site Request Forgery"),
    ("xss", "VulnerabilityClass", "Cross-Site Scripting"),
    ("idor", "VulnerabilityClass", "Insecure Direct Object Reference"),
    ("bola", "VulnerabilityClass", "Broken Object-Level Authorization"),
    ("nosql", "VulnerabilityClass", "NoSQL Injection"),
    ("sql", "VulnerabilityClass", "SQL Injection"),
    ("ssrf", "VulnerabilityClass", "Server-Side Request Forgery"),
    ("path traversal", "VulnerabilityClass", "Path Traversal"),
    ("directory traversal", "VulnerabilityClass", "Path Traversal"),
    ("file inclusion", "VulnerabilityClass", "File Include"),
    ("mime", "DefensiveControl", "MIME Type Validation"),
    ("extension allow", "DefensiveControl", "File Extension Allowlist"),
    ("samesite", "DefensiveControl", "SameSite Cookie Attribute"),
    ("secure missing", "DefensiveControl", "Secure Cookie Attribute"),
    ("content-security-policy", "DefensiveControl", "Content-Security-Policy"),
    ("csp", "DefensiveControl", "Content-Security-Policy"),
    ("stack trace", "Artifact", "Stack Trace"),
    ("bearer token", "Artifact", "Bearer Token"),
    ("access token", "Artifact", "JWT Access Token"),
    ("database syntax", "ObservableSignal", "Database Error Message"),
    ("error messages", "ObservableSignal", "Database Error Message"),
    ("response timing", "ObservableSignal", "Response Time Delay"),
    ("private ip", "ObservableSignal", "Internal Service Response Timing Difference"),
)


def _abstract_feature_terms(profile: Mapping[str, Any]) -> list[str]:
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)
        elif value is not None:
            text = str(value).strip()
            if text:
                values.append(text)

    collect(profile)
    return list(dict.fromkeys(values))[:30]


if __name__ == "__main__":
    raise SystemExit(main())
