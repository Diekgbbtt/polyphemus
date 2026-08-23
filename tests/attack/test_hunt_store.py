"""Unit tier: the per-project hunt-config + notes memory store (memory-system
spec, #166).

Pure filesystem mechanics - no Neo4j, no LLM. Pins the topology, the
file-naming round-trip, the duplicate-write novelty gate, the dropped-on-disk
rule, the notes append/update/delete order, the fail-open reads, the
cross-pass visibility on the same project, the atomic-write guarantee (I1),
the per-project write serialisation (I2), the directory validation (M2), and
the ambiguous-parse corner (M3) - the storage-layer assertions the
orchestrator and the e2e tiers build on.
"""
import threading

import pytest

from polymerhus.attack.hunting.hunt_store import (
    DuplicateConfigError,
    HUNT_STORE_ROOT,
    HuntStore,
    config_file_name,
    parse_config_file_name,
    semantic_key,
)

PROJECT = "proj-1"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"

# A config with the full HuntConfig-shape fields (the identity slots plus a
# couple of carried slots) as the store writes them.
def _config(**overrides) -> dict:
    data = {
        "hunt_id": "hunt-1",
        "unit_id": UNIT,
        "fault_class": CWE,
        "status": "hypothesised",
        "vulnerability_class": CLASS,
        "prompt_template": {"rationale": "r", "l0_evidence": [], "research_direction": "rd"},
        "surface_context": {},
        "target_caveats": [],
        "prior_hunt_insights": [],
        "tool_registry": [],
    }
    data.update(overrides)
    return data


# --- naming + the semantic key round-trip (G4) ------------------------------

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


def test_semantic_key_is_the_canonical_internal_identity():
    assert semantic_key(UNIT, CWE, CLASS) == "Service:catalogue-and-discovery::CWE-639::IDOR"


# --- topology: lazily created per project at the first write -----------------

def test_write_creates_the_project_topology(tmp_path):
    store = HuntStore(tmp_path)
    key = store.write_config(PROJECT, _config())
    assert key == semantic_key(UNIT, CWE, CLASS)
    produced = tmp_path / PROJECT / "orchestration" / "hunt_configs" / "produced"
    consumed = tmp_path / PROJECT / "orchestration" / "hunt_configs" / "consumed"
    memory = tmp_path / PROJECT / "orchestration" / "memory.yaml"
    assert produced.exists()
    assert consumed.exists()          # both directories are part of the topology
    assert not memory.exists()        # memory.yaml is created only by a note write
    assert (produced / f"{UNIT}_{CWE}_{CLASS}.yaml").exists()


def test_default_root_is_the_fixed_seam_root():
    assert HUNT_STORE_ROOT.name == "data"
    assert str(HUNT_STORE_ROOT).endswith("src/polymerhus/attack/hunting/data")
    assert HuntStore()._root == HUNT_STORE_ROOT


# --- duplicate-write novelty gate (G4) --------------------------------------

def test_duplicate_config_write_fails(tmp_path):
    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config())
    with pytest.raises(DuplicateConfigError):
        store.write_config(PROJECT, _config())
    # the novelty gate is cross-directory: a config in consumed/ also blocks
    store.write_config(PROJECT, _config(unit_id="Service:b", fault_class=CWE,
                                        vulnerability_class="IDOR"),
                       directory="consumed")
    with pytest.raises(DuplicateConfigError):
        store.write_config(PROJECT, _config(unit_id="Service:b", fault_class=CWE,
                                            vulnerability_class="IDOR"),
                           directory="produced")


# --- ratify-phase upsert (update_config) --------------------------------------

def test_update_config_overwrites_the_existing_identity_in_place(tmp_path):
    """The ratify write amends the hypothesised draft at its identity: the
    file is overwritten in place (no second file, no novelty-gate failure) and
    reads back with the ratified status + the filled ratification fields."""
    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config())
    store.update_config(PROJECT, _config(
        status="ratified",
        adversarial_capabilities=["forge a cross-origin request"],
        assumptions=["the session is cookie-bound"],
        technique_primitives=["token-missing probe"],
    ))
    configs = store.read_configs(PROJECT)
    assert len(configs) == 1                       # still ONE file at the identity
    assert configs[0]["status"] == "ratified"
    assert configs[0]["adversarial_capabilities"] == ["forge a cross-origin request"]
    assert configs[0]["assumptions"] == ["the session is cookie-bound"]
    assert configs[0]["technique_primitives"] == ["token-missing probe"]


def test_update_config_marks_dropped_and_stays_on_disk(tmp_path):
    """A config deleted during ratification is marked status='dropped' and
    stays on disk (G6) - never deleted, never a second file."""
    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config())
    store.update_config(PROJECT, _config(status="dropped"))
    configs = store.read_configs(PROJECT)
    assert len(configs) == 1
    assert configs[0]["status"] == "dropped"
    assert (tmp_path / PROJECT / "orchestration" / "hunt_configs" / "produced"
            / f"{UNIT}_{CWE}_{CLASS}.yaml").exists()


