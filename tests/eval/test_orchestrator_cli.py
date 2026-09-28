"""The `python -m orchestrator` CLI (ticket #269).

`plan` and `--dry-run` print every command and never construct a runner;
`up`/`down`/`status` inject the thin local runner. The runner factory is a
parameter so a test can prove plan mode executes nothing.
"""
from __future__ import annotations

import yaml

from orchestrator import cli


def _write_setup(tmp_path, payload) -> str:
    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def _explode():
    raise AssertionError("plan mode must never construct a runner")


class _SpyFactory:
    def __init__(self, runner):
        self.runner = runner
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.runner


def test_plan_emits_commands_and_executes_nothing(
    sample_setup, tmp_path, capsys
) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(["plan", setup_path], runner_factory=_explode)

    out = capsys.readouterr().out
    assert code == 0
    assert "worktree add" in out
    assert "scripts/targetctl up jetlinks" in out
    assert "env_preflight.py" in out


def test_up_dry_run_emits_commands_and_executes_nothing(
    sample_setup, tmp_path, capsys
) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(["up", setup_path, "--dry-run"], runner_factory=_explode)

    out = capsys.readouterr().out
    assert code == 0
    assert "scripts/targetctl up jetlinks" in out


def test_up_executes_through_the_injected_runner(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "hostname -I": fake_result(0, "10.0.0.5 \n"),
            "curl": fake_result(0, "200"),
        }
    )
    factory = _SpyFactory(runner)

    code = cli.main(["up", setup_path], runner_factory=factory)

    assert code == 0
    assert factory.calls >= 1
    assert any("scripts/targetctl up jetlinks" in t for t in runner.argv_texts)


def test_down_executes_teardown(sample_setup, tmp_path, recording_runner) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner()

    code = cli.main(["down", setup_path], runner_factory=_SpyFactory(runner))

    assert code == 0
    assert any("down -v --remove-orphans" in t for t in runner.argv_texts)


def test_gate_refusal_exits_nonzero_and_names_the_item(
    sample_setup, tmp_path, recording_runner, capsys
) -> None:
    sample_setup["work_items"][0]["status"] = "incomplete"
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(["up", setup_path], runner_factory=_SpyFactory(recording_runner()))

    err = capsys.readouterr().err
    assert code != 0
    assert "auth-bootstrap" in err
