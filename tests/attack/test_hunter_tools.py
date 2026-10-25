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
from polymerhus.attack.hunting.spec_contract import TargetIdentity

PROJECT = "proj-1"
HUNT_KEY = "Service-account-registration__loop-1"
TARGET = TargetIdentity(url="https://a", unit_id="Service:a")


def _disc(fault: str = "f1", strategy: str = "probe") -> list[dict]:
    return [
        {"axis": "fault", "value": fault},
        {"axis": "technique", "value": strategy},
    ]


def _notes(store, **kwargs):
    return NotesTool(store=store, project_id=PROJECT, hunt_key=HUNT_KEY).invoke(kwargs)


def _hunts(store, **kwargs):
    return HuntsStoreTool(store=store, project_id=PROJECT, hunt_key=HUNT_KEY,
                          target_identity=TARGET).invoke(kwargs)


# --- #209: the coded teaching rejection --------------------------------------

def test_notes_missing_command_with_write_intent_is_a_teaching_rejection(tmp_path):
    """The 5-run defect (eval 2026-08-31, 22:17:17/22:17:47/22:19:53/22:27:36/
    22:28:30): the model emitted `{'action': 'append', ...}` without `command`.
    The tool must NOT raise - it returns a coded rejection teaching `command`.
    """
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_notes(store, action="append",
                            note_name="n", kind="freeform", body="b"))
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    assert "command" in out["detail"] and "write" in out["detail"]
    assert store.read_notes(PROJECT, parent_key=HUNT_KEY) == []


def test_notes_dict_evidence_is_a_teaching_rejection(tmp_path):
    """The 22:17:17 case: `evidence={'probe_refs': [...], 'fault_key': ...}` -
    a dict where the schema wants prose str. The rejection teaches `provenance`.
    """
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_notes(store, command="write", action="append",
                            note_name="n", kind="freeform",
                            body="b", evidence={"probe_refs": ["exec:SPA shell"],
                                                "hunt_key": HUNT_KEY}))
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    assert "provenance" in out["detail"]
    assert store.read_notes(PROJECT, parent_key=HUNT_KEY) == []


def test_notes_valid_write_with_typed_provenance_lands(tmp_path):
    """The corrected shape: `command="write"` + prose `evidence` + structured
    refs in the typed `provenance`. The note must persist with the provenance
    fields verbatim."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_notes(store, command="write", action="append",
                            note_name="n", kind="freeform",
                            body="decision trail",
                            evidence="prose evidence",
                            provenance={"source": "pod-export", "run_id": "r1",
                                        "verdict_stub": True,
                                        "probe_refs": ["exec:SPA shell"]}))
    assert out["ok"] is True
    notes = store.read_notes(PROJECT, parent_key=HUNT_KEY)
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
                            note_name="n", kind="freeform",
                            body="b", provenance={"source": "x",
                                                  "stray": True}))
    assert out["ok"] is False
    assert out["error"] == "notes_args_rejected"
    assert "provenance" in out["detail"]


def test_hunts_store_missing_command_with_write_intent_is_a_teaching_rejection(tmp_path):
    """The same required-`command` pattern on `hunts_store` (uniform contract):
    the one-spec write payload without `command` -> coded teaching rejection."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_hunts(store, spec={"status": "hypothesised",
         "target_identity": {"url": "https://a"},
         "discriminators": _disc("f1")}))
    assert out["ok"] is False
    assert out["error"] == "hunts_store_args_rejected"
    assert "command" in out["detail"] and "write" in out["detail"]
    assert store.read_specs(PROJECT, HUNT_KEY) == []


# --- the one-spec write and the finalize gate (F-025, S3 8.6-8.7) ------------

def test_hunts_store_write_payload_is_one_spec_object(tmp_path):
    """F-025: the write payload is exactly one `spec`; there is no top-level
    `specs` batch, and the file-name identity rides inside the spec."""
    fields = HuntsStoreTool(store=None, project_id=PROJECT).args_schema.model_fields
    assert "spec" in fields
    assert "specs" not in fields
    for gone in ("spec_id", "fault_keyword", "strategy_keyword", "mode"):
        assert gone not in fields, gone


