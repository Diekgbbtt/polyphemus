"""Target lifecycle strategies (ticket #269, D9/D2, spec #301).

One interface (`plan_up`/`up`/`plan_down`/`down`/`plan_status`/`status`, plus
`await_ready`/`provision`/`reclaim`) behind three strategies:

  * `targetctl` - the WebExploitBench lifecycle on the LOCAL eval host (D45),
    run locally and fronted by the shared container nginx on the synthetic Host;
  * `image` and `compose` - local pullable containers, published on the host and
    aliased to `host.docker.internal` (the Docker host gateway) in the instance
    kali, so a loopback-only publish would be unreachable.

The bring-up data is resolved from a `TargetConfiguration` and its
`BenchmarkDataset` helper (spec #301): the checkout/repo from the dataset, the
compose/port/platform/reclaimable from the config. Every command goes through the
injected runner; `up` never blocks on health, and `await_ready` verifies it under
the helper's bounded plan (an unreachable target is never a silent success).
"""
from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from orchestrator import docker, instances, routing
from orchestrator.dataset import BenchmarkDataset
from orchestrator.datasets.base import DatasetHelper
from orchestrator.setup import Instance, TargetConfig, TargetRun
from orchestrator.target_config import TargetConfiguration
from orchestrator.targets import (
    TargetNotReadyError,
    TargetUpResult,
    build_strategy,
    targetctl,
)
from orchestrator.targets.compose import ComposeTargetError
from orchestrator.targets.image import ImageError

GATEWAY_LINE = "172.17.0.1 host.docker.internal\n"

COMPOSE = """\
name: pb_mock
services:
  web:
    build:
      context: ./setup_files
      dockerfile: environment/Dockerfile
    image: pentestbench-jetlinks:web
"""


def _noop(_seconds: float) -> None:
    pass


def _dataset(
    tmp_path,
    *,
    dataset_id="mock",
    repo="https://example.invalid/repo.git",
    platform_root="",
):
    return BenchmarkDataset(
        id=dataset_id,
        repo=repo,
        platform_root=platform_root,
        targets=("jetlinks", "img", "stack", "a b"),
        eval_root=tmp_path / "eval",
    )


def _strategy(tmp_path, *, runner, config, dataset=None, env=None):
    dataset = dataset or _dataset(tmp_path)
    run = TargetRun(
        target_key=f"{dataset.id}/{config.target}",
        target_id="t-1",
        target_config=TargetConfig(),
    )
    instance = Instance(instance_id="arm-a", targets=(run,))
    paths = instances.instance_paths(
        instance, tmp_path / "instances", repo=tmp_path / "repo", branch="eval"
    )
    strategy = build_strategy(
        config,
        dataset,
        DatasetHelper(dataset),
        paths,
        run,
        env={} if env is None else env,
        sleep=_noop,
    )
    return strategy, paths


def _targetctl(tmp_path, *, target="jetlinks", **kwargs):
    kwargs.setdefault("compose", "docker-compose.yml")
    kwargs.setdefault("images", (f"ph/mock/{target}:web",))
    return _strategy(
        tmp_path,
        runner="targetctl",
        config=TargetConfiguration(target=target, runner="targetctl", **kwargs),
    )


def _image(tmp_path, **kwargs):
    kwargs.setdefault("image", "nginx:alpine")
    kwargs.setdefault("port", 18080)
    kwargs.setdefault("images", ("ph/mock/img:web",))
    return _strategy(
        tmp_path, runner="image", config=TargetConfiguration(target="img", runner="image", **kwargs)
    )


def _compose(tmp_path, **kwargs):
    kwargs.setdefault("compose", "target-compose.yml")
    kwargs.setdefault("port", 18081)
    kwargs.setdefault("images", ("ph/mock/stack:web",))
    return _strategy(
        tmp_path,
        runner="compose",
        config=TargetConfiguration(target="stack", runner="compose", **kwargs),
    )


