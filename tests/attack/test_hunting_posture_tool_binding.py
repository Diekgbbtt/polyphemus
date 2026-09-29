"""Where the `rate_limit_posture` read is bound (operator ruling, 2026-09-28).

The posture is readable ONLY inside the **test-executor pod**: the Runner
(where the traffic decision is actually made) and the Triager (which judges
what the Runner did). The **Hunter does NOT bind it**.

This supersedes the #238 follow-up spec section 11, which bound the tool to the
Pod Runner and the Hunter and excluded the Triager - the read moved into the pod
and away from the hunting agent.
"""
from langchain_core.tools import BaseTool
from types import SimpleNamespace

from polymerhus.attack.hunting import hunter_tools
from polymerhus.attack.hunting.pod import agents


def _stub_tool() -> BaseTool:
    class _Stub(BaseTool):
        name: str = "rate_limit_posture"
        description: str = "stub"

        def _run(self, *args, **kwargs):  # pragma: no cover - binding only
            return ""

    return _Stub()


def _names(tools) -> set[str]:
    return {getattr(tool, "name", "") for tool in tools}


def test_runner_binds_the_posture_tool(monkeypatch):
    monkeypatch.setattr(agents, "_posture_tool", lambda project_id: _stub_tool())

    tools = agents.runner_react_tools(
        exec_fn=None, memory_store=SimpleNamespace(), spec_id="s-1",
        log=None, variant_ref="", project_id="proj-1",
    )

    assert "rate_limit_posture" in _names(tools)


def test_triager_binds_the_posture_tool(monkeypatch):
    monkeypatch.setattr(agents, "_posture_tool", lambda project_id: _stub_tool())

    tools = agents.triager_react_tools(
        memory_store=SimpleNamespace(), spec_id="s-1", project_id="proj-1",
    )

    assert "rate_limit_posture" in _names(tools)


def test_the_hunter_never_binds_the_posture_tool():
    tools = hunter_tools.build_hunter_tools(project_id="proj-1")

    assert "rate_limit_posture" not in _names(tools)
