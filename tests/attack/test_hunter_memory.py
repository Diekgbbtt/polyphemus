"""Unit tier: the hunter-memory spec-set store (S3 8.6-8.9, T6 #379).

Pure filesystem mechanics - no Neo4j, no LLM. Pins the threat-driven store's
contract: the batched `specs` set write, the `{hypothesised, ratified,
dropped}` lifecycle, the threat dispatch store key / folder / derived file name,
the move-aware write (the #205 rule), the reduced-D4-at-every-status body, the
typed skill-procedure provenance, and the atomic/bounded notes surface.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
import yaml

from polymerhus.attack.hunting import hunter_memory
from polymerhus.attack.hunting.hunter_memory import (
    DuplicateSpecError,
    HunterMemoryStore,
    IncompleteSpecSetError,
    spec_identifier,
)

PROJECT = "proj-1"
HUNT_KEY = "Service-account-registration__threat-1"
SPEC_ID = "spec__registration__probe"


def _spec(*, status: str = "hypothesised", fault_keyword: str = "registration",
          strategy_keyword: str = "probe", **extra) -> dict:
    """A reduced-D4 spec payload with the two discriminating instances the
    older tests named as `fault_keyword` / `strategy_keyword`, translated to
    the new `{axis, value}` contract."""
    body = {
        "status": status,
        "discriminators": [
            {"axis": "fault", "value": fault_keyword},
            {"axis": "technique", "value": strategy_keyword},
        ],
        "target_identity": {"url": "http://target", "unit_id": "Service:a"},
        "verification_symptoms": ["a foreign item renders"],
        "assumptions": ["the ownership check is absent"],
        "rationale": "an anonymous caller reads another user's item",
        "parent_spec_ref": None,
        "provenance": {"threat_id": "threat-1", "unit_id": "Service:a"},
    }
    body.update(extra)
    return body


def _spec_file(tmp_path, side: str, spec_id: str = SPEC_ID) -> Path:
    return (
        tmp_path / PROJECT / "hunting" / "hunter" / "test-specs" / HUNT_KEY
        / side / f"{spec_id}.yaml"
    )


# --- the terminal-set record (F-025 / F-022) ----------------------------------

def test_a_one_spec_promotion_does_not_require_the_whole_set(tmp_path):
    """F-025: the hunter writes one spec per call. Promoting one draft while a
    sibling is still hypothesised is legal at the store; the finalize command
    is the one whole-set gate."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="registration"),
        _spec(fault_keyword="reset"),
    ])
    written = store.write_specs(
        PROJECT, HUNT_KEY, [_spec(status="ratified", fault_keyword="registration")],
        enforce_complete=False)
    assert [spec_id for spec_id, _ in written] == ["spec__registration__probe"]
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__registration__probe")["status"] == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__reset__probe")["status"] == "hypothesised"


def test_finalize_requires_every_draft_to_be_decided(tmp_path):
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="registration"),
        _spec(fault_keyword="reset"),
    ])
    store.write_specs(
        PROJECT, HUNT_KEY, [_spec(status="ratified", fault_keyword="registration")],
        enforce_complete=False)
    with pytest.raises(IncompleteSpecSetError) as raised:
        store.finalize_specs(PROJECT, HUNT_KEY, run_id="run-1")
    assert raised.value.missing == ["spec__reset__probe"]
    assert store.read_terminal_set(PROJECT, HUNT_KEY) is None


