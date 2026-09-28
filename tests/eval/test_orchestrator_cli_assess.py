"""The `assess` and `close-verify` CLI verbs (#271).

`--dry-run` prints the dispatch/verification plan and executes nothing; the
dispatcher factory is a parameter so a test can prove it.
"""
from __future__ import annotations

import yaml

from orchestrator import assessment, cli


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


def _write_trial(tmp_path, *, trace_id=None) -> str:
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
    return str(trial_dir)


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


def test_assess_dry_run_prints_the_request_and_dispatches_nothing(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    trial_dir = _write_trial(tmp_path)

    code = cli.main(
        [
            "assess",
            setup,
            "--trial",
            trial_dir,
            "--ground-truth",
            str(tmp_path / "gt" / "comfyui"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--command",
            "agent assess {prompt} {trial_record} {ground_truth} {destination}",
            "--dry-run",
        ],
        runner_factory=_explode,
        dispatch_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "assessment.md" in out
    assert str(tmp_path / "gt" / "comfyui") in out
    assert "verdicts.yaml" in out


def test_assess_dispatches_through_the_injected_dispatcher(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    trial_dir = _write_trial(tmp_path)
    fake = FakeDispatcher()

    code = cli.main(
        [
            "assess",
            setup,
            "--trial",
            trial_dir,
            "--ground-truth",
            str(tmp_path / "gt" / "comfyui"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--command",
            "agent assess {prompt}",
        ],
        runner_factory=_explode,
        dispatch_factory=lambda _argv: fake,
    )

    assert code == 0
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request.trial_record == tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml"
    assert request.destination == tmp_path / "runs" / "comfyui" / "trial-1" / "verdicts.yaml"
    assert request.data_root == tmp_path / "data"
    # The dispatch attempt is persisted in the trial record (fire-and-forget).
    payload = yaml.safe_load((tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text())
    assert payload["assessment"]["status"] == "dispatched"


def test_assess_request_carries_the_trial_trace_id(tmp_path) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    trial_dir = _write_trial(tmp_path, trace_id="trace-9")
    fake = FakeDispatcher()

    code = cli.main(
        [
            "assess",
            setup,
            "--trial",
            trial_dir,
            "--ground-truth",
            str(tmp_path / "gt" / "comfyui"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--command",
            "agent assess {prompt} {trace_id}",
        ],
        runner_factory=_explode,
        dispatch_factory=lambda _argv: fake,
    )

    assert code == 0
    assert fake.requests[0].trace_id == "trace-9"


def test_close_verify_dry_run_lists_the_trials_and_executes_nothing(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)

    code = cli.main(
        [
            "close-verify",
            setup,
            "--ground-truth",
            str(tmp_path / "gt" / "comfyui"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--command",
            "agent assess {prompt}",
            "--dry-run",
        ],
        runner_factory=_explode,
        dispatch_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "trial-1" in out
    assert "verdicts.yaml" in out


def test_close_verify_escalates_a_missing_verdict_and_exits_nonzero(tmp_path, capsys) -> None:
    setup = _write_setup(tmp_path, _setup_payload())
    _write_trial(tmp_path)
    fake = FakeDispatcher()  # never produces a verdict

    code = cli.main(
        [
            "close-verify",
            setup,
            "--ground-truth",
            str(tmp_path / "gt" / "comfyui"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--command",
            "agent assess {prompt}",
        ],
        runner_factory=_explode,
        dispatch_factory=lambda _argv: fake,
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "assessment_empty_file" in err
    payload = yaml.safe_load((tmp_path / "runs" / "comfyui" / "trial-1" / "trial.yaml").read_text())
    assert payload["assessment"]["status"] == "escalated"
