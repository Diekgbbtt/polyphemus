"""The `align` and `alignment resolve` CLI verbs (#274).

`align --dry-run` prints the planned alignment commands and constructs no
runner; an escalation writes a hold marker that blocks `trial` until
`alignment resolve` records the operator's decision.
"""
from __future__ import annotations

import yaml

from orchestrator import alignment, cli


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
                        "target_id": "jetlinks-1",
                        "target_config": {
                            "lifecycle": "targetctl",
                            "params": {"target": "jetlinks"},
                        },
                    }
                ],
            }
        ],
    }


def _write_setup(tmp_path, payload: dict | None = None) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload or _setup_payload()), encoding="utf-8")
    return str(path)


def _decision_input(changed: list[dict]) -> dict:
    return {
        "dev_sha": "dev-sha",
        "eval_sha": "eval-sha",
        "all_idle": True,
        "delta": {
            "changed": changed,
            "unchanged": [],
            "images_changed": [],
            "images_unchanged": [],
        },
        "fingerprints": {"dev": "fp-dev", "eval": "fp-eval"},
    }


def _write_input(tmp_path, changed: list[dict]) -> str:
    path = tmp_path / "decision.yaml"
    path.write_text(yaml.safe_dump(_decision_input(changed)), encoding="utf-8")
    return str(path)


class _FakeDecider:
    def __init__(self, decision: alignment.AlignmentDecision) -> None:
        self.decision = decision

    def decide(self, request):
        return self.decision


def _explode():
    raise AssertionError("this path must never construct a runner")


def test_align_dry_run_plans_and_constructs_no_runner(tmp_path, capsys) -> None:
    setup_path = _write_setup(tmp_path)
    input_path = _write_input(tmp_path, [{"name": "kali", "artifact_class": "exec_plane"}])
    decider = _FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="restart", component="kali"),)
        )
    )

    code = cli.main(
        [
            "align",
            setup_path,
            "--decision-file",
            input_path,
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--dry-run",
        ],
        runner_factory=_explode,
        alignment_decider=decider,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "docker restart" in out


def test_align_distinguishes_no_change_from_decided_no_action(
    tmp_path, capsys
) -> None:
    """M1: a true no-op and a decider-chosen no-action read differently."""
    setup_path = _write_setup(tmp_path)
    decider = _FakeDecider(alignment.AlignmentDecision(actions=()))

    # A real delta the decider judged a no-op.
    input_path = _write_input(tmp_path, [{"name": "kali", "artifact_class": "exec_plane"}])
    code = cli.main(
        [
            "align",
            setup_path,
            "--decision-file",
            input_path,
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--dry-run",
        ],
        runner_factory=_explode,
        alignment_decider=decider,
    )
    decided = capsys.readouterr().out

    # Nothing moved at all.
    empty_path = _write_input(tmp_path, [])
    code_empty = cli.main(
        [
            "align",
            setup_path,
            "--decision-file",
            empty_path,
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--dry-run",
        ],
        runner_factory=_explode,
        alignment_decider=decider,
    )
    unchanged = capsys.readouterr().out

    assert code == 0 and code_empty == 0
    assert "no change" in unchanged.lower()
    assert "decided no action" in decided.lower()
    assert "no change; nothing to align" not in decided.lower()


def test_align_reports_a_bad_command_template_as_a_handled_error(
    tmp_path, capsys, recording_runner
) -> None:
    """M5: a literal `{...}` in the operator command is handled, not a traceback."""
    setup_path = _write_setup(tmp_path)
    input_path = _write_input(tmp_path, [{"name": "kali", "artifact_class": "exec_plane"}])
    runner = recording_runner()

    code = cli.main(
        [
            "align",
            setup_path,
            "--decision-file",
            input_path,
            "--state",
            str(tmp_path / "alignment.yaml"),
            "--command",
            "python3 agent.py {bogus}",
        ],
        runner_factory=lambda: runner,
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "invalid placeholder" in err
    assert "Traceback" not in err


def test_align_escalation_blocks_trial_until_resolved(tmp_path, capsys, recording_runner) -> None:
    setup_path = _write_setup(tmp_path)
    input_path = _write_input(tmp_path, [{"name": "db", "artifact_class": "schema_data_layout"}])
    state_path = str(tmp_path / "alignment.yaml")
    decider = _FakeDecider(
        alignment.AlignmentDecision(actions=(), escalation="no declared migration for db")
    )
    runner = recording_runner()

    code = cli.main(
        [
            "align",
            setup_path,
            "--decision-file",
            input_path,
            "--state",
            state_path,
        ],
        runner_factory=lambda: runner,
        alignment_decider=decider,
    )
    # An escalation is a deliberate outcome, but it needs an operator: non-zero.
    assert code == 1
    assert runner.calls == []
    hold_id = alignment.AlignmentState(state_path).unresolved_holds()[0].hold_id

    # The unresolved hold refuses the trial before any runner is constructed.
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
        api_factory=_explode,
    )
    err = capsys.readouterr().err
    assert blocked == 1
    assert hold_id in err
    assert "no declared migration for db" in err

    resolved = cli.main(
        [
            "alignment",
            "resolve",
            setup_path,
            "--hold-id",
            hold_id,
            "--decision",
            "operator ran the migration by hand",
            "--state",
            state_path,
        ]
    )
    assert resolved == 0
    state = alignment.AlignmentState(state_path)
    state.require_no_holds()  # no longer raises
    assert state.holds()[0].decision == "operator ran the migration by hand"