def test_update_config_creates_when_the_identity_is_absent(tmp_path):
    """The ratify phase may CREATE additional configs: an upsert write for an
    absent identity lands a new produced/ file (no novelty gate - the write is
    an explicit amendment, not a re-elicitation)."""
    store = HuntStore(tmp_path)
    key = store.update_config(PROJECT, _config(status="ratified"))
    assert key == semantic_key(UNIT, CWE, CLASS)
    configs = store.read_configs(PROJECT)
    assert len(configs) == 1
    assert configs[0]["status"] == "ratified"


def test_update_config_never_triggers_the_novelty_gate(tmp_path):
    """The G4 duplicate-write gate applies to CREATE writes (write_config),
    never to the ratify-phase upsert: amending the same identity repeatedly is
    legal."""
    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config())
    for _ in range(2):
        store.update_config(PROJECT, _config(status="ratified"))
    assert len(store.read_configs(PROJECT)) == 1


# --- dropped configs stay on disk, never deleted (G6) -----------------------

def test_dropped_config_stays_on_disk(tmp_path):
    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config(status="dropped"))
    configs = store.read_configs(PROJECT)
    assert len(configs) == 1
    assert configs[0]["status"] == "dropped"
    # the file survives any later read / note operation (never deleted)
    store.append_note(PROJECT, f"{UNIT}::{CWE}", "a note")
    assert len(store.read_configs(PROJECT)) == 1
    assert (tmp_path / PROJECT / "orchestration" / "hunt_configs" / "produced"
            / f"{UNIT}_{CWE}_{CLASS}.yaml").exists()


# --- read surface: by semantic key and by revival-key prefix ----------------

def test_read_configs_by_semantic_key_and_revival_prefix(tmp_path):
    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config())
    store.write_config(PROJECT, _config(hunt_id="hunt-2", vulnerability_class="CSRF"))
    store.write_config(PROJECT, _config(unit_id="Service:b", fault_class=CWE,
                                        vulnerability_class="IDOR"))
    # the full semantic key reads exactly its config
    exact = store.read_configs_by_key(PROJECT, semantic_key(UNIT, CWE, CLASS))
    assert [c["hunt_id"] for c in exact] == ["hunt-1"]
    # the 2-part revival key reads every class at the locus
    locus = store.read_configs_by_key(PROJECT, f"{UNIT}::{CWE}")
    assert {c["vulnerability_class"] for c in locus} == {"IDOR", "CSRF"}
    # an unknown key reads nothing
    assert store.read_configs_by_key(PROJECT, f"{UNIT}::CWE-9") == []


def test_read_configs_searches_produced_and_consumed(tmp_path):
    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config())
    store.write_config(PROJECT, _config(unit_id="Service:b", fault_class=CWE,
                                        vulnerability_class="CSRF"),
                       directory="consumed")
    assert len(store.read_configs(PROJECT)) == 2


def test_config_read_round_trips_the_full_config(tmp_path):
    store = HuntStore(tmp_path)
    config = _config(prompt_template={
        "rationale": "the catalogue surface is public", "l0_evidence": [],
        "research_direction": "enumerate the receipts resource",
    })
    store.write_config(PROJECT, config)
    out = store.read_configs(PROJECT)[0]
    assert out["unit_id"] == UNIT
    assert out["status"] == "hypothesised"
    assert out["prompt_template"]["research_direction"] == \
        "enumerate the receipts resource"


def test_read_failures_are_fail_open(tmp_path):
    store = HuntStore(tmp_path)
    # a missing project reads nothing, never raises
    assert store.read_configs("absent-project") == []
    assert store.read_configs_by_key("absent-project", UNIT) == []
    assert store.read_notes("absent-project") == []
    # a corrupt config file degrades that record (warned + skipped), the
    # surviving config still reads
    store.write_config(PROJECT, _config())
    corrupt = tmp_path / PROJECT / "orchestration" / "hunt_configs" / "produced"
    (corrupt / f"{UNIT}_CWE-9_broken.yaml").write_text(":: not yaml ::", encoding="utf-8")
    assert len(store.read_configs(PROJECT)) == 1


# --- memory.yaml notes: append / update / delete in natural order -----------

def test_notes_append_in_natural_order(tmp_path):
    store = HuntStore(tmp_path)
    key = f"{UNIT}::{CWE}"
    store.append_note(PROJECT, key, "first")
    store.append_note(PROJECT, key, "second")
    store.append_note(PROJECT, f"{UNIT}::CWE-9", "other")
    notes = store.read_notes(PROJECT, key)
    assert [n["note"] for n in notes] == ["first", "second"]
    # natural append order, no _seq anywhere
    body = (tmp_path / PROJECT / "orchestration" / "memory.yaml").read_text(
        encoding="utf-8")
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


# --- cross-pass visibility on the same project ------------------------------