def _write_compose(tmp_path, target, name="docker-compose.yml"):
    bank = tmp_path / "platform" / "mock" / target
    bank.mkdir(parents=True, exist_ok=True)
    (bank / name).write_text(COMPOSE, encoding="utf-8")
    return str(tmp_path / "platform" / "mock")


# --- shared interface ---------------------------------------------------------


def test_all_strategies_expose_the_same_interface(tmp_path) -> None:
    strategies = [_targetctl(tmp_path)[0], _image(tmp_path)[0], _compose(tmp_path)[0]]
    for strategy in strategies:
        for name in (
            "plan_up",
            "up",
            "plan_down",
            "down",
            "plan_status",
            "status",
            "await_ready",
            "provision",
            "reclaim",
        ):
            assert callable(getattr(strategy, name))


# --- targetctl (local eval host) ---------------------------------------------


def test_targetctl_up_deploys_locally_and_registers_routing(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _targetctl(tmp_path)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(
                0, "Accessible URLs:\nUI: http://127.0.0.1:32768/\n"
            ),
            "getent hosts": fake_result(0, GATEWAY_LINE),
        }
    )

    result = strategy.up(runner)

    assert isinstance(result, TargetUpResult)
    assert result.host == routing.synthetic_host("arm-a/t-1")
    assert result.front_url == f"http://{result.host}/"
    assert "32768" in result.backend
    assert result.ready is True

    texts = runner.argv_texts
    # The checkout and the deploy run locally; no ssh anywhere.
    assert not any(t.startswith("ssh") or " ssh " in t for t in texts)
    assert any("test -d" in t and "git clone" in t for t in texts)
    assert any("scripts/targetctl build jetlinks" in t for t in texts)
    assert any("scripts/targetctl up jetlinks" in t for t in texts)
    # The front conf is added to the shared container, not a host nginx.
    assert any("ph-eval-front" in t and "nginx -s reload" in t for t in texts)
    assert any(f"server_name {result.host};" in (c.stdin or "") for c in runner.calls)
    assert any("docker exec" in t for t in texts)


def test_targetctl_commands_select_the_amd64_platform(tmp_path) -> None:
    """D46: an aarch64 host emulates the amd64 target via the platform env."""
    strategy, _ = _targetctl(tmp_path)

    for command in strategy.plan_up():
        if (command.description or "").startswith("targetctl"):
            assert command.env == {"DOCKER_DEFAULT_PLATFORM": "linux/amd64"}


def test_targetctl_plan_up_lists_every_command_without_a_runner(
    tmp_path, recording_runner
) -> None:
    strategy, _ = _targetctl(tmp_path)
    runner = recording_runner()

    plan = strategy.plan_up()

    assert plan  # non-empty
    assert runner.calls == []  # planning never touches a runner
    assert any("scripts/targetctl up" in " ".join(c.argv) for c in plan)
    assert any("server_name" in (c.stdin or "") for c in plan)


