"""Target lifecycle strategies (ticket #269, D9/D2, operator directive).

One interface (`plan_up`/`up`/`plan_down`/`down`/`plan_status`/`status`) behind
three strategies:

  * `targetctl` - the WebExploitBench lifecycle on the REMOTE workshop host,
    deployed over ssh and fronted by that host's nginx on the synthetic Host;
  * `image` and `compose` - local pullable containers, published on the host and
    aliased to `host.docker.internal` (the Docker host gateway) in the instance
    kali, so a loopback-only publish would be unreachable.

Every command goes through the injected runner; the readiness probe is a read
whose failure is fatal (an unreachable target is never a silent success).
"""
from __future__ import annotations

import shlex

import pytest

from orchestrator import instances, routing, setup as setup_mod
from orchestrator.targets import (
    TargetError,
    TargetNotReadyError,
    TargetUpResult,
    build_strategy,
    targetctl,
)
from orchestrator.targets.compose import ComposeTargetError
from orchestrator.targets.image import ImageError

GATEWAY_LINE = "172.17.0.1 host.docker.internal\n"


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


def test_targetctl_down_front_failure_is_best_effort_and_clears_alias(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP3: a failed front removal must not abort the alias clear."""
    strategy, _ = _strategy(tmp_path)
    runner = recording_runner(
        routes={"sudo rm -f": fake_result(1, stderr="nginx conf busy")}
    )

    with pytest.raises(targetctl.TargetctlError, match="front removal"):
        strategy.down(runner)

    texts = runner.argv_texts
    assert any("scripts/targetctl down jetlinks" in t for t in texts)
    # The alias was still cleared.
    assert any("awk" in t for t in texts)


def test_targetctl_status_reads_targetctl_ps(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _strategy(tmp_path)
    runner = recording_runner(default=fake_result(0, stdout="jetlinks running"))

    assert "jetlinks" in strategy.status(runner)


def test_targetctl_quotes_interpolated_config(tmp_path) -> None:
    """S5: remote_dir/repo_url/target are operator config and must be quoted."""
    run = setup_mod.TargetRun(
        target_id="t-1",
        target_config=setup_mod.TargetConfig(
            lifecycle="targetctl",
            params={
                "target": "a b",
                "remote_dir": "/opt/a b",
                "repo_url": "https://example.invalid/a b.git",
            },
        ),
    )
    instance = setup_mod.Instance(instance_id="arm-a", targets=(run,))
    paths = instances.instance_paths(
        instance, tmp_path / "instances", repo=tmp_path / "repo", branch="eval"
    )
    strategy = build_strategy(run, paths, env={}, sleep=_noop)

    plan = strategy.plan_up()
    checkout = " ".join(plan[0].argv)
    targetctl_up = " ".join(
        " ".join(c.argv) for c in plan if "targetctl" in " ".join(c.argv)
    )

    assert shlex.quote("/opt/a b") in checkout
    assert shlex.quote("https://example.invalid/a b.git") in checkout
    assert shlex.quote("a b") in targetctl_up


def test_routing_constants_are_single_sourced() -> None:
    """S1/S2: the strategies share routing's constants, not private copies."""
    from orchestrator.targets import compose, image

    assert image.LOOPBACK == routing.LOOPBACK
    assert image.HOST_GATEWAY == routing.HOST_GATEWAY
    assert compose.LOOPBACK == routing.LOOPBACK
    assert compose.HOST_GATEWAY == routing.HOST_GATEWAY


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
    runner = recording_runner(
        routes={"getent hosts": fake_result(0, GATEWAY_LINE), "curl": fake_result(0, "200")}
    )

    result = strategy.up(runner)

    assert result.backend == "http://127.0.0.1:18080"
    # The front URL is a bare domain on the standard web port (SP2).
    assert result.front_url == f"http://{result.host}/"
    assert ":" not in result.front_url[len("http://") :]
    run_argv = runner.calls[0].argv
    run_text = " ".join(run_argv)
    assert "docker run" in run_text
    assert "nginx:alpine" in run_text
    # The publish must bind an interface the kali alias can reach through
    # host.docker.internal: docker's default all-interfaces publish, never
    # loopback-only (the bridge gateway cannot reach a 127.0.0.1 bind).
    publish = run_argv[run_argv.index("--publish") + 1]
    assert publish == "18080:80"
    assert "127.0.0.1" not in publish
    # The shared front gets a conf proxying the synthetic host to the published port.
    conf_calls = [c for c in runner.calls if "nginx -s reload" in " ".join(c.argv)]
    assert conf_calls and f"server_name {strategy.host};" in (conf_calls[0].stdin or "")

    down_runner = recording_runner()
    strategy.down(down_runner)
    down_texts = down_runner.argv_texts
    assert any("docker rm -f" in t for t in down_texts)
    # The front conf is removed and nginx reloaded; the alias is cleared.
    assert any("rm -f" in t and "nginx -s reload" in t for t in down_texts)
    assert any("awk" in t for t in down_texts)

    status_runner = recording_runner(default=fake_result(0, stdout="running\n"))
    assert strategy.status(status_runner).strip() == "running"


def test_image_plan_publishes_on_a_gateway_reachable_interface(tmp_path) -> None:
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="image",
        params={"image": "nginx:alpine", "port": 18080, "internal_port": 8080},
    )

    run_cmd = strategy.plan_up()[0]
    publish = run_cmd.argv[run_cmd.argv.index("--publish") + 1]

    assert publish == "18080:8080"
    assert "127.0.0.1" not in publish


