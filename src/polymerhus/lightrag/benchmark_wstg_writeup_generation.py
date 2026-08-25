from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from polymerhus.lightrag.benchmark_ontology_queries import (
    extract_context_payload,
    extract_response_text,
)
from polymerhus.lightrag.client import LightRAGHttpClient
from polymerhus.lightrag.formatter import (
    FORMATTER_SYSTEM_PROMPT,
    _formatter_human_prompt,
    format_methodology_context,
    normalize_source_chunks,
)
from polymerhus.lightrag.types import (
    CompactMethodologyBundle,
    FaultContext,
    KnowledgeQuery,
    RetrievalOptions,
    SourceTier,
)


DEFAULT_OUTPUT_DIR = Path("data/lightrag/benchmarks")
DEFAULT_OUTPUT_NAME = "wstg_writeup_generation_benchmark.json"
DEFAULT_BASE_URL = "http://127.0.0.1:9621"
DEFAULT_WRITEUP_URL = "http://127.0.0.1:9622"
REQUIRED_OUTPUT_SECTIONS = (
    "Executed Query",
    "Parameters Used",
    "Context Retrieved from LightRAG",
    "Complete Input Passed to LLM (Final Prompt)",
    "Output Returned by LLM",
)


@dataclass(frozen=True)
class ConstantLightRAGParameters:
    mode: str = "mix"
    top_k: int = 20
    chunk_size: int = 1200
    chunk_top_k: int = 10
    max_total_tokens: int = 20000
    max_entity_tokens: int = 12000
    max_relation_tokens: int = 12000
    only_need_context: bool = True
    include_references: bool = True
    include_chunk_content: bool = True
    stream: bool = False

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    def to_query_extra(self) -> dict[str, Any]:
        return {
            "top_k": self.top_k,
            "chunk_top_k": self.chunk_top_k,
            "max_total_tokens": self.max_total_tokens,
            "max_entity_tokens": self.max_entity_tokens,
            "max_relation_tokens": self.max_relation_tokens,
            "only_need_context": self.only_need_context,
            "stream": self.stream,
        }

    def to_query_payload(self, query: str) -> dict[str, Any]:
        return {
            "query": query,
            "mode": self.mode,
            "include_references": self.include_references,
            "include_chunk_content": self.include_chunk_content,
            **self.to_query_extra(),
        }


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    source_names: tuple[str, ...]
    source_tier: SourceTier


@dataclass(frozen=True)
class EvaluationUseCase:
    use_case_id: str
    title: str
    question: str
    vulnerability_hypothesis: str
    observed_conditions: tuple[str, ...]
    defenses_present: tuple[str, ...]
    taxonomy_tags: tuple[str, ...]
    ontology_constraints: Mapping[str, Sequence[str]]

    def to_knowledge_query(
        self,
        parameters: ConstantLightRAGParameters,
    ) -> KnowledgeQuery:
        ontology_json = json.dumps(
            self.ontology_constraints,
            indent=2,
            sort_keys=True,
        )
        objective = (
            "Retrieve evidence-grounded testing methodology from the selected "
            "LightRAG methodology corpus.\n\n"
            f"Use case: {self.title}\n"
            f"Question: {self.question}\n\n"
            "Constrain retrieval and generation to these ontology roles:\n"
            "- Target / TechnologyStack / PreconditionEnvironment\n"
            "- VulnerabilityClass / Fault\n"
            "- AttackTechnique\n"
            "- PayloadPattern\n"
            "- ObservableSignal\n"
            "- TestingStrategy / Mitigation\n\n"
            f"Ontology constraints:\n{ontology_json}\n\n"
            "Return compact, evidence-backed methodology candidates. Do not "
            "produce free-form prose or procedural exploit walkthroughs."
        )
        return KnowledgeQuery(
            query_id=self.use_case_id,
            pattern="target_state",
            objective=objective,
            symptom=self.question,
            taxonomy_tags=list(self.taxonomy_tags),
            fault_context=FaultContext(
                vulnerability_hypothesis=self.vulnerability_hypothesis,
                observed_conditions=list(self.observed_conditions),
                defenses_present=list(self.defenses_present),
            ),
            retrieval=RetrievalOptions(
                mode=parameters.mode,  # type: ignore[arg-type]
                max_candidates=parameters.top_k,
            ),
        )


