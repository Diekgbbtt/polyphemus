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
    "KnowledgeQuery",
    "LightRAGHttpClient",
    "MethodologyBundle",
    "MethodologyCandidate",
    "PreprocessResult",
    "QueryConstraints",
    "QueryPattern",
    "RelationPathStep",
    "RelationType",
    "RetrievalMode",
    "RetrievalOptions",
    "SourceChunk",
    "SourceFragment",
    "TechniqueRef",
    "build_preprocessed_documents",
    "fetch_and_preprocess_wstg",
    "preprocess_sources_for_lightrag",
    "preprocess_wstg_for_lightrag",
]


def __getattr__(name: str):
    if name == "LightRAGHttpClient":
        from agent.lightrag.client import LightRAGHttpClient

        return LightRAGHttpClient
    if name in {
        "PreprocessResult",
        "SourceFragment",
        "build_preprocessed_documents",
        "preprocess_sources_for_lightrag",
        "preprocess_wstg_for_lightrag",
    }:
        preprocess = importlib.import_module("agent.lightrag.preprocess")

        return getattr(preprocess, name)
    if name == "fetch_and_preprocess_wstg":
        wstg_fetch = importlib.import_module("agent.lightrag.wstg_fetch")

        return wstg_fetch.fetch_and_preprocess_wstg
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
