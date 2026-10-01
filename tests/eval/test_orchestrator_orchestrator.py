"""The orchestrator skeleton over a whole `EvalSetup` (ticket #269).

`plan()` is pure: it builds every command without a runner, so an operator can
inspect a run before it touches ssh, docker, or git. `up`/`down` gate the
eval-wide work items, then drive instances and their serial target pipelines.
"""
from __future__ import annotations

import pytest

from orchestrator import orchestrator, routing
from orchestrator.setup import parse_eval_setup
from orchestrator.workitems import WorkItemGateError


def _config(tmp_path):
    return orchestrator.OrchestratorConfig(
        repo=tmp_path / "repo", instances_root=tmp_path / "instances"
    )


def _orchestrator(sample_setup, tmp_path, *, runner=None):
    return orchestrator.Orchestrator(
        parse_eval_setup(sample_setup), _config(tmp_path), runner=runner
    )


def test_plan_builds_instance_and_target_commands_without_a_runner(
    sample_setup, tmp_path, recording_runner
) -> None:
    runner = recording_runner()
    plan = _orchestrator(sample_setup, tmp_path, runner=runner).plan()

    assert runner.calls == []
    commands = [c for step in plan for c in step.commands]
    texts = [" ".join(c.argv) for c in commands]
    assert any("worktree add" in t for t in texts)
    assert any("env_preflight.py" in t for t in texts)
    assert any("docker compose" in t for t in texts)
    assert any("scripts/targetctl up jetlinks" in t for t in texts)


def test_up_refuses_when_a_required_work_item_is_incomplete(
    sample_setup, tmp_path, recording_runner
) -> None:
    sample_setup["work_items"][0]["status"] = "incomplete"
    runner = recording_runner()

    with pytest.raises(WorkItemGateError, match="auth-bootstrap"):
        _orchestrator(sample_setup, tmp_path, runner=runner).up()

    assert runner.calls == []


def test_up_drives_the_instance_and_target(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "curl": fake_result(0, "200"),
        }
    )

    results = _orchestrator(sample_setup, tmp_path, runner=runner).up()

    (instance_result,) = results
    assert instance_result.instance_id == "arm-a"
    (target_result,) = instance_result.targets
    assert target_result.host == routing.synthetic_host("arm-a/jetlinks-1")
    assert target_result.front_url == f"http://{target_result.host}/"
    texts = runner.argv_texts
    assert any("up -d" in t for t in texts)
    assert any("scripts/targetctl up jetlinks" in t for t in texts)


def test_down_removes_targets_then_the_instance(
    sample_setup, tmp_path, recording_runner
) -> None:
    runner = recording_runner()
    # A real teardown follows a bring-up that created the worktree.
    (tmp_path / "instances" / "arm-a").mkdir(parents=True)

    _orchestrator(sample_setup, tmp_path, runner=runner).down()

    texts = runner.argv_texts
    assert any("scripts/targetctl down jetlinks" in t for t in texts)
    assert any("down -v --remove-orphans" in t for t in texts)
    assert any("worktree remove" in t for t in texts)


