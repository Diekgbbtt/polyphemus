"""Unit tier: the residual hunt-store key helpers and notes surface (#166, T6).

Pure filesystem mechanics - no Neo4j, no LLM. The config I/O surface retired in
T6 (#379) with no live consumer; this file pins what remains: the config-key
helpers (still used by the legacy identity tests / the eval translation) and
the orchestrator `memory.yaml` notes surface (append order, update/delete, the
atomic write, the per-project write serialisation, and the #341 bounds).
"""
import threading

import pytest
import yaml

from polymerhus.attack.hunting.hunt_store import (
    HuntStore,
    config_file_name,
    parse_config_file_name,
    semantic_key,
    split_semantic_key,
)

PROJECT = "proj-1"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"


# --- the key-helper contract (the residual identity vocabulary) ---------------

def test_config_file_name_uses_underscore_separators():
    # unit ids contain `:` and `-` (poisoned as separators); `_` is the one
    # safe character; the CWE id sits between unit and vulnerability class.
    assert config_file_name(UNIT, CWE, CLASS) == \
        "Service:catalogue-and-discovery_CWE-639_IDOR.yaml"


def test_parse_config_file_name_round_trips_last_two_underscores():
    # A unit_id (and a class) containing `_` round-trips: the parse splits on
    # the LAST two underscores, with CWE-\d+ disambiguating the middle segment.
    name = config_file_name("Service:edge_router", CWE, "IDOR_xml")
    assert name == "Service:edge_router_CWE-639_IDOR_xml.yaml"
    assert parse_config_file_name(name) == \
        ("Service:edge_router", CWE, "IDOR_xml")


def test_parse_config_file_name_tolerates_the_carried_bare_class():
    # the carried-bare degrade (a class-less config) keeps the trailing
    # underscore; the parse tolerates the empty class.
    assert parse_config_file_name(f"{UNIT}_{CWE}_.yaml") == (UNIT, CWE, "")


def test_parse_config_file_name_rejects_non_convention_names():
    assert parse_config_file_name("not-a-config.md") is None
    assert parse_config_file_name(f"{UNIT}_fault-x_IDOR.yaml") is None


def test_parse_config_file_name_preserves_a_unit_ending_in_underscore():
    # G4 regression (live e2e eval): a unit identity ending in `_` - the
    # `__singleton__` marker - must round-trip its FULL identity.
    name = "AuthenticationMechanism:__singleton___CWE-266_Broken Authentication.yaml"
    parsed = parse_config_file_name(name)
    assert parsed is not None
    unit, cwe, cls = parsed
    assert (unit, cwe, cls) == \
        ("AuthenticationMechanism:__singleton__", "CWE-266", "Broken Authentication")
    assert semantic_key(unit, cwe, cls) == \
        "AuthenticationMechanism:__singleton__::CWE-266::Broken Authentication"
    # a WebPresentation discriminator containing `::` and `-` also round-trips
    name2 = "WebPresentation:moodique-storefront::homepage_CWE-639_CSRF.yaml"
    assert parse_config_file_name(name2) == \
        ("WebPresentation:moodique-storefront::homepage", "CWE-639", "CSRF")


def test_semantic_key_is_the_canonical_internal_identity():
    assert semantic_key(UNIT, CWE, CLASS) == "Service:catalogue-and-discovery::CWE-639::IDOR"


def test_split_semantic_key_round_trips_a_system_unit_with_double_colon():
    # G4 regression (live e2e eval): a System unit id is a kind-qualified
    # identity containing `::` (`System:AuthorizationSystem::__singleton__`),
    # so its semantic key has MORE than three `::` segments. The split anchors
    # on the CWE token, or the move refuses the key and the run hangs.
    unit = "System:AuthorizationSystem::__singleton__"
    key = semantic_key(unit, CWE, CLASS)
    assert key == f"{unit}::CWE-639::IDOR"
    assert split_semantic_key(key) == (unit, CWE, CLASS)
    # the 2-part revival key is NOT a semantic key
    assert split_semantic_key(f"{unit}::{CWE}") is None


def test_singleton_unit_id_has_no_sentinel_and_a_clean_three_part_key():
    # #279 follow-up: a singleton System's orchestrator-facing unit id is the
    # BARE kind and its semantic key is a clean 3-part key - the ambiguous
    # literal never reaches the mover / orchestrator.
    unit = "AuthorizationSystem"
    key = semantic_key(unit, CWE, CLASS)
    assert key == f"AuthorizationSystem::{CWE}::{CLASS}"
    assert key.count("::") == 2


def test_ambiguous_cwe_like_segments_parse_greedily():
    """M3 (documented corner, not solved - the memory spec fixed the last-two-
    underscores convention): a unit_id ending in a CWE-like segment and a class
    beginning with a CWE-like segment are indistinguishable from extra CWE
    segments. The greedy regex wins (the unit swallows the earlier CWE-like
    segments); the file name IS the identity."""
    unit = "Service:router_CWE-9"
    cwe = "CWE-9"
    cls = "CWE-9_xml"
    name = config_file_name(unit, cwe, cls)
    assert name == "Service:router_CWE-9_CWE-9_CWE-9_xml.yaml"
    assert parse_config_file_name(name) == \
        ("Service:router_CWE-9_CWE-9", "CWE-9", "xml")


# --- the notes surface --------------------------------------------------------

def _memory_file(tmp_path):
    return tmp_path / PROJECT / "hunting" / "orchestration" / "memory.yaml"


