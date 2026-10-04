"""The `python -m orchestrator` CLI (ticket #269).

`plan` and `--dry-run` print every command and never construct a runner;
`up`/`down`/`status` inject the thin local runner. The runner factory is a
parameter so a test can prove plan mode executes nothing.
"""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import yaml

from orchestrator import api, cli


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
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "curl": fake_result(0, "200"),
            "ps -a --format json": fake_result(
                0, '{"Service": "app", "Health": "healthy"}'
            ),
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
        # The L1 surface is placed through the multipart endpoint, not scaffold.py.
        "POST /projects/pid/data-dependencies/l1": {
            "ok": True, "services_written": 3, "systems_written": 2,
        },
        # The trial-wide token budget reads the usage seam each poll. A constant
        # total snapshots the baseline and never reaches the budget.
        "GET /projects/pid/usage": {"total_tokens": 1000, "by_agent": {}},
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
    assert "data-dependencies/l1" in out
    assert "poll" in out.lower()


def test_trial_executes_through_the_injected_api_and_runner(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "scaffold.py": fake_result(0, "services: 3\n"),
            "curl": fake_result(0, "200"),
            "ps -a --format json": fake_result(
                0, '{"Service": "app", "Health": "healthy"}'
            ),
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


def test_trial_api_transport_failure_is_handled_not_a_traceback(
    sample_setup, tmp_path, recording_runner, fake_result, capsys
) -> None:
    """I2: a transport failure yields a written failed record and exit 1."""
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "scaffold.py": fake_result(0, "services: 3\n"),
            "curl": fake_result(0, "200"),
            "ps -a --format json": fake_result(
                0, '{"Service": "app", "Health": "healthy"}'
            ),
        }
    )

    class ExplodingApi:
        def __call__(self, call):
            raise api.ApiError(call, 0, "connection refused")

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
        api_factory=lambda base: ExplodingApi(),
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "connection refused" in captured.err
    records = list((tmp_path / "runs" / "jetlinks-1").glob("*/trial.yaml"))
    assert len(records) == 1
    record = yaml.safe_load(records[0].read_text(encoding="utf-8"))
    assert record["terminal"] == "failed"
    assert any(
        "connection refused" in (phase.get("failure") or "")
        for phase in record["phases"]
    )


def _run_trial_cli(sample_setup, tmp_path, recording_runner, fake_result, extra_args=()):
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "scaffold.py": fake_result(0, "services: 3\n"),
            "curl": fake_result(0, "200"),
            "ps -a --format json": fake_result(
                0, '{"Service": "app", "Health": "healthy"}'
            ),
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
            *extra_args,
        ],
        runner_factory=lambda: runner,
        api_factory=lambda base: api,
    )
    records = list((tmp_path / "runs" / "jetlinks-1").glob("*/trial.yaml"))
    assert len(records) == 1
    return code, yaml.safe_load(records[0].read_text(encoding="utf-8"))


def test_trial_threads_the_setup_target_run_id_into_the_record(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    sample_setup["instances"][0]["targets"][0]["target_run_id"] = "setup-run"

    code, record = _run_trial_cli(sample_setup, tmp_path, recording_runner, fake_result)

    assert code == 0
    assert record["target_run_id"] == "setup-run"


def test_trial_cli_target_run_id_overrides_the_setup(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    sample_setup["instances"][0]["targets"][0]["target_run_id"] = "setup-run"

    code, record = _run_trial_cli(
        sample_setup,
        tmp_path,
        recording_runner,
        fake_result,
        extra_args=("--target-run-id", "cli-run"),
    )

    assert code == 0
    assert record["target_run_id"] == "cli-run"


def test_trial_rejects_a_path_unsafe_target_run_id(
    sample_setup, tmp_path, recording_runner, fake_result, capsys
) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(
        [
            "trial",
            setup_path,
            "arm-a",
            "jetlinks-1",
            "--data-root",
            str(tmp_path / "data"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--target-run-id",
            "../escape",
        ],
        runner_factory=_explode,
        api_factory=_explode,
    )

    assert code == 1
    assert "target_run_id" in capsys.readouterr().err


def test_trial_threads_the_token_budget_into_the_record(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """The setup's per-target token budget reaches the TrialConfig and record."""
    code, record = _run_trial_cli(sample_setup, tmp_path, recording_runner, fake_result)

    assert code == 0
    assert record["token_budget"] == 10


def test_trial_outcome_prints_the_token_spend(monkeypatch) -> None:
    record = SimpleNamespace(
        trial_id="t1",
        terminal="stopped",
        project_id="pid",
        phases=[
            SimpleNamespace(
                phase="hunting", status="stopped", failure=None, blocks=[], notes=[]
            )
        ],
        overshoot=None,
        cap=None,
        stop_count=None,
        final_count=None,
        token_budget=500,
        spent_tokens=600,
        spend_overshoot=100,
    )

    class _FakeTrial:
        def __init__(self, cfg, **kwargs) -> None:
            pass

        def run(self, **kwargs) -> object:
            return record

    monkeypatch.setattr(cli, "_trial_config", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(cli.trial, "Trial", _FakeTrial)
    monkeypatch.setattr(
        cli, "Orchestrator", lambda *a, **k: SimpleNamespace(up=lambda: None)
    )
    out, err = io.StringIO(), io.StringIO()

    code = cli._run_trial(
        SimpleNamespace(dry_run=False, api="http://api"),
        object(),
        cli.OrchestratorConfig(repo=Path("/repo"), instances_root=Path("/instances")),
        out,
        err,
        lambda: object(),
        lambda base: object(),
    )

    assert code == 0
    assert "spend 600 tokens (overshoot 100)" in out.getvalue()
