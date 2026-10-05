"""The `next-target` CLI verb - the tool the orchestrator agent calls per target.

The verb wraps `Chain.next_target`: it reclaims the previous target's images,
provisions the next from the dataset helper, brings it up, and prints the step
as JSON; on failure it prints the inspectable trace and exits non-zero. Under
spec #301 the target is addressed by its `<dataset>/<target>` key, so these
predicates drive the verb against the repo-local `mock` dataset with a recording
runner: the whole chain step runs against canned command output with no host.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from orchestrator import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "arm-a"
TARGET = "webmock-1"
# The mock compose builds exactly one service (`web`), so the helper derives one
# canonical tag from the target's docker-compose.cage.yml.
CANONICAL_IMAGE = "ph/mock/webmock:web"


def _setup_file(tmp_path) -> Path:
    payload = {
        "schema_version": 1,
        "artifact_store": "/srv/eval-artifacts",
        "datasets": ["mock"],
        "instances": [
            {
                "instance_id": INSTANCE,
                "targets": [
                    {"target_key": "mock/webmock", "target_id": TARGET},
                ],
            }
        ],
    }
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _argv(setup_path, tmp_path, target=TARGET) -> list[str]:
    return [
        "next-target",
        str(setup_path),
        "--instance",
        INSTANCE,
        "--target",
        target,
        "--repo",
        str(REPO_ROOT),
        "--instances-root",
        str(tmp_path / "instances"),
        "--state",
        str(tmp_path / "alignment.yaml"),
        "--chain-state",
        str(tmp_path / "chain-state.yaml"),
    ]


def test_next_target_reports_the_step(tmp_path, recording_runner, fake_result):
    runner = recording_runner(
        {
            "targetctl up": fake_result(0, stdout="UI: http://127.0.0.1:4321"),
            "getent hosts": fake_result(0, stdout="172.17.0.1 host.docker.internal\n"),
            "curl": fake_result(0, stdout="200"),
            "docker build": fake_result(0),
            "image inspect": fake_result(0, stdout="sha256:built"),
            "ps -a --format json": fake_result(
                0, stdout='{"Service": "web", "Health": "healthy"}'
            ),
        },
        default=fake_result(0, stdout="running"),
    )
    out = _StringIO()
    err = _StringIO()

    code = cli.main(
        _argv(_setup_file(tmp_path), tmp_path),
        runner_factory=lambda: runner,
        stdout=out,
        stderr=err,
    )

    assert code == 0, err.getvalue()
    report = json.loads(out.getvalue())
    assert report["target_id"] == TARGET
    # The image set is derived from the mock compose, not hand-listed in the setup.
    assert report["images"] == [CANONICAL_IMAGE]
    assert isinstance(report["pulled"], list)
    assert report["host"]
    assert report["front_url"]
    # The mock `web` service declares no healthcheck, so the default plan is the
    # composite front answer + stack health.
    assert report["health"] == "composite ready"


def test_next_target_unknown_target_reports_the_trace(tmp_path, recording_runner):
    out = _StringIO()
    err = _StringIO()

    code = cli.main(
        _argv(_setup_file(tmp_path), tmp_path, target="nope"),
        runner_factory=lambda: recording_runner({}),
        stdout=out,
        stderr=err,
    )

    assert code == 1
    report = json.loads(err.getvalue())
    assert "unknown target" in report["error"]
    assert report["traceback"]


def test_next_target_rejects_an_unlisted_dataset(tmp_path, sample_setup) -> None:
    """A key naming a dataset the setup never lists fails loud, not silently."""
    sample_setup["datasets"] = []
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(sample_setup), encoding="utf-8")
    out = _StringIO()
    err = _StringIO()

    code = cli.main(
        [
            "next-target",
            str(path),
            "--instance",
            "arm-a",
            "--target",
            "jetlinks-1",
            "--repo",
            str(REPO_ROOT),
            "--instances-root",
            str(tmp_path / "instances"),
            "--chain-state",
            str(tmp_path / "chain-state.yaml"),
        ],
        runner_factory=lambda: _RecordingRunner(),
        stdout=out,
        stderr=err,
    )

    assert code == 1
    assert "does not list" in err.getvalue()


class _RecordingRunner:
    def __call__(self, command):
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()


class _StringIO:
    """A tiny stdout/stderr sink (avoids importing io in the test body)."""

    def __init__(self) -> None:
        self._parts: list[str] = []

    def write(self, text: str) -> int:
        self._parts.append(text)
        return len(text)

    def getvalue(self) -> str:
        return "".join(self._parts)
