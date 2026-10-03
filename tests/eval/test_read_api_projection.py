"""The eval read-API projection (#278): the authoritative artifact trees -> a report.

The projection reads *only* the materialized trial trees
`<store>/<target_id>/<target_run_id>/<trial_id>/`, honors `run-manifest.yaml`
for identity, preserves every verdict on its trial while counting a success
*only* for `identified`, aggregates versions by the `eval_sha + stack_fingerprint`
pair, and sanitizes diagnoses plus evidence references. These tests pin all of
that, plus the degradations, the `_sync/`/`live/` exclusions, the
no-absolute-paths contract, and deterministic ordering.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from read_api import projection

MANIFEST = "run-manifest.yaml"
VERDICTS = "verdicts.yaml"
DIAGNOSES = "diagnoses.yaml"


# --- fixtures ------------------------------------------------------------------


def _manifest(
    target_id: str,
    target_run_id: str,
    trial_id: str,
    *,
    eval_sha: str = "demo-sha-a",
    stack_fingerprint: str = "demo-env-x",
) -> dict:
    return {
        "schema_version": 1,
        "trial_id": trial_id,
        "target_id": target_id,
        "target_run_id": target_run_id,
        "instance_id": f"inst-{target_id}",
        "project_id": f"proj-{target_id}",
        "start_phase": "recon",
        "terminal": "complete",
        "phases": [
            {"phase": "recon", "status": "complete", "run_id": "recon-1"},
            {"phase": "analysis", "status": "complete", "run_id": "analysis-1"},
            {"phase": "hunting", "status": "complete", "run_id": "hunt-1"},
        ],
        "eval_sha": eval_sha,
        "stack_fingerprint": stack_fingerprint,
        "copied_at": "2024-01-01T00:00:00+00:00",
    }


def _verdict(
    vuln_id: str,
    identified: str = "identified",
    *,
    confidence: float = 0.9,
    unit: str | None = "u",
    fault_class: str | None = "fc",
    symptom: str | None = "s",
    chain: object = "auto",
) -> dict:
    if chain == "auto":
        chain = {
            "hunt_config": f"demo/{vuln_id}/hunt-config.yaml",
            "spec_dir": f"demo/{vuln_id}/spec",
            "experiment_logs": [f"demo/{vuln_id}/log.yaml"],
            "pod_export": f"demo/{vuln_id}/export.yaml",
        }
    return {
        "vuln_id": vuln_id,
        "identified": identified,
        "confidence": confidence,
        "matched": {"unit": unit, "fault_class": fault_class, "symptom": symptom},
        "evidence_chain": chain,
        "eval_sha": "row-sha",
        "stack_fingerprint": "row-fp",
    }


def _diagnosis(vuln: str, **overrides: object) -> dict:
    row: dict = {
        "vuln": vuln,
        "failure_mode": "surface_gap",
        "root_cause": {
            "type": "implementation_defect",
            "combination_of": [],
            "extended_description": "the handler never validated the parameter",
        },
        "diagnosis_overview": "the surface was incomplete for this unit",
        "evidences": [{"source": "spec", "ref": f"demo/{vuln}/spec", "note": "n"}],
        "closest_issue": {"repo": "org/repo", "number": 12, "title": "t", "rationale": "r"},
        "eval_sha": "row-sha",
        "stack_fingerprint": "row-fp",
    }
    row.update(overrides)
    return row


def _write_trial(
    store: Path,
    target_id: str,
    target_run_id: str,
    trial_id: str,
    *,
    manifest: object = "auto",
    verdicts: object = "auto",
    diagnoses: object = None,
) -> Path:
    trial_dir = store / target_id / target_run_id / trial_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    if manifest == "auto":
        manifest = _manifest(target_id, target_run_id, trial_id)
    if manifest is not None:
        _dump(trial_dir / MANIFEST, manifest)
    if verdicts == "auto":
        verdicts = [_verdict("v1")]
    if verdicts is not None:
        _dump(trial_dir / VERDICTS, verdicts)
    if diagnoses is not None:
        _dump(trial_dir / DIAGNOSES, diagnoses)
    return trial_dir


def _dump(path: Path, document: object) -> None:
    text = document if isinstance(document, str) else yaml.safe_dump(document)
    path.write_text(text, encoding="utf-8")


def _snapshot(store: Path) -> dict:
    return projection.build_snapshot(store)


# --- scanning and aggregation --------------------------------------------------


def test_scans_multiple_target_runs_and_trials(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "jetlinks-1", "run-a", "t1", verdicts=[_verdict("v1"), _verdict("v2")])
    _write_trial(store, "jetlinks-1", "run-a", "t2", verdicts=[_verdict("v3")])
    _write_trial(store, "jetlinks-1", "run-b", "t3", verdicts=[_verdict("v4")])
    _write_trial(store, "prestashop-1", "run-a", "t1", verdicts=[_verdict("v5")])

    snap = _snapshot(store)

    assert snap["summary"] == {
        "targets": 2,
        "trials": 4,
        "identified": 5,
        "partial": 0,
        "missed": 0,
        "degraded": 0,
    }
    assert len(snap["trials"]) == 4
    row = next(r for r in snap["successes"] if r["vuln_id"] == "v3")
    assert (row["target_id"], row["target_run_id"], row["trial_id"]) == (
        "jetlinks-1",
        "run-a",
        "t2",
    )
    # Identity is carried from the manifest, never from the verdict row.
    assert row["eval_sha"] == "demo-sha-a"
    assert row["stack_fingerprint"] == "demo-env-x"


def test_every_verdict_is_preserved_on_the_trial(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(
        store,
        "t",
        "r",
        "trial",
        verdicts=[
            _verdict("v3", "missed", unit=None, fault_class=None, symptom=None, chain=None),
            _verdict("v1"),
            _verdict("v2", "partial"),
        ],
        diagnoses=[_diagnosis("v2"), _diagnosis("v3")],
    )

    trial = _snapshot(store)["trials"][0]

    assert [v["vuln_id"] for v in trial["verdicts"]] == ["v1", "v2", "v3"]
    assert [v["identified"] for v in trial["verdicts"]] == ["identified", "partial", "missed"]
    # A missed verdict describes no match; its matched triple is null.
    assert trial["verdicts"][2]["matched"] == {
        "unit": None,
        "fault_class": None,
        "symptom": None,
    }


def test_successes_contain_only_identified(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(
        store,
        "t",
        "r",
        "trial",
        verdicts=[_verdict("ok"), _verdict("maybe", "partial"), _verdict("no", "missed")],
        diagnoses=[_diagnosis("maybe"), _diagnosis("no")],
    )

    snap = _snapshot(store)

    assert [r["vuln_id"] for r in snap["successes"]] == ["ok"]
    assert snap["summary"]["identified"] == 1
    assert snap["summary"]["partial"] == 1
    assert snap["summary"]["missed"] == 1


def test_target_aggregates_count_every_verdict(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(
        store,
        "beta",
        "r1",
        "t1",
        verdicts=[_verdict("v1"), _verdict("v2"), _verdict("v3", "partial")],
        diagnoses=[_diagnosis("v3")],
    )
    _write_trial(store, "beta", "r2", "t2", verdicts=[_verdict("v4", "missed", unit=None, fault_class=None, symptom=None, chain=None)], diagnoses=[_diagnosis("v4")])
    _write_trial(store, "alpha", "r1", "t1", verdicts=[_verdict("v5")])

    targets = _snapshot(store)["targets"]

    assert [t["target_id"] for t in targets] == ["alpha", "beta"]
    assert targets[0] == {
        "target_id": "alpha",
        "trial_count": 1,
        "identified_count": 1,
        "partial_count": 0,
        "missed_count": 0,
    }
    assert targets[1] == {
        "target_id": "beta",
        "trial_count": 2,
        "identified_count": 2,
        "partial_count": 1,
        "missed_count": 1,
    }


# --- versions ------------------------------------------------------------------


def test_versions_group_by_sha_and_fingerprint(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "comfyui-1", "run-a", "t1", manifest=_manifest("comfyui-1", "run-a", "t1", eval_sha="sha-a", stack_fingerprint="env-x"), verdicts=[_verdict("v1")])
    _write_trial(store, "jetlinks-1", "run-a", "t1", manifest=_manifest("jetlinks-1", "run-a", "t1", eval_sha="sha-a", stack_fingerprint="env-x"), verdicts=[_verdict("v2"), _verdict("v3", "missed", unit=None, fault_class=None, symptom=None, chain=None)], diagnoses=[_diagnosis("v3")])
    _write_trial(store, "comfyui-1", "run-a", "t2", manifest=_manifest("comfyui-1", "run-a", "t2", eval_sha="sha-b", stack_fingerprint="env-y"), verdicts=[_verdict("v4")])

    versions = _snapshot(store)["versions"]

    assert [(v["eval_sha"], v["stack_fingerprint"]) for v in versions] == [
        ("sha-a", "env-x"),
        ("sha-b", "env-y"),
    ]
    first = versions[0]
    assert first["targets"] == ["comfyui-1", "jetlinks-1"]
    assert first["trial_count"] == 2
    assert (first["identified"], first["partial"], first["missed"]) == (2, 0, 1)
    assert [t["trial_id"] for t in first["trials"]] == ["t1", "t1"]


def test_same_sha_with_a_different_fingerprint_stays_distinct(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "a", "r", "t", manifest=_manifest("a", "r", "t", eval_sha="sha-a", stack_fingerprint="env-x"), verdicts=[_verdict("v1")])
    _write_trial(store, "b", "r", "t", manifest=_manifest("b", "r", "t", eval_sha="sha-a", stack_fingerprint="env-z"), verdicts=[_verdict("v2")])

    versions = _snapshot(store)["versions"]

    assert [(v["eval_sha"], v["stack_fingerprint"]) for v in versions] == [
        ("sha-a", "env-x"),
        ("sha-a", "env-z"),
    ]


# --- diagnoses -----------------------------------------------------------------


def test_diagnoses_pair_with_partial_and_missed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(
        store,
        "t",
        "r",
        "trial",
        verdicts=[_verdict("v1"), _verdict("v2", "partial"), _verdict("v3", "missed", unit=None, fault_class=None, symptom=None, chain=None)],
        diagnoses=[_diagnosis("v3", proposed_issue={"title": "fix it", "labels": ["bug"]}, closest_issue=None), _diagnosis("v2")],
    )

    trial = _snapshot(store)["trials"][0]

    assert [d["vuln"] for d in trial["diagnoses"]] == ["v2", "v3"]
    assert trial["diagnoses"][0]["failure_mode"] == "surface_gap"
    assert trial["diagnoses"][0]["closest_issue"]["repo"] == "org/repo"
    assert trial["diagnoses"][1]["closest_issue"] is None
    assert trial["diagnoses"][1]["proposed_issue"] == {"title": "fix it", "labels": ["bug"]}


def test_missing_diagnosis_for_a_partial_degrades_only_that_trial(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "t", "r", "good", verdicts=[_verdict("v1")])
    _write_trial(store, "t", "r", "unpaired", verdicts=[_verdict("v2", "partial")])

    snap = _snapshot(store)

    assert [r["vuln_id"] for r in snap["successes"]] == ["v1"]
    assert snap["summary"]["degraded"] == 1
    assert snap["degraded_trials"][0]["reason"] == "diagnoses_missing"
    assert snap["degraded_trials"][0]["trial_id"] == "unpaired"


def test_malformed_diagnoses_degrade_only_that_trial(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "t", "r", "good", verdicts=[_verdict("v1")])
    _write_trial(
        store,
        "t",
        "r",
        "broken",
        verdicts=[_verdict("v2", "missed", unit=None, fault_class=None, symptom=None, chain=None)],
        diagnoses="not: [a, list",
    )

    snap = _snapshot(store)

    assert snap["summary"]["degraded"] == 1
    assert snap["degraded_trials"][0]["reason"] == "diagnoses_invalid"


def test_a_defective_evidence_chain_degrades_only_that_trial(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "t", "r", "good", verdicts=[_verdict("v1")])
    _write_trial(store, "t", "r", "bad-chain", verdicts=[_verdict("v2", chain=["nope"])])

    snap = _snapshot(store)

    assert snap["summary"]["degraded"] == 1
    assert snap["degraded_trials"][0]["reason"] == "verdict_invalid"


# --- degradation ---------------------------------------------------------------


def test_malformed_trial_degrades_without_failing(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "t", "r", "good", verdicts=[_verdict("v1")])
    _write_trial(store, "t", "r", "broken", verdicts="vuln: [unclosed")
    _write_trial(store, "t", "r", "no-manifest", manifest=None)

    snap = _snapshot(store)

    assert [r["vuln_id"] for r in snap["successes"]] == ["v1"]
    assert snap["summary"]["degraded"] == 2
    reasons = {(d["trial_id"], d["reason"]) for d in snap["degraded_trials"]}
    assert ("broken", "verdicts_invalid") in reasons
    assert ("no-manifest", "manifest_missing") in reasons
    # A degraded trial is still a trial, and still projected (sorted by trial_id).
    assert [t["availability"] for t in snap["trials"]] == ["degraded", "complete", "degraded"]


def test_manifest_without_identity_degrades(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(
        store,
        "t",
        "r",
        "trial",
        manifest={"target_id": "t", "target_run_id": "r", "trial_id": "trial"},
        verdicts=None,
    )

    trial = _snapshot(store)["trials"][0]

    assert trial["availability"] == "degraded"
    assert trial["reason"] == "identity_missing"
    assert trial["verdicts"] == []


# --- exclusions and ordering ---------------------------------------------------


def test_ignores_sync_and_live_trees(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "t", "r", "authoritative", verdicts=[_verdict("v1")])
    _write_trial(store / "_sync", "t", "r", "sneaky", verdicts=[_verdict("bad1")])
    _write_trial(store / "arm-a" / "live", "t", "r", "sneaky", verdicts=[_verdict("bad2")])
    _write_trial(store / "_staging" / "trial-x", "t", "r", "staged", verdicts=[_verdict("bad3")])

    snap = _snapshot(store)

    assert [r["vuln_id"] for r in snap["successes"]] == ["v1"]
    assert [trial["trial_id"] for trial in snap["trials"]] == ["authoritative"]
    assert snap["summary"] == {
        "targets": 1,
        "trials": 1,
        "identified": 1,
        "partial": 0,
        "missed": 0,
        "degraded": 0,
    }


def test_skips_files_in_a_target_tree(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "t", "r", "trial", verdicts=[_verdict("v1")])
    (store / "t" / "loose.txt").write_text("not a trial", encoding="utf-8")

    assert _snapshot(store)["summary"]["trials"] == 1


def test_deterministic_ordering(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "b", "r2", "t2", verdicts=[_verdict("v9"), _verdict("v1")])
    _write_trial(store, "b", "r1", "t1", verdicts=[_verdict("v7")])
    _write_trial(store, "a", "r1", "t1", verdicts=[_verdict("v2")])

    first = _snapshot(store)
    second = projection.build_snapshot(store)

    assert first == second
    keys = [
        (r["target_id"], r["target_run_id"], r["trial_id"], r["vuln_id"])
        for r in first["successes"]
    ]
    assert keys == sorted(keys)
    assert keys == [
        ("a", "r1", "t1", "v2"),
        ("b", "r1", "t1", "v7"),
        ("b", "r2", "t2", "v1"),
        ("b", "r2", "t2", "v9"),
    ]


# --- exposure contract ---------------------------------------------------------


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_no_absolute_paths_or_unallowlisted_content(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(
        store,
        "t",
        "r",
        "trial",
        verdicts=[
            _verdict(
                "v1",
                chain={
                    "hunt_config": "/host/secret/cfg.yaml",
                    "spec_dir": "../../escape",
                    "experiment_logs": ["demo/ok/log.yaml", "/host/secret/log.yaml"],
                    "pod_export": "https://example.invalid/export.yaml",
                },
            )
        ],
    )
    _write_trial(store, "t", "r", "degraded", verdicts="broken: [")

    snap = _snapshot(store)
    blob = json.dumps(snap)

    assert str(store) not in blob
    assert str(tmp_path) not in blob
    for value in _walk(snap):
        if isinstance(value, str):
            assert not value.startswith("/"), value

    trial = next(t for t in snap["trials"] if t["trial_id"] == "trial")
    # Only the valid, relative, path-safe reference survives.
    assert trial["verdicts"][0]["evidence"] == ["demo/ok/log.yaml"]


def test_payload_uses_only_the_allowlisted_fields(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(
        store,
        "t",
        "r",
        "trial",
        verdicts=[_verdict("v1"), _verdict("v2", "partial")],
        diagnoses=[_diagnosis("v2")],
    )
    _write_trial(store, "t", "r", "degraded", verdicts="broken: [")

    snap = _snapshot(store)
    trial = next(t for t in snap["trials"] if t["trial_id"] == "trial")

    assert set(snap) == {
        "dataset",
        "summary",
        "targets",
        "trials",
        "versions",
        "coverage",
        "successes",
        "degraded_trials",
    }
    assert set(snap["coverage"]) == {"targets", "vulnerabilities"}
    assert set(snap["coverage"]["targets"]) == {
        "tested",
        "with_identified",
        "without_identified",
    }
    assert set(snap["coverage"]["vulnerabilities"]) == {
        "total",
        "found",
        "not_found",
        "partial",
    }
    assert set(snap["summary"]) == {
        "targets",
        "trials",
        "identified",
        "partial",
        "missed",
        "degraded",
    }
    assert set(snap["targets"][0]) == {
        "target_id",
        "trial_count",
        "identified_count",
        "partial_count",
        "missed_count",
    }
    assert set(trial) == {
        "target_id",
        "target_run_id",
        "trial_id",
        "instance_id",
        "project_id",
        "start_phase",
        "terminal",
        "copied_at",
        "phases",
        "eval_sha",
        "stack_fingerprint",
        "verdicts",
        "diagnoses",
        "availability",
        "reason",
    }
    assert set(trial["phases"][0]) == {"phase", "status", "run_id"}
    assert set(trial["verdicts"][0]) == {
        "vuln_id",
        "identified",
        "confidence",
        "matched",
        "evidence",
    }
    assert set(trial["verdicts"][0]["matched"]) == {
        "unit",
        "fault_class",
        "symptom",
    }
    assert set(trial["diagnoses"][0]) == {
        "vuln",
        "failure_mode",
        "root_cause",
        "diagnosis_overview",
        "closest_issue",
        "proposed_issue",
    }
    assert set(trial["diagnoses"][0]["root_cause"]) == {
        "type",
        "combination_of",
        "extended_description",
    }
    assert set(snap["versions"][0]) == {
        "eval_sha",
        "stack_fingerprint",
        "targets",
        "trial_count",
        "identified",
        "partial",
        "missed",
        "trials",
    }
    assert set(snap["versions"][0]["trials"][0]) == {
        "target_id",
        "target_run_id",
        "trial_id",
        "availability",
        "identified",
        "partial",
        "missed",
    }
    assert set(snap["successes"][0]) == {
        "vuln_id",
        "target_id",
        "target_run_id",
        "trial_id",
        "eval_sha",
        "stack_fingerprint",
        "confidence",
        "matched",
    }
    assert set(snap["degraded_trials"][0]) == {
        "target_id",
        "target_run_id",
        "trial_id",
        "reason",
    }


def test_dataset_defaults_to_webexploitbench(tmp_path: Path) -> None:
    assert _snapshot(tmp_path / "empty")["dataset"] == {
        "id": "webexploitbench",
        "name": "WebExploitBench",
    }


def test_missing_store_projects_empty_snapshot(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path / "does-not-exist")

    assert snap["summary"] == {
        "targets": 0,
        "trials": 0,
        "identified": 0,
        "partial": 0,
        "missed": 0,
        "degraded": 0,
    }
    assert snap["coverage"] == {
        "targets": {"tested": 0, "with_identified": 0, "without_identified": 0},
        "vulnerabilities": {"total": 0, "found": 0, "not_found": 0, "partial": 0},
    }
    assert snap["targets"] == []
    assert snap["trials"] == []
    assert snap["versions"] == []
    assert snap["successes"] == []
    assert snap["degraded_trials"] == []


# --- deduplicated coverage -----------------------------------------------------


def test_coverage_deduplicates_by_target_and_vuln(tmp_path: Path) -> None:
    store = tmp_path / "store"
    # The same vuln in two trials of one Target is a single evaluated vuln.
    _write_trial(store, "t", "r", "t1", verdicts=[_verdict("v1", "partial")], diagnoses=[_diagnosis("v1")])
    _write_trial(store, "t", "r", "t2", verdicts=[_verdict("v1", "identified")])

    coverage = _snapshot(store)["coverage"]

    assert coverage["vulnerabilities"] == {
        "total": 1,
        "found": 1,
        "not_found": 0,
        "partial": 0,
    }


def test_coverage_keeps_the_same_vuln_on_different_targets_apart(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "a", "r", "t1", verdicts=[_verdict("v1")])
    _write_trial(store, "b", "r", "t1", verdicts=[_verdict("v1", "missed", unit=None, fault_class=None, symptom=None)], diagnoses=[_diagnosis("v1")])

    coverage = _snapshot(store)["coverage"]

    # The key is (target_id, vuln_id): one found on a, one not found on b.
    assert coverage["vulnerabilities"] == {
        "total": 2,
        "found": 1,
        "not_found": 1,
        "partial": 0,
    }
    assert coverage["targets"] == {"tested": 2, "with_identified": 1, "without_identified": 1}


def test_coverage_precedence_is_identified_then_partial_then_missed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    # v1: identified beats partial+missed; v2: partial beats missed; v3: missed only.
    _write_trial(
        store,
        "t",
        "r",
        "t1",
        verdicts=[
            _verdict("v1", "partial"),
            _verdict("v2", "partial"),
            _verdict("v3", "missed", unit=None, fault_class=None, symptom=None),
        ],
        diagnoses=[_diagnosis("v1"), _diagnosis("v2"), _diagnosis("v3")],
    )
    _write_trial(
        store,
        "t",
        "r",
        "t2",
        verdicts=[
            _verdict("v1", "identified"),
            _verdict("v2", "missed", unit=None, fault_class=None, symptom=None),
            _verdict("v3", "missed", unit=None, fault_class=None, symptom=None),
        ],
        diagnoses=[_diagnosis("v2"), _diagnosis("v3")],
    )

    coverage = _snapshot(store)["coverage"]

    assert coverage["vulnerabilities"] == {
        "total": 3,
        "found": 1,  # v1, identified in t2
        "not_found": 2,  # v2 (partial) and v3 (missed)
        "partial": 1,  # v2: partial is a subset of not_found
    }


def test_degraded_trials_do_not_affect_vulnerability_coverage(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "t", "r", "good", verdicts=[_verdict("v1")])
    # No verdicts at all: degraded, and it contributes nothing to coverage.
    _write_trial(store, "t", "r", "degraded", manifest=None)
    _write_trial(store, "t", "r", "no-verdicts", verdicts=None)

    snap = _snapshot(store)

    assert snap["coverage"]["vulnerabilities"] == {
        "total": 1,
        "found": 1,
        "not_found": 0,
        "partial": 0,
    }
    assert snap["coverage"]["targets"] == {"tested": 1, "with_identified": 1, "without_identified": 0}
    assert snap["summary"]["trials"] == 3
    assert snap["summary"]["degraded"] == 2


def test_targets_without_identified_findings_are_counted(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_trial(store, "with", "r", "t", verdicts=[_verdict("v1"), _verdict("v2", "missed", unit=None, fault_class=None, symptom=None)], diagnoses=[_diagnosis("v2")])
    _write_trial(store, "without", "r", "t", verdicts=[_verdict("v3", "partial")], diagnoses=[_diagnosis("v3")])

    coverage = _snapshot(store)["coverage"]

    assert coverage["targets"] == {"tested": 2, "with_identified": 1, "without_identified": 1}
