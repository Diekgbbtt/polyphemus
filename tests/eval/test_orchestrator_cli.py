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
            "rev-parse HEAD": fake_result(0, "d" * 40 + "\n"),
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
    # The worktree survives the stack teardown (its data root is preserved).
    assert not any("worktree remove" in t for t in runner.argv_texts)
    assert (tmp_path / "instances" / "arm-a").is_dir()


def test_worktree_remove_is_the_operator_only_removal(
    sample_setup, tmp_path, recording_runner
) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner()
    (tmp_path / "instances" / "arm-a").mkdir(parents=True)

    code = cli.main(
        [
            "worktree-remove",
            setup_path,
            "--instances-root",
            str(tmp_path / "instances"),
        ],
        runner_factory=_SpyFactory(runner),
    )

    assert code == 0
    assert any("worktree remove" in t for t in runner.argv_texts)


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
        # The recon entry chains recon -> analysis -> hunting, so the analysis
        # status route must settle (`drained` is the analysis terminal vocabulary;
        # a `complete` status is never terminal there, so it would poll forever).
        # It must precede the generic `GET /projects` needle, which the substring
        # matcher would otherwise answer with a status-less body.
        "GET /projects/pid/analysis/r1": {"status": "drained", "analysis_run_id": "a1"},
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
        # capped total snapshots the baseline and never reaches the budget.
        "GET /projects/pid/usage": {"total_tokens": 1000, "generated_tokens": 1000,
                                    "by_agent": {}},
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
            "rev-parse HEAD": fake_result(0, "d" * 40 + "\n"),
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
            "rev-parse HEAD": fake_result(0, "d" * 40 + "\n"),
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


def _run_trial_cli(sample_setup, tmp_path, recording_runner, fake_result, extra_args=(),
                   head_sha="a" * 40):
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "rev-parse HEAD": fake_result(0, f"{head_sha}\n"),
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
        token_spectrum=None,
    )

    class _FakeTrial:
        def __init__(self, cfg, **kwargs) -> None:
            pass

        def run(self, **kwargs) -> object:
            return record

    monkeypatch.setattr(cli, "_trial_config", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(cli, "_with_version_identity", lambda cfg, *a, **k: cfg)
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


def test_trial_outcome_prints_the_per_agent_token_spectrum(monkeypatch) -> None:
    # #349: the terminal prints each agent's flat spectrum after the spend line.
    record = SimpleNamespace(
        trial_id="t1",
        terminal="stopped",
        project_id="pid",
        phases=[
            SimpleNamespace(
                phase="hunting", status="stopped", failure=None, blocks=[], notes=[]
            )
        ],
        token_budget=500,
        spent_tokens=600,
        spend_overshoot=100,
        token_spectrum={
            "mechanism_typist": {
                "visible": 100,
                "reasoning": 900,
                "cached_input": 19000,
                "uncached_input": 43100,
                "generated": 1000,
                "total": 62100,
                "capped": 44100,
                "calls": 24,
                "cache_detail_omitted": 3,
            }
        },
    )

    class _FakeTrial:
        def __init__(self, cfg, **kwargs) -> None:
            pass

        def run(self, **kwargs) -> object:
            return record

    monkeypatch.setattr(cli, "_trial_config", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(cli, "_with_version_identity", lambda cfg, *a, **k: cfg)
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
    line = out.getvalue()
    assert "spectrum mechanism_typist:" in line
    assert "cached_input 19000" in line
    assert "uncached_input 43100" in line
    assert "cache_detail_omitted 3" in line


# --- the trial record names the commit the stack loads (D32) ------------------


def test_the_trial_starter_stamps_the_instance_head(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """The starter - not an operator env var - writes the version identity: the
    commit HEAD points to in the worktree whose sources the containers mount."""
    head = "1f0c8a2b3c4d5e6f708192a3b4c5d6e7f8091a2b"

    code, record = _run_trial_cli(
        sample_setup, tmp_path, recording_runner, fake_result, head_sha=head
    )

    assert code == 0
    assert record["eval_sha"] == head


def test_the_starter_reads_head_from_the_instance_worktree(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """The read targets `<instances_root>/<instance_id>`, never the repo checkout:
    a detached instance worktree is the code its compose bind-mounts."""
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "rev-parse HEAD": fake_result(0, "a" * 40 + "\n"),
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "scaffold.py": fake_result(0, "services: 3\n"),
            "curl": fake_result(0, "200"),
            "ps -a --format json": fake_result(
                0, '{"Service": "app", "Health": "healthy"}'
            ),
        }
    )

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
        api_factory=lambda base: _FakeApi(_trial_routes()),
    )

    assert code == 0
    worktree = str(tmp_path / "instances" / "arm-a")
    reads = [text for text in runner.argv_texts if "rev-parse HEAD" in text]
    assert reads == [f"git -C {worktree} rev-parse HEAD"]


def test_a_declared_eval_sha_never_overrides_head(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """An operator-declared sha is a cross-check, not a source: the record names
    the loaded commit, and the disagreement is recorded instead of swallowed."""
    head = "b" * 40
    declared = "c" * 40

    code, record = _run_trial_cli(
        sample_setup,
        tmp_path,
        recording_runner,
        fake_result,
        head_sha=head,
        extra_args=("--eval-sha", declared),
    )

    assert code == 0
    assert record["eval_sha"] == head
    assert any(declared in note and head in note for note in record["notes"])


def test_an_unreadable_head_stops_the_trial_before_it_starts(
    sample_setup, tmp_path, recording_runner, fake_result, capsys
) -> None:
    """A record must never carry a null identity: the starter fails loud."""
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={"rev-parse HEAD": fake_result(128, "", "fatal: not a git repository")}
    )

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
        api_factory=lambda base: _FakeApi(_trial_routes()),
    )

    assert code == 1
    assert "worktree" in capsys.readouterr().err
    assert list((tmp_path / "runs").glob("*/**/trial.yaml")) == []


