"""Seam under test: the crawl's MCP browser client.

The unit tier injects a fake async MCP client; the contract tier runs the real
streamable-HTTP protocol against a real FastMCP server. No Steel worker and no
Docker socket are needed.
"""
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Mapping

import pytest

from polymerhus.recon.crawl.steel.mcp_client import (
    BrowserUnavailable,
    McpBackend,
    McpBrowserClient,
    McpBrowserError,
    McpStart,
)
from polymerhus.recon.crawl.steel.session import (
    CommandFailed,
    InvalidCommand,
    SessionMissing,
    SessionStillLive,
    SessionTaken,
    TargetLost,
)

START_RESULT = {
    "success": True,
    "session": {"name": "steel-proj", "session_id": "steel-1"},
    "warnings": ["a cookie attribute is not restorable"],
    "restored": {
        "cookies": 2,
        "origins": 1,
        "storage_keys": 3,
        "warnings": [],
    },
    "cdp_url": "ws://172.20.0.5:3000/",
    "cdp_host": "localhost:3000",
    "remaining_ms": 900_000,
}


class FakeToolResult:
    def __init__(self, data: Mapping | None, *, is_error: bool = False) -> None:
        self.data = dict(data) if data is not None else None
        self.is_error = is_error
        self.content = []


class FakeClient:
    def __init__(self, results: dict[str, list[object]]) -> None:
        self._results = {name: list(values) for name, values in results.items()}
        self.calls: list[tuple[str, dict]] = []
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.exited = True
        return None

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, dict(arguments)))
        value = self._results[name].pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _client(results: dict[str, list[object]]) -> tuple[McpBrowserClient, FakeClient]:
    fake = FakeClient(results)
    client = McpBrowserClient(
        "http://browser.invalid/mcp",
        client_factory=lambda: fake,
        timeout_s=2.0,
    )
    return client, fake


def test_start_maps_the_restore_and_cdp_contract():
    client, fake = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_end": [FakeToolResult({"success": True, "stopped": True})],
        }
    )

    start = client.start("steel-proj")
    client.close()

    assert start == McpStart(
        name="steel-proj",
        session_id="steel-1",
        restored={"cookies": 2, "origins": 1, "storage_keys": 3, "warnings": []},
        cdp_url="ws://172.20.0.5:3000/",
        cdp_host="localhost:3000",
        warnings=("a cookie attribute is not restorable",),
        remaining_ms=900_000,
    )
    assert fake.calls == [
        ("browser_start", {"name": "steel-proj"}),
    ]
    assert fake.entered is True
    assert fake.exited is True


def test_start_maps_the_session_model_fields():
    result = dict(
        START_RESULT,
        role="member",
        root_url="http://app.test/index/user/index.html",
        auth_probe="http://app.test/index/user/index.html",
    )
    client, _ = _client({"browser_start": [FakeToolResult(result)]})

    start = client.start("hunt")
    client.close()

    assert start.role == "member"
    assert start.root_url == "http://app.test/index/user/index.html"
    assert start.auth_probe == "http://app.test/index/user/index.html"


def test_backend_start_result_carries_the_session_model_fields():
    result = dict(
        START_RESULT,
        role="member",
        root_url="http://app.test/index/user/index.html",
        auth_probe="http://app.test/index/user/index.html",
    )
    client, _ = _client({"browser_start": [FakeToolResult(result)]})
    backend = McpBackend(client)

    start = backend.start("hunt")
    backend.close()

    assert start.role == "member"
    assert start.root_url == "http://app.test/index/user/index.html"
    assert start.auth_probe == "http://app.test/index/user/index.html"


def test_start_reports_the_mounted_context_not_the_requested_one():
    result = dict(START_RESULT, context_ref="steel-auth-proj-1-alice")
    client, _ = _client({"browser_start": [FakeToolResult(result)]})

    start = client.start("hunt", context_ref="steel-auth-proj-1-bob")
    client.close()

    assert start.context_ref == "steel-auth-proj-1-alice"


def test_start_reports_an_anonymous_mount_when_the_server_has_no_context():
    result = dict(START_RESULT, context_ref=None)
    client, _ = _client({"browser_start": [FakeToolResult(result)]})

    start = client.start("hunt", context_ref="steel-auth-proj-1-bob")
    client.close()

    assert start.context_ref is None


