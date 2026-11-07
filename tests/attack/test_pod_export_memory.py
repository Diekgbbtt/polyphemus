"""Unit tier: the durable pod-export store (ADR Q16, split from the notes).

The surfer's per-pod completion record lives in its own module bucket
(`hunting/pod-export/notes.yaml`). The hunter's episodic notes file is a
separate file with a separate writer and a separate bound. No live target, no
LLM, no DB.
"""
from __future__ import annotations

import yaml

from polymerhus.attack.hunting import pod_export_memory
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.pod_export_memory import PodExportStore

PROJECT = "proj-1"
HUNT = "Unit__threat-1"
SPEC = "spec__x"


def _export_file(tmp_path):
    return tmp_path / PROJECT / "hunting" / "pod-export" / "notes.yaml"


def _write(store: PodExportStore, *, spec: str = SPEC, verdict: str = "successful",
           run_id: str = "run-1") -> str:
    return store.write_export(
        PROJECT,
        hunt_key=HUNT,
        spec_id=spec,
        run_id=run_id,
        source=f"hunting:run-1:pod:{HUNT}:{spec}",
        export={"verdict": verdict, "terminal_reason": "symptom-confirmed"},
    )


def test_pod_export_store_writes_its_own_module_file(tmp_path):
    """The durable export lands under `hunting/pod-export/`, never in the
    hunter's `hunting/hunter/notes.yaml`."""
    store = PodExportStore(tmp_path)
    key = _write(store)

    assert key == f"{HUNT}:pod-export:{SPEC}"
    assert _export_file(tmp_path).exists()
    assert not (tmp_path / PROJECT / "hunting" / "hunter" / "notes.yaml").exists()

    records = yaml.safe_load(_export_file(tmp_path).read_text(encoding="utf-8"))
    assert len(records) == 1
    record = records[0]
    assert record["key"] == key
    assert record["hunt_key"] == HUNT
    assert record["note_name"] == f"pod-export:{SPEC}"
    assert record["kind"] == "freeform"
    assert record["provenance"]["verdict_stub"] is True
    assert record["provenance"]["source"] == f"hunting:run-1:pod:{HUNT}:{SPEC}"
    assert "symptom-confirmed" in record["body"]


def test_pod_export_store_updates_the_same_key(tmp_path):
    """A re-export of the same spec updates its one current record."""
    store = PodExportStore(tmp_path)
    _write(store, verdict="unsuccessful")
    _write(store, verdict="successful", run_id="run-2")

    records = store.read_exports(PROJECT)
    assert len(records) == 1
    assert records[0]["provenance"]["run_id"] == "run-2"
    assert "successful" in records[0]["body"]
    assert "unsuccessful" not in records[0]["body"]


def test_pod_export_store_keeps_the_hunter_notes_file_separate(tmp_path):
    """The two stores never share a file: a phase note and an export land in
    their own module buckets."""
    hunter = HunterMemoryStore(tmp_path)
    hunter.write_note(
        PROJECT, action="append", hunt_key=HUNT, note_name="phase:grounding",
        kind="phase_summary", body="the phase note",
    )
    exports = PodExportStore(tmp_path)
    _write(exports)

    hunter_notes = hunter.read_notes(PROJECT)
    assert [note["note_name"] for note in hunter_notes] == ["phase:grounding"]
    export_notes = exports.read_exports(PROJECT)
    assert [note["note_name"] for note in export_notes] == [f"pod-export:{SPEC}"]


def test_pod_export_store_reads_latest_first(tmp_path):
    store = PodExportStore(tmp_path)
    _write(store, spec="spec__first")
    _write(store, spec="spec__second")

    names = [note["note_name"] for note in store.read_exports(PROJECT)]
    assert names == ["pod-export:spec__second", "pod-export:spec__first"]


def test_pod_export_store_is_bounded(tmp_path, monkeypatch):
    """The durable trail keeps the newest records under a byte ceiling."""
    monkeypatch.setattr(pod_export_memory, "POD_EXPORT_NOTES_MAX_BYTES", 1200)
    store = PodExportStore(tmp_path)
    for index in range(4):
        _write(store, spec=f"spec__{index}", verdict="x" * 200)

    records = store.read_exports(PROJECT)
    assert records[0]["note_name"] == "pod-export:spec__3"
    assert len(records) < 4
