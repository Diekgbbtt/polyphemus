"""Unit tier: the shared hunting tool contract (#293, building on #209).

The threat modeller's `hunts_store` / `notes` are typed `BaseTool` schemas (not
inferred `@tool` closures): every field carries a description, the
discriminators are `Literal` enums, and a call that omits the discriminator
returns a CODED teaching rejection naming the discriminator and the known
commands - never a bare pydantic `ValidationError`. The `notes` implementation
is SINGLE-SOURCED (`tool_contract.build_notes_tool`) and bound at both the
modeller and hunter seams through a caller-bound store handle, so the
filesystem destination is derived from the handle and never a request field.
No live target, no LLM, no DB.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunter_tools import (
    HunterMemoryNotesHandle,
    NotesArgs,
    NotesTool,
    notes_tool_for,
)
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller_tools import (
    ModellerNotesArgs,
    ModellerNotesHandle,
    ModellerTools,
    build_modeller_tool_surface,
)
from polymerhus.attack.hunting.tool_contract import (
    NotesFieldMap,
    StoreNotesTool,
    build_notes_tool,
)

PROJECT = "proj-1"
UNIT = "Service:account-registration"
FAULT_KEY = "Service:account-registration_CWE-266_Privilege Escalation"

_MODELLER_FIELD_MAP = NotesFieldMap(
    key=None, read_key="key", action="option", note="body",
    note_id="note_id", attributes="attributes",
    note_name="note_name", kind="kind", evidence="evidence",
)
_HUNTER_FIELD_MAP = NotesFieldMap(
    key=None, read_key=None, action="action", note="body",
    note_id=None, attributes="attributes", key_keyword="key_keyword",
    body_keyword="body_keyword",
    note_name="note_name", kind="kind", evidence="evidence",
    passthrough=("provenance",),
)


def _surface(store):
    tools = ModellerTools(threat_store=store, project_id=PROJECT, run_id="run-1")
    return build_modeller_tool_surface(PROJECT, UNIT, tools)


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


def test_modeller_hunts_store_empty_call_teaches_the_discriminator(tmp_path):
    """#286: an empty-argument `hunts_store` call must return a CODED teaching
    rejection naming the missing discriminator and the known commands, never a
    bare `1 validation error for hunts_store`."""
    out = _surface(ThreatModelStore(root_dir=tmp_path))["hunts_store"].invoke({})
    assert isinstance(out, dict)
    assert out["ok"] is False
    assert out["error"] == "hunts_store_args_rejected"
    detail = out["detail"]
    assert "cmd" in detail
    assert "read" in detail and "write" in detail


def test_modeller_notes_empty_call_teaches_the_discriminator(tmp_path):
    """A write-intent call that omits the discriminator is a CODED teaching
    rejection naming `cmd` and the known commands (the shared base's rule).
    A wholly EMPTY call is a genuinely unknown request and keeps the
    rejected-call canon (the modeller's notes require a write intent)."""
    out = _surface(ThreatModelStore(root_dir=tmp_path))["notes"].invoke(
        {"option": "append"})
    assert isinstance(out, dict)
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    detail = out["detail"]
    assert "cmd" in detail
    assert "read" in detail and "write" in detail


def test_modeller_notes_invalid_option_is_a_coded_rejection(tmp_path):
    """An invalid enum value is a rejected call the model can act on, not a
    raise - and nothing is persisted."""
    store = ThreatModelStore(root_dir=tmp_path)
    out = _surface(store)["notes"].invoke(
        {"cmd": "write", "option": "append2", "note_name": "n", "body": "n"})
    assert isinstance(out, dict)
    assert "error" in out
    assert store.read_notes(PROJECT, UNIT) == []


def test_modeller_notes_write_without_option_is_rejected(tmp_path):
    """A write that states no `option` must not default to append: it is a
    rejected call and nothing is persisted (the contract's write discriminator
    is required)."""
    store = ThreatModelStore(root_dir=tmp_path)
    out = _surface(store)["notes"].invoke(
        {"cmd": "write", "note_name": "n", "body": "n"})
    assert isinstance(out, dict)
    assert "error" in out
    assert store.read_notes(PROJECT, UNIT) == []


# --- the emitted JSON schema carries the enums + descriptions ------------------


def test_modeller_hunts_store_schema_carries_enum_and_descriptions(tmp_path):
    params = _params(_surface(ThreatModelStore(root_dir=tmp_path))["hunts_store"])
    assert params["properties"]["cmd"]["enum"] == ["read", "write"]
    for name, prop in params["properties"].items():
        assert prop.get("description"), f"{name} has no description"


def test_modeller_notes_schema_carries_enum_and_descriptions(tmp_path):
    params = _params(_surface(ThreatModelStore(root_dir=tmp_path))["notes"])
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
    from polymerhus.attack.hunting.threat_model_store import sanitise_unit_name

    models = ThreatModelStore(root_dir=tmp_path)
    hunter = HunterMemoryStore(root_dir=tmp_path)
    modeller_notes = build_notes_tool(
        ModellerNotesHandle(models, PROJECT, UNIT),
        args_schema=ModellerNotesArgs, field_map=_MODELLER_FIELD_MAP,
        name="notes", description="modeller notes",
        discriminator="cmd", as_json=False, rejection_name="notes",
    )
    hunter_notes = build_notes_tool(
        HunterMemoryNotesHandle(hunter, PROJECT, FAULT_KEY),
        args_schema=NotesArgs, field_map=_HUNTER_FIELD_MAP,
        name="notes", description="hunter notes",
        discriminator="command", as_json=True, rejection_name="notes",
        write_intent_fields=("action", "note_name", "kind", "body"),
    )
    assert isinstance(modeller_notes, StoreNotesTool)
    assert isinstance(hunter_notes, StoreNotesTool)

    modeller_notes.invoke(
        {"cmd": "write", "option": "append", "note_name": "m",
         "kind": "freeform", "body": "modeller note"})
    hunter_notes.invoke(
        {"command": "write", "action": "append",
         "note_name": "n", "kind": "freeform", "body": "hunter note"})

    unit_name = sanitise_unit_name(UNIT)
    assert [n["body"] for n in models.read_notes(PROJECT, unit_name)] == [
        "modeller note"]
    assert [n["body"] for n in hunter.read_notes(PROJECT)] == ["hunter note"]
    # no cross-talk: the hunter's write never reached the modeller store
    assert [n["body"] for n in models.read_notes(PROJECT, unit_name)] == [
        "modeller note"]
    assert [n["body"] for n in hunter.read_notes(PROJECT)] == ["hunter note"]


def test_shared_notes_builder_is_used_at_the_hunter_seam(tmp_path):
    """The hunter seam binds the shared implementation: `NotesTool` IS a
    `StoreNotesTool`, so both seams ride one write algorithm."""
    assert issubclass(NotesTool, StoreNotesTool)


def test_modeller_notes_schema_has_no_destination_field(tmp_path):
    params = _params(_surface(ThreatModelStore(root_dir=tmp_path))["notes"])
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
            args_schema=ModellerNotesArgs, field_map=_HUNTER_FIELD_MAP,
            name="notes", description="mismatched", discriminator="cmd",
        )


# --- the hunter's bound config identity (#298) ---------------------------------


def test_hunter_notes_tool_is_bound_to_its_own_config(tmp_path):
    """The hunt key is BOUND at construction (S3 8.9): two tools bound to
    different threats read and write ONLY their own folder. The model never
    supplies the key, and there is no cross-threat read."""
    store = HunterMemoryStore(root_dir=tmp_path)
    key_a = "Service-aaa__threat-1"
    key_b = "Service-bbb__threat-1"
    tool_a = notes_tool_for(store=store, project_id=PROJECT, hunt_key=key_a)
    tool_b = notes_tool_for(store=store, project_id=PROJECT, hunt_key=key_b)
    tool_a.invoke({"command": "write", "action": "append",
                   "note_name": "a", "kind": "freeform", "body": "note-a"})
    tool_b.invoke({"command": "write", "action": "append",
                   "note_name": "b", "kind": "freeform", "body": "note-b"})

    read_a = json.loads(tool_a.invoke({"command": "read"}))
    assert [n["body"] for n in read_a["notes"]] == ["note-a"]
    read_b = json.loads(tool_b.invoke({"command": "read"}))
    assert [n["body"] for n in read_b["notes"]] == ["note-b"]
    # the hunt key is not a request field at all
    assert "hunt_key" not in NotesArgs.model_fields
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
