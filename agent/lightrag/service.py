from __future__ import annotations

from typing import Any

from agent.lightrag.packager import package_methodology
from agent.lightrag.types import KnowledgeQuery, MethodologyBundle


def _coerce_query(query: KnowledgeQuery | dict) -> KnowledgeQuery:
    if isinstance(query, KnowledgeQuery):
        return query
    if isinstance(query, dict):
        return KnowledgeQuery(**query)
    raise TypeError("retrieve_methodology requires a KnowledgeQuery or query mapping")


def _call_retriever(retriever, query: KnowledgeQuery) -> Any:
    if hasattr(retriever, "retrieve_methodology"):
        return retriever.retrieve_methodology(query)
    if hasattr(retriever, "retrieve"):
        return retriever.retrieve(query)
    if callable(retriever):
        return retriever(query)
    raise TypeError("retriever must be callable or expose retrieve()/retrieve_methodology()")


def _save_artifact(artifact_store, run_id: str, query: KnowledgeQuery, bundle: MethodologyBundle):
    if artifact_store is None:
        from agent.app.clients import pg  # noqa: PLC0415

        artifact_store = pg
    if hasattr(artifact_store, "save_methodology_bundle"):
        return artifact_store.save_methodology_bundle(run_id, query, bundle)
    if callable(artifact_store):
        return artifact_store(run_id, query, bundle)
    raise TypeError("artifact_store must be callable or expose save_methodology_bundle()")


def retrieve_methodology(
    query: KnowledgeQuery | dict,
    *,
    run_id: str,
    retriever,
    artifact_store=None,
) -> MethodologyBundle:
    """Run the generic P0 KnowledgeQuery -> MethodologyBundle -> artifact path."""
    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be blank")
    validated_query = _coerce_query(query)
    retriever_output = _call_retriever(retriever, validated_query)
    bundle = package_methodology(validated_query, retriever_output)
    _save_artifact(artifact_store, run_id, validated_query, bundle)
    return bundle
