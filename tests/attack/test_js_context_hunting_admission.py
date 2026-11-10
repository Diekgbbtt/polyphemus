"""A hunting launch is admitted only through one settled JS workflow state."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from polymerhus.attack.hunting.js_context_admission import (
    JsContextAdmissionError,
    resolve_js_context_admission,
)
from polymerhus.app.js_context.selection import publication_input
from polymerhus.app.js_context.selection import not_applicable


def _selection(run_id="run-1"):
    return publication_input(
        project_id="project-a",
        producing_run_id=run_id,
        publication={
            "status": "published",
            "context_id": "jsctx_" + "a" * 40,
            "document_id": "document-1",
            "document_sha256": "b" * 64,
            "auth_ref": "alice",
            "origin": {"status": "known", "value": "https://app.example"},
            "gaps": ["bounded_selection"],
        },
    )


def _summary(selection, status="settled_success", gaps=None):
    return {
        "schema_version": 1,
        "input_id": selection.input_id,
        "project_id": selection.project_id,
        "producing_run_id": selection.producing_run_id,
        "context_id": selection.context_id,
        "document_id": selection.document_id,
        "document_sha256": selection.document_sha256,
        "status": status,
        "gaps": list(gaps or []),
        "selection": selection.as_dict(),
        "roles": {},
    }


class PG:
    def __init__(self, run=None, producers=()):
        self.run = run
        self.producers = list(producers)

    def get_run(self, run_id):
        return self.run if self.run and self.run["run_id"] == run_id else None

    def list_active_js_context_producers(self, project_id):
        return list(self.producers)


@pytest.mark.parametrize("status", ["settled_success", "settled_gap"])
def test_settled_js_application_admits_with_the_same_frozen_selection(status):
    selection = _selection()
    pg = PG(
        run={
            "run_id": "run-1",
            "project_id": "project-a",
            "status": "complete",
            "stats": {
                "js_context_application": _summary(
                    selection,
                    status,
                    ["bounded_selection"] if status == "settled_gap" else [],
                )
            },
        }
    )

    admitted = resolve_js_context_admission(
        "project-a",
        "run-1",
        pg_module=pg,
    )

    assert admitted.selection == selection
    assert admitted.summary["input_id"] == selection.input_id


@pytest.mark.parametrize(
    "status,code",
    [
        ("pending", "js_context_not_ready"),
        ("settled_success", "js_context_analysis_missing"),
    ],
)
def test_pending_or_missing_js_application_is_coded_not_ready(status, code):
    selection = _selection()
    stats = {}
    if status == "pending":
        stats["js_context_application"] = _summary(selection, status)
    pg = PG(
        run={
            "run_id": "run-1",
            "project_id": "project-a",
            "status": "complete",
            "stats": stats,
        }
    )

    with pytest.raises(JsContextAdmissionError) as caught:
        resolve_js_context_admission(
            "project-a",
            "run-1",
            pg_module=pg,
        )

    assert caught.value.code == code


def test_explicit_and_implicit_producer_selection_is_never_latest_based():
    first = _selection("run-1")
    second = _selection("run-2")
    pg = PG(
        run={
            "run_id": "run-2",
            "project_id": "project-a",
            "status": "complete",
            "stats": {
                "js_context_application": _summary(second)
            },
        },
        producers=("run-1", "run-2"),
    )

    with pytest.raises(JsContextAdmissionError) as caught:
        resolve_js_context_admission("project-a", None, pg_module=pg)

    assert caught.value.code == "ambiguous_producing_run"


def test_unique_active_producer_resolves_explicitly():
    selection = _selection()
    pg = PG(
        run={
            "run_id": "run-1",
            "project_id": "project-a",
            "status": "complete",
            "stats": {
                "js_context_application": _summary(selection)
            },
        },
        producers=("run-1",),
    )

    admitted = resolve_js_context_admission(
        "project-a",
        None,
        pg_module=pg,
    )

    assert admitted.selection.producing_run_id == "run-1"


def test_no_active_js_workflow_returns_none_for_legacy_hunting():
    admitted = resolve_js_context_admission(
        "project-a",
        None,
        pg_module=PG(producers=()),
    )

    assert admitted is None


def test_not_applicable_js_outcome_is_a_valid_settlement():
    selection = not_applicable(
        project_id="project-a",
        producing_run_id="run-1",
    )
    pg = PG(
        run={
            "run_id": "run-1",
            "project_id": "project-a",
            "status": "complete",
            "stats": {
                "js_context_application": {
                    "input_id": selection.input_id,
                    "project_id": "project-a",
                    "producing_run_id": "run-1",
                    "status": "not_applicable",
                    "gaps": ["js_not_selected"],
                    "selection": selection.as_dict(),
                }
            },
        }
    )

    admitted = resolve_js_context_admission(
        "project-a",
        "run-1",
        pg_module=pg,
    )

    assert admitted.selection == selection


def test_foreign_project_or_changed_input_is_refused():
    selection = _selection()
    pg = PG(
        run={
            "run_id": "run-1",
            "project_id": "project-b",
            "status": "complete",
            "stats": {
                "js_context_application": _summary(selection)
            },
        }
    )

    with pytest.raises(JsContextAdmissionError) as caught:
        resolve_js_context_admission(
            "project-a",
            "run-1",
            pg_module=pg,
        )

    assert caught.value.code == "js_context_project_mismatch"
