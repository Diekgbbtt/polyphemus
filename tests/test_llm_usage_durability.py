"""Unit tier: the durable usage ledger (`app/llm/usage.py`, #326).

The ledger keeps its process-wide, per-project accumulator in memory, but
WRITE-THROUGHS each project's cumulative entries to a durable per-project file
and READ-THROUGHS them on first use, so a project's spend and its per-agent
breakdown survive an app restart, a stop, or a drain. These tests inject a
temp-rooted `UsageStore`; the unit tier never touches the live data root and
never a database.
"""
from __future__ import annotations

from polymerhus.app.llm.usage import UsageLedger, UsageStore

_ASSIGNER = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_TRIAGER = {"input_tokens": 1, "output_tokens": 4, "total_tokens": 5}


def _fresh(tmp_path) -> UsageLedger:
    """A new-process ledger over the same on-disk store (a simulated restart)."""
    return UsageLedger(store=UsageStore(root=tmp_path))


def test_snapshot_reads_through_a_fresh_ledger_after_a_restart(tmp_path):
    first = UsageLedger(store=UsageStore(root=tmp_path))
    first.record("proj-1", "assigner", _ASSIGNER)
    first.record("proj-1", "triager", _TRIAGER)

    snap = _fresh(tmp_path).snapshot("proj-1")

    assert snap["calls"] == 2
    assert snap["total_tokens"] == 20
    assert snap["by_agent"]["assigner"]["total_tokens"] == 15
    assert snap["by_agent"]["triager"]["total_tokens"] == 5


def test_a_record_is_durable_before_any_flush(tmp_path):
    # The observed d76f1bcc loss was a process death between boundaries, so the
    # durable record cannot wait for a stop/drain: each record write-throughs.
    UsageLedger(store=UsageStore(root=tmp_path)).record("proj-1", "assigner", _ASSIGNER)

    restarted = _fresh(tmp_path)
    assert restarted.snapshot("proj-1")["total_tokens"] == 15
    assert restarted.snapshot("proj-1")["calls"] == 1


def test_resumed_recording_does_not_double_count_the_durable_floor(tmp_path):
    UsageLedger(store=UsageStore(root=tmp_path)).record("proj-1", "assigner", _ASSIGNER)

    resumed = _fresh(tmp_path)
    resumed.record("proj-1", "assigner", _ASSIGNER)

    snap = resumed.snapshot("proj-1")
    assert snap["calls"] == 2
    assert snap["total_tokens"] == 30
    assert snap["by_agent"]["assigner"]["total_tokens"] == 30


def test_flush_persists_in_memory_spend_at_a_boundary(tmp_path):
    ledger = UsageLedger()
    ledger.record("proj-1", "assigner", _ASSIGNER)
    ledger.attach_store(UsageStore(root=tmp_path))

    ledger.flush("proj-1")

    assert _fresh(tmp_path).snapshot("proj-1")["total_tokens"] == 15


def test_flush_all_persists_every_project(tmp_path):
    ledger = UsageLedger(store=UsageStore(root=tmp_path))
    ledger.record("proj-1", "assigner", _ASSIGNER)
    ledger.record("proj-2", "triager", _TRIAGER)

    ledger.flush_all()

    restarted = _fresh(tmp_path)
    assert restarted.snapshot("proj-1")["total_tokens"] == 15
    assert restarted.snapshot("proj-2")["total_tokens"] == 5


def test_flush_does_not_erase_a_durable_project_with_no_live_records(tmp_path):
    # A flush for a project this process never recorded must not clobber its
    # durable record: the read-through loads it first, then re-persists it.
    UsageLedger(store=UsageStore(root=tmp_path)).record("proj-1", "assigner", _ASSIGNER)

    fresh = _fresh(tmp_path)
    fresh.flush("proj-1")

    assert _fresh(tmp_path).snapshot("proj-1")["total_tokens"] == 15


def test_unscoped_records_are_never_persisted(tmp_path):
    ledger = UsageLedger(store=UsageStore(root=tmp_path))
    ledger.record(None, "assigner", _ASSIGNER)
    ledger.record("", "cli", _TRIAGER)

    assert UsageStore(root=tmp_path).read("unscoped") == {}
    assert _fresh(tmp_path).snapshot("proj-1")["calls"] == 0


def test_a_ledger_without_a_store_stays_in_memory(tmp_path):
    ledger = UsageLedger()
    ledger.record("proj-1", "assigner", _ASSIGNER)

    assert ledger.snapshot("proj-1")["total_tokens"] == 15
    assert UsageStore(root=tmp_path).read("proj-1") == {}


def test_record_stays_fail_open_when_the_store_write_raises(tmp_path):
    class _BoomStore:
        def read(self, project_id):
            return {}

        def write(self, project_id, entries):
            raise OSError("disk gone")

    ledger = UsageLedger(store=_BoomStore())
    ledger.record("proj-1", "assigner", _ASSIGNER)

    assert ledger.snapshot("proj-1")["total_tokens"] == 15


def test_snapshot_stays_fail_open_when_the_store_read_raises(tmp_path):
    class _BoomStore:
        def read(self, project_id):
            raise OSError("disk gone")

        def write(self, project_id, entries):
            raise AssertionError("snapshot must not write")

    assert UsageLedger(store=_BoomStore()).snapshot("proj-1")["calls"] == 0


# --- UsageStore: the durable file seam ---------------------------------------

def test_store_round_trips_the_per_agent_entries(tmp_path):
    store = UsageStore(root=tmp_path)
    entries = {
        "assigner": {"cached": 1, "uncached": 2, "reasoning": 3, "visible": 4,
                     "total_tokens": 10, "capped_tokens": 9, "calls": 1,
                     "cache_detail_omitted": 0},
    }

    store.write("proj-1", entries)

    assert store.read("proj-1") == entries


def test_store_reads_a_missing_project_as_empty(tmp_path):
    assert UsageStore(root=tmp_path).read("never-seen") == {}


def test_store_reads_a_corrupt_file_as_empty(tmp_path):
    path = tmp_path / "proj-1" / "usage" / "usage.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("[unclosed\n", encoding="utf-8")

    assert UsageStore(root=tmp_path).read("proj-1") == {}


def test_store_ignores_a_non_mapping_body(tmp_path):
    path = tmp_path / "proj-1" / "usage" / "usage.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    assert UsageStore(root=tmp_path).read("proj-1") == {}