def test_second_pass_sees_the_first_pass_configs_and_notes(tmp_path):
    """A later pass on the same project reads the prior pass's produced/
    configs and notes through a FRESH store at the same root - the store is
    per-project and per-pass durable, not per-run."""
    store_a = HuntStore(tmp_path)
    store_a.write_config(PROJECT, _config())
    store_a.append_note(PROJECT, f"{UNIT}::{CWE}", "track the IDOR surface")

    store_b = HuntStore(tmp_path)  # a new store, same root
    configs = store_b.read_configs_by_key(PROJECT, f"{UNIT}::{CWE}")
    assert len(configs) == 1
    assert configs[0]["status"] == "hypothesised"
    notes = store_b.read_notes(PROJECT, f"{UNIT}::{CWE}")
    assert [n["note"] for n in notes] == ["track the IDOR surface"]
    # a re-elicited duplicate cannot be written by the second pass (G4)
    with pytest.raises(DuplicateConfigError):
        store_b.write_config(PROJECT, _config())


# --- I1: atomic writes - a crash mid-dump leaves prior content intact --------

def test_failed_note_dump_leaves_prior_content_intact(tmp_path, monkeypatch):
    """I1 - a raising dump leaves the previous memory.yaml content intact (the
    temp-file + os.replace write), so the whole notes history is never lost."""
    store = HuntStore(tmp_path)
    store.append_note(PROJECT, f"{UNIT}::{CWE}", "first")
    memory = tmp_path / PROJECT / "orchestration" / "memory.yaml"
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


def test_failed_config_dump_leaves_no_partial_file(tmp_path, monkeypatch):
    """I1 - a raising dump during a config write leaves no partial target file
    (the pre-atomic truncate-and-rewrite would have left one)."""
    store = HuntStore(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("dump crashed (fixture)")

    monkeypatch.setattr("polymerhus.attack.hunting.hunt_store.yaml.safe_dump", boom)
    with pytest.raises(RuntimeError):
        store.write_config(PROJECT, _config())
    monkeypatch.undo()

    assert store.read_configs(PROJECT) == []
    produced = tmp_path / PROJECT / "orchestration" / "hunt_configs" / "produced"
    assert [p for p in produced.iterdir() if p.name.endswith(".yaml")] == []
    assert [p for p in produced.iterdir() if p.name.endswith(".tmp")] == []


# --- I2: per-project write serialisation (not TOCTOU, no lost updates) -------

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


def test_concurrent_duplicate_config_writes_are_serialised(tmp_path):
    """I2 - concurrent writes of the SAME config id: exactly one succeeds and
    the others hit the DuplicateConfigError gate (the check-then-write runs
    under the project's lock, so the gate is not TOCTOU)."""
    store = HuntStore(tmp_path)
    workers = 4
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []

    def worker():
        barrier.wait()
        try:
            store.write_config(PROJECT, _config())
            outcomes.append("ok")
        except DuplicateConfigError:
            outcomes.append("duplicate")
        except Exception as exc:  # noqa: BLE001 - fail loudly on anything else
            outcomes.append(f"error: {exc}")

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count("ok") == 1
    assert outcomes.count("duplicate") == workers - 1
    assert len(store.read_configs(PROJECT)) == 1


# --- M2: the config directory parameter is validated -------------------------

def test_unknown_config_directory_is_rejected(tmp_path):
    store = HuntStore(tmp_path)
    with pytest.raises(ValueError, match="unknown config directory"):
        store.write_config(PROJECT, _config(), directory="archive")
    # nothing was written anywhere
    assert store.read_configs(PROJECT) == []


# --- M3: the ambiguous CWE-like parse corner (documented, not solved) ---------

def test_ambiguous_cwe_like_segments_parse_greedily(tmp_path):
    """M3 (documented corner, not solved - the memory spec fixed the last-two-
    underscores convention): a unit_id ending in a CWE-like segment and a class
    beginning with a CWE-like segment are indistinguishable from extra CWE
    segments. The greedy regex wins (the unit swallows the earlier CWE-like
    segments) and the content-rebuild fallback does NOT fire - the file name IS
    the identity, so a write/read round-trip keys on the greedy parse."""
    unit = "Service:router_CWE-9"
    cwe = "CWE-9"
    cls = "CWE-9_xml"
    name = config_file_name(unit, cwe, cls)
    assert name == "Service:router_CWE-9_CWE-9_CWE-9_xml.yaml"
    assert parse_config_file_name(name) == \
        ("Service:router_CWE-9_CWE-9", "CWE-9", "xml")

    store = HuntStore(tmp_path)
    store.write_config(PROJECT, _config(unit_id=unit, fault_class=cwe,
                                        vulnerability_class=cls))
    # the greedy parse wins: reading by the original identity finds nothing
    # (the unit was swallowed), reading by the greedy identity finds it
    assert store.read_configs_by_key(PROJECT, f"{unit}::{cwe}") == []
    greedy_unit = "Service:router_CWE-9_CWE-9"
    configs = store.read_configs_by_key(PROJECT, f"{greedy_unit}::{cwe}")
    assert len(configs) == 1
    assert configs[0]["unit_id"] == unit  # the CONTENT keeps the true identity
    assert configs[0]["vulnerability_class"] == cls