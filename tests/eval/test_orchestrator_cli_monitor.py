"""The `monitor` CLI verb (#289, #350) - the tick plan engine.

The monitor never dispatches: it reports, per trial, the next workflow action
as JSON (a `dispatch` with the role agent, the launch message, and the
destination; or an `escalate` with a named cause), and applies the native child
terminals the plugin reports back through `--results` before re-planning. This
is the deterministic half of the synchronous assessor -> diagnoser flow.
"""
from __future__ import annotations

import io
import json

import yaml

from orchestrator import cli

SHA = "eval-sha-1"
FP = "fp-1"


def _setup_payload(target: str = "comfyui") -> dict:
    return {
        "schema_version": 1,
        "artifact_store": "/srv/a",
        "work_items": [{"name": "auth-bootstrap", "status": "complete"}],
        "instances": [
            {
                "instance_id": "arm-a",
                "targets": [
                    {"target_key": f"webexploitbench/{target}", "target_id": target}
                ],
            }
        ],
    }


def _write_setup(tmp_path, payload) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def _trial_dir(tmp_path):
    return tmp_path / "runs" / "comfyui" / "trial-1"


def _write_trial(tmp_path, *, terminal: str = "complete", assessment=None, diagnosis=None) -> None:
    trial_dir = _trial_dir(tmp_path)
    trial_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trial_id": "trial-1",
        "instance_id": "arm-a",
        "target_id": "comfyui",
        "project_id": "pid",
        "start_phase": "recon",
        "terminal": terminal,
        "phases": [],
        "started_at": "2026-10-01T00:00:00+00:00",
        "finished_at": "2026-10-01T01:00:00+00:00",
        "eval_sha": SHA,
        "stack_fingerprint": FP,
    }
    if assessment is not None:
        payload["assessment"] = assessment
    if diagnosis is not None:
        payload["diagnosis"] = diagnosis
    (trial_dir / "trial.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def _write_verdicts(tmp_path, *, identified: str = "missed") -> None:
    path = _trial_dir(tmp_path) / "verdicts.yaml"
    rows = [
        {
            "vuln_id": "comfyui-001",
            "identified": identified,
            "confidence": 0.2,
            "matched": {},
            "eval_sha": SHA,
            "stack_fingerprint": FP,
        }
    ]
    path.write_text(yaml.safe_dump(rows), encoding="utf-8")


def _write_diagnoses(tmp_path) -> None:
    path = _trial_dir(tmp_path) / "diagnoses.yaml"
    rows = [
        {
            "vuln": "comfyui-001",
            "failure_mode": "surface_gap",
            "root_cause": {"type": "missing_component", "extended_description": "x"},
            "diagnosis_overview": "x",
            "evidences": [],
            "proposed_issue": {"title": "t", "body": "b", "labels": []},
            "eval_sha": SHA,
            "stack_fingerprint": FP,
        }
    ]
    path.write_text(yaml.safe_dump(rows), encoding="utf-8")


def _trial_payload(tmp_path) -> dict:
    return yaml.safe_load((_trial_dir(tmp_path) / "trial.yaml").read_text())


def _run(tmp_path, setup, *, results=None) -> tuple[int, dict, str]:
    argv = [
        "monitor",
        setup,
        "--ground-truth",
        str(tmp_path / "gt" / "comfyui"),
        "--data-root",
        str(tmp_path / "data"),
        "--runs-root",
        str(tmp_path / "runs"),
    ]
    if results is not None:
        results_path = tmp_path / "results.json"
        results_path.write_text(json.dumps(results), encoding="utf-8")
        argv += ["--results", str(results_path)]
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=out, stderr=err)
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    return code, report, err.getvalue()


def _one(report: dict) -> dict:
    assert len(report["actions"]) == 1
    return report["actions"][0]


# --- the plan (read-only) ------------------------------------------------------


