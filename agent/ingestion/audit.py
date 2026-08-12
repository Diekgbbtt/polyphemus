from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Literal

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
    vdb_chunks: list[Any] = Field(default_factory=list)
    vdb_entities: list[Any] = Field(default_factory=list)
    vdb_relationships: list[Any] = Field(default_factory=list)
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
            return {} if name in self._JSON_FILES else []
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