def test_finalize_records_the_terminal_set_and_is_idempotent(tmp_path):
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="registration"),
        _spec(fault_keyword="reset"),
    ])
    store.write_specs(
        PROJECT, HUNT_KEY, [_spec(status="ratified", fault_keyword="registration")],
        enforce_complete=False)
    store.write_specs(
        PROJECT, HUNT_KEY, [_spec(status="dropped", fault_keyword="reset")],
        enforce_complete=False)
    marker = store.finalize_specs(PROJECT, HUNT_KEY, run_id="run-1")
    assert marker["run_id"] == "run-1"
    assert marker["spec_ids"] == ["spec__registration__probe", "spec__reset__probe"]
    assert marker["spec_statuses"] == {
        "spec__registration__probe": "ratified", "spec__reset__probe": "dropped"}
    again = store.finalize_specs(PROJECT, HUNT_KEY, run_id="run-1")
    assert again["finalized_at"] == marker["finalized_at"]
    assert store.read_terminal_set(PROJECT, HUNT_KEY)["run_id"] == "run-1"


def test_finalize_accepts_a_zero_spec_hunt(tmp_path):
    """A hunter that authors no spec still needs a durable completion marker,
    or its consumed threat would be recovered forever."""
    store = HunterMemoryStore(root_dir=tmp_path)
    marker = store.finalize_specs(PROJECT, HUNT_KEY, run_id="run-empty")
    assert marker["spec_ids"] == []
    assert marker["spec_statuses"] == {}
    assert store.read_terminal_set(PROJECT, HUNT_KEY)["run_id"] == "run-empty"


# --- the set write and the status lifecycle (S3 8.6-8.7) ----------------------

def test_a_batched_specs_write_creates_the_whole_set(tmp_path):
    """S3 8.7: one write carries the WHOLE set, all `hypothesised`, and the
    store creates one file per derived identity in the threat's folder."""
    store = HunterMemoryStore(root_dir=tmp_path)
    written = store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="registration", strategy_keyword="probe"),
        _spec(fault_keyword="reset", strategy_keyword="replay"),
    ])
    assert [spec_id for spec_id, _ in written] == ["spec__registration__probe", "spec__reset__replay"]
    assert _spec_file(tmp_path, "produced", "spec__registration__probe").is_file()
    assert _spec_file(tmp_path, "produced", "spec__reset__replay").is_file()
    assert store.read_specs(PROJECT, HUNT_KEY, sides=("produced",)) == [
        _spec(fault_keyword="registration", strategy_keyword="probe"),
        _spec(fault_keyword="reset", strategy_keyword="replay"),
    ]


def test_the_terminal_write_promotes_and_declasses_in_place(tmp_path):
    """S3 8.7: the terminal write carries the whole set - survivors `ratified`,
    unfeasible `dropped` - and upserts each identity in place (one file per
    identity, never a second one)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="registration", strategy_keyword="probe"),
        _spec(fault_keyword="reset", strategy_keyword="replay"),
    ])
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(status="ratified", fault_keyword="registration", strategy_keyword="probe"),
        _spec(status="dropped", fault_keyword="reset", strategy_keyword="replay",
              verification_symptoms=[]),
    ])
    produced = _spec_file(tmp_path, "produced").parent
    assert sorted(path.name for path in produced.glob("*.yaml")) == [
        "spec__registration__probe.yaml", "spec__reset__replay.yaml"]
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__registration__probe")["status"] == "ratified"
    dropped = store.read_spec(PROJECT, HUNT_KEY, "spec__reset__replay")
    assert dropped["status"] == "dropped"
    # the body is the reduced D4 at every status: no FaultItem/spec_id residue
    assert dropped["verification_symptoms"] == []
    assert "spec_id" not in dropped and "experiment_ref" not in dropped


def test_a_terminal_write_that_omits_a_hypothesised_spec_is_refused(tmp_path):
    """F-017 quality repair: the terminal VERIFY-CLAIMS write carries the
    WHOLE set. A terminal write that silently omits a previously authored
    hypothesised spec is an incomplete set, not a promotion - the store
    refuses it and names the missing identities so the hunter can ratify or
    explicitly drop them (comfyui-003's `/view` SVG draft was lost this way)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="registration", strategy_keyword="probe"),
        _spec(fault_keyword="reset", strategy_keyword="replay"),
    ])
    with pytest.raises(IncompleteSpecSetError) as caught:
        store.write_specs(PROJECT, HUNT_KEY, [
            _spec(status="ratified", fault_keyword="registration",
                  strategy_keyword="probe"),
        ])
    assert "spec__reset__replay" in str(caught.value)
    # the refused write is atomic: the old produced set is untouched
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__registration__probe")["status"] \
        == "hypothesised"
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__reset__replay")["status"] \
        == "hypothesised"


