"""Unit tier: the hunter tool surface contract (#209).

The store/notes tools carry the D84-22 coded teaching rejection: a call that
omits the required `command` discriminator (write-intent fields present) or
passes a parameter of the wrong type (a dict-valued `evidence`) is REJECTED with
a coded JSON error naming the exact fix - the model self-corrects on the retry
instead of burning the turn on a bare `tool_failed`. `notes.provenance` is a
TYPED `NoteProvenance` sub-model (the JSON schema that rides the request
declares it). No live target, no LLM, no DB.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from polymerhus.attack.hunting.hunter_tools import (
    HuntsStoreTool,
    NoteProvenance,
    NotesTool,
)
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore

PROJECT = "proj-1"
FAULT_KEY = "Service:account-registration_CWE-266_Privilege Escalation"


def _notes(store, **kwargs):
    return NotesTool(store=store, project_id=PROJECT).invoke(kwargs)


def _hunts(store, **kwargs):
    return HuntsStoreTool(store=store, project_id=PROJECT).invoke(kwargs)


# --- #209: the coded teaching rejection --------------------------------------

def test_notes_missing_command_with_write_intent_is_a_teaching_rejection(tmp_path):
    """The 5-run defect (eval 2026-08-31, 22:17:17/22:17:47/22:19:53/22:27:36/
    22:28:30): the model emitted `{'action': 'append', ...}` without `command`.
    The tool must NOT raise - it returns a coded rejection teaching `command`.
    """
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_notes(store, action="append", fault_key=FAULT_KEY,
                            note_name="n", kind="freeform", body="b"))
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    assert "command" in out["detail"] and "write" in out["detail"]
    assert store.read_notes(PROJECT, parent_key=FAULT_KEY) == []


def test_notes_dict_evidence_is_a_teaching_rejection(tmp_path):
    """The 22:17:17 case: `evidence={'probe_refs': [...], 'fault_key': ...}` -
    a dict where the schema wants prose str. The rejection teaches `provenance`.
    """
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_notes(store, command="write", action="append",
                            fault_key=FAULT_KEY, note_name="n", kind="freeform",
                            body="b", evidence={"probe_refs": ["exec:SPA shell"],
                                                "fault_key": FAULT_KEY}))
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    assert "provenance" in out["detail"]
    assert store.read_notes(PROJECT, parent_key=FAULT_KEY) == []


def test_notes_valid_write_with_typed_provenance_lands(tmp_path):
    """The corrected shape: `command="write"` + prose `evidence` + structured
    refs in the typed `provenance`. The note must persist with the provenance
    fields verbatim."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_notes(store, command="write", action="append",
                            fault_key=FAULT_KEY, note_name="n", kind="freeform",
                            body="decision trail",
                            evidence="prose evidence",
                            provenance={"source": "pod-export", "run_id": "r1",
                                        "verdict_stub": True,
                                        "probe_refs": ["exec:SPA shell"]}))
    assert out["ok"] is True
    notes = store.read_notes(PROJECT, parent_key=FAULT_KEY)
    assert len(notes) == 1
    assert notes[0]["evidence"] == "prose evidence"
    assert notes[0]["provenance"]["source"] == "pod-export"
    assert notes[0]["provenance"]["probe_refs"] == ["exec:SPA shell"]


def test_notes_args_schema_declares_the_typed_provenance(tmp_path):
    """The typed structure rides the tool-calling protocol's own schema: the
    rendered JSON schema must declare `provenance` with its fields, never a
    bare object."""
    schema = NotesTool(store=None, project_id=PROJECT).args_schema.model_json_schema()
    prov = schema["properties"]["provenance"]
    # the schema references the typed sub-model definition (nullable)
    ref = prov.get("anyOf", [{}])[0].get("$ref") or prov.get("$ref")
    assert ref, prov
    name = ref.split("/")[-1]
    props = schema.get("$defs", {}).get(name, {}).get("properties", {})
    assert "source" in props and "run_id" in props
    assert "verdict_stub" in props and "probe_refs" in props
    assert props["probe_refs"]["type"] == "array"
    assert schema["$defs"][name].get("additionalProperties") is False


def test_note_provenance_is_extra_forbid(tmp_path):
    """D84-22: the typed provenance rejects a stray key like a bare dict never
    could - the contract stays the validator."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_notes(store, command="write", action="append",
                            fault_key=FAULT_KEY, note_name="n", kind="freeform",
                            body="b", provenance={"source": "x",
                                                  "stray": True}))
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    assert "provenance" in out["detail"]


def test_hunts_store_missing_command_with_write_intent_is_a_teaching_rejection(tmp_path):
    """The same required-`command` pattern on `hunts_store` (uniform contract):
    write-intent fields without `command` -> coded teaching rejection."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_hunts(store, mode="create", fault_key=FAULT_KEY,
                            fault_keyword="f1", strategy_keyword="probe",
                            spec={"fault_id": "F1", "status": "hypothesised"}))
    assert out["ok"] is False
    assert out["error"] == "hunts_store_args_rejected"
    assert "command" in out["detail"] and "write" in out["detail"]
    assert store.read_specs(PROJECT, FAULT_KEY) == []


# --- #209: the D84-22 rejected-call canon survives ----------------------------

def test_unknown_parameter_still_raises_the_rejected_call(tmp_path):
    """#209: only the KNOWN drift shapes are translated to a teaching
    rejection. An unknown parameter keeps the D84-22 canon - it FAILS as a
    rejected call (raises ValidationError), never a silent accept."""
    store = HunterMemoryStore(root_dir=tmp_path)
    notes = NotesTool(store=store, project_id=PROJECT)
    with pytest.raises(ValidationError):
        notes.invoke({"command": "write", "action": "append",
                      "fault_key": FAULT_KEY, "note_name": "n",
                      "kind": "freeform", "body": "b", "bogus": 1})
    hunts = HuntsStoreTool(store=store, project_id=PROJECT)
    with pytest.raises(ValidationError):
        hunts.invoke({"command": "write", "mode": "create",
                      "fault_key": FAULT_KEY, "fault_keyword": "f1",
                      "strategy_keyword": "probe",
                      "spec": {"status": "hypothesised"}, "bogus": 1})