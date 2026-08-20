"""Unit tier: the append-only markdown hunt-store stub (#68).

Pure filesystem mechanics - no Neo4j, no LLM. Pins the multi-record
round-trip regression the orchestrator's e2e catalogue surfaced: a single
kind file holding several records must yield them all, in append order, never
just the first (the naive `split("\n## ")` dropped the header from every
subsequent block, so a two-hunt file parsed as one hunt record).
"""
from polymerhus.attack.hunting.hunt_store import HuntStore, ProjectMemoryStore


def test_multi_record_file_round_trips_all_records_in_order(tmp_path):
    store = HuntStore(tmp_path)
    store.append("run-1", "hunt", {"hunt_id": "a", "revival_key": "k1"})
    store.append("run-1", "hunt", {"hunt_id": "b", "revival_key": "k2"})
    store.append("run-1", "config", {"hunt_id": "b", "prompt_template": {"rationale": "r"}})

    hunts = store.list_records("run-1", "hunt")
    assert [h["hunt_id"] for h in hunts] == ["a", "b"]
    assert [h["revival_key"] for h in hunts] == ["k1", "k2"]
    assert hunts[0]["_seq"] < hunts[1]["_seq"]

    configs = store.list_records("run-1", "config")
    assert len(configs) == 1
    assert configs[0]["prompt_template"]["rationale"] == "r"


def test_store_wide_sequence_across_kind_files(tmp_path):
    store = HuntStore(tmp_path)
    store.append("run-1", "run", {"run_id": "run-1"})
    config_ref = store.append("run-1", "config", {"hunt_id": "a"})
    hunt_ref = store.append("run-1", "hunt", {"hunt_id": "a"})
    assert config_ref < hunt_ref  # _ref embeds the store-wide seq, ordering the kinds
    configs = store.list_records("run-1", "config")
    hunts = store.list_records("run-1", "hunt")
    assert configs[0]["_seq"] < hunts[0]["_seq"]


def test_unknown_kind_is_rejected(tmp_path):
    store = HuntStore(tmp_path)
    try:
        store.append("run-1", "bogus", {})
    except ValueError as exc:
        assert "unknown hunt-store record kind" in str(exc)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("unknown kind was not rejected")


# --- C1/C2: per-project lazy creation + cross-project isolation (#138) ------

def test_project_memory_created_lazily_and_isolated(tmp_path):
    store = HuntStore(tmp_path)
    # Nothing exists before the first write.
    assert not (tmp_path / "projects").exists()
    store.project_memory.append_config("p1", {"key": "A::x", "hunt_id": "h1"})
    assert (tmp_path / "projects" / "p1" / "configs.yaml").exists()
    # p2's folder is still absent - never eagerly created.
    assert not (tmp_path / "projects" / "p2").exists()
    # Writing p2 does not touch p1's read.
    store.project_memory.append_config("p2", {"key": "B::x", "hunt_id": "h2"})
    assert [r["key"] for r in store.project_memory.read_configs("p1")] == ["A::x"]
    assert [r["key"] for r in store.project_memory.read_configs("p2")] == ["B::x"]


# --- C5: unknown note kind is rejected at write ------------------------------

