"""The `next-target` CLI verb - the tool the orchestrator agent calls per target.

The verb wraps `Chain.next_target`: it reclaims the previous target's image,
pulls (or builds) the next, brings it up, and prints the step as JSON; on
failure it prints the inspectable trace and exits non-zero. These predicates
drive the verb with a recording runner, so the whole chain step runs against
canned command output with no host.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from orchestrator import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "arm-a"
TARGET = "jetlinks-1"


def _setup_file(tmp_path, sample_setup) -> Path:
    # Give the target an image identifier and a Dockerfile, so the chain builds
    # the app image (the Dockerfile overwrites the pull path).
    target = sample_setup["instances"][0]["targets"][0]
    target["images"] = ["pentestbench-jetlinks:2.3.0-synthetic"]
    target["target_config"]["dockerfile"] = "setup_files/environment/Dockerfile"
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(sample_setup), encoding="utf-8")
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


def test_next_target_reports_the_step(tmp_path, sample_setup, recording_runner, fake_result):
    runner = recording_runner(
        {
            "targetctl up": fake_result(0, stdout="UI: http://127.0.0.1:4321"),
            "getent hosts": fake_result(0, stdout="172.17.0.1 host.docker.internal\n"),
            "curl": fake_result(0, stdout="200"),
            "docker build": fake_result(0),
            "image inspect": fake_result(0, stdout="sha256:built"),
        },
        default=fake_result(0, stdout="running"),
    )
    out = _StringIO()
    err = _StringIO()

    code = cli.main(
        _argv(_setup_file(tmp_path, sample_setup), tmp_path),
        runner_factory=lambda: runner,
        stdout=out,
        stderr=err,
    )

    assert code == 0, err.getvalue()
    report = json.loads(out.getvalue())
    assert report["target_id"] == TARGET
    assert report["images"] == ["pentestbench-jetlinks:2.3.0-synthetic"]
    assert report["pulled"] == [
        "targetctl build jetlinks",
        "build pentestbench-jetlinks:2.3.0-synthetic from "
        "setup_files/environment/Dockerfile",
    ]
    assert report["health"].strip() == "running"


def test_next_target_unknown_target_reports_the_trace(tmp_path, sample_setup, recording_runner):
    out = _StringIO()
    err = _StringIO()

    code = cli.main(
        _argv(_setup_file(tmp_path, sample_setup), tmp_path, target="nope"),
        runner_factory=lambda: recording_runner({}),
        stdout=out,
        stderr=err,
    )

    assert code == 1
    report = json.loads(err.getvalue())
    assert "unknown target" in report["error"]
    assert report["traceback"]


class _StringIO:
    """A tiny stdout/stderr sink (avoids importing io in the test body)."""

    def __init__(self) -> None:
        self._parts: list[str] = []

    def write(self, text: str) -> int:
        self._parts.append(text)
        return len(text)

    def getvalue(self) -> str:
        return "".join(self._parts)
