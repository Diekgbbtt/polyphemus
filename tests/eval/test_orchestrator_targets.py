"""Target lifecycle strategies (ticket #269, D9/D2, operator directive).

One interface (`plan_up`/`up`/`plan_down`/`down`/`plan_status`/`status`) behind
three strategies:

  * `targetctl` - the WebExploitBench lifecycle on the REMOTE workshop host,
    deployed over ssh and fronted by that host's nginx on the synthetic Host;
  * `image` and `compose` - local pullable containers, fronted by a loopback
    publish and aliased to `127.0.0.1` in the instance kali.

Every command goes through the injected runner; the readiness probe is a read
whose failure is fatal (an unreachable target is never a silent success).
"""
from __future__ import annotations

import pytest

from orchestrator import instances, routing, setup as setup_mod
from orchestrator.targets import (
    TargetNotReadyError,
    TargetUpResult,
    build_strategy,
    targetctl,
)


def _noop(_seconds: float) -> None:
    pass


def _strategy(tmp_path, *, lifecycle="targetctl", params=None):
    if params is None:
        params = {"target": "jetlinks"} if lifecycle == "targetctl" else {}
    run = setup_mod.TargetRun(
        target_id="t-1",
        target_config=setup_mod.TargetConfig(lifecycle=lifecycle, params=params),
    )
    instance = setup_mod.Instance(instance_id="arm-a", targets=(run,))
    paths = instances.instance_paths(
        instance, tmp_path / "instances", repo=tmp_path / "repo", branch="eval"
    )
    strategy = build_strategy(run, paths, env={}, sleep=_noop)
    return strategy, paths


# --- shared interface ---------------------------------------------------------


def test_all_strategies_expose_the_same_interface(tmp_path) -> None:
    for lifecycle, params in (
        ("targetctl", {"target": "jetlinks"}),
        ("image", {"image": "nginx:alpine", "port": 18080}),
        ("compose", {"compose_file": "target-compose.yml", "port": 18081}),
    ):
        strategy, _ = _strategy(tmp_path, lifecycle=lifecycle, params=params)
        for name in ("plan_up", "up", "plan_down", "down", "plan_status", "status"):
            assert callable(getattr(strategy, name)), (lifecycle, name)


# --- targetctl (remote workshop host) ----------------------------------------


def test_targetctl_up_deploys_remotely_and_registers_routing(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, paths = _strategy(tmp_path)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(
                0, "Accessible URLs:\nUI: http://127.0.0.1:32768/\n"
            ),
            "hostname -I": fake_result(0, "10.0.0.5 \n"),
            "curl": fake_result(0, "200"),
        }
    )

    result = strategy.up(runner)

    assert isinstance(result, TargetUpResult)
    assert result.host == routing.synthetic_host("arm-a/t-1")
    assert result.front_url == f"http://{result.host}/"
    assert "32768" in result.backend
    assert result.ready is True

    texts = runner.argv_texts
    assert any("worktree" not in t and "test -d" in t and "git clone" in t for t in texts)
    assert any("scripts/targetctl build jetlinks" in t for t in texts)
    assert any("scripts/targetctl up jetlinks" in t for t in texts)
    assert any(f"server_name {result.host};" in (c.stdin or "") for c in runner.calls)
    assert any("docker exec" in t for t in texts)


def test_targetctl_plan_up_lists_every_command_without_a_runner(
    tmp_path, recording_runner
) -> None:
    strategy, _ = _strategy(tmp_path)
    runner = recording_runner()

    plan = strategy.plan_up()

    assert plan  # non-empty
    assert runner.calls == []  # planning never touches a runner
    assert any("scripts/targetctl up" in " ".join(c.argv) for c in plan)
    assert any("server_name" in (c.stdin or "") for c in plan)