def test_notes_append_in_natural_order(tmp_path):
    store = HuntStore(tmp_path)
    key = f"{UNIT}::{CWE}"
    store.append_note(PROJECT, key, "first")
    store.append_note(PROJECT, key, "second")
    store.append_note(PROJECT, f"{UNIT}::CWE-9", "other")
    notes = store.read_notes(PROJECT, key)
    assert [n["note"] for n in notes] == ["first", "second"]
    # natural append order, no _seq anywhere
    body = _memory_file(tmp_path).read_text(encoding="utf-8")
    assert "_seq" not in body
    assert body.index("first") < body.index("second")
    # the key match rule: a 3-part query also finds the 2-part-keyed note
    three_part = store.read_notes(PROJECT, semantic_key(UNIT, CWE, CLASS))
    assert [n["note"] for n in three_part] == ["first", "second"]


def test_notes_update_and_delete_by_note_id(tmp_path):
    store = HuntStore(tmp_path)
    key = f"{UNIT}::{CWE}"
    first = store.append_note(PROJECT, key, "first")
    second = store.append_note(PROJECT, key, "second")
    assert store.update_note(PROJECT, first["note_id"], "first amended") is True
    assert store.delete_note(PROJECT, second["note_id"]) is True
    notes = store.read_notes(PROJECT, key)
    assert [n["note"] for n in notes] == ["first amended"]
    # an unknown id is a no-op False, never a raise
    assert store.update_note(PROJECT, "missing", "x") is False
    assert store.delete_note(PROJECT, "missing") is False


def test_a_later_store_reads_the_prior_pass_notes(tmp_path):
    """A later pass on the same project reads the prior pass's notes through a
    FRESH store at the same root - the notes file is per-project durable."""
    store_a = HuntStore(tmp_path)
    store_a.append_note(PROJECT, f"{UNIT}::{CWE}", "track the IDOR surface")

    store_b = HuntStore(tmp_path)  # a new store, same root
    notes = store_b.read_notes(PROJECT, f"{UNIT}::{CWE}")
    assert [n["note"] for n in notes] == ["track the IDOR surface"]


# --- I1: atomic writes - a crash mid-dump leaves prior content intact --------

def test_failed_note_dump_leaves_prior_content_intact(tmp_path, monkeypatch):
    """I1 - a raising dump leaves the previous memory.yaml content intact (the
    temp-file + os.replace write), so the whole notes history is never lost."""
    store = HuntStore(tmp_path)
    store.append_note(PROJECT, f"{UNIT}::{CWE}", "first")
    memory = _memory_file(tmp_path)
    before = memory.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("dump crashed (fixture)")

    monkeypatch.setattr("polymerhus.attack.hunting.hunt_store.yaml.safe_dump", boom)
    with pytest.raises(RuntimeError):
        store.append_note(PROJECT, f"{UNIT}::{CWE}", "second")
    monkeypatch.undo()  # restore safe_dump before reading back

    assert memory.read_text(encoding="utf-8") == before
    assert [n["note"] for n in store.read_notes(PROJECT)] == ["first"]
    # no leftover temp file in the directory
    assert [p for p in memory.parent.iterdir() if p.name.endswith(".tmp")] == []


# --- I2: per-project write serialisation ---------------------------------------

def test_concurrent_note_appends_lose_none(tmp_path):
    """I2 - two (here: eight) threads appending notes concurrently to the same
    project lose none: the load-append-rewrite runs under the project's lock."""
    store = HuntStore(tmp_path)
    workers = 8
    barrier = threading.Barrier(workers)
    errors: list = []

    def worker(i):
        barrier.wait()
        try:
            store.append_note(PROJECT, f"{UNIT}::{CWE}", f"note-{i}")
        except Exception as exc:  # noqa: BLE001 - record, then assert none
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    notes = store.read_notes(PROJECT)
    assert len(notes) == workers
    assert {n["note"] for n in notes} == {f"note-{i}" for i in range(workers)}


# --- #341: memory.yaml growth is bounded (count + size, oldest-first) --------

def test_memory_yaml_is_bounded_by_record_count(tmp_path, monkeypatch):
    """#341: the orchestrator's `memory.yaml` is a whole-file rewrite; a long
    run keeps only the newest records so the rewrite cost cannot grow without
    bound, and the reader still sees a complete parseable file."""
    from polymerhus.attack.hunting import hunt_store as hs

    monkeypatch.setattr(hs, "MEMORY_NOTES_MAX_RECORDS", 3)
    monkeypatch.setattr(hs, "MEMORY_NOTES_MAX_BYTES", 10**9)
    store = HuntStore(tmp_path)
    key = f"{UNIT}::{CWE}"
    for i in range(6):
        store.append_note(PROJECT, key, f"note-{i}")
    notes = store.read_notes(PROJECT)
    assert [n["note"] for n in notes] == ["note-3", "note-4", "note-5"]
    assert len(yaml.safe_load(_memory_file(tmp_path).read_text(encoding="utf-8"))["notes"]) == 3


def test_memory_yaml_is_bounded_by_serialized_size(tmp_path, monkeypatch):
    """#341: the size ceiling evicts oldest-first until the file fits, so one
    huge note body cannot grow the file without bound."""
    from polymerhus.attack.hunting import hunt_store as hs

    monkeypatch.setattr(hs, "MEMORY_NOTES_MAX_RECORDS", 10**6)
    monkeypatch.setattr(hs, "MEMORY_NOTES_MAX_BYTES", 4000)
    store = HuntStore(tmp_path)
    key = f"{UNIT}::{CWE}"
    for i in range(20):
        store.append_note(PROJECT, key, "z" * 500)
    raw = _memory_file(tmp_path).read_text(encoding="utf-8")
    assert len(raw.encode("utf-8")) <= 4000
    notes = store.read_notes(PROJECT)
    assert 1 <= len(notes) < 20
    assert notes[-1]["note"] == "z" * 500