def test_hunts_store_write_derives_the_file_name_from_one_spec(tmp_path):
    """The store derives `<fault_keyword>_<strategy_keyword>.yaml` in the
    symbolic layer; repeated one-spec writes build the set."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_hunts(store, command="write", spec={
        "status": "hypothesised",
        "target_identity": {"url": "https://a"},
        "discriminators": _disc("cwe1220-owner-binding"),
        "provenance": {"canonical_class": "CWE-1220"},
    }))
    assert out["ok"] is True
    assert out["specs"][0]["spec_id"] == "cwe-1220__cwe1220-owner-binding__probe"
    second = json.loads(_hunts(store, command="write", spec={
        "status": "hypothesised",
        "target_identity": {"url": "https://a"},
        "discriminators": _disc("reset-replay"),
    }))
    assert second["ok"] is True
    specs = store.read_specs(PROJECT, HUNT_KEY)
    assert [spec["discriminators"][0]["value"] for spec in specs] == [
        "cwe1220-owner-binding", "reset-replay"]
    assert specs[0]["provenance"]["canonical_class"] == "CWE-1220"


def test_hunts_store_one_spec_terminal_writes_upsert_then_finalize(tmp_path):
    """F-025: promote and declass one identity per call, then finalize. The
    terminal record is the durable whole-set closure."""
    store = HunterMemoryStore(root_dir=tmp_path)
    for fault in ("f1", "f2"):
        assert json.loads(_hunts(store, command="write", spec={
            "status": "hypothesised",
            "target_identity": {"url": "https://a"},
            "discriminators": _disc(fault)}))["ok"] is True
    assert json.loads(_hunts(store, command="write", spec={
        "status": "ratified",
        "target_identity": {"url": "https://a"},
        "discriminators": _disc("f1")}))["ok"] is True
    assert json.loads(_hunts(store, command="write", spec={
        "status": "dropped",
        "target_identity": {"url": "https://a"},
        "discriminators": _disc("f2")}))["ok"] is True
    out = json.loads(_hunts(store, command="finalize"))
    assert out["ok"] is True and out["finalized"] is True
    assert out["terminal"]["spec_ids"] == ["spec__f1__probe", "spec__f2__probe"]
    assert out["terminal"]["spec_statuses"] == {
        "spec__f1__probe": "ratified", "spec__f2__probe": "dropped"}
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__f1__probe")["status"] == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__f2__probe")["status"] == "dropped"


def test_hunts_store_write_missing_identity_is_a_coded_rejection(tmp_path):
    """A spec missing the second file-name keyword FAILS with a coded,
    field-naming rejection, so the model corrects on the retry."""
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_hunts(store, command="write", spec={
        "status": "hypothesised",
        "target_identity": {"url": "https://a"},
        "discriminators": _disc("cwe1220-owner-binding")[:1]}))
    assert out["ok"] is False
    assert out["error"] == "hunts_store_args_rejected"
    assert "discriminators" in " ".join(out["fields"])
    assert store.read_specs(PROJECT, HUNT_KEY) == []


def test_hunts_store_read_is_bound_to_the_loop_key(tmp_path):
    """S3 8.9: the hunt key is BOUND at construction; the read never accepts a
    key from the request, so the hunter can only address its own loop."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _hunts(store, command="write", spec={
        "status": "hypothesised",
        "target_identity": {"url": "https://a"},
        "discriminators": _disc("f1")})
    assert json.loads(_hunts(store, command="read"))["specs"][0]["status"] ==         "hypothesised"
    assert json.loads(_hunts(store, command="read",
                             statuses=["ratified"]))["specs"] == []


