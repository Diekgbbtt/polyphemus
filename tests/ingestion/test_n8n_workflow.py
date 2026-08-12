import json
from pathlib import Path


def test_n8n_workflow_uses_local_trigger_and_no_code_nodes():
    workflow = json.loads(Path("workflows/n8n/lightrag-file-ingestion.json").read_text(encoding="utf-8"))

    node_types = {node["type"] for node in workflow["nodes"]}
    assert "n8n-nodes-base.localFileTrigger" in node_types
    assert "n8n-nodes-base.scheduleTrigger" not in node_types
    assert "n8n-nodes-base.code" not in node_types
    assert "n8n-nodes-base.executeCommand" in node_types
    assert "n8n-nodes-base.httpRequest" in node_types
    trigger = next(node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.localFileTrigger")
    assert trigger["parameters"]["triggerOn"] == "folder"
    assert trigger["parameters"]["options"]["awaitWriteFinish"] is True


def test_n8n_workflow_calls_agent_ingestion_api_and_moves_terminal_files():
    workflow = json.loads(Path("workflows/n8n/lightrag-file-ingestion.json").read_text(encoding="utf-8"))
    serialized = json.dumps(workflow)

    assert "http://ingestion:8080/v1/ingestions" in serialized
    assert "/data/ingestion/processed" in serialized
    assert "/data/ingestion/failed" in serialized
    assert "SKIPPED_DUPLICATE" in serialized
    assert "PROCESSED" in serialized
    assert "FAILED" in serialized
    assert '"operation": "move"' not in serialized
