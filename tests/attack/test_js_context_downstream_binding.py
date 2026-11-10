"""Deterministic downstream binding proof for the six approved roles."""

from __future__ import annotations

import asyncio
import ast
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

import polymerhus.app.data_root as data_root_module
from polymerhus.app.js_context.selection import publication_input
from polymerhus.app.js_context.store import JsContextStore
from tests.app.test_js_context_store import _context_id, _document


PROJECT_A = "project-a"
PROJECT_B = "project-b"


def _publish_project(
    root,
    project_id: str,
    *,
    run_ids=("run-1",),
) -> str:
    store = JsContextStore(root_dir=root)
    document = None
    for run_id in run_ids:
        document = _document(project_id=project_id, run_id=run_id)
        store.publish(document)
    return _context_id(document)


@pytest.fixture
def published_root(tmp_path, monkeypatch):
    monkeypatch.setattr(data_root_module, "DATA_ROOT", tmp_path)
    contexts = {
        project: _publish_project(
            tmp_path,
            project,
            run_ids=(
                ("run-1", "run-2")
                if project == PROJECT_A
                else ("run-3", "run-4")
            ),
        )
        for project in (PROJECT_A, PROJECT_B)
    }
    return tmp_path, contexts


def _js_tools(tools):
    return [tool for tool in tools if getattr(tool, "name", "") == "js_context"]


def _published_runs(result: dict) -> set[str]:
    return {
        item["run_id"]
        for item in result.get("publications") or []
    }


def _selection(root, project_id: str, run_id: str):
    document = _document(project_id=project_id, run_id=run_id)
    published = JsContextStore(root_dir=root).publish(document)
    return publication_input(
        project_id=project_id,
        producing_run_id=run_id,
        publication={
            "status": "published",
            "context_id": _context_id(document),
            "document_id": "document-1",
            "document_sha256": published["document_sha256"],
            "auth_ref": document["context"]["auth_ref"],
            "origin": document["context"]["origin"],
        },
    )


def test_analysis_proposers_bind_one_real_project_tool_each(
    published_root,
    monkeypatch,
):
    from polymerhus.analysis.analyser_types import L1DeltaBatch
    from polymerhus.analysis import proposer_turn
    import polymerhus.app.llm.session as session

    _, contexts = published_root
    seen = []

    def fake_turn(role_id, address, messages, **kwargs):
        seen.append((role_id, kwargs.get("tools") or ()))
        return None

    monkeypatch.setattr(session, "stateful_turn", fake_turn)
    for role_id in ("assigner", "mechanism_typist"):
        for project in (PROJECT_A, PROJECT_B):
            invoke = proposer_turn.session_invoke_fn(
                role_id,
                "run-analysis",
                object(),
                project_id=project,
            )
            invoke(
                [HumanMessage(content="task")],
                schema=L1DeltaBatch,
            )
            tools = _js_tools(seen[-1][1])
            assert len(tools) == 1
            listed = tools[0].invoke({"command": "list"})
            assert listed["ok"] is True
            expected_runs = (
                {"run-1", "run-2"}
                if project == PROJECT_A
                else {"run-3", "run-4"}
            )
            assert _published_runs(listed) == expected_runs
            expected_current = sorted(expected_runs)[-1]
            assert tools[0].invoke(
                {
                    "command": "read",
                    "context_id": contexts[project],
                    "selector": "current",
                    "section": "metadata",
                }
            )["publication"]["run_id"] == expected_current
            assert tools[0].invoke(
                {
                    "command": "read",
                    "context_id": "jsctx_" + "0" * 40,
                    "selector": "current",
                }
            ) == {"ok": False, "error": "missing"}

        invoke = proposer_turn.session_invoke_fn(
            role_id,
            "run-unscoped",
            object(),
        )
        invoke([HumanMessage(content="task")], schema=L1DeltaBatch)
        assert _js_tools(seen[-1][1]) == []


def test_hunting_threat_modeller_surface_binds_and_executes_reader(
    published_root,
):
    pytest.importorskip("cvss", reason="candidate runtime dependency is absent")
    from polymerhus.app.js_context.tool import build_js_context_tool
    from polymerhus.attack.hunting.threat_modeller_tools import (
        ModellerTools,
        build_modeller_tool_surface,
    )

    root, contexts = published_root
    selection = _selection(root, PROJECT_A, "run-1")
    tools = ModellerTools(
        project_id=PROJECT_A,
        run_id="run-hunt",
        js_context_tool=build_js_context_tool(
            project_id=PROJECT_A,
            store=JsContextStore(root_dir=root),
            selection=selection,
        ),
    )
    surface = {
        tool.name: tool
        for tool in build_modeller_tool_surface(
            PROJECT_A,
            "Service:slug:a",
            tools,
        ).values()
    }

    assert len(_js_tools(list(surface.values()))) == 1
    listed = surface["js_context"].invoke({"command": "list"})
    assert _published_runs(listed) == {"run-1"}
    historical = surface["js_context"].invoke(
        {
            "command": "read",
            "context_id": contexts[PROJECT_A],
            "selector": "run-1",
            "section": "behaviors",
        }
    )
    assert historical["items"][0]["behavior_id"] == "behavior_a"
    assert "js_context" in surface


