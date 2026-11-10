"""Task 5 deterministic acceptance for streaming, refinement and hunting order."""

from __future__ import annotations

import asyncio
import copy

from langchain_core.messages import HumanMessage

from polymerhus.analysis import lifecycle
from polymerhus.analysis.analyser_types import (
    L1DeltaBatch,
    SystemEdgeProposal,
    SystemProposal,
)
from polymerhus.analysis.assigner import assign
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.feed import L0Chunk, QueuedAnalysisFeed
from polymerhus.analysis.js_context_application import (
    JsContextApplicationTracker,
)
from polymerhus.analysis.mechanism_typist import type_mechanisms
from polymerhus.analysis.messages import StepReceipt
from polymerhus.app.js_context.selection import publication_input
from polymerhus.app.js_context.store import JsContextStore
from polymerhus.app.js_context.tool import build_js_context_tool
from tests.app.test_js_context_store import _document, _context_id


def test_analysis_and_js_settle_before_hunting_planning_with_zero_candidates(
    monkeypatch,
):
    early_entered = asyncio.Event()
    release_early = asyncio.Event()
    js_passed = asyncio.Event()
    order = []
    launch_calls = []

    async def consume(chunk):
        from polymerhus.analysis.supervisor import PassCensus, PassResult

        if chunk.job == "katana":
            order.append("analysis:early:start")
            early_entered.set()
            await release_early.wait()
            order.append("analysis:early:end")
        elif chunk.js_context_input is not None:
            assert chunk.assets == []
            order.append("analysis:js")
            js_passed.set()
            return PassResult(
                export=None,
                census=PassCensus(
                    dispatches_entered=2,
                    unprocessed_after=0,
                    js_context_status="settled_success",
                    terminal=chunk.terminal,
                ),
            )
        return PassResult(
            export=None,
            census=PassCensus(
                dispatches_entered=1,
                unprocessed_after=0,
                terminal=chunk.terminal,
            ),
        )

    selection = publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "published",
            "context_id": "jsctx_" + "a" * 40,
            "document_id": "document-1",
            "document_sha256": "b" * 64,
        },
    )

    async def scenario():
        feed = QueuedAnalysisFeed(
            "project-a",
            "run-1",
            pass_fn=consume,
        ).start()
        await feed.push(
            L0Chunk(
                project_id="project-a",
                run_id="run-1",
                job="katana",
            )
        )
        await early_entered.wait()
        order.append("producer:js")
        release_early.set()
        await feed.push(
            L0Chunk(
                project_id="project-a",
                run_id="run-1",
                job="js_analysis",
                js_context_input=selection,
            )
        )
        await js_passed.wait()
        assert launch_calls == []
        await feed.signal_end()
        stats = await feed.wait_until_done()
        assert stats.analysis_drained is True
        return stats

    async def fake_launch(project_id, body):
        launch_calls.append((project_id, body))
        return {"hunting_run_id": "hunt-1"}

    import polymerhus.attack.hunting.runtime as hunting_runtime
    import polymerhus.project_management.api as pm_api
    import polymerhus.app.clients.pg as pg

    async def inline_to_thread(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)
    monkeypatch.setattr(pg, "run_has_js_analysis", lambda run_id: True)
    monkeypatch.setattr(
        hunting_runtime,
        "hunting_control_plane_available",
        lambda: True,
    )
    monkeypatch.setattr(pm_api, "launch_hunting", fake_launch)

    asyncio.run(
        _ordering_scenario(
            scenario,
            project_id="project-a",
            run_id="run-1",
        )
    )

    assert order == [
        "analysis:early:start",
        "producer:js",
        "analysis:early:end",
        "analysis:js",
    ]
    assert launch_calls[0][1].producing_run_id == "run-1"


async def _ordering_scenario(scenario, *, project_id, run_id):
    await scenario()
    await lifecycle._chain_hunting_on_drained(
        project_id,
        run_id,
        "drained",
        enabled=True,
    )


