"""LightRAG methodology retrieval contracts and helpers."""

import importlib

from agent.lightrag.types import (
    AuthenticationState,
    CandidateApplicability,
    CandidateRelevance,
    ConfidenceLevel,
    EntityRef,
    EntityType,
    EvidenceRef,
    ExpectedEffect,
    FaultContext,
    KnowledgeQuery,
    MethodologyBundle,
    MethodologyCandidate,
    QueryConstraints,
    QueryPattern,
    RelationPathStep,
    RelationType,
    RetrievalMode,
    RetrievalOptions,
    SourceTier,
    SourceChunk,
    TechniqueRef,
)

__all__ = [
    "AuthenticationState",
    "CandidateApplicability",
    "CandidateRelevance",
    "ConfidenceLevel",
    "EntityRef",
    "EntityType",
    "EvidenceRef",
    "ExpectedEffect",
    "FaultContext",
    "GraphAuditReport",
    "GraphEntity",
    "GraphRelation",
    "EntityTypeUpdate",
    "EntityTypeUpdateResult",
    "GraphGateResult",
    "CorpusQAIssue",
    "KnowledgeQuery",
    "LightRAGHttpClient",
    "MethodologyBundle",
    "MethodologyCandidate",
    "PreprocessResult",
    "WSTGCorpusQAResult",
    "QueryConstraints",
    "QueryPattern",
    "RelationPathStep",
    "RelationType",
    "RetrievalMode",
    "RetrievalOptions",
    "RoutedMethodologyRetriever",
    "SourceChunk",
    "SourceTier",
    "SourceFragment",
    "TechniqueRef",
    "QueryCase",
    "QueryEvaluation",
    "StagedBatchResult",
    "StagedRunResult",
    "SmokeRunResult",
    "audit_lightrag_graph",
    "build_preprocessed_documents",
    "canonicalize_entity_type",
    "evaluate_graph_gate",
    "evaluate_query_response",
    "fetch_and_preprocess_writeups",
    "fetch_and_preprocess_wstg",
    "load_wstg_manifest_scenarios",
    "preprocess_sources_for_lightrag",
    "preprocess_writeups_for_lightrag",
    "preprocess_wstg_for_lightrag",
    "qa_wstg_preprocessed_corpus",
    "normalize_lightrag_entity_types",
    "plan_entity_type_updates",
    "run_smoke_test",
    "run_staged_wstg_ingestion",
    "run_query_cases",
    "wstg_manifest_query_cases",
    "wstg_methodology_paths",
    "wstg_query_cases_for_files",
    "wstg_required_maps_for_files",
    "wstg_staged_batches",
]


def __getattr__(name: str):
    if name == "LightRAGHttpClient":
        from agent.lightrag.client import LightRAGHttpClient

        return LightRAGHttpClient
    if name == "RoutedMethodologyRetriever":
        from agent.lightrag.retriever import RoutedMethodologyRetriever

        return RoutedMethodologyRetriever
    if name in {
        "PreprocessResult",
        "CorpusQAIssue",
        "SourceFragment",
        "WSTGCorpusQAResult",
        "build_preprocessed_documents",
        "preprocess_sources_for_lightrag",
        "preprocess_writeups_for_lightrag",
        "preprocess_wstg_for_lightrag",
        "qa_wstg_preprocessed_corpus",
    }:
        preprocess = importlib.import_module("agent.lightrag.preprocess")

        return getattr(preprocess, name)
    if name == "fetch_and_preprocess_wstg":
        wstg_fetch = importlib.import_module("agent.lightrag.wstg_fetch")

        return wstg_fetch.fetch_and_preprocess_wstg
    if name == "fetch_and_preprocess_writeups":
        writeup_fetch = importlib.import_module("agent.lightrag.writeup_fetch")

        return writeup_fetch.fetch_and_preprocess_writeups
    if name in {
        "GraphAuditReport",
        "GraphEntity",
        "GraphRelation",
        "EntityTypeUpdate",
        "EntityTypeUpdateResult",
        "audit_lightrag_graph",
        "canonicalize_entity_type",
        "normalize_lightrag_entity_types",
        "plan_entity_type_updates",
    }:
        graph_audit = importlib.import_module("agent.lightrag.graph_audit")

        return getattr(graph_audit, name)
    if name in {
        "GraphGateResult",
        "QueryCase",
        "QueryEvaluation",
        "StagedBatchResult",
        "StagedRunResult",
        "SmokeRunResult",
        "evaluate_graph_gate",
        "evaluate_query_response",
        "load_wstg_manifest_scenarios",
        "run_query_cases",
        "run_smoke_test",
        "run_staged_wstg_ingestion",
        "wstg_manifest_query_cases",
        "wstg_methodology_paths",
        "wstg_query_cases_for_files",
        "wstg_required_maps_for_files",
        "wstg_staged_batches",
    }:
        smoke = importlib.import_module("agent.lightrag.smoke")

        return getattr(smoke, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
