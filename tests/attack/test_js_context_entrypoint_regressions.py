"""Frozen JS context survives native resume and modeller-only entrypoints."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from polymerhus.app.clients import pg
import polymerhus.app.data_root as data_root
from polymerhus.app.js_context.records import document_identity
from polymerhus.app.js_context.selection import publication_input, not_applicable
from polymerhus.app.js_context.store import JsContextStore
from polymerhus.attack.hunting import runtime
from polymerhus.attack.hunting.js_context_admission import (
    JsContextAdmission,
    JsContextAdmissionError,
    current_js_context_selection,
)
from tests.app.test_js_context_store import _document, _context_id
from tests.attack.test_js_context_hunting_admission import _summary


def published_selection(root, run_id="run-1", project_id="project-a"):
    document = _document(project_id=project_id, run_id=run_id)
    publication = JsContextStore(root_dir=root).publish(document)
    return publication_input(
        project_id=project_id,
        producing_run_id=run_id,
        publication={
            **publication,
            "document_id": document_identity(document),
            "context_id": _context_id(document),
            "auth_ref": document["context"]["auth_ref"],
            "origin": document["context"]["origin"],
        },
    )


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    async def inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)
    monkeypatch.setattr(data_root, "DATA_ROOT", tmp_path)
    selection = published_selection(tmp_path)
    newer = published_selection(tmp_path, "run-2")  # current has advanced
    rows = {
        s.producing_run_id: {
            "run_id": s.producing_run_id, "project_id": "project-a",
            "status": "complete", "stats": {"js_context_application": _summary(s)},
        }
        for s in (selection, newer)
    }
    hunting = {
        "hunting_run_id": "hunt-1", "project_id": "project-a",
        "status": "stopped", "stats": {"js_context_selection": selection.as_dict()},
    }
    writes = []
    monkeypatch.setattr(pg, "get_run", rows.get)
    monkeypatch.setattr(pg, "get_hunting_run", lambda _: hunting)
    monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: [])
    monkeypatch.setattr(pg, "set_hunting_run_status", lambda *a, **k: writes.append((a, k)))
    return selection, rows, hunting, writes


@pytest.mark.parametrize("active", [[], ["run-2"]])
def test_resume_uses_persisted_run_even_after_analysis_or_current_advance(workflow, monkeypatch, active):
    selected, _, _, _ = workflow
    monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: active)

    async def consume(*args, **kwargs):
        selection = current_js_context_selection()
        assert selection == selected
        from polymerhus.app.js_context.tool import build_js_context_tool
        result = build_js_context_tool(project_id="project-a", selection=selection).invoke({
            "command": "read", "context_id": selection.context_id,
            "selector": "current", "section": "behaviors",
        })
        assert result["ok"] is True
        assert result["js_context_binding"]["producing_run_id"] == "run-1"
        return "resumed"

    monkeypatch.setattr(runtime, "_start_hunting_under_context", consume)
    assert asyncio.run(runtime.start_hunting("project-a", run_id="hunt-1")) == "resumed"
    assert current_js_context_selection() is None


@pytest.mark.parametrize("damage", [
    "missing", "corrupt", "hash", "document", "auth", "origin", "context",
    "project", "producer", "malformed", "null", "foreign_hunting",
])
def test_resume_refuses_missing_corrupt_or_foreign_selection(workflow, tmp_path, monkeypatch, damage):
    selected, rows, hunting, writes = workflow
    path = tmp_path / "project-a/js-client-side" / selected.context_id / "run-1.yml"
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_text("[not: yaml")
    elif damage in {"hash", "document", "auth", "origin", "context", "project", "producer"}:
        changes = {
            "hash": {"document_sha256": "f" * 64},
            "document": {"document_id": "f" * 64},
            "auth": {"auth_ref": "foreign-account"},
            "origin": {"origin": {"status": "known", "value": "https://foreign.test"}},
            "context": {"context_id": "jsctx_" + "f" * 40},
            "project": {"project_id": "foreign-project"},
            "producer": {"producing_run_id": "run-2"},
        }
        modified = replace(selected, **changes[damage])
        hunting["stats"]["js_context_selection"] = modified.as_dict()
        if damage in {"hash", "document", "auth", "origin", "context"}:
            # Even matching persisted workflow records cannot bless different
            # or foreign bytes; reach the actual store's identity validation.
            rows["run-1"]["stats"]["js_context_application"] = _summary(modified)
    elif damage == "foreign_hunting":
        hunting["project_id"] = "foreign-project"
    else:
        hunting["stats"]["js_context_selection"] = None if damage == "null" else {"invalid": True}

    async def must_not_start(*args, **kwargs):
        pytest.fail("invalid resume reached execution")

    monkeypatch.setattr(runtime, "_start_hunting_under_context", must_not_start)
    assert asyncio.run(runtime.start_hunting("project-a", run_id="hunt-1")) is None
    assert writes[-1][0] == ("hunt-1", "failed")
    assert writes[-1][1]["stats"]["js_context_admission_error"]["code"]


def test_resume_legacy_never_adopts_new_active_js_workflow(workflow, monkeypatch):
    _, _, hunting, _ = workflow
    hunting["stats"] = {"intake_order": ["unit-a"]}
    monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: ["run-2"])

    async def consume(*args, **kwargs):
        assert current_js_context_selection() is None
        return "legacy"

    monkeypatch.setattr(runtime, "_start_hunting_under_context", consume)
    assert asyncio.run(runtime.start_hunting("project-a", run_id="hunt-1")) == "legacy"


@pytest.mark.parametrize("argument", ["producing_run_id", "js_context_admission"])
def test_explicit_launch_arguments_cannot_replace_persisted_resume_selection(workflow, monkeypatch, argument):
    _, rows, _, writes = workflow
    value = "run-2" if argument == "producing_run_id" else JsContextAdmission(
        publication_input(project_id="project-a", producing_run_id="run-2",
                          publication={**rows["run-2"]["stats"]["js_context_application"]["selection"]}),
        rows["run-2"]["stats"]["js_context_application"],
    )

    async def consume(*a, **k):
        return "wrong-resume"

    monkeypatch.setattr(runtime, "_start_hunting_under_context", consume)
    assert asyncio.run(runtime.start_hunting("project-a", run_id="hunt-1", **{argument: value})) is None
    assert writes[-1][1]["stats"]["js_context_admission_error"]["code"] == "js_context_application_changed"


def test_resume_refuses_loss_of_a_previously_admitted_selection(workflow, monkeypatch):
    selected, rows, hunting, writes = workflow
    admitted = JsContextAdmission(selected, rows["run-1"]["stats"]["js_context_application"])
    hunting["stats"].pop("js_context_selection")

    async def consume(*a, **k):
        return "lost-selection"

    monkeypatch.setattr(runtime, "_start_hunting_under_context", consume)
    assert asyncio.run(runtime.start_hunting(
        "project-a", run_id="hunt-1", resume=True, js_context_admission=admitted,
    )) is None
    assert writes[-1][1]["stats"]["js_context_admission_error"]["code"] == "js_context_application_changed"


@pytest.mark.parametrize("entrypoint", ["modeller", "hunting"])
def test_runtime_refuses_a_new_workflow_after_api_admitted_legacy(workflow, monkeypatch, entrypoint):
    _, _, hunting, writes = workflow
    hunting["stats"] = {}
    hunting["status"] = "running"  # fresh row opened by a legacy API launch
    monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: ["run-2"])

    async def no_live(*a, **k):
        return False

    async def consume(*a, **k):
        return ["wrong-model"], None

    monkeypatch.setattr(runtime, "_project_has_live_hunting_run", no_live)
    monkeypatch.setattr(runtime, "_run_intake", consume)
    monkeypatch.setattr(runtime, "_start_hunting_under_context", consume)
    if entrypoint == "modeller":
        with pytest.raises(JsContextAdmissionError, match="js_context_application_changed"):
            asyncio.run(runtime.launch_modeller(
                "project-a", run_id="modeller-1", tools=object(), js_context_admission=None,
            ))
    else:
        assert asyncio.run(runtime.start_hunting(
            "project-a", run_id="hunt-1", js_context_admission=None,
        )) is None
        assert writes[-1][1]["stats"]["js_context_admission_error"]["code"] == "js_context_application_changed"


def test_native_modeller_refuses_pending_before_any_intake(workflow, monkeypatch):
    _, rows, _, _ = workflow
    rows["run-1"]["stats"]["js_context_application"]["status"] = "pending"
    monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: ["run-1"])

    async def no_live(*a, **k):
        return False

    async def must_not_start(*a, **k):
        pytest.fail("pending JS reached modeller intake")

    monkeypatch.setattr(runtime, "_project_has_live_hunting_run", no_live)
    monkeypatch.setattr(runtime, "_run_intake", must_not_start)
    with pytest.raises(JsContextAdmissionError, match="js_context_not_ready"):
        asyncio.run(runtime.launch_modeller("project-a", run_id="modeller-1", tools=object()))


@pytest.mark.parametrize("status", ["settled_success", "settled_gap", "not_applicable", "legacy"])
def test_native_modeller_binds_the_admitted_selection(workflow, monkeypatch, status):
    selected, rows, _, _ = workflow
    if status == "not_applicable":
        selected = not_applicable(project_id="project-a", producing_run_id="run-1")
    if status != "legacy":
        rows["run-1"]["stats"]["js_context_application"] = _summary(selected, status)
        monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: ["run-1"])

    async def no_live(*a, **k):
        return False

    async def consume(*a, **k):
        assert current_js_context_selection() == (None if status == "legacy" else selected)
        return ["modelled"], None

    monkeypatch.setattr(runtime, "_project_has_live_hunting_run", no_live)
    monkeypatch.setattr(runtime, "_run_intake", consume)
    assert asyncio.run(runtime.launch_modeller("project-a", run_id="modeller-1", tools=object())) == ["modelled"]
    assert current_js_context_selection() is None
