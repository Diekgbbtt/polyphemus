"""MCP-facing service: project isolation, sanitized views, replay lineage."""
from __future__ import annotations

import json

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
from kali.http_history import service as service_module
from kali.http_history.service import ExecOutcome, HttpHistoryService, NotFoundError
from kali.http_history.store import HttpHistoryStore
from tests.kali.fakes import FakeFlow, FakeMessage


def _service(tmp_path, **config_overrides) -> HttpHistoryService:
    config = HttpHistoryConfig(store_root=str(tmp_path), **config_overrides)
    return HttpHistoryService(config=config)


def _quiet_service(tmp_path, **config_overrides) -> HttpHistoryService:
    """A service whose runner never shells out (the exec path stays deterministic)."""
    config = HttpHistoryConfig(store_root=str(tmp_path), **config_overrides)
    return HttpHistoryService(
        config=config,
        runner=lambda command, session_id, timeout_s, namespace=None: ExecOutcome(
            stdout="ok", stderr="", returncode=0, duration_ms=1
        ),
    )


def _frozen_clock(monkeypatch, start: float = 1000.0) -> dict:
    """Freeze the monotonic clock the storage-cap throttle reads."""
    clock = {"now": start}
    monkeypatch.setattr(service_module.time, "monotonic", lambda: clock["now"])
    return clock


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


def test_execute_enforces_the_byte_cap_throttled_per_project(tmp_path, monkeypatch):
    """§5.C: nothing called `enforce_limits` in production, so the store grew
    unbounded once capture was on by default. The exec path is the only place
    that sees every project, so it trims - at most once per project per
    interval, and never in a way the command can observe."""
    service = _quiet_service(tmp_path, project_max_bytes=1024, enforce_interval_s=60)
    clock = _frozen_clock(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        service, "enforce_limits",
        lambda project_id: calls.append(project_id) or {"artifacts_removed": 0},
    )

    for _ in range(3):
        result = service.execute("httpx -u 172.28.0.20", "s1", 5, project_id="proj-1")
        assert result["returncode"] == 0
    assert calls == ["proj-1"], calls

    clock["now"] += 61
    service.execute("httpx -u 172.28.0.20", "s1", 5, project_id="proj-1")
    assert calls == ["proj-1", "proj-1"], calls

    # A different project has its own budget: one project's heavy traffic must
    # not defer another's trim.
    service.execute("httpx -u 172.28.0.20", "s2", 5, project_id="proj-2")
    assert calls == ["proj-1", "proj-1", "proj-2"], calls


