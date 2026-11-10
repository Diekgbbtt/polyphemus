"""Deterministic Analysis integration for one frozen JS publication."""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.feed import L0Chunk, QueuedAnalysisFeed
from polymerhus.analysis.js_context_application import (
    JsContextApplicationTracker,
)
from polymerhus.analysis.messages import StepReceipt
from polymerhus.analysis.proposer_turn import proposer_batch, session_invoke_fn
from polymerhus.analysis.supervisor import analyse_chunked
from polymerhus.app.js_context.selection import publication_input
from polymerhus.app.js_context.store import JsContextStore
from polymerhus.app.js_context.tool import build_js_context_tool
from tests.app.test_js_context_store import _context_id, _document


async def _run(coro):
    return await coro


def _selection(tmp_path=None, project_id="project-a", run_id="run-1"):
    document = _document(project_id=project_id, run_id=run_id)
    publication = None
    if tmp_path is not None:
        publication = JsContextStore(root_dir=tmp_path).publish(document)
    context_id = publication["context_id"] if publication else _context_id(document)
    value = publication_input(
        project_id=project_id,
        producing_run_id=run_id,
        publication={
            "status": "published",
            "context_id": context_id,
            "document_id": "document-1",
            "document_sha256": (
                publication["document_sha256"] if publication else "a" * 64
            ),
            "auth_ref": document["context"]["auth_ref"],
            "origin": document["context"]["origin"],
            "gaps": ["bounded_selection"],
        },
    )
    return document, value


def _tool_message(selection):
    return ToolMessage(
        content=json.dumps(
            {
                "ok": True,
                "command": "read",
                "publication": {
                    "document_sha256": selection.document_sha256,
                },
                "js_context_binding": {
                    "input_id": selection.input_id,
                    "project_id": selection.project_id,
                    "producing_run_id": selection.producing_run_id,
                    "context_id": selection.context_id,
                    "document_id": selection.document_id,
                    "document_sha256": selection.document_sha256,
                },
            }
        ),
        name="js_context",
        tool_call_id=f"read-{selection.input_id}",
    )


def _actual_tool_message(
    tmp_path,
    selection,
    *,
    command,
    section="metadata",
    call_id,
):
    tool = build_js_context_tool(
        project_id=selection.project_id,
        store=JsContextStore(root_dir=tmp_path),
        selection=selection,
    )
    args = {"command": command}
    if command == "read":
        args.update(
            {
                "context_id": selection.context_id,
                "selector": "current",
                "section": section,
            }
        )
    output = tool.invoke(args)
    return ToolMessage(
        content=json.dumps(output, ensure_ascii=False),
        name="js_context",
        tool_call_id=call_id,
    )


def test_list_and_metadata_reads_are_not_behavioral_consumption(tmp_path):
    _, selection = _selection(tmp_path)
    messages = [
        _actual_tool_message(
            tmp_path,
            selection,
            command="list",
            call_id="list-1",
        ),
        _actual_tool_message(
            tmp_path,
            selection,
            command="read",
            section="metadata",
            call_id="metadata-1",
        ),
    ]
    tracker = JsContextApplicationTracker(selection)
    for role in ("assigner", "mechanism_typist"):
        tracker.observe_turn(role, messages)
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

    summary = tracker.settle()

    assert summary["status"] == "settled_gap"
    assert "js_context_read_content_missing" in summary["gaps"]
    assert summary["roles"]["assigner"]["delivered_reads"] == 0
    assert summary["roles"]["mechanism_typist"]["delivered_reads"] == 0


def test_relevant_behavior_read_is_consumption(tmp_path):
    _, selection = _selection(tmp_path)
    tracker = JsContextApplicationTracker(selection)
    for role in ("assigner", "mechanism_typist"):
        tracker.observe_turn(
            role,
            [
                _actual_tool_message(
                    tmp_path,
                    selection,
                    command="read",
                    section="behaviors",
                    call_id=f"behavior-{role}",
                )
            ],
        )
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

    summary = tracker.settle()

    assert summary["status"] == "settled_success"
    assert summary["roles"]["assigner"]["delivered_reads"] == 1
    assert summary["roles"]["mechanism_typist"]["delivered_reads"] == 1