def test_plan_lists_a_successful_trial_and_dispatches_nothing(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    code, report, _ = _run(tmp_path, setup)

    assert code == 0
    action = _one(report)
    assert action["action"] == "dispatch"
    assert action["node"] == "assessment"
    assert action["role"] == "eval-assessor"
    assert action["destination"].endswith("verdicts.yaml")
    assert "trial record" in action["message"]
    assert "verdicts.yaml" in action["message"]
    # The plan is read-only: it never writes the trial record.
    assert "assessment" not in _trial_payload(tmp_path)


def test_plan_defers_a_failed_execution(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path, terminal="failed")

    _, report, _ = _run(tmp_path, setup)
    action = _one(report)
    assert action["action"] is None
    assert action["state"] == "deferred"


def test_plan_defers_an_interrupted_execution(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path, terminal="interrupted")
    _, report, _ = _run(tmp_path, setup)
    assert _one(report)["state"] == "deferred"


def test_plan_dispatches_diagnosis_for_missed_verdicts(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path, assessment={"status": "present", "attempts": []})
    _write_verdicts(tmp_path, identified="missed")

    _, report, _ = _run(tmp_path, setup)
    action = _one(report)
    assert action["node"] == "diagnosis"
    assert action["role"] == "eval-diagnoser"
    assert "comfyui-001" in action["message"]
    assert action["destination"].endswith("diagnoses.yaml")


def test_plan_escalates_after_the_bound(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    old = "2026-01-01T00:00:00+00:00"
    _write_trial(
        tmp_path,
        assessment={
            "status": "dispatched",
            "attempts": [
                {"attempt": 1, "outcome": "error", "detail": "x", "at": old},
                {"attempt": 2, "outcome": "error", "detail": "y", "at": old},
            ],
        },
    )
    code, report, _ = _run(tmp_path, setup)
    action = _one(report)
    assert action["action"] == "escalate"
    assert action["cause"] == "dispatcher_process"
    assert code == 1


# --- applying the native child terminals ---------------------------------------


def test_assessment_success_advances_straight_to_diagnosis(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)
    _write_verdicts(tmp_path, identified="missed")

    _, report, _ = _run(
        tmp_path,
        setup,
        results=[{"trial_record": str(_trial_dir(tmp_path) / "trial.yaml"), "node": "assessment", "outcome": "success"}],
    )

    action = _one(report)
    assert action["node"] == "diagnosis"
    payload = _trial_payload(tmp_path)
    assert payload["assessment"]["status"] == "dispatched"
    assert payload["assessment"]["attempts"][-1]["outcome"] == "dispatched"


def test_a_failure_records_an_error_attempt_and_awaits(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    _, report, _ = _run(
        tmp_path,
        setup,
        results=[
            {
                "trial_record": str(_trial_dir(tmp_path) / "trial.yaml"),
                "node": "assessment",
                "outcome": "failure",
                "detail": "boom",
            }
        ],
    )

    payload = _trial_payload(tmp_path)
    assert payload["assessment"]["attempts"][-1]["outcome"] == "error"
    action = _one(report)
    assert action["action"] == "await"
    assert action["state"] == "awaiting_assessment"


def test_a_provider_death_records_the_provider_outcome_and_backs_off(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    _, report, _ = _run(
        tmp_path,
        setup,
        results=[
            {
                "trial_record": str(_trial_dir(tmp_path) / "trial.yaml"),
                "node": "assessment",
                "outcome": "failure",
                "detail": "AI_APICallError: Go usage limit exceeded",
            }
        ],
    )

    payload = _trial_payload(tmp_path)
    assert payload["assessment"]["attempts"][-1]["outcome"] == "provider"
    action = _one(report)
    assert action["action"] == "await"
    assert "provider-quota" in action["detail"]


def test_an_escalation_result_writes_the_named_failure_once(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    code, report, _ = _run(
        tmp_path,
        setup,
        results=[
            {
                "trial_record": str(_trial_dir(tmp_path) / "trial.yaml"),
                "node": "assessment",
                "escalate": True,
                "cause": "empty_file",
            }
        ],
    )

    payload = _trial_payload(tmp_path)
    assert payload["assessment"]["status"] == "escalated"
    assert payload["assessment"]["failure"] == "assessment_empty_file"
    action = _one(report)
    assert action["action"] is None  # already escalated, nothing left to apply
    assert action["state"] == "escalated"
    assert code == 1


def test_a_paired_diagnosis_completes_the_trial(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(
        tmp_path,
        assessment={"status": "present", "attempts": []},
        diagnosis={"status": "present", "attempts": []},
    )
    _write_verdicts(tmp_path, identified="missed")
    _write_diagnoses(tmp_path)

    code, report, _ = _run(tmp_path, setup)
    action = _one(report)
    assert action["state"] == "complete"
    assert action["action"] is None
    assert code == 0
