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
    # Teardown follows a bring-up that created the worktree; an absent worktree
    # skips the compose-down (idempotent teardown, #269).
    (tmp_path / "instances" / "arm-a").mkdir(parents=True)

    code = cli.main(
        ["down", setup_path, "--instances-root", str(tmp_path / "instances")],
        runner_factory=_SpyFactory(runner),
    )

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


def test_status_prints_front_urls_and_kali_aliases(
    sample_setup, tmp_path, recording_runner, fake_result, capsys
) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "/etc/hosts": fake_result(
                0, stdout="127.0.0.1 localhost\n10.0.0.5 t-aaaa.target\n"
            ),
        },
        default=fake_result(0, stdout="running\n"),
    )

    code = cli.main(["status", setup_path], runner_factory=_SpyFactory(runner))

    out = capsys.readouterr().out
    assert code == 0
    assert "http://t-" in out
    assert "t-aaaa.target" in out


# --- the trial verb (#270) ----------------------------------------------------


class _FakeApi:
    """A minimal recording `ApiRunner` for the CLI wiring test."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, call):
        self.calls.append(call)
        key = f"{call.method} {call.path}"
        for needle, resp in self.routes.items():
            if needle in key:
                return resp
        raise AssertionError(f"unexpected API call {key}")


def _trial_routes() -> dict:
    graph = {"nodes": [{"type": "L1Service"}, {"type": "Endpoint"}], "links": []}
    return {
        "GET /projects/pid/recon/r1": {
            "status": "complete",
            "per_job": [{"job": "crawl", "status": "complete"}],
            "stats": {"analysis_drained": True},
        },
        "GET /projects/pid/hunting/h1": {"status": "complete"},
        "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
        "POST /projects/pid/recon": {"run_id": "r1"},
        "GET /projects/pid/graph": graph,
        "PUT /projects/pid/settings": {"ok": True},
        "POST /projects": {"project_id": "pid"},
        "GET /projects": {"projects": [{"project_id": "pid"}]},
    }


def test_trial_dry_run_prints_and_executes_nothing(sample_setup, tmp_path, capsys) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(
        ["trial", setup_path, "arm-a", "jetlinks-1", "--dry-run"],
        runner_factory=_explode,
        api_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "POST /projects" in out
    assert "scaffold.py" in out
    assert "poll" in out.lower()


def test_trial_executes_through_the_injected_api_and_runner(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "hostname -I": fake_result(0, "10.0.0.5 \n"),
            "scaffold.py": fake_result(0, "services: 3\n"),
            "curl": fake_result(0, "200"),
        }
    )
    api = _FakeApi(_trial_routes())

    code = cli.main(
        [
            "trial",
            setup_path,
            "arm-a",
            "jetlinks-1",
            "--instances-root",
            str(tmp_path / "instances"),
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
        ],
        runner_factory=lambda: runner,
        api_factory=lambda base: api,
    )

    assert code == 0
    assert any(c.path == "/projects/pid/recon" for c in api.calls)
    assert any("scripts/targetctl up jetlinks" in t for t in runner.argv_texts)