def test_context_only_js_input_reaches_both_proposers(tmp_path):
    _, selection = _selection(tmp_path)
    roles = []
    persisted = {}
    tracker = JsContextApplicationTracker(selection)

    async def fake_supervisor(project_id, run_id, schedule, **kwargs):
        roles.extend(dispatch.role for dispatch in schedule)
        for dispatch in schedule:
            assert dispatch.chunk.js_context_input == selection
            tracker.observe_turn(
                dispatch.role,
                [
                    _actual_tool_message(
                        tmp_path,
                        selection,
                        command="read",
                        section="behaviors",
                        call_id=f"context-{dispatch.role}",
                    )
                ],
            )
        return {
            "receipts": [
                StepReceipt(
                    dispatch_id=dispatch.dispatch_id,
                    role=dispatch.role,
                    phase=dispatch.phase,
                    status="empty",
                )
                for dispatch in schedule
            ]
        }

    result = asyncio.run(
        analyse_chunked(
            L0Chunk(
                project_id="project-a",
                run_id="run-1",
                job="js_analysis",
                js_context_input=selection,
            ),
            inventory_fn=lambda project_id: {
                "services": [],
                "systems": [],
                "system_descriptions": {},
            },
            invoke_fn=lambda *args, **kwargs: L1DeltaBatch(),
            typist_invoke_fn=lambda *args, **kwargs: L1DeltaBatch(),
            js_context_tracker=tracker,
            js_stats_write_fn=lambda run_id, stats: persisted.update(stats),
            run_supervisor_fn=fake_supervisor,
            observe=False,
        )
    )

    assert roles[:2] == ["assigner", "mechanism_typist"]
    assert result.census.dispatches_scheduled == 2
    assert result.census.js_context_input_id == selection.input_id
    summary = persisted["js_context_application"]
    assert summary["input_id"] == selection.input_id
    assert summary["selection"] == selection.as_dict()
    assert summary["status"] == "settled_success"
    assert summary["roles"]["assigner"]["delivered_reads"] == 1
    assert summary["roles"]["mechanism_typist"]["delivered_reads"] == 1


def test_context_only_input_is_not_short_circuited_by_either_role():
    from polymerhus.analysis.assigner import assign
    from polymerhus.analysis.chunking import Chunk
    from polymerhus.analysis.mechanism_typist import type_mechanisms

    _, selection = _selection()
    chunk = Chunk(
        chunk_id="js_analysis:0",
        source_job="js_analysis",
        js_context_input=selection,
    )
    seen = []

    def assigner_invoke(messages, **kwargs):
        seen.append(("assigner", messages[0].content))
        return L1DeltaBatch()

    def typist_invoke(messages, *, schema=None, **kwargs):
        seen.append(("mechanism_typist", messages[0].content))
        return "reflection" if schema is None else L1DeltaBatch()

    assign(
        chunk,
        invoke_fn=assigner_invoke,
        inventory={"services": [], "systems": []},
    )
    type_mechanisms(
        chunk,
        invoke_fn=typist_invoke,
        inventory={"services": [], "systems": []},
        aggregations=[],
    )

    by_role = {}
    for role, prompt in seen:
        by_role.setdefault(role, []).append(prompt)
    assert "assigner" in by_role
    assert "mechanism_typist" in by_role
    assert all(selection.input_id in prompt for prompt in by_role["assigner"])
    assert any(
        selection.input_id in prompt
        for prompt in by_role["mechanism_typist"]
    )


def test_analysis_streams_while_js_producer_is_still_open():
    early_seen = asyncio.Event()
    release_js = asyncio.Event()
    order = []

    async def consume(chunk):
        from polymerhus.analysis.supervisor import PassCensus, PassResult

        order.append(chunk.job)
        if chunk.job == "katana":
            early_seen.set()
            await release_js.wait()
        return PassResult(
            export=None,
            census=PassCensus(
                dispatches_entered=1,
                unprocessed_after=0,
                terminal=chunk.terminal,
            ),
        )

    async def scenario():
        feed = QueuedAnalysisFeed("project-a", "run-1", pass_fn=consume).start()
        await feed.push(
            L0Chunk(
                project_id="project-a",
                run_id="run-1",
                job="katana",
                assets=[],
            )
        )
        await early_seen.wait()
        assert order == ["katana"]
        release_js.set()
        _, selection = _selection()
        await feed.push(
            L0Chunk(
                project_id="project-a",
                run_id="run-1",
                job="js_analysis",
                js_context_input=selection,
            )
        )
        await feed.signal_end()
        return await feed.wait_until_done()

    stats = asyncio.run(scenario())
    assert order == ["katana", "js_analysis", ""]
    assert stats.analysis_drained is True