def test_targetctl_readiness_is_bounded_and_fatal_on_failure(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _targetctl(tmp_path)
    strategy.ready_retries = 2
    runner = recording_runner(
        routes={"ps --format json": fake_result(0, '[{"State": "exited"}]\n')}
    )

    with pytest.raises(TargetNotReadyError, match=strategy.host):
        strategy.await_ready(runner)

    # The bounded window: exactly `ready_retries` probes, never an unbounded wait.
    assert len(runner.calls) == 2


def test_targetctl_readiness_succeeds_on_a_healthy_service(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _targetctl(tmp_path)
    runner = recording_runner(
        routes={"ps --format json": fake_result(0, '[{"Health": "healthy"}]\n')}
    )

    assert "ready" in strategy.await_ready(runner)


def test_targetctl_up_without_a_url_is_fatal(tmp_path, recording_runner, fake_result) -> None:
    strategy, _ = _targetctl(tmp_path)
    runner = recording_runner(
        routes={"scripts/targetctl up": fake_result(0, "no url here\n")}
    )

    with pytest.raises(targetctl.TargetctlError, match="URL"):
        strategy.up(runner)


def test_targetctl_gateway_resolution_failure_is_fatal(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP1: no numeric gateway means abort before any alias command is issued."""
    strategy, _ = _targetctl(tmp_path)
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(1, stderr="Name or service not known"),
        }
    )

    with pytest.raises(targetctl.TargetctlError, match="host.docker.internal"):
        strategy.up(runner)

    # The up path aborted before touching kali: no alias write.
    assert not any("alias" in (c.description or "") for c in runner.calls)


def test_targetctl_down_removes_target_front_and_alias(
    tmp_path, recording_runner
) -> None:
    strategy, _ = _targetctl(tmp_path)
    runner = recording_runner()

    strategy.down(runner)

    texts = runner.argv_texts
    assert any("scripts/targetctl down jetlinks" in t for t in texts)
    # The front conf is removed from the shared container, not a host nginx.
    assert any("ph-eval-front" in t and "rm -f" in t for t in texts)
    assert any("docker exec" in t for t in texts)


def test_targetctl_down_front_failure_is_best_effort_and_clears_alias(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP3: a failed front removal must not abort the alias clear."""
    strategy, _ = _targetctl(tmp_path)
    conf = str(routing.front_conf_path("/etc/nginx/conf.d", strategy.host))
    runner = recording_runner(routes={conf: fake_result(1, stderr="nginx conf busy")})

    with pytest.raises(targetctl.TargetctlError, match="front removal"):
        strategy.down(runner)

    texts = runner.argv_texts
    assert any("scripts/targetctl down jetlinks" in t for t in texts)
    # The alias was still cleared.
    assert any("awk" in t for t in texts)


def test_targetctl_status_reads_targetctl_ps(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _targetctl(tmp_path)
    runner = recording_runner(default=fake_result(0, stdout="jetlinks running"))

    assert "jetlinks" in strategy.status(runner)


def test_targetctl_quotes_interpolated_config(tmp_path, recording_runner) -> None:
    """S5: web_dir/repo_url are interpolated into a shell line and must be quoted."""
    dataset = _dataset(
        tmp_path, repo="https://example.invalid/a b.git", platform_root="/opt/a b"
    )
    config = TargetConfiguration(
        target="a b", runner="targetctl", compose="c.yml", images=("ph/mock/a b:web",)
    )
    strategy, _ = _strategy(tmp_path, runner="targetctl", config=config, dataset=dataset)

    plan = strategy.plan_up()
    checkout = " ".join(plan[0].argv)
    targetctl_cmds = [
        c for c in plan if (c.description or "").startswith("targetctl")
    ]

    assert shlex.quote("/opt/a b") in checkout
    assert shlex.quote("https://example.invalid/a b.git") in checkout
    # The targetctl argv is an argv list: the target stays one unquoted element.
    assert any("a b" in c.argv for c in targetctl_cmds)


def test_targetctl_expands_a_tilde_platform_root(tmp_path) -> None:
    """The checkout quotes the path and the argv never sees a shell, so `~` must
    be expanded before either is built."""
    dataset = _dataset(tmp_path, platform_root="~/w")
    config = TargetConfiguration(
        target="jetlinks", runner="targetctl", compose="c.yml", images=("ph/mock/jetlinks:web",)
    )
    strategy, _ = _strategy(tmp_path, runner="targetctl", config=config, dataset=dataset)

    home = str(Path.home())
    assert strategy.web_dir == f"{home}/w"
    checkout = " ".join(strategy.plan_up()[0].argv)
    assert home in checkout and "~" not in checkout
    assert strategy.plan_status()[0].argv[0].startswith(home)


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


# --- targetctl provision / reclaim -------------------------------------------


def test_targetctl_provision_builds_and_binds_canonical_tags(
    tmp_path, recording_runner, fake_result
) -> None:
    platform_root = _write_compose(tmp_path, "jetlinks")
    dataset = _dataset(tmp_path, platform_root=platform_root)
    config = TargetConfiguration(
        target="jetlinks", runner="targetctl", compose="docker-compose.yml"
    )
    strategy, _ = _strategy(tmp_path, runner="targetctl", config=config, dataset=dataset)
    runner = recording_runner(
        routes={"image inspect": fake_result(1, stderr="No such image")}
    )

    outcomes = strategy.provision(runner)

    assert [(o.tag, o.source) for o in outcomes] == [
        ("ph/mock/jetlinks:web", docker.BUILD)
    ]
    texts = runner.argv_texts
    assert any("scripts/targetctl build jetlinks" in t for t in texts)
    assert "docker tag pentestbench-jetlinks:web ph/mock/jetlinks:web" in texts


def test_targetctl_provision_pulls_and_binds_when_declared(
    tmp_path, recording_runner, fake_result
) -> None:
    config = TargetConfiguration(
        target="jetlinks",
        runner="targetctl",
        compose="docker-compose.yml",
        images=("ph/mock/jetlinks:web",),
        pull={"ph/mock/jetlinks:web": "reg/web:latest"},
    )
    strategy, _ = _strategy(tmp_path, runner="targetctl", config=config)
    runner = recording_runner(
        {
            "reg/web:latest": fake_result(0, stdout="sha256:x\n"),
            "image inspect": fake_result(1, stderr="No such image"),
            "docker pull": fake_result(0),
        }
    )

    outcomes = strategy.provision(runner)

    assert [(o.tag, o.source, o.reference) for o in outcomes] == [
        ("ph/mock/jetlinks:web", docker.PULL, "reg/web:latest")
    ]
    assert "docker tag reg/web:latest ph/mock/jetlinks:web" in runner.argv_texts


def test_targetctl_reclaim_is_gated_on_reclaimable(tmp_path, recording_runner) -> None:
    kept, _ = _targetctl(tmp_path, reclaimable=False)
    runner = recording_runner()
    assert kept.reclaim(runner) == ()
    assert runner.calls == []

    reclaimed, _ = _targetctl(tmp_path, reclaimable=True)
    runner2 = recording_runner()
    assert reclaimed.reclaim(runner2) == ("rm ph/mock/jetlinks:web",)


# --- image (local pullable container) ----------------------------------------


def test_image_up_down_status(tmp_path, recording_runner, fake_result) -> None:
    strategy, _ = _image(tmp_path)
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

    # Readiness is a separate, bounded step and probes the published port.
    assert "ready" in strategy.await_ready(runner)
    assert any("127.0.0.1:18080" in t for t in runner.argv_texts)

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
    strategy, _ = _image(tmp_path, internal_port=8080)

    run_cmd = strategy.plan_up()[0]
    publish = run_cmd.argv[run_cmd.argv.index("--publish") + 1]

    assert publish == "18080:8080"
    assert "127.0.0.1" not in publish


def test_image_aliases_kali_to_a_numeric_gateway_address(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP1/#269: kali is not on the host network; the alias must be numeric."""
    strategy, _ = _image(tmp_path)
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

    strategy.await_ready(runner)
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
    strategy, _ = _image(tmp_path)
    runner = recording_runner(
        routes={"getent hosts": fake_result(1, stderr="Name or service not known")}
    )

    with pytest.raises(ImageError, match="host.docker.internal"):
        strategy.up(runner)


def test_image_non_numeric_gateway_output_is_fatal(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _image(tmp_path)
    runner = recording_runner(
        routes={"getent hosts": fake_result(0, "host.docker.internal\n")}
    )

    with pytest.raises(ImageError, match="numeric address"):
        strategy.up(runner)


def test_image_down_treats_an_absent_container_as_success(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP3: teardown after a failed/never-started run must not abort."""
    strategy, _ = _image(tmp_path)
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
    strategy, _ = _image(tmp_path)
    runner = recording_runner(
        routes={"docker rm -f": fake_result(1, stderr="permission denied")}
    )

    with pytest.raises(ImageError, match="permission denied"):
        strategy.down(runner)

    # Cleanup ran before the error was raised.
    assert any("awk" in t for t in runner.argv_texts)


def test_image_provision_pulls_and_binds(tmp_path, recording_runner, fake_result) -> None:
    strategy, _ = _image(
        tmp_path,
        pull={"ph/mock/img:web": "reg/img:latest"},
    )
    runner = recording_runner(
        {
            "reg/img:latest": fake_result(0, stdout="sha256:x\n"),
            "image inspect": fake_result(1, stderr="No such image"),
            "docker pull": fake_result(0),
        }
    )

    outcomes = strategy.provision(runner)

    assert [(o.tag, o.source) for o in outcomes] == [("ph/mock/img:web", docker.PULL)]
    assert "docker tag reg/img:latest ph/mock/img:web" in runner.argv_texts


# --- compose (local pullable stack) ------------------------------------------


def test_compose_up_down_status(tmp_path, recording_runner, fake_result) -> None:
    strategy, _ = _compose(tmp_path)
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
    strategy, paths = _compose(tmp_path)

    plan = strategy.plan_up()
    up_text = " ".join(plan[0].argv)

    assert "ph-target-" in up_text
    assert paths.compose_project not in up_text


def test_compose_aliases_kali_to_a_numeric_gateway_address(
    tmp_path, recording_runner, fake_result
) -> None:
    """SP1/#269: kali is not on the host network; the alias must be numeric."""
    strategy, _ = _compose(tmp_path)
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
    strategy, _ = _compose(tmp_path)
    runner = recording_runner(
        routes={"getent hosts": fake_result(1, stderr="server misbehaving")}
    )

    with pytest.raises(ComposeTargetError, match="host.docker.internal"):
        strategy.up(runner)


def test_compose_down_reports_failure_but_still_clears(
    tmp_path, recording_runner, fake_result
) -> None:
    strategy, _ = _compose(tmp_path)
    runner = recording_runner(
        routes={"down -v --remove-orphans": fake_result(1, stderr="compose boom")}
    )

    with pytest.raises(ComposeTargetError, match="compose boom"):
        strategy.down(runner)

    assert any("awk" in t for t in runner.argv_texts)


def test_compose_provision_builds_and_binds_canonical_tags(
    tmp_path, recording_runner, fake_result
) -> None:
    platform_root = _write_compose(tmp_path, "stack", name="target-compose.yml")
    dataset = _dataset(tmp_path, platform_root=platform_root)
    config = TargetConfiguration(
        target="stack", runner="compose", compose="target-compose.yml", port=18081
    )
    strategy, _ = _strategy(tmp_path, runner="compose", config=config, dataset=dataset)
    runner = recording_runner(
        routes={"image inspect": fake_result(1, stderr="No such image")}
    )

    outcomes = strategy.provision(runner)

    assert [(o.tag, o.source) for o in outcomes] == [("ph/mock/stack:web", docker.BUILD)]
    texts = runner.argv_texts
    assert any("docker compose" in t and t.endswith("build") for t in texts)
    assert "docker tag pentestbench-jetlinks:web ph/mock/stack:web" in texts


def test_compose_reclaim_is_gated_on_reclaimable(tmp_path, recording_runner) -> None:
    kept, _ = _compose(tmp_path, reclaimable=False)
    runner = recording_runner()
    assert kept.reclaim(runner) == ()
    assert runner.calls == []

    reclaimed, _ = _compose(tmp_path, reclaimable=True)
    runner2 = recording_runner()
    assert reclaimed.reclaim(runner2) == ("rm ph/mock/stack:web",)
