"""The recorded-spend resolver for the Trial report (current-usage feature).

The live `GET /projects/{id}/usage` endpoint is a process-wide, in-memory
accumulator: it dies with the app and carries no per-run attribution. The
*recorded* spend of a finished Trial lives in the harness's authoritative
``trial.yaml`` under the runs root, not in the artifact store. This resolver
maps one fully-identified Trial from the projected ``/snapshot`` to that record:

- the record filename is arbitrary - it is matched by the full identity
  ``(target_id, target_run_id, trial_id)`` plus a verified ``project_id`` and
  ``instance_id``;
- an absent or ambiguous association is ``unavailable`` (never guessed);
- zero is a value, a missing field is ``None`` (the UI shows "non disponibile");
- the overshoot is never added to the spent total, and the per-agent breakdown
  is preserved verbatim (no invented attributions);
- nothing here mutates a record or exposes a host path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from read_api import trial_spend

TARGET = "comfyui-1"
RUN = "run-real-1"
TRIAL = "trial-1"
PROJECT = "c0641257-a1a9-4e13-acee-6effa28311f5"
INSTANCE = "eval-server-1"


def _write_record(runs_root: Path, name: str, record: dict) -> None:
    path = runs_root / "ignored" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")


def _identity(**overrides) -> dict:
    record = {
        "target_id": TARGET,
        "target_run_id": RUN,
        "trial_id": TRIAL,
        "project_id": PROJECT,
        "instance_id": INSTANCE,
        "terminal": "stopped",
        "spent_tokens": 500,
        "spend_overshoot": 0,
        "spend_by_agent": {"recon": {"total_tokens": 1500}},
    }
    record.update(overrides)
    return record


def _resolve(runs_root: Path | None):
    return trial_spend.resolve_trial_spend(
        runs_root,
        target_id=TARGET,
        target_run_id=RUN,
        trial_id=TRIAL,
        project_id=PROJECT,
        instance_id=INSTANCE,
    )


# --- resolution by full identity -----------------------------------------------


def test_a_record_with_an_arbitrary_filename_is_matched_by_full_identity(
    tmp_path: Path,
) -> None:
    _write_record(tmp_path, "spend-report-a1b2c3.yaml", _identity())

    spend = _resolve(tmp_path)

    assert spend.status == "available"
    assert spend.reason is None
    assert spend.spent_tokens == 500
    assert spend.spend_overshoot == 0
    assert spend.spend_by_agent == {"recon": {"total_tokens": 1500}}


def test_a_non_yaml_file_is_never_treated_as_the_record(tmp_path: Path) -> None:
    _write_record(tmp_path, "notes.json", _identity())

    spend = _resolve(tmp_path)

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_RECORD_NOT_FOUND


@pytest.mark.parametrize(
    "overrides",
    [
        {"project_id": "another-project"},
        {"instance_id": "another-instance"},
        {"target_run_id": "another-run"},
        {"trial_id": "another-trial"},
        {"target_id": "another-target"},
    ],
)
def test_a_mismatched_identity_never_matches(tmp_path: Path, overrides: dict) -> None:
    _write_record(tmp_path, "record.yaml", _identity(**overrides))

    spend = _resolve(tmp_path)

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_RECORD_NOT_FOUND


def test_two_matching_records_are_ambiguous_and_unavailable(tmp_path: Path) -> None:
    _write_record(tmp_path, "first.yaml", _identity())
    _write_record(tmp_path, "second.yaml", _identity())

    spend = _resolve(tmp_path)

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_RECORD_AMBIGUOUS


def test_an_unsafe_identity_is_never_matched(tmp_path: Path) -> None:
    _write_record(tmp_path, "record.yaml", _identity())

    spend = trial_spend.resolve_trial_spend(
        tmp_path,
        target_id=TARGET,
        target_run_id="../escape",
        trial_id=TRIAL,
        project_id=PROJECT,
        instance_id=INSTANCE,
    )

    assert spend.status == "unavailable"


# --- field semantics -----------------------------------------------------------


def test_zero_spent_stays_zero_not_missing(tmp_path: Path) -> None:
    _write_record(tmp_path, "r.yaml", _identity(spent_tokens=0, spend_overshoot=0))

    spend = _resolve(tmp_path)

    assert spend.status == "available"
    assert spend.spent_tokens == 0
    assert spend.spend_overshoot == 0


def test_a_missing_field_is_none_while_zero_stays_zero(tmp_path: Path) -> None:
    record = _identity()
    del record["spent_tokens"]
    record["spend_overshoot"] = 0
    _write_record(tmp_path, "r.yaml", record)

    spend = _resolve(tmp_path)

    assert spend.status == "available"
    assert spend.spent_tokens is None
    assert spend.spend_overshoot == 0


def test_the_overshoot_is_never_added_to_the_spent_total(tmp_path: Path) -> None:
    _write_record(tmp_path, "r.yaml", _identity(spent_tokens=500, spend_overshoot=200))

    spend = _resolve(tmp_path)

    assert spend.spent_tokens == 500
    assert spend.spend_overshoot == 200


def test_the_per_agent_breakdown_is_preserved_without_new_attributions(
    tmp_path: Path,
) -> None:
    breakdown = {
        "recon": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "calls": 2},
        "hunting": {"total_tokens": 485, "calls": 3},
    }
    _write_record(tmp_path, "r.yaml", _identity(spend_by_agent=breakdown))

    spend = _resolve(tmp_path)

    assert spend.spend_by_agent == breakdown


@pytest.mark.parametrize(
    "overrides",
    [
        {"spent_tokens": "many"},
        {"spent_tokens": -1},
        {"spent_tokens": True},
        {"spend_overshoot": "a lot"},
        {"spend_by_agent": "recon"},
        {"spend_by_agent": {"recon": "15"}},
    ],
)
def test_an_invalid_field_marks_the_spend_unavailable(
    tmp_path: Path, overrides: dict
) -> None:
    _write_record(tmp_path, "r.yaml", _identity(**overrides))

    spend = _resolve(tmp_path)

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_RECORD_INVALID


def test_a_null_by_agent_block_is_missing_not_invalid(tmp_path: Path) -> None:
    _write_record(tmp_path, "r.yaml", _identity(spend_by_agent=None))

    spend = _resolve(tmp_path)

    assert spend.status == "available"
    assert spend.spend_by_agent is None


# --- configuration / safety ----------------------------------------------------


def test_an_unconfigured_root_is_unavailable(tmp_path: Path) -> None:
    spend = _resolve(None)

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_ROOT_UNCONFIGURED


def test_a_missing_identity_is_unavailable(tmp_path: Path) -> None:
    _write_record(tmp_path, "r.yaml", _identity())

    spend = trial_spend.resolve_trial_spend(
        tmp_path,
        target_id=TARGET,
        target_run_id=RUN,
        trial_id=TRIAL,
        project_id=None,
        instance_id=INSTANCE,
    )

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_IDENTITY_UNAVAILABLE


def test_the_result_never_carries_a_host_path(tmp_path: Path) -> None:
    _write_record(tmp_path, "r.yaml", _identity())

    spend = _resolve(tmp_path)

    assert str(tmp_path) not in json.dumps(spend.to_dict())


def test_a_corrupt_yaml_record_is_ignored_not_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "target" / "broken.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(":\n  - [unbalanced", encoding="utf-8")
    _write_record(tmp_path, "good.yaml", _identity())

    spend = _resolve(tmp_path)

    assert spend.status == "available"
    assert spend.spent_tokens == 500


# --- primary + optional legacy runs roots ---------------------------------------


def _resolve_in(primary: Path | None, legacy: Path | None):
    return trial_spend.resolve_trial_spend(
        primary,
        legacy_runs_root=legacy,
        target_id=TARGET,
        target_run_id=RUN,
        trial_id=TRIAL,
        project_id=PROJECT,
        instance_id=INSTANCE,
    )


def test_the_legacy_root_supplies_a_record_the_primary_root_does_not(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "runs"
    legacy = tmp_path / "legacy-runs"
    primary.mkdir()
    _write_record(legacy, "historical.yaml", _identity())

    spend = _resolve_in(primary, legacy)

    assert spend.status == "available"
    assert spend.spent_tokens == 500


def test_the_primary_root_supplies_a_record_the_legacy_root_does_not(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "runs"
    legacy = tmp_path / "legacy-runs"
    legacy.mkdir()
    _write_record(primary, "current.yaml", _identity())

    spend = _resolve_in(primary, legacy)

    assert spend.status == "available"
    assert spend.spent_tokens == 500


def test_the_same_root_configured_twice_is_not_a_conflict(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _write_record(root, "only.yaml", _identity())

    spend = _resolve_in(root, root)

    assert spend.status == "available"
    assert spend.spent_tokens == 500


def test_one_identity_in_two_different_roots_is_ambiguous(tmp_path: Path) -> None:
    primary = tmp_path / "runs"
    legacy = tmp_path / "legacy-runs"
    _write_record(primary, "current.yaml", _identity())
    _write_record(legacy, "historical.yaml", _identity())

    spend = _resolve_in(primary, legacy)

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_RECORD_AMBIGUOUS
    assert spend.spent_tokens is None


def test_no_configured_root_stays_unavailable(tmp_path: Path) -> None:
    spend = _resolve_in(None, None)

    assert spend.status == "unavailable"
    assert spend.reason == trial_spend.SPEND_ROOT_UNCONFIGURED


def test_loading_records_skips_a_missing_and_a_repeated_root(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _write_record(root, "only.yaml", _identity())

    records = trial_spend.load_spend_records_from_roots(
        [root, tmp_path / "missing", root]
    )

    assert len(records) == 1
