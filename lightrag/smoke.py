from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lightrag.client import LightRAGHttpClient
from lightrag.graph_audit import (
    audit_lightrag_graph,
    normalize_lightrag_entity_types,
    parse_lightrag_graphml,
)
from lightrag.experiment_tracker import DEFAULT_HISTORY_DB, ExperimentTracker

DEFAULT_GRAPHML_PATH = Path("data/lightrag/rag_storage/graph_chunk_entity_relation.graphml")
DEFAULT_WSTG_INPUT_DIR = Path("data/lightrag/inputs/wstg_preprocessed")

WSTG_SMOKE_FILES: tuple[str, ...] = (
    "wstg-athz-01-methodology.md",
    "wstg-inpv-01-methodology.md",
    "wstg-inpv-05-methodology.md",
    "wstg-inpv-05-6-methodology.md",
    "wstg-inpv-06-methodology.md",
    "wstg-inpv-07-methodology.md",
    "wstg-inpv-09-methodology.md",
    "wstg-inpv-12-methodology.md",
    "wstg-inpv-19-methodology.md",
)

WSTG_EXPECTED_VULNERABILITY_TYPES: dict[str, str] = {
    "Path Traversal": "VulnerabilityClass",
    "Reflected Cross-Site Scripting": "VulnerabilityClass",
    "SQL Injection": "VulnerabilityClass",
    "NoSQL Injection": "VulnerabilityClass",
    "LDAP Injection": "VulnerabilityClass",
    "XML Injection": "VulnerabilityClass",
    "XPath Injection": "VulnerabilityClass",
    "Command Injection": "VulnerabilityClass",
    "Server-Side Request Forgery": "VulnerabilityClass",
}

WSTG_EXPECTED_SOURCE_FILES: dict[str, str] = {
    "Path Traversal": "wstg-athz-01-methodology.md",
    "Reflected Cross-Site Scripting": "wstg-inpv-01-methodology.md",
    "SQL Injection": "wstg-inpv-05-methodology.md",
    "NoSQL Injection": "wstg-inpv-05-6-methodology.md",
    "LDAP Injection": "wstg-inpv-06-methodology.md",
    "XML Injection": "wstg-inpv-07-methodology.md",
    "XPath Injection": "wstg-inpv-09-methodology.md",
    "Command Injection": "wstg-inpv-12-methodology.md",
    "Server-Side Request Forgery": "wstg-inpv-19-methodology.md",
}

WSTG_EXPECTED_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "Path Traversal": (
        "Directory Traversal File Include",
        "Directory Traversal",
    ),
    "Reflected Cross-Site Scripting": (
        "Reflected Cross-Site Scripting (XSS)",
        "Reflected Cross-site Scripting (XSS)",
        "Reflected Cross Site Scripting (XSS)",
        "Reflected Cross Site Scripting",
        "Reflected XSS",
    ),
    "LDAP Injection": (
        "Ldap Injection",
        "Ldap Injection Vulnerability",
    ),
    "XML Injection": (
        "Xml Injection",
    ),
    "Server-Side Request Forgery": (
        "Server-Side Request Forgery (SSRF)",
        "ServerSide Request Forgery",
        "Server-side Request Forgery",
        "Server-side Request Forgery (SSRF)",
        "SSRF",
        "SSRF Injection",
    ),
}

WSTG_FORBIDDEN_GENERALIZATIONS: tuple[str, ...] = (
    "Stored XSS",
    "DOM XSS",
    "Content Security Policy",
    "CSP",
)

WSTG_SOURCE_NOISE_TERMS: tuple[str, ...] = (
    "OWASP Testing Guide",
    "Mozilla JavaScript Guide",
    "Wikipedia",
    "PayloadsAllTheThings",
)

WSTG_TARGETED_REQUIRED_ANY: dict[str, tuple[tuple[str, ...], ...]] = {
    "Path Traversal": (
        ("../", "directory traversal", "file include", "path traversal"),
        ("Input Validation", "canonicalization", "sanitization"),
    ),
    "Reflected Cross-Site Scripting": (
        ("<script", "HTTP Parameter Pollution", "character encoding", "JavaScript"),
        ("Input Validation", "Web Application Firewall", "sanitization"),
    ),
    "SQL Injection": (
        ("UNION", "Boolean", "time delay", "single quote"),
        ("Input Validation", "Parameterized Queries", "sanitization"),
    ),
    "NoSQL Injection": (
        ("MongoDB", "BSON", "NoSQL database", "$where"),
        ("Input Validation", "sanitization", "query validation"),
    ),
    "LDAP Injection": (
        ("LDAP search filter", "metacharacter", "Boolean", "group aggregation"),
        ("Input Validation", "LDAP Query Validation", "sanitization"),
    ),
    "XML Injection": (
        ("XML metacharacters", "tag injection", "External Entity", "XML parser"),
        ("Input Validation", "validation", "sanitization", "XML validation", "schema", "DTD"),
    ),
    "XPath Injection": (
        ("Blind XPath Injection", "' or '1' = '1", "XPath query", "inference"),
        ("Input Validation", "error message", "filter"),
    ),
    "Command Injection": (
        ("command chaining", "environment variable", "OS command", "time delay"),
        ("Input Validation", "Allow List", "command filter"),
    ),
    "Server-Side Request Forgery": (
        ("localhost", "127.0.0.1", "loopback", "internal service"),
        ("Allow List", "input validation", "URL parser"),
    ),
}


