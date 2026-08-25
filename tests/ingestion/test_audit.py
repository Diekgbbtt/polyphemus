import json
from datetime import datetime

import pytest

from polymerhus.ingestion.audit import (
    AuditIssue,
    AuditReport,
    GraphEdge,
    GraphMLGraph,
    GraphNode,
    LightRAGStorageReader,
    LightRAGStorageSnapshot,
    StorageParseError,
    has_critical_issues,
    run_post_ingestion_audit,
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


def test_audit_valid_snapshot_has_zero_critical_issues():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
        kv_store_text_chunks={"chunk1": {"full_doc_id": "doc1"}},
        vdb_chunks={"chunk1": {"metadata": {"doc_id": "doc1"}}},
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="n1", entity_type="Server", source_id="doc1"),
                GraphNode(id="n2", entity_type="Client", source_id="doc1"),
            ],
            edges=[
                GraphEdge(source="n1", target="n2", source_id="doc1"),
            ],
        ),
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types={"Server", "Client"},
    )
    assert report.critical_issues == []


def test_audit_missing_lightrag_document_id():
    snapshot = LightRAGStorageSnapshot()
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    assert [i.code for i in report.critical_issues] == ["LIGHTRAG_DOCUMENT_ID_MISSING"]


def test_audit_missing_document_status():
    snapshot = LightRAGStorageSnapshot()
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    assert [i.code for i in report.critical_issues] == ["DOCUMENT_STATUS_MISSING"]


def test_audit_failed_document_status():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "failed"}},
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    assert "DOCUMENT_STATUS_FAILED" in [i.code for i in report.critical_issues]


def test_audit_successful_doc_with_no_chunks():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    assert "DOCUMENT_HAS_NO_CHUNKS" in [i.code for i in report.critical_issues]


def test_audit_entity_type_not_allowed():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="n1", entity_type="Server", source_id="doc1"),
                GraphNode(id="n2", entity_type="Evil", source_id="doc1"),
            ]
        ),
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )
    codes = [i.code for i in report.critical_issues]
    assert "ENTITY_TYPE_NOT_ALLOWED" in codes


def test_audit_orphan_edge_source():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[GraphNode(id="n1", source_id="doc1")],
            edges=[GraphEdge(source="missing", target="n1", source_id="doc1")],
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    codes = [i.code for i in report.critical_issues]
    assert "ORPHAN_RELATION_ENDPOINT" in codes


def test_audit_orphan_edge_target():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[GraphNode(id="n1", source_id="doc1")],
            edges=[GraphEdge(source="n1", target="missing", source_id="doc1")],
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    codes = [i.code for i in report.critical_issues]
    assert "ORPHAN_RELATION_ENDPOINT" in codes


def test_audit_graph_node_without_provenance():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[GraphNode(id="n1", entity_type="Server")],
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )
    codes = [i.code for i in report.critical_issues]
    assert "GRAPH_NODE_WITHOUT_PROVENANCE" in codes


def test_audit_graph_edge_without_provenance():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="n1", source_id="doc1"),
                GraphNode(id="n2", source_id="doc1"),
            ],
            edges=[GraphEdge(source="n1", target="n2", source_id="")],
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    codes = [i.code for i in report.critical_issues]
    assert "GRAPH_EDGE_WITHOUT_PROVENANCE" in codes


def test_audit_missing_vector_chunk():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
        kv_store_text_chunks={"chunk1": {"full_doc_id": "doc1"}},
        vdb_chunks={},
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    codes = [i.code for i in report.critical_issues]
    assert "VECTOR_CHUNK_MISSING" in codes


def test_audit_kv_vector_chunk_mismatch():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
        kv_store_text_chunks={"chunk1": {"full_doc_id": "doc1"}},
        vdb_chunks={"chunk1": {"metadata": {"doc_id": "doc1"}}},
    )
    snapshot.kv_store_text_chunks = {"other": {"full_doc_id": "doc2"}}
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    codes = [i.code for i in report.critical_issues]
    assert "KV_VECTOR_CHUNK_MISMATCH" in codes


