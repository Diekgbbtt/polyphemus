"""The full-chain target lifecycle e2e (opt-in, live).

Drives the eval chain over every WebExploitBench target in the setup's order.
For each target, `orchestrator next-target` tears down the previous target,
provisions the next from the dataset helper (store -> pull -> build, D48),
brings the stack up with the dataset's excluded services cut (D49: the
`evaluator`), verifies bounded readiness, and points the shared front.

Only the eval orchestrator agent is absent: the test invokes the same CLI tool
the agent calls, so every other layer is real - docker, `scripts/targetctl`,
the shared `ph-eval-front`, the numeric kali alias, the bounded readiness poll,
and reclaim. Nothing about the target stack is stubbed.

Prerequisites (the live eval host):
- docker, the deployed eval checkout, and the instance worktree;
- all target images already present locally (pre-pulled from the registry);
- the instance stack (`ph-<short>`) running, so kali aliasing can resolve.

Opt-in: set ``EVAL_CHAIN_E2E=1``. Run on the eval host:

    EVAL_CHAIN_E2E=1 PYTHONPATH=eval python3 -m pytest \
        tests/e2e/test_eval_chain_full_live.py -q

Subset for a quick check (comma-separated target ids):

    EVAL_CHAIN_TARGETS=comfyui-1,siyucms-1 EVAL_CHAIN_E2E=1 ...
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

DEFAULT_REPO = "/opt/eval-platform-model"
DEFAULT_INSTANCES_ROOT = "/opt/polymerhus-dev/eval/instances"
DEFAULT_BRANCH = "eval"
DEFAULT_WEB_DIR = "/root/WebExploitBench"
DEFAULT_PLATFORM = "linux/amd64"
DEFAULT_INSTANCE = "eval-server-1"
DEFAULT_SETUP = "eval/setups/webexploitbench-chain.yaml"
# One target up + bounded readiness + teardown can be slow under emulation.
STEP_TIMEOUT_S = 900


@dataclass(frozen=True)
class LiveConfig:
    repo: Path
    setup: Path
    instances_root: Path
    branch: str
    web_dir: str
    platform: str
    instance: str
    target_ids: tuple[str, ...]


def _live_config() -> LiveConfig:
    """The live environment, or a pytest skip naming the missing prerequisite."""
    if os.environ.get("EVAL_CHAIN_E2E") != "1":
        pytest.skip("set EVAL_CHAIN_E2E=1 to run the live full-chain e2e")
    if shutil.which("docker") is None:
        pytest.skip("docker is not available")

    repo = Path(os.environ.get("EVAL_REPO", DEFAULT_REPO))
    setup = Path(os.environ.get("EVAL_SETUP", repo / DEFAULT_SETUP))
    if not (repo / "eval" / "orchestrator").is_dir():
        pytest.skip(f"eval checkout not found at {repo}")
    if not setup.is_file():
        pytest.skip(f"setup not found at {setup}")

    instances_root = Path(os.environ.get("EVAL_INSTANCES_ROOT", DEFAULT_INSTANCES_ROOT))
    branch = os.environ.get("EVAL_BRANCH", DEFAULT_BRANCH)
    web_dir = os.environ.get("EVAL_WEB_DIR", DEFAULT_WEB_DIR)
    platform = os.environ.get("EVAL_TARGET_PLATFORM", DEFAULT_PLATFORM)
    instance = os.environ.get("EVAL_INSTANCE", DEFAULT_INSTANCE)

    data = yaml.safe_load(setup.read_text(encoding="utf-8"))
    inst = next(
        (i for i in data.get("instances", []) if i.get("instance_id") == instance),
        None,
    )
    if inst is None:
        pytest.skip(f"instance {instance!r} not in {setup}")
    target_ids = tuple(t["target_id"] for t in inst.get("targets", []))
    if not target_ids:
        pytest.skip(f"instance {instance!r} declares no targets")

    selected = os.environ.get("EVAL_CHAIN_TARGETS")
    if selected:
        wanted = {t.strip() for t in selected.split(",") if t.strip()}
        target_ids = tuple(t for t in target_ids if t in wanted)

    worktree = instances_root / instance
    if not worktree.is_dir():
        pytest.skip(f"instance worktree not found at {worktree}")

    return LiveConfig(
        repo=repo,
        setup=setup,
        instances_root=instances_root,
        branch=branch,
        web_dir=web_dir,
        platform=platform,
        instance=instance,
        target_ids=target_ids,
    )


def _orchestrator_env(cfg: LiveConfig) -> dict[str, str]:
    """The RUN env. The exclusion is NOT set here: the dataset declares it and
    the strategy passes it, so this also verifies the native wiring (D49)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = "eval"
    env["EVAL_REPO"] = str(cfg.repo)
    env["EVAL_INSTANCES_ROOT"] = str(cfg.instances_root)
    env["EVAL_DATA_ROOT"] = str(cfg.instances_root / cfg.instance / "data")
    env["EVAL_BRANCH"] = cfg.branch
    env["EVAL_WEB_DIR"] = cfg.web_dir
    env["EVAL_TARGET_PLATFORM"] = cfg.platform
    env.pop("TARGETCTL_EXCLUDE_SERVICES", None)
    return env


