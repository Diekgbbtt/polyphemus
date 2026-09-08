"""Unit tier: the halt-everything teardown's fail-open external-client close (#211, TD-7).

The one persistent outbound handle at the app level is the neo4j driver (the LLM
gateway, Kali MCP, and lightrag clients are short-lived per-call HTTP). Its close
is fail-open and idempotent - teardown never raises on a close failure.
"""
import pytest


def test_neo4j_driver_close_is_fail_open_and_logged(monkeypatch, caplog):
    from polymerhus.app.clients import neo4j_client

    calls = []

    class _Fake:
        def close(self):
            calls.append(1)
            raise RuntimeError("boom")

    monkeypatch.setattr(neo4j_client, "_driver", _Fake())
    neo4j_client.close()          # must not raise
    assert calls == [1]
    assert any("neo4j driver close failed" in r.message for r in caplog.records)


def test_neo4j_driver_close_is_idempotent(monkeypatch):
    from polymerhus.app.clients import neo4j_client

    calls = []

    class _Fake:
        def close(self):
            calls.append(1)

    monkeypatch.setattr(neo4j_client, "_driver", _Fake())
    neo4j_client.close()
    neo4j_client.close()          # a second close never raises (the driver's own close is safe to repeat)
    assert calls == [1, 1]
