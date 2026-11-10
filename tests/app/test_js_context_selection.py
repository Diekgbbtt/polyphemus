"""Application-owned JS input carried by the Analysis feed."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from polymerhus.app.js_context.selection import (
    JsContextInput,
    gap_input,
    not_applicable,
    publication_input,
)


def test_published_input_is_immutable_and_has_deterministic_identity():
    value = publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "published",
            "context_id": "jsctx_" + "a" * 40,
            "document_id": "document-1",
            "document_sha256": "b" * 64,
            "auth_ref": "alice",
            "origin": {"status": "known", "value": "https://app.example"},
            "gaps": ["bounded_selection", "producer_incomplete"],
        },
    )

    reordered = JsContextInput.from_dict(
        {
            "gaps": ["bounded_selection", "producer_incomplete"],
            "document_sha256": "b" * 64,
            "origin": {"value": "https://app.example", "status": "known"},
            "auth_ref": "alice",
            "document_id": "document-1",
            "context_id": "jsctx_" + "a" * 40,
            "producing_run_id": "run-1",
            "project_id": "project-a",
            "status": "published",
            "input_id": "jsinput_3eef98eec6c670cf47001b505aa308f27d0484a8",
        }
    )

    assert value.input_id == "jsinput_3eef98eec6c670cf47001b505aa308f27d0484a8"
    assert reordered == value
    assert value.as_dict()["gaps"] == ["bounded_selection", "producer_incomplete"]
    with pytest.raises(FrozenInstanceError):
        value.status = "pending"


@pytest.mark.parametrize(
    "status,extra",
    [
        ("published", {}),
        (
            "failed",
            {
                "context_id": "jsctx_" + "a" * 40,
                "document_id": "document-1",
                "document_sha256": "b" * 64,
            },
        ),
    ],
)
def test_selection_rejects_half_published_or_gap_with_publication_refs(
    status, extra
):
    with pytest.raises(ValueError):
        JsContextInput(
            project_id="project-a",
            producing_run_id="run-1",
            status=status,
            context_id=extra.get("context_id"),
            document_id=extra.get("document_id"),
            document_sha256=extra.get("document_sha256"),
            auth_ref="",
            origin={"status": "unknown", "value": None},
            gaps=("context_publication_timeout",),
        )


def test_pending_or_failed_publication_freezes_a_gap_without_current_refs():
    value = publication_input(
        project_id="project-a",
        producing_run_id="run-1",
        publication={
            "status": "pending",
            "context_id": "jsctx_" + "a" * 40,
            "document_id": "prepared-document",
            "document_sha256": "b" * 64,
            "error": "context_publication_timeout",
        },
        auth_ref="alice",
    )

    assert value.status == "pending"
    assert value.context_id is None
    assert value.document_id is None
    assert value.document_sha256 is None
    assert value.auth_ref == "alice"
    assert "context_publication_timeout" in value.gaps


def test_gap_and_not_applicable_helpers_remain_distinct_and_scoped():
    failed = gap_input(
        project_id="project-a",
        producing_run_id="run-1",
        status="unavailable",
        gaps=["js_analysis_dispatch_failed"],
        auth_ref="alice",
    )
    absent = not_applicable(
        project_id="project-a",
        producing_run_id="run-1",
    )

    assert failed.status == "unavailable"
    assert failed.auth_ref == "alice"
    assert absent.status == "not_applicable"
    assert absent.gaps == ("js_not_selected",)
    assert failed.input_id != absent.input_id


def test_from_dict_rejects_a_tampered_identity_or_unbounded_gap():
    original = gap_input(
        project_id="project-a",
        producing_run_id="run-1",
        status="failed",
        gaps=["js_analysis_failed"],
    ).as_dict()

    with pytest.raises(ValueError, match="identity mismatch"):
        JsContextInput.from_dict({**original, "input_id": "jsinput_" + "0" * 40})
    with pytest.raises(ValueError, match="bounded codes"):
        JsContextInput.from_dict(
            {**original, "gaps": ["not a code"], "input_id": None}
        )


def test_identity_is_isolated_by_project_run_auth_and_document_hash():
    base = {
        "status": "published",
        "context_id": "jsctx_" + "a" * 40,
        "document_id": "document-1",
        "document_sha256": "b" * 64,
        "auth_ref": "alice",
    }
    values = [
        publication_input(
            project_id=project,
            producing_run_id=run,
            publication={
                **base,
                "auth_ref": auth,
                "document_sha256": digest,
            },
            auth_ref=auth,
        )
        for project, run, auth, digest in [
            ("project-a", "run-1", "alice", "b" * 64),
            ("project-b", "run-1", "alice", "b" * 64),
            ("project-a", "run-2", "alice", "b" * 64),
            ("project-a", "run-1", "bob", "b" * 64),
            ("project-a", "run-1", "alice", "c" * 64),
        ]
    ]

    assert len({value.input_id for value in values}) == 5