def _next_target(cfg: LiveConfig, target_id: str) -> subprocess.CompletedProcess[str]:
    argv = [
        sys.executable,
        "-m",
        "orchestrator",
        "next-target",
        str(cfg.setup),
        "--repo",
        str(cfg.repo),
        "--instances-root",
        str(cfg.instances_root),
        "--branch",
        cfg.branch,
        "--instance",
        cfg.instance,
        "--target",
        target_id,
    ]
    return subprocess.run(
        argv,
        cwd=cfg.repo,
        env=_orchestrator_env(cfg),
        capture_output=True,
        text=True,
        timeout=STEP_TIMEOUT_S,
    )


def _running_containers() -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _target_stack_prefix(target_id: str) -> str:
    """The container-name prefix `scripts/targetctl` gives a target's stack."""
    target = target_id.rsplit("-", 1)[0]
    return "web_" + "".join(c if c.isalnum() else "_" for c in target.lower())


def _front_code(host: str) -> str:
    out = subprocess.run(
        [
            "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
            "--max-time", "15", "-H", f"Host: {host}", "http://127.0.0.1/",
        ],
        capture_output=True,
        text=True,
    ).stdout
    return out.strip()


def test_full_chain_target_lifecycle_live() -> None:
    cfg = _live_config()
    active: str | None = None
    try:
        for target_id in cfg.target_ids:
            proc = _next_target(cfg, target_id)
            assert proc.returncode == 0, (
                f"next-target {target_id} failed (rc={proc.returncode}):\n{proc.stderr}"
            )
            step = json.loads(proc.stdout)

            assert step["target_id"] == target_id
            assert step["health"] == "compose ready", step
            assert step["images"], f"{target_id} bound no canonical image"
            assert all("evaluator" not in img for img in step["images"]), step
            assert step["front_url"].startswith("http://"), step

            # Exactly the current target's stack runs; the previous is torn down.
            prefix = _target_stack_prefix(target_id)
            containers = _running_containers()
            target_stacks = {n.split("-", 1)[0] for n in containers if n.startswith("web_")}
            assert target_stacks == {prefix}, (
                f"{target_id}: expected only {prefix} up, saw {sorted(target_stacks)}"
            )
            assert not any("evaluator" in n for n in containers), containers

            # The shared front reaches the target through the synthetic Host.
            host = step["front_url"].removeprefix("http://").rstrip("/")
            assert _front_code(host) != "000", f"{host} is not reachable through the front"

            active = target_id
    finally:
        if active is not None:
            # Leave no target stack behind: tear the active target down directly.
            subprocess.run(
                [f"{cfg.web_dir}/scripts/targetctl", "down", active.rsplit("-", 1)[0]],
                env={**os.environ, "DOCKER_DEFAULT_PLATFORM": cfg.platform,
                     "TARGETCTL_EXCLUDE_SERVICES": "evaluator"},
                capture_output=True,
                text=True,
            )
