"""Pure publication-contract tests for the JS context store."""

from __future__ import annotations

import copy

import pytest

from polymerhus.app.js_context.records import (
    JsContextInvalidError,
    context_id_for,
    document_identity,
    normalize_origin,
    validate_document,
)


def _document(**overrides) -> dict:
    document = {
        "schema_version": 1,
        "context": {
            "project_id": "project-a",
            "run_id": "run-1",
            "origin": {"status": "known", "value": "https://app.test"},
            "auth_ref": "account-a",
            "coverage": {
                "status": "complete",
                "gaps": [],
            },
        },
        "behaviors": [
            {
                "behavior_id": "behavior_a",
                "revision": 2,
                "reconstruction_level": "reconstructed",
                "question_ref": "span_a",
                "question": "How is the request built?",
                "priority": "high",
                "lead_id": "lead_a",
                "record_sha256": "a" * 64,
                "redaction_policy": "js-source-redaction-v1",
                "redaction_count": 0,
                "steps": [
                    {
                        "kind": "request",
                        "text": "The first supported step.",
                        "read_ids": ["read_a"],
                    },
                    {
                        "kind": "sink",
                        "text": "The second supported step.",
                        "read_ids": ["read_a"],
                    },
                ],
                "assumptions": [
                    {
                        "text": "The server accepts this value.",
                        "status": "unverified",
                        "read_ids": [],
                    }
                ],
                "gaps": ["Server behaviour is not visible."],
            }
        ],
        "evidence": [
            {
                "read_id": "read_a",
                "lead_id": "lead_a",
                "selector": {"type": "source", "id": "source_a"},
                "content_sha256": "b" * 64,
                "range": {"start": 12, "end": 84},
                "redaction_policy": "js-source-redaction-v1",
                "delivery_status": "delivered",
                "availability": "retained_unverified",
                "retention_status": "retained",
                "artifact_ref": "sha256/" + "b" * 64,
                "limitations": [],
            }
        ],
    }
    document.update(overrides)
    return document


def test_valid_document_is_preserved_and_has_a_stable_identity() -> None:
    document = _document()

    validated = validate_document(document)

    assert validated == document
    assert validated is not document
    assert document_identity(validated) == document_identity(copy.deepcopy(document))
    assert len(document_identity(validated)) == 64


def test_origin_normalization_never_uses_an_implicit_value() -> None:
    assert normalize_origin(None) == {"status": "unknown", "value": None}
    assert normalize_origin("https://APP.test:443/") == {
        "status": "known",
        "value": "https://app.test",
    }


def test_origin_normalizes_the_explicit_pipeline_envelope() -> None:
    assert normalize_origin(
        {"status": "known", "value": "https://APP.test:443/"}
    ) == {
        "status": "known",
        "value": "https://app.test",
    }
    assert normalize_origin(
        {"status": "unknown", "value": None}
    ) == {
        "status": "unknown",
        "value": None,
    }


@pytest.mark.parametrize(
    "origin,field",
    [
        ({"status": "known", "value": None}, "context.origin.value"),
        ({"status": "unknown", "value": "https://app.test"}, "context.origin.value"),
        (
            {
                "status": "known",
                "value": {
                    "status": "known",
                    "value": "https://app.test",
                },
            },
            "context.origin.value",
        ),
        ({"status": "other", "value": None}, "context.origin.status"),
        (
            {
                "status": "known",
                "value": "https://app.test",
                "fallback": "https://other.test",
            },
            "context.origin.fallback",
        ),
        (
            {"status": "known", "value": "https://user:secret@app.test"},
            "context.origin",
        ),
        (
            {"status": "known", "value": "https://app.test/path"},
            "context.origin",
        ),
        (
            {"status": "known", "value": "https://app.test?token=secret"},
            "context.origin",
        ),
    ],
)
def test_origin_rejects_incoherent_or_unsafe_envelopes_without_fallback(
    origin,
    field,
) -> None:
    with pytest.raises(JsContextInvalidError) as exc:
        normalize_origin(origin)
    assert exc.value.field == field


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "app.test",
        "https://user:secret@app.test",
        "https://app.test/path",
        "https://app.test?token=secret",
        "https://app.test#fragment",
    ],
)
def test_origin_requires_an_explicit_clean_http_origin(origin: str) -> None:
    with pytest.raises(JsContextInvalidError) as exc:
        normalize_origin(origin)
    assert exc.value.field == "context.origin"