def test_status_reports_target_host_front_url_and_kali_aliases(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """#269: status must report the synthetic host, its front URL, and the live aliases."""
    host = routing.synthetic_host("arm-a/jetlinks-1")
    runner = recording_runner(
        routes={
            "/etc/hosts": fake_result(
                0, stdout="127.0.0.1 localhost\n10.0.0.5 t-aaaa.target\n"
            ),
        },
        default=fake_result(0, stdout="running\n"),
    )

    report = _orchestrator(sample_setup, tmp_path, runner=runner).status()

    entry = report["arm-a"]
    assert "running" in entry["stack"]
    (target,) = entry["targets"].values()
    assert target["host"] == host
    assert target["front_url"] == f"http://{host}/"
    assert target["status"].strip() == "running"
    assert entry["aliases"] == {"t-aaaa.target": "10.0.0.5"}


def test_down_is_idempotent_when_the_worktree_is_absent(
    sample_setup, tmp_path, recording_runner
) -> None:
    """#269: teardown must not fail because the instance worktree never existed."""
    runner = recording_runner()

    _orchestrator(sample_setup, tmp_path, runner=runner).down()

    texts = runner.argv_texts
    assert any("scripts/targetctl down jetlinks" in t for t in texts)
    # No compose down for a worktree that does not exist.
    assert not any("down -v --remove-orphans" in t for t in texts)


# --- SP2: the shared host-level front for local targets -----------------------


def _local_setup(instance_id="arm-a", lifecycle="image", target_id="img-1"):
    params = (
        {"image": "nginx:alpine", "port": 18080}
        if lifecycle == "image"
        else {"compose_file": "target-compose.yml", "port": 18081}
    )
    return {
        "schema_version": 1,
        "artifact_store": "/srv/eval-artifacts",
        "work_items": [
            {"name": "auth-bootstrap", "status": "complete"},
            {"name": "l1-surface", "status": "complete"},
        ],
        "instances": [
            {
                "instance_id": instance_id,
                "env_file": f"{instance_id}/.env",
                "systems": f"ph-{instance_id}",
                "targets": [
                    {
                        "target_id": target_id,
                        "start_phase": "recon",
                        "hunt_config_budget": 10,
                        "preloaded_hunting_artifacts": None,
                        "target_config": {"lifecycle": lifecycle, "params": params},
                    }
                ],
            }
        ],
    }


GATEWAY_LINE = "172.17.0.1 host.docker.internal\n"


def test_up_ensures_the_shared_front_before_a_local_target(
    tmp_path, recording_runner, fake_result
) -> None:
    runner = recording_runner(
        routes={"getent hosts": fake_result(0, GATEWAY_LINE), "curl": fake_result(0, "200")}
    )

    _orchestrator(_local_setup(), tmp_path, runner=runner).up()

    texts = runner.argv_texts
    ensure = texts[0]
    assert "docker run -d --name ph-eval-front" in ensure
    assert "--publish 80:80" in ensure
    assert "host.docker.internal:host-gateway" in ensure
    # The target's conf is added to the shared front.
    assert any("nginx -s reload" in t for t in texts)


def test_up_creates_the_front_for_a_targetctl_target(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """D45: `targetctl` is local now, so it too is fronted by the shared container."""
    runner = recording_runner(
        routes={
            "scripts/targetctl up": fake_result(0, "UI: http://127.0.0.1:32768/\n"),
            "getent hosts": fake_result(0, "172.17.0.1 host.docker.internal\n"),
            "curl": fake_result(0, "200"),
        }
    )

    _orchestrator(sample_setup, tmp_path, runner=runner).up()

    texts = runner.argv_texts
    assert any("docker run -d --name ph-eval-front" in t for t in texts)
    assert any("ph-eval-front" in t and "nginx -s reload" in t for t in texts)


def test_plan_lists_the_front_container_for_local_targets(
    tmp_path, recording_runner
) -> None:
    plan = _orchestrator(_local_setup(), tmp_path).plan()

    labels = [step.label for step in plan]
    assert any("front container" in label for label in labels)
    commands = " ".join(
        " ".join(c.argv) for step in plan for c in step.commands
    )
    assert "ph-eval-front" in commands


def test_down_removes_the_shared_front_after_local_targets(
    tmp_path, recording_runner
) -> None:
    runner = recording_runner()

    errors = _orchestrator(_local_setup(), tmp_path, runner=runner).down()

    assert errors == []
    assert "docker rm -f ph-eval-front" in runner.argv_texts[-1]


def test_down_continues_after_one_target_failure(
    sample_setup, tmp_path, recording_runner, fake_result
) -> None:
    """SP3: one target's failure must not strand the rest of the teardown."""
    (tmp_path / "instances" / "arm-a").mkdir(parents=True)
    setup = sample_setup
    second = {
        "target_id": "t-2",
        "start_phase": "recon",
        "hunt_config_budget": 10,
        "preloaded_hunting_artifacts": None,
        "target_config": {
            "lifecycle": "targetctl",
            "params": {"target": "siyucms"},
        },
    }
    setup["instances"][0]["targets"].append(second)
    h2 = routing.synthetic_host("arm-a/t-2")
    conf2 = str(routing.front_conf_path("/etc/nginx/conf.d", h2))
    runner = recording_runner(routes={conf2: fake_result(1, stderr="front stuck")})

    errors = _orchestrator(setup, tmp_path, runner=runner).down()

    assert len(errors) == 1
    assert "arm-a/t-2" in errors[0].label
    # The first target and the instance stack still tore down.
    texts = runner.argv_texts
    assert any("scripts/targetctl down jetlinks" in t for t in texts)
    assert any("down -v --remove-orphans" in t for t in texts)
