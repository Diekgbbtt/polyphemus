"""The durable pod-export store (ADR Q16, split from the hunter notes).

The surfer writes ONE durable parent-keyed record per completed pod: the
`PodExport` envelope, keyed `<hunt_key>:pod-export:<spec_id>`.
The record is a crash-safe completion marker, independent of any live parent
inbox and of the pod store's own per-spec file.

This store owns the pod module's notes file under the project data root:

    <data_root>/<project_id>/hunting/test-executor-pod/notes.yaml

The hunter's `hunting/hunter/notes.yaml` holds the hunter's episodic notes
ONLY. The pod's `freeform`/`kb_insight` records and the durable pod-export
records share the one pod notes file, the one project lock, and the one notes
bound. The path is derived from the data root, never from a host path, so a
container bind keeps the file on the host without any code change.
A read falls back to the legacy `hunting/pod-export/notes.yaml` bucket so an
existing run does not lose its exports.

The write is the same atomic whole-file idiom as the other hunting stores
(temp + fsync + `os.replace`), and the read is fail-loud: a corrupt file
raises rather than returning an empty list that a later write would persist.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from polymerhus.app.data_root import DATA_ROOT, project_dir, validate_path_component
from polymerhus.app.memory.store import BoundedRecordStore

__all__ = [
    "POD_EXPORT_EVIDENCE",
    "POD_EXPORT_KIND",
    "POD_EXPORT_NOTES_MAX_BYTES",
    "POD_EXPORT_NOTES_MAX_RECORDS",
    "PodExportStore",
]

# One record per completed pod spec. The run's pod count is bounded by the
# threat set, so the count ceiling is generous. The byte ceiling is a safety
# net for the durable trail, not an eviction policy for ordinary notes; the
# newest record is always kept whole.
POD_EXPORT_NOTES_MAX_RECORDS = 1000
POD_EXPORT_NOTES_MAX_BYTES = 64 * 1024 * 1024
POD_EXPORT_KIND = "freeform"
POD_EXPORT_EVIDENCE = (
    "durable pod-completion export record (ADR Q16): no re-evaluation"
)


class PodExportStore(BoundedRecordStore):
    """The surfer's per-project durable pod-export store."""

    def __init__(self, root_dir: str | Path | None = None):
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT

    @property
    def root(self) -> Path:
        """The data root every project bucket resolves under."""
        return self._root

    def _project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/test-executor-pod", root=self._root)

    def _legacy_project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/pod-export", root=self._root)

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "notes.yaml"

    def _legacy_notes_file(self, project_id: str) -> Path:
        return self._legacy_project_dir(project_id) / "notes.yaml"

    @staticmethod
    def note_key(hunt_key: str, spec_id: str) -> str:
        """The durable record key: the parent dispatch id + the pod marker."""
        return f"{hunt_key}:pod-export:{spec_id}"

    @staticmethod
    def _read_records(path: Path) -> list[dict]:
        """All records in `path`, in natural list order; empty for a missing file.

        A corrupt/unparseable file raises rather than returning [] - a later
        whole-file write would otherwise destroy every earlier record."""
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(
                f"pod-export memory: unreadable notes file {path}: {exc}"
            ) from exc
        if isinstance(loaded, list):
            return [record for record in loaded if isinstance(record, dict)]
        if isinstance(loaded, dict):
            return [record for record in loaded.values() if isinstance(record, dict)]
        return []

    def _write_records(self, path: Path, records: list[dict]) -> None:
        self._dump_yaml_atomic(
            path,
            self._bounded(
                records,
                max_records=POD_EXPORT_NOTES_MAX_RECORDS,
                max_bytes=POD_EXPORT_NOTES_MAX_BYTES,
                # The file is shared with the pod's own notes. The export write
                # may trim other EXPORTS under its bound, but it must never evict
                # the pod's freeform/kb_insight records.
                protected=lambda record: ":pod-export:" not in str(
                    record.get("key") or ""
                ),
            ),
        )

    def write_export(
        self,
        project_id: str,
        *,
        hunt_key: str,
        spec_id: str,
        run_id: str,
        source: str,
        export: dict | None,
    ) -> str:
        """Record one completed pod's export durably.

        The same `(hunt_key, spec_id)` key updates its one current record; a
        new key appends. The whole read-modify-write runs under the lock keyed
        on the shared notes file, so a concurrent pod note append cannot
        lost-update the file.
        """
        validate_path_component(project_id, "project_id")
        validate_path_component(hunt_key, "hunt_key")
        validate_path_component(spec_id, "spec_id")
        key = self.note_key(hunt_key, spec_id)
        record = {
            "key": key,
            "hunt_key": hunt_key,
            "note_name": f"pod-export:{spec_id}",
            "kind": POD_EXPORT_KIND,
            "body": json.dumps(export or {}, sort_keys=True),
            "evidence": POD_EXPORT_EVIDENCE,
            "provenance": {
                "run_id": run_id,
                "source": source,
                "verdict_stub": True,
            },
        }
        with self._lock_for(str(self._notes_file(project_id))):
            path = self._notes_file(project_id)
            records = self._read_records(path)
            for index, existing in enumerate(records):
                if existing.get("key") == key:
                    records[index] = record
                    break
            else:
                records.append(record)
            self._write_records(path, records)
        return key

    def read_exports(
        self, project_id: str, *, hunt_key: str | None = None
    ) -> list[dict]:
        """The project's durable exports, latest-first, optionally per hunt.

        The pod module's notes file is the current home. When it does not
        exist, the legacy `hunting/pod-export/notes.yaml` bucket is read so an
        existing run keeps its exports.
        """
        records = self._read_records(self._notes_file(project_id))
        legacy = self._read_records(self._legacy_notes_file(project_id))
        if legacy:
            known = {str(record.get("key") or "") for record in records}
            records = [
                record for record in legacy
                if str(record.get("key") or "") not in known
            ] + records
        if hunt_key is not None:
            records = [
                record for record in records
                if str(record.get("hunt_key") or "") == hunt_key
            ]
        return list(reversed(records))
