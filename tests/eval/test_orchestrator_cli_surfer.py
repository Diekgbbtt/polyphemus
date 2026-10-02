"""The `surfer` CLI verb (#275).

`surfer --dry-run` asserts the state and prints it without dispatching the
decider or mutating anything; `surfer --once` performs exactly one
poll-assert-decide cycle. An escalation writes a hold through the same
mechanism `align` uses, so it blocks `trial` until `alignment resolve`.
"""
from __future__ import annotations

import argparse
from types import SimpleNamespace

import yaml

from advance.app_state import AppState
from orchestrator import alignment, cli, setup as setup_mod, surfer, trial


def _setup_payload() -> dict:
    return {
        "schema_version": 1,
        "artifact_store": "/srv/eval-artifacts",
        "work_items": [
            {"name": "auth-bootstrap", "status": "complete"},
            {"name": "l1-surface", "status": "complete"},
        ],
        "instances": [
            {
                "instance_id": "arm-a",
                "env_file": "arm-a/.env",
                "targets": [
                    {
                        "target_key": "webexploitbench/jetlinks",
                        "target_id": "jetlinks-1",
                    }
                ],
            }
        ],
    }


def _write_setup(tmp_path, payload: dict | None = None) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload or _setup_payload()), encoding="utf-8")
    return str(path)


class _Asserter:
    def __init__(self, state: surfer.SurfacedState) -> None:
        self.state = state

    def assert_state(self) -> surfer.SurfacedState:
        return self.state


class _Decider:
    def __init__(self, decision: surfer.SurferDecision) -> None:
        self.decision = decision
        self.calls = 0

    def decide(self, request):
        self.calls += 1
        return self.decision


class _ExplodingDecider:
    def decide(self, request):  # pragma: no cover - a dry-run never dispatches
        raise AssertionError("the decider must not be dispatched in dry-run")


class _ExplodingApi:
    def __call__(self, call):  # pragma: no cover - a dry-run performs no call
        raise AssertionError("dry-run must not call the API")


def _explode(*args, **kwargs):
    raise AssertionError("dry-run must not construct a runner")


def _failed_state() -> surfer.SurfacedState:
    return surfer.SurfacedState(
        idle=False,
        triggers=(
            surfer.Trigger(
                kind=surfer.FAILED_RUN,
                instance_id="arm-a",
                detail="hunting failed",
                target_id="jetlinks-1",
                project_id="pid",
                run_kind="hunting",
                run_id="h1",
                start_phase="hunting",
            ),
        ),
    )