def test_the_trial_plan_names_the_identity_read(
    sample_setup, tmp_path, capsys
) -> None:
    setup_path = _write_setup(tmp_path, sample_setup)

    code = cli.main(
        ["trial", setup_path, "arm-a", "jetlinks-1", "--dry-run"],
        runner_factory=_explode,
        api_factory=_explode,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "rev-parse HEAD" in out


def test_the_record_marks_a_dirty_instance_worktree(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """HEAD names the base commit only: a tracked edit in the loaded tree must be
    visible on the record, so a reader never mistakes the SHA for the bytes."""
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "rev-parse HEAD": fake_result(0, "f" * 40 + "\n"),
            "status --porcelain": fake_result(0, " M src/polymerhus/app/auth/tool.py\n"),
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "scaffold.py": fake_result(0, "services: 3\n"),
            "curl": fake_result(0, "200"),
            "ps -a --format json": fake_result(
                0, '{"Service": "app", "Health": "healthy"}'
            ),
        }
    )

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
        api_factory=lambda base: _FakeApi(_trial_routes()),
    )

    assert code == 0
    record = yaml.safe_load(
        next((tmp_path / "runs" / "jetlinks-1").glob("*/trial.yaml")).read_text(
            encoding="utf-8")
    )
    assert record["eval_sha"] == "f" * 40
    assert record["worktree_dirty"] is True


def test_a_standalone_trial_creates_the_worktree_before_reading_its_head(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """`up`'s first step is idempotent and creates the tree; a `trial` run
    without a prior `up` must therefore still be able to read its HEAD."""
    sample_setup["instances"][0]["targets"][0]["target_config"]["target_seed"] = "t.test"
    setup_path = _write_setup(tmp_path, sample_setup)
    runner = recording_runner(
        routes={
            "rev-parse HEAD": fake_result(0, "9" * 40 + "\n"),
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "scaffold.py": fake_result(0, "services: 3\n"),
            "curl": fake_result(0, "200"),
            "ps -a --format json": fake_result(
                0, '{"Service": "app", "Health": "healthy"}'
            ),
        }
    )

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
        api_factory=lambda base: _FakeApi(_trial_routes()),
    )

    assert code == 0
    texts = runner.argv_texts
    worktree_add = next(i for i, text in enumerate(texts) if "worktree add" in text)
    head_read = next(i for i, text in enumerate(texts) if "rev-parse HEAD" in text)
    assert worktree_add < head_read
