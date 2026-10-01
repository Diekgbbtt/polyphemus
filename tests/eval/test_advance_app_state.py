"""Unit tests for the eval idle proxy (`eval/advance/app_state.py`).

The proxy reads the instance-wide running state from #265's `GET /app-state`
surface and falls back to the documented direct-postgres query when the API is
unreachable. Both transports are injected; the module imports without I/O and
never imports a database driver (stdlib only, so the fallback shells out).
"""
from __future__ import annotations

import json

import pytest

from advance import app_state


def test_http_idle_is_returned_from_the_endpoint() -> None:
    seen: list[str] = []

    def transport(url: str):
        seen.append(url)
        return 200, json.dumps({"idle": True, "projects": []})

    proxy = app_state.IdleProxy("http://agent.invalid:8000", http_transport=transport)

    result = proxy.fetch()

    assert result.idle is True
    assert result.projects == ()
    assert seen == ["http://agent.invalid:8000/app-state"]


def test_busy_state_is_not_idle_and_carries_projects() -> None:
    def transport(url: str):
        return 200, json.dumps(
            {"idle": False, "projects": [{"project_id": "p1", "in_flight": True}]}
        )

    proxy = app_state.IdleProxy("http://agent.invalid:8000/app-state", http_transport=transport)

    result = proxy.fetch()

    assert result.idle is False
    assert result.projects == ({"project_id": "p1", "in_flight": True},)


def test_unreachable_api_falls_back_to_the_dsn_and_empty_rows_mean_idle() -> None:
    def failing_http(url: str):
        raise OSError("connection refused")

    dsn_calls: list[str] = []

    def dsn_transport(dsn: str) -> str:
        dsn_calls.append(dsn)
        return ""

    proxy = app_state.IdleProxy(
        "http://agent.invalid:8000",
        dsn="postgresql://example/db",
        http_transport=failing_http,
        dsn_transport=dsn_transport,
    )

    assert proxy.is_idle() is True
    assert dsn_calls == ["postgresql://example/db"]


def test_dsn_rows_mean_not_idle() -> None:
    def dsn_transport(dsn: str) -> str:
        return "recon|r1|p1\n"

    proxy = app_state.IdleProxy(
        "http://agent.invalid:8000",
        dsn="postgresql://example/db",
        http_transport=lambda url: (_ for _ in ()).throw(OSError("down")),
        dsn_transport=dsn_transport,
    )

    assert proxy.is_idle() is False


def test_non_200_and_invalid_json_also_fall_back() -> None:
    cases = [
        (503, "service unavailable"),
        (200, "not json"),
        (200, json.dumps({"projects": []})),
    ]
    for status, body in cases:
        proxy = app_state.IdleProxy(
            "http://agent.invalid:8000",
            dsn="postgresql://example/db",
            http_transport=lambda url, status=status, body=body: (status, body),
            dsn_transport=lambda dsn: "",
        )
        assert proxy.is_idle() is True, (status, body)


def test_both_transports_failing_is_unavailable_not_idle() -> None:
    proxy = app_state.IdleProxy(
        "http://agent.invalid:8000",
        dsn="postgresql://example/db",
        http_transport=lambda url: (_ for _ in ()).throw(OSError("down")),
        dsn_transport=lambda dsn: (_ for _ in ()).throw(RuntimeError("psql missing")),
    )

    with pytest.raises(app_state.AppStateUnavailable):
        proxy.fetch()


def test_http_without_a_dsn_is_unavailable() -> None:
    proxy = app_state.IdleProxy(
        "http://agent.invalid:8000",
        http_transport=lambda url: (_ for _ in ()).throw(OSError("down")),
    )

    with pytest.raises(app_state.AppStateUnavailable):
        proxy.fetch()


def test_fallback_query_matches_the_documented_predicate() -> None:
    query = app_state.FALLBACK_QUERY
    assert "recon_runs" in query and "status = 'running'" in query
    assert "analysis_runs" in query and "status = 'draining'" in query
    assert "hunting_runs" in query and "status = 'running'" in query
    assert query.rstrip().endswith(";")


def test_psql_command_carries_the_dsn_and_query() -> None:
    args = app_state.psql_command("postgresql://example/db")
    assert args[0] == "psql"
    assert "postgresql://example/db" in args
    assert app_state.FALLBACK_QUERY in args


def test_default_dsn_transport_runs_psql_and_returns_stdout() -> None:
    from advance.images import CommandResult

    seen: list[list[str]] = []

    def run(args):
        seen.append(list(args))
        return CommandResult(0, "recon|r1|p1\n")

    out = app_state.default_dsn_transport("postgresql://example/db", run=run)

    assert out == "recon|r1|p1\n"
    assert seen[0][0] == "psql"


def test_endpoint_appends_app_state_exactly_once() -> None:
    assert app_state.app_state_endpoint("http://h:8000") == "http://h:8000/app-state"
    assert (
        app_state.app_state_endpoint("http://h:8000/")
        == "http://h:8000/app-state"
    )
    assert (
        app_state.app_state_endpoint("http://h:8000/app-state")
        == "http://h:8000/app-state"
    )