@dataclass(frozen=True)
class QueryCase:
    case_id: str
    prompt: str = ""
    required_terms: tuple[str, ...] = ()
    required_any_terms: tuple[tuple[str, ...], ...] = ()
    required_source_files: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    mode: str = "hybrid"
    top_k: int = 80
    chunk_top_k: int | None = 10
    max_total_tokens: int | None = 30000
    max_entity_tokens: int | None = 12000
    max_relation_tokens: int | None = 12000
    hl_keywords: tuple[str, ...] = ()
    ll_keywords: tuple[str, ...] = ()
    only_need_context: bool = True
    blocking: bool = True


@dataclass(frozen=True)
class QueryEvaluation:
    case_id: str
    blocking: bool
    passed: bool
    missing_terms: list[str]
    missing_any_terms: list[list[str]]
    missing_source_files: list[str]
    forbidden_terms_found: list[str]
    response_excerpt: str


@dataclass(frozen=True)
class GraphGateResult:
    passed: bool
    entity_count: int
    relation_count: int
    type_counts: dict[str, int]
    unknown_type_count: int
    non_canonical_type_count: int
    noise_count: int
    expected_type_mismatches: list[dict]
    missing_required_entities: list[str]
    wrong_required_entity_types: list[dict]
    missing_required_source_files: list[dict]


@dataclass(frozen=True)
class ProcessingStatus:
    complete: bool
    processed: int
    failed: int
    total: int
    busy: bool
    active: bool
    pending_enqueues: int
    raw_counts: dict


@dataclass(frozen=True)
class SmokeRunResult:
    uploaded: list[dict]
    processing: ProcessingStatus | None
    normalization: dict | None
    graph_gate: GraphGateResult | None
    query_evaluations: list[QueryEvaluation]

    @property
    def passed(self) -> bool:
        if self.graph_gate is not None and not self.graph_gate.passed:
            return False
        return all(
            evaluation.passed
            for evaluation in self.query_evaluations
            if evaluation.blocking
        )

    def to_dict(self) -> dict:
        return asdict(self) | {"passed": self.passed}


@dataclass(frozen=True)
class StagedBatchResult:
    batch_number: int
    uploaded_files: list[str]
    upload_responses: list[dict]
    processing: ProcessingStatus
    normalization: dict | None
    graph_gate: GraphGateResult | None
    query_evaluations: list[QueryEvaluation]

    @property
    def passed(self) -> bool:
        if not self.processing.complete:
            return False
        if self.graph_gate is not None and not self.graph_gate.passed:
            return False
        return all(
            evaluation.passed
            for evaluation in self.query_evaluations
            if evaluation.blocking
        )


@dataclass(frozen=True)
class StagedRunResult:
    batches: list[StagedBatchResult]
    final_query_evaluations: list[QueryEvaluation]

    @property
    def passed(self) -> bool:
        return all(batch.passed for batch in self.batches) and all(
            evaluation.passed
            for evaluation in self.final_query_evaluations
            if evaluation.blocking
        )

    def to_dict(self) -> dict:
        return asdict(self) | {"passed": self.passed}


WSTG_DIAGNOSTIC_QUERY_CASES: tuple[QueryCase, ...] = (
    QueryCase(
        case_id="wstg_raw_multi_vulnerability_inventory",
        prompt=(
            "Using only indexed context, fill exactly one row for each expected "
            "vulnerability class: Path Traversal, Reflected Cross-Site Scripting, "
            "SQL Injection, NoSQL Injection, LDAP Injection, XML Injection, "
            "XPath Injection, Command Injection, Server-Side Request Forgery. "
            "Do not add other vulnerability classes. For each row include source "
            "file, 2-4 concrete techniques or payload patterns, 1-3 defensive "
            "controls, and mark missing fields as not found in indexed context. "
            "Do not mention Stored XSS, DOM XSS, or CSP unless the indexed "
            "context explicitly supports them."
        ),
        required_terms=tuple(WSTG_EXPECTED_VULNERABILITY_TYPES),
        required_source_files=tuple(WSTG_EXPECTED_SOURCE_FILES.values()),
        forbidden_terms=WSTG_FORBIDDEN_GENERALIZATIONS,
        hl_keywords=tuple(WSTG_EXPECTED_VULNERABILITY_TYPES),
        ll_keywords=tuple(WSTG_EXPECTED_SOURCE_FILES.values()),
        top_k=100,
        blocking=False,
    ),
)

