"""Unit tier: the analysis `notes` tool (T3).

The analysis `notes` tool is the SHARED `StoreNotesTool` (`app.memory.tool_contract`)
bound over the analysis `AnalysisMemoryStore` through an explicit `NotesFieldMap`
and the analysis args schema. These tests pin the binding (no destination field),
the coded teaching rejection, the emitted schema, and the fail-open read - no LLM.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from polymerhus.analysis.memory import (
    AnalysisMemoryStore,
    AnalysisNotesArgs,
    notes_tool_for,
)
from polymerhus.app.memory.tool_contract import NotesFieldMap, StoreNotesTool

PROJECT = "proj-1"


def _tool(tmp_path, **kw):
    return notes_tool_for(store=AnalysisMemoryStore(root_dir=tmp_path),
                          project_id=PROJECT, **kw)


def _params(tool):
    return convert_to_openai_tool(tool)["function"]["parameters"]


def _enum(prop):
    if "enum" in prop:
        return prop["enum"]
    for sub in prop.get("anyOf", []):
        if "enum" in sub:
            return sub["enum"]
    return None


def test_the_bound_tool_is_the_shared_implementation(tmp_path):
    assert isinstance(_tool(tmp_path), StoreNotesTool)


def test_write_then_read_round_trips_through_the_tool(tmp_path):
    tool = _tool(tmp_path)
    out = json.loads(tool.invoke({
        "command": "write", "action": "append", "unit": "checkout",
        "note_name": "cart", "kind": "data", "body": "cart is checkout-owned"}))
    assert out["ok"] is True and out["key"] == "checkout:cart"

    read = json.loads(tool.invoke({"command": "read", "unit": "checkout"}))
    assert [n["note_name"] for n in read["notes"]] == ["cart"]


def test_read_returns_earlier_units_notes_without_a_unit_filter(tmp_path):
    """Read-back is per-project: a later unit sees earlier units' notes."""
    tool = _tool(tmp_path)
    tool.invoke({"command": "write", "action": "append", "unit": "checkout",
                 "note_name": "cart", "kind": "data", "body": "x"})
    tool.invoke({"command": "write", "action": "append", "unit": "search",
                 "note_name": "index", "kind": "system", "body": "y"})
    read = json.loads(tool.invoke({"command": "read"}))
    assert {n["unit"] for n in read["notes"]} == {"checkout", "search"}


def test_empty_call_teaches_the_discriminator(tmp_path):
    out = json.loads(_tool(tmp_path).invoke({}))
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    assert "command" in out["detail"]


def test_read_on_an_absent_store_degrades_fail_open():
    tool = notes_tool_for(store=None, project_id=PROJECT)
    out = json.loads(tool.invoke({"command": "read"}))
    assert out["notes"] == []
    assert out.get("error")


def test_schema_carries_the_enums_and_descriptions(tmp_path):
    params = _params(_tool(tmp_path))
    assert _enum(params["properties"]["command"]) == ["read", "write"]
    assert _enum(params["properties"]["action"]) == ["append", "update", "delete"]
    assert _enum(params["properties"]["kind"]) == [
        "assignment", "system", "data", "refusal", "open_question"]
    for name, prop in params["properties"].items():
        assert prop.get("description"), f"{name} has no description"


def test_schema_has_no_destination_field(tmp_path):
    params = _params(_tool(tmp_path))
    for banned in ("destination", "path", "store", "file", "filename"):
        assert banned not in params["properties"], banned


def test_field_map_naming_an_absent_field_fails_loudly(tmp_path):
    from polymerhus.app.memory.tool_contract import build_notes_tool

    with pytest.raises(ValueError, match="absent"):
        build_notes_tool(
            None, args_schema=AnalysisNotesArgs,
            field_map=NotesFieldMap(action="nope", note="body"),
            name="notes", description="bad",
        )
