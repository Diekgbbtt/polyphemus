"""Unit tier: the browser MCP server, its three tools, and its close hook.

The lease manager is a fake. The FastMCP client runs in memory, so no worker,
port, or Docker socket is needed. The middleware tests drive the ASGI app
directly, which is the one place the DELETE close signal enters.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kali.steel_pool.cli import CliError, RestoreError
from kali.steel_pool.lease import (
    EndReport,
    LeaseInUse,
    LeaseView,
    NoLease,
    PoolExhausted,
)
from kali.steel_pool.server import (
    BrowserServerConfig,
    BrowserService,
    CommandParseError,
    SessionCloseMiddleware,
    build_service,
    create_browser_mcp,
    parse_browser_command,
)
from kali.steel_pool.store import CorruptSessionRecord


class FakeManager:
    def __init__(self) -> None:
        self.started: list[tuple] = []
        self.execs: list[tuple] = []
        self.ends: list[str] = []
        self.closed: list[str] = []
        self.shutdowns = 0
        self.view = LeaseView(
            name="hunt",
            steel_session_id="steel-1",
            mcp_session_id="mcp-1",
            warnings=("a cookie attribute is not restorable",),
        )
        self.payload: dict = {"success": True, "data": {"title": "app"}}
        self.end_report = EndReport(
            ended=True,
            reason="explicit",
            captured=True,
            saved=True,
            stopped=True,
            released=None,
        )
        self.start_error: Exception | None = None
        self.exec_error: Exception | None = None
        self.end_error: Exception | None = None
        self.close_error: Exception | None = None
        self.shutdown_error: Exception | None = None

    def start(self, mcp_session_id: str, name: str, url: str | None = None):
        self.started.append((mcp_session_id, name, url))
        if self.start_error is not None:
            raise self.start_error
        return LeaseView(
            name=name,
            steel_session_id=self.view.steel_session_id,
            mcp_session_id=mcp_session_id,
            warnings=self.view.warnings,
        )

    def exec(self, mcp_session_id: str, args):
        self.execs.append((mcp_session_id, list(args)))
        if self.exec_error is not None:
            raise self.exec_error
        return self.payload

    def end(self, mcp_session_id: str, *, reason: str = "explicit"):
        self.ends.append(mcp_session_id)
        if self.end_error is not None:
            raise self.end_error
        return self.end_report

    def close_mcp_session(self, mcp_session_id: str):
        self.closed.append(mcp_session_id)
        if self.close_error is not None:
            raise self.close_error
        return EndReport(ended=True, reason="mcp_close")

    def shutdown(self):
        self.shutdowns += 1
        if self.shutdown_error is not None:
            raise self.shutdown_error
        return ()


class FakeApp:
    def __init__(self) -> None:
        self.scopes: list[dict] = []

    async def __call__(self, scope, receive, send) -> None:
        self.scopes.append(scope)
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        await send({"type": "http.response.body", "body": b"ok"})


def _events() -> tuple[list[tuple[str, dict]], callable]:
    events: list[tuple[str, dict]] = []

    def emit(event: str, **fields) -> None:
        events.append((event, fields))

    return events, emit


def _service(manager: FakeManager | None = None):
    events, emit = _events()
    return BrowserService(manager or FakeManager(), emit=emit), events


def _call(service: BrowserService, tool: str, *args):
    return getattr(service, tool)(*args)


def _run(coro):
    return asyncio.run(coro)


def _delete_scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "method": "DELETE",
        "path": "/mcp",
        "headers": headers,
    }


def _get_scope(method: str = "GET", path: str = "/mcp") -> dict:
    return {"type": "http", "method": method, "path": path, "headers": []}


class TestCommandGrammar:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("navigate https://app.test", ["navigate", "https://app.test"]),
            ("browser navigate https://app.test", ["navigate", "https://app.test"]),
            (
                "steel browser navigate https://app.test --json",
                ["navigate", "https://app.test"],
            ),
            ("snapshot -i", ["snapshot", "-i"]),
            (
                "fill '#user' -- 'a b'",
                ["fill", "#user", "--", "a b"],
            ),
            (
                "batch -- 'snapshot -i' 'click @e1'",
                ["batch", "--", "snapshot -i", "click @e1"],
            ),
            ("wait --selector '#app' --timeout 5000", ["wait", "--selector", "#app", "--timeout", "5000"]),
        ],
    )
    def test_parse_accepts_the_browser_grammar(self, command, expected):
        assert parse_browser_command(command) == expected

    @pytest.mark.parametrize(
        "command",
        [
            "",
            "   ",
            "start --session other",
            "stop -a",
            "sessions --json",
            "live",
            "navigate --session other https://app.test",
            "navigate --session=other https://app.test",
            "navigate --api-url http://worker:3000 https://app.test",
            "navigate --local https://app.test",
            "steel scrape https://app.test",
            "scrape https://app.test",
            "browser scrape https://app.test",
            "batch -- 'snapshot -i' 'stop'",
            "batch -- 'navigate --session other https://app.test'",
            "'unterminated",
        ],
    )
    def test_parse_rejects_session_ownership_and_bad_syntax(self, command):
        with pytest.raises(CommandParseError):
            parse_browser_command(command)

    def test_parse_rejects_a_non_string(self):
        with pytest.raises(CommandParseError):
            parse_browser_command(["navigate", "https://app.test"])


class TestBrowserService:
    def test_start_returns_the_name_and_session_id(self):
        service, _ = _service()

        result = service.start("mcp-1", "hunt", "https://app.test")

        assert result == {
            "success": True,
            "session": {"name": "hunt", "session_id": "steel-1"},
            "warnings": ["a cookie attribute is not restorable"],
        }

    def test_start_never_carries_the_worker(self):
        manager = FakeManager()
        service, _ = _service(manager)

        result = service.start("mcp-1", "hunt")

        body = json.dumps(result)
        assert "http://" not in body
        assert "localhost" not in body
        assert "container" not in body
        assert "worker" not in body.lower()

    def test_pool_exhausted_is_retryable(self):
        manager = FakeManager()
        manager.start_error = PoolExhausted("no worker")
        service, _ = _service(manager)

        result = _call(service, "start", "mcp-1", "hunt")

        assert result["success"] is False
        assert result["error"]["code"] == "pool_exhausted"
        assert result["error"]["retryable"] is True

    def test_duplicate_name_is_not_retryable(self):
        manager = FakeManager()
        manager.start_error = LeaseInUse("the browser session 'hunt' is mounted")
        service, _ = _service(manager)

        result = _call(service, "start", "mcp-2", "hunt")

        assert result["error"]["code"] == "session_in_use"
        assert result["error"]["retryable"] is False

    def test_restore_failure_is_typed(self):
        manager = FakeManager()
        manager.start_error = RestoreError("bad state")
        service, _ = _service(manager)

        result = _call(service, "start", "mcp-1", "hunt")

        assert result["error"]["code"] == "restore_failed"

    def test_invalid_name_is_typed(self):
        manager = FakeManager()
        manager.start_error = ValueError("the browser session name is invalid")
        service, _ = _service(manager)

        result = _call(service, "start", "mcp-1", "../escape")

        assert result["error"]["code"] == "invalid_argument"

    def test_store_error_is_typed(self):
        manager = FakeManager()
        manager.start_error = CorruptSessionRecord("broken record")
        service, _ = _service(manager)

        result = _call(service, "start", "mcp-1", "hunt")

        assert result["error"]["code"] == "store_error"

    def test_unexpected_start_error_is_contained(self):
        manager = FakeManager()
        manager.start_error = RuntimeError("boom")
        service, _ = _service(manager)

        result = _call(service, "start", "mcp-1", "hunt")

        assert result["error"]["code"] == "internal_error"
        assert "boom" in result["error"]["message"]

    def test_exec_passes_the_parsed_command_to_the_lease(self):
        manager = FakeManager()
        service, _ = _service(manager)

        result = service.exec("mcp-1", "steel browser click '#go' --json")

        assert result == {"success": True, "data": {"title": "app"}}
        assert manager.execs == [("mcp-1", ["click", "#go"])]

    def test_exec_without_a_lease_is_typed(self):
        manager = FakeManager()
        manager.exec_error = NoLease("no browser session")
        service, _ = _service(manager)

        result = service.exec("mcp-1", "snapshot -i")

        assert result["error"]["code"] == "no_session"
        assert result["error"]["recovery"] == "call_browser_start_first"

    def test_exec_transport_failure_is_typed(self):
        manager = FakeManager()
        manager.exec_error = CliError("the CLI timed out")
        service, _ = _service(manager)

        result = service.exec("mcp-1", "snapshot -i")

        assert result["error"]["code"] == "browser_error"
        assert result["error"]["retryable"] is True

    def test_exec_rejects_a_bad_command_before_the_lease(self):
        manager = FakeManager()
        service, _ = _service(manager)

        result = service.exec("mcp-1", "stop -a")

        assert result["error"]["code"] == "invalid_command"
        assert manager.execs == []

    def test_exec_returns_the_cli_envelope_unchanged(self):
        manager = FakeManager()
        manager.payload = {
            "success": False,
            "error": {"message": "Unknown ref: e9"},
        }
        service, _ = _service(manager)

        assert service.exec("mcp-1", "click @e9") == manager.payload

    def test_end_reports_the_capture_outcome(self):
        manager = FakeManager()
        service, _ = _service(manager)

        result = service.end("mcp-1")

        assert result == {
            "success": True,
            "ended": True,
            "reason": "explicit",
            "captured": True,
            "saved": True,
            "stopped": True,
            "released": None,
            "warnings": [],
        }

    def test_end_is_idempotent(self):
        manager = FakeManager()
        manager.end_report = EndReport(ended=False, reason="explicit")
        service, _ = _service(manager)

        result = service.end("mcp-1")

        assert result["success"] is True
        assert result["ended"] is False

    def test_close_session_never_raises(self):
        manager = FakeManager()
        manager.close_error = RuntimeError("boom")
        service, events = _service(manager)

        assert service.close_session("mcp-1") is None
        assert events[-1][0] == "session.close_error"

    def test_close_session_reports_the_release(self):
        manager = FakeManager()
        service, events = _service(manager)

        report = service.close_session("mcp-1")

        assert report is not None and report.reason == "mcp_close"
        assert manager.closed == ["mcp-1"]
        assert events[-1][0] == "session.close"

    def test_shutdown_ends_every_lease(self):
        manager = FakeManager()
        service, events = _service(manager)

        service.shutdown()

        assert manager.shutdowns == 1
        assert events[-1][0] == "server.shutdown"

    def test_shutdown_failure_is_contained(self):
        manager = FakeManager()
        manager.shutdown_error = RuntimeError("boom")
        service, events = _service(manager)

        assert service.shutdown() == ()
        assert events[-1][0] == "server.shutdown_error"


class TestFastMcpSurface:
    def _run(self, coroutine):
        return _run(coroutine)

    def test_tools_are_exactly_the_three(self):
        async def go():
            service, _ = _service()
            mcp = create_browser_mcp(service)
            from fastmcp import Client

            async with Client(mcp) as client:
                return await client.list_tools()

        tools = self._run(go())

        assert {tool.name for tool in tools} == {
            "browser_start",
            "browser_exec",
            "browser_end",
        }

    def test_no_status_pool_or_owner_tool_exists(self):
        async def go():
            service, _ = _service()
            mcp = create_browser_mcp(service)
            from fastmcp import Client

            async with Client(mcp) as client:
                return await client.list_tools()

        names = {tool.name for tool in self._run(go())}

        assert "browser_status" not in names
        assert "pool_status" not in names
        assert "release_owner" not in names

    def test_start_exec_end_share_the_mcp_session_id(self):
        async def go():
            manager = FakeManager()
            service, _ = _service(manager)
            mcp = create_browser_mcp(service)
            from fastmcp import Client

            async with Client(mcp) as client:
                started = await client.call_tool("browser_start", {"name": "hunt"})
                executed = await client.call_tool(
                    "browser_exec", {"command": "snapshot -i"}
                )
                ended = await client.call_tool("browser_end", {})
                return manager, started, executed, ended

        manager, started, executed, ended = self._run(go())

        assert started.data["success"] is True
        assert executed.data == {"success": True, "data": {"title": "app"}}
        assert ended.data["ended"] is True
        mcp_ids = {manager.started[0][0], manager.execs[0][0], manager.ends[0]}
        assert len(mcp_ids) == 1
        assert mcp_ids.pop()

    def test_start_result_keeps_the_worker_obscure(self):
        async def go():
            service, _ = _service()
            mcp = create_browser_mcp(service)
            from fastmcp import Client

            async with Client(mcp) as client:
                return await client.call_tool(
                    "browser_start", {"name": "hunt", "url": "https://app.test"}
                )

        result = self._run(go())

        body = json.dumps(result.data)
        assert "3110" not in body
        assert "container" not in body
        assert "worker" not in body.lower()

    def test_start_error_is_a_structured_envelope(self):
        async def go():
            manager = FakeManager()
            manager.start_error = PoolExhausted("no worker")
            service, _ = _service(manager)
            mcp = create_browser_mcp(service)
            from fastmcp import Client

            async with Client(mcp) as client:
                return await client.call_tool("browser_start", {"name": "hunt"})

        result = self._run(go())

        assert result.data["success"] is False
        assert result.data["error"]["code"] == "pool_exhausted"
        assert result.is_error is False

    def test_lifespan_shutdown_releases_every_lease(self):
        async def go():
            manager = FakeManager()
            service, _ = _service(manager)
            mcp = create_browser_mcp(service)
            from fastmcp import Client

            async with Client(mcp):
                pass
            return manager

        manager = self._run(go())

        assert manager.shutdowns == 1

    def test_exec_rejects_a_session_flag(self):
        async def go():
            manager = FakeManager()
            service, _ = _service(manager)
            mcp = create_browser_mcp(service)
            from fastmcp import Client

            async with Client(mcp) as client:
                return await client.call_tool(
                    "browser_exec",
                    {"command": "navigate --session other https://app.test"},
                )

        result = self._run(go())

        assert result.data["error"]["code"] == "invalid_command"
        assert result.is_error is False


class TestSessionCloseMiddleware:
    def test_delete_releases_the_session(self):
        service, _ = _service()
        app = FakeApp()
        wrapped = SessionCloseMiddleware(app, service)
        messages: list[dict] = []

        async def go():
            await wrapped(
                _delete_scope([(b"mcp-session-id", b"session-abc")]),
                _receive,
                _send(messages),
            )

        _run(go())

        assert service._manager.closed == ["session-abc"]
        assert len(app.scopes) == 1
        assert messages[-1]["type"] == "http.response.body"

    def test_delete_without_a_session_header_is_ignored(self):
        service, _ = _service()
        app = FakeApp()
        wrapped = SessionCloseMiddleware(app, service)

        async def go():
            await wrapped(_delete_scope([]), _receive, _send([]))

        _run(go())

        assert service._manager.closed == []
        assert len(app.scopes) == 1

    def test_other_methods_do_not_release(self):
        service, _ = _service()
        app = FakeApp()
        wrapped = SessionCloseMiddleware(app, service)

        async def go():
            await wrapped(_get_scope("GET"), _receive, _send([]))
            await wrapped(_get_scope("POST"), _receive, _send([]))

        _run(go())

        assert service._manager.closed == []
        assert len(app.scopes) == 2

    def test_a_delete_on_another_path_is_ignored(self):
        service, _ = _service()
        app = FakeApp()
        wrapped = SessionCloseMiddleware(app, service)

        async def go():
            await wrapped(
                _delete_scope([(b"mcp-session-id", b"session-abc")]) | {"path": "/other"},
                _receive,
                _send([]),
            )

        _run(go())

        assert service._manager.closed == []
        assert len(app.scopes) == 1

    def test_a_close_failure_does_not_break_the_response(self):
        service, events = _service()
        service._manager.close_error = RuntimeError("boom")
        app = FakeApp()
        wrapped = SessionCloseMiddleware(app, service)

        async def go():
            await wrapped(
                _delete_scope([(b"mcp-session-id", b"session-abc")]),
                _receive,
                _send([]),
            )

        _run(go())

        assert events[-1][0] == "session.close_error"


async def _receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


def _send(messages: list[dict]):
    async def send(message: dict) -> None:
        messages.append(message)

    return send


class TestConfig:
    class _BootDocker:
        def __init__(self, payload=None):
            self.payload = payload or []
            self.calls = []

        def get_json(self, path: str, query: dict | None = None):
            self.calls.append((path, query))
            return self.payload

    def _files(self, tmp_path: Path):
        socket_path = tmp_path / "docker.sock"
        socket_path.write_text("")
        cli = tmp_path / "steel"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o700)
        guard = tmp_path / "steel_guard.py"
        guard.write_text("# guard\n")
        guard.chmod(0o700)
        store = tmp_path / "sessions"
        store.mkdir(mode=0o700)
        return socket_path, cli, guard, store

    def _env(self, tmp_path: Path) -> dict:
        socket_path, cli, guard, store = self._files(tmp_path)
        return {
            "STEEL_POOL_DOCKER_SOCKET": str(socket_path),
            "STEEL_SESSION_STORE": str(store),
            "STEEL_CLI": str(cli),
            "STEEL_GUARD": str(guard),
        }

    def test_defaults(self, tmp_path):
        config = BrowserServerConfig.from_env(self._env(tmp_path))

        assert config.port == 8003
        assert config.mcp_path == "/mcp"
        assert config.pool_label == "polymerhus.steel-pool=true"
        assert config.pool_size == 4
        assert config.worker_host == "localhost"
        assert config.pool_wait_s == pytest.approx(30.0)
        assert config.heartbeat_s == pytest.approx(120.0)
        assert config.lease_ttl_s == pytest.approx(600.0)
        assert config.worker_api_suffix == "/v1"

    def test_reads_the_deployment_values(self, tmp_path):
        env = self._env(tmp_path)
        env.update(
            {
                "STEEL_MCP_PORT": "9003",
                "STEEL_POOL_LABEL": "pool=one",
                "STEEL_POOL_SIZE": "2",
                "STEEL_WORKER_HOST": "host.docker.internal",
                "STEEL_POOL_WAIT_S": "5",
                "STEEL_POOL_HEALTH_S": "3",
                "STEEL_HEARTBEAT_S": "60",
                "STEEL_LEASE_TTL_S": "300",
                "STEEL_CLI_TIMEOUT_S": "120",
                "STEEL_WORKER_API_SUFFIX": "",
                "STEEL_MCP_PATH": "/browser",
            }
        )

        config = BrowserServerConfig.from_env(env)

        assert config.port == 9003
        assert config.pool_label == "pool=one"
        assert config.pool_size == 2
        assert config.worker_host == "host.docker.internal"
        assert config.pool_wait_s == pytest.approx(5.0)
        assert config.health_timeout_s == pytest.approx(3.0)
        assert config.heartbeat_s == pytest.approx(60.0)
        assert config.lease_ttl_s == pytest.approx(300.0)
        assert config.cli_timeout_s == pytest.approx(120.0)
        assert config.worker_api_suffix == ""
        assert config.mcp_path == "/browser"

    def test_missing_socket_fails_loud(self, tmp_path):
        env = self._env(tmp_path)
        del env["STEEL_POOL_DOCKER_SOCKET"]

        with pytest.raises(ValueError, match="STEEL_POOL_DOCKER_SOCKET"):
            BrowserServerConfig.from_env(env)

    def test_nonexistent_socket_fails_loud(self, tmp_path):
        env = self._env(tmp_path)
        env["STEEL_POOL_DOCKER_SOCKET"] = str(tmp_path / "missing.sock")

        with pytest.raises(ValueError, match="does not exist"):
            BrowserServerConfig.from_env(env)

    def test_missing_store_fails_loud(self, tmp_path):
        env = self._env(tmp_path)
        del env["STEEL_SESSION_STORE"]

        with pytest.raises(ValueError, match="STEEL_SESSION_STORE"):
            BrowserServerConfig.from_env(env)

    def test_missing_cli_fails_loud(self, tmp_path):
        env = self._env(tmp_path)
        del env["STEEL_CLI"]

        with pytest.raises(ValueError, match="STEEL_CLI"):
            BrowserServerConfig.from_env(env)

    def test_non_executable_guard_fails_loud(self, tmp_path):
        env = self._env(tmp_path)
        Path(env["STEEL_GUARD"]).chmod(0o600)

        with pytest.raises(ValueError, match="STEEL_GUARD"):
            BrowserServerConfig.from_env(env)

    def test_invalid_numbers_fail_loud(self, tmp_path):
        env = self._env(tmp_path)
        env["STEEL_POOL_SIZE"] = "zero"

        with pytest.raises(ValueError, match="STEEL_POOL_SIZE"):
            BrowserServerConfig.from_env(env)

    def test_invalid_suffix_fails_loud(self, tmp_path):
        env = self._env(tmp_path)
        env["STEEL_WORKER_API_SUFFIX"] = "/v2"

        with pytest.raises(ValueError, match="suffix"):
            BrowserServerConfig.from_env(env)

    def test_invalid_worker_host_fails_loud(self, tmp_path):
        env = self._env(tmp_path)
        env["STEEL_WORKER_HOST"] = "http://worker"

        with pytest.raises(ValueError, match="worker host"):
            BrowserServerConfig.from_env(env)

    def test_build_service_wires_the_manager(self, tmp_path):
        config = BrowserServerConfig.from_env(self._env(tmp_path))

        service = build_service(
            config,
            docker_client=self._BootDocker(),
            emit=lambda event, **fields: None,
        )

        assert isinstance(service, BrowserService)
        manager = service._manager
        assert manager._store.root == Path(config.session_store)
        assert manager._ttl_s == pytest.approx(600.0)
        assert manager._registry._label == config.pool_label

    def test_build_service_discovers_and_probes_the_pool_at_boot(self, tmp_path):
        config = BrowserServerConfig.from_env(self._env(tmp_path))
        docker = self._BootDocker(
            [
                {
                    "Id": "a",
                    "Names": ["/steel-1"],
                    "Ports": [
                        {
                            "IP": "127.0.0.1",
                            "PrivatePort": 3000,
                            "PublicPort": 59999,
                            "Type": "tcp",
                        }
                    ],
                }
            ]
        )
        events = []

        service = build_service(
            config,
            docker_client=docker,
            emit=lambda event, **fields: events.append((event, fields)),
        )

        assert docker.calls
        assert service._manager._registry.report is not None
        assert [event for event, _ in events][0] == "pool.discovered"
        assert events[0][1]["discovered"] == 1
