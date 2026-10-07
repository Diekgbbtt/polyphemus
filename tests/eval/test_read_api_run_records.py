"""Unmaterialized Trials: authoritative run records behind the read API.

The store is only one of the sources the dashboard reads. A finished Trial's
authoritative record (its ``trial.yaml``) also lives under the read-only runs
roots, and a Trial that timed out before the materializer ever copied it must
still be catalogued, navigable, and honest about the results it does not have.

These tests pin the catalogue union (store + runs roots), the independent
verdicts/diagnoses availability, the store precedence on a shared identity, the
bind-alias dedup and the physical ambiguity, and the fail-closed safety of the
record reader: no symlink is followed, no malformed record hides its siblings,
and no host path ever reaches the payload.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from read_api import projection, run_records, source

INSTANCE = "inst-1"
PROJECT = "proj-alpha"
IDENTITY = ("comfyui-1", "run-a", "t-timeout")


# --- fixtures ------------------------------------------------------------------


def _verdict(
    vuln_id: str,
    identified: str,
    *,
    confidence: float = 0.8,
    matched: bool = True,
) -> dict:
    row: dict = {
        "vuln_id": vuln_id,
        "identified": identified,
        "confidence": confidence,
        "evidence_chain": None,
    }
    if matched and identified != "missed":
        row["matched"] = {"unit": "u", "fault_class": "fc", "symptom": "s"}
    return row


def _diagnosis(vuln: str) -> dict:
    return {
        "vuln": vuln,
        "failure_mode": "fm",
        "root_cause": {
            "type": "cause",
            "combination_of": [],
            "extended_description": None,
        },
        "diagnosis_overview": "overview",
        "closest_issue": {
            "repo": "org/repo",
            "number": 1,
            "title": "title",
            "rationale": "rationale",
        },
        "proposed_issue": None,
    }


def _write_record(
    directory: Path,
    *,
    target: str = IDENTITY[0],
    run: str = IDENTITY[1],
    trial: str = IDENTITY[2],
    project: str | None = PROJECT,
    instance: str | None = INSTANCE,
    terminal: str | None = "timeout",
    start_phase: str | None = "hunting",
    phases: tuple[tuple[str, str, str], ...] = (
        ("recon", "complete", "recon-1"),
        ("hunting", "timeout", "hunt-1"),
    ),
    eval_sha: str | None = "sha-1",
    stack_fingerprint: str | None = "fp-1",
    filename: str = "trial.yaml",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "trial_id": trial,
        "target_id": target,
        "target_run_id": run,
        "phases": [
            {"phase": phase, "status": status, "run_id": run_id}
            for phase, status, run_id in phases
        ],
    }
    if instance is not None:
        record["instance_id"] = instance
    if project is not None:
        record["project_id"] = project
    if start_phase is not None:
        record["start_phase"] = start_phase
    if terminal is not None:
        record["terminal"] = terminal
    if eval_sha is not None:
        record["eval_sha"] = eval_sha
    if stack_fingerprint is not None:
        record["stack_fingerprint"] = stack_fingerprint
    path = directory / filename
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    return path


def _run_record(
    root: Path,
    *,
    target: str = IDENTITY[0],
    run: str = IDENTITY[1],
    trial: str = IDENTITY[2],
    verdicts: list[dict] | None = None,
    diagnoses: list[dict] | None = None,
    verdicts_text: str | None = None,
    diagnoses_text: str | None = None,
    **record_kwargs: object,
) -> Path:
    directory = root / target / trial
    _write_record(directory, target=target, run=run, trial=trial, **record_kwargs)
    if verdicts is not None:
        (directory / "verdicts.yaml").write_text(
            yaml.safe_dump(verdicts), encoding="utf-8"
        )
    if diagnoses is not None:
        (directory / "diagnoses.yaml").write_text(
            yaml.safe_dump(diagnoses), encoding="utf-8"
        )
    if verdicts_text is not None:
        (directory / "verdicts.yaml").write_text(verdicts_text, encoding="utf-8")
    if diagnoses_text is not None:
        (directory / "diagnoses.yaml").write_text(diagnoses_text, encoding="utf-8")
    return directory


def _store_trial(
    store: Path,
    *,
    target: str,
    run: str,
    trial: str,
    project: str = PROJECT,
    instance: str = INSTANCE,
    terminal: str = "complete",
    verdicts: list[dict] | None = None,
    diagnoses: list[dict] | None = None,
) -> Path:
    directory = store / target / run / trial
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "trial_id": trial,
        "target_id": target,
        "target_run_id": run,
        "instance_id": instance,
        "project_id": project,
        "start_phase": "recon",
        "terminal": terminal,
        "phases": [{"phase": "recon", "status": "complete", "run_id": "recon-1"}],
        "eval_sha": "sha-store",
        "stack_fingerprint": "fp-store",
        "copied_at": "2024-01-01T00:00:00+00:00",
    }
    (directory / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    (directory / "verdicts.yaml").write_text(
        yaml.safe_dump(verdicts if verdicts is not None else []), encoding="utf-8"
    )
    if diagnoses is not None:
        (directory / "diagnoses.yaml").write_text(
            yaml.safe_dump(diagnoses), encoding="utf-8"
        )
    return directory


class _GraphClient:
    def __init__(self, payload: object | None) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_graph(self, project_id: str) -> object:
        self.calls.append(project_id)
        return self.payload


def _graph_payload(project_id: str = PROJECT) -> dict:
    return {
        "project_id": project_id,
        "nodes": [{"id": "n1", "name": "a", "type": "L1Service", "properties": {}}],
        "links": [],
    }


def _raw_project(root: Path, project_id: str = PROJECT) -> None:
    path = root / project_id / "hunting/orchestration/hunt_configs/produced/prod.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("kind: hunt-config\n", encoding="utf-8")


def _adapter(
    tmp_path: Path,
    *,
    runs: Path | None = None,
    legacy: Path | None = None,
    raw: Path | None = None,
    graph: _GraphClient | None = None,
) -> source.ArtifactStoreSnapshotSource:
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    return source.ArtifactStoreSnapshotSource(
        store=store,
        project_data_root=raw,
        runs_root=runs,
        legacy_runs_root=legacy,
        instance_id=INSTANCE,
        graph_client_factory=(lambda: graph) if graph is not None else None,
    )


def _trial(snapshot: dict, trial_id: str) -> dict:
    for trial in snapshot["trials"]:
        if trial["trial_id"] == trial_id:
            return trial
    raise AssertionError(f"trial {trial_id} missing from the snapshot")


def _flatten(groups: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for group in groups:
        entries.extend(group["entries"])
        entries.extend(_flatten(group["children"]))
    return entries


# --- A. a timeout record with no results is catalogued and browsable ----------


def test_timeout_record_without_manifest_is_catalogued(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs)
    adapter = _adapter(tmp_path, runs=runs, raw=tmp_path / "raw")

    snapshot = adapter.snapshot()

    trial = _trial(snapshot, IDENTITY[2])
    assert trial["storage_source"] == "run_record"
    assert trial["terminal"] == "timeout"
    assert trial["copied_at"] is None
    assert trial["project_id"] == PROJECT
    assert trial["instance_id"] == INSTANCE
    assert trial["verdicts"] == []
    assert trial["diagnoses"] == []
    assert trial["results_availability"] == {
        "verdicts": {"status": "unavailable", "reason": "verdicts_missing"},
        "diagnoses": {"status": "unavailable", "reason": "diagnoses_missing"},
    }
    assert snapshot["issues"] == []
    assert str(tmp_path) not in repr(snapshot)


def test_timeout_record_resolves_raw_inventory_detail_and_content(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    _run_record(runs)
    raw = tmp_path / "raw"
    _raw_project(raw)
    adapter = _adapter(tmp_path, runs=runs, raw=raw)

    inventory = adapter.list_resolved_artifacts(*IDENTITY)
    entries = _flatten(inventory["groups"])

    assert inventory["status"] == "available"
    assert inventory["source"] == "project_storage"
    assert entries, "the raw allowlisted tree must be readable"
    entry = entries[0]
    detail = adapter.get_resolved_artifact(*IDENTITY, entry["artifact_id"])
    assert detail["entry"]["relative_path"] == entry["relative_path"]
    download = adapter.stream_resolved_artifact(
        *IDENTITY, entry["artifact_id"], entry["sha256"]
    )
    assert b"hunt-config" in b"".join(download.chunks)


def test_timeout_record_resolves_the_current_graph(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs)
    client = _GraphClient(_graph_payload())
    adapter = _adapter(tmp_path, runs=runs, graph=client)

    body = adapter.resolved_graph(*IDENTITY)

    assert body["status"] == "available"
    assert body["source"] == "project_storage"
    assert client.calls == [PROJECT]
    assert str(tmp_path) not in repr(body)


def test_record_identity_comes_from_content_not_the_filename(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    nested = runs / "whatever" / "deep"
    _write_record(nested, filename="record-2026-10-07.yaml")
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert (trial["target_id"], trial["target_run_id"]) == (IDENTITY[0], IDENTITY[1])


# --- B. verdicts and diagnoses availability are independent --------------------


def test_verdicts_present_without_diagnoses(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(
        runs,
        verdicts=[_verdict("V1", "identified"), _verdict("V2", "partial")],
    )
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert [v["vuln_id"] for v in trial["verdicts"]] == ["V1", "V2"]
    assert trial["results_availability"]["verdicts"] == {
        "status": "available",
        "reason": None,
    }
    assert trial["results_availability"]["diagnoses"] == {
        "status": "unavailable",
        "reason": "diagnoses_missing",
    }
    assert trial["availability"] == "degraded"
    assert trial["reason"] == "diagnoses_missing"


def test_diagnoses_present_without_verdicts(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs, diagnoses=[_diagnosis("V9")])
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["verdicts"] == []
    assert [d["vuln"] for d in trial["diagnoses"]] == ["V9"]
    assert trial["results_availability"]["verdicts"] == {
        "status": "unavailable",
        "reason": "verdicts_missing",
    }
    assert trial["results_availability"]["diagnoses"] == {
        "status": "available",
        "reason": None,
    }


def test_empty_verdicts_file_is_available_not_missing(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs, verdicts=[])
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["results_availability"]["verdicts"] == {
        "status": "available",
        "reason": None,
    }
    assert trial["availability"] == "complete"


def test_invalid_verdict_row_does_not_erase_its_valid_siblings(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    good = _verdict("V1", "identified")
    broken = {"vuln_id": "V2", "identified": "identified", "confidence": "nope"}
    _run_record(runs, verdicts=[good, broken])
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert [v["vuln_id"] for v in trial["verdicts"]] == ["V1"]
    assert trial["results_availability"]["verdicts"] == {
        "status": "available",
        "reason": None,
    }
    assert trial["availability"] == "degraded"
    assert trial["reason"] == "verdict_invalid"


def test_invalid_diagnoses_file_is_unavailable_not_missing(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs, verdicts=[_verdict("V1", "identified")], diagnoses_text="not: [")
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["results_availability"]["diagnoses"] == {
        "status": "unavailable",
        "reason": "diagnoses_invalid",
    }


# --- C. no results: nothing is invented ----------------------------------------


def test_missing_results_invent_no_missed_or_coverage(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs)
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    assert snapshot["summary"]["missed"] == 0
    assert snapshot["summary"]["identified"] == 0
    assert snapshot["coverage"]["vulnerabilities"] == {
        "total": 0,
        "found": 0,
        "not_found": 0,
        "partial": 0,
    }
    assert snapshot["successes"] == []
    assert snapshot["targets"][0]["trial_count"] == 1
    assert snapshot["targets"][0]["missed_count"] == 0


# --- D. results arrive, then the Trial is materialized -------------------------


def test_results_arrive_then_materialization_keeps_one_identity(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    directory = _run_record(runs)
    adapter = _adapter(tmp_path, runs=runs)

    before = [t for t in adapter.snapshot()["trials"] if t["trial_id"] == IDENTITY[2]]
    assert len(before) == 1
    assert before[0]["storage_source"] == "run_record"
    assert before[0]["results_availability"]["verdicts"]["status"] == "unavailable"

    (directory / "verdicts.yaml").write_text(
        yaml.safe_dump([_verdict("V-live", "identified")]), encoding="utf-8"
    )

    after = [t for t in adapter.snapshot()["trials"] if t["trial_id"] == IDENTITY[2]]
    assert len(after) == 1
    assert after[0]["storage_source"] == "run_record"
    assert [v["vuln_id"] for v in after[0]["verdicts"]] == ["V-live"]

    _store_trial(
        tmp_path / "store",
        target=IDENTITY[0],
        run=IDENTITY[1],
        trial=IDENTITY[2],
        verdicts=[_verdict("V-store", "identified")],
    )

    final = [t for t in adapter.snapshot()["trials"] if t["trial_id"] == IDENTITY[2]]
    assert len(final) == 1
    assert final[0]["storage_source"] == "materialized"
    assert [v["vuln_id"] for v in final[0]["verdicts"]] == ["V-store"]


# --- E. shared identity, bind aliases and physical ambiguity -------------------


def test_bind_alias_root_is_read_once(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs)
    alias = tmp_path / "alias"
    os.symlink(runs, alias, target_is_directory=True)
    adapter = _adapter(tmp_path, runs=runs, legacy=alias)

    snapshot = adapter.snapshot()

    assert [t["trial_id"] for t in snapshot["trials"]] == [IDENTITY[2]]
    assert snapshot["issues"] == []


def test_same_identity_in_two_roots_is_not_arbitrated(tmp_path: Path) -> None:
    primary = tmp_path / "runs"
    legacy = tmp_path / "runs-legacy"
    _run_record(primary, project="proj-primary")
    _run_record(legacy, project="proj-legacy")
    _run_record(primary, target="other", run="run-b", trial="t-ok")
    adapter = _adapter(tmp_path, runs=primary, legacy=legacy)

    snapshot = adapter.snapshot()

    assert IDENTITY[2] not in {t["trial_id"] for t in snapshot["trials"]}
    assert "t-ok" in {t["trial_id"] for t in snapshot["trials"]}
    assert snapshot["issues"] == ["run_record_ambiguous"]
    assert str(tmp_path) not in repr(snapshot)


def test_materialized_identity_survives_an_ambiguous_record(tmp_path: Path) -> None:
    primary = tmp_path / "runs"
    legacy = tmp_path / "runs-legacy"
    _run_record(primary, project="proj-primary")
    _run_record(legacy, project="proj-legacy")
    _store_trial(
        tmp_path / "store",
        target=IDENTITY[0],
        run=IDENTITY[1],
        trial=IDENTITY[2],
        verdicts=[_verdict("V-store", "identified")],
    )
    adapter = _adapter(tmp_path, runs=primary, legacy=legacy)

    snapshot = adapter.snapshot()

    trials = [t for t in snapshot["trials"] if t["trial_id"] == IDENTITY[2]]
    assert len(trials) == 1
    assert trials[0]["storage_source"] == "materialized"
    assert trials[0]["project_id"] == PROJECT
    assert snapshot["issues"] == []


def test_conflicting_instance_is_not_associated(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs, instance="other-instance")
    raw = tmp_path / "raw"
    _raw_project(raw)
    client = _GraphClient(_graph_payload())
    adapter = _adapter(tmp_path, runs=runs, raw=raw, graph=client)

    snapshot = adapter.snapshot()
    trial = _trial(snapshot, IDENTITY[2])
    inventory = adapter.list_resolved_artifacts(*IDENTITY)
    graph = adapter.resolved_graph(*IDENTITY)

    assert trial["instance_id"] == "other-instance"
    assert inventory["status"] == "unavailable"
    assert inventory["reason"] == "instance_not_eligible"
    assert graph["status"] == "unavailable"
    assert graph["reason"] == "instance_not_eligible"
    assert client.calls == []


# --- F. fail-closed safety: symlinks, traversal, malformed YAML, missing root --


def test_symlinked_results_file_is_not_followed(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    directory = _run_record(runs)
    secret = tmp_path / "secret.yaml"
    secret.write_text(
        yaml.safe_dump([_verdict("V-secret", "identified")]), encoding="utf-8"
    )
    os.symlink(secret, directory / "verdicts.yaml")
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["verdicts"] == []
    assert trial["results_availability"]["verdicts"]["status"] == "unavailable"


def test_unsafe_identity_is_never_catalogued(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_record(runs / "escape", target="..", trial="t")
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    assert snapshot["trials"] == []
    assert str(tmp_path) not in repr(snapshot)


def test_invalid_yaml_does_not_hide_valid_records(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    (runs / "broken").mkdir(parents=True)
    (runs / "broken" / "trial.yaml").write_text("trial_id: [unclosed\n", encoding="utf-8")
    _run_record(runs, target="other", run="run-b", trial="t-ok")
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    assert [t["trial_id"] for t in snapshot["trials"]] == ["t-ok"]


def test_run_record_is_not_a_spend_record(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    spend = runs / "demo-complete-1"
    spend.mkdir(parents=True)
    (spend / "demo-trial.yaml").write_text(
        yaml.safe_dump(
            {
                "target_id": "demo-complete-1",
                "target_run_id": "demo-run-a",
                "trial_id": "demo-trial",
                "project_id": "p",
                "instance_id": INSTANCE,
                "spent_tokens": 5,
            }
        ),
        encoding="utf-8",
    )
    adapter = _adapter(tmp_path, runs=runs)

    assert adapter.snapshot()["trials"] == []


def test_missing_runs_root_still_serves_the_store(tmp_path: Path) -> None:
    _store_trial(
        tmp_path / "store",
        target="comfyui-1",
        run="run-a",
        trial="t-store",
        verdicts=[_verdict("V-store", "identified")],
    )
    adapter = _adapter(tmp_path, runs=tmp_path / "does-not-exist")

    snapshot = adapter.snapshot()

    assert [t["trial_id"] for t in snapshot["trials"]] == ["t-store"]
    assert snapshot["issues"] == []


# --- the catalogue module itself -----------------------------------------------


def test_catalog_reports_unique_and_ambiguous_identities(tmp_path: Path) -> None:
    primary = tmp_path / "runs"
    legacy = tmp_path / "runs-legacy"
    _run_record(primary)
    _run_record(legacy)
    _run_record(primary, target="other", run="run-b", trial="t-ok")

    catalog = run_records.load_run_record_catalog([primary, legacy], files=None)

    assert set(catalog.records) == {("other", "run-b", "t-ok")}
    assert catalog.ambiguous == (IDENTITY,)
    assert catalog.issues == ("run_record_ambiguous",)


def test_health_distinguishes_catalogued_and_materialized(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run_record(runs)
    _store_trial(
        tmp_path / "store",
        target="comfyui-1",
        run="run-a",
        trial="t-store",
        verdicts=[_verdict("V-store", "identified")],
    )
    adapter = _adapter(tmp_path, runs=runs)

    health = adapter.health().as_dict()

    assert health["materialized_trials"] == 1
    assert health["run_record_trials"] == 1


# --- identity and terminal validation (review hardening) ------------------------


def _base_mapping(
    *,
    target: str = IDENTITY[0],
    run: object = IDENTITY[1],
    trial: str = IDENTITY[2],
    instance: object = INSTANCE,
    project: object = PROJECT,
    terminal: object = "timeout",
    phases: object = None,
) -> dict:
    """A minimal valid record mapping; callers mutate the field under test."""
    return {
        "trial_id": trial,
        "target_id": target,
        "target_run_id": run,
        "instance_id": instance,
        "project_id": project,
        "start_phase": "hunting",
        "terminal": terminal,
        "phases": phases
        if phases is not None
        else [
            {"phase": "recon", "status": "complete", "run_id": "recon-1"},
            {"phase": "hunting", "status": "timeout", "run_id": "hunt-1"},
        ],
    }


def _write_mapping(directory: Path, mapping: dict, *, filename: str = "trial.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "value",
    ["../evil", "a/b", "a\\b", "", ".", "..", 123, 1.5, True, ["x"], {"a": 1}],
    ids=repr,
)
def test_present_invalid_target_run_id_rejects_the_record(
    tmp_path: Path, value: object
) -> None:
    runs = tmp_path / "runs"
    _write_mapping(runs / IDENTITY[0] / IDENTITY[2], _base_mapping(run=value))
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    # Present-but-invalid is never replaced by instance_id: the record is out.
    assert snapshot["trials"] == []


def test_invalid_target_run_id_host_path_never_leaks(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_mapping(
        runs / IDENTITY[0] / IDENTITY[2], _base_mapping(run="/etc/passwd")
    )
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    assert snapshot["trials"] == []
    assert "/etc/passwd" not in repr(snapshot)
    assert str(tmp_path) not in repr(snapshot)


def test_absent_target_run_id_falls_back_to_instance_id(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    mapping = _base_mapping()
    del mapping["target_run_id"]
    _write_mapping(runs / IDENTITY[0] / IDENTITY[2], mapping)
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["target_run_id"] == INSTANCE


def test_null_target_run_id_falls_back_to_instance_id(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_mapping(
        runs / IDENTITY[0] / IDENTITY[2], _base_mapping(run=None)
    )
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["target_run_id"] == INSTANCE


@pytest.mark.parametrize(
    "terminal",
    ["complete", "stopped", "timeout", "failed", "blocked", "interrupted"],
)
def test_supported_producer_terminal_is_accepted(
    tmp_path: Path, terminal: str
) -> None:
    runs = tmp_path / "runs"
    _write_mapping(
        runs / IDENTITY[0] / IDENTITY[2], _base_mapping(terminal=terminal)
    )
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["terminal"] == terminal


@pytest.mark.parametrize(
    "terminal",
    ["pwned", "/etc/passwd", "a/b", "timeout ", "Timeout", "", 123, None, ["timeout"], True],
    ids=repr,
)
def test_unsupported_terminal_is_rejected(tmp_path: Path, terminal: object) -> None:
    runs = tmp_path / "runs"
    _write_mapping(
        runs / IDENTITY[0] / IDENTITY[2], _base_mapping(terminal=terminal)
    )
    adapter = _adapter(tmp_path, runs=runs)

    assert adapter.snapshot()["trials"] == []


def test_rejected_terminal_host_path_never_leaks(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_mapping(
        runs / IDENTITY[0] / IDENTITY[2], _base_mapping(terminal="/etc/passwd")
    )
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    assert snapshot["trials"] == []
    assert "/etc/passwd" not in repr(snapshot)


# --- bounded discovery and bounded results (review hardening) -------------------


def _clutter(directory: Path, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"filler-{index:05d}.txt").write_text("x", encoding="utf-8")


def test_oversized_record_is_skipped_with_an_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_records, "RECORD_MAX_BYTES", 512, raising=False)
    runs = tmp_path / "runs"
    big = _base_mapping(target="big", run="run-b", trial="t-big")
    big["padding"] = "x" * 4096
    _write_mapping(runs / "big" / "t-big", big)
    _run_record(runs, target="other", run="run-b", trial="t-ok")
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    assert [t["trial_id"] for t in snapshot["trials"]] == ["t-ok"]
    assert "run_record_too_large" in snapshot["issues"]
    assert str(tmp_path) not in repr(snapshot)


def test_excessive_entries_report_scan_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_records, "SCAN_MAX_ENTRIES", 4, raising=False)
    primary = tmp_path / "runs"
    _clutter(primary, 50)
    legacy = tmp_path / "runs-legacy"
    _run_record(legacy, target="other", run="run-b", trial="t-ok")
    adapter = _adapter(tmp_path, runs=primary, legacy=legacy)

    snapshot = adapter.snapshot()

    # The exhausted root reports the budget, but a valid Trial in the other
    # root is still catalogueable.
    assert [t["trial_id"] for t in snapshot["trials"]] == ["t-ok"]
    assert "run_record_scan_limit" in snapshot["issues"]
    assert str(tmp_path) not in repr(snapshot)


def test_excessive_depth_reports_scan_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A record sits at depth 3 (<root>/<target>/<trial>/trial.yaml); the deep
    # one is at depth 4 and must never be read.
    monkeypatch.setattr(run_records, "SCAN_MAX_DEPTH", 3, raising=False)
    runs = tmp_path / "runs"
    _run_record(runs, target="shallow", run="run-b", trial="t-shallow")
    _write_mapping(
        runs / "one" / "two" / "three" / "trial.yaml",
        _base_mapping(target="deep", run="run-c", trial="t-deep"),
    )
    adapter = _adapter(tmp_path, runs=runs)

    snapshot = adapter.snapshot()

    assert [t["trial_id"] for t in snapshot["trials"]] == ["t-shallow"]
    assert "run_record_scan_limit" in snapshot["issues"]


def test_oversized_verdicts_degrade_only_their_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projection, "RESULTS_MAX_BYTES", 1024, raising=False)
    runs = tmp_path / "runs"
    _run_record(
        runs,
        verdicts_text=yaml.safe_dump([_verdict("V1", "identified")]) + "#" + "x" * 4096,
        diagnoses=[_diagnosis("V9")],
    )
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["results_availability"]["verdicts"] == {
        "status": "unavailable",
        "reason": "verdicts_too_large",
    }
    assert trial["results_availability"]["diagnoses"] == {
        "status": "available",
        "reason": None,
    }
    assert [d["vuln"] for d in trial["diagnoses"]] == ["V9"]


def test_oversized_diagnoses_degrade_only_their_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projection, "RESULTS_MAX_BYTES", 1024, raising=False)
    runs = tmp_path / "runs"
    _run_record(
        runs,
        verdicts=[_verdict("V1", "identified")],
        diagnoses_text=yaml.safe_dump([_diagnosis("V1")]) + "#" + "x" * 4096,
    )
    adapter = _adapter(tmp_path, runs=runs)

    trial = _trial(adapter.snapshot(), IDENTITY[2])

    assert trial["results_availability"]["diagnoses"] == {
        "status": "unavailable",
        "reason": "diagnoses_too_large",
    }
    assert trial["results_availability"]["verdicts"] == {
        "status": "available",
        "reason": None,
    }
    assert [v["vuln_id"] for v in trial["verdicts"]] == ["V1"]


def test_bind_alias_roots_do_not_double_the_scan_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    _run_record(runs, target="solo", run="run-b", trial="t-solo")
    # The record needs three entries; a budget of four fits one scan but a
    # duplicated (non-deduplicated) scan of the same physical root would not.
    monkeypatch.setattr(run_records, "SCAN_MAX_ENTRIES", 4, raising=False)
    alias = tmp_path / "alias"
    os.symlink(runs, alias, target_is_directory=True)
    adapter = _adapter(tmp_path, runs=runs, legacy=alias)

    snapshot = adapter.snapshot()

    assert [t["trial_id"] for t in snapshot["trials"]] == ["t-solo"]
    assert snapshot["issues"] == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