def test_a_terminal_write_that_explicitly_drops_a_draft_is_allowed(tmp_path):
    """The completeness gate is satisfied by an explicit `dropped` entry: the
    hunter must decide every draft, not silently forget it."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="registration", strategy_keyword="probe"),
        _spec(fault_keyword="reset", strategy_keyword="replay"),
    ])
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(status="ratified", fault_keyword="registration",
              strategy_keyword="probe"),
        _spec(status="dropped", fault_keyword="reset",
              strategy_keyword="replay"),
    ])
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__registration__probe")["status"] \
        == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY, "spec__reset__replay")["status"] \
        == "dropped"


def test_a_duplicate_identity_in_one_set_is_the_dedup_signal(tmp_path):
    """S3 8.7: a duplicate derived identity INSIDE one set is the dedup signal;
    a rejected batch never leaves a partial set on disk."""
    store = HunterMemoryStore(root_dir=tmp_path)
    with pytest.raises(DuplicateSpecError):
        store.write_specs(PROJECT, HUNT_KEY, [
            _spec(fault_keyword="registration", strategy_keyword="probe"),
            _spec(fault_keyword="registration", strategy_keyword="probe"),
        ])
    assert store.read_specs(PROJECT, HUNT_KEY) == []


def test_the_payload_must_not_author_the_derived_spec_id(tmp_path):
    """S3 8.6: the spec identity is the DERIVED file-name stem; a payload that
    authors `spec_id` is rejected rather than persisted."""
    store = HunterMemoryStore(root_dir=tmp_path)
    with pytest.raises(ValueError, match="spec_id"):
        store.write_specs(PROJECT, HUNT_KEY, [_spec(spec_id="S1")])


def test_the_status_vocabulary_is_the_three_live_values(tmp_path):
    """S3 8.6/S4 14.6: `{hypothesised, ratified, dropped}` everywhere; the
    retired `verified`/`specified` values are refused by the store."""
    store = HunterMemoryStore(root_dir=tmp_path)
    for retired in ("verified", "specified"):
        with pytest.raises(ValueError, match="status"):
            store.write_specs(PROJECT, HUNT_KEY, [_spec(status=retired)])


def test_a_mixed_hypothesised_and_terminal_set_is_refused(tmp_path):
    """S3 8.7 defines exactly two set shapes: the GENERATE write (all
    `hypothesised`) and the terminal write (`ratified`/`dropped`). A mixed set
    would persist while the tracker sees no exit, so the store refuses it and
    leaves no partial file behind."""
    store = HunterMemoryStore(root_dir=tmp_path)
    with pytest.raises(ValueError, match="GENERATE write"):
        store.write_specs(PROJECT, HUNT_KEY, [
            _spec(fault_keyword="f1", status="hypothesised"),
            _spec(fault_keyword="f2", status="ratified"),
        ])
    assert store.read_specs(PROJECT, HUNT_KEY) == []
    # the two legal shapes still land
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="f1", status="hypothesised")])
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="f1", status="ratified"),
        _spec(fault_keyword="f2", status="dropped"),
    ])
    assert [s["status"] for s in store.read_specs(PROJECT, HUNT_KEY)] == [
        "ratified", "dropped"]


def test_the_file_name_is_derived_from_the_class_and_values(tmp_path):
    """S3 8.6/G3: `<class>__<value>__<value>.yaml`; the class is sanitised and
    the values are already safe tokens. An unsafe value is a coded rejection."""
    store = HunterMemoryStore(root_dir=tmp_path)
    written = store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="csrf", strategy_keyword="probe"),
    ])
    assert written[0][0] == "spec__csrf__probe"
    assert _spec_file(tmp_path, "produced", "spec__csrf__probe").is_file()
    assert spec_identifier("spec", [
        {"axis": "fault", "value": "csrf"},
        {"axis": "technique", "value": "probe"},
    ]) == "spec__csrf__probe"
    with pytest.raises(ValueError):
        store.write_specs(PROJECT, HUNT_KEY, [
            _spec(fault_keyword="..", strategy_keyword="probe")])


def test_the_store_key_is_the_hunt_key_folder(tmp_path):
    """S3 8.9: the folder is `test-specs/<hunt_key>/`, where the hunt key is
    the threat dispatch id `<unit_name>__<threat_id>`."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    expected = (
        tmp_path / PROJECT / "hunting" / "hunter" / "test-specs" / HUNT_KEY
        / "produced" / "spec__registration__probe.yaml"
    )
    assert expected.is_file()
    assert store.list_hunt_keys(PROJECT) == [HUNT_KEY]