def test_surfer_dry_run_asserts_and_never_dispatches_the_decider(tmp_path, capsys) -> None:
    setup_path = _write_setup(tmp_path)

    code = cli.main(
        [
            "surfer",
            setup_path,
            "--dry-run",
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
        ],
        runner_factory=_explode,
        api_factory=lambda base: _ExplodingApi(),
        surfer_asserter=_Asserter(_failed_state()),
        surfer_decider=_ExplodingDecider(),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "failed_run" in out
    assert "hunting failed" in out


def test_surfer_surfaces_a_corrupt_trial_record_on_stderr(
    tmp_path, capsys, monkeypatch
) -> None:
    # A corrupt record is named on stderr (the operator's channel) and never
    # crashes the cycle; the app-state read is stubbed so no network is touched.
    monkeypatch.setattr(
        cli, "_surfer_app_state", lambda args: (lambda: AppState(idle=True, projects=()))
    )
    setup_path = _write_setup(tmp_path)
    trial_dir = tmp_path / "runs" / "jetlinks-1" / "trial-1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "trial.yaml").write_text("trial_id: [unclosed\n", encoding="utf-8")

    code = cli.main(
        [
            "surfer",
            setup_path,
            "--dry-run",
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
        ],
        runner_factory=_explode,
    )

    err = capsys.readouterr().err
    assert code == 0
    assert "trial_record_invalid" in err
    assert "trial.yaml" in err


def test_surfer_once_terminate_stops_the_named_runs(tmp_path, capsys, recording_runner) -> None:
    setup_path = _write_setup(tmp_path)
    api_runner = _RecordingApi()
    runner = recording_runner()
    decider = _Decider(surfer.SurferDecision(surfer.TERMINATE, reason="budget"))

    code = cli.main(
        [
            "surfer",
            setup_path,
            "--once",
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--instances-root",
            str(tmp_path / "instances"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
        ],
        runner_factory=lambda: runner,
        api_factory=lambda base: api_runner,
        surfer_asserter=_Asserter(_failed_state()),
        surfer_decider=decider,
    )

    assert code == 0
    assert decider.calls == 1
    assert api_runner.paths == ["POST /projects/pid/hunting/h1/stop"]
    assert runner.calls == []


def test_surfer_escalation_blocks_trial_until_resolved(
    tmp_path, capsys, recording_runner
) -> None:
    setup_path = _write_setup(tmp_path)
    state_path = str(tmp_path / "alignment.yaml")
    decider = _Decider(
        surfer.SurferDecision(surfer.ESCALATE, reason="operator must top up credits")
    )
    runner = recording_runner()

    code = cli.main(
        [
            "surfer",
            setup_path,
            "--once",
            "--state",
            state_path,
            "--instances-root",
            str(tmp_path / "instances"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
        ],
        runner_factory=lambda: runner,
        surfer_asserter=_Asserter(_failed_state()),
        surfer_decider=decider,
    )
    # An escalation is deliberate but needs an operator: non-zero.
    assert code == 1
    hold_id = alignment.AlignmentState(state_path).unresolved_holds()[0].hold_id

    blocked = cli.main(
        [
            "trial",
            setup_path,
            "arm-a",
            "jetlinks-1",
            "--state",
            state_path,
            "--instances-root",
            str(tmp_path / "instances"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--data-root",
            str(tmp_path / "data"),
        ],
        runner_factory=_explode,
        api_factory=lambda base: _ExplodingApi(),
    )
    err = capsys.readouterr().err
    assert blocked == 1
    assert hold_id in err
    assert "operator must top up credits" in err

    resolved = cli.main(
        [
            "alignment",
            "resolve",
            setup_path,
            "--hold-id",
            hold_id,
            "--decision",
            "operator funded the account",
            "--state",
            state_path,
        ]
    )
    assert resolved == 0
    alignment.AlignmentState(state_path).require_no_holds()  # no longer raises


def test_surfer_cli_wires_the_run_error_evidence_reader(
    tmp_path, capsys, monkeypatch
) -> None:
    """I9: the CLI's surfer asserter reads run errors through the REST seam."""
    monkeypatch.setattr(
        cli, "_surfer_app_state", lambda args: (lambda: AppState(idle=True, projects=()))
    )
    setup_path = _write_setup(tmp_path)
    trial_dir = tmp_path / "runs" / "jetlinks-1" / "trial-1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "instance_id": "arm-a",
                "target_id": "jetlinks-1",
                "project_id": "pid",
                "terminal": "complete",
                "phases": [{"phase": "recon", "status": "complete", "run_id": "r1"}],
            }
        ),
        encoding="utf-8",
    )

    class FakeApi:
        def __call__(self, call):
            return {
                "per_job": [
                    {"job": "crawl", "status": "failed", "error": "insufficient_quota"}
                ]
            }

    monkeypatch.setattr(cli.api, "HttpApiRunner", lambda base: FakeApi())

    code = cli.main(
        [
            "surfer",
            setup_path,
            "--dry-run",
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
        ],
        runner_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "failure_signal" in out
    assert "insufficient_quota" in out


class _RecordingApi:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, call):
        self.calls.append(call)
        return {}

    @property
    def paths(self) -> list[str]:
        return [f"{c.method} {c.path}" for c in self.calls]


def test_resume_trial_threads_the_record_cap_baseline(tmp_path, monkeypatch) -> None:
    """The CLI resume builds a TrialConfig carrying the record's baseline."""
    setup = setup_mod.parse_eval_setup(_setup_payload())
    config = cli.OrchestratorConfig(
        repo=tmp_path / "repo", instances_root=tmp_path / "instances", branch="eval"
    )
    canned = trial.TrialConfig(
        instance_id="arm-a",
        target_id="jetlinks-1",
        start_phase="hunting",
        project_id="pid",
        data_root=tmp_path / "data",
        runs_root=tmp_path / "runs",
    )
    args = argparse.Namespace(
        runs_root=str(tmp_path / "runs"),
        budget_s=100.0,
        poll_s=10.0,
        eval_sha="sha",
        stack_fingerprint="fp",
        trace_id="t",
        repo=str(tmp_path / "repo"),
        api="http://api",
    )
    captured: dict = {}

    class _FakeTrial:
        def __init__(self, cfg, **kwargs) -> None:
            captured["cfg"] = cfg

        def run(self, **kwargs) -> object:
            return SimpleNamespace(trial_id="resumed-1")

    monkeypatch.setattr(cli, "_trial_config", lambda *a, **k: (canned, None, None))
    monkeypatch.setattr(cli.trial, "Trial", _FakeTrial)
    monkeypatch.setattr(
        cli.trial, "make_reachability_probe", lambda *a, **k: (lambda: True)
    )
    monkeypatch.setattr(
        cli, "Orchestrator", lambda *a, **k: SimpleNamespace(up=lambda: None)
    )
    plan = surfer.ResumePlan(
        instance_id="arm-a",
        target_id="jetlinks-1",
        project_id="pid",
        start_phase="hunting",
        intervention="surfer: resumed",
        cap_baseline=("old.yaml",),
    )

    trial_id = cli._resume_trial(
        args, setup, config, plan, tmp_path / "data",
        lambda: object(), lambda base: object(),
    )

    assert trial_id == "resumed-1"
    assert captured["cfg"].cap_baseline == ("old.yaml",)
    assert captured["cfg"].start_phase == "hunting"
