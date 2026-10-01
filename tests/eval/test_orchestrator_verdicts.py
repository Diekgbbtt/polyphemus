"""The `verdicts.yaml` schema, validation, and atomic write (#271).

The schema is exactly the spec block: vuln_id, identified|partial|missed,
confidence, matched{unit,fault_class,symptom}, evidence_chain (required for
identified/partial), eval_sha, stack_fingerprint. A malformed verdict is
rejected loudly and never written. The write is temp + rename.
"""
from __future__ import annotations

import pytest
import yaml

from orchestrator import evidence, verdicts
from orchestrator.files import (
    FileStore,
    hunt_configs_dir,
    hunter_test_specs_dir,
    pod_experiment_logs_dir,
    pod_spec_dir,
)

SHA = "eval-sha-1"
FINGERPRINT = "fp-1"


def seed_chain(tmp_path, *, project: str = "pid"):
    files = FileStore()
    root = tmp_path / "data"
    files.write_text(
        hunt_configs_dir(root, project, "produced") / "unit_CWE-89_sqli.yaml",
        "id: unit_CWE-89_sqli\n",
    )
    spec_dir = hunter_test_specs_dir(root, project) / "unit_CWE-89_sqli"
    files.write_text(spec_dir / "produced" / "sqli_error.yaml", "id: sqli_error\n")
    files.write_text(pod_experiment_logs_dir(root, project, "sqli_error") / "0.yaml", "o: 0\n")
    files.write_text(pod_spec_dir(root, project, "sqli_error") / "run1.yaml", "v: s\n")
    chain = evidence.resolve_evidence(
        root,
        evidence.EvidenceTarget(
            project_id=project,
            hunt_config="unit_CWE-89_sqli",
            fault_key="unit_CWE-89_sqli",
            spec_id="sqli_error",
            pod_export="run1",
        ),
        files=files,
    )
    return files, root, chain


def row(*, identified: str = "identified", chain: evidence.EvidenceChain | None = None,
        sha: str = SHA, fingerprint: str = FINGERPRINT) -> dict:
    payload = {
        "vuln_id": "comfyui-004",
        "identified": identified,
        "confidence": 0.9,
        "matched": {"unit": "viewer", "fault_class": "CWE-22", "symptom": "file read"},
        "eval_sha": sha,
        "stack_fingerprint": fingerprint,
    }
    if chain is not None:
        payload["evidence_chain"] = chain.to_dict()
    return payload


# --- acceptance ---------------------------------------------------------------