def test_audit_does_not_mutate_input_snapshot():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
        kv_store_text_chunks={"chunk1": {"full_doc_id": "doc1"}},
        vdb_chunks={"chunk1": {"metadata": {"doc_id": "doc1"}}},
        graph=GraphMLGraph(
            nodes=[GraphNode(id="n1", entity_type="Server", source_id="doc1")],
            edges=[GraphEdge(source="n1", target="n2", source_id="doc1")],
        ),
    )
    original = snapshot.model_copy(deep=True)

    run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )

    assert snapshot == original


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


# ---------------------------------------------------------------------------
# New tests for warnings and merge candidates
# ---------------------------------------------------------------------------


def test_missing_storage_file_creates_warning():
    snapshot = LightRAGStorageSnapshot(missing_files=["kv_store_doc_status.json"])
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    assert any(i.code == "MISSING_STORAGE_FILE" for i in report.warnings)


def test_successful_doc_with_explicit_zero_chunks_warning():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed", "chunks_count": 0}},
        kv_store_text_chunks={},
        vdb_chunks={},
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    assert any(i.code == "DOCUMENT_EXPLICIT_ZERO_CHUNKS" for i in report.warnings)


def test_ontology_divergence_warning():
    snapshot = LightRAGStorageSnapshot()
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types=set(),
    )
    assert any(i.code == "ONTOLOGY_DIVERGENCE" for i in report.warnings)


def test_warnings_do_not_block_successful_audit():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
        kv_store_text_chunks={"chunk1": {"full_doc_id": "doc1"}},
        vdb_chunks={"chunk1": {"metadata": {"doc_id": "doc1"}}},
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="n1", entity_type="Server", source_id="doc1"),
                GraphNode(id="n2", entity_type="Client", source_id="doc1"),
            ],
            edges=[GraphEdge(source="n1", target="n2", source_id="doc1")],
        ),
        missing_files=["vdb_relationships.json"],
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types={"Server", "Client"},
    )
    assert has_critical_issues(report) is False
    assert any(i.code == "MISSING_STORAGE_FILE" for i in report.warnings)
    assert any(i.code == "ONTOLOGY_DIVERGENCE" for i in report.warnings)


def test_exact_duplicate_entities_create_merge_candidates():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id=" Apache ", entity_type="Server", source_id="doc1",
                          description="Apache server", keywords="apache"),
                GraphNode(id="apache", entity_type="Server", source_id="doc1",
                          description="Apache server", keywords="apache"),
            ]
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )
    entity_candidates = [
        c for c in report.merge_candidates if c["candidate_type"] == "entity_duplicate"
    ]
    assert len(entity_candidates) == 1
    assert entity_candidates[0]["node_ids"] == [" Apache ", "apache"]


def test_exact_duplicate_relations_create_merge_candidates():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="n1", entity_type="Server", source_id="doc1",
                          description="Apache server", keywords="apache"),
                GraphNode(id="n2", entity_type="Client", source_id="doc1",
                          description="Browser client", keywords="browser"),
            ],
            edges=[
                GraphEdge(source="n1", target="n2", source_id="doc1",
                          description="serves", keywords="http"),
                GraphEdge(source="n1", target="n2", source_id="doc1",
                          description="serves", keywords="http"),
            ],
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server", "Client"},
    )
    rel_candidates = [
        c for c in report.merge_candidates if c["candidate_type"] == "relation_duplicate"
    ]
    assert len(rel_candidates) == 1
    assert rel_candidates[0]["edges"] == [
        {"source": "n1", "target": "n2"},
        {"source": "n1", "target": "n2"},
    ]


def test_non_exact_candidates_not_reported():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="n1", entity_type="Server", source_id="doc1",
                          description="Apache server", keywords="apache"),
                GraphNode(id="n2", entity_type="Server", source_id="doc1",
                          description="Nginx server", keywords="nginx"),
            ]
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )
    assert all(
        c["candidate_type"] != "entity_duplicate" for c in report.merge_candidates
    )