def test_supported_js_refinement_reaches_the_existing_writer_boundary(
    tmp_path,
):
    document = copy.deepcopy(
        _document(project_id="project-a", run_id="run-1")
    )
    document["behaviors"][0]["question"] = (
        "How does the client guard a protected route?"
    )
    document["behaviors"][0]["steps"][0]["text"] = (
        "router.beforeEach calls requireAuth, reads localStorage and sends "
        "axios requests with credentials."
    )
    published = JsContextStore(root_dir=tmp_path).publish(document)
    selection = publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "published",
            "context_id": _context_id(document),
            "document_id": "document-1",
            "document_sha256": published["document_sha256"],
            "auth_ref": document["context"]["auth_ref"],
            "origin": document["context"]["origin"],
        },
    )
    tool = build_js_context_tool(
        project_id="project-a",
        store=JsContextStore(root_dir=tmp_path),
        selection=selection,
    )
    chunk = Chunk(
        chunk_id="js_analysis:0",
        source_job="js_analysis",
        js_context_input=selection,
    )
    l1 = {
        "system_details": {
            "AuthenticationMechanism": "client route gate incomplete"
        },
        "edges": [],
    }

    def read_behaviors():
        result = tool.invoke(
            {
                "command": "read",
                "context_id": selection.context_id,
                "selector": "current",
                "section": "behaviors",
            }
        )
        assert result["ok"] is True
        assert result["items"]
        return result["items"]

    def assign_invoke(messages, **kwargs):
        assert read_behaviors()
        return L1DeltaBatch()

    stage = {"n": 0}

    def typist_invoke(messages, *, schema=None, **kwargs):
        if schema is None:
            behaviors = read_behaviors()
            assert "localStorage" in behaviors[0]["steps"][0]["text"]
            return "The client guard and request construction are supported."
        stage["n"] += 1
        if stage["n"] == 1:
            return L1DeltaBatch(
                systems=[
                    SystemProposal(
                        kind="AuthenticationMechanism",
                        props={
                            "description": (
                                "client router guard using requireAuth, "
                                "localStorage and credentialed axios requests"
                            )
                        },
                    )
                ]
            )
        return L1DeltaBatch(
            system_edges=[
                SystemEdgeProposal(
                    service_slug="app",
                    kind="AuthenticationMechanism",
                    rel="AUTHENTICATED_BY",
                )
            ]
        )

    assign(
        chunk,
        invoke_fn=assign_invoke,
        inventory={"services": ["app"], "systems": []},
    )
    batch = type_mechanisms(
        chunk,
        invoke_fn=typist_invoke,
        inventory={
            "services": ["app"],
            "systems": ["AuthenticationMechanism"],
            "system_descriptions": l1["system_details"],
        },
        aggregations=[],
    )

    def existing_writer_boundary(value):
        for system in value.systems:
            l1["system_details"][system.kind] = system.props["description"]
        for edge in value.system_edges:
            l1["edges"].append(
                (edge.service_slug, edge.kind, edge.rel)
            )

    existing_writer_boundary(batch)

    def hunting_observer():
        return (
            l1["system_details"]["AuthenticationMechanism"],
            l1["edges"],
        )

    detail, edges = hunting_observer()
    assert "router guard" in detail
    assert "credentialed axios" in detail
    assert ("app", "AuthenticationMechanism", "AUTHENTICATED_BY") in edges


def test_unresolved_contradiction_remains_an_explicit_hunting_gap():
    selection = publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "published",
            "context_id": "jsctx_" + "a" * 40,
            "document_id": "document-1",
            "document_sha256": "b" * 64,
            "gaps": ["contradiction_unresolved"],
        },
    )
    tracker = JsContextApplicationTracker(selection)
    for role in ("assigner", "mechanism_typist"):
        tracker.observe_turn(role, [])
        tracker.observe_receipts(
            [
                StepReceipt(
                    dispatch_id=role,
                    role=role,
                    phase="A1",
                    status="empty",
                )
            ]
        )
    # Mark real reads separately from dispatch; the contradiction still settles
    # as a gap rather than becoming graph consistency.
    from langchain_core.messages import ToolMessage
    import json

    for role in ("assigner", "mechanism_typist"):
        tracker.observe_turn(
            role,
            [
                ToolMessage(
                    content=json.dumps(
                        {
                            "ok": True,
                            "js_context_binding": {
                                "input_id": selection.input_id
                            },
                        }
                    ),
                    name="js_context",
                    tool_call_id=f"read-{role}",
                )
            ],
        )
    summary = tracker.settle()

    assert summary["status"] == "settled_gap"
    assert "contradiction_unresolved" in summary["gaps"]
