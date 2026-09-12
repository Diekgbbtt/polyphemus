"""The MCP tool bodies: backward compatibility, fail-open capture, not_found."""
from __future__ import annotations

import kali.mcp_server as mcp_server
from kali.http_history.config import HttpHistoryConfig
from kali.http_history.models import (
    CaptureContext,
    HttpArtifact,
    RequestRecord,
    ResponseRecord,
)
from kali.http_history.service import ExecOutcome, HttpHistoryService
from kali.http_history.store import HttpHistoryStore


class FakeLease:
    def __init__(self, namespace="kali-http-0001"):
        self.namespace = namespace
        self.source_ip = "172.30.0.2"
        self.session_id = "s1"
        self.slot = 0


class FakeLeaseManager:
    def __init__(self):
        self.acquired = []
        self.released = []

    def acquire(self, *, session_id, project_id, context):
        self.acquired.append((session_id, project_id, context.exec_id))
        return FakeLease()

    def release(self, lease):
        self.released.append(lease)

    def status(self):
        return {"pool_size": 4, "active": 1, "available": 3}


class CapturingManager(FakeLeaseManager):
    """Records the runtime exec_id so a fake addon can stamp it on an artifact."""

    def __init__(self, runner):
        super().__init__()
        self._runner = runner

    def acquire(self, *, session_id, project_id, context):
        self._runner.exec_id = context.exec_id
        return super().acquire(session_id=session_id, project_id=project_id, context=context)


def _capturing_runner(store_root, artifact_id="http_01J0000000000000000000000C"):
    def runner(command, session_id, timeout_s, namespace=None):
        store = HttpHistoryStore(store_root, "proj-1")
        store.record(
            HttpArtifact(
                artifact_id=artifact_id,
                project_id="proj-1",
                capture_context=CaptureContext(exec_id=runner.exec_id, session_id=session_id),
                request=RequestRecord(method="GET", url="https://target.example/"),
                response=ResponseRecord(status=200, reason="OK"),
            ),
            bodies={},
        )
        return ExecOutcome(stdout="ok", stderr="", returncode=0, duration_ms=5)

    runner.exec_id = ""
    return runner


def _service(tmp_path, lease_manager, runner):
    return HttpHistoryService(
        config=HttpHistoryConfig(store_root=str(tmp_path)),
        lease_manager=lease_manager,
        runner=runner,
        proxy_probe=lambda: {"ok": True},
        routing_probe=lambda: {"ok": True},
    )


def test_execute_command_keeps_the_legacy_shape(tmp_path, monkeypatch):
    def runner(command, session_id, timeout_s, namespace=None):
        return ExecOutcome(stdout="hello", stderr="", returncode=0, duration_ms=3)

    service = _service(tmp_path, FakeLeaseManager(), runner)
    monkeypatch.setattr(mcp_server, "_SERVICE", service)
    out = mcp_server.execute_command("echo hello", "run1-pod1")
    assert out["stdout"] == "hello"
    assert out["returncode"] == 0
    assert "duration_ms" in out
    assert out["exec_id"]
    assert out["http_artifact_refs"] == []
    assert out["capture_warning"] is None


def test_execute_command_correlates_refs(tmp_path, monkeypatch):
    runner = _capturing_runner(tmp_path)
    manager = CapturingManager(runner)
    service = _service(tmp_path, manager, runner)
    monkeypatch.setattr(mcp_server, "_SERVICE", service)
    out = mcp_server.execute_command(
        "curl https://target.example/", "s1", project_id="proj-1", run_id="r1", variant_ref="v0"
    )
    assert out["returncode"] == 0
    assert out["http_artifact_refs"] == ["http_01J0000000000000000000000C"]
    assert manager.released  # the lease is always returned


def test_capture_failure_does_not_prevent_execution(tmp_path, monkeypatch):
    class BoomManager:
        def acquire(self, **_kwargs):
            raise TimeoutError("pool exhausted")

    def runner(command, session_id, timeout_s, namespace=None):
        return ExecOutcome(stdout="ran anyway", stderr="", returncode=0, duration_ms=1)

    service = _service(tmp_path, BoomManager(), runner)
    monkeypatch.setattr(mcp_server, "_SERVICE", service)
    out = mcp_server.execute_command("true", "s1", project_id="proj-1")
    assert out["stdout"] == "ran anyway"
    assert out["returncode"] == 0
    assert "capture unavailable" in out["capture_warning"]


def test_search_get_and_status_tools(tmp_path, monkeypatch):
    runner = _capturing_runner(tmp_path)
    service = _service(tmp_path, CapturingManager(runner), runner)
    monkeypatch.setattr(mcp_server, "_SERVICE", service)
    mcp_server.execute_command("probe", "s1", project_id="proj-1")

    page = mcp_server.search_http_history("proj-1", filters=[])
    assert page["summaries"][0]["artifact_id"] == "http_01J0000000000000000000000C"
    view = mcp_server.get_http_artifact("proj-1", "http_01J0000000000000000000000C")
    assert view["request"]["method"] == "GET"
    assert mcp_server.get_http_artifact("proj-2", "http_01J0000000000000000000000C") == {
        "error": "not_found",
        "detail": "artifact 'http_01J0000000000000000000000C' not found in project 'proj-2'",
    }
    status = mcp_server.proxy_status()
    assert status["ok"] is True
    assert status["namespaces"]["pool_size"] == 4
