"""The mitmproxy addon records correlated flows and never breaks the proxy."""
from __future__ import annotations

import asyncio

from kali.http_history.addon import UNSCOPED_PROJECT, HttpHistoryAddon
from kali.http_history.governor import GovernorDecision
from kali.http_history.models import CaptureContext
from kali.http_history.registry import SourceRegistration
from kali.http_history.store import HttpHistoryStore
from tests.kali.fakes import FakeError, FakeFlow, FakeMessage


class FakeResolver:
    def __init__(self, mapping):
        self.mapping = mapping

    def lookup(self, source_ip):
        return self.mapping.get(source_ip)


def _addon(tmp_path, resolver=None, **kwargs):
    return HttpHistoryAddon(root=tmp_path, resolver=resolver, **kwargs)


def test_response_hook_records_a_correlated_flow(tmp_path):
    resolver = FakeResolver(
        {"172.30.0.2": ("proj-1", CaptureContext(session_id="s1", exec_id="e1"))}
    )
    addon = _addon(tmp_path, resolver)
    addon.response(
        FakeFlow(
            request=FakeMessage(method="GET", url="https://target.example/a"),
            response=FakeMessage(status=200, reason="OK"),
        )
    )
    store = HttpHistoryStore(tmp_path, "proj-1")
    page = store.search(
        [{"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "GET"}]
    )
    assert len(page.artifacts) == 1
    assert page.artifacts[0].capture_context.exec_id == "e1"
    assert addon.status()["recorded"] == 1


def test_error_hook_records_an_incomplete_flow(tmp_path):
    resolver = FakeResolver({"172.30.0.2": ("proj-1", CaptureContext(exec_id="e1"))})
    addon = _addon(tmp_path, resolver)
    addon.error(FakeFlow(request=FakeMessage(), response=None, error=FakeError("reset")))
    artifact = HttpHistoryStore(tmp_path, "proj-1").search([]).artifacts[0]
    assert artifact.response is None
    assert artifact.error.message == "reset"


def test_uncorrelated_flow_lands_in_the_unscoped_bucket(tmp_path):
    addon = _addon(tmp_path, FakeResolver({}))
    addon.response(FakeFlow(response=FakeMessage(status=200, reason="OK")))
    assert HttpHistoryStore(tmp_path, UNSCOPED_PROJECT).search([]).artifacts
    assert HttpHistoryStore(tmp_path, "proj-1").search([]).artifacts == []


def test_store_failure_is_fail_open(tmp_path):
    class BoomStore(HttpHistoryStore):
        def record(self, *args, **kwargs):
            raise sqlite_error()

    def sqlite_error():
        import sqlite3

        return sqlite3.OperationalError("database is locked")

    addon = HttpHistoryAddon(
        root=tmp_path,
        resolver=FakeResolver({"172.30.0.2": ("proj-1", CaptureContext())}),
        store_factory=lambda project: BoomStore(tmp_path, project),
    )
    addon.response(FakeFlow(response=FakeMessage(status=200, reason="OK")))
    status = addon.status()
    assert status["failed"] == 1
    assert "OperationalError" in status["last_error"]


def test_disabled_addon_records_nothing(tmp_path):
    addon = _addon(
        tmp_path,
        FakeResolver({"172.30.0.2": ("proj-1", CaptureContext())}),
        enabled=False,
    )
    addon.response(FakeFlow(response=FakeMessage(status=200, reason="OK")))
    assert addon.status()["recorded"] == 0
    assert HttpHistoryStore(tmp_path, "proj-1").search([]).artifacts == []


def test_websocket_flows_are_excluded_and_disclosed(tmp_path):
    class WsFlow(FakeFlow):
        websocket = object()

    addon = _addon(
        tmp_path, FakeResolver({"172.30.0.2": ("proj-1", CaptureContext())})
    )
    addon.response(WsFlow(response=FakeMessage(status=101, reason="Switching Protocols")))
    assert addon.status()["recorded"] == 0
    assert addon.status()["excluded_websocket"] == 1


# --- #238 Task 7: the governance hook --------------------------------------------

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


class RecordingGovernor:
    def __init__(self, *, explode: bool = False):
        self.calls: list[tuple] = []
        self.explode = explode

    async def acquire(self, project_id, policy, request_host=None):
        self.calls.append((project_id, policy, request_host))
        if self.explode:
            raise RuntimeError("bucket exploded")
        return GovernorDecision(True, 0.0, policy["target_key"])


class RegistrationResolver(FakeResolver):
    """A resolver that serves the #238 registration alongside the legacy hit."""

    def __init__(self, registration=None):
        super().__init__({})
        self.registration = registration

    def lookup_registration(self, source_ip):
        return self.registration


def _governed_addon(tmp_path, *, governor=None, registration=None, **kwargs):
    return HttpHistoryAddon(
        root=tmp_path,
        resolver=RegistrationResolver(
            registration
            or SourceRegistration("proj-1", CaptureContext(exec_id="e1"), _POLICY)
        ),
        governor=governor or RecordingGovernor(),
        **kwargs,
    )


def test_the_request_hook_consumes_the_registered_policy(tmp_path):
    governor = RecordingGovernor()
    addon = _governed_addon(tmp_path, governor=governor)
    asyncio.run(addon.request(FakeFlow(request=FakeMessage(url="https://app.example.com/x"))))

    assert governor.calls == [("proj-1", _POLICY, "app.example.com")]
    assert addon.status()["governed"] == 1


def test_governance_off_leaves_the_request_hook_inert(tmp_path):
    governor = RecordingGovernor()
    addon = _governed_addon(tmp_path, governor=governor, governor_enabled=False)
    asyncio.run(addon.request(FakeFlow(request=FakeMessage(url="https://app.example.com/x"))))
    assert governor.calls == []


def test_an_unregistered_flow_is_not_governed(tmp_path):
    governor = RecordingGovernor()
    addon = HttpHistoryAddon(
        root=tmp_path, resolver=RegistrationResolver(None), governor=governor
    )
    asyncio.run(addon.request(FakeFlow(request=FakeMessage(url="https://app.example.com/x"))))
    assert governor.calls == []
    assert addon.status()["governed"] == 0


def test_capture_without_a_policy_is_never_governed(tmp_path):
    """A legacy registration (no policy) keeps today's behaviour exactly."""
    governor = RecordingGovernor()
    addon = _governed_addon(
        tmp_path,
        governor=governor,
        registration=SourceRegistration("proj-1", CaptureContext(exec_id="e1"), None),
    )
    asyncio.run(addon.request(FakeFlow(request=FakeMessage(url="https://app.example.com/x"))))
    assert governor.calls == []


def test_capture_and_governance_are_independent_switches(tmp_path):
    """Capture off must not disarm the governor, and governance off must not
    stop capture - the spec's Global Constraint, pinned at the addon."""
    governor = RecordingGovernor()
    capture_off = _governed_addon(tmp_path, governor=governor, enabled=False)
    flow = FakeFlow(
        request=FakeMessage(url="https://app.example.com/x"),
        response=FakeMessage(status=200, reason="OK"),
    )
    capture_off.response(flow)
    asyncio.run(capture_off.request(flow))
    assert capture_off.status()["recorded"] == 0
    assert len(governor.calls) == 1

    governance_off = _governed_addon(tmp_path, governor_enabled=False)
    governance_off.response(flow)
    asyncio.run(governance_off.request(flow))
    assert governance_off.status()["recorded"] == 1
    assert governor.calls == [("proj-1", _POLICY, "app.example.com")]


def test_a_governor_failure_never_breaks_the_proxy(tmp_path):
    addon = _governed_addon(tmp_path, governor=RecordingGovernor(explode=True))
    asyncio.run(addon.request(FakeFlow(request=FakeMessage(url="https://app.example.com/x"))))
    status = addon.status()
    assert status["governor_failed"] == 1
    assert "RuntimeError" in status["governor_last_error"]
