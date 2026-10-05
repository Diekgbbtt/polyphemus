"""Test setup for the eval harness modules.

`eval/` is a flat directory of scripts with no package `__init__`; the newer
`eval/advance/` package is imported by putting `eval/` on `sys.path`, so the
tests load it the same way the daemon's entry point does.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))


class FakeResult:
    """Duck-typed `CommandResult`; the fake runner imports nothing at module load."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    """Records every `Command` and answers reads by an argv substring match.

    `routes` is an ordered mapping `needle -> FakeResult`: the first needle
    contained in the joined argv wins, else `default`. This is enough to model
    read commands (targetctl output, `curl` status codes, `getent hosts`) while
    asserting the emitted command sequence.
    """

    def __init__(self, routes: dict | None = None, default: FakeResult | None = None):
        self.routes = routes or {}
        self.default = default or FakeResult()
        self.calls: list = []

    def __call__(self, command):
        self.calls.append(command)
        argv = " ".join(command.argv)
        for needle, result in self.routes.items():
            if needle in argv:
                return result
        return self.default

    @property
    def argv_texts(self) -> list[str]:
        return [" ".join(c.argv) for c in self.calls]


@pytest.fixture
def recording_runner():
    """Return the class so a test can build a runner with its own routes."""
    return RecordingRunner


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Never sleep for real in the eval tier: a readiness poll must not hang a test."""
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)


@pytest.fixture
def fake_result():
    """Return the result class so a test can build read responses."""
    return FakeResult


def sample_setup_dict() -> dict:
    """A minimal valid `EvalSetup`: one instance, one keyed `targetctl` target.

    The target is addressed by `<dataset>/<target>` (spec #301); the bring-up
    configuration lives in `eval/targets/<dataset>/<target>.yaml`, while the
    inline `target_config` carries only the per-trial data dependencies.
    """
    return {
        "schema_version": 1,
        "artifact_store": "/srv/eval-artifacts",
        "datasets": ["webexploitbench"],
        "work_items": [
            {"name": "auth-bootstrap", "status": "complete"},
            {"name": "l1-surface", "status": "complete"},
        ],
        "instances": [
            {
                "instance_id": "arm-a",
                "env_file": "arm-a/.env",
                "systems": "ph-arm-a",
                "targets": [
                    {
                        "target_key": "webexploitbench/jetlinks",
                        "target_id": "jetlinks-1",
                        "start_phase": "recon",
                        "token_budget": 10,
                        "preloaded_hunting_artifacts": None,
                        "target_config": {
                            "operator_kb": "eval/data/webexploitbench/jetlinks/operator_kb.md",
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture
def sample_setup():
    import copy

    return copy.deepcopy(sample_setup_dict())