def test_context_identity_separates_project_origin_unknown_and_auth() -> None:
    known = context_id_for(
        project_id="project-a",
        origin={"status": "known", "value": "https://app.test"},
        auth_ref="account-a",
    )
    assert known == context_id_for(
        project_id="project-a",
        origin={"status": "known", "value": "https://app.test"},
        auth_ref="account-a",
    )
    assert known.startswith("jsctx_")
    assert "account-a" not in known
    assert known != context_id_for(
        project_id="project-b",
        origin={"status": "known", "value": "https://app.test"},
        auth_ref="account-a",
    )
    assert known != context_id_for(
        project_id="project-a",
        origin={"status": "unknown", "value": None},
        auth_ref="account-a",
    )
    assert known != context_id_for(
        project_id="project-a",
        origin={"status": "known", "value": "https://app.test"},
        auth_ref="account-b",
    )


def test_unknown_origin_is_preserved_and_isolated() -> None:
    document = _document()
    document["context"]["origin"] = {"status": "unknown", "value": None}
    assert validate_document(document)["context"]["origin"] == {
        "status": "unknown",
        "value": None,
    }

    document["context"]["origin"] = {"status": "known", "value": None}
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(document)
    assert exc.value.field == "context.origin.value"


def test_every_cited_read_must_have_exactly_one_evidence_entry() -> None:
    missing = _document(evidence=[])
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(missing)
    assert exc.value.field == "behaviors[0].steps[0].read_ids[0]"

    duplicate = _document()
    duplicate["evidence"].append(copy.deepcopy(duplicate["evidence"][0]))
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(duplicate)
    assert exc.value.field == "evidence[1].read_id"


def test_evidence_may_record_missing_retention_without_inventing_a_hash() -> None:
    document = _document()
    document["context"]["coverage"] = {
        "status": "partial",
        "gaps": ["read_receipt_missing_or_foreign:read_a"],
    }
    document["evidence"][0].update(
        {
            "selector": {"type": "unknown", "id": "read_a"},
            "content_sha256": None,
            "range": {"start": 0, "end": 0},
            "redaction_policy": None,
            "delivery_status": "missing_or_foreign",
            "availability": "receipt_missing_or_foreign",
            "retention_status": "unknown",
            "artifact_ref": None,
            "limitations": ["read_receipt_missing_or_foreign"],
        }
    )
    validated = validate_document(document)
    assert validated["evidence"][0]["content_sha256"] is None


def test_evidence_delivery_retention_and_artifact_states_must_agree() -> None:
    mismatch = _document()
    mismatch["evidence"][0]["retention_status"] = "pending"
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(mismatch)
    assert exc.value.field == "evidence[0].availability"

    missing_ref = _document()
    missing_ref["evidence"][0]["artifact_ref"] = None
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(missing_ref)
    assert exc.value.field == "evidence[0].artifact_ref"


def test_complete_coverage_requires_retained_evidence_metadata() -> None:
    document = _document()
    document["evidence"][0].update(
        {
            "availability": "pending",
            "retention_status": "pending",
            "artifact_ref": None,
        }
    )

    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(document)

    assert exc.value.field == "context.coverage.status"


def test_empty_and_partial_coverage_require_explicit_gaps() -> None:
    empty = _document(
        behaviors=[],
        evidence=[],
    )
    empty["context"]["coverage"] = {"status": "empty", "gaps": []}
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(empty)
    assert exc.value.field == "context.coverage.gaps"

    empty["context"]["coverage"]["gaps"] = ["no_saved_behaviors"]
    assert validate_document(empty)["behaviors"] == []

    partial = _document()
    partial["context"]["coverage"] = {"status": "partial", "gaps": []}
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(partial)
    assert exc.value.field == "context.coverage.gaps"


def test_document_rejects_unknown_fields_and_unsafe_identifiers() -> None:
    extra = _document()
    extra["raw_source"] = "not allowed"
    with pytest.raises(JsContextInvalidError):
        validate_document(extra)

    unsafe = _document()
    unsafe["context"]["run_id"] = "../escape"
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(unsafe)
    assert exc.value.field == "context.run_id"

    boolean_version = _document()
    boolean_version["schema_version"] = True
    with pytest.raises(JsContextInvalidError) as exc:
        validate_document(boolean_version)
    assert exc.value.field == "schema_version"