# --- the move-aware write (the #205 rule) -------------------------------------

def test_produced_write_after_move_is_a_no_op_and_never_recreates(tmp_path, caplog):
    """#205: after the mover consumed an identity, the hunter's late terminal
    write must be a no-op success returning the durable consumed Path -
    produced/ stays absent, so the inbox drains and the run does not hang."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    assert store.consume_spec(PROJECT, HUNT_KEY, SPEC_ID) is True
    assert not _spec_file(tmp_path, "produced").exists()
    with caplog.at_level(logging.WARNING):
        written = store.write_specs(PROJECT, HUNT_KEY, [_spec(status="ratified")])
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    assert store.produced_spec_files(PROJECT, HUNT_KEY) == []
    assert written == [(SPEC_ID, _spec_file(tmp_path, "consumed"))]
    assert any("post-move write, #205" in r.message for r in caplog.records)


def test_move_aware_no_op_keeps_consume_a_noop_success(tmp_path, caplog):
    """#205 quiesce proof: after the move-aware no-op the next mover tick has an
    empty produced inbox - `consume_spec` is a no-op success, never the
    dual-sided clobber refusal."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    assert store.consume_spec(PROJECT, HUNT_KEY, SPEC_ID) is True
    store.write_specs(PROJECT, HUNT_KEY, [_spec(status="ratified")])
    with caplog.at_level(logging.WARNING):
        assert store.consume_spec(PROJECT, HUNT_KEY, SPEC_ID) is True
    assert store.produced_spec_files(PROJECT, HUNT_KEY) == []
    assert not any("both produced/ and consumed/" in r.message for r in caplog.records)


def test_produced_write_still_creates_when_consumed_absent(tmp_path):
    """A normal produced-target write with no consumed twin creates the set and
    upserts it in place - the move-aware guard only fires post-move."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(status="ratified", rationale="amended")])
    assert store.read_spec(PROJECT, HUNT_KEY, SPEC_ID)["rationale"] == "amended"
    assert store.produced_spec_files(PROJECT, HUNT_KEY) == [SPEC_ID]


def test_consumed_side_write_is_unaffected(tmp_path):
    """A `side="consumed"` write is untouched by the guard: replay still
    overwrites the consumed record in place."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()], side="consumed")
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    store.write_specs(PROJECT, HUNT_KEY,
                      [_spec(status="ratified", rationale="replay")], side="consumed")
    assert store.read_spec(PROJECT, HUNT_KEY, SPEC_ID, side="consumed")["rationale"] \
        == "replay"
    assert not _spec_file(tmp_path, "produced").exists()


# --- the read surface ---------------------------------------------------------