def test_each_chunk_reset_rebinds_the_same_frozen_publication(
    tmp_path, monkeypatch
):
    import polymerhus.app.data_root as data_root_module

    monkeypatch.setattr(data_root_module, "DATA_ROOT", tmp_path)
    _, selection = _selection(tmp_path)
    store = JsContextStore(root_dir=tmp_path)
    newer = _document(project_id="project-a", run_id="run-2")
    store.publish(newer)

    tracker = JsContextApplicationTracker(selection)
    observed = []

    def fake_stateful_turn(role_id, address, messages, **kwargs):
        from polymerhus.app.llm.session import SessionTurn

        tool = next(
            tool for tool in kwargs["tools"] if tool.name == "js_context"
        )
        result = tool.invoke(
            {
                "command": "read",
                "context_id": selection.context_id,
                "selector": "current",
                "section": "metadata",
            }
        )
        assert result.get("selector", {}).get("run_id") == "run-1", result
        observed.append(result["js_context_binding"]["input_id"])
        kwargs["on_turn"](
            SessionTurn(
                content="read",
                messages=[_tool_message(selection)],
                thread_id=address.thread_id,
            )
        )
        return None

    monkeypatch.setattr(
        "polymerhus.app.llm.session.stateful_turn",
        fake_stateful_turn,
    )
    for role in ("assigner", "mechanism_typist"):
        invoke = session_invoke_fn(
            role,
            "run-1",
            InMemorySaver(),
            project_id="project-a",
            js_context_selection=selection,
            js_context_tracker=tracker,
        )
        for batch_id in ("js_analysis:0", "js_analysis:1"):
            with proposer_batch(batch_id):
                invoke(
                    [HumanMessage(content="integrate current JS")],
                    schema=L1DeltaBatch,
                )

    assert observed == [selection.input_id] * 4


@pytest.mark.parametrize(
    "role_gap,read_gap,expected_gap",
    [
        ("degraded", None, "js_context_role_failed"),
        (None, "missing", "js_context_read_failed"),
        (None, "declared_only", "js_context_read_missing"),
    ],
)
def test_application_never_claims_success_from_dispatch_alone(
    role_gap, read_gap, expected_gap
):
    _, selection = _selection()
    tracker = JsContextApplicationTracker(selection)
    receipts = [
        StepReceipt(
            dispatch_id="a",
            role="assigner",
            phase="A1",
            status=role_gap or "empty",
            error="provider timeout" if role_gap else None,
        ),
        StepReceipt(
            dispatch_id="t",
            role="mechanism_typist",
            phase="A1",
            status="empty",
        ),
    ]
    if read_gap == "missing":
        tracker.observe_turn(
            "assigner",
            [
                ToolMessage(
                    content=json.dumps(
                        {
                            "ok": False,
                            "error": "missing",
                            "js_context_binding": {
                                "input_id": selection.input_id
                            },
                        }
                    ),
                    name="js_context",
                    tool_call_id="read-a",
                )
            ],
        )
    elif read_gap == "declared_only":
        tracker.observe_turn("assigner", [])
    else:
        tracker.observe_turn("assigner", [_tool_message(selection)])
    if role_gap is None and read_gap is not None:
        tracker.observe_turn("mechanism_typist", [_tool_message(selection)])

    tracker.observe_receipts(receipts)
    summary = tracker.settle()
    assert summary["status"] == "settled_gap"
    assert expected_gap in summary["gaps"]


def test_nonpublished_publication_settles_without_fake_read_success():
    selection = publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "pending",
            "error": "context_publication_timeout",
        },
    )
    tracker = JsContextApplicationTracker(selection)
    tracker.observe_receipts(
        [
            StepReceipt(
                dispatch_id="a",
                role="assigner",
                phase="A1",
                status="empty",
            ),
            StepReceipt(
                dispatch_id="t",
                role="mechanism_typist",
                phase="A1",
                status="empty",
            ),
        ]
    )
    summary = tracker.settle()
    assert summary["status"] == "settled_gap"
    assert "context_publication_timeout" in summary["gaps"]


def test_resume_reuses_a_settled_context_only_application_without_model():
    _, selection = _selection()
    existing = {
        "schema_version": 1,
        "input_id": selection.input_id,
        "project_id": selection.project_id,
        "producing_run_id": selection.producing_run_id,
        "context_id": selection.context_id,
        "document_id": selection.document_id,
        "document_sha256": selection.document_sha256,
        "status": "settled_success",
        "gaps": ["bounded_selection"],
        "roles": {
            "assigner": {
                "delivered_reads": 1,
                "failed_reads": 0,
                "receipts": 1,
            },
            "mechanism_typist": {
                "delivered_reads": 1,
                "failed_reads": 0,
                "receipts": 1,
            },
        },
    }
    calls = []

    async def must_not_run(*args, **kwargs):
        calls.append("supervisor")
        raise AssertionError("resume called the model")

    result = asyncio.run(
        analyse_chunked(
            L0Chunk(
                project_id="project-a",
                run_id="run-1",
                job="js_analysis",
                js_context_input=selection,
            ),
            invoke_fn=lambda *args, **kwargs: calls.append("assigner"),
            typist_invoke_fn=lambda *args, **kwargs: calls.append("typist"),
            js_stats_read_fn=lambda run_id: {
                "stats": {"js_context_application": existing}
            },
            js_stats_write_fn=lambda run_id, stats: None,
            run_supervisor_fn=must_not_run,
            observe=False,
        )
    )

    assert calls == []
    assert result.census.js_context_reused is True
    assert result.census.js_context_status == "settled_success"