DEFAULT_LIGHTRAG_PARAMETERS = ConstantLightRAGParameters()


def default_datasets() -> tuple[DatasetSpec, ...]:
    return (
        DatasetSpec(
            dataset_id="wstg",
            source_names=("wstg",),
            source_tier="validated_base",
        ),
        DatasetSpec(
            dataset_id="wstg+writeup",
            source_names=("wstg", "writeups"),
            source_tier="review_overlay",
        ),
    )


def default_use_cases() -> tuple[EvaluationUseCase, ...]:
    return (
        EvaluationUseCase(
            use_case_id="broken-access-control",
            title="Broken Access Control (Horizontal & Vertical Escalation)",
            question=(
                "What evidence-backed methodology validates horizontal and vertical "
                "broken access control across authenticated roles, tenants, and "
                "privilege boundaries?"
            ),
            vulnerability_hypothesis=(
                "Authorization checks can be bypassed across horizontal or vertical "
                "privilege boundaries."
            ),
            observed_conditions=(
                "authenticated low-privilege and high-privilege roles exist",
                "role or tenant scoped resources are accessible through requests",
                "server-side authorization decisions must be validated",
            ),
            defenses_present=(
                "role-based access control",
                "session cookies or bearer tokens",
            ),
            taxonomy_tags=(
                "broken-access-control",
                "horizontal-escalation",
                "vertical-escalation",
            ),
            ontology_constraints={
                "Target": [
                    "authenticated web application",
                    "role and tenant authorization boundary",
                ],
                "VulnerabilityClass/Fault": [
                    "Broken Access Control",
                    "Authorization Schema Bypass",
                ],
                "AttackTechnique": [
                    "authorization bypass validation",
                    "object or role boundary manipulation",
                ],
                "PayloadPattern": [
                    "role parameter tampering",
                    "cross-user resource identifier substitution",
                ],
                "ObservableSignal": [
                    "cross-role access succeeds",
                    "unauthorized resource response matches authorized response",
                ],
                "TestingStrategy/Mitigation": [
                    "negative authorization controls",
                    "server-side policy enforcement validation",
                ],
            },
        ),
        EvaluationUseCase(
            use_case_id="oauth2-oidc-flows",
            title=(
                "OAuth2 / OIDC Flaws (Authorization Code Flow, State Validation, "
                "Token Handling)"
            ),
            question=(
                "What methodology validates OAuth2/OIDC authorization code flow "
                "security, state validation, redirect URI enforcement, token "
                "handling, and session binding?"
            ),
            vulnerability_hypothesis=(
                "OAuth2/OIDC authorization flow validation is incomplete, enabling "
                "token or authorization-code misuse."
            ),
            observed_conditions=(
                "authorization code flow is used",
                "state, redirect_uri, scope, authorization code, and tokens are present",
                "session binding and token storage must be validated",
            ),
            defenses_present=(
                "authorization server controls",
                "OIDC token validation",
                "redirect URI allow-listing",
            ),
            taxonomy_tags=("oauth2", "oidc", "authorization-code", "token-handling"),
            ontology_constraints={
                "Target": ["OAuth2/OIDC authorization server", "authorization code flow"],
                "VulnerabilityClass/Fault": [
                    "OAuth Authorization Server Weakness",
                    "Broken Access Control",
                ],
                "AttackTechnique": [
                    "OAuth parameter validation",
                    "state and redirect_uri tamper validation",
                ],
                "PayloadPattern": [
                    "state parameter tampering",
                    "redirect_uri substitution",
                    "authorization code replay",
                ],
                "ObservableSignal": [
                    "unexpected token issuance",
                    "state mismatch accepted",
                    "redirect URI bypass accepted",
                ],
                "TestingStrategy/Mitigation": [
                    "strict redirect URI validation",
                    "state binding validation",
                    "token lifetime and storage checks",
                ],
            },
        ),
        EvaluationUseCase(
            use_case_id="session-management-fixation",
            title=(
                "Session Management & Fixation (Session Hijacking, Cookie Security, "
                "Concurrency)"
            ),
            question=(
                "What methodology validates session fixation, hijacking resistance, "
                "cookie security attributes, logout invalidation, and concurrent "
                "session handling?"
            ),
            vulnerability_hypothesis=(
                "Session identifiers or cookies are not rotated, protected, or "
                "invalidated consistently across authentication lifecycle events."
            ),
            observed_conditions=(
                "session cookies maintain authenticated state",
                "login, logout, and concurrent sessions are observable",
                "cookie attributes and session identifier rotation must be validated",
            ),
            defenses_present=(
                "session cookies",
                "secure cookie attributes",
                "logout functionality",
            ),
            taxonomy_tags=("session-management", "session-fixation", "cookie-security"),
            ontology_constraints={
                "Target": ["session-managed web application", "HTTP cookies"],
                "VulnerabilityClass/Fault": [
                    "Session Fixation",
                    "Broken Session Invalidation",
                    "Exposed Session Variables",
                ],
                "AttackTechnique": [
                    "session identifier reuse validation",
                    "cookie attribute validation",
                    "concurrent session testing",
                ],
                "PayloadPattern": [
                    "fixed session identifier",
                    "tampered cookie attributes",
                    "parallel authenticated sessions",
                ],
                "ObservableSignal": [
                    "session identifier unchanged after login",
                    "token remains valid after logout",
                    "cookie lacks secure attributes",
                ],
                "TestingStrategy/Mitigation": [
                    "rotate session identifiers after authentication",
                    "invalidate server-side sessions on logout",
                    "enforce Secure, HttpOnly, SameSite attributes",
                ],
            },
        ),
        EvaluationUseCase(
            use_case_id="bola-idor-apis",
            title="Broken Object Level Authorization (BOLA / IDOR in APIs)",
            question=(
                "What methodology validates BOLA and IDOR weaknesses in APIs by "
                "testing object identifiers, tenant boundaries, and negative "
                "authorization controls?"
            ),
            vulnerability_hypothesis=(
                "API object-level authorization can be bypassed by substituting "
                "resource identifiers across users or tenants."
            ),
            observed_conditions=(
                "API endpoints expose object identifiers",
                "multiple authenticated users or tenants exist",
                "authorization decisions must be enforced per object",
            ),
            defenses_present=(
                "API authentication",
                "server-side object authorization policy",
            ),
            taxonomy_tags=("api", "bola", "idor", "object-level-authorization"),
            ontology_constraints={
                "Target": ["REST or GraphQL API", "object identifier authorization boundary"],
                "VulnerabilityClass/Fault": [
                    "Broken Object Level Authorization",
                    "Insecure Direct Object Reference",
                ],
                "AttackTechnique": [
                    "object ID tampering",
                    "cross-tenant resource access validation",
                ],
                "PayloadPattern": [
                    "sequential object ID substitution",
                    "UUID or tenant identifier substitution",
                ],
                "ObservableSignal": [
                    "adjacent account object accessible",
                    "cross-tenant response exposes data",
                ],
                "TestingStrategy/Mitigation": [
                    "negative object authorization tests",
                    "per-object server-side policy checks",
                ],
            },
        ),
    )