def test_read_specs_sides_and_status_filters(tmp_path):
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="f1", strategy_keyword="probe"),
        _spec(fault_keyword="f2", strategy_keyword="probe"),
    ])
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(fault_keyword="f1", strategy_keyword="probe", status="ratified"),
        _spec(fault_keyword="f2", strategy_keyword="probe", status="dropped")])
    assert len(store.read_specs(PROJECT, HUNT_KEY)) == 2
    ratified = store.read_specs(PROJECT, HUNT_KEY, statuses=["ratified"],
                                attributes=["status"])
    assert ratified == [{"status": "ratified"}]
    dropped = store.read_specs(PROJECT, HUNT_KEY, statuses=["dropped"],
                              attributes=["status"])
    assert dropped == [{"status": "dropped"}]
    assert store.read_spec(PROJECT, HUNT_KEY, "missing") is None


def test_consumed_spec_files_lists_only_the_consumed_side(tmp_path):
    """F-017: the mover needs the consumed-side inventory to reconcile a spec
    admitted before a pause against its terminal PodExport."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    assert store.consumed_spec_files(PROJECT, HUNT_KEY) == []
    store.consume_spec(PROJECT, HUNT_KEY, SPEC_ID)
    assert store.consumed_spec_files(PROJECT, HUNT_KEY) == [SPEC_ID]


def test_a_corrupt_spec_file_raises(tmp_path):
    """O4: a corrupt file raises rather than silently returning an empty set
    (the write paths rewrite whole files)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    _spec_file(tmp_path, "produced").write_text(": : not yaml [", encoding="utf-8")
    with pytest.raises(OSError):
        store.read_specs(PROJECT, HUNT_KEY)


# --- the typed skill-concretised procedure (S3 8.6, S5 8.6) -------------------

def test_the_skill_concretised_procedure_round_trips(tmp_path):
    from polymerhus.attack.hunting.spec_contract import (
        SkillConcretisedProcedure,
    )

    procedure = SkillConcretisedProcedure(
        recon_action="mine the item id",
        bypass_technique="swap the id",
        payload_vector="the item id in the path, no encoding",
        technology_misconfiguration="the store trusts the signed scope",
    )
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [
        _spec(skill_concretised_procedure=procedure.model_dump())])
    body = store.read_spec(PROJECT, HUNT_KEY, SPEC_ID)
    assert body["skill_concretised_procedure"]["recon_action"] == \
        "mine the item id"
    assert body["skill_concretised_procedure"]["payload_vector"] == \
        "the item id in the path, no encoding"


def test_an_over_long_skill_concretised_procedure_is_a_coded_rejection(tmp_path):
    from polymerhus.attack.hunting.spec_contract import (
        SKILL_CONCRETISED_PROCEDURE_MAX_CHARS,
    )

    store = HunterMemoryStore(root_dir=tmp_path)
    procedure = {"recon_action": "z" * (SKILL_CONCRETISED_PROCEDURE_MAX_CHARS + 1)}
    with pytest.raises(ValueError, match="exceeds"):
        store.write_specs(PROJECT, HUNT_KEY, [
            _spec(skill_concretised_procedure=procedure)])


def test_a_terminal_write_for_an_unknown_identity_is_refused(tmp_path):
    """Identity stability: a changed discriminator value is a new sub-slice,
    not a silent rename of an existing slot."""
    store = HunterMemoryStore(root_dir=tmp_path)
    store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    with pytest.raises(ValueError, match="no hypothesised spec"):
        store.write_specs(PROJECT, HUNT_KEY, [
            _spec(status="ratified", strategy_keyword="different")],
            enforce_complete=False)


# --- #340: notes.yaml is written atomically ----------------------------------

def _notes_file(tmp_path: Path) -> Path:
    return tmp_path / PROJECT / "hunting" / "hunter" / "notes.yaml"


