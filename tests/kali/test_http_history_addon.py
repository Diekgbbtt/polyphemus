"""The mitmproxy addon records correlated flows and never breaks the proxy."""
from __future__ import annotations

from kali.http_history.addon import UNSCOPED_PROJECT, HttpHistoryAddon
from kali.http_history.models import CaptureContext
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
