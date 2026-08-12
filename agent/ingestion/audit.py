from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Collection, Literal

from pydantic import BaseModel, Field


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


def _chunk_full_doc_id(chunk_data: Any) -> str | None:
    if isinstance(chunk_data, dict):
        return chunk_data.get("full_doc_id") or chunk_data.get("doc_id")
    return None


def _vdb_chunk_doc_id(chunk_data: Any) -> str | None:
    if isinstance(chunk_data, dict):
        metadata = chunk_data.get("metadata")
        if isinstance(metadata, dict):
            return metadata.get("doc_id") or metadata.get("full_doc_id")
    return None


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

    def add_issue(code: str, message: str, evidence: dict[str, Any]) -> None:
        issues.append(
            AuditIssue(
                code=code,
                message=message,
                severity="critical",
                evidence=evidence,
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

        # Missing vector chunks for chunks that belong to the audited document
        for chunk_id in linked_chunk_ids:
            if chunk_id not in storage_snapshot.vdb_chunks:
                add_issue(
                    "VECTOR_CHUNK_MISSING",
                    f"Text chunk {chunk_id!r} of document {document_id!r} is missing from vdb_chunks.",
                    {"document_id": document_id, "chunk_id": chunk_id},
                )

        # Vector chunks that are tagged with the audited document but have no KV text chunk
        for chunk_id, chunk_data in storage_snapshot.vdb_chunks.items():
            if _vdb_chunk_doc_id(chunk_data) == document_id and chunk_id not in storage_snapshot.kv_store_text_chunks:
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

    return AuditReport(
        job_id=job_id,
        source_key=source_key,
        critical_issues=issues,
        warnings=[],
        merge_candidates=[],
        checked_at="",
    )
