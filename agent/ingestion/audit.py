from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Iterator, Literal

from pydantic import BaseModel, Field

from agent.lightrag.ontology import ENTITY_TYPES


class AuditIssue(BaseModel):
    code: str
    message: str
    severity: Literal["critical", "warning"]
    evidence: dict[str, Any] = Field(default_factory=dict)


class AuditReport(BaseModel):
    job_id: str
    source_key: str
    critical_issues: list[AuditIssue] = Field(default_factory=list)
    warnings: list[AuditIssue] = Field(default_factory=list)
    merge_candidates: list[dict[str, Any]] = Field(default_factory=list)
    checked_at: str


def has_critical_issues(report: AuditReport) -> bool:
    return len(report.critical_issues) > 0


def build_storage_parse_error_report(
    *,
    job_id: str,
    source_key: str,
    error: Exception,
) -> AuditReport:
    """Create a complete audit report for a StorageParseError."""
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return AuditReport(
        job_id=job_id,
        source_key=source_key,
        critical_issues=[
            AuditIssue(
                code="STORAGE_PARSE_ERROR",
                message=f"Failed to parse LightRAG storage snapshot: {error}",
                severity="critical",
                evidence={
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
        ],
        warnings=[],
        merge_candidates=[],
        checked_at=checked_at,
    )


class LightRAGStorageError(RuntimeError):
    pass


class StorageParseError(LightRAGStorageError):
    pass


class GraphNode(BaseModel):
    id: str
    entity_type: str = ""
    source_id: str = ""
    file_path: str = ""
    description: str = ""
    keywords: str = ""


class GraphEdge(BaseModel):
    source: str
    target: str
    source_id: str = ""
    file_path: str = ""
    description: str = ""
    keywords: str = ""


class GraphMLGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class LightRAGStorageSnapshot(BaseModel):
    kv_store_doc_status: dict[str, Any] = Field(default_factory=dict)
    kv_store_full_docs: dict[str, Any] = Field(default_factory=dict)
    kv_store_text_chunks: dict[str, Any] = Field(default_factory=dict)
    kv_store_full_entities: dict[str, Any] = Field(default_factory=dict)
    kv_store_full_relations: dict[str, Any] = Field(default_factory=dict)
    kv_store_entity_chunks: dict[str, Any] = Field(default_factory=dict)
    kv_store_relation_chunks: dict[str, Any] = Field(default_factory=dict)
    vdb_chunks: dict[str, Any] = Field(default_factory=dict)
    vdb_entities: dict[str, Any] = Field(default_factory=dict)
    vdb_relationships: dict[str, Any] = Field(default_factory=dict)
    graph: GraphMLGraph = Field(default_factory=GraphMLGraph)
    missing_files: list[str] = Field(default_factory=list)


class LightRAGStorageReader:
    _JSON_FILES = (
        "kv_store_doc_status.json",
        "kv_store_full_docs.json",
        "kv_store_text_chunks.json",
        "kv_store_full_entities.json",
        "kv_store_full_relations.json",
        "kv_store_entity_chunks.json",
        "kv_store_relation_chunks.json",
    )
    _VDB_FILES = (
        "vdb_chunks.json",
        "vdb_entities.json",
        "vdb_relationships.json",
    )

    def __init__(self, storage_root: Path):
        self.storage_root = Path(storage_root)

    def snapshot(self) -> LightRAGStorageSnapshot:
        missing: list[str] = []

        json_data = {}
        for name in self._JSON_FILES:
            json_data[name] = self._load_json(name, missing)

        vdb_data = {}
        for name in self._VDB_FILES:
            vdb_data[name] = self._load_json(name, missing)

        graph = self._load_graph(missing)

        return LightRAGStorageSnapshot(
            kv_store_doc_status=json_data["kv_store_doc_status.json"],
            kv_store_full_docs=json_data["kv_store_full_docs.json"],
            kv_store_text_chunks=json_data["kv_store_text_chunks.json"],
            kv_store_full_entities=json_data["kv_store_full_entities.json"],
            kv_store_full_relations=json_data["kv_store_full_relations.json"],
            kv_store_entity_chunks=json_data["kv_store_entity_chunks.json"],
            kv_store_relation_chunks=json_data["kv_store_relation_chunks.json"],
            vdb_chunks=vdb_data["vdb_chunks.json"],
            vdb_entities=vdb_data["vdb_entities.json"],
            vdb_relationships=vdb_data["vdb_relationships.json"],
            graph=graph,
            missing_files=missing,
        )

    def _load_json(self, name: str, missing: list[str]) -> Any:
        path = self.storage_root / name
        if not path.exists():
            missing.append(name)
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageParseError(f"Invalid JSON in {name}: {exc}") from exc

    def _load_graph(self, missing: list[str]) -> GraphMLGraph:
        path = self.storage_root / "graph_chunk_entity_relation.graphml"
        if not path.exists():
            missing.append(path.name)
            return GraphMLGraph()
        try:
            tree = ET.parse(path)
        except (ET.ParseError, OSError) as exc:
            raise StorageParseError(f"Invalid GraphML {path.name}: {exc}") from exc
        root = tree.getroot()
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]
        keys = {}
        for key in root.findall("key"):
            key_id = key.get("id")
            attr_name = key.get("attr.name")
            if key_id and attr_name:
                keys[key_id] = attr_name
        graph_elem = root.find("graph")
        nodes = []
        edges = []
        if graph_elem is not None:
            for node in graph_elem.findall("node"):
                node_id = node.get("id")
                attrs = self._extract_attrs(node, keys)
                nodes.append(
                    GraphNode(
                        id=node_id,
                        entity_type=attrs.get("entity_type", ""),
                        source_id=attrs.get("source_id", ""),
                        file_path=attrs.get("file_path", ""),
                        description=attrs.get("description", ""),
                        keywords=attrs.get("keywords", ""),
                    )
                )
            for edge in graph_elem.findall("edge"):
                source = edge.get("source")
                target = edge.get("target")
                attrs = self._extract_attrs(edge, keys)
                edges.append(
                    GraphEdge(
                        source=source,
                        target=target,
                        source_id=attrs.get("source_id", ""),
                        file_path=attrs.get("file_path", ""),
                        description=attrs.get("description", ""),
                        keywords=attrs.get("keywords", ""),
                    )
                )
        return GraphMLGraph(nodes=nodes, edges=edges)

    @staticmethod
    def _extract_attrs(elem: ET.Element, keys: dict[str, str]) -> dict[str, str]:
        attrs = {}
        for data in elem.findall("data"):
            key = data.get("key")
            value = data.text or ""
            attr_name = keys.get(key)
            if attr_name:
                attrs[attr_name] = value
        return attrs


_SUCCESSFUL_TERMINAL_STATUSES = frozenset({"processed", "completed", "done"})

PREVIOUSLY_AGREED_ENTITY_TYPES = frozenset(
    {
        "PreconditionEnvironment",
        "TechnologyStack",
        "DefensiveControl",
        "VulnerabilityClass",
        "AttackGoal",
        "AttackerCapability",
        "AttackTechnique",
        "PayloadPattern",
        "Artifact",
    }
)


def _chunk_full_doc_id(chunk_data: Any) -> str | None:
    if isinstance(chunk_data, dict):
        return chunk_data.get("full_doc_id") or chunk_data.get("doc_id")
    return None


def _vdb_chunk_doc_id(chunk_data: Any) -> str | None:
    """Return the document id for a vector chunk.

    Priority:
      1. top-level ``full_doc_id`` / ``doc_id`` (real LightRAG schema)
      2. ``metadata.full_doc_id`` / ``metadata.doc_id`` (legacy fixtures)
    """
    if not isinstance(chunk_data, dict):
        return None
    for key in ("full_doc_id", "doc_id"):
        val = chunk_data.get(key)
        if val:
            return str(val)
    metadata = chunk_data.get("metadata")
    if isinstance(metadata, dict):
        for key in ("full_doc_id", "doc_id"):
            val = metadata.get(key)
            if val:
                return str(val)
    return None


def _iter_vdb_chunks(vdb_data: Any) -> Iterator[tuple[str | None, Any]]:
    """Yield ``(record_id, record)`` from either supported schema.

    Real LightRAG container: ``{"embedding_dim": ..., "matrix": ..., "data": [...]}``
    where each record in ``data`` carries ``__id__`` (or ``id``) and
    top-level ``full_doc_id``.

    Legacy simple schema: ``{record_id: {...}}``.
    """
    if not isinstance(vdb_data, dict):
        return
    data = vdb_data.get("data")
    if isinstance(data, list):
        for record in data:
            if isinstance(record, dict):
                rec_id = record.get("__id__") or record.get("id")
                yield rec_id, record
        return
    for rec_id, record in vdb_data.items():
        yield rec_id, record


def _extract_chunk_count(record: Any) -> int | None:
    if not isinstance(record, dict):
        return None
    for key in ("chunks_count", "chunk_count", "chunks", "num_chunks", "total_chunks"):
        val = record.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                return None
    return None


def _norm_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _norm_identifier(value: str) -> str:
    return " ".join(value.strip().split())


def _norm_entity_id(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _entity_identity(node: GraphNode) -> tuple[str, ...]:
    return (
        _norm_entity_id(node.id),
        _norm_text(node.entity_type),
        _norm_identifier(node.source_id),
        _norm_identifier(node.file_path),
        _norm_text(node.description),
        _norm_text(node.keywords),
    )


def _relation_identity(edge: GraphEdge) -> tuple[str, ...]:
    return (
        _norm_identifier(edge.source),
        _norm_identifier(edge.target),
        _norm_identifier(edge.source_id),
        _norm_text(edge.description),
        _norm_text(edge.keywords),
    )


def run_post_ingestion_audit(
    *,
    job_id: str,
    source_key: str,
    lightrag_document_id: str | None,
    storage_snapshot: LightRAGStorageSnapshot,
    allowed_entity_types: Collection[str],
) -> AuditReport:
    """Run the critical non‑destructive post‑ingestion audit checks."""
    issues: list[AuditIssue] = []
    warnings: list[AuditIssue] = []
    merge_candidates: list[dict[str, Any]] = []

    def add_issue(code: str, message: str, evidence: dict[str, Any]) -> None:
        issues.append(
            AuditIssue(
                code=code,
                message=message,
                severity="critical",
                evidence=evidence,
            )
        )

    # Missing storage file warnings (always relevant)
    for fname in storage_snapshot.missing_files:
        warnings.append(
            AuditIssue(
                code="MISSING_STORAGE_FILE",
                message=f"Missing storage file: {fname}",
                severity="warning",
                evidence={"filename": fname},
            )
        )

    # Ontology divergence warning (independent of any audited document)
    current_types = set(ENTITY_TYPES)
    previous_types = set(PREVIOUSLY_AGREED_ENTITY_TYPES)
    added_types = sorted(current_types - previous_types)
    removed_types = sorted(previous_types - current_types)
    if added_types or removed_types:
        warnings.append(
            AuditIssue(
                code="ONTOLOGY_DIVERGENCE",
                message="Configured LightRAG ontology diverges from the previously agreed ontology.",
                severity="warning",
                evidence={
                    "current_ontology_types": sorted(current_types),
                    "previously_agreed_types": sorted(previous_types),
                    "added": added_types,
                    "removed": removed_types,
                },
            )
        )

    document_id = (lightrag_document_id or "").strip()

    if not document_id:
        add_issue(
            "LIGHTRAG_DOCUMENT_ID_MISSING",
            "Missing LightRAG document id for audit.",
            {"lightrag_document_id": lightrag_document_id},
        )

    if document_id:
        status_record = storage_snapshot.kv_store_doc_status.get(document_id)
        status: Any = None
        if status_record is not None:
            if isinstance(status_record, dict):
                status = status_record.get("status")
            else:
                status = status_record

        if status_record is None:
            add_issue(
                "DOCUMENT_STATUS_MISSING",
                f"No document status entry for {document_id!r}.",
                {"document_id": document_id},
            )
        else:
            status_str = str(status or "").strip().lower()
            if status_str not in _SUCCESSFUL_TERMINAL_STATUSES:
                add_issue(
                    "DOCUMENT_STATUS_FAILED",
                    f"Document {document_id!r} is not in a successful terminal state (status={status!r}).",
                    {"document_id": document_id, "status": status},
                )

            # Warning when a successful terminal status explicitly reports zero chunks
            chunk_count = _extract_chunk_count(status_record)
            if (
                status_str in _SUCCESSFUL_TERMINAL_STATUSES
                and chunk_count is not None
                and chunk_count == 0
            ):
                warnings.append(
                    AuditIssue(
                        code="DOCUMENT_EXPLICIT_ZERO_CHUNKS",
                        message=f"Successful document {document_id!r} explicitly reports zero chunks.",
                        severity="warning",
                        evidence={"document_id": document_id, "chunk_count": 0},
                    )
                )

        # Chunk linkage (only when the document actually exists and is successful)
        linked_chunk_ids = sorted(
            chunk_id
            for chunk_id, chunk_data in storage_snapshot.kv_store_text_chunks.items()
            if _chunk_full_doc_id(chunk_data) == document_id
        )

        if (
            status_record is not None
            and str(status or "").strip().lower() in _SUCCESSFUL_TERMINAL_STATUSES
            and not linked_chunk_ids
        ):
            add_issue(
                "DOCUMENT_HAS_NO_CHUNKS",
                f"Successful document {document_id!r} has no linked text chunks.",
                {"document_id": document_id},
            )

        # Build an ID index of the vector chunks without mutating the snapshot
        vdb_chunk_ids = {
            chunk_id
            for chunk_id, _ in _iter_vdb_chunks(storage_snapshot.vdb_chunks)
            if chunk_id is not None
        }

        # Missing vector chunks for chunks that belong to the audited document
        for chunk_id in linked_chunk_ids:
            if chunk_id not in vdb_chunk_ids:
                add_issue(
                    "VECTOR_CHUNK_MISSING",
                    f"Text chunk {chunk_id!r} of document {document_id!r} is missing from vdb_chunks.",
                    {"document_id": document_id, "chunk_id": chunk_id},
                )

        # Vector chunks that are tagged with the audited document but have no KV text chunk
        for chunk_id, chunk_data in _iter_vdb_chunks(storage_snapshot.vdb_chunks):
            if (
                chunk_id is not None
                and _vdb_chunk_doc_id(chunk_data) == document_id
                and chunk_id not in storage_snapshot.kv_store_text_chunks
            ):
                add_issue(
                    "KV_VECTOR_CHUNK_MISMATCH",
                    f"Vector chunk {chunk_id!r} for document {document_id!r} has no corresponding KV text chunk.",
                    {"document_id": document_id, "chunk_id": chunk_id},
                )

    # Graph checks (independent of the audited document id)
    allowed_set = set(allowed_entity_types)

    for node in storage_snapshot.graph.nodes:
        entity_type = node.entity_type.strip()
        if entity_type and entity_type not in allowed_set:
            add_issue(
                "ENTITY_TYPE_NOT_ALLOWED",
                f"Graph node {node.id!r} uses disallowed entity type {entity_type!r}.",
                {
                    "node_id": node.id,
                    "entity_type": entity_type,
                    "allowed_entity_types": sorted(allowed_set),
                },
            )

    node_ids = {node.id for node in storage_snapshot.graph.nodes}

    for edge in storage_snapshot.graph.edges:
        edge_label = f"{edge.source}->{edge.target}"
        if edge.source not in node_ids:
            add_issue(
                "ORPHAN_RELATION_ENDPOINT",
                f"Graph edge {edge_label!r} has source node not present in the graph.",
                {"edge": edge_label, "endpoint": "source", "node_id": edge.source},
            )
        if edge.target not in node_ids:
            add_issue(
                "ORPHAN_RELATION_ENDPOINT",
                f"Graph edge {edge_label!r} has target node not present in the graph.",
                {"edge": edge_label, "endpoint": "target", "node_id": edge.target},
            )

    for node in storage_snapshot.graph.nodes:
        if node.entity_type.strip() and not node.source_id:
            add_issue(
                "GRAPH_NODE_WITHOUT_PROVENANCE",
                f"Graph entity node {node.id!r} has no source_id.",
                {"node_id": node.id, "entity_type": node.entity_type},
            )

    for edge in storage_snapshot.graph.edges:
        if not edge.source_id:
            edge_label = f"{edge.source}->{edge.target}"
            add_issue(
                "GRAPH_EDGE_WITHOUT_PROVENANCE",
                f"Graph edge {edge_label!r} has no source_id.",
                {"edge": edge_label},
            )

    # Non‑destructive merge candidates
    entity_groups: dict[tuple[str, ...], list[str]] = {}
    for node in storage_snapshot.graph.nodes:
        key = _entity_identity(node)
        entity_groups.setdefault(key, []).append(node.id)

    for key in sorted(entity_groups):
        ids = entity_groups[key]
        if len(ids) > 1:
            merge_candidates.append(
                {
                    "candidate_type": "entity_duplicate",
                    "node_ids": sorted(ids),
                    "identity": {
                        "entity_id": key[0],
                        "entity_type": key[1],
                        "source_id": key[2],
                        "file_path": key[3],
                        "description": key[4],
                        "keywords": key[5],
                    },
                }
            )

    relation_groups: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for edge in storage_snapshot.graph.edges:
        key = _relation_identity(edge)
        relation_groups.setdefault(key, []).append(
            {"source": edge.source, "target": edge.target}
        )

    for key in sorted(relation_groups):
        edges_list = relation_groups[key]
        if len(edges_list) > 1:
            merge_candidates.append(
                {
                    "candidate_type": "relation_duplicate",
                    "edges": sorted(edges_list, key=lambda e: (e["source"], e["target"])),
                    "identity": {
                        "source": key[0],
                        "target": key[1],
                        "source_id": key[2],
                        "description": key[3],
                        "keywords": key[4],
                    },
                }
            )

    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return AuditReport(
        job_id=job_id,
        source_key=source_key,
        critical_issues=issues,
        warnings=warnings,
        merge_candidates=merge_candidates,
        checked_at=checked_at,
    )