def test_start_requires_the_cdp_endpoint():
    result = dict(START_RESULT)
    result.pop("cdp_url")
    client, _ = _client({"browser_start": [FakeToolResult(result)]})

    with pytest.raises(McpBrowserError):
        client.start("steel-proj")
    client.close()


def test_pool_exhaustion_is_a_retryable_browser_unavailable():
    client, _ = _client(
        {
            "browser_start": [
                FakeToolResult(
                    {
                        "success": False,
                        "error": {
                            "code": "pool_exhausted",
                            "message": "no worker",
                            "retryable": True,
                        },
                    }
                )
            ]
        }
    )

    with pytest.raises(BrowserUnavailable):
        client.start("steel-proj")
    client.close()


def test_restore_failure_is_typed():
    from polymerhus.recon.crawl.steel.session import RestoreFailed

    client, _ = _client(
        {
            "browser_start": [
                FakeToolResult(
                    {
                        "success": False,
                        "error": {"code": "restore_failed", "message": "bad state"},
                    }
                )
            ]
        }
    )

    with pytest.raises(RestoreFailed):
        client.start("steel-proj")
    client.close()


def test_exec_sends_one_shell_quoted_command_string():
    client, fake = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_exec": [
                FakeToolResult({"success": True, "data": {"title": "app"}})
            ],
            "browser_end": [FakeToolResult({"success": True, "stopped": True})],
        }
    )
    client.start("steel-proj")

    envelope = client.exec(["fill", "#user", "--", "a b"])

    assert envelope == {"success": True, "data": {"title": "app"}}
    assert fake.calls[1] == (
        "browser_exec",
        {"command": "fill '#user' -- 'a b'"},
    )
    client.close()


def test_no_session_maps_to_session_missing():
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_exec": [
                FakeToolResult(
                    {
                        "success": False,
                        "error": {"code": "no_session", "message": "no lease"},
                    }
                )
            ],
        }
    )
    client.start("steel-proj")

    with pytest.raises(SessionMissing):
        client.exec(["snapshot", "-i"])
    client.close()


def test_session_in_use_maps_to_session_taken():
    client, _ = _client(
        {
            "browser_start": [
                FakeToolResult(
                    {
                        "success": False,
                        "error": {
                            "code": "session_in_use",
                            "message": "mounted elsewhere",
                        },
                    }
                )
            ]
        }
    )

    with pytest.raises(SessionTaken):
        client.start("steel-proj")
    client.close()


def test_a_cli_error_envelope_keeps_its_typed_code():
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_exec": [
                FakeToolResult(
                    {
                        "success": False,
                        "error": {
                            "code": "target_lost",
                            "message": "the target disappeared",
                        },
                    }
                )
            ],
        }
    )
    client.start("steel-proj")

    with pytest.raises(TargetLost):
        client.exec(["snapshot", "-i"])
    client.close()


def test_an_unknown_error_code_is_command_failed():
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_exec": [
                FakeToolResult(
                    {
                        "success": False,
                        "error": {"code": "mystery", "message": "?"},
                    }
                )
            ],
        }
    )
    client.start("steel-proj")

    with pytest.raises(CommandFailed):
        client.exec(["snapshot", "-i"])
    client.close()


def test_invalid_command_is_typed():
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_exec": [
                FakeToolResult(
                    {
                        "success": False,
                        "error": {"code": "invalid_command", "message": "no"},
                    }
                )
            ],
        }
    )
    client.start("steel-proj")

    with pytest.raises(InvalidCommand):
        client.exec(["start"])
    client.close()


def test_a_transport_failure_is_browser_unavailable():
    client, _ = _client(
        {"browser_start": [ConnectionError("the server is gone")]}
    )

    with pytest.raises(BrowserUnavailable):
        client.start("steel-proj")
    client.close()


def test_end_reports_a_live_session_as_still_live():
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_end": [
                FakeToolResult(
                    {
                        "success": False,
                        "ended": True,
                        "stopped": False,
                        "released": None,
                        "error": {
                            "code": "browser_error",
                            "message": "neither",
                        },
                    }
                )
            ],
        }
    )
    client.start("steel-proj")

    with pytest.raises(SessionStillLive):
        client.end()
    client.close()


