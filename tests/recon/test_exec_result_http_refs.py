"""#196: ExecResult carries exec_id + http artifact refs, backward-compatibly."""
from __future__ import annotations

from polymerhus.recon.domain.pod import _exec_result_from_artifact
from polymerhus.recon.domain.types import CaptureContext, ExecResult


def test_exec_result_new_fields_default_to_empty():
    result = ExecResult(stdout="x", stderr="", returncode=0)
    assert result.exec_id == ""
    assert result.http_artifact_refs == []
    assert result.capture_warning is None


def test_artifact_mapping_reads_the_new_fields():
    artifact = {
        "stdout": "ok",
        "stderr": "",
        "returncode": 0,
        "duration_ms": 12,
        "exec_id": "01JEXEC",
        "http_artifact_refs": ["http_01J0000000000000000000000A"],
        "capture_warning": "capture unavailable: pool exhausted",
    }
    result = _exec_result_from_artifact(artifact)
    assert result.exec_id == "01JEXEC"
    assert result.http_artifact_refs == ["http_01J0000000000000000000000A"]
    assert "pool exhausted" in result.capture_warning


def test_artifact_mapping_keeps_old_payloads_working():
    artifact = {"stdout": "ok", "stderr": "", "returncode": 0, "duration_ms": 3}
    result = _exec_result_from_artifact(artifact)
    assert result.exec_id == ""
    assert result.http_artifact_refs == []
    assert result.capture_warning is None


def test_artifact_mapping_reads_the_browser_error_fields():
    artifact = {
        "stdout": "",
        "stderr": "CDP error",
        "returncode": 1,
        "duration_ms": 1,
        "error": {
            "code": "target_lost",
            "message": "the page target is gone",
            "retryable": False,
            "fatal": False,
            "recovery": {"action": "tab_new"},
            "session": {"name": "wj-live", "live": True},
            "canonical_command": "steel browser eval --session wj-live --json",
        },
    }
    result = _exec_result_from_artifact(artifact)
    assert result.error_code == "target_lost"
    assert result.error_message == "the page target is gone"
    assert result.retryable is False
    assert result.fatal is False
    assert result.recovery["action"] == "tab_new"
    assert result.session_state == {"name": "wj-live", "live": True}
    assert result.canonical_command == "steel browser eval --session wj-live --json"


def test_capture_context_is_a_typed_runtime_value():
    context = CaptureContext(project_id="proj-1", run_id="r1", spec_id="s", variant_ref="v0")
    assert context.project_id == "proj-1"
    assert context.as_mcp_args()["project_id"] == "proj-1"
