"""One frozen JS selection reaches every hunting executor path."""

from __future__ import annotations

import pytest

import polymerhus.app.data_root as data_root_module
from polymerhus.attack.hunting.js_context_admission import (
    js_context_selection_scope,
)
from polymerhus.app.js_context.selection import publication_input
from polymerhus.app.js_context.store import JsContextStore
from tests.app.test_js_context_store import _document


def _selection(tmp_path):
    first = _document(project_id="project-a", run_id="run-1")
    published = JsContextStore(root_dir=tmp_path).publish(first)
    JsContextStore(root_dir=tmp_path).publish(
        _document(project_id="project-a", run_id="run-2")
    )
    return publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "published",
            "context_id": published["context_id"],
            "document_id": "document-1",
            "document_sha256": published["document_sha256"],
            "auth_ref": first["context"]["auth_ref"],
            "origin": first["context"]["origin"],
        },
    )


def test_modeller_hunter_and_both_pod_roles_use_the_frozen_selection(
    tmp_path, monkeypatch
):
    pytest.importorskip("cvss", reason="candidate runtime dependency is absent")
    from polymerhus.app.js_context.tool import build_js_context_tool
    from polymerhus.attack.hunting.threat_modeller_tools import (
        ModellerTools,
        build_modeller_tool_surface,
    )
    from polymerhus.attack.hunting.hunter_tools import build_hunter_tools
    from polymerhus.attack.hunting.pod.agents import (
        runner_react_tools,
        triager_react_tools,
    )
    from polymerhus.attack.hunting.pod.context import ExperimentLog
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
    from polymerhus.recon.domain.types import ExecResult

    monkeypatch.setattr(data_root_module, "DATA_ROOT", tmp_path)
    selection = _selection(tmp_path)

    def exec_fn(command, timeout_s):
        return ExecResult(returncode=0)

    def graph_read(cypher, params):
        return []

    with js_context_selection_scope(selection):
        js_tool = build_js_context_tool(
            project_id="project-a",
            selection=selection,
        )
        modeller = {
            tool.name: tool
            for tool in build_modeller_tool_surface(
                "project-a",
                "Service:slug:a",
                ModellerTools(
                    project_id="project-a",
                    run_id="hunt-1",
                    js_context_tool=js_tool,
                ),
            ).values()
        }
        hunter = {
            tool.name: tool
            for tool in build_hunter_tools(
                project_id="project-a",
                js_context_tool=js_tool,
            )
        }
        runner = {
            tool.name: tool
            for tool in runner_react_tools(
                exec_fn,
                PodMemoryStore(tmp_path),
                "fault_strategy",
                ExperimentLog(),
                "v0",
                graph_view_fn=graph_read,
                project_id="project-a",
            )
        }
        triager = {
            tool.name: tool
            for tool in triager_react_tools(
                PodMemoryStore(tmp_path),
                "fault_strategy",
                graph_view_fn=graph_read,
                project_id="project-a",
            )
        }

    for surface in (modeller, hunter, runner, triager):
        result = surface["js_context"].invoke(
            {
                "command": "read",
                "context_id": selection.context_id,
                "selector": "current",
                "section": "metadata",
            }
        )
        assert result["ok"] is True
        assert result["selector"]["run_id"] == "run-1"
        binding = result["js_context_binding"]
        assert binding["input_id"] == selection.input_id
        assert binding["project_id"] == "project-a"
        assert binding["producing_run_id"] == "run-1"
        assert binding["context_id"] == selection.context_id
        assert binding["document_id"] == "document-1"
        assert binding["document_sha256"] == selection.document_sha256
        assert binding["auth_ref"] == selection.auth_ref
        assert binding["origin"] == selection.origin.as_dict()