def test_hunter_declares_and_executes_the_same_reader(
    published_root,
    monkeypatch,
):
    pytest.importorskip("cvss", reason="candidate runtime dependency is absent")
    from polymerhus.attack.hunting import hunting_agent
    import polymerhus.app.llm.session as session

    _, contexts = published_root
    calls = []
    cursor = {"index": 0}

    async def fake_turn(
        role_id,
        thread_id,
        messages,
        *,
        tools=(),
        **kwargs,
    ):
        calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "system_prompt": kwargs.get("system_prompt"),
            }
        )
        if cursor["index"] == 0:
            cursor["index"] = 1
            reply = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "js_context",
                        "args": {"command": "list"},
                        "id": "js-1",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            reply = AIMessage(content="done")
        return session.SessionTurn(
            content=str(reply.content or ""),
            messages=[reply],
            thread_id=thread_id,
        )

    monkeypatch.setattr(session, "arun_session_turn", fake_turn)

    async def direct_to_thread(fn, *args):
        return fn(*args)

    monkeypatch.setattr(asyncio, "to_thread", direct_to_thread)
    from polymerhus.attack.hunting.js_context_admission import (
        js_context_selection_scope,
    )

    selection = _selection(published_root[0], PROJECT_A, "run-1")
    dispatch = hunting_agent.build_hunting_agent(
        run_id="run-hunt",
        project_id=PROJECT_A,
        checkpointer=InMemorySaver(),
        middleware=[],
        observe=False,
        overview_fn=lambda _: "",
    )
    payload = {
        "dispatch_id": "Service:slug:a__threat-1",
        "threat_id": "threat-1",
        "unit_id": "Service:slug:a",
        "target_context": {},
    }
    with js_context_selection_scope(selection):
        result = asyncio.run(dispatch(payload))

    declared = {
        item["function"]["name"]
        for item in calls[0]["tools"]
    }
    assert "js_context" in declared
    feedback_messages = calls[1]["messages"]
    assert len(feedback_messages) == 1
    assert isinstance(feedback_messages[0], ToolMessage)
    payload = ast.literal_eval(feedback_messages[0].content)
    assert _published_runs(payload) == {"run-1"}
    assert result["state"] == "grounding"
    assert "done" in result["feedback"]


def _pod_hc(tmp_path, *, project_id):
    from polymerhus.attack.hunting.pod.context import ExperimentLog
    from polymerhus.attack.hunting.pod.llm import PodHarnessContext
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
    from polymerhus.recon.domain.types import ExecResult

    def exec_fn(command, timeout_s):
        return ExecResult(returncode=0)

    return PodHarnessContext(
        exec_fn=exec_fn,
        memory_store=PodMemoryStore(tmp_path),
        spec_id="fault_strategy",
        log=ExperimentLog(),
        variant_ref="v0",
        project_id=project_id,
        capture_context=None,
    )


def test_pod_runner_and_triager_execute_reader_without_capture_context(
    published_root,
    monkeypatch,
):
    from polymerhus.attack.hunting.pod import agents, llm
    import polymerhus.app.llm.session as session
    from polymerhus.attack.hunting.pod.agents import TriagerDecision
    from polymerhus.attack.hunting.js_context_admission import (
        js_context_selection_scope,
    )

    root, contexts = published_root
    selection = _selection(root, PROJECT_A, "run-1")
    seen = {}

    async def fake_runner_turn(role_id, address, messages, **kwargs):
        seen["runner"] = list(kwargs.get("tools") or [])
        return session.SessionTurn(content="done", messages=[], thread_id=address.thread_id)

    monkeypatch.setattr(session, "arun_session_turn", fake_runner_turn)
    hc = _pod_hc(root, project_id=PROJECT_A)
    assert hc.capture_context is None

    async def run_runner():
        with js_context_selection_scope(selection):
            with llm.bind_pod_session(
                "run-pod",
                "",
                hc.spec_id,
                role_id=llm.POD_RUNNER_ROLE,
                harness=hc,
            ):
                return await agents.default_runner_step_fn({}, [], 0)

    asyncio.run(run_runner())
    runner_js = _js_tools(seen["runner"])
    assert len(runner_js) == 1
    assert _published_runs(runner_js[0].invoke({"command": "list"})) == {"run-1"}

    def fake_triager_turn(role_id, address, messages, **kwargs):
        seen["triager"] = list(kwargs.get("tools") or [])
        return TriagerDecision()

    monkeypatch.setattr(session, "stateful_turn", fake_triager_turn)

    async def run_triager():
        with js_context_selection_scope(selection):
            with llm.bind_pod_session(
                "run-pod",
                "",
                hc.spec_id,
                role_id=llm.POD_TRIAGER_ROLE,
                harness=hc,
            ):
                return await agents.default_triager_fn(
                    {},
                    None,
                    [{"role": "human", "content": "triager delta"}],
                    hc.log,
                )

    asyncio.run(run_triager())
    triager_js = _js_tools(seen["triager"])
    assert len(triager_js) == 1
    assert triager_js[0].invoke(
        {
            "command": "read",
            "context_id": contexts[PROJECT_A],
            "selector": "run-1",
            "section": "behaviors",
        }
    )["items"][0]["revision"] == 1