def test_unknown_note_kind_is_rejected(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    try:
        store.append_note("p1", "Service:slug:a", "fault-x", "nf:detail",
                          "bogus_kind", "body")
    except ValueError as exc:
        assert "unknown note kind" in str(exc)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("unknown note kind was not rejected")


# --- C3: monotonic append + read-latest + within-pass dedup ------------------

def test_notes_append_monotonically_and_read_latest(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_note("p1", "Service:slug:a", "fault-x",
                      "hypothesis_refusal:missing-csrf", "hypothesis_refusal",
                      "form Z carries no CSRF token")
    store.append_note("p1", "Service:slug:a", "fault-x",
                      "implicit_test_primitive:csrf-probe", "implicit_test_primitive",
                      "probe the POST with a bare token")
    notes = store.read_notes("p1")
    # Latest-first: the second note is returned before the first.
    assert notes[0]["kind"] == "implicit_test_primitive"
    assert notes[0]["_seq"] > notes[1]["_seq"]
    history = [n["kind"] for n in notes]  # both survive (history preserved)
    assert set(history) == {"hypothesis_refusal", "implicit_test_primitive"}


# --- C4/C6: grep-match read + empty-valid + fail-open -------------------------

def test_read_notes_grep_match_filters(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_note("p1", "Service:slug:a", "fault-x",
                      "hypothesis_refusal:missing-csrf", "hypothesis_refusal",
                      "no CSRF token on form Z")
    store.append_note("p1", "Service:slug:a", "fault-y",
                      "freeform:forward", "freeform", "consider the upload endpoint")
    # body keyword.
    assert len(store.read_notes("p1", body_keyword="csrf")) == 1
    # key keyword matches the note-key + unit/fault parts.
    assert len(store.read_notes("p1", key_keyword="missing-csrf")) == 1
    # parent index (the pair) matches only its own notes.
    pair = "Service:slug:a:fault-x"
    got = store.read_notes("p1", parent_key=pair)
    assert len(got) == 1 and got[0]["fault_class"] == "fault-x"
    # Combinable filters intersect.
    assert len(store.read_notes("p1", key_keyword="missing-csrf", body_keyword="csrf")) == 1
    # Empty-but-valid: no match yields [], never a failure.
    assert store.read_notes("p1", body_keyword="nothing-matches") == []


def test_read_missing_project_is_empty_valid(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    assert store.read_configs("nope") == []
    assert store.read_notes("nope") == []
    assert store.config_keys("nope") == []


# --- config_keys (the prompt-embedded index, #141) ----------------------------

def test_config_keys_newest_first(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_config("p1", {"key": "Service:slug:a::fault-x", "hunt_id": "h1"})
    store.append_config("p1", {"key": "Service:slug:a::fault-y", "hunt_id": "h2"})
    assert store.config_keys("p1") == [
        "Service:slug:a::fault-y", "Service:slug:a::fault-x",
    ]


# --- review fixes: corrupt-read must not clobber history; delimiter normalisation

def test_corrupt_file_raises_not_silently_clobbers(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_note("p1", "Service:slug:a", "fault-x", "hf:one", "hypothesis_refusal",
                      "first note")
    path = store._notes_file("p1")
    # Corrupt the file: a write that then appends must NOT silently rewrite it
    # to a single record (that would lose the history).
    with path.open("w", encoding="utf-8") as fh:
        fh.write(": this is not: valid yaml [")
    try:
        store.append_note("p1", "Service:slug:a", "fault-x", "hf:two",
                          "hypothesis_refusal", "second note")
    except OSError as exc:
        assert "unreadable memory file" in str(exc)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("corrupt file did not raise before clobbering")
    # The corrupt original is untouched (no silent rewrite happened).
    assert "first note" not in (path.read_text(encoding="utf-8"))


def test_single_colon_parent_matches_config_keyed_with_double_colon(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_config("p1", {"key": "Service:slug:a::fault-x", "hunt_id": "h1"})
    # The single-colon parent index must find the double-colon config key.
    got = store.read_memories("p1", parent_key="Service:slug:a:fault-x")
    kinds = [r["memory_kind"] for r in got]
    assert "config" in kinds
    # And the double-colon revival-key form works too.
    got2 = store.read_memories("p1", parent_key="Service:slug:a::fault-x")
    assert [r["memory_kind"] for r in got2] == kinds


def test_memory_seq_never_collides_after_degraded_record(tmp_path):
    store = ProjectMemoryStore(tmp_path)
    store.append_config("p1", {"key": "A::x", "hunt_id": "h1"})
    store.append_config("p1", {"key": "B::x", "hunt_id": "h2"})
    refs = store.read_configs("p1")
    assert refs[0]["_seq"] == 2 and refs[1]["_seq"] == 1  # max+1, not count+1
