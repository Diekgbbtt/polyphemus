"""MCP-facing service: project isolation, sanitized views, replay lineage."""
from __future__ import annotations

import pytest

from kali.http_history.config import HttpHistoryConfig
from kali.http_history.models import (
    CaptureContext,
    HttpArtifact,
    NameValue,
    RequestRecord,
    ResponseRecord,
)
from kali.http_history.normalize import normalize_flow
from kali.http_history.service import HttpHistoryService, NotFoundError
from kali.http_history.store import HttpHistoryStore
from tests.kali.fakes import FakeFlow, FakeMessage


def _service(tmp_path, **config_overrides) -> HttpHistoryService:
    config = HttpHistoryConfig(store_root=str(tmp_path), **config_overrides)
    return HttpHistoryService(config=config)


def _seed(tmp_path, project="proj-1", artifact_id="http_01J0000000000000000000000A"):
    flow = FakeFlow(
        request=FakeMessage(
            method="POST",
            url="https://target.example/login?token=supersecret",
            headers=[["authorization", "Bearer supersecret"], ["accept", "application/json"]],
        ),
        response=FakeMessage(status=200, reason="OK", content=b"welcome"),
    )
    artifact, bodies = normalize_flow(
        flow,
        project_id=project,
        capture_context=CaptureContext(exec_id="e1", session_id="s1"),
        artifact_id=artifact_id,
    )
    HttpHistoryStore(tmp_path, project).record(artifact, bodies)
    return artifact