def build_final_llm_payload(
    query: KnowledgeQuery,
    *,
    raw_lightrag_context: str,
    source_tier: SourceTier,
    source_chunks: Sequence[Any],
) -> dict[str, Any]:
    normalized_chunks = normalize_source_chunks(source_chunks)
    human_prompt = _formatter_human_prompt(
        query,
        raw_lightrag_context=raw_lightrag_context,
        source_tier=source_tier,
        source_chunks=normalized_chunks,
    )
    return {
        "system_prompt": FORMATTER_SYSTEM_PROMPT,
        "human_prompt": human_prompt,
        "messages": [
            {"role": "system", "content": FORMATTER_SYSTEM_PROMPT},
            {"role": "user", "content": human_prompt},
        ],
        "ontological_constraints": {
            "query_id": query.query_id,
            "pattern": query.pattern,
            "taxonomy_tags": query.taxonomy_tags,
            "fault_context": query.fault_context.model_dump(mode="json"),
            "source_tier": source_tier,
        },
        "required_output_schema": CompactMethodologyBundle.model_json_schema(),
        "structured_output_binding": {
            "schema": "CompactMethodologyBundle",
            "method": "function_calling",
        },
    }


def run_evaluation(
    *,
    clients: Mapping[str, Any] | None = None,
    output_path: str | Path | None = None,
    llm: Any | None = None,
    use_cases: Sequence[EvaluationUseCase] | None = None,
    datasets: Sequence[DatasetSpec] | None = None,
    parameters: ConstantLightRAGParameters = DEFAULT_LIGHTRAG_PARAMETERS,
    generated_at: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    writeup_url: str = DEFAULT_WRITEUP_URL,
    api_key: str | None = None,
    timeout: float = 180.0,
) -> Path:
    generated_at = generated_at or _timestamp()
    output = Path(output_path) if output_path else DEFAULT_OUTPUT_DIR / DEFAULT_OUTPUT_NAME
    output.parent.mkdir(parents=True, exist_ok=True)
    active_clients = dict(
        clients
        or {
            "wstg": LightRAGHttpClient(base_url, api_key=api_key, timeout=timeout),
            "writeups": LightRAGHttpClient(writeup_url, api_key=api_key, timeout=timeout),
        }
    )

    executions = []
    for use_case in use_cases or default_use_cases():
        query = use_case.to_knowledge_query(parameters)
        executed_query = query.to_retrieval_prompt()
        for dataset in datasets or default_datasets():
            executions.append(
                _run_single_execution(
                    use_case=use_case,
                    dataset=dataset,
                    query=query,
                    executed_query=executed_query,
                    parameters=parameters,
                    clients=active_clients,
                    llm=llm,
                )
            )

    payload = {
        "schema_version": 1,
        "generated_at": generated_at,
        "benchmark": "wstg_writeup_retrieval_generation",
        "parameter_selection_rationale": (
            "Constant mix/top_k=20 profile selected from prior ontology benchmark "
            "and tuning notes: top_k=20 was sufficient while larger top_k spent "
            "budget poorly; mix preserves graph entities, relationships, and text "
            "chunks for ontology-constrained generation."
        ),
        "summary": _summary(executions, parameters),
        "executions": executions,
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output


def _run_single_execution(
    *,
    use_case: EvaluationUseCase,
    dataset: DatasetSpec,
    query: KnowledgeQuery,
    executed_query: str,
    parameters: ConstantLightRAGParameters,
    clients: Mapping[str, Any],
    llm: Any | None,
) -> dict[str, Any]:
    source_records = []
    raw_context_parts = []
    all_source_chunks = []
    errors = []
    for source_name in dataset.source_names:
        client = clients[source_name]
        request_payload = parameters.to_query_payload(executed_query)
        kwargs = {
            "mode": parameters.mode,
            "include_references": parameters.include_references,
            "include_chunk_content": parameters.include_chunk_content,
            "extra": parameters.to_query_extra(),
        }
        try:
            raw_response = client.query(executed_query, **kwargs)
        except Exception as exc:
            raw_response = None
            raw_context = ""
            context_payload = _empty_context_payload()
            errors.append(
                {
                    "source": source_name,
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        else:
            raw_context = extract_response_text(raw_response)
            context_payload = extract_context_payload(raw_response)
            raw_context_parts.append(f"## SOURCE: {source_name}\n{raw_context}")
            all_source_chunks.extend(context_payload["source_chunks"])

        source_records.append(
            {
                "source": source_name,
                "request_payload": request_payload,
                "kwargs": kwargs,
                "raw_response": raw_response,
                "raw_lightrag_context": raw_context,
                "Entities": context_payload["retrieved_entities_by_type"],
                "Relationships": context_payload["extracted_relations"],
                "Text Chunks": context_payload["source_chunks"],
                "error": errors[-1] if errors and errors[-1]["source"] == source_name else None,
            }
        )

    raw_lightrag_context = "\n\n".join(raw_context_parts)
    context_payload = extract_context_payload(
        {
            "response": raw_lightrag_context,
            "references": all_source_chunks,
        }
    )
    final_llm_payload = build_final_llm_payload(
        query,
        raw_lightrag_context=raw_lightrag_context,
        source_tier=dataset.source_tier,
        source_chunks=all_source_chunks,
    )
    bundle = format_methodology_context(
        query,
        raw_lightrag_context=raw_lightrag_context,
        source_tier=dataset.source_tier,
        source_chunks=all_source_chunks,
        llm=llm,
    )
    output = bundle.model_dump(mode="json")

    return {
        "Executed Query": {
            "use_case_id": use_case.use_case_id,
            "use_case_title": use_case.title,
            "dataset": dataset.dataset_id,
            "source_names": list(dataset.source_names),
            "query_text_sent_to_lightrag": executed_query,
        },
        "Parameters Used": {
            "LightRAG": parameters.to_record(),
            "dataset": {
                "dataset_id": dataset.dataset_id,
                "source_names": list(dataset.source_names),
                "source_tier": dataset.source_tier,
            },
        },
        "Context Retrieved from LightRAG": {
            "Entities": context_payload["retrieved_entities_by_type"],
            "Relationships": context_payload["extracted_relations"],
            "Text Chunks": all_source_chunks,
            "raw_lightrag_context": raw_lightrag_context,
            "raw_lightrag_context_bytes": len(raw_lightrag_context.encode("utf-8")),
            "source_responses": source_records,
        },
        "Complete Input Passed to LLM (Final Prompt)": final_llm_payload,
        "Output Returned by LLM": output,
    }


def _empty_context_payload() -> dict[str, Any]:
    return {
        "retrieved_entities_by_type": {},
        "extracted_relations": [],
        "source_chunks": [],
    }


def _summary(
    executions: Sequence[Mapping[str, Any]],
    parameters: ConstantLightRAGParameters,
) -> dict[str, Any]:
    output_errors = [
        _execution_id(execution)
        for execution in executions
        if _execution_error_count(execution)
    ]
    return {
        "execution_count": len(executions),
        "expected_execution_count": len(default_use_cases()) * len(default_datasets()),
        "constant_parameters_enforced": all(
            execution["Parameters Used"]["LightRAG"] == parameters.to_record()
            for execution in executions
        ),
        "datasets": [dataset.dataset_id for dataset in default_datasets()],
        "use_cases": [case.use_case_id for case in default_use_cases()],
        "error_count": len(output_errors),
        "executions_with_errors": output_errors,
    }


def _execution_error_count(execution: Mapping[str, Any]) -> int:
    context = execution["Context Retrieved from LightRAG"]
    source_errors = [
        source_response
        for source_response in context.get("source_responses", [])
        if source_response.get("error")
    ]
    output = execution["Output Returned by LLM"]
    formatter_error = output.get("retrieval_metadata", {}).get("formatter_error")
    return len(source_errors) + (1 if formatter_error else 0)


def _execution_id(execution: Mapping[str, Any]) -> str:
    executed = execution["Executed Query"]
    return f"{executed['use_case_id']}:{executed['dataset']}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run WSTG vs WSTG+writeup LightRAG retrieval and structured generation "
            "benchmark with constant parameters."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--writeup-url", default=DEFAULT_WRITEUP_URL)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR / DEFAULT_OUTPUT_NAME))
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero if any retrieval or formatter execution records an error.",
    )
    args = parser.parse_args(argv)

    output_path = run_evaluation(
        output_path=args.output,
        base_url=args.base_url,
        writeup_url=args.writeup_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    print(json.dumps({"output_path": str(output_path), **summary}, indent=2, sort_keys=True))
    if args.fail_on_error and summary["error_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
