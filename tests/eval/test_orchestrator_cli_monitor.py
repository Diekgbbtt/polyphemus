"""The `monitor` CLI verb (#289) - one tick of the post-execution control plane.

One sweep verifies each trial's execution state and advances one workflow node:
a successful execution dispatches the assessment subagent, a present
`verdicts.yaml` dispatches the diagnoser for its `missed`/`partial` verdicts,
and a present, paired `diagnoses.yaml` completes the trial. A failed execution
is deferred (the surfer owns recovery) and never assessed. The dispatcher
factories are parameters so a test can prove dry-run dispatches nothing.
"""
from __future__ import annotations

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
                    {
                        "target_key": f"webexploitbench/{target}",
                        "target_id": target,
                    }
                ],
            }
        ],
    }


def _write_setup(tmp_path, payload) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def _write_trial(tmp_path, *, terminal: str = "complete", assessment=None, diagnosis=None) -> str:
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
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
    return str(trial_dir)


def _write_verdicts(tmp_path, *, identified: str = "missed") -> None:
    path = tmp_path / "runs" / "comfyui" / "trial-1" / "verdicts.yaml"
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


class FakeDispatcher:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)


def _explode(*_args, **_kwargs):
    raise AssertionError("must not construct a dispatcher")


def _diag_argv() -> list[str]:
    return [
        "--command",
        "agent assess {prompt} {destination}",
        "--diagnose-command",
        "agent diagnose {prompt} {destination} {vulns}",
    ]


def _base_args(tmp_path, setup, *extra, with_commands: bool = True) -> list[str]:
    args = [
        "monitor",
        setup,
        "--ground-truth",
        str(tmp_path / "gt" / "comfyui"),
        "--data-root",
        str(tmp_path / "data"),
        "--runs-root",
        str(tmp_path / "runs"),
    ]
    if with_commands:
        args += _diag_argv()
    return args + list(extra)


def test_monitor_dry_run_lists_trials_and_constructs_no_dispatcher(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    code = cli.main(
        _base_args(tmp_path, setup, "--dry-run"),
        runner_factory=_explode,
        dispatch_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "trial-1" in out
    assert "assessment_dispatched" in out


def test_monitor_dispatches_assessment_for_a_successful_trial(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)
    fake = FakeDispatcher()

    code = cli.main(
        _base_args(tmp_path, setup),
        runner_factory=_explode,
        dispatch_factory=lambda _argv: fake,
        diagnose_dispatch_factory=_explode,
    )

    assert code == 0
    assert len(fake.requests) == 1
    payload = yaml.safe_load(
        (tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text()
    )
    assert payload["assessment"]["status"] == "dispatched"


def test_monitor_defers_a_failed_execution(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path, terminal="failed")
    fake = FakeDispatcher()

    code = cli.main(
        _base_args(tmp_path, setup),
        runner_factory=_explode,
        dispatch_factory=lambda _argv: fake,
        diagnose_dispatch_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "deferred" in out
    assert fake.requests == []


def test_monitor_awaits_a_recent_dispatch_instead_of_resent(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)
    fake = FakeDispatcher()

    args = _base_args(tmp_path, setup)
    cli.main(
        args,
        runner_factory=_explode,
        dispatch_factory=lambda _argv: fake,
        diagnose_dispatch_factory=_explode,
    )
    code = cli.main(
        args,
        runner_factory=_explode,
        dispatch_factory=lambda _argv: fake,
        diagnose_dispatch_factory=_explode,
    )

    assert code == 0
    assert len(fake.requests) == 1  # the second tick awaits, never re-dispatches


def test_monitor_dispatches_diagnosis_once_verdicts_are_present(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path, assessment={"status": "present", "attempts": []})
    _write_verdicts(tmp_path, identified="missed")
    assess = FakeDispatcher()
    diagnose = FakeDispatcher()

    code = cli.main(
        _base_args(tmp_path, setup),
        runner_factory=_explode,
        dispatch_factory=lambda _argv: assess,
        diagnose_dispatch_factory=lambda _argv: diagnose,
    )

    assert code == 0
    assert assess.requests == []
    assert len(diagnose.requests) == 1
    assert diagnose.requests[0].vulns == ("comfyui-001",)
    payload = yaml.safe_load(
        (tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text()
    )
    assert payload["diagnosis"]["status"] == "dispatched"


def test_monitor_records_a_raised_dispatch_as_an_error_attempt(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    class Boom:
        def __call__(self, request):
            raise RuntimeError("agent command failed")

    code = cli.main(
        _base_args(tmp_path, setup),
        runner_factory=_explode,
        dispatch_factory=lambda _argv: Boom(),
        diagnose_dispatch_factory=_explode,
    )

    assert code == 0
    payload = yaml.safe_load(
        (tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text()
    )
    assert payload["assessment"]["status"] == "dispatched"
    assert payload["assessment"]["attempts"][-1]["outcome"] == "error"


def test_monitor_escalates_dispatcher_process_after_the_bound(tmp_path, capsys) -> None:
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

    code = cli.main(
        _base_args(tmp_path, setup),
        runner_factory=_explode,
        dispatch_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "assessment_dispatcher_process" in err
    payload = yaml.safe_load(
        (tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text()
    )
    assert payload["assessment"]["failure"] == "assessment_dispatcher_process"


def test_monitor_does_not_clobber_an_existing_escalation(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    old = "2026-01-01T00:00:00+00:00"
    _write_trial(
        tmp_path,
        assessment={
            "status": "escalated",
            "failure": "assessment_empty_file",
            "attempts": [{"attempt": 1, "outcome": "dispatched", "at": old}],
        },
    )

    code = cli.main(
        _base_args(tmp_path, setup),
        runner_factory=_explode,
        dispatch_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    assert code == 1
    payload = yaml.safe_load(
        (tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text()
    )
    assert payload["assessment"]["failure"] == "assessment_empty_file"


def test_monitor_escalates_assessment_no_command(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    code = cli.main(
        _base_args(tmp_path, setup, with_commands=False),
        runner_factory=_explode,
        dispatch_factory=_explode,
        diagnose_dispatch_factory=_explode,
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "assessment_no_command" in err
    payload = yaml.safe_load(
        (tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text()
    )
    assert payload["assessment"]["status"] == "escalated"
