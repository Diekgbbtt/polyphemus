import json

import pytest

from agent.ingestion.audit import (
    AuditIssue,
    AuditReport,
    LightRAGStorageReader,
    StorageParseError,
    has_critical_issues,
)


def test_audit_report_model_dump_contains_required_fields():
    report = AuditReport(
        job_id="job-123",
        source_key="docs/foo.md",
        checked_at="2025-01-01T00:00:00Z",
    )
    dumped = report.model_dump(mode="json")
    assert "critical_issues" in dumped
    assert "warnings" in dumped
    assert "merge_candidates" in dumped
    assert "checked_at" in dumped
    assert dumped["critical_issues"] == []
    assert dumped["warnings"] == []
    assert dumped["merge_candidates"] == []


def test_has_critical_issues_false_for_warnings_only():
    report = AuditReport(
        job_id="job-123",
        source_key="docs/foo.md",
        checked_at="2025-01-01T00:00:00Z",
        warnings=[
            AuditIssue(
                code="WARN-1",
                message="minor issue",
                severity="warning",
                evidence={"detail": "something"},
            )
        ],
    )
    assert has_critical_issues(report) is False


def test_has_critical_issues_true_when_critical_present():
    report = AuditReport(
        job_id="job-123",
        source_key="docs/foo.md",
        checked_at="2025-01-01T00:00:00Z",
        critical_issues=[
            AuditIssue(
                code="CRIT-1",
                message="blocking issue",
                severity="critical",
                evidence={"detail": "bad"},
            )
        ],
    )
    assert has_critical_issues(report) is True


def test_audit_report_mutable_defaults_are_not_shared():
    report_a = AuditReport(job_id="a", source_key="a.md", checked_at="now")
    report_b = AuditReport(job_id="b", source_key="b.md", checked_at="now")
    report_a.critical_issues.append(
        AuditIssue(code="X", message="x", severity="critical")
    )
    assert report_b.critical_issues == []


def test_json_kv_files_are_loaded(tmp_path):
    doc_status = {"doc1": {"status": "processed", "chunks_count": 2}}
    full_docs = {"doc1": "full document text"}
    text_chunks = {"chunk1": {"tokens": 10, "content": "text", "full_doc_id": "doc1"}}
    full_entities = {"entity1": {"entity_type": "Server", "description": "desc"}}
    full_relations = {"rel1": {"src_id": "entity1", "tgt_id": "entity2"}}
    entity_chunks = {"entity1": ["chunk1"]}
    relation_chunks = {"rel1": ["chunk1"]}
    for name, payload in [
        ("kv_store_doc_status.json", doc_status),
        ("kv_store_full_docs.json", full_docs),
        ("kv_store_text_chunks.json", text_chunks),
        ("kv_store_full_entities.json", full_entities),
        ("kv_store_full_relations.json", full_relations),
        ("kv_store_entity_chunks.json", entity_chunks),
        ("kv_store_relation_chunks.json", relation_chunks),
    ]:
        (tmp_path / name).write_text(json.dumps(payload))

    reader = LightRAGStorageReader(tmp_path)
    snap = reader.snapshot()
    assert snap.kv_store_doc_status == doc_status
    assert snap.kv_store_full_docs == full_docs
    assert snap.kv_store_text_chunks == text_chunks
    assert snap.kv_store_full_entities == full_entities
    assert snap.kv_store_full_relations == full_relations
    assert snap.kv_store_entity_chunks == entity_chunks
    assert snap.kv_store_relation_chunks == relation_chunks


def test_vdb_chunks_json_is_loaded(tmp_path):
    vdb = {
        "chunk1": {
            "id": "chunk1",
            "vector": [0.1, 0.2],
            "metadata": {"doc_id": "doc1"},
        }
    }
    (tmp_path / "vdb_chunks.json").write_text(json.dumps(vdb))
    snap = LightRAGStorageReader(tmp_path).snapshot()
    assert snap.vdb_chunks == vdb
    assert snap.vdb_entities == {}
    assert snap.vdb_relationships == {}


