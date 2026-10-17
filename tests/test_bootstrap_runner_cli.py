"""Unit tier: the external-bootstrap runner, part 6 - the CLI and the entry point.

`plan | run | resume | status` (the architecture doc, section 2) over the run
config: the CLI is the only place that wires the production seams (the ssh
environment driver, the real validator gate, the `opencode api` harness), so the
tests replace exactly those three builders and let everything else run for real -
the config loader, the wrapper builders over the repo's own versioned carriers,
the orchestration loop, the state file, and the per-turn logs.

No network, no model, no docker, no ssh.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_path(rel: str) -> None:
    path = str(REPO_ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


# The entry point's own sys.path contract (run_external_bootstrap.py).
_on_path("tools/bootstrap")
_on_path("eval")
_on_path("src")

from orchestrator.commands import Command, CommandResult  # noqa: E402

from runner import cli, state as state_mod  # noqa: E402
from runner.config import EnvironmentSection, load_config, load_resolved  # noqa: E402
from runner.env import ContainerFact, Observation  # noqa: E402
from runner.gates import AUTH_ONLY, FULL, GateResult  # noqa: E402
from runner.harness import ModelRef, TurnResult, is_retryable  # noqa: E402

EXAMPLE_CONFIG = REPO_ROOT / "tools/bootstrap/run.example.yaml"
EVAL_TARGETS = (
    "dataease",
    "comfyui",
    "geoserver",
    "jetlinks",
    "phpbb",
    "prestashop",
    "siyucms",
    "white-jotter",
)


# --- the three replaced production builders --------------------------------


class FakeHarness:
    """A scripted harness: records the wrappers, answers with canned turns.

    `session_model` is the resume-time liveness probe: the CLI asks it for every
    target it is about to continue, and a session in `gone` answers None.
    """

    def __init__(self, *, gone=()) -> None:
        self.created: list = []
        self.prompts: list[tuple[str, str]] = []
        self.interrupts: list[str] = []
        self.turns: list[object] = []
        self.gone = set(gone)
        self.probed: list[str] = []

    def create_session(self, spec) -> str:
        self.created.append(spec)
        return spec.session_id

    def prompt(self, session_id: str, text: str) -> str:
        self.prompts.append((session_id, text))
        return str(len(self.prompts))

    def wait_terminal(self, session_id: str, timeout_s: float) -> TurnResult:
        answer = self.turns.pop(0) if self.turns else _turn(session_id, "succeeded")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def interrupt(self, session_id: str) -> CommandResult:
        self.interrupts.append(session_id)
        return CommandResult(0, "", "")

    def session_model(self, session_id: str):
        self.probed.append(session_id)
        if session_id in self.gone:
            return None
        return {"providerID": "opencode", "id": "deepseek-v4.1-flash-free", "variant": "high"}


def _turn(session_id="ses_bt_r1_a_creator", outcome="succeeded", error=""):
    return TurnResult(
        session_id=session_id,
        outcome=outcome,
        ok=outcome == "succeeded" and not error,
        retryable=is_retryable(error) if error else False,
        error=error,
        model={"id": "deepseek-v4.1-flash-free", "providerID": "opencode", "variant": "high"},
        messages=(
            {"id": "m1", "type": "assistant", "content": [{"text": "phase report"}]},
            {"id": "m2", "type": "idle", "outcome": outcome},
        ),
    )


class FakeEnv:
    """The deployment simulation the loop tests use, plus its command log."""

    def __init__(self, *, ready: bool = False, containers: bool = True, residual=()) -> None:
        self.ready = ready
        self.commands: list[tuple[str, str]] = []
        self._containers = containers
        self._deployed = False
        # Containers that survive `down` (the leftover-teardown case).
        self.residual = list(residual)

    def _observation(self, target: str) -> Observation:
        if self.ready or self._deployed:
            return Observation(
                target=target,
                containers=(
                    ContainerFact(f"web_{target}-app-1", "app", "running", "healthy", 0),
                ),
                url="http://0.0.0.0:48287/",
                http_status="200",
            )
        if self.residual:
            return Observation(
                target=target,
                containers=tuple(
                    ContainerFact(name, "app", "running", "healthy", 0)
                    for name in self.residual
                ),
                url=None,
                http_status="000",
            )
        return Observation(target=target, containers=(), url=None, http_status="000")

    def up(self, target: str) -> CommandResult:
        self.commands.append(("up", target))
        self._deployed = True
        return CommandResult(0, "", "")

    def down(self, target: str) -> CommandResult:
        self.commands.append(("down", target))
        self._deployed = False
        return CommandResult(0, "", "")

    def observe(self, target: str) -> Observation:
        self.commands.append(("observe", target))
        return self._observation(target)

    def supported_containers(self) -> bool:
        return self._containers

    def lifecycle_hints(self, target: str) -> tuple[str, ...]:
        return (
            f"ssh srv /root/wb ps {target}",
            f"ssh srv /root/wb up {target}",
            f"ssh srv /root/wb down {target}",
        )


class ScriptedGate:
    """A gate whose every answer is scripted (OK unless the script says red)."""

    def __init__(self, script=None) -> None:
        self.script = list(script or [])
        self.calls: list[tuple[str, str]] = []

    def run(self, target: str, mode: str) -> GateResult:
        self.calls.append((target, mode))
        answer = self.script.pop(0) if self.script else True
        ok, output = answer if isinstance(answer, tuple) else (bool(answer), "OK")
        return GateResult(
            ok=ok,
            output=output,
            command=("python3", "validate_data_dependencies.py", "--staging", "s", target),
            mode=mode,
        )


@pytest.fixture
def wired(monkeypatch):
    """Replace the three production builders and hand the fakes back."""
    harness, env, gate = FakeHarness(), FakeEnv(), ScriptedGate()
    monkeypatch.setattr(cli, "build_harness", lambda config: harness)
    monkeypatch.setattr(cli, "build_env", lambda config: env)
    monkeypatch.setattr(cli, "build_gate", lambda config: gate)
    return {"harness": harness, "env": env, "gate": gate}


# --- fixtures ---------------------------------------------------------------


def _config_yaml(tmp_path: Path, *, targets=("a", "b"), **overrides) -> Path:
    paths = {
        "kbs": str(REPO_ROOT / "eval/data/webexploitbench"),
        "staging": str(REPO_ROOT / "eval/data-dependencies"),
        "prompts": str(REPO_ROOT / "tools/bootstrap/prompts"),
        "contract": str(REPO_ROOT / "tools/bootstrap/DATA-DEPENDENCIES.md"),
        "meta_skill": str(REPO_ROOT / "skills/meta/authn-skill-writing/SKILL.md"),
        "validator": str(REPO_ROOT / "tools/bootstrap/validate_data_dependencies.py"),
    }
    run = {"id": "r1", "targets": list(targets), "worktree": str(tmp_path)}
    environment = {
        "driver": "ssh",
        "ssh": "srv",
        "web_root": "/root/WebExploitBench",
        "public_host": "203.0.113.9",
    }
    for key, value in overrides.items():
        if key in {"run", "environment", "paths"}:
            continue
        run[key] = value
    body = {"run": run, "environment": environment, "paths": paths}
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return path


def _rundir(tmp_path: Path, run_id: str = "r1") -> Path:
    return tmp_path / ".bootstrap-runs" / run_id


def _planted_state(tmp_path: Path, cfg: Path, *, phases=None, digest=None) -> Path:
    """A previous run's rundir: the resolved snapshot plus a planted state."""
    config = load_config(cfg, repo_root=REPO_ROOT)
    rundir = _rundir(tmp_path)
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / "config.resolved.yaml").write_text(
        yaml.safe_dump(config.resolved(), sort_keys=False), encoding="utf-8"
    )
    state = state_mod.new_state(
        config.run.id,
        config_digest=config.digest if digest is None else digest,
        targets=config.run.targets,
    )
    for target, phase, read, gate in phases or ():
        record = state.target(target)
        record.phase(phase).read = read
        record.phase(phase).gate = gate
    # A target with every phase complete carries its terminal status, as a real
    # finished run would have written it.
    for target in config.run.targets:
        if state.first_incomplete_phase(target) is None:
            state.target(target).status = state_mod.DONE
    state.save(rundir)
    return rundir


