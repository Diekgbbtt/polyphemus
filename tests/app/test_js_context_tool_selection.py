"""Application-selected JS reads cannot drift to a newer current pointer."""

from __future__ import annotations

from polymerhus.app.js_context.selection import publication_input
from polymerhus.app.js_context.store import JsContextStore
from polymerhus.app.js_context.tool import build_js_context_tool
from tests.app.test_js_context_store import _context_id, _document


def _selection(tmp_path, project_id="project-a", run_id="run-1"):
    document = _document(project_id=project_id, run_id=run_id)
    publication = JsContextStore(root_dir=tmp_path).publish(document)
    return publication_input(
        project_id=project_id,
        producing_run_id=run_id,
        publication={
            "status": "published",
            "context_id": publication["context_id"],
            "document_id": "document-1",
            "document_sha256": publication["document_sha256"],
            "auth_ref": document["context"]["auth_ref"],
            "origin": document["context"]["origin"],
        },
    ), document, publication


def test_selected_current_reads_the_producing_run_not_latest(tmp_path):
    store = JsContextStore(root_dir=tmp_path)
    selection, _first, publication = _selection(tmp_path)
    store.publish(_document(project_id="project-a", run_id="run-2"))
    tool = build_js_context_tool(
        project_id="project-a",
        store=store,
        selection=selection,
    )

    result = tool.invoke(
        {
            "command": "read",
            "context_id": selection.context_id,
            "selector": "current",
            "section": "metadata",
        }
    )

    assert result["ok"] is True
    assert result["selector"]["run_id"] == "run-1"
    assert result["js_context_binding"]["input_id"] == selection.input_id


def test_selected_list_validates_the_plural_publication_envelope(tmp_path):
    selection, _first, publication = _selection(tmp_path)
    JsContextStore(root_dir=tmp_path).publish(
        _document(project_id="project-a", run_id="run-2")
    )
    tool = build_js_context_tool(
        project_id="project-a",
        store=JsContextStore(root_dir=tmp_path),
        selection=selection,
    )

    result = tool.invoke({"command": "list"})

    assert result["ok"] is True
    assert len(result["publications"]) == 1
    assert result["publications"][0]["run_id"] == "run-1"
    assert (
        result["publications"][0]["document_sha256"]
        == publication["document_sha256"]
    )
    assert result["js_context_binding"]["input_id"] == selection.input_id


def test_selected_list_and_read_keep_hash_integrity(tmp_path):
    selection, _first, publication = _selection(tmp_path)
    changed = type(selection)(
        project_id=selection.project_id,
        producing_run_id=selection.producing_run_id,
        context_id=selection.context_id,
        document_id=selection.document_id,
        document_sha256="c" * 64,
        auth_ref=selection.auth_ref,
        origin=selection.origin,
        status="published",
        gaps=selection.gaps,
    )
    tool = build_js_context_tool(
        project_id="project-a",
        store=JsContextStore(root_dir=tmp_path),
        selection=changed,
    )

    listed = tool.invoke({"command": "list"})
    read = tool.invoke(
        {
            "command": "read",
            "context_id": changed.context_id,
            "selector": "current",
            "section": "metadata",
        }
    )

    assert listed["ok"] is False
    assert listed["error"] == "corrupt"
    assert read["ok"] is False
    assert read["error"] == "corrupt"
    assert publication["document_sha256"] != changed.document_sha256


def test_selected_tool_refuses_another_context_or_run(tmp_path):
    store = JsContextStore(root_dir=tmp_path)
    selection, _first, _publication = _selection(tmp_path)
    store.publish(_document(project_id="project-a", run_id="run-2"))
    tool = build_js_context_tool(
        project_id="project-a",
        store=store,
        selection=selection,
    )

    wrong_run = tool.invoke(
        {
            "command": "read",
            "context_id": selection.context_id,
            "selector": "run-2",
            "section": "metadata",
        }
    )
    wrong_context = tool.invoke(
        {
            "command": "read",
            "context_id": "jsctx_" + "0" * 40,
            "selector": "current",
            "section": "metadata",
        }
    )

    assert wrong_run == {
        "ok": False,
        "error": "run_mismatch",
        "js_context_binding": {
            "input_id": selection.input_id,
            "project_id": "project-a",
            "producing_run_id": "run-1",
            "context_id": selection.context_id,
            "document_id": "document-1",
            "document_sha256": _publication["document_sha256"],
                "auth_ref": selection.auth_ref,
                "origin": selection.origin.as_dict(),
        },
    }
    assert wrong_context["ok"] is False
    assert wrong_context["error"] == "missing"
