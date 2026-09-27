"""A governed command may legitimately run for many minutes - the MCP call that
carries it must survive that, and must never hang the pod.

Diagnosis (2026-09-27, `docs/superpowers/notes/2026-09-27-mcp-long-exec-verdict.md`):
`langchain-mcp-adapters` builds its streamable-HTTP client with
`httpx.Timeout(read=DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT)` - **300 s**. Once
enforcement made a real command longer than that, no event arrived inside the
window, the stream was torn down, the result was never delivered and the agent
waited forever. Same command, same stack, only `sse_read_timeout` changed:
default -> never returned in 780 s; `sse_read_timeout=1800` -> returned at 360 s.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from polymerhus.recon.domain import pod as pod_module
from polymerhus.recon.domain.pod import default_exec_fn


class _FakeTool:
    name = "execute_command"

    def __init__(self, *, hang: bool = False):
        self.hang = hang

    async def ainvoke(self, payload, config=None):
        if self.hang:
            await asyncio.sleep(3600)
        return SimpleNamespace(
            artifact={
                "structured_content": {
                    "stdout": "ok",
                    "stderr": "",
                    "returncode": 0,
                    "duration_ms": 1,
                }
            }
        )


class _FakeClient:
    captured: dict = {}
    hang: bool = False

    def __init__(self, servers):
        type(self).captured = servers

    async def get_tools(self):
        return [_FakeTool(hang=type(self).hang)]


def _install_fakes(monkeypatch, *, hang: bool = False) -> None:
    _FakeClient.hang = hang
    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient", _FakeClient
    )
    monkeypatch.setattr(
        "polymerhus.app.observability.get_langfuse_callbacks", lambda: []
    )


def test_the_stream_window_never_undercuts_the_library_default():
    derive = pod_module._mcp_sse_read_timeout_s

    assert derive(1800) > 1800.0, "the stream must outlive the command it carries"
    assert derive(5) >= 300.0, "never below the adapter's own default"
    assert derive(300) >= 300.0


def test_the_call_bound_exceeds_the_command_bound():
    limit = pod_module._mcp_call_timeout_s

    assert limit(1800) > 1800.0
    assert limit(300) > 300.0


def test_the_client_is_built_with_the_derived_stream_window(monkeypatch):
    _install_fakes(monkeypatch)

    result = default_exec_fn("true", "sess-1", 1800)

    assert result.returncode == 0
    config = _FakeClient.captured["kali"]
    assert config["transport"] == "streamable_http"
    assert config["sse_read_timeout"] == pod_module._mcp_sse_read_timeout_s(1800)


def test_a_lost_transport_fails_loud_instead_of_hanging(monkeypatch):
    """The whole point: a transport that never answers must become a STRUCTURED
    failure the pod can retry and degrade on - never an unbounded wait."""
    _install_fakes(monkeypatch, hang=True)
    monkeypatch.setattr(pod_module, "_mcp_call_timeout_s", lambda timeout_s: 0.1)

    started = time.monotonic()
    result = default_exec_fn("sleep 9999", "sess-1", 5)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"the call must be bounded, took {elapsed:.1f}s"
    assert result.returncode == 124
    assert "timed out" in result.stderr
    assert result.stdout == ""