WSTG_BYPASS_QUERY_CASES: tuple[QueryCase, ...] = (
    QueryCase(
        case_id="wstg_bypass_relations",
        prompt=(
            "Using only indexed WSTG context, identify techniques that bypass or "
            "test defensive controls such as input validation, filters, WAFs, "
            "allow lists, parser validation, and command filters. Return "
            "technique -> defensive control -> relevant condition or payload "
            "pattern."
        ),
        required_any_terms=(
            ("Input Validation", "input validation"),
            ("Web Application Firewall", "WAF"),
            ("Allow List", "allow list", "allowlist"),
            ("Command Filter", "command filter"),
        ),
        forbidden_terms=WSTG_SOURCE_NOISE_TERMS,
        hl_keywords=(
            "defensive controls",
            "bypass techniques",
            "input validation",
            "filters",
            "WAF",
            "allow lists",
        ),
        ll_keywords=(
            "command filters",
            "parser validation",
            "payload pattern",
            "encoding",
        ),
        top_k=80,
        blocking=False,
    ),
)

WSTG_TARGETED_QUERY_CASES: tuple[QueryCase, ...] = tuple(
    QueryCase(
        case_id=(
            "wstg_targeted_"
            + re.sub(r"[^a-z0-9]+", "_", vulnerability.lower()).strip("_")
        ),
        prompt=(
            f"Using only indexed WSTG context, summarize {vulnerability} from "
            f"{source_file}. Include the literal source file name {source_file} "
            "in the answer. Cover vulnerability class, preconditions, concrete "
            "techniques or payload patterns, observable signals, defensive "
            "controls, and likely attack goals. If context is missing, say "
            "missing."
        ),
        required_terms=(vulnerability, source_file),
        required_source_files=(source_file,),
        required_any_terms=WSTG_TARGETED_REQUIRED_ANY.get(vulnerability, ()),
        forbidden_terms=("not found in indexed context",),
        hl_keywords=(vulnerability, "WSTG methodology", source_file),
        ll_keywords=(
            source_file,
            vulnerability,
            *tuple(
                dict.fromkeys(
                    term
                    for group in WSTG_TARGETED_REQUIRED_ANY.get(vulnerability, ())
                    for term in group
                )
            )[:8],
        ),
        top_k=80,
    )
    for vulnerability, source_file in WSTG_EXPECTED_SOURCE_FILES.items()
)

WSTG_QUERY_CASES: tuple[QueryCase, ...] = (
    WSTG_DIAGNOSTIC_QUERY_CASES + WSTG_TARGETED_QUERY_CASES + WSTG_BYPASS_QUERY_CASES
)


def wstg_smoke_paths(input_dir: str | Path = DEFAULT_WSTG_INPUT_DIR) -> list[Path]:
    root = Path(input_dir)
    return [root / filename for filename in WSTG_SMOKE_FILES]


def wstg_methodology_paths(input_dir: str | Path = DEFAULT_WSTG_INPUT_DIR) -> list[Path]:
    return sorted(Path(input_dir).glob("*-methodology.md"))


def wstg_staged_batches(
    input_dir: str | Path = DEFAULT_WSTG_INPUT_DIR,
    *,
    batch_size: int = 10,
    mini_batch_first: bool = True,
    start_batch: int = 0,
    max_batches: int | None = None,
) -> list[list[Path]]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    all_paths = wstg_methodology_paths(input_dir)
    paths_by_name = {path.name: path for path in all_paths}
    batches: list[list[Path]] = []
    used: set[str] = set()

    if mini_batch_first:
        mini_batch = [
            paths_by_name[name]
            for name in WSTG_SMOKE_FILES
            if name in paths_by_name
        ]
        if mini_batch:
            batches.append(mini_batch)
            used.update(path.name for path in mini_batch)

    remaining = [path for path in all_paths if path.name not in used]
    for index in range(0, len(remaining), batch_size):
        batches.append(remaining[index : index + batch_size])

    selected = batches[start_batch:]
    if max_batches is not None:
        selected = selected[:max_batches]
    return selected


def wstg_query_cases_for_files(
    file_names: Iterable[str],
    *,
    input_dir: str | Path = DEFAULT_WSTG_INPUT_DIR,
    include_diagnostics: bool = True,
    include_bypass: bool = True,
    include_manifest_scenarios: bool = False,
    scenario_query_limit: int | None = None,
) -> tuple[QueryCase, ...]:
    loaded = set(file_names)
    targeted = tuple(
        case
        for case in WSTG_TARGETED_QUERY_CASES
        if any(source_file in loaded for source_file in case.required_source_files)
    )
    diagnostics = (
        WSTG_DIAGNOSTIC_QUERY_CASES
        if include_diagnostics and _all_expected_sources_loaded(loaded)
        else ()
    )
    bypass = WSTG_BYPASS_QUERY_CASES if include_bypass and loaded else ()
    manifest_cases = (
        wstg_manifest_query_cases(
            input_dir,
            file_names=loaded,
            limit=scenario_query_limit,
        )
        if include_manifest_scenarios
        else ()
    )
    return diagnostics + targeted + manifest_cases + bypass