def test_graphml_with_one_node_and_one_edge_is_parsed(tmp_path):
    graphml = """<?xml version="1.0" encoding="UTF-8"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="entity_type" attr.type="string"/>
  <key id="d1" for="node" attr.name="source_id" attr.type="string"/>
  <key id="d2" for="node" attr.name="file_path" attr.type="string"/>
  <key id="d3" for="node" attr.name="description" attr.type="string"/>
  <key id="d4" for="node" attr.name="keywords" attr.type="string"/>
  <key id="d5" for="edge" attr.name="source_id" attr.type="string"/>
  <key id="d6" for="edge" attr.name="file_path" attr.type="string"/>
  <key id="d7" for="edge" attr.name="description" attr.type="string"/>
  <key id="d8" for="edge" attr.name="keywords" attr.type="string"/>
  <graph id="G" edgedefault="directed">
    <node id="n1">
      <data key="d0">Server</data>
      <data key="d1">doc1</data>
      <data key="d2">report.md</data>
      <data key="d3">A server</data>
      <data key="d4">nginx,apache</data>
    </node>
    <edge id="e1" source="n1" target="n2">
      <data key="d5">doc1</data>
      <data key="d6">report.md</data>
      <data key="d7">A relationship</data>
      <data key="d8">needs-merge</data>
    </edge>
  </graph>
</graphml>"""
    (tmp_path / "graph_chunk_entity_relation.graphml").write_text(graphml)
    snap = LightRAGStorageReader(tmp_path).snapshot()
    assert len(snap.graph.nodes) == 1
    node = snap.graph.nodes[0]
    assert node.id == "n1"
    assert node.entity_type == "Server"
    assert node.source_id == "doc1"
    assert node.file_path == "report.md"
    assert node.description == "A server"
    assert node.keywords == "nginx,apache"
    assert len(snap.graph.edges) == 1
    edge = snap.graph.edges[0]
    assert edge.source == "n1"
    assert edge.target == "n2"
    assert edge.source_id == "doc1"
    assert edge.file_path == "report.md"
    assert edge.description == "A relationship"
    assert edge.keywords == "needs-merge"


def test_missing_files_do_not_break_snapshot_and_are_recorded(tmp_path):
    snap = LightRAGStorageReader(tmp_path).snapshot()
    assert snap.kv_store_doc_status == {}
    assert snap.vdb_chunks == {}
    assert snap.vdb_entities == {}
    assert snap.vdb_relationships == {}
    assert snap.graph.nodes == []
    assert snap.graph.edges == []
    expected = [
        "kv_store_doc_status.json",
        "kv_store_full_docs.json",
        "kv_store_text_chunks.json",
        "kv_store_full_entities.json",
        "kv_store_full_relations.json",
        "kv_store_entity_chunks.json",
        "kv_store_relation_chunks.json",
        "vdb_chunks.json",
        "vdb_entities.json",
        "vdb_relationships.json",
        "graph_chunk_entity_relation.graphml",
    ]
    assert sorted(snap.missing_files) == sorted(expected)


def test_snapshot_does_not_write_delete_or_modify_files(tmp_path):
    doc_status = {"doc1": {"status": "processed"}}
    path = tmp_path / "kv_store_doc_status.json"
    path.write_text(json.dumps(doc_status))
    before = path.read_bytes()
    before_entries = set(tmp_path.iterdir())
    reader = LightRAGStorageReader(tmp_path)
    reader.snapshot()
    after = path.read_bytes()
    after_entries = set(tmp_path.iterdir())
    assert after == before
    assert after_entries == before_entries


def test_malformed_json_raises_storage_parse_error(tmp_path):
    (tmp_path / "kv_store_doc_status.json").write_text("{not valid json")
    with pytest.raises(StorageParseError):
        LightRAGStorageReader(tmp_path).snapshot()


def test_malformed_graphml_raises_storage_parse_error(tmp_path):
    (tmp_path / "graph_chunk_entity_relation.graphml").write_text("<graphml><graph>")
    with pytest.raises(StorageParseError):
        LightRAGStorageReader(tmp_path).snapshot()
