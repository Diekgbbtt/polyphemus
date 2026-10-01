"""Unit tier: the shared hunting tool contract (#293, building on #209).

The orchestrator's `hunts_store` / `notes` are typed `BaseTool` schemas (not
inferred `@tool` closures): every field carries a description, the
discriminators are `Literal` enums, and a call that omits the discriminator
returns a CODED teaching rejection naming the discriminator and the known
commands - never a bare pydantic `ValidationError`. The `notes` implementation
is SINGLE-SOURCED (`tool_contract.build_notes_tool`) and bound at both the
orchestrator and hunter seams through a caller-bound store handle, so the
filesystem destination is derived from the handle and never a request field.
No live target, no LLM, no DB.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from polymerhus.attack.hunting.actors import (
    OrchestratorNotesArgs,
    HuntStoreNotesHandle,
    build_orchestrator_tool_surface,
)
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunter_tools import (
    HunterMemoryNotesHandle,
    NotesArgs,
    NotesTool,
    notes_tool_for,
)
from polymerhus.attack.hunting.hunt_orchestrator import (
    OrchestratorTools,
    ReadOnlyGraphView,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.tool_contract import (
    NotesFieldMap,
    StoreNotesTool,
    build_notes_tool,
)

PROJECT = "proj-1"
FAULT_KEY = "Service:account-registration_CWE-266_Privilege Escalation"

_ORCH_FIELD_MAP = NotesFieldMap(
    key="key", read_key="key", action="option", note="note",
    note_id="note_id", attributes="attributes",
)
_HUNTER_FIELD_MAP = NotesFieldMap(
    key=None, read_key=None, action="action", note="body",
    note_id=None, attributes="attributes", key_keyword="key_keyword",
    body_keyword="body_keyword",
    passthrough=("note_name", "kind", "evidence", "provenance"),
)


def _surface(store):
    tools = OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView(PROJECT, read_fn=lambda cypher, params: []),
    )
    return {
        t.name: t
        for t in build_orchestrator_tool_surface(
            tools, run_id="run-1", project_id=PROJECT)
    }


def _params(tool):
    return convert_to_openai_tool(tool)["function"]["parameters"]


def _enum(prop):
    """The enum values of a property, whether rendered inline or under an
    `anyOf` (a `Literal[...] | None` union)."""
    if "enum" in prop:
        return prop["enum"]
    for sub in prop.get("anyOf", []):
        if "enum" in sub:
            return sub["enum"]
    return None


# --- the coded teaching rejection (the #286 empty-argument defect) -------------


def test_orchestrator_hunts_store_empty_call_teaches_the_discriminator(tmp_path):
    """#286: an empty-argument `hunts_store` call must return a CODED teaching
    rejection naming the missing discriminator and the known commands, never a
    bare `1 validation error for hunts_store`."""
    out = _surface(HuntStore(tmp_path))["hunts_store"].invoke({})
    assert isinstance(out, dict)
    assert out["ok"] is False
    assert out["error"] == "hunts_store_args_rejected"
    detail = out["detail"]
    assert "cmd" in detail
    assert "read" in detail and "write" in detail


def test_orchestrator_notes_empty_call_teaches_the_discriminator(tmp_path):
    out = _surface(HuntStore(tmp_path))["notes"].invoke({})
    assert isinstance(out, dict)
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    detail = out["detail"]
    assert "cmd" in detail
    assert "read" in detail and "write" in detail


def test_orchestrator_notes_invalid_option_is_a_coded_rejection(tmp_path):
    """An invalid enum value is a rejected call the model can act on, not a
    raise - and nothing is persisted."""
    store = HuntStore(tmp_path)
    out = _surface(store)["notes"].invoke(
        {"cmd": "write", "option": "append2", "key": FAULT_KEY, "note": "n"})
    assert isinstance(out, dict)
    assert "error" in out
    assert store.read_notes(PROJECT) == []


def test_orchestrator_notes_write_without_option_is_rejected(tmp_path):
    """A write that states no `option` must not default to append: it is a
    rejected call and nothing is persisted (the contract's write discriminator
    is required)."""
    store = HuntStore(tmp_path)
    out = _surface(store)["notes"].invoke(
        {"cmd": "write", "key": FAULT_KEY, "note": "n"})
    assert isinstance(out, dict)
    assert "error" in out
    assert store.read_notes(PROJECT) == []


# --- the emitted JSON schema carries the enums + descriptions ------------------


def test_orchestrator_hunts_store_schema_carries_enum_and_descriptions(tmp_path):
    params = _params(_surface(HuntStore(tmp_path))["hunts_store"])
    assert params["properties"]["cmd"]["enum"] == ["read", "write"]
    for name, prop in params["properties"].items():
        assert prop.get("description"), f"{name} has no description"


def test_orchestrator_notes_schema_carries_enum_and_descriptions(tmp_path):
    params = _params(_surface(HuntStore(tmp_path))["notes"])
    assert _enum(params["properties"]["cmd"]) == ["read", "write"]
    assert _enum(params["properties"]["option"]) == [
        "append", "update", "delete"]
    for name, prop in params["properties"].items():
        assert prop.get("description"), f"{name} has no description"


# --- one shared notes implementation, bound through a caller-bound handle ------


def test_shared_notes_builder_routes_writes_to_the_bound_store(tmp_path):
    """`build_notes_tool` binds the SAME implementation to two different store
    handles: a write through each lands in ITS store and nowhere else. The
    destination is the handle, never a request field."""
    hunt = HuntStore(tmp_path)
    hunter = HunterMemoryStore(root_dir=tmp_path)
    orchestrator_notes = build_notes_tool(
        HuntStoreNotesHandle(hunt, PROJECT, None),
        args_schema=OrchestratorNotesArgs, field_map=_ORCH_FIELD_MAP,
        name="notes", description="orchestrator notes",
        discriminator="cmd", as_json=False, rejection_name="notes",
    )
    hunter_notes = build_notes_tool(
        HunterMemoryNotesHandle(hunter, PROJECT, FAULT_KEY),
        args_schema=NotesArgs, field_map=_HUNTER_FIELD_MAP,
        name="notes", description="hunter notes",
        discriminator="command", as_json=True, rejection_name="notes",
        write_intent_fields=("action", "note_name", "kind", "body"),
    )
    assert isinstance(orchestrator_notes, StoreNotesTool)
    assert isinstance(hunter_notes, StoreNotesTool)

    orchestrator_notes.invoke(
        {"cmd": "write", "option": "append", "key": FAULT_KEY,
         "note": "orchestrator note"})
    hunter_notes.invoke(
        {"command": "write", "action": "append",
         "note_name": "n", "kind": "freeform", "body": "hunter note"})

    assert [n["note"] for n in hunt.read_notes(PROJECT, FAULT_KEY)] == [
        "orchestrator note"]
    assert [n["body"] for n in hunter.read_notes(PROJECT)] == ["hunter note"]
    # no cross-talk: the hunter's write never reached the orchestrator store
    assert [n["note"] for n in hunt.read_notes(PROJECT, FAULT_KEY)] == [
        "orchestrator note"]
    assert [n["body"] for n in hunter.read_notes(PROJECT)] == ["hunter note"]


def test_shared_notes_builder_is_used_at_the_hunter_seam(tmp_path):
    """The hunter seam binds the shared implementation: `NotesTool` IS a
    `StoreNotesTool`, so both seams ride one write algorithm."""
    assert issubclass(NotesTool, StoreNotesTool)


def test_orchestrator_notes_schema_has_no_destination_field(tmp_path):
    params = _params(_surface(HuntStore(tmp_path))["notes"])
    for banned in ("destination", "path", "store", "file", "filename"):
        assert banned not in params["properties"], banned


# --- the explicit field map (no alias guessing) --------------------------------


def test_builder_rejects_a_field_map_naming_an_absent_schema_field(tmp_path):
    """A field map that names a field the bound schema does not declare fails
    LOUDLY at construction (CODING_STANDARD 5: no path left to chance), instead
    of silently reading the wrong field."""
    with pytest.raises(ValueError, match="action"):
        build_notes_tool(
            HunterMemoryNotesHandle(HunterMemoryStore(root_dir=tmp_path),
                                    PROJECT, ""),
            args_schema=OrchestratorNotesArgs, field_map=_HUNTER_FIELD_MAP,
            name="notes", description="mismatched", discriminator="cmd",
        )


# --- the hunter's bound config identity (#298) ---------------------------------


def test_hunter_notes_tool_is_bound_to_its_own_config(tmp_path):
    """The hunt's config key is BOUND at construction (#298): two tools bound to
    different configs read and write ONLY their own folder. The model never
    supplies the key, and there is no cross-config read."""
    store = HunterMemoryStore(root_dir=tmp_path)
    key_a = "Service:aaa_CWE-352_CSRF"
    key_b = "Service:bbb_CWE-352_CSRF"
    tool_a = notes_tool_for(store=store, project_id=PROJECT, fault_key=key_a)
    tool_b = notes_tool_for(store=store, project_id=PROJECT, fault_key=key_b)
    tool_a.invoke({"command": "write", "action": "append",
                   "note_name": "a", "kind": "freeform", "body": "note-a"})
    tool_b.invoke({"command": "write", "action": "append",
                   "note_name": "b", "kind": "freeform", "body": "note-b"})

    read_a = json.loads(tool_a.invoke({"command": "read"}))
    assert [n["body"] for n in read_a["notes"]] == ["note-a"]
    read_b = json.loads(tool_b.invoke({"command": "read"}))
    assert [n["body"] for n in read_b["notes"]] == ["note-b"]
    # the config key is not a request field at all
    assert "fault_key" not in NotesArgs.model_fields
    assert "parent_key" not in NotesArgs.model_fields


def test_hunter_notes_missing_command_names_the_action_option(tmp_path):
    """#209 restored: the hunter's missing-`command` rejection names `action`
    as the write option, not the command."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(NotesTool(store=store, project_id=PROJECT,
                               fault_key=FAULT_KEY).invoke(
        {"action": "append", "note_name": "n",
         "kind": "freeform", "body": "b"}))
    assert out["error"] == "notes_args_rejected"
    assert "command" in out["detail"]
    assert "action" in out["detail"]
    assert store.read_notes(PROJECT) == []