def test_image_aliases_kali_to_a_numeric_gateway_address(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP1/#269: kali is not on the host network; the alias must be numeric."""
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="image",
        params={"image": "nginx:alpine", "port": 18080},
    )
    runner = recording_runner(
        routes={"getent hosts": fake_result(0, GATEWAY_LINE), "curl": fake_result(0, "200")}
    )

    result = strategy.up(runner)

    alias_text = " ".join(runner.calls[-1].argv)
    # /etc/hosts has no resolver in its address column: write the resolved IP.
    assert f"172.17.0.1 {result.host}" in alias_text
    assert f"host.docker.internal {result.host}" not in alias_text
    assert f"127.0.0.1 {result.host}" not in alias_text
    # The gateway is resolved inside kali via the injected runner.
    assert any("getent hosts host.docker.internal" in t for t in runner.argv_texts)
    # The host-side readiness probe still runs on loopback.
    probe_text = " ".join(
        " ".join(command.argv)
        for command in runner.calls
        if "curl" in " ".join(command.argv)
    )
    assert "127.0.0.1:18080" in probe_text


def test_image_gateway_resolution_failure_is_fatal(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP1: a failure to resolve the gateway must fail loudly, never write a name."""
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="image",
        params={"image": "nginx:alpine", "port": 18080},
    )
    runner = recording_runner(
        routes={
            "getent hosts": fake_result(1, stderr="Name or service not known"),
            "curl": fake_result(0, "200"),
        }
    )

    with pytest.raises(ImageError, match="host.docker.internal"):
        strategy.up(runner)


def test_image_non_numeric_gateway_output_is_fatal(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="image",
        params={"image": "nginx:alpine", "port": 18080},
    )
    runner = recording_runner(
        routes={
            "getent hosts": fake_result(0, "host.docker.internal\n"),
            "curl": fake_result(0, "200"),
        }
    )

    with pytest.raises(ImageError, match="numeric address"):
        strategy.up(runner)


def test_image_down_treats_an_absent_container_as_success(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP3: teardown after a failed/never-started run must not abort."""
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="image",
        params={"image": "nginx:alpine", "port": 18080},
    )
    runner = recording_runner(
        routes={
            "docker rm -f": fake_result(
                1, stderr="Error response from daemon: No such container: gone"
            )
        }
    )

    strategy.down(runner)  # no raise

    # The alias is cleared even though the container was absent.
    assert any("docker exec" in t for t in runner.argv_texts)
    assert any("awk" in t for t in runner.argv_texts)


def test_image_down_reports_a_real_removal_failure_but_still_clears(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP3: a genuine removal failure is reported after cleanup, not instead of it."""
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="image",
        params={"image": "nginx:alpine", "port": 18080},
    )
    runner = recording_runner(
        routes={"docker rm -f": fake_result(1, stderr="permission denied")}
    )

    with pytest.raises(ImageError, match="permission denied"):
        strategy.down(runner)

    # Cleanup ran before the error was raised.
    assert any("awk" in t for t in runner.argv_texts)


# --- compose (local pullable stack) ------------------------------------------


def test_compose_up_down_status(tmp_path, recording_runner, fake_result) -> None:
    strategy, paths = _strategy(
        tmp_path,
        lifecycle="compose",
        params={"compose_file": "target-compose.yml", "port": 18081},
    )
    runner = recording_runner(
        routes={"getent hosts": fake_result(0, GATEWAY_LINE), "curl": fake_result(0, "200")}
    )

    result = strategy.up(runner)

    assert result.backend == "http://127.0.0.1:18081"
    assert result.front_url == f"http://{result.host}/"
    up_text = " ".join(runner.calls[0].argv)
    assert "docker compose" in up_text
    assert "target-compose.yml" in up_text
    assert up_text.endswith("up -d")
    conf_calls = [c for c in runner.calls if "nginx -s reload" in " ".join(c.argv)]
    assert conf_calls and f"server_name {strategy.host};" in (conf_calls[0].stdin or "")

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


def test_compose_aliases_kali_to_a_numeric_gateway_address(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP1/#269: kali is not on the host network; the alias must be numeric."""
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="compose",
        params={"compose_file": "target-compose.yml", "port": 18081},
    )
    runner = recording_runner(
        routes={"getent hosts": fake_result(0, GATEWAY_LINE), "curl": fake_result(0, "200")}
    )

    result = strategy.up(runner)

    alias_text = " ".join(runner.calls[-1].argv)
    assert f"172.17.0.1 {result.host}" in alias_text
    assert f"host.docker.internal {result.host}" not in alias_text
    assert f"127.0.0.1 {result.host}" not in alias_text


def test_compose_gateway_resolution_failure_is_fatal(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="compose",
        params={"compose_file": "target-compose.yml", "port": 18081},
    )
    runner = recording_runner(
        routes={
            "getent hosts": fake_result(1, stderr="server misbehaving"),
            "curl": fake_result(0, "200"),
        }
    )

    with pytest.raises(ComposeTargetError, match="host.docker.internal"):
        strategy.up(runner)


def test_compose_down_reports_failure_but_still_clears(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _strategy(
        tmp_path,
        lifecycle="compose",
        params={"compose_file": "target-compose.yml", "port": 18081},
    )
    runner = recording_runner(
        routes={"down -v --remove-orphans": fake_result(1, stderr="compose boom")}
    )

    with pytest.raises(ComposeTargetError, match="compose boom"):
        strategy.down(runner)

    assert any("awk" in t for t in runner.argv_texts)