def load_wstg_manifest_scenarios(
    input_dir: str | Path = DEFAULT_WSTG_INPUT_DIR,
) -> list[dict[str, str]]:
    manifest_path = Path(input_dir) / ".manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenarios = []
    for scenario in payload.get("scenarios", []):
        primary_document = scenario.get("primary_document")
        title = scenario.get("title")
        wstg_id = scenario.get("wstg_id")
        if not primary_document or not title or not wstg_id:
            continue
        scenarios.append(
            {
                "wstg_id": str(wstg_id),
                "title": str(title),
                "primary_document": str(primary_document),
            }
        )
    return sorted(scenarios, key=lambda item: item["primary_document"])


def wstg_manifest_query_cases(
    input_dir: str | Path = DEFAULT_WSTG_INPUT_DIR,
    *,
    file_names: Iterable[str] | None = None,
    limit: int | None = None,
) -> tuple[QueryCase, ...]:
    selected_files = set(file_names or ())
    cases = []
    for scenario in load_wstg_manifest_scenarios(input_dir):
        source_file = scenario["primary_document"]
        if selected_files and source_file not in selected_files:
            continue
        title = scenario["title"]
        cases.append(
            QueryCase(
                case_id=f"wstg_scenario_{_slug_case_id(source_file)}",
                prompt=(
                    "Using only indexed WSTG context, summarize the methodology "
                    f"for '{title}' from {source_file}. Include the literal source "
                    f"file name {source_file} in the answer. Cover the test "
                    "purpose, relevant target conditions, concrete test methods, "
                    "observable signals or artifacts, and defensive controls when "
                    "present. If context is missing, say missing."
                ),
                required_terms=(source_file,),
                required_any_terms=(_title_signal_terms(title),),
                forbidden_terms=("not found in indexed context",) + WSTG_SOURCE_NOISE_TERMS,
                hl_keywords=(title, "WSTG methodology", source_file),
                ll_keywords=(
                    source_file,
                    *_title_signal_terms(title),
                ),
                top_k=60,
            )
        )
        if limit is not None and len(cases) >= limit:
            break
    return tuple(cases)


def wstg_required_maps_for_files(
    file_names: Iterable[str],
) -> tuple[dict[str, str], dict[str, str]]:
    loaded = set(file_names)
    entity_types = {
        name: entity_type
        for name, entity_type in WSTG_EXPECTED_VULNERABILITY_TYPES.items()
        if WSTG_EXPECTED_SOURCE_FILES.get(name) in loaded
    }
    source_files = {
        name: source_file
        for name, source_file in WSTG_EXPECTED_SOURCE_FILES.items()
        if source_file in loaded
    }
    return entity_types, source_files


