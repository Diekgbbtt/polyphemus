"""Public hunting launch checks a workflow-bound JS application before row open."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from polymerhus.app.clients import pg
from polymerhus.app.js_context.selection import publication_input
from polymerhus.project_management.api import HuntingLaunch, launch_hunting


def _selection():
    return publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "published",
            "context_id": "jsctx_" + "a" * 40,
            "document_id": "document-1",
            "document_sha256": "b" * 64,
            "auth_ref": "alice",
            "origin": {"status": "known", "value": "https://app.example"},
        },
    )


def _patch_launch_dependencies(monkeypatch, *, admission):
    import polymerhus.attack.hunting.js_context_admission as admission_mod
    from polymerhus.attack.hunting import runtime as hunting_runtime

    async def inline_to_thread(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)
    monkeypatch.setattr(pg, "project_exists", lambda project_id: True)
    monkeypatch.setattr(pg, "list_hunting_runs", lambda project_id: [])
    monkeypatch.setattr(pg, "create_hunting_run", lambda project_id: "hunt-1")
    monkeypatch.setattr(pg, "set_hunting_run_status", lambda *a, **k: None)
    monkeypatch.setattr(
        hunting_runtime,
        "hunting_control_plane_available",
        lambda: True,
    )

    def default_start(project_id, **kwargs):
        async def done():
            return kwargs.get("run_id")

        return done()

    def default_schedule(coro, *, name):
        coro.close()
        return object()

    monkeypatch.setattr(hunting_runtime, "start_hunting", default_start)
    monkeypatch.setattr(hunting_runtime, "schedule_hunting", default_schedule)
    return admission_mod, hunting_runtime


def test_pending_js_application_returns_coded_not_ready_before_row_open(
    monkeypatch,
):
    admission_mod, hunting_runtime = _patch_launch_dependencies(
        monkeypatch,
        admission=None,
    )
    created = []
    monkeypatch.setattr(
        pg,
        "create_hunting_run",
        lambda project_id: created.append(project_id) or "hunt-1",
    )

    def refuse(*args, **kwargs):
        raise admission_mod.JsContextAdmissionError(
            "js_context_not_ready",
            gaps=["analysis_in_progress"],
        )

    monkeypatch.setattr(
        admission_mod,
        "resolve_js_context_admission",
        refuse,
    )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            launch_hunting(
                "project-a",
                HuntingLaunch(producing_run_id="run-1"),
            )
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "js_context_not_ready"
    assert created == []


def test_settled_js_application_is_carried_into_the_bound_launch(monkeypatch):
    selection = _selection()
    admission_mod, hunting_runtime = _patch_launch_dependencies(
        monkeypatch,
        admission=None,
    )
    admitted = admission_mod.JsContextAdmission(
        selection=selection,
        summary={
            "input_id": selection.input_id,
            "status": "settled_gap",
            "gaps": ["bounded_selection"],
        },
    )
    monkeypatch.setattr(
        admission_mod,
        "resolve_js_context_admission",
        lambda *args, **kwargs: admitted,
    )
    seen = {}

    def fake_start(project_id, **kwargs):
        seen.update({"project_id": project_id, **kwargs})

        async def done():
            return kwargs.get("run_id")

        return done()

    def schedule(coro, *, name):
        coro.close()
        seen["scheduled"] = name
        return object()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)
    monkeypatch.setattr(hunting_runtime, "schedule_hunting", schedule)

    response = asyncio.run(
        launch_hunting(
            "project-a",
            HuntingLaunch(producing_run_id="run-1"),
        )
    )

    assert response == {"hunting_run_id": "hunt-1"}
    assert seen["project_id"] == "project-a"
    assert seen["run_id"] == "hunt-1"
    assert seen["producing_run_id"] == "run-1"
    assert seen["js_context_selection"] == selection
    assert seen["scheduled"] == "hunting:hunt-1"


def test_no_active_js_workflow_keeps_legacy_unbound_launch(monkeypatch):
    admission_mod, hunting_runtime = _patch_launch_dependencies(
        monkeypatch,
        admission=None,
    )
    monkeypatch.setattr(
        admission_mod,
        "resolve_js_context_admission",
        lambda *args, **kwargs: None,
    )
    seen = {}

    def fake_start(project_id, **kwargs):
        seen.update(kwargs)

        async def done():
            return kwargs.get("run_id")

        return done()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)

    response = asyncio.run(
        launch_hunting("project-a", HuntingLaunch())
    )

    assert response == {"hunting_run_id": "hunt-1"}
    assert seen["producing_run_id"] is None
    assert seen["js_context_selection"] is None