def test_search_returns_sanitized_summaries(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    page = service.search("proj-1", filters=[{"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "POST"}])
    assert len(page["summaries"]) == 1
    summary = page["summaries"][0]
    assert summary["artifact_id"] == "http_01J0000000000000000000000A"
    assert "supersecret" not in str(page)


def test_search_limit_bounds_are_enforced(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.search("proj-1", limit=0)
    with pytest.raises(ValueError):
        service.search("proj-1", limit=201)


def test_search_rejects_the_reserved_unscoped_project(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.search("unscoped")


def test_get_returns_a_sanitized_record(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    view = service.get("proj-1", "http_01J0000000000000000000000A")
    assert view["request"]["method"] == "POST"
    assert "supersecret" not in str(view)


def test_get_rejects_include_body_on_the_model_facing_surface(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.get("proj-1", "http_01J0000000000000000000000A", include_body=True)


def test_cross_project_get_is_not_found(tmp_path):
    _seed(tmp_path, project="proj-1")
    service = _service(tmp_path)
    with pytest.raises(NotFoundError):
        service.get("proj-2", "http_01J0000000000000000000000A")


def _fake_sender(store):
    def sender(project_id, plan, context):
        artifact = HttpArtifact(
            artifact_id="http_01J0000000000000000000000B",
            project_id=project_id,
            capture_context=context,
            request=RequestRecord(
                method=plan.method, url=plan.url, headers=list(plan.headers), body_size=len(plan.body)
            ),
            response=ResponseRecord(status=200, reason="OK"),
        )
        bodies = {}
        if plan.body:
            import hashlib

            ref = f"sha256:{hashlib.sha256(plan.body).hexdigest()}"
            artifact.request.body_ref = ref
            bodies[ref] = plan.body
        store.record(artifact, bodies)
        return artifact.artifact_id

    return sender


def test_replay_baseline_creates_a_derived_artifact(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    store = HttpHistoryStore(tmp_path, "proj-1")
    result = service.replay(
        "proj-1", "http_01J0000000000000000000000A", {}, sender=_fake_sender(store)
    )
    assert result["artifact_id"] == "http_01J0000000000000000000000B"
    assert result["derived_from"] == "http_01J0000000000000000000000A"
    assert result["replay_kind"] == "baseline"
    assert store.get_raw("http_01J0000000000000000000000A").derived_from is None


def test_replay_mutation_is_marked_mutated(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    store = HttpHistoryStore(tmp_path, "proj-1")
    result = service.replay(
        "proj-1",
        "http_01J0000000000000000000000A",
        {"method": "PUT"},
        sender=_fake_sender(store),
    )
    assert result["replay_kind"] == "mutated"


def test_replay_rejects_unknown_overrides(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.replay(
            "proj-1",
            "http_01J0000000000000000000000A",
            {"command": "rm -rf /"},
            sender=_fake_sender(HttpHistoryStore(tmp_path, "proj-1")),
        )


def test_cross_project_replay_is_not_found(tmp_path):
    _seed(tmp_path, project="proj-1")
    service = _service(tmp_path)
    with pytest.raises(NotFoundError):
        service.replay(
            "proj-2",
            "http_01J0000000000000000000000A",
            {},
            sender=_fake_sender(HttpHistoryStore(tmp_path, "proj-2")),
        )


def test_proxy_status_distinguishes_every_component(tmp_path):
    service = HttpHistoryService(
        config=HttpHistoryConfig(store_root=str(tmp_path)),
        proxy_probe=lambda: {"ok": True, "detail": "listening"},
        routing_probe=lambda: {"ok": True, "detail": "rules present"},
    )
    status = service.proxy_status()
    assert set(status) >= {"ok", "mcp", "proxy", "routing", "namespaces", "store", "capture"}
    assert status["mcp"]["ok"] is True
    assert status["proxy"]["ok"] is True
    assert status["store"]["ok"] is True


def test_enforce_limits_applies_the_configured_caps(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path, retention_s=0, project_max_bytes=1)
    result = service.enforce_limits("proj-1")
    assert result["artifacts_removed"] == 1
    assert service.store("proj-1").status()["artifact_count"] == 0


def test_purge_project_removes_everything(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    result = service.purge_project("proj-1")
    assert result["artifacts_removed"] == 1
    assert service.search("proj-1")["summaries"] == []


from kali.http_history.service import BodyUnavailableError


def test_replay_refuses_a_baseline_whose_body_is_missing(tmp_path):
    flow = FakeFlow(
        request=FakeMessage(
            method="POST", url="https://target.example/upload", content=b"0123456789"
        ),
        response=FakeMessage(status=200, reason="OK"),
    )
    artifact, bodies = normalize_flow(
        flow,
        project_id="proj-1",
        capture_context=CaptureContext(exec_id="e1"),
        artifact_id="http_01J0000000000000000000000A",
        max_body_bytes=1,
    )
    assert artifact.request.capture_state == "omitted"
    assert bodies == {}
    HttpHistoryStore(tmp_path, "proj-1").record(artifact, bodies)

    service = _service(tmp_path)
    store = HttpHistoryStore(tmp_path, "proj-1")
    with pytest.raises(BodyUnavailableError) as excinfo:
        service.replay("proj-1", artifact.artifact_id, {}, sender=_fake_sender(store))
    assert "omitted" in str(excinfo.value)


def test_replay_still_accepts_a_bodyless_baseline(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    store = HttpHistoryStore(tmp_path, "proj-1")
    result = service.replay(
        "proj-1", "http_01J0000000000000000000000A", {}, sender=_fake_sender(store)
    )
    assert result["replay_kind"] == "baseline"


from kali.http_history.service import ExecOutcome


def test_execute_can_label_a_manual_replay(tmp_path):
    seen = {}

    class _Lease:
        namespace = "kali-http-0001"

    class _Leases:
        def acquire(self, *, session_id, project_id, context):
            seen["context"] = context
            return _Lease()

        def release(self, lease):
            pass

    service = HttpHistoryService(
        config=HttpHistoryConfig(store_root=str(tmp_path)),
        lease_manager=_Leases(),
        runner=lambda command, session_id, timeout_s, namespace=None: ExecOutcome(
            stdout="", stderr="", returncode=0, duration_ms=1
        ),
    )
    service.execute(
        "curl -sS http://t/", "s1", project_id="proj-1",
        derived_from="http_01J0000000000000000000000A", replay_kind="mutated",
    )
    assert seen["context"].derived_from == "http_01J0000000000000000000000A"
    assert seen["context"].replay_kind == "mutated"


def test_store_cache_is_bounded(tmp_path, monkeypatch):
    from kali.http_history import service as service_module

    monkeypatch.setattr(service_module, "_STORE_CACHE_MAX", 2)
    service = _service(tmp_path)
    for index in range(4):
        service.store(f"proj-{index}")
    assert len(service._stores) <= 2
    assert "proj-0" not in service._stores