def test_hunts_store_finalize_omitting_a_draft_is_a_coded_rejection(tmp_path):
    """The F-017 quality repair moves to finalize: closing while a draft is
    still hypothesised returns the missing identity, so the hunter must ratify
    or drop each draft explicitly."""
    store = HunterMemoryStore(root_dir=tmp_path)
    for fault in ("f1", "f2"):
        assert json.loads(_hunts(store, command="write", spec={
            "status": "hypothesised",
            "target_identity": {"url": "https://a"},
            "discriminators": _disc(fault)}))["ok"] is True
    assert json.loads(_hunts(store, command="write", spec={
        "status": "ratified",
        "target_identity": {"url": "https://a"},
        "discriminators": _disc("f1")}))["ok"] is True
    out = json.loads(_hunts(store, command="finalize"))
    assert out["ok"] is False
    assert out["error"] == "incomplete_spec_set"
    assert out["missing"] == ["spec__f2__probe"]
    assert "drop" in out["detail"]
    assert store.read_terminal_set(PROJECT, HUNT_KEY) is None


def test_hunts_store_one_spec_write_allows_a_mixed_lifecycle_then_finalize_gates(tmp_path):
    """A one-spec promotion while a sibling is still hypothesised is legal;
    only finalize enforces the whole-set decision."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _hunts(store, command="write", spec={
        "status": "hypothesised", "target_identity": {"url": "https://a"},
        "discriminators": _disc("f1")})
    _hunts(store, command="write", spec={
        "status": "hypothesised", "target_identity": {"url": "https://a"},
        "discriminators": _disc("f2")})
    out = json.loads(_hunts(store, command="write", spec={
        "status": "ratified", "target_identity": {"url": "https://a"},
        "discriminators": _disc("f1")}))
    assert out["ok"] is True
    assert json.loads(_hunts(store, command="finalize"))["error"] ==         "incomplete_spec_set"


def test_hunts_store_refuses_a_write_after_finalize(tmp_path):
    store = HunterMemoryStore(root_dir=tmp_path)
    _hunts(store, command="write", spec={
        "status": "hypothesised", "target_identity": {"url": "https://a"},
        "discriminators": _disc("f1")})
    _hunts(store, command="write", spec={
        "status": "ratified", "target_identity": {"url": "https://a"},
        "discriminators": _disc("f1")})
    assert json.loads(_hunts(store, command="finalize"))["finalized"] is True
    out = json.loads(_hunts(store, command="write", spec={
        "status": "dropped", "target_identity": {"url": "https://a"},
        "discriminators": _disc("f2")}))
    assert out["ok"] is False
    assert out["error"] == "spec_set_finalized"
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__f2__probe") is None


def test_hunts_store_zero_spec_finalize_is_the_loop_completion_marker(tmp_path):
    store = HunterMemoryStore(root_dir=tmp_path)
    out = json.loads(_hunts(store, command="finalize"))
    assert out["ok"] is True and out["specs"] == []
    assert store.read_terminal_set(PROJECT, HUNT_KEY) is not None


# --- #209: the D84-22 rejected-call canon survives ----------------------------

def test_unknown_parameter_is_a_coded_teaching_rejection(tmp_path):
    """F-015: a field outside the typed contract is a coded rejection naming
    the unknown field and the accepted field set. The model evaluates the
    contract instead of decoding a bare pydantic error."""
    store = HunterMemoryStore(root_dir=tmp_path)
    notes = NotesTool(store=store, project_id=PROJECT)
    out = notes.invoke({"command": "write", "action": "append",
                        "note_name": "n",
                        "kind": "freeform", "body": "b", "bogus": 1})
    parsed = out if isinstance(out, dict) else json.loads(out)
    assert parsed["ok"] is False
    assert parsed["error"] == "notes_args_rejected"
    assert "bogus" in " ".join(parsed["fields"])
    hunts = HuntsStoreTool(store=store, project_id=PROJECT)
    out = hunts.invoke({"command": "write",
                        "spec": {"status": "hypothesised",
                                 "discriminators": _disc("f1"),
                                 "target_identity": {"url": "https://a"}},
                        "bogus": 1})
    parsed = json.loads(out) if isinstance(out, str) else out
    assert parsed["ok"] is False
    assert parsed["error"] == "hunts_store_args_rejected"
    assert "bogus" in " ".join(parsed["fields"])


def test_hunts_store_injects_the_bound_target_identity(tmp_path):
    """The target identity is symbolic: the tool binds the dispatch URL and
    unit id, so the hunter never authors either."""
    store = HunterMemoryStore(root_dir=tmp_path)
    tool = HuntsStoreTool(store=store, project_id=PROJECT, hunt_key=HUNT_KEY,
                          target_identity=TARGET)
    out = json.loads(tool.invoke({
        "command": "write",
        "spec": {"status": "hypothesised", "discriminators": _disc("f1")},
    }))
    assert out["ok"] is True
    body = store.read_spec(PROJECT, HUNT_KEY, "spec__f1__probe")
    assert body["target_identity"] == {
        "url": "https://a", "unit_id": "Service:a"}


def test_hunts_store_refuses_a_write_with_no_resolvable_target(tmp_path):
    store = HunterMemoryStore(root_dir=tmp_path)
    tool = HuntsStoreTool(store=store, project_id=PROJECT, hunt_key=HUNT_KEY)
    out = json.loads(tool.invoke({
        "command": "write",
        "spec": {"status": "hypothesised", "discriminators": _disc("f1")},
    }))
    assert out["ok"] is False
    assert out["error"] == "hunts_store_write_rejected"
    assert "target_identity.url" in " ".join(out["fields"])


def test_hunts_store_injects_the_bound_run_id_into_spec_provenance(tmp_path):
    """F-017: every spec carries the hunting run id, so a consumed spec with no
    terminal PodExport can be attributed to the current run on resume. The model
    never has to author a run id; the tool binds it."""
    store = HunterMemoryStore(root_dir=tmp_path)
    tool = HuntsStoreTool(store=store, project_id=PROJECT,
                          hunt_key=HUNT_KEY, run_id="run-42")
    out = json.loads(tool.invoke({
        "command": "write",
        "spec": {"status": "hypothesised",
                 "target_identity": {"url": "https://a"},
                 "discriminators": _disc("f1")},
    }))
    assert out["ok"] is True
    stored = store.read_spec(PROJECT, HUNT_KEY, "spec__f1__probe")
    assert stored["provenance"]["run_id"] == "run-42"


# --- S3 8.7: the skill pair is bound ------------------------------------------

def test_build_hunter_tools_binds_the_skill_pair(tmp_path):
    """S3 8.7: the hunter's surface carries `skill_list` / `skill_load` over the
    web-vulnerability suite, so the loop's suite class can select the class
    skill."""
    from polymerhus.attack.hunting.hunter_tools import build_hunter_tools

    tools = build_hunter_tools(
        store=HunterMemoryStore(root_dir=tmp_path), project_id=PROJECT,
        hunt_key=HUNT_KEY)
    names = [tool.name for tool in tools]
    assert "skill_list" in names and "skill_load" in names
    assert names.index("skill_list") < names.index("skill_load")
    # the always-bound fail-open pair answers a coded gap, never a raise
    skill_list = tools[names.index("skill_list")]
    missing = skill_list.invoke({})
    filtered = skill_list.invoke({"filter": "idor"})
    assert missing["error"] == "skill_filter_required"
    assert filtered["suite_gap"] is True


# --- #292: the conciseness directive in the hunter tool descriptions -----------

def test_hunter_store_and_notes_descriptions_carry_the_conciseness_directive():
    """The hunter's `hunts_store` / `notes` descriptions carry the single-sourced
    conciseness directive verbatim (#292), so the writing cap reaches the hunter
    model."""
    from polymerhus.attack.hunting.llm import HUNTING_CONCISENESS_DIRECTIVE

    for tool in (HuntsStoreTool(store=None, project_id=PROJECT),
                 NotesTool(store=None, project_id=PROJECT)):
        assert HUNTING_CONCISENESS_DIRECTIVE in tool.description, tool.name