def test_execute_is_a_no_op_when_both_storage_limits_are_zero(tmp_path, monkeypatch):
    """Retention 0 and cap 0 mean "keep everything": the trimmer must not even
    be consulted, so the default deployment keeps every artifact."""
    service = _quiet_service(tmp_path, retention_s=0, project_max_bytes=0)
    _frozen_clock(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(service, "enforce_limits", lambda project_id: calls.append(project_id))

    service.execute("true", "s1", 5, project_id="proj-1")
    assert calls == []

    # A retention window alone still arms the trimmer (cap 0).
    service_retention = _quiet_service(tmp_path, retention_s=60, project_max_bytes=0)
    monkeypatch.setattr(
        service_retention, "enforce_limits",
        lambda project_id: calls.append(project_id) or {"artifacts_removed": 0},
    )
    service_retention.execute("true", "s1", 5, project_id="proj-1")
    assert calls == ["proj-1"]


def test_execute_storage_cap_is_best_effort(tmp_path, monkeypatch):
    """A trim failure must never fail, or even alter, the command result."""
    service = _quiet_service(tmp_path, project_max_bytes=1024)
    _frozen_clock(monkeypatch)

    def boom(project_id):
        raise OSError("disk busy")

    monkeypatch.setattr(service, "enforce_limits", boom)
    result = service.execute("true", "s1", 5, project_id="proj-1")
    assert result["stdout"] == "ok"
    assert result["returncode"] == 0


def test_execute_trims_the_real_store_when_the_cap_is_exceeded(tmp_path, monkeypatch):
    """End to end through the real store: the exec path is what actually evicts."""
    _seed(tmp_path)
    service = _service(tmp_path, project_max_bytes=1, enforce_interval_s=60)
    _frozen_clock(monkeypatch)
    service._runner = lambda command, session_id, timeout_s, namespace=None: ExecOutcome(
        stdout="ok", stderr="", returncode=0, duration_ms=1
    )

    service.execute("true", "s1", 5, project_id="proj-1")
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


def test_execute_forwards_private_stdin_to_a_stdin_aware_runner(tmp_path):
    """#238: the experiment spec (which carries the authenticated context)
    travels to the child on private stdin - never argv - and is not echoed
    back in the service envelope."""
    seen: dict[str, str] = {}

    def runner(command, session_id, timeout_s, namespace=None, stdin_text=""):
        seen["stdin_text"] = stdin_text
        return ExecOutcome(stdout="ok", stderr="", returncode=0, duration_ms=1)

    service = HttpHistoryService(
        config=HttpHistoryConfig(store_root=str(tmp_path)), runner=runner
    )
    result = service.execute(
        "vegeta attack", "s1", 5, stdin_text='{"Authorization":"Bearer supersecret"}'
    )

    assert seen["stdin_text"] == '{"Authorization":"Bearer supersecret"}'
    assert "supersecret" not in json.dumps(result)


def test_execute_keeps_a_legacy_runner_working(tmp_path):
    """Every pre-#238 runner takes four parameters; the new keyword must be
    forwarded only to a seam that declares it (signature-aware, the same guard
    `pod._accepts_capture_context` uses)."""
    seen: list[str] = []

    def legacy_runner(command, session_id, timeout_s, namespace=None):
        seen.append(command)
        return ExecOutcome(stdout="ok", stderr="", returncode=0, duration_ms=1)

    service = HttpHistoryService(
        config=HttpHistoryConfig(store_root=str(tmp_path)), runner=legacy_runner
    )
    result = service.execute("true", "s1", 5, stdin_text="ignored by a legacy seam")

    assert seen == ["true"]
    assert result["returncode"] == 0


# --- #238 Task 7: governed execution ---------------------------------------------

_POLICY = {
    "target_key": "app.example.com",
    "host_patterns": ["app.example.com"],
    "rate_per_s": 2.0,
    "burst": 1,
    "max_concurrency": 1,
    "min_delay_ms": 500.0,
    "source": "measured-transition",
    "version": "traffic-policy/v1",
}


class _Lease:
    namespace = "kali-http-0001"
    source_ip = "172.30.0.2"
    session_id = "s1"
    slot = 0


class _PolicyLeases:
    """A lease manager that carries the #238 policy (the production shape)."""

    def __init__(self, *, fail: bool = False):
        self.acquired: list[dict] = []
        self.released: list[object] = []
        self.fail = fail

    def acquire(self, *, session_id, project_id, context, traffic_policy=None):
        if self.fail:
            raise RuntimeError("pool exhausted")
        self.acquired.append(
            {
                "session_id": session_id,
                "project_id": project_id,
                "context": context,
                "traffic_policy": traffic_policy,
            }
        )
        return _Lease()

    def release(self, lease):
        self.released.append(lease)


class _LegacyLeases:
    """A pre-#238 lease manager: three kwargs, no policy channel."""

    def acquire(self, *, session_id, project_id, context):
        return _Lease()

    def release(self, lease):
        pass


def _probe(ok=True, detail="listening"):
    return lambda: {"ok": ok, "detail": detail}


def _governed_service(tmp_path, *, runner_calls, leases=None, proxy_ok=True, **config):
    def runner(command, session_id, timeout_s, namespace=None):
        runner_calls.append(command)
        return ExecOutcome(stdout="ok", stderr="", returncode=0, duration_ms=1)

    return HttpHistoryService(
        config=HttpHistoryConfig(store_root=str(tmp_path), **config),
        lease_manager=leases if leases is not None else _PolicyLeases(),
        runner=runner,
        proxy_probe=_probe(proxy_ok, "proxy not reachable" if not proxy_ok else "listening"),
    )


def test_an_armed_policy_is_registered_with_the_lease_and_the_command_runs(tmp_path):
    leases, calls = _PolicyLeases(), []
    service = _governed_service(tmp_path, runner_calls=calls, leases=leases)

    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy=_POLICY,
    )

    assert result["returncode"] == 0
    assert result["traffic_warning"] is None
    assert calls == ["httpx -u http://app.example.com"]
    assert leases.acquired[0]["traffic_policy"] == _POLICY
    assert leases.acquired[0]["project_id"] == "p1"
    assert leases.acquired[0]["context"].session_id == "s1"
    assert len(leases.released) == 1


