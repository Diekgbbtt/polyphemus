from lightrag.context import (
    build_reference_registry,
    from_raw_response,
    normalize_citations,
    provenance_completeness,
    serialize_context,
)


RAW = {
    "status": "success",
    "message": "ok",
    "data": {
        "entities": [],
        "relationships": [],
        "chunks": [
            {
                "reference_id": "doc-1",
                "file_path": "WSTG-ATHZ/x.md",
                "content": "chunk text",
            },
            {
                "reference_id": "doc-2",
                "file_path": "WSTG-APIT/y.md",
                "content": "more text",
            },
        ],
        "references": [
            {"reference_id": "doc-1", "file_path": "WSTG-ATHZ/x.md"},
            {"reference_id": "doc-2", "file_path": "WSTG-APIT/y.md"},
        ],
    },
    "metadata": {"processing_info": {"final_chunks_count": 2}},
}


def test_from_raw_response_counts_and_context():
    context = from_raw_response(RAW)
    assert len(context.chunks) == 2 and len(context.references) == 2
    assert context.final_chunks_count == 2
    assert context.is_empty is False
    assert provenance_completeness(context) == 1.0


def test_registry_orders_references_and_maps_bracket_indices():
    context = from_raw_response(RAW)
    registry = build_reference_registry(
        context, evidence_refs=["l0:SIM-01:1"]
    )
    assert registry.allowed_ids == ["doc-1", "doc-2", "l0:SIM-01:1"]
    assert registry.alias_to_id["[1]"] == "doc-1"
    assert registry.alias_to_id["[2]"] == "doc-2"


def test_normalize_citations_resolves_aliases_and_rejects_invented():
    context = from_raw_response(RAW)
    registry = build_reference_registry(context)
    resolved, rejected = normalize_citations(
        ["[1]", "doc-2", "fabricated-99"], registry
    )
    assert resolved == ["doc-1", "doc-2"]
    assert rejected == ["fabricated-99"]


def test_serialize_context_uses_reference_ids():
    context = from_raw_response(RAW)
    text = serialize_context(context)
    assert "[doc-1] WSTG-ATHZ/x.md: chunk text" in text
