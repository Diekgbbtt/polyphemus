"""The `diagnose`, `issue-search`, and extended `close-verify` verbs (#272).

`diagnose --dry-run` prints the diagnoser dispatch plan and executes nothing;
the dispatcher factory is a parameter so a test can prove it. `close-verify`
extends to the `diagnoses.yaml` pairing check (D19/D22).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from orchestrator import assessment, cli, diagnosis


def _setup_payload(*, target: str = "comfyui") -> dict:
    return {
        "schema_version": 1,
        "artifact_store": "/srv/a",
        "work_items": [{"name": "auth-bootstrap", "status": "complete"}],
        "instances": [
            {
                "instance_id": "arm-a",
                "targets": [
                    {
                        "target_id": target,
                        "target_config": {
                            "lifecycle": "targetctl",
                            "params": {"target": target},
                        },
                    }
                ],
            }
        ],
    }


def _write_setup(tmp_path, payload) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def _write_trial(tmp_path, *, verdicts_rows=None, trace_id=None) -> str:
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    trial_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trial_id": "trial-1",
        "instance_id": "arm-a",
        "target_id": "comfyui",
        "project_id": "pid",
        "start_phase": "recon",
        "terminal": "complete",
        "phases": [],
        "started_at": "t",
        "finished_at": "t",
        "eval_sha": "eval-sha-1",
        "stack_fingerprint": "fp-1",
    }
    if trace_id is not None:
        payload["trace_id"] = trace_id
    (trial_dir / "trial.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    if verdicts_rows is not None:
        (trial_dir / "verdicts.yaml").write_text(
            yaml.safe_dump(verdicts_rows), encoding="utf-8"
        )
    return str(trial_dir)


def _missed_verdict(vuln_id: str = "v1") -> dict:
    return {
        "vuln_id": vuln_id,
        "identified": "missed",
        "confidence": 0.5,
        "matched": {"unit": "u", "fault_class": "CWE-89", "symptom": "s"},
        "evidence_chain": None,
        "eval_sha": "eval-sha-1",
        "stack_fingerprint": "fp-1",
    }


def _diagnosis_row(vuln: str = "v1") -> dict:
    return {
        "vuln": vuln,
        "failure_mode": "surface_gap",
        "root_cause": {
            "type": "implementation_defect",
            "extended_description": "missed the route",
        },
        "diagnosis_overview": "never reached the sink",
        "evidences": [{"source": "pod_export", "ref": "run1", "note": "no success"}],
        "proposed_issue": {"title": "gap", "body": "b", "labels": []},
    }


def _explode(*_args, **_kwargs):
    raise AssertionError("dry-run must never construct a dispatcher")


class FakeDispatcher:
    def __init__(self, action=None):
        self.requests = []
        self.action = action

    def __call__(self, request):
        self.requests.append(request)
        if self.action is not None:
            self.action(request)


class FakeBank:
    def __init__(self, hits=()):
        self.hits = tuple(hits)
        self.queries = []
        self.limits = []

    def search(self, query: str, *, limit: int = 5):
        self.queries.append(query)
        self.limits.append(limit)
        return self.hits


def _common(tmp_path) -> list[str]:
    return [
        "--ground-truth", str(tmp_path / "gt" / "comfyui"),
        "--data-root", str(tmp_path / "data"),
        "--runs-root", str(tmp_path / "runs"),
        "--command", "agent assess {prompt} {trial_record} {ground_truth}",
    ]


def _diag_common(tmp_path) -> list[str]:
    return [
        "--ground-truth", str(tmp_path / "gt" / "comfyui"),
        "--data-root", str(tmp_path / "data"),
        "--runs-root", str(tmp_path / "runs"),
        "--diagnose-command",
        "agent diagnose {prompt} {trial_record} {verdicts} {destination} {vulns}",
    ]


def _close_common(tmp_path) -> list[str]:
    # close-verify runs the assessment phase too, so it needs both commands.
    return _common(tmp_path) + _diag_common(tmp_path)


def test_diagnose_dry_run_prints_the_plan_and_dispatches_nothing(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    trial_dir = _write_trial(tmp_path, verdicts_rows=[_missed_verdict()])

    code = cli.main(
        ["diagnose", setup, "--trial", trial_dir, *_diag_common(tmp_path), "--dry-run"],
        runner_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "diagnoser.md" in out
    assert "diagnoses.yaml" in out
    assert "v1" in out


def test_diagnose_dispatches_through_the_injected_dispatcher(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    trial_dir = _write_trial(tmp_path, verdicts_rows=[_missed_verdict()])
    fake = FakeDispatcher()

    code = cli.main(
        ["diagnose", setup, "--trial", trial_dir, *_diag_common(tmp_path)],
        runner_factory=_explode,
        diagnose_dispatch_factory=lambda _argv: fake,
    )

    assert code == 0
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request.destination == tmp_path / "runs" / "comfyui" / "trial-1" / "diagnoses.yaml"
    assert request.vulns == ("v1",)
    assert request.verdicts == tmp_path / "runs" / "comfyui" / "trial-1" / "verdicts.yaml"
    payload = yaml.safe_load((tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text())
    assert payload["diagnosis"]["status"] == "dispatched"


def test_diagnose_request_carries_the_trial_trace_id(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    trial_dir = _write_trial(tmp_path, verdicts_rows=[_missed_verdict()], trace_id="trace-7")
    fake = FakeDispatcher()

    code = cli.main(
        ["diagnose", setup, "--trial", trial_dir, *_diag_common(tmp_path)],
        runner_factory=_explode,
        diagnose_dispatch_factory=lambda _argv: fake,
    )

    assert code == 0
    assert fake.requests[0].trace_id == "trace-7"


def test_diagnose_refuses_a_trial_without_valid_verdicts(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    trial_dir = _write_trial(tmp_path)
    # An empty verdicts file is itself invalid; `diagnose` refuses loudly.
    (tmp_path / "runs" / "comfyui" / "trial-1" / "verdicts.yaml").write_text("[]\n")

    code = cli.main(
        ["diagnose", setup, "--trial", trial_dir, *_diag_common(tmp_path)],
        runner_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    assert code == 1
    assert "verdict" in capsys.readouterr().err.lower()


def test_close_verify_escalates_an_unpaired_diagnosis(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path, verdicts_rows=[_missed_verdict()])
    fake = FakeDispatcher()  # never writes diagnoses.yaml

    code = cli.main(
        ["close-verify", setup, *_close_common(tmp_path)],
        runner_factory=_explode,
        dispatch_factory=lambda _argv: FakeDispatcher(),
        diagnose_dispatch_factory=lambda _argv: fake,
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "diagnosis_empty_file" in err
    payload = yaml.safe_load((tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text())
    assert payload["diagnosis"]["status"] == "escalated"


def test_close_verify_passes_a_paired_diagnosis(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path, verdicts_rows=[_missed_verdict()])
    diag_path = tmp_path / "runs" / "comfyui" / "trial-1" / "diagnoses.yaml"
    diag_path.write_text(yaml.safe_dump([_diagnosis_row()]), encoding="utf-8")

    code = cli.main(
        ["close-verify", setup, *_close_common(tmp_path)],
        runner_factory=_explode,
        # A present, valid verdict needs no assessment dispatcher at all.
        dispatch_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "present" in out
    payload = yaml.safe_load((tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text())
    assert payload["diagnosis"]["status"] == "present"
    assert payload["diagnosis"]["entries_written"] == 1


def test_close_verify_continues_past_an_identity_less_record(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    good_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    _write_trial(tmp_path, verdicts_rows=[_missed_verdict()])
    (good_dir / "diagnoses.yaml").write_text(
        yaml.safe_dump([_diagnosis_row()]), encoding="utf-8"
    )
    # A second trial in the same run directory with no version identity.
    bad_dir = tmp_path / "runs" / "comfyui" / "trial-2"
    bad_dir.mkdir(parents=True)
    (bad_dir / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "trial_id": "trial-2",
                "instance_id": "arm-a",
                "target_id": "comfyui",
                "project_id": "pid",
                "start_phase": "recon",
                "terminal": "complete",
                "phases": [],
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        ["close-verify", setup, *_close_common(tmp_path)],
        runner_factory=_explode,
        dispatch_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "identity" in captured.err.lower()
    # The identity-less record is escalated alone; the good trial still verifies.
    assert "trial-1: present" in captured.out
    payload = yaml.safe_load((good_dir / "trial.yaml").read_text())
    assert payload["assessment"]["status"] == "present"


def test_close_verify_continues_past_a_missing_ground_truth(
    tmp_path, capsys, monkeypatch
) -> None:
    setup_payload = {
        "schema_version": 1,
        "artifact_store": "/srv/a",
        "work_items": [{"name": "auth-bootstrap", "status": "complete"}],
        "instances": [
            {
                "instance_id": "arm-a",
                "targets": [
                    {
                        "target_id": "comfyui",
                        "target_config": {
                            "lifecycle": "targetctl",
                            "params": {"target": "comfyui"},
                        },
                    },
                    {
                        # An image target declares no ground-truth name.
                        "target_id": "no-gt",
                        "target_config": {
                            "lifecycle": "image",
                            "params": {"image": "nginx", "port": 18080},
                        },
                    },
                ],
            }
        ],
    }
    setup = _write_setup(tmp_path, setup_payload)
    good_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    _write_trial(tmp_path, verdicts_rows=[_missed_verdict()])
    (good_dir / "diagnoses.yaml").write_text(
        yaml.safe_dump([_diagnosis_row()]), encoding="utf-8"
    )
    # A second target's trial with identity but no resolvable ground truth.
    bad_dir = tmp_path / "runs" / "no-gt" / "trial-2"
    bad_dir.mkdir(parents=True)
    (bad_dir / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "trial_id": "trial-2",
                "instance_id": "arm-a",
                "target_id": "no-gt",
                "project_id": "pid",
                "start_phase": "recon",
                "terminal": "complete",
                "phases": [],
                "eval_sha": "eval-sha-1",
                "stack_fingerprint": "fp-1",
            }
        ),
        encoding="utf-8",
    )

    def fake_resolve(target: str) -> Path:
        if target == "comfyui":
            root = tmp_path / "gt" / "comfyui"
            root.mkdir(parents=True, exist_ok=True)
            return root
        raise assessment.AssessmentError(f"ground truth for {target!r} not found")

    monkeypatch.setattr(cli.assessment, "resolve_ground_truth", fake_resolve)

    code = cli.main(
        [
            "close-verify",
            setup,
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--command",
            "agent assess {prompt}",
            "--diagnose-command",
            "agent diagnose {prompt}",
        ],
        runner_factory=_explode,
        dispatch_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    captured = capsys.readouterr()
    assert code == 1
    # The no-ground-truth target is escalated alone; the other still verifies.
    assert "ground_truth" in captured.err.lower()
    assert "comfyui/trial-1: present" in captured.out


def test_issue_search_prints_read_only_matches(tmp_path, capsys) -> None:
    bank = FakeBank([diagnosis.Issue(repo="o/r", number=7, title="known gap")])

    code = cli.main(
        ["issue-search", "surface gap", "--repo", "o/r"],
        runner_factory=_explode,
        issue_bank_factory=lambda: bank,
    )

    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["closest_issue"]["number"] == 7
    assert payload["proposed_issue"] is None
    assert bank.queries == ["surface gap repo:o/r"]


def test_issue_search_honours_the_limit(tmp_path, capsys) -> None:
    bank = FakeBank([])

    code = cli.main(
        ["issue-search", "surface gap", "--repo", "o/r", "--limit", "2"],
        runner_factory=_explode,
        issue_bank_factory=lambda: bank,
    )

    assert code == 0
    assert bank.limits == [2]