def extract_track_id(payload: Any) -> str | None:
    if isinstance(payload, Mapping):
        for key in ("track_id", "id", "request_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = extract_track_id(value)
            if found:
                return found
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for value in payload:
            found = extract_track_id(value)
            if found:
                return found
    return None


def status_counts_from_payload(payload: Mapping[str, Any]) -> dict[str, int]:
    counts = payload.get("status_counts", payload)
    if not isinstance(counts, Mapping):
        return {}
    return {str(key): int(value) for key, value in counts.items() if isinstance(value, int)}


def processing_status(
    *,
    health: Mapping[str, Any],
    status_counts: Mapping[str, Any],
    expected_documents: int,
) -> ProcessingStatus:
    counts = status_counts_from_payload(status_counts)
    processed = counts.get("processed", 0)
    failed = counts.get("failed", 0)
    total = counts.get("all", counts.get("total", sum(counts.values())))
    busy = bool(health.get("pipeline_busy"))
    active = bool(health.get("pipeline_active"))
    pending = int(health.get("pipeline_pending_enqueues") or 0)
    complete = (
        total >= expected_documents
        and processed >= expected_documents
        and failed == 0
        and not busy
        and pending == 0
    )
    return ProcessingStatus(
        complete=complete,
        processed=processed,
        failed=failed,
        total=total,
        busy=busy,
        active=active,
        pending_enqueues=pending,
        raw_counts=dict(counts),
    )


def wait_for_processing(
    client: LightRAGHttpClient,
    *,
    expected_documents: int,
    timeout_seconds: float = 900,
    poll_seconds: float = 5,
) -> ProcessingStatus:
    deadline = time.time() + timeout_seconds
    last_status: ProcessingStatus | None = None
    while True:
        last_status = processing_status(
            health=client.health(),
            status_counts=client.status_counts(),
            expected_documents=expected_documents,
        )
        if last_status.complete:
            return last_status
        if _processing_has_terminal_failures(last_status, expected_documents):
            return last_status
        if time.time() > deadline:
            return last_status
        time.sleep(poll_seconds)


def _processing_has_terminal_failures(
    status: ProcessingStatus,
    expected_documents: int,
) -> bool:
    return (
        status.total >= expected_documents
        and status.failed > 0
        and not status.busy
        and not status.active
        and status.pending_enqueues == 0
    )


def extract_response_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        for key in ("response", "result", "answer", "data"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return str(payload)


def evaluate_query_response(case: QueryCase, response: Any) -> QueryEvaluation:
    text = extract_response_text(response)
    normalized = _normalize_text(text)
    missing_terms = [
        term for term in case.required_terms if not _contains_term(normalized, term)
    ]
    missing_any_terms = [
        list(group)
        for group in case.required_any_terms
        if not any(_contains_term(normalized, term) for term in group)
    ]
    missing_source_files = [
        source_file
        for source_file in case.required_source_files
        if not _contains_term(normalized, source_file)
    ]
    forbidden_terms_found = [
        term for term in case.forbidden_terms if _contains_term(normalized, term)
    ]
    return QueryEvaluation(
        case_id=case.case_id,
        blocking=case.blocking,
        passed=not (
            missing_terms
            or missing_any_terms
            or missing_source_files
            or forbidden_terms_found
        ),
        missing_terms=missing_terms,
        missing_any_terms=missing_any_terms,
        missing_source_files=missing_source_files,
        forbidden_terms_found=forbidden_terms_found,
        response_excerpt=_response_excerpt(text),
    )


def evaluate_graph_gate(
    graphml_path: str | Path = DEFAULT_GRAPHML_PATH,
    *,
    required_entity_types: Mapping[str, str] = WSTG_EXPECTED_VULNERABILITY_TYPES,
    required_source_files: Mapping[str, str] = WSTG_EXPECTED_SOURCE_FILES,
    required_entity_aliases: Mapping[str, Sequence[str]] = WSTG_EXPECTED_ENTITY_ALIASES,
) -> GraphGateResult:
    report = audit_lightrag_graph(graphml_path)
    entities, _relations = parse_lightrag_graphml(graphml_path)
    entities_by_name = {entity.name: entity for entity in entities}

    missing_required_entities = [
        name
        for name in sorted(required_entity_types)
        if not _required_entity_candidates(
            entities_by_name,
            name,
            required_entity_aliases,
        )
    ]
    wrong_required_entity_types = []
    for name, expected_type in required_entity_types.items():
        candidates = _required_entity_candidates(
            entities_by_name,
            name,
            required_entity_aliases,
        )
        if not candidates or any(
            entity.canonical_type == expected_type for entity in candidates
        ):
            continue
        entity = candidates[0]
        wrong_required_entity_types.append(
            {
                "name": name,
                "actual_type": entity.entity_type,
                "canonical_actual_type": entity.canonical_type,
                "expected_type": expected_type,
            }
        )

    missing_required_source_files = []
    for name, expected_source in required_source_files.items():
        candidates = _required_entity_candidates(
            entities_by_name,
            name,
            required_entity_aliases,
        )
        if not candidates:
            continue
        if not any(
            _source_file_matches(entity.file_path, expected_source)
            for entity in candidates
        ):
            missing_required_source_files.append(
                {
                    "name": name,
                    "expected_source_file": expected_source,
                    "actual_source_files": _candidate_source_files(candidates),
                }
            )

    blocking = report.has_blocking_issues
    passed = not (
        blocking
        or missing_required_entities
        or wrong_required_entity_types
        or missing_required_source_files
    )
    return GraphGateResult(
        passed=passed,
        entity_count=report.entity_count,
        relation_count=report.relation_count,
        type_counts=report.type_counts,
        unknown_type_count=len(report.unknown_type_entities),
        non_canonical_type_count=len(report.non_canonical_type_entities),
        noise_count=len(report.noise_entities),
        expected_type_mismatches=[
            asdict(mismatch) for mismatch in report.expected_type_mismatches
        ],
        missing_required_entities=missing_required_entities,
        wrong_required_entity_types=wrong_required_entity_types,
        missing_required_source_files=missing_required_source_files,
    )


def _required_entity_candidates(
    entities_by_name: Mapping[str, Any],
    name: str,
    aliases: Mapping[str, Sequence[str]],
) -> list[Any]:
    candidates = []
    for candidate_name in (name, *aliases.get(name, ())):
        entity = entities_by_name.get(candidate_name)
        if entity is not None:
            candidates.append(entity)
    return candidates


def _candidate_source_files(entities: Sequence[Any]) -> list[str]:
    source_files: list[str] = []
    for entity in entities:
        for source_file in _split_source_files(entity.file_path):
            if source_file not in source_files:
                source_files.append(source_file)
    return source_files


def run_query_cases(
    client: LightRAGHttpClient,
    query_cases: Sequence[QueryCase] = WSTG_QUERY_CASES,
    *,
    blocking_only: bool = False,
) -> list[QueryEvaluation]:
    evaluations = []
    for case in query_cases:
        if blocking_only and not case.blocking:
            continue
        response = client.query(
            case.prompt,
            mode=case.mode,
            extra={
                "top_k": case.top_k,
                "chunk_top_k": case.chunk_top_k,
                "max_total_tokens": case.max_total_tokens,
                "max_entity_tokens": case.max_entity_tokens,
                "max_relation_tokens": case.max_relation_tokens,
                "stream": False,
                "only_need_context": case.only_need_context,
                "hl_keywords": list(case.hl_keywords),
                "ll_keywords": list(case.ll_keywords),
            },
        )
        evaluations.append(evaluate_query_response(case, response))
    return evaluations


def run_smoke_test(
    *,
    client: LightRAGHttpClient,
    graphml_path: str | Path = DEFAULT_GRAPHML_PATH,
    upload_paths: Iterable[str | Path] = (),
    reset_store: bool = False,
    wait_documents: int = 0,
    normalize_types: bool = False,
    delete_noise_entities: bool = True,
    run_graph: bool = True,
    run_queries: bool = True,
    query_cases: Sequence[QueryCase] = WSTG_QUERY_CASES,
    blocking_queries_only: bool = False,
    timeout_seconds: float = 900,
    poll_seconds: float = 5,
) -> SmokeRunResult:
    uploaded = []
    if reset_store:
        client.delete_all_documents()
        client.clear_cache()
    for path in upload_paths:
        response = client.upload_file(path)
        uploaded.append({"source_path": str(path), "response": response})

    processing = None
    expected_documents = wait_documents or len(uploaded)
    if expected_documents:
        processing = wait_for_processing(
            client,
            expected_documents=expected_documents,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )

    normalization = None
    if normalize_types:
        normalization = normalize_lightrag_entity_types(
            graphml_path,
            base_url=client.base_url,
            api_key=client.api_key,
            delete_noise_entities=delete_noise_entities,
        )

    graph_gate = evaluate_graph_gate(graphml_path) if run_graph else None
    query_evaluations = (
        run_query_cases(client, query_cases, blocking_only=blocking_queries_only)
        if run_queries
        else []
    )
    return SmokeRunResult(
        uploaded=uploaded,
        processing=processing,
        normalization=normalization,
        graph_gate=graph_gate,
        query_evaluations=query_evaluations,
    )


def run_staged_wstg_ingestion(
    *,
    client: LightRAGHttpClient,
    batches: Sequence[Sequence[str | Path]],
    graphml_path: str | Path = DEFAULT_GRAPHML_PATH,
    input_dir: str | Path = DEFAULT_WSTG_INPUT_DIR,
    reset_store: bool = False,
    normalize_types: bool = True,
    delete_noise_entities: bool = True,
    run_graph: bool = True,
    run_queries_after_each_batch: bool = False,
    run_final_queries: bool = True,
    include_diagnostic_queries: bool = True,
    include_manifest_scenario_queries: bool = False,
    scenario_query_limit: int | None = None,
    blocking_queries_only: bool = False,
    timeout_seconds: float = 900,
    poll_seconds: float = 5,
    tracker: ExperimentTracker | None = None,
    run_label: str = "",
) -> StagedRunResult:
    if reset_store:
        client.delete_all_documents()
        client.clear_cache()

    baseline_status = processing_status(
        health=client.health(),
        status_counts=client.status_counts(),
        expected_documents=0,
    )
    baseline_total = 0 if reset_store else baseline_status.total
    uploaded_file_names: list[str] = []
    batch_results: list[StagedBatchResult] = []

    for batch_number, batch_paths in enumerate(batches, start=1):
        current_uploaded = []
        upload_responses = []
        for path_value in batch_paths:
            path = Path(path_value)
            upload_response = client.upload_file(path)
            current_uploaded.append(path.name)
            upload_responses.append(
                {
                    "source_path": str(path),
                    "file_name": path.name,
                    "track_id": extract_track_id(upload_response),
                    "response": upload_response,
                }
            )
            uploaded_file_names.append(path.name)

        expected_total = baseline_total + len(uploaded_file_names)
        status = wait_for_processing(
            client,
            expected_documents=expected_total,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )

        normalization = None
        if normalize_types:
            normalization = normalize_lightrag_entity_types(
                graphml_path,
                base_url=client.base_url,
                api_key=client.api_key,
                delete_noise_entities=delete_noise_entities,
            )

        graph_gate = None
        if run_graph:
            entity_types, source_files = wstg_required_maps_for_files(uploaded_file_names)
            graph_gate = evaluate_graph_gate(
                graphml_path,
                required_entity_types=entity_types,
                required_source_files=source_files,
            )

        query_evaluations: list[QueryEvaluation] = []
        if run_queries_after_each_batch:
            query_evaluations = run_query_cases(
                client,
                wstg_query_cases_for_files(
                    current_uploaded,
                    input_dir=input_dir,
                    include_diagnostics=include_diagnostic_queries,
                    include_manifest_scenarios=include_manifest_scenario_queries,
                    scenario_query_limit=scenario_query_limit,
                ),
                blocking_only=blocking_queries_only,
            )

        batch_result = StagedBatchResult(
            batch_number=batch_number,
            uploaded_files=current_uploaded,
            upload_responses=upload_responses,
            processing=status,
            normalization=normalization,
            graph_gate=graph_gate,
            query_evaluations=query_evaluations,
        )
        batch_results.append(batch_result)
        if tracker is not None:
            tracker.log_ingestion_batch(
                batch_number=batch_number,
                input_dir=input_dir,
                uploaded_files=current_uploaded,
                upload_responses=upload_responses,
                processing=asdict(status),
                normalization=normalization,
                graph_gate=asdict(graph_gate) if graph_gate is not None else None,
                query_evaluations=[
                    asdict(evaluation) for evaluation in query_evaluations
                ],
                metrics=_ingestion_batch_metrics(batch_result),
                passed=batch_result.passed,
                run_label=run_label,
            )

    final_query_evaluations: list[QueryEvaluation] = []
    if run_final_queries:
        final_query_evaluations = run_query_cases(
            client,
            wstg_query_cases_for_files(
                uploaded_file_names,
                input_dir=input_dir,
                include_diagnostics=include_diagnostic_queries,
                include_manifest_scenarios=include_manifest_scenario_queries,
                scenario_query_limit=scenario_query_limit,
            ),
            blocking_only=blocking_queries_only,
        )

    return StagedRunResult(
        batches=batch_results,
        final_query_evaluations=final_query_evaluations,
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold()


def _slug_case_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _title_signal_terms(title: str) -> tuple[str, ...]:
    stopwords = {
        "api",
        "and",
        "for",
        "of",
        "the",
        "to",
        "web",
        "test",
        "testing",
        "review",
    }
    terms = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", title):
        normalized = token.casefold()
        if normalized in stopwords:
            continue
        terms.append(token)
    return tuple(dict.fromkeys((title, *terms[:5])))


def _contains_term(normalized_text: str, term: str) -> bool:
    return _normalize_text(term) in normalized_text


def _response_excerpt(text: str, *, max_chars: int = 1200) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3]}..."


def _split_source_files(value: str) -> list[str]:
    return [part.strip() for part in value.split("<SEP>") if part.strip()]


def _source_file_matches(actual_source_files: str, expected_source_file: str) -> bool:
    return expected_source_file in _split_source_files(actual_source_files)


def _all_expected_sources_loaded(file_names: set[str]) -> bool:
    return all(source_file in file_names for source_file in WSTG_EXPECTED_SOURCE_FILES.values())


def _ingestion_batch_metrics(batch_result: StagedBatchResult) -> dict[str, Any]:
    blocking_evaluations = [
        evaluation for evaluation in batch_result.query_evaluations if evaluation.blocking
    ]
    return {
        "processed": batch_result.processing.processed,
        "failed": batch_result.processing.failed,
        "total": batch_result.processing.total,
        "complete": batch_result.processing.complete,
        "graph_gate_passed": (
            batch_result.graph_gate.passed if batch_result.graph_gate is not None else None
        ),
        "query_gate_passed": all(
            evaluation.passed for evaluation in blocking_evaluations
        ),
        "blocking_query_count": len(blocking_evaluations),
        "failed_blocking_query_count": sum(
            1 for evaluation in blocking_evaluations if not evaluation.passed
        ),
        "uploaded_file_count": len(batch_result.uploaded_files),
        "track_ids": [
            item["track_id"]
            for item in batch_result.upload_responses
            if item.get("track_id")
        ],
    }


def _main_payload(result: SmokeRunResult) -> dict:
    return result.to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run automated LightRAG WSTG smoke checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:9621")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--poll", type=float, default=5)
    parser.add_argument("--graphml-path", default=DEFAULT_GRAPHML_PATH.as_posix())
    parser.add_argument("--reset-store", action="store_true")
    parser.add_argument("--normalize-types", action="store_true")
    parser.add_argument(
        "--keep-noise-entities",
        action="store_true",
        help="Do not delete graph-audit noise entities during --normalize-types.",
    )
    parser.add_argument("--skip-graph", action="store_true")
    parser.add_argument("--skip-queries", action="store_true")
    parser.add_argument("--fail-on-issues", action="store_true")
    parser.add_argument("--upload-mini-batch", action="store_true")
    parser.add_argument("--upload-all-wstg", action="store_true")
    parser.add_argument("--upload-staged-wstg", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--start-batch", type=int, default=0)
    parser.add_argument("--query-after-each-batch", action="store_true")
    parser.add_argument("--skip-diagnostic-queries", action="store_true")
    parser.add_argument("--include-scenario-queries", action="store_true")
    parser.add_argument("--scenario-query-limit", type=int, default=None)
    parser.add_argument("--blocking-queries-only", action="store_true")
    parser.add_argument(
        "--history-db",
        default=None,
        help=(
            "SQLite history DB for staged ingestion batch events. Defaults to "
            f"{DEFAULT_HISTORY_DB} when --log-ingestion-history is set."
        ),
    )
    parser.add_argument(
        "--log-ingestion-history",
        action="store_true",
        help="Persist staged WSTG batch upload, processing, gate, and query results.",
    )
    parser.add_argument(
        "--run-label",
        default="",
        help="Optional label stored with ingestion history events.",
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_WSTG_INPUT_DIR.as_posix(),
        help="Directory used with WSTG upload options.",
    )
    parser.add_argument(
        "--upload-file",
        action="append",
        default=[],
        help="Additional Markdown file to upload before smoke checks.",
    )
    parser.add_argument(
        "--wait-documents",
        type=int,
        default=0,
        help="Expected processed document count before checks. Defaults to uploaded count.",
    )
    args = parser.parse_args(argv)

    upload_paths = [Path(path) for path in args.upload_file]
    if args.upload_mini_batch:
        upload_paths.extend(wstg_smoke_paths(args.input_dir))
    if args.upload_all_wstg:
        upload_paths.extend(wstg_methodology_paths(args.input_dir))

    client = LightRAGHttpClient(
        args.base_url,
        api_key=args.api_key,
        timeout=min(args.timeout, 240),
    )

    if args.upload_staged_wstg:
        history_db = args.history_db or DEFAULT_HISTORY_DB
        if args.log_ingestion_history:
            with ExperimentTracker(history_db) as tracker:
                staged_result = run_staged_wstg_ingestion(
                    client=client,
                    batches=wstg_staged_batches(
                        args.input_dir,
                        batch_size=args.batch_size,
                        start_batch=args.start_batch,
                        max_batches=args.max_batches,
                    ),
                    graphml_path=args.graphml_path,
                    input_dir=args.input_dir,
                    reset_store=args.reset_store,
                    normalize_types=args.normalize_types,
                    delete_noise_entities=not args.keep_noise_entities,
                    run_graph=not args.skip_graph,
                    run_queries_after_each_batch=args.query_after_each_batch,
                    run_final_queries=not args.skip_queries,
                    include_diagnostic_queries=not args.skip_diagnostic_queries,
                    include_manifest_scenario_queries=args.include_scenario_queries,
                    scenario_query_limit=args.scenario_query_limit,
                    blocking_queries_only=args.blocking_queries_only,
                    timeout_seconds=args.timeout,
                    poll_seconds=args.poll,
                    tracker=tracker,
                    run_label=args.run_label,
                )
        else:
            staged_result = run_staged_wstg_ingestion(
                client=client,
                batches=wstg_staged_batches(
                    args.input_dir,
                    batch_size=args.batch_size,
                    start_batch=args.start_batch,
                    max_batches=args.max_batches,
                ),
                graphml_path=args.graphml_path,
                input_dir=args.input_dir,
                reset_store=args.reset_store,
                normalize_types=args.normalize_types,
                delete_noise_entities=not args.keep_noise_entities,
                run_graph=not args.skip_graph,
                run_queries_after_each_batch=args.query_after_each_batch,
                run_final_queries=not args.skip_queries,
                include_diagnostic_queries=not args.skip_diagnostic_queries,
                include_manifest_scenario_queries=args.include_scenario_queries,
                scenario_query_limit=args.scenario_query_limit,
                blocking_queries_only=args.blocking_queries_only,
                timeout_seconds=args.timeout,
                poll_seconds=args.poll,
            )
        print(json.dumps(staged_result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True))
        if args.fail_on_issues and not staged_result.passed:
            return 1
        return 0

    if upload_paths:
        query_cases = wstg_query_cases_for_files(
            [path.name for path in upload_paths],
            input_dir=args.input_dir,
            include_diagnostics=not args.skip_diagnostic_queries,
            include_manifest_scenarios=args.include_scenario_queries,
            scenario_query_limit=args.scenario_query_limit,
        )
    elif args.skip_diagnostic_queries:
        query_cases = tuple(case for case in WSTG_QUERY_CASES if case.blocking)
    else:
        query_cases = WSTG_QUERY_CASES

    result = run_smoke_test(
        client=client,
        graphml_path=args.graphml_path,
        upload_paths=upload_paths,
        reset_store=args.reset_store,
        wait_documents=args.wait_documents,
            normalize_types=args.normalize_types,
            delete_noise_entities=not args.keep_noise_entities,
            run_graph=not args.skip_graph,
        run_queries=not args.skip_queries,
        query_cases=query_cases,
        blocking_queries_only=args.blocking_queries_only,
        timeout_seconds=args.timeout,
        poll_seconds=args.poll,
    )
    print(json.dumps(_main_payload(result), indent=2, ensure_ascii=False, sort_keys=True))
    if args.fail_on_issues and not result.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