def _tmp_leftovers(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [p for p in directory.iterdir() if p.name.endswith(".tmp")]


def _append(store: HunterMemoryStore, body: str) -> None:
    store.write_note(
        PROJECT, action="append", hunt_key=HUNT_KEY, note_name="n1",
        kind="freeform", body=body,
    )


def test_failed_notes_dump_leaves_prior_content_intact(tmp_path, monkeypatch, caplog):
    """#340: a raising dump must never truncate notes.yaml."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _append(store, "first")
    notes = _notes_file(tmp_path)
    before = notes.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("dump crashed (fixture)")

    monkeypatch.setattr(
        "polymerhus.attack.hunting.hunter_memory.yaml.safe_dump", boom)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError):
            _append(store, "second")
    monkeypatch.undo()

    assert notes.read_text(encoding="utf-8") == before
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["first"]
    assert _tmp_leftovers(notes.parent) == []


def test_aborted_replace_leaves_prior_notes_intact(tmp_path, monkeypatch):
    """#340: an abort before the atomic rename leaves the previous file."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _append(store, "first")
    notes = _notes_file(tmp_path)
    before = notes.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated kill before the atomic rename")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        _append(store, "second")
    monkeypatch.undo()

    assert notes.read_text(encoding="utf-8") == before
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["first"]
    assert _tmp_leftovers(notes.parent) == []


def test_reader_never_sees_a_partial_notes_file(tmp_path, monkeypatch):
    """#340: a concurrent reader observes the OLD complete file until the
    atomic rename lands."""
    store = HunterMemoryStore(root_dir=tmp_path)
    _append(store, "first")
    notes = _notes_file(tmp_path)
    before = notes.read_text(encoding="utf-8")
    observed: list[str] = []
    real_replace = os.replace

    def observe(src, dst):
        observed.append(notes.read_text(encoding="utf-8"))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", observe)
    _append(store, "second")
    monkeypatch.undo()

    assert observed == [before]
    assert [n["body"] for n in store.read_notes(PROJECT)] == ["second", "first"]
    assert _tmp_leftovers(notes.parent) == []


def test_failed_spec_dump_leaves_no_partial_file(tmp_path, monkeypatch):
    """#340: the batched spec write is atomic per file; a raising dump leaves
    no partial spec file on disk."""
    store = HunterMemoryStore(root_dir=tmp_path)
    spec_file = _spec_file(tmp_path, "produced")

    def boom(*args, **kwargs):
        raise RuntimeError("dump crashed (fixture)")

    monkeypatch.setattr(
        "polymerhus.attack.hunting.hunter_memory.yaml.safe_dump", boom)
    with pytest.raises(RuntimeError):
        store.write_specs(PROJECT, HUNT_KEY, [_spec()])
    monkeypatch.undo()

    assert not spec_file.exists()
    assert _tmp_leftovers(spec_file.parent) == []


# --- #341: notes.yaml growth is bounded (count + size, value-aware eviction) --
def _append_named(store: HunterMemoryStore, name: str, body: str = "x",
                  provenance: dict | None = None) -> None:
    store.write_note(
        PROJECT, action="append", hunt_key=HUNT_KEY, note_name=name,
        kind="freeform", body=body, provenance=provenance,
    )


def _unbounded_size(monkeypatch) -> None:
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_BYTES", 10**9)


def test_notes_file_is_bounded_by_record_count(tmp_path, monkeypatch):
    """#341: the store keeps only the newest HUNTER_NOTES_MAX_RECORDS."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 3)
    _unbounded_size(monkeypatch)
    store = HunterMemoryStore(root_dir=tmp_path)
    for i in range(6):
        _append_named(store, f"n{i}")
    notes = store.read_notes(PROJECT)
    assert [n["note_name"] for n in notes] == ["n5", "n4", "n3"]
    raw = yaml.safe_load(_notes_file(tmp_path).read_text(encoding="utf-8"))
    assert len(raw) == 3


def test_notes_eviction_preserves_durable_pod_export_records(tmp_path, monkeypatch):
    """#341: the Q16 pod-export stub (`provenance.verdict_stub`) survives
    ordinary eviction; the oldest reasoning notes are dropped first."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 3)
    _unbounded_size(monkeypatch)
    store = HunterMemoryStore(root_dir=tmp_path)
    _append_named(store, "pod-export:s1", body="stub",
                  provenance={"verdict_stub": True, "run_id": "r", "source": "s"})
    for i in range(5):
        _append_named(store, f"n{i}")
    names = {n["note_name"] for n in store.read_notes(PROJECT)}
    assert names == {"pod-export:s1", "n3", "n4"}


def test_notes_bound_is_absolute_when_durable_records_alone_exceed_it(tmp_path, monkeypatch):
    """#341: the bound is absolute even when protected records alone exceed it."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 2)
    _unbounded_size(monkeypatch)
    store = HunterMemoryStore(root_dir=tmp_path)
    for i in range(3):
        _append_named(store, f"pod-export:s{i}",
                      provenance={"verdict_stub": True})
    names = {n["note_name"] for n in store.read_notes(PROJECT)}
    assert names == {"pod-export:s1", "pod-export:s2"}


def test_notes_file_is_bounded_by_serialized_size(tmp_path, monkeypatch):
    """#341: a serialized-size ceiling evicts oldest-first until the file fits."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 10**6)
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_BYTES", 4000)
    store = HunterMemoryStore(root_dir=tmp_path)
    for i in range(20):
        _append_named(store, f"n{i}", body="z" * 500)
    raw = _notes_file(tmp_path).read_text(encoding="utf-8")
    assert len(raw.encode("utf-8")) <= 4000
    kept = yaml.safe_load(raw)
    assert 1 <= len(kept) < 20
    assert kept[-1]["note_name"] == "n19"


def test_a_single_oversized_record_is_kept_whole(tmp_path, monkeypatch):
    """#341: a record larger than the ceiling is never truncated."""
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_RECORDS", 10**6)
    monkeypatch.setattr(hunter_memory, "HUNTER_NOTES_MAX_BYTES", 100)
    store = HunterMemoryStore(root_dir=tmp_path)
    _append_named(store, "oversized", body="z" * 5000)
    notes = store.read_notes(PROJECT)
    assert len(notes) == 1
    assert notes[0]["note_name"] == "oversized"


# --- S4 14.8: the hunter-only phase-summary note kind -------------------------

def test_phase_summary_is_a_hunter_note_kind_and_an_update_rewrites_it(tmp_path):
    """S4 14.8/Q51a: the phase note is written and updated on a re-iteration;
    the name is `phase:<state>` under the bound hunt key."""
    store = HunterMemoryStore(root_dir=tmp_path)
    key = store.write_note(
        PROJECT, action="append", hunt_key=HUNT_KEY,
        note_name="phase:slice", kind="phase_summary", body="first slice")
    assert key == f"{HUNT_KEY}:phase:slice"
    store.write_note(
        PROJECT, action="update", hunt_key=HUNT_KEY,
        note_name="phase:slice", kind="phase_summary", body="re-iterated slice")
    notes = store.read_notes(PROJECT, parent_key=HUNT_KEY)
    assert [n["body"] for n in notes] == ["re-iterated slice"]
    assert notes[0]["kind"] == "phase_summary"


def test_the_phase_kind_is_hunter_only():
    """S4 14.8: the hunt-store and pod note enums do NOT gain `phase_summary`."""
    from polymerhus.attack.hunting.hunt_store import ProjectMemoryStore
    from polymerhus.attack.hunting.pod.pod_memory import POD_NOTE_KINDS

    assert "phase_summary" in hunter_memory.NOTE_KINDS
    assert "phase_summary" not in ProjectMemoryStore.NOTE_KINDS
    assert "phase_summary" not in POD_NOTE_KINDS
