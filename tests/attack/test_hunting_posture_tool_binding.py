"""The posture tool is bound to the two agents that execute on Kali (Pod
Runner, Hunter) and NEVER to the Triager, which never touches the target."""
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


def test_triager_never_binds_the_posture_tool():
    tools = agents.triager_react_tools(
        memory_store=SimpleNamespace(), spec_id="s-1",
    )

    assert "rate_limit_posture" not in _names(tools)


def test_hunter_binds_the_posture_tool(monkeypatch):
    monkeypatch.setattr(hunter_tools, "_posture_tool", lambda project_id: _stub_tool())

    tools = hunter_tools.build_hunter_tools(project_id="proj-1")

    assert "rate_limit_posture" in _names(tools)