# --- plan -------------------------------------------------------------------


def test_plan_prints_the_targets_sessions_lifecycle_and_gate_commands(
    tmp_path, wired, capsys
):
    cfg = _config_yaml(tmp_path)
    out = capsys.readouterr()
    code = cli.main(["plan", "--config", str(cfg)])
    printed = capsys.readouterr().out
    assert out.out == ""
    assert code == 0
    assert "ses_bt_r1_a_creator" in printed
    assert "ses_bt_r1_b_creator" in printed
    assert "ssh srv /root/wb ps a" in printed
    assert "ssh srv /root/wb up b" in printed
    assert "--auth-only" in printed
    assert "validate_data_dependencies.py" in printed
    # `<target_dir>` is the LOCAL KB output dir; the checkout root on the target
    # host is its own fact.
    assert "webexploitbench/b (local KB output)" in printed
    assert "web root:   /root/WebExploitBench (on the target host)" in printed
    assert "nothing was created" in printed
    # A plan is a read-only preflight: no target was observed and no run
    # directory was created.
    assert wired["env"].commands == []
    assert not _rundir(tmp_path).exists()


def test_plan_obey_targets_filter_and_a_rundir_override(tmp_path, wired, capsys):
    cfg = _config_yaml(tmp_path)
    code = cli.main(
        ["plan", "--config", str(cfg), "--targets", "b", "--rundir", str(tmp_path / "elsewhere")]
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert "ses_bt_r1_b_creator" in printed
    assert "ses_bt_r1_a_creator" not in printed
    assert str(tmp_path / "elsewhere") in printed


def test_plan_reports_a_missing_carrier_instead_of_planning_a_dead_run(
    tmp_path, wired, capsys
):
    cfg = _config_yaml(tmp_path)
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    raw["paths"]["validator"] = str(tmp_path / "missing-validator.py")
    cfg.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    code = cli.main(["plan", "--config", str(cfg)])
    captured = capsys.readouterr()
    assert code == 2
    assert "missing-validator.py" in captured.err
    assert not _rundir(tmp_path).exists()


# --- run --------------------------------------------------------------------


def test_run_drives_both_phases_and_writes_the_state_and_the_snapshot(
    tmp_path, wired, capsys
):
    cfg = _config_yaml(tmp_path, targets=("a",))
    code = cli.main(["run", "--config", str(cfg)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "done" in printed

    rundir = _rundir(tmp_path)
    assert (rundir / "state.json").is_file()
    snapshot = rundir / "config.resolved.yaml"
    assert snapshot.is_file()

    original = load_config(cfg, repo_root=REPO_ROOT)
    assert load_resolved(snapshot).digest == original.digest

    state = state_mod.RunState.load(rundir)
    assert state.target("a").status == state_mod.DONE
    assert state.target("a").phase("authn").gate == state_mod.DONE
    assert state.target("a").phase("l1").gate == state_mod.DONE
    assert state.target("a").lifecycle.verified_teardown is True

    prompts = [text for session, text in wired["harness"].prompts]
    assert len(prompts) == 2
    assert all("target `a`" in text for text in prompts)
    assert "authentication bootstrapper" in prompts[0]
    assert "L1-surface producer" in prompts[1]
    # The wrapper carries the URL the run discovered, host rewritten for the mac.
    assert "203.0.113.9:48287" in prompts[0]
    # ... and the validator command whose mode matches the phase: auth_only
    # validates the staging project dir BY NAME, the full gate the KB dir.
    staging = str(REPO_ROOT / "eval/data-dependencies")
    kb_dir = str(REPO_ROOT / "eval/data/webexploitbench/a")
    assert f"validate_data_dependencies.py --auth-only --staging {staging} a" in prompts[0]
    assert f"validate_data_dependencies.py --staging {staging} {kb_dir}" in prompts[1]

    log = rundir / "a" / "authn" / "01-dispatch.log"
    assert log.is_file()
    body = log.read_text(encoding="utf-8")
    assert "authentication bootstrapper" in body
    assert "### turn" in body
    assert "phase report" in body


def test_run_refuses_a_rundir_that_already_holds_a_run(tmp_path, wired, capsys):
    cfg = _config_yaml(tmp_path, targets=("a",))
    assert cli.main(["run", "--config", str(cfg)]) == 0
    first_prompts = len(wired["harness"].prompts)
    code = cli.main(["run", "--config", str(cfg)])
    captured = capsys.readouterr()
    assert code == 2
    assert "resume" in captured.err
    assert len(wired["harness"].prompts) == first_prompts


def test_run_without_lifecycle_never_deploys_or_tears_down(tmp_path, monkeypatch, capsys):
    env = FakeEnv(ready=True)
    monkeypatch.setattr(cli, "build_env", lambda config: env)
    monkeypatch.setattr(cli, "build_harness", lambda config: FakeHarness())
    monkeypatch.setattr(cli, "build_gate", lambda config: ScriptedGate())
    cfg = _config_yaml(tmp_path, targets=("a",))
    assert cli.main(["run", "--config", str(cfg), "--no-lifecycle"]) == 0
    assert [kind for kind, _ in env.commands if kind in {"up", "down"}] == []
    state = state_mod.RunState.load(_rundir(tmp_path))
    assert state.target("a").status == state_mod.DONE


# --- status -----------------------------------------------------------------


def test_status_prints_the_table_from_the_rundir(tmp_path, wired, capsys):
    cfg = _config_yaml(tmp_path, targets=("a", "b"))
    assert cli.main(["run", "--config", str(cfg)]) == 0
    capsys.readouterr()
    code = cli.main(["status", "--rundir", str(_rundir(tmp_path))])
    printed = capsys.readouterr().out
    assert code == 0
    assert "ses_bt_r1_a_creator" in printed
    for word in ("target", "status", "authn", "l1", "teardown"):
        assert word in printed
    assert printed.count("done") >= 4


def test_status_exits_one_when_a_target_failed_and_two_without_a_run(tmp_path, capsys):
    cfg = _config_yaml(tmp_path, targets=("a",))
    rundir = _planted_state(
        tmp_path,
        cfg,
        phases=(("a", "authn", state_mod.DONE, state_mod.FAILED),),
    )
    state = state_mod.RunState.load(rundir)
    state.target("a").status = state_mod.FAILED
    state.save(rundir)
    assert cli.main(["status", "--rundir", str(rundir)]) == 1
    assert cli.main(["status", "--rundir", str(tmp_path / "nope")]) == 2
    captured = capsys.readouterr()
    assert "no run state" in captured.err


# --- resume -----------------------------------------------------------------


def test_resume_continues_at_the_first_incomplete_phase_and_probes_sessions(
    tmp_path, wired, capsys
):
    cfg = _config_yaml(tmp_path, targets=("a", "b"))
    rundir = _planted_state(
        tmp_path,
        cfg,
        phases=(
            ("a", "authn", state_mod.DONE, state_mod.DONE),
            ("a", "l1", state_mod.DONE, state_mod.DONE),
        ),
    )
    code = cli.main(["resume", "--rundir", str(rundir)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "resum" in printed.lower()
    # Only the incomplete target's session is probed, and only target b runs.
    assert wired["harness"].probed == ["ses_bt_r1_b_creator"]
    sessions = [session for session, _ in wired["harness"].prompts]
    assert sessions == ["ses_bt_r1_b_creator", "ses_bt_r1_b_creator"]
    assert all("target `b`" in text for _, text in wired["harness"].prompts)
    state = state_mod.RunState.load(rundir)
    assert state.target("a").status == state_mod.DONE
    assert state.target("b").status == state_mod.DONE


def test_resume_reports_a_gone_session_and_recreates_it(tmp_path, wired, capsys):
    cfg = _config_yaml(tmp_path, targets=("a",))
    rundir = _planted_state(tmp_path, cfg)
    wired["harness"].gone = {"ses_bt_r1_a_creator"}
    code = cli.main(["resume", "--rundir", str(rundir)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "not live" in printed
    assert "ses_bt_r1_a_creator" in [spec.session_id for spec in wired["harness"].created]


def test_resume_warns_loudly_when_the_config_drifted_from_the_state(
    tmp_path, wired, capsys
):
    cfg = _config_yaml(tmp_path, targets=("a",))
    rundir = _planted_state(tmp_path, cfg, digest="not-the-same-digest")
    code = cli.main(["resume", "--rundir", str(rundir)])
    captured = capsys.readouterr()
    assert code == 0
    assert "drift" in captured.err.lower()
    assert "not-the-same-digest" in captured.err


def test_resume_needs_a_snapshot_or_a_config(tmp_path, wired, capsys):
    rundir = _rundir(tmp_path)
    rundir.mkdir(parents=True)
    (rundir / "state.json").write_text(
        json.dumps({"run": {"id": "r1", "status": "interrupted"}, "targets": {}}),
        encoding="utf-8",
    )
    code = cli.main(["resume", "--rundir", str(rundir)])
    captured = capsys.readouterr()
    assert code == 2
    assert "--config" in captured.err


# --- the shipped example config ---------------------------------------------


def _run_dir_snapshot() -> set[str]:
    """Every path under the repo's default run root, relative and sorted.

    A plan must create nothing and touch nothing - including a live run's own
    directory, which legitimately exists while a regeneration is in flight.
    """
    root = REPO_ROOT / ".bootstrap-runs"
    if not root.exists():
        return set()
    return {str(p.relative_to(REPO_ROOT)) for p in root.rglob("*")}


def test_the_example_config_plans_the_eight_eval_server_targets(capsys):
    before = _run_dir_snapshot()
    code = cli.main(["plan", "--config", str(EXAMPLE_CONFIG)])
    printed = capsys.readouterr().out
    assert code == 0
    for target in EVAL_TARGETS:
        assert f"ses_bt_w2_6_{target.replace('-', '_')}_creator" in printed
    assert "eval-server-polyphemus" in printed
    assert "46.224.225.245" in printed
    assert _run_dir_snapshot() == before


def test_the_entry_script_plans_the_example_config_from_any_cwd(tmp_path):
    """The shipped entry point wires sys.path itself and needs no particular cwd."""
    before = _run_dir_snapshot()
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools/bootstrap/run_external_bootstrap.py"),
            "plan",
            "--config",
            str(EXAMPLE_CONFIG),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "plan only: nothing was created" in completed.stdout
    assert "ses_bt_w2_6_dataease_creator" in completed.stdout
    assert _run_dir_snapshot() == before


def test_the_example_config_resolves_to_the_pinned_policy():
    config = load_config(EXAMPLE_CONFIG, repo_root=REPO_ROOT)
    assert config.run.targets == EVAL_TARGETS
    assert config.run.agent == "data-dep-worker"
    assert config.run.model == ModelRef("opencode-go", "deepseek-v4.1-flash", "high")
    assert config.environment.driver == "ssh"
    assert config.environment.ssh == "eval-server-polyphemus"
    assert config.environment.targetctl == "/root/wb"
    assert config.paths.kbs == REPO_ROOT / "eval/data/webexploitbench"
    assert config.paths.staging == REPO_ROOT / "eval/data-dependencies"
    assert AUTH_ONLY == "auth_only" and FULL == "full"
