"""The `store render-sync` and `store materialize` CLI verbs (#273).

`--dry-run` prints the plan and executes nothing (writes no config, unit, or
trial tree), provable because the output directories stay empty.
"""
from __future__ import annotations

import yaml

from orchestrator import cli

EVAL_SHA = "eval-sha-1"
FP = "fp-1"


def _setup_payload(store_dir: str) -> dict:
    return {
        "schema_version": 1,
        "artifact_store": store_dir,
        "work_items": [{"name": "auth-bootstrap", "status": "complete"}],
        "instances": [
            {
                "instance_id": "arm-a",
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


def _write_setup(tmp_path, store_dir) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(_setup_payload(str(store_dir))), encoding="utf-8")
    return str(path)


def _make_data_root(root):
    (root / "pid/hunting/orchestration/hunt_configs/consumed").mkdir(parents=True)
    (root / "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml").write_text(
        "config: cfg\n", encoding="utf-8"
    )
    (root / "pid/hunting/hunter/test-specs/fault-a").mkdir(parents=True)
    (root / "pid/hunting/hunter/test-specs/fault-a/spec.yaml").write_text(
        "spec: a\n", encoding="utf-8"
    )
    (root / "pid/hunting/test-executor-pod/spec-1/experiment-log").mkdir(parents=True)
    (root / "pid/hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml").write_text(
        "order: 0\n", encoding="utf-8"
    )
    (root / "pid/hunting/test-executor-pod/spec-1/export.yaml").write_text(
        "export: 1\n", encoding="utf-8"
    )


def _make_trial(tmp_path, data_root) -> str:
    trial_dir = tmp_path / "runs" / "jetlinks-1" / "trial-1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "verdicts.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "vuln_id": "v1",
                    "identified": "identified",
                    "confidence": 0.9,
                    "matched": {"unit": "u", "fault_class": "fc", "symptom": "s"},
                    "evidence_chain": {
                        "hunt_config": "pid/hunting/orchestration/hunt_configs/consumed/cfg.yaml",
                        "spec_dir": "pid/hunting/hunter/test-specs/fault-a",
                        "experiment_logs": [
                            "pid/hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml"
                        ],
                        "pod_export": "pid/hunting/test-executor-pod/spec-1/export.yaml",
                    },
                    "eval_sha": EVAL_SHA,
                    "stack_fingerprint": FP,
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (trial_dir / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "trial_id": "trial-1",
                "instance_id": "arm-a",
                "target_id": "jetlinks-1",
                "project_id": "pid",
                "start_phase": "recon",
                "terminal": "complete",
                "phases": [],
                "started_at": "t",
                "finished_at": "t",
                "eval_sha": EVAL_SHA,
                "stack_fingerprint": FP,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return str(trial_dir)


def test_render_sync_dry_run_prints_and_writes_nothing(tmp_path, capsys) -> None:
    store_dir = tmp_path / "store"
    setup = _write_setup(tmp_path, store_dir)

    code = cli.main(
        [
            "store",
            "render-sync",
            setup,
            "--instances-root",
            str(tmp_path / "instances"),
            "--out",
            str(store_dir / "_sync"),
            "--dry-run",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert not (store_dir / "_sync").exists()
    assert "eval-store-arm-a.conf" in out
    assert "eval-store-arm-a.service" in out


def test_render_sync_writes_the_config_and_unit(tmp_path) -> None:
    store_dir = tmp_path / "store"
    setup = _write_setup(tmp_path, store_dir)

    code = cli.main(
        [
            "store",
            "render-sync",
            setup,
            "--instances-root",
            str(tmp_path / "instances"),
            "--out",
            str(store_dir / "_sync"),
        ]
    )

    assert code == 0
    assert (store_dir / "_sync" / "eval-store-arm-a.conf").exists()
    assert (store_dir / "_sync" / "eval-store-arm-a.service").exists()


def test_materialize_dry_run_prints_and_writes_nothing(tmp_path, capsys) -> None:
    store_dir = tmp_path / "store"
    setup = _write_setup(tmp_path, store_dir)
    data_root = tmp_path / "instances" / "arm-a" / "data"
    _make_data_root(data_root)
    trial_dir = _make_trial(tmp_path, data_root)

    code = cli.main(
        [
            "store",
            "materialize",
            setup,
            "--instances-root",
            str(tmp_path / "instances"),
            "--trial",
            trial_dir,
            "--dry-run",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "trial-1" in out
    assert "run-manifest.yaml" in out
    assert not (store_dir / "jetlinks-1").exists()


def test_materialize_writes_the_trial_tree(tmp_path) -> None:
    store_dir = tmp_path / "store"
    setup = _write_setup(tmp_path, store_dir)
    data_root = tmp_path / "instances" / "arm-a" / "data"
    _make_data_root(data_root)
    trial_dir = _make_trial(tmp_path, data_root)

    code = cli.main(
        [
            "store",
            "materialize",
            setup,
            "--instances-root",
            str(tmp_path / "instances"),
            "--trial",
            trial_dir,
        ]
    )

    assert code == 0
    dest = store_dir / "jetlinks-1" / "arm-a" / "trial-1"
    assert (dest / "run-manifest.yaml").exists()
    assert (dest / "verdicts.yaml").exists()