def test_capture_project_metadata_cannot_supply_missing_tool_project(tmp_path):
    from polymerhus.attack.hunting.pod.agents import (
        runner_react_tools,
        triager_react_tools,
    )
    from polymerhus.attack.hunting.pod.context import ExperimentLog
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
    from polymerhus.recon.domain.types import CaptureContext, ExecResult

    def exec_fn(command, timeout_s):
        return ExecResult(returncode=0)

    store = PodMemoryStore(tmp_path)
    capture = CaptureContext(project_id=PROJECT_A)
    runner = runner_react_tools(
        exec_fn,
        store,
        "fault_strategy",
        ExperimentLog(),
        "v0",
        capture_context=capture,
        project_id="",
    )
    triager = triager_react_tools(
        store,
        "fault_strategy",
        project_id="",
    )

    assert _js_tools(runner) == []
    assert _js_tools(triager) == []


def test_all_served_role_prompts_receive_the_identical_cortex_once(
    published_root,
    monkeypatch,
):
    from polymerhus.analysis import proposer_turn
    from polymerhus.attack.hunting import cortex, hunting_agent
    from polymerhus.attack.hunting.llm import _modeller_skill
    from polymerhus.attack.hunting.pod.prompts import (
        load_pod_runner_skill,
        load_pod_triager_skill,
    )
    import polymerhus.app.llm.session as session

    architecture = cortex.cognitive_architecture_map()
    assert "Target surface" in architecture
    assert "A domain that is unavailable" in architecture
    assert "js_context" not in architecture
    for contract_marker in ("list/read", "cursor", "16 KiB"):
        assert contract_marker not in architecture

    captured = []

    def fake_turn(role_id, address, messages, **kwargs):
        captured.append(kwargs["system_prompt"])
        return None

    monkeypatch.setattr(session, "stateful_turn", fake_turn)
    custom = "CUSTOM ROLE PROMPT"
    for role_id in ("assigner", "mechanism_typist"):
        invoke = proposer_turn.session_invoke_fn(
            role_id,
            f"run-cortex-{role_id}",
            object(),
            project_id=PROJECT_A,
        )
        invoke([HumanMessage(content="one")], schema=None, system_prompt=custom)
        invoke([HumanMessage(content="two")], schema=None, system_prompt=custom)
    for index in range(0, len(captured), 2):
        assert captured[index].startswith(custom)
        assert captured[index].count(architecture) == 1
        assert captured[index] == captured[index + 1]

    prompts = [
        _modeller_skill(),
        hunting_agent._load_hunting_agent_skill(),
        load_pod_runner_skill(),
        load_pod_triager_skill(),
    ]
    for prompt in prompts:
        assert prompt.count(architecture) == 1
        assert prompt.rstrip().endswith(architecture)

    once = cortex.with_cortex(f"BASE\n\n{architecture}")
    assert once == f"BASE\n\n{architecture}"


def test_missing_cortex_map_fails_closed(monkeypatch, tmp_path):
    from polymerhus.attack.hunting import cortex

    monkeypatch.setattr(cortex, "_MAP", None)
    monkeypatch.setattr(
        cortex.Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing")),
    )
    with pytest.raises(OSError):
        cortex.cognitive_architecture_map()


def test_deferred_roles_and_js_specialist_do_not_receive_js_context(
    published_root,
):
    from polymerhus.analysis import proposer_turn

    assert proposer_turn._surface_tools("sweep", PROJECT_A) == ()


def test_js_specialist_still_receives_only_exec(tmp_path):
    from polymerhus.recon.js_intake import issue_js_intake_reference
    from polymerhus.recon.js_specialist.agent import build_js_specialist

    seen = {}
    reference = issue_js_intake_reference(
        "project-js",
        "run-js",
        context_ref="alice",
    )

    async def reconcile(**_kwargs):
        return {
            "status": "no_work",
            "retry_attempts": 0,
            "maintenance_execs": 0,
            "gaps": [],
        }

    async def session(role_id, address, messages, **kwargs):
        seen["role_id"] = role_id
        seen["tools"] = [tool.name for tool in kwargs["tools"]]
        return SimpleNamespace(content="done", blackloop=False)

    dispatch = build_js_specialist(
        root=tmp_path,
        session_fn=session,
        checkpointer=object(),
        middleware=[],
        retention_reconcile_fn=reconcile,
    )
    result = asyncio.run(
        dispatch(
            project_id="project-js",
            run_id="run-js",
            reference=reference,
            auth_context_label="authenticated",
            auth_context_ref="alice",
        )
    )

    assert result["coverage"] == "partial"
    assert seen == {
        "role_id": "js_specialist",
        "tools": ["exec"],
    }
