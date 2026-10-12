"""The recovery-state verbs: `alignment resolve` and the hold that blocks `trial`.

An unresolved hold marker refuses `trial` before any runner is constructed;
`alignment resolve` records the operator's decision and clears it.
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


def _explode():
    raise AssertionError("this path must never construct a runner")


def test_unresolved_hold_blocks_trial_until_resolved(tmp_path, capsys, recording_runner) -> None:
    setup_path = _write_setup(tmp_path)
    state_path = str(tmp_path / "alignment.yaml")
    state = alignment.AlignmentState(state_path)
    hold = state.add_hold(
        target_sha="eval-sha",
        target_fingerprint="fp-eval",
        rationale="no declared migration for db",
        now="2026-10-12T00:00:00Z",
    )
    runner = recording_runner()

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
    assert hold.hold_id in err
    assert "no declared migration for db" in err
    assert runner.calls == []

    resolved = cli.main(
        [
            "alignment",
            "resolve",
            setup_path,
            "--hold-id",
            hold.hold_id,
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
