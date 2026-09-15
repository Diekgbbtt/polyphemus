"""Exec-tool trace metadata (#226).

The Kali exec tool is invoked on a worker thread (`run_coro_blocking`) with a
fresh LangChain config, so it never inherits the graph run's metadata. The
execute node therefore publishes the pod's trace metadata
(`langfuse_session_id` / `langfuse_tags`) on a ContextVar, and
`default_exec_fn` attaches it to the tool config - where the attributing
handler turns it into session/tags on the tool span. No metadata, no run
context: the config stays callbacks-only, exactly as today.
"""
import asyncio
import sys
import types
from types import SimpleNamespace

from polymerhus.recon.domain import pod
from polymerhus.recon.domain.types import JobSpec


def _job(tool="whois"):
    return JobSpec(tool=tool, skill="s", command_template="t",
                   produces=[], consumes="Subdomain")


def test_exec_trace_metadata_present_with_run_context():
    md = pod.exec_trace_metadata(
        {"run_id": "run-1", "phase": 2, "job": _job("whois")})
    assert md["langfuse_session_id"] == "run-1"
    assert md["langfuse_tags"] == ["recon", "pod", "whois"]


def test_exec_trace_metadata_absent_without_run_context():
    assert pod.exec_trace_metadata({}) is None
    assert pod.exec_trace_metadata({"run_id": None}) is None


def _install_exec_fakes(monkeypatch, seen):
    class _FakeTool:
        name = "execute_command"

        async def ainvoke(self, payload, config=None):
            seen["config"] = config
            return SimpleNamespace(
                artifact={"stdout": "ok", "stderr": "",
                          "returncode": 0, "duration_ms": 1},
                content="ok",
            )

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def get_tools(self):
            return [_FakeTool()]

    fake_mod = types.ModuleType("langchain_mcp_adapters.client")
    fake_mod.MultiServerMCPClient = _FakeClient
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake_mod)
    monkeypatch.setitem(
        sys.modules, "langchain_mcp_adapters",
        types.ModuleType("langchain_mcp_adapters"))

    import polymerhus.app.config as app_config
    monkeypatch.setattr(app_config, "config",
                        SimpleNamespace(KALI_MCP_URL="http://kali.invalid"))
    import polymerhus.recon.control.async_bridge as bridge
    monkeypatch.setattr(bridge, "run_coro_blocking",
                        lambda coro: asyncio.run(coro))
    import polymerhus.app.observability as obs
    monkeypatch.setattr(obs, "get_langfuse_callbacks", lambda: [])


def test_default_exec_fn_attaches_trace_metadata_when_published(monkeypatch):
    seen = {}
    _install_exec_fakes(monkeypatch, seen)
    token = pod.trace_metadata_ctx().set(
        {"langfuse_session_id": "run-1", "langfuse_tags": ["recon"]})
    try:
        result = pod.default_exec_fn("whois x", "sess", 5)
    finally:
        pod.trace_metadata_ctx().reset(token)

    assert result.returncode == 0
    assert seen["config"]["metadata"] == {
        "langfuse_session_id": "run-1", "langfuse_tags": ["recon"]}


def test_default_exec_fn_config_stays_callbacks_only_without_metadata(monkeypatch):
    seen = {}
    _install_exec_fakes(monkeypatch, seen)
    pod.default_exec_fn("whois x", "sess", 5)

    assert seen["config"] == {"callbacks": []}