def test_a_policy_is_registered_even_with_capture_disabled(tmp_path):
    """Capture and governance are separate switches: disabling the recording
    plane must not disarm an armed policy."""
    leases, calls = _PolicyLeases(), []
    service = _governed_service(
        tmp_path, runner_calls=calls, leases=leases, enabled=False
    )

    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy=_POLICY,
    )

    assert result["returncode"] == 0
    assert calls == ["httpx -u http://app.example.com"]
    assert leases.acquired[0]["traffic_policy"] == _POLICY


def test_an_armed_policy_without_a_lease_manager_refuses_without_running(tmp_path):
    calls: list[str] = []
    service = _governed_service(tmp_path, runner_calls=calls, leases=None)
    service.lease_manager = None

    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy=_POLICY,
    )

    assert result["returncode"] == 78
    assert result["stdout"] == ""
    assert calls == [], "an ungovernable policy must not run the command"
    assert "traffic_policy" not in json.dumps(result)
    assert "lease manager" in result["traffic_warning"]


def test_an_armed_policy_that_cannot_lease_refuses_without_running(tmp_path):
    calls: list[str] = []
    service = _governed_service(
        tmp_path, runner_calls=calls, leases=_PolicyLeases(fail=True)
    )

    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy=_POLICY,
    )

    assert result["returncode"] == 78
    assert calls == []
    assert "governor unavailable" in result["traffic_warning"]


def test_an_armed_policy_with_an_unhealthy_proxy_refuses_and_releases(tmp_path):
    calls, leases = [], _PolicyLeases()
    service = _governed_service(
        tmp_path, runner_calls=calls, leases=leases, proxy_ok=False
    )

    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy=_POLICY,
    )

    assert result["returncode"] == 78
    assert calls == []
    assert "proxy not reachable" in result["traffic_warning"]
    assert len(leases.released) == 1, "the namespace must not be leaked"


def test_an_armed_policy_with_governance_disabled_refuses(tmp_path):
    calls: list[str] = []
    service = _governed_service(
        tmp_path, runner_calls=calls, governor_enabled=False
    )
    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy=_POLICY,
    )
    assert result["returncode"] == 78
    assert calls == []
    assert "disabled" in result["traffic_warning"]


def test_an_unenforceable_policy_refuses_instead_of_running_ungoverned(tmp_path):
    calls: list[str] = []
    service = _governed_service(tmp_path, runner_calls=calls)
    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy={**_POLICY, "version": "traffic-policy/v2"},
    )
    assert result["returncode"] == 78
    assert calls == []
    assert "not enforceable" in result["traffic_warning"]


def test_a_policy_a_legacy_lease_manager_cannot_carry_refuses(tmp_path):
    calls: list[str] = []
    service = _governed_service(tmp_path, runner_calls=calls, leases=_LegacyLeases())
    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1",
        traffic_policy=_POLICY,
    )
    assert result["returncode"] == 78
    assert calls == []


def test_no_policy_keeps_the_legacy_fail_open_exec_path(tmp_path):
    calls: list[str] = []
    service = _governed_service(tmp_path, runner_calls=calls, leases=None)
    service.lease_manager = None

    result = service.execute("httpx -u http://app.example.com", "s1", 5, project_id="p1")

    assert result["returncode"] == 0
    assert result["traffic_warning"] is None
    assert calls == ["httpx -u http://app.example.com"]
    assert result["capture_warning"], "capture stays fail-open and loud"


def test_capture_without_a_policy_stays_fail_open(tmp_path):
    calls: list[str] = []
    service = _governed_service(
        tmp_path, runner_calls=calls, leases=_PolicyLeases(fail=True)
    )

    result = service.execute("httpx -u http://app.example.com", "s1", 5, project_id="p1")

    assert result["returncode"] == 0
    assert result["traffic_warning"] is None
    assert calls == ["httpx -u http://app.example.com"]
    assert "capture unavailable" in result["capture_warning"]


def test_an_empty_policy_payload_is_not_an_armed_policy(tmp_path):
    """`{}` is the transport default for "nothing attached", not a malformed
    budget: it keeps the pre-#238 path instead of refusing every command."""
    calls: list[str] = []
    service = _governed_service(tmp_path, runner_calls=calls, leases=None)
    service.lease_manager = None

    result = service.execute(
        "httpx -u http://app.example.com", "s1", 5, project_id="p1", traffic_policy={}
    )

    assert result["returncode"] == 0
    assert result["traffic_warning"] is None
    assert calls == ["httpx -u http://app.example.com"]