def test_accepts_identified_with_a_resolvable_chain(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)

    parsed = verdicts.validate_verdicts(
        [row(chain=chain)],
        data_root=root,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert parsed[0].identified == "identified"
    assert parsed[0].eval_sha == SHA
    assert parsed[0].matched.fault_class == "CWE-22"
    assert parsed[0].evidence_chain is not None
    assert parsed[0].evidence_chain.spec_dir.endswith("test-specs/unit_CWE-89_sqli")


def test_accepts_partial_with_a_resolvable_chain(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)
    assert verdicts.validate_verdicts(
        [row(identified="partial", chain=chain)],
        data_root=root,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )


def test_accepts_missed_without_a_chain(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)

    parsed = verdicts.validate_verdicts(
        [row(identified="missed")],
        data_root=root,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert parsed[0].identified == "missed"
    assert parsed[0].evidence_chain is None


# --- rejection ----------------------------------------------------------------


def test_accepts_a_missed_row_with_null_matched(tmp_path) -> None:
    # A missed row describes no match: null/empty matched subfields are the
    # honest shape (the same rule as the chain - required only for positive
    # verdicts). Live e2e regression: the first assessment wrote nulls and the
    # strict validator rejected the whole file.
    payload = row(identified="missed")
    payload["matched"] = {"unit": None, "fault_class": None, "symptom": ""}

    parsed = verdicts.validate_verdicts(
        [payload],
        data_root=tmp_path,
        files=FileStore(),
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert parsed[0].identified == "missed"
    assert parsed[0].matched.unit is None
    assert parsed[0].matched.fault_class is None
    assert parsed[0].matched.symptom is None


def test_rejects_a_null_matched_on_an_identified_row(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)
    payload = row(chain=chain)
    payload["matched"] = {"unit": None, "fault_class": "CWE-22", "symptom": "file read"}

    with pytest.raises(verdicts.VerdictError):
        verdicts.validate_verdicts(
            [payload],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


def test_rejects_a_bad_enum(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)

    with pytest.raises(verdicts.VerdictError, match="identified"):
        verdicts.validate_verdicts(
            [row(identified="maybe")],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


def test_rejects_a_missing_chain_on_identified(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)

    with pytest.raises(verdicts.VerdictError, match="evidence_chain"):
        verdicts.validate_verdicts(
            [row(chain=None)],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


def test_rejects_an_unresolvable_chain_path(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)
    broken = dict(row(chain=chain))
    broken["evidence_chain"] = dict(broken["evidence_chain"])
    broken["evidence_chain"]["pod_export"] = "pid/hunting/test-executor-pod/sq/run9.yaml"

    with pytest.raises(verdicts.VerdictError, match="pod_export"):
        verdicts.validate_verdicts(
            [broken],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


def test_rejects_a_missing_sha_or_fingerprint(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)

    with pytest.raises(verdicts.VerdictError, match="eval_sha"):
        verdicts.validate_verdicts(
            [row(sha="")],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )
    with pytest.raises(verdicts.VerdictError, match="stack_fingerprint"):
        verdicts.validate_verdicts(
            [row(fingerprint="")],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


def test_rejects_a_sha_that_does_not_match_the_trial_record(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)

    with pytest.raises(verdicts.VerdictError, match="eval_sha"):
        verdicts.validate_verdicts(
            [row(sha="other-sha")],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


def test_rejects_a_missing_expected_record_identity(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)

    with pytest.raises(verdicts.VerdictError, match="trial record"):
        verdicts.validate_verdicts(
            [row()], data_root=root, files=files, eval_sha=None, stack_fingerprint=None
        )


def test_rejects_a_confidence_out_of_range(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)
    bad = row(identified="missed")
    bad["confidence"] = 1.5

    with pytest.raises(verdicts.VerdictError, match="confidence"):
        verdicts.validate_verdicts(
            [bad],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


def test_rejects_an_unknown_field(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)
    bad = row(identified="missed")
    bad["notes"] = "free text"

    with pytest.raises(verdicts.VerdictError, match="unknown"):
        verdicts.validate_verdicts(
            [bad],
            data_root=root,
            files=files,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )


# --- the atomic write ----------------------------------------------------------


def test_write_validates_and_writes_atomically(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)
    dest = tmp_path / "runs" / "t1" / "trial-1" / "verdicts.yaml"

    verdicts.write_verdicts(
        dest,
        [row(chain=chain)],
        files=files,
        data_root=root,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    written = yaml.safe_load(dest.read_text())
    assert written[0]["vuln_id"] == "comfyui-004"
    assert written[0]["eval_sha"] == SHA
    # Atomic: no temp sibling survives beside the destination.
    leftovers = [p.name for p in dest.parent.iterdir() if p.name != "verdicts.yaml"]
    assert leftovers == []


def test_write_rejects_a_malformed_verdict_loudly(tmp_path) -> None:
    files, root, _chain = seed_chain(tmp_path)
    dest = tmp_path / "runs" / "t1" / "trial-1" / "verdicts.yaml"
    bad = row(identified="maybe")

    with pytest.raises(verdicts.VerdictError):
        verdicts.write_verdicts(
            dest,
            [bad],
            files=files,
            data_root=root,
            eval_sha=SHA,
            stack_fingerprint=FINGERPRINT,
        )

    assert not dest.exists()


def test_load_round_trips_the_written_rows(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)
    dest = tmp_path / "runs" / "t1" / "trial-1" / "verdicts.yaml"
    verdicts.write_verdicts(
        dest,
        [row(chain=chain)],
        files=files,
        data_root=root,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    loaded = verdicts.load_verdicts(
        dest,
        files=files,
        data_root=root,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert loaded[0].vuln_id == "comfyui-004"
    assert loaded[0].evidence_chain.hunt_config == chain.hunt_config