def test_audit_execution_has_no_side_effects_on_warnings_and_merge_candidates():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
        kv_store_text_chunks={"chunk1": {"full_doc_id": "doc1"}},
        vdb_chunks={"chunk1": {"metadata": {"doc_id": "doc1"}}},
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="n1", entity_type="Server", source_id="doc1",
                          description="Apache server", keywords="apache"),
                GraphNode(id="n2", entity_type="Server", source_id="doc1",
                          description="Apache server", keywords="apache"),
            ],
            edges=[GraphEdge(source="n1", target="n2", source_id="doc1",
                             description="serves", keywords="http")],
        ),
        missing_files=["vdb_chunks.json"],
    )
    original = snapshot.model_copy(deep=True)

    run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )

    assert snapshot == original


# ---------------------------------------------------------------------------
# New tests for the reviewed findings
# ---------------------------------------------------------------------------


def test_vdb_chunks_container_schema_no_false_missing_or_mismatch():
    snapshot = LightRAGStorageSnapshot(
        kv_store_doc_status={"doc1": {"status": "processed"}},
        kv_store_text_chunks={"chunk-1": {"full_doc_id": "doc1"}},
        vdb_chunks={
            "embedding_dim": 3,
            "matrix": [],
            "data": [
                {"__id__": "chunk-1", "full_doc_id": "doc1"},
            ],
        },
        graph=GraphMLGraph(
            nodes=[GraphNode(id="n1", entity_type="Server", source_id="doc1")],
            edges=[],
        ),
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id="doc1",
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )
    codes = [i.code for i in report.critical_issues]
    assert "VECTOR_CHUNK_MISSING" not in codes
    assert "KV_VECTOR_CHUNK_MISMATCH" not in codes


def test_checked_at_is_non_empty_utc_rfc3339():
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=LightRAGStorageSnapshot(),
        allowed_entity_types=set(),
    )
    assert report.checked_at
    dt = datetime.fromisoformat(report.checked_at)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_duplicate_entity_requires_same_normalized_id():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="AES128", entity_type="Crypto", source_id="doc1",
                          description="AES128", keywords="aes"),
                GraphNode(id="AES256", entity_type="Crypto", source_id="doc1",
                          description="AES128", keywords="aes"),
            ]
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Crypto"},
    )
    entity_candidates = [
        c for c in report.merge_candidates if c["candidate_type"] == "entity_duplicate"
    ]
    assert entity_candidates == []


def test_exact_normalized_duplicate_entities_detected():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="Server-1", entity_type="Server", source_id="doc1",
                          description="Apache", keywords="web"),
                GraphNode(id="server-1", entity_type="Server", source_id="doc1",
                          description="Apache", keywords="web"),
            ]
        )
    )
    report = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server"},
    )
    entity_candidates = [
        c for c in report.merge_candidates if c["candidate_type"] == "entity_duplicate"
    ]
    assert len(entity_candidates) == 1
    assert entity_candidates[0]["node_ids"] == ["Server-1", "server-1"]


def test_duplicate_candidate_ordering_is_deterministic():
    snapshot = LightRAGStorageSnapshot(
        graph=GraphMLGraph(
            nodes=[
                GraphNode(id="z-a", entity_type="Server", source_id="doc1",
                          description="x", keywords="k"),
                GraphNode(id="z-b", entity_type="Server", source_id="doc1",
                          description="x", keywords="k"),
                GraphNode(id="a-a", entity_type="Client", source_id="doc1",
                          description="y", keywords="l"),
                GraphNode(id="a-b", entity_type="Client", source_id="doc1",
                          description="y", keywords="l"),
            ]
        )
    )
    report1 = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server", "Client"},
    )
    report2 = run_post_ingestion_audit(
        job_id="job-1",
        source_key="docs/foo.md",
        lightrag_document_id=None,
        storage_snapshot=snapshot,
        allowed_entity_types={"Server", "Client"},
    )
    assert report1.merge_candidates == report2.merge_candidates
    entity_ids = [
        c["node_ids"] for c in report1.merge_candidates
        if c["candidate_type"] == "entity_duplicate"
    ]
    assert all(ids == sorted(ids) for ids in entity_ids)
