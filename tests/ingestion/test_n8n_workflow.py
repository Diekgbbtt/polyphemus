import json
from pathlib import Path


def test_n8n_workflow_uses_local_trigger_and_no_code_nodes():
    workflow = json.loads(Path("lightrag/workflows/n8n/lightrag-file-ingestion.json").read_text(encoding="utf-8"))

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
    workflow = json.loads(Path("lightrag/workflows/n8n/lightrag-file-ingestion.json").read_text(encoding="utf-8"))
    serialized = json.dumps(workflow)

    assert "http://ingestion:8080/v1/ingestions" in serialized
    assert "/data/ingestion/processed" in serialized
    assert "/data/ingestion/failed" in serialized
    assert "SKIPPED_DUPLICATE" in serialized
    assert "PROCESSED" in serialized
    assert "FAILED" in serialized
    assert "FAILED_AUDIT" in serialized
    assert '"operation": "move"' not in serialized


def test_n8n_workflow_terminates_and_routes_failed_audit_to_failed_folder():
    workflow = json.loads(Path("lightrag/workflows/n8n/lightrag-file-ingestion.json").read_text(encoding="utf-8"))

    terminal = next(node for node in workflow["nodes"] if node["name"] == "Terminal state?")
    success = next(node for node in workflow["nodes"] if node["name"] == "Success or duplicate?")

    def regex_value(node):
        string_condition = node["parameters"]["conditions"]["string"][0]
        assert string_condition["operation"] == "regex"
        return string_condition["value2"]

    terminal_regex = regex_value(terminal)
    success_regex = regex_value(success)

    assert "FAILED_AUDIT" in terminal_regex
    assert "PROCESSED" in terminal_regex
    assert "SKIPPED_DUPLICATE" in terminal_regex
    assert "FAILED" in terminal_regex

    assert "FAILED_AUDIT" not in success_regex
    assert "PROCESSED" in success_regex
    assert "SKIPPED_DUPLICATE" in success_regex
    assert "FAILED" not in success_regex


def test_n8n_workflow_does_not_execute_audit_logic():
    workflow = json.loads(Path("lightrag/workflows/n8n/lightrag-file-ingestion.json").read_text(encoding="utf-8"))
    serialized = json.dumps(workflow)

    assert "critical_issues" not in serialized
    assert "merge_candidates" not in serialized
    assert "critical" not in serialized
    assert "audit_runner" not in serialized
    assert "AUDIT_FAILED" not in serialized  # backend error code
    # Only the status token FAILED_AUDIT is allowed because n8n is routing a
    # backend-reported final state, not executing the audit itself.
    assert serialized.count("FAILED_AUDIT") == 1
