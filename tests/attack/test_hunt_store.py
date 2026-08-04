"""Unit tier: the append-only markdown hunt-store stub (#68).

Pure filesystem mechanics - no Neo4j, no LLM. Pins the multi-record
round-trip regression the orchestrator's e2e catalogue surfaced: a single
kind file holding several records must yield them all, in append order, never
just the first (the naive `split("\n## ")` dropped the header from every
subsequent block, so a two-hunt file parsed as one hunt record).
"""
from polymerhus.attack.hunting.hunt_store import HuntStore


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