def test_a_second_end_is_an_idempotent_success():
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_end": [
                FakeToolResult(
                    {"success": True, "ended": False, "stopped": False}
                )
            ],
        }
    )
    client.start("steel-proj")

    result = client.end()

    assert result["ended"] is False
    assert result["success"] is True
    client.close()


def test_an_already_gone_session_is_not_still_live():
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_end": [
                FakeToolResult(
                    {
                        "success": False,
                        "ended": True,
                        "stopped": False,
                        "released": False,
                        "error": {
                            "code": "browser_error",
                            "message": "already gone",
                        },
                    }
                )
            ],
        }
    )
    client.start("steel-proj")

    result = client.end()

    assert result["released"] is False
    client.close()


def test_end_returns_the_capture_report():
    report = {
        "success": True,
        "ended": True,
        "reason": "explicit",
        "captured": True,
        "saved": True,
        "stopped": True,
        "released": None,
        "warnings": [],
    }
    client, _ = _client(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_end": [FakeToolResult(report)],
        }
    )
    client.start("steel-proj")

    assert client.end() == report
    client.close()


def test_every_server_error_code_is_typed_on_the_crawl_side():
    import ast
    from pathlib import Path

    from polymerhus.recon.crawl.steel.mcp_client import MCP_ERROR_TYPES
    from polymerhus.recon.crawl.steel.session import CLI_ERROR_TYPES

    source = (
        Path(__file__).resolve().parents[4]
        / "kali"
        / "steel_pool"
        / "server.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    codes = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "error_envelope"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            codes.add(node.args[0].value)

    assert codes
    assert codes <= set(MCP_ERROR_TYPES) | set(CLI_ERROR_TYPES)


def test_close_is_idempotent_and_before_open():
    client, fake = _client({})

    client.close()
    client.close()

    assert fake.entered is False


def test_the_session_client_uses_the_mcp_backend_end_to_end():
    from polymerhus.recon.crawl.steel.session import InvalidCommand, SteelSessionClient

    fake = FakeClient(
        {
            "browser_start": [FakeToolResult(START_RESULT)],
            "browser_exec": [
                FakeToolResult({"success": True, "data": {"title": "app"}})
            ],
            "browser_end": [
                FakeToolResult({"success": True, "ended": True, "saved": True})
            ],
        }
    )
    session = SteelSessionClient.from_mcp(
        "http://browser.invalid/mcp", client_factory=lambda: fake
    )

    attached = session.attach("steel-proj")
    assert session.cdp_endpoint == ("ws://172.20.0.5:3000/", "localhost:3000")
    envelope = session.execute("eval", "1+1")
    report = session.stop()

    assert attached.session_id == "steel-1"
    assert envelope == {"success": True, "data": {"title": "app"}}
    assert fake.calls[1] == ("browser_exec", {"command": "eval 1+1"})
    assert report.saved is True
    assert session.attached is None
    session.close()

    with pytest.raises(InvalidCommand):
        fake_backend = McpBackend(McpBrowserClient("http://browser.invalid/mcp"))
        fake_backend.command("start", "x")
        fake_backend.close()


# --- the real streamable-HTTP protocol contract --------------------------------


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_the_client_speaks_the_real_mcp_protocol():
    from fastmcp import FastMCP

    mcp = FastMCP("contract")

    @mcp.tool()
    def browser_start(name: str, url: str | None = None) -> dict:
        return {
            "success": True,
            "session": {"name": name, "session_id": "steel-contract"},
            "warnings": [],
            "restored": {"cookies": 0, "origins": 0, "storage_keys": 0, "warnings": []},
            "cdp_url": "ws://172.20.0.5:3000/",
            "cdp_host": "localhost:3000",
        }

    @mcp.tool()
    def browser_exec(command: str) -> dict:
        return {"success": True, "data": {"command": command}}

    @mcp.tool()
    def browser_end() -> dict:
        return {"success": True, "stopped": True, "saved": True}

    import uvicorn

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    client = McpBrowserClient(f"http://127.0.0.1:{port}/mcp", timeout_s=10)
    try:
        start = client.start("steel-contract")
        assert start.session_id == "steel-contract"
        assert start.cdp_host == "localhost:3000"
        assert client.exec(["eval", "1+1"])["data"] == {"command": "eval 1+1"}
        assert client.end()["saved"] is True
    finally:
        client.close()
        server.should_exit = True
        thread.join(timeout=10)