def test_targetctl_readiness_failure_is_fatal(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _strategy(tmp_path)
    strategy.ready_retries = 2
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(
                0, "UI: http://127.0.0.1:32768/\n"
            ),
            "hostname -I": fake_result(0, "10.0.0.5 \n"),
            "curl": fake_result(0, "502"),
        }
    )

    with pytest.raises(TargetNotReadyError, match=strategy.host):
        strategy.up(runner)


def test_targetctl_up_without_a_url_is_fatal(tmp_path, recording_runner, fake_result) -> None:
    strategy, _ = _strategy(tmp_path)
    runner = recording_runner(
        routes={"scripts/targetctl up": fake_result(0, "no url here\n")}
    )

    with pytest.raises(targetctl.TargetctlError, match="URL"):
        strategy.up(runner)


def test_targetctl_down_removes_target_front_and_alias(
    tmp_path, recording_runner
) -> None:
    strategy, _ = _strategy(tmp_path)
    runner = recording_runner()

    strategy.down(runner)

    texts = runner.argv_texts
    assert any("scripts/targetctl down jetlinks" in t for t in texts)
    assert any("sudo rm -f" in t for t in texts)
    assert any("docker exec" in t for t in texts)


def test_targetctl_status_reads_targetctl_ps(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _strategy(tmp_path)
    runner = recording_runner(default=fake_result(0, stdout="jetlinks running"))

    assert "jetlinks" in strategy.status(runner)


def test_parse_targetctl_output_prefers_ui_url() -> None:
    out = "Accessible URLs:\n  UI: http://0.0.0.0:32768/\n  docs: http://0.0.0.0:32768/doc.html\n"

    assert targetctl.parse_targetctl_url(out) == "http://0.0.0.0:32768/"


# --- image (local pullable container) ----------------------------------------


def test_image_up_down_status(tmp_path, recording_runner, fake_result) -> None:
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="image",
        params={"image": "nginx:alpine", "port": 18080, "internal_port": 80},
    )
    runner = recording_runner(routes={"curl": fake_result(0, "200")})

    result = strategy.up(runner)

    assert result.backend == "http://127.0.0.1:18080"
    assert result.front_url == f"http://{result.host}/"
    run_text = " ".join(runner.calls[0].argv)
    assert "docker run" in run_text
    assert "nginx:alpine" in run_text
    assert "127.0.0.1:18080:80" in run_text

    down_runner = recording_runner()
    strategy.down(down_runner)
    assert any("docker rm -f" in t for t in down_runner.argv_texts)

    status_runner = recording_runner(default=fake_result(0, stdout="running\n"))
    assert strategy.status(status_runner).strip() == "running"


# --- compose (local pullable stack) ------------------------------------------


def test_compose_up_down_status(tmp_path, recording_runner, fake_result) -> None:
    strategy, paths = _strategy(
        tmp_path,
        lifecycle="compose",
        params={"compose_file": "target-compose.yml", "port": 18081},
    )
    runner = recording_runner(routes={"curl": fake_result(0, "200")})

    result = strategy.up(runner)

    assert result.backend == "http://127.0.0.1:18081"
    up_text = " ".join(runner.calls[0].argv)
    assert "docker compose" in up_text
    assert "target-compose.yml" in up_text
    assert up_text.endswith("up -d")

    down_runner = recording_runner()
    strategy.down(down_runner)
    assert any(t.endswith("down -v --remove-orphans") for t in down_runner.argv_texts)

    status_runner = recording_runner(default=fake_result(0, stdout="running\n"))
    assert strategy.status(status_runner).strip() == "running"


def test_compose_plan_up_uses_its_own_project(tmp_path) -> None:
    strategy, paths = _strategy(
        tmp_path,
        lifecycle="compose",
        params={"compose_file": "target-compose.yml", "port": 18081},
    )

    plan = strategy.plan_up()
    up_text = " ".join(plan[0].argv)

    assert "ph-target-" in up_text
    assert paths.compose_project not in up_text
